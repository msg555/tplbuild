import functools
import io
import os.path
import re
import sys
import tarfile
from typing import Dict, Iterable, Optional, Tuple

from . import hashing
from .exceptions import TplBuildContextException

if sys.version_info < (3, 9):

    class _PatchedTarInfo(tarfile.TarInfo):
        """
        Patched tarinfo class for python < 3.9
        """

        # pylint: disable=redefined-builtin,consider-using-f-string
        @staticmethod
        def _create_header(info, *args, **kwargs):
            """
            Patch create_header to correctly zero out dev numbers for non-devices.
            """
            buf = tarfile.TarInfo._create_header(info, *args, **kwargs)
            assert len(buf) == 512

            if info.get("type") in (tarfile.CHRTYPE, tarfile.BLKTYPE):
                return buf

            buf = buf[:329] + b"\x00" * 16 + buf[345:]
            chksum = tarfile.calc_chksums(buf)[0]
            buf = buf[:148] + bytes("%06o\0" % chksum, "ascii") + buf[155:]
            return buf

else:
    _PatchedTarInfo = tarfile.TarInfo


def _create_pattern_part(path_pat: str) -> Tuple[str, bool]:
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
    if path_pat == "**":
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
        elif ch == "]":
            raise ValueError("Unmatched ']' should be escaped")
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
                elif ch == "[":
                    raise ValueError("'[' in character class should be escaped")

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


def _create_pattern(path_pat: str, match_prefix: bool) -> str:
    """
    Compile a full path pattern with separators into a regex.

    If `match_prefix` is True, and all but the last component of `path_pat`
    is simple, then any path that matches a prefix of path components will also
    be matched by this pattern. For example "a/b/c/*.txt" will match "a", "a/b",
    and "a/b/c". If the pattern was instead "a/*/c/*.txt" then no prefix matching
    will happen at all because the second component is not simple.
    """
    pattern_parts = [
        _create_pattern_part(path_part) for path_part in path_pat.split(os.path.sep)
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

    def _write_context_files(self, tf: tarfile.TarFile) -> None:
        """
        Write all the context data from the file system.
        """
        assert self.base_dir is not None

        def filter_tarinfo(ti: tarfile.TarInfo) -> tarfile.TarInfo:
            """
            Filter out metadata that should not be included in the build
            context or its hash.
            """
            ti.uid = 0
            ti.gid = 0
            ti.uname = "root"
            ti.gname = "root"
            ti.mtime = 0
            ti.mode = _apply_umask(ti.mode, self.umask)
            if not ti.isreg() and not ti.islnk():
                ti.size = 0
            ti.devmajor = 0
            ti.devminor = 0

            return ti

        for root, dir_names, file_names in os.walk(self.base_dir):
            arch_root = os.path.relpath(root, self.base_dir)
            if arch_root == ".":
                arch_root = "/"
            else:
                arch_root = "/" + arch_root

            tf.add(
                root,
                arcname="." + arch_root,
                recursive=False,
                filter=filter_tarinfo,
            )

            file_names[:] = sorted(
                file_name
                for file_name in file_names
                if not self.ignored(os.path.join(arch_root, file_name))
            )
            dir_names[:] = sorted(
                dir_name
                for dir_name in dir_names
                if not self.ignored(os.path.join(arch_root, dir_name))
            )

            for file_name in file_names:
                tf.add(
                    os.path.join(root, file_name),
                    arcname="." + os.path.join(arch_root, file_name),
                    recursive=False,
                    filter=filter_tarinfo,
                )

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
            tarinfo=_PatchedTarInfo,
            mode=("w|gz" if compress else "w|"),
        ) as tf:
            if self.base_dir is None:
                ti = _PatchedTarInfo("./")
                ti.mode = _apply_umask(0o777, self.umask)
                ti.type = tarfile.DIRTYPE
                tf.addfile(ti)
            else:
                self._write_context_files(tf)

            for file_name, (file_mode, file_data) in extra_files.items():
                ti = _PatchedTarInfo(file_name)
                ti.mode = _apply_umask(file_mode, self.umask)
                ti.size = len(file_data)
                tf.addfile(ti, fileobj=io.BytesIO(file_data))

    @functools.cached_property
    def full_hash(self) -> str:
        """The full content hash of the build context, as a hex digest"""
        hsh = hashing.HASHER()
        self.write_context(hashing.HashWriter(hsh))  # type: ignore
        return hashing.json_hash(
            [
                type(self).__name__,
                "full",
                hsh.hexdigest(),
            ]
        )

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
