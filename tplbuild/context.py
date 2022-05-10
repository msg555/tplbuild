import functools
import io
import os.path
import re
import stat
import tarfile
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import hashing
from .exceptions import TplBuildContextException, TplBuildException


@functools.lru_cache(maxsize=2**16)
def _hash_file(path: str) -> str:
    """
    Hash the passed file, cache the result.
    """
    hsh = hashing.HASHER()
    with open(path, "rb") as fdata:
        while data := fdata.read(2**16):
            hsh.update(data)
    return hsh.hexdigest()


def _create_pattern_part(
    path_pat: str, *, allow_double_star: bool = True
) -> Tuple[str, bool]:
    """
    Returns (regex_pattern, simple) tuple where `regex_pattern` is a regex that
    recognizes the passed pattern and `simple` indicates if the pattern is a
    "simple" pattern, i.e. matching only a single literal.

    `path_pat` is to be interpretted as described in
    https://pkg.go.dev/path/filepath#Match except that "**" should match any
    number of directories.

    Raises a ValueError if path_pat is malformed.
    """
    assert os.path.sep not in path_pat
    if path_pat == "**" and allow_double_star:
        # Match any number of directories
        return ".*", False

    result = [re.escape(os.path.sep)]
    simple = True

    i = 0
    while i < len(path_pat):
        ch = path_pat[i]
        i += 1

        if ch == "\\":
            if i == len(path_pat):
                raise ValueError("Trailing escape character")
            result.append(re.escape(path_pat[i]))
            i += 1
        elif ch in "*?":
            simple = False
            result.append(f"[^{os.path.sep}]{ch}")
        elif ch == "[":
            simple = False
            range_start = None
            cclass_empty = True
            char_avail = False
            result.append("[")

            # Check for character class negation
            if i < len(path_pat) and path_pat[i] == "^":
                result.append("^")
                i += 1

            while True:
                if i == len(path_pat):
                    raise ValueError("Unclosed character class")

                ch = path_pat[i]
                i += 1

                if ch == "\\":
                    if i == len(path_pat):
                        raise ValueError("Trailing escape character")
                    ch = path_pat[i]
                    i += 1
                elif ch == "]":
                    if range_start is not None:
                        raise ValueError("Unclosed character range")
                    if cclass_empty:
                        raise ValueError("Empty character class")
                    break
                elif ch == "-":
                    if not char_avail:
                        raise ValueError("Unexpected '-' in character class")
                    range_start = result[-1]
                    result.append("-")
                    char_avail = False
                    continue

                if range_start is not None:
                    if ord(range_start) > ord(ch):
                        raise ValueError("Invalid character range")
                    range_start = None
                else:
                    char_avail = True
                result.append(re.escape(ch))
                cclass_empty = False

            result.append("]")
        else:
            result.append(re.escape(ch))

    return "".join(result), simple


def _create_pattern(
    path_pat: str, match_prefix: bool, *, allow_double_star: bool = True
) -> str:
    """
    Compile a full path pattern with separators into a regex.

    If `match_prefix` is True, and all but the last component of `path_pat`
    is simple, then any path that matches a prefix of path components will also
    be matched by this pattern. For example "a/b/c/*.txt" will match "a", "a/b",
    and "a/b/c". If the pattern was instead "a/*/c/*.txt" then no prefix matching
    will happen at all because the second component is not simple.
    """
    pattern_parts = [
        _create_pattern_part(path_part, allow_double_star=allow_double_star)
        for path_part in path_pat.split(os.path.sep)
    ]
    if not match_prefix or not all(simple for _, simple in pattern_parts[:-1]):
        return (
            "^"
            + "".join(pat for pat, _ in pattern_parts)
            + f"(?:$|{re.escape(os.path.sep)})"
        )

    result = ["^"]
    for pat_part, _ in pattern_parts:
        result.append(pat_part)
        result.append("(?:$|")
    result.append(re.escape(os.path.sep))

    result.append(")" * len(pattern_parts))
    return "".join(result)


class ContextPattern:
    """
    Represents a pattern used to control what files are availble in a
    build context.

    Attributes:
        ignoring (bool): Flag indicating if matching this pattern means the
            matched element should be ignored or not ignored.
    """

    def __init__(self, pattern: str):
        try:
            if pattern.startswith("!"):
                self.ignoring = False
                self.pattern = re.compile(_create_pattern(pattern[1:], True))
            else:
                self.ignoring = True
                self.pattern = re.compile(_create_pattern(pattern, False))
        except ValueError as exc:
            raise TplBuildContextException(
                f"Error handling {repr(pattern)}: {exc}"
            ) from exc

    def matches(self, path: str) -> bool:
        """Returns True if this pattern matches the path"""
        return bool(self.pattern.search(path))


def _apply_umask(mode: int, umask: Optional[int]) -> int:
    """
    Copy the user permission bits to group and all bits and then apply
    the supplied umask. If umask is None just return mode instead.
    """
    if umask is None:
        return mode
    umode = (mode >> 6) & 0o7
    mode &= ~0o777
    mode |= ((umode << 6) | (umode << 3) | umode) & ~umask
    return mode


def _stat_to_tarinfo(
    base_path: str, arch_path: str, *, umask: Optional[int] = None, follow_link=True
) -> tarfile.TarInfo:
    """
    Convert a stat_result into a TarInfo structure.
    """
    tarinfo = tarfile.TarInfo()
    if follow_link:
        statres = os.stat(os.path.join(base_path, arch_path))
    else:
        statres = os.lstat(os.path.join(base_path, arch_path))

    linkname = ""
    stmd = statres.st_mode
    if stat.S_ISREG(stmd):
        typ = tarfile.REGTYPE
    elif stat.S_ISDIR(stmd):
        typ = tarfile.DIRTYPE
    elif stat.S_ISFIFO(stmd):
        typ = tarfile.FIFOTYPE
    elif stat.S_ISLNK(stmd):
        typ = tarfile.SYMTYPE
        linkname = os.readlink(os.path.join(base_path, arch_path))
    elif stat.S_ISCHR(stmd):
        typ = tarfile.CHRTYPE
    elif stat.S_ISBLK(stmd):
        typ = tarfile.BLKTYPE
    else:
        raise TplBuildException("Unsupported file mode in context")

    if arch_path == ".":
        tarinfo.name = "/"
    elif arch_path.startswith("./"):
        tarinfo.name = arch_path[1:]
    else:
        tarinfo.name = "/" + arch_path
    tarinfo.mode = _apply_umask(stmd, umask)
    tarinfo.uid = 0
    tarinfo.gid = 0
    tarinfo.uname = "root"
    tarinfo.gname = "root"
    if typ == tarfile.REGTYPE:
        tarinfo.size = statres.st_size
    else:
        tarinfo.size = 0
    tarinfo.mtime = 0
    tarinfo.type = typ
    tarinfo.linkname = linkname

    if typ in (tarfile.CHRTYPE, tarfile.BLKTYPE):
        if hasattr(os, "major") and hasattr(os, "minor"):
            tarinfo.devmajor = os.major(statres.st_rdev)
            tarinfo.devminor = os.minor(statres.st_rdev)
    return tarinfo


class BuildContext:
    """
    Class representing and capable of writing a build context.

    Args:
        base_dir: The base directory of the build context
        umask: If not None, the user permission bits will be copied to the
            'group' and 'all' bits and then the umask will be applied. If
            None then the exact file permissions will be forwarded to the
            build context.
        ignore_patterns: An interable of ignore patterns in the order they
            should be tested. A path will be ignored if the last pattern it
            matches in the list is not negated. This is meant to mirror the
            behavior and semantics of
            https://docs.docker.com/engine/reference/builder/#dockerignore-file
    """

    def __init__(
        self,
        base_dir: Optional[str],
        umask: Optional[int],
        ignore_patterns: Iterable[str],
    ) -> None:
        self.base_dir = base_dir
        self.umask = umask
        self.context_patterns = tuple(
            ContextPattern(pattern.strip())
            for pattern in ignore_patterns
            if pattern.strip() and pattern.strip()[0] != "#"
        )

    def ignored(self, path: str):
        """
        Returns True if the given path should be ignored (not present) in
        the build contxt. `path` should start with a directory separator
        and should be relative to `self.base_dir`.
        """
        ignored = False
        for pattern in self.context_patterns:
            if pattern.ignoring == ignored:
                continue
            if pattern.matches(path):
                ignored = pattern.ignoring
        return ignored

    def walk_context(
        self,
        *,
        extra_files: Optional[Dict[str, Tuple[int, bytes]]] = None,
        ignore_func: Callable[[str], bool] = None,
    ) -> Iterable[tarfile.TarInfo]:
        """
        Generator that yields TarInfo objects for each not-ignored object
        in the context. Objects are yielded in a deterministic order based on the
        names.
        """

        def _is_ignored(path: str) -> bool:
            if self.ignored(path):
                return True
            return ignore_func is not None and ignore_func(path)

        if self.base_dir is None:
            tarinfo = tarfile.TarInfo("/")
            tarinfo.mode = _apply_umask(0o777, self.umask)
            tarinfo.type = tarfile.DIRTYPE
            yield tarinfo
        else:
            for root, dir_names, file_names in os.walk(self.base_dir):
                arch_root = os.path.relpath(root, self.base_dir)
                tarinfo = _stat_to_tarinfo(self.base_dir, arch_root, umask=self.umask)
                yield tarinfo

                file_names[:] = sorted(
                    file_name
                    for file_name in file_names
                    if not _is_ignored(os.path.join(tarinfo.name, file_name))
                )
                dir_names[:] = sorted(
                    dir_name
                    for dir_name in dir_names
                    if not _is_ignored(os.path.join(tarinfo.name, dir_name))
                )

                for file_name in file_names:
                    yield _stat_to_tarinfo(
                        self.base_dir,
                        os.path.join(arch_root, file_name),
                        umask=self.umask,
                        follow_link=False,
                    )

        extra_files = extra_files or {}
        for file_name, (file_mode, file_data) in extra_files.items():
            tarinfo = tarfile.TarInfo(file_name)
            tarinfo.mode = _apply_umask(file_mode, self.umask)
            tarinfo.size = len(file_data)
            yield tarinfo

    def write_context(
        self,
        io_out: io.BytesIO,
        *,
        extra_files: Optional[Dict[str, Tuple[int, bytes]]] = None,
        compress: bool = False,
    ) -> None:
        """
        Write the context to `io_out`.

        Args:
            io_out: The file-like object to write the build context to as a tar file.
            extra_files: Extra file data to add at the root of the archive.
                this is of the form (file mode, file data).
            compress: If set the output stream will be gzipped.
        """
        extra_files = extra_files or {}

        with tarfile.open(
            fileobj=io_out,
            format=tarfile.PAX_FORMAT,
            mode=("w|gz" if compress else "w|"),
        ) as tf:
            for tarinfo in self.walk_context(extra_files=extra_files):
                if tarinfo.type == tarfile.REGTYPE:
                    extra_data = extra_files.get(tarinfo.name)
                    if extra_data:
                        tf.addfile(tarinfo, fileobj=io.BytesIO(extra_data[1]))
                    else:
                        assert self.base_dir is not None
                        with open(
                            os.path.join(self.base_dir, "." + tarinfo.name), "rb"
                        ) as fileobj:
                            tf.addfile(tarinfo, fileobj=fileobj)
                else:
                    tf.addfile(tarinfo)

    def compute_partial_hash(
        self,
        *,
        patterns: Optional[List[str]] = None,
    ) -> str:
        """
        Compute a partial hash of the context where all hashed files must match
        at least one file pattern in `patterns`.
        """
        pats = [
            re.compile(_create_pattern(pat, True, allow_double_star=False))
            for pat in (patterns or [])
        ]

        def _ignore_func(path: str) -> bool:
            return not any(pat.search(path) for pat in pats)

        hsh = hashing.HASHER()
        for tarinfo in self.walk_context(
            ignore_func=_ignore_func if patterns else None
        ):
            info = tarinfo.get_info()
            info["type"] = info["type"].decode("utf-8")  # type: ignore
            hsh.update(hashing.json_hash(info).encode("utf-8"))
            if tarinfo.type == tarfile.REGTYPE:
                assert self.base_dir is not None
                hsh.update(
                    _hash_file(os.path.join(self.base_dir, "." + tarinfo.name)).encode(
                        "utf-8"
                    )
                )

        return hashing.json_hash(
            [
                type(self).__name__,
                "full",
                hsh.hexdigest(),
            ]
        )

    @functools.cached_property
    def full_hash(self) -> str:
        """The full content hash of the build context, as a hex digest"""
        return self.compute_partial_hash()

    @functools.cached_property
    def symbolic_hash(self) -> str:
        """
        The symbolic content hash of the build context, as a hex digest. This
        is different from :attr:`full_hash` in that it does not read any files
        from the build context and is only a hash of the parameters that define
        the build context instead.
        """
        return hashing.json_hash(
            [
                type(self).__name__,
                "symbolic",
                self.umask,
                self.base_dir,
                [[pat.ignoring, pat.pattern.pattern] for pat in self.context_patterns],
            ]
        )
