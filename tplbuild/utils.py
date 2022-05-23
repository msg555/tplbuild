import contextlib
import json
import os
import tempfile
from typing import Dict, Iterable, List, Tuple


def line_reader(document: str) -> Iterable[Tuple[int, str]]:
    """
    Yield lines from `document`. Lines will have leading and trailing whitespace
    stripped. Lines that being with a '#' character will be omitted. Lines that
    end with a single backslash character will be treated as continuations with
    the following line concatenated onto itself, not including the backslash or
    line feed character.
    """
    idx = -1
    line_parts: List[str] = []
    lines = document.splitlines()
    for idx, line_part in enumerate(lines):
        line_part = line_part.rstrip()
        if line_part.lstrip().startswith("#"):
            continue
        if line_part.endswith("\\") and not line_part.endswith("\\\\"):
            line_parts.append(line_part[:-1])
            continue

        line = ("".join(line_parts) + line_part).strip()
        line_parts.clear()
        if line:
            yield idx, line

    line = "".join(line_parts).strip()
    if line:
        yield idx, line


@contextlib.contextmanager
def open_and_swap(filename, mode="w+b", buffering=-1, encoding=None, newline=None):
    """
    Open a file for writing and relink it to the desired path in an atomic
    operation when the file is closed without an exception. This prevents
    the existing file data from being lost if an unexpected failure occurs
    while writing the file.
    """
    fd, tmppath = tempfile.mkstemp(
        dir=os.path.dirname(filename) or ".",
        text="b" not in mode,
    )
    fh = None
    try:
        fh = open(
            fd,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            newline=newline,
            closefd=False,
        )
        yield fh
        os.rename(tmppath, filename)
        tmppath = None
    finally:
        if fh is not None:
            fh.close()
        os.close(fd)
        if tmppath is not None:
            os.unlink(tmppath)


def split_line_tokens(line: str) -> List[str]:
    """
    Split a Dockerfile command into tokens. For commands that can accept flags
    this should be called with the `line` portion returned from
    `extract_command_flags`
    """
    line = line.strip()
    if line.startswith("["):
        parts = json.loads(line)
        if not isinstance(parts, list):
            raise ValueError("Expected JSON list")
        if not all(isinstance(part, str) for part in parts):
            raise ValueError("Expected list of strings")
        return parts
    return line.split()


def extract_command_flags(line: str) -> Tuple[str, Dict[str, str]]:
    """
    Some Dockerfile commands support flags in the form "--name=value" at the start of
    the command. This extracts the commands with those flags removed and returns a
    mapping of the extracted flags.

    Notes:
        As far as I know there is no escaping layer here. Names that contain spaces
        or equal signs cannot be represented as flag names or values.

    Returns: (line, flags) tuple
        line: The line with the flags removed.
        flags: The mapping of flag names to flag values that was extracted
    """

    def _skip_ws(pos: int) -> int:
        while pos < len(line) and line[pos].isspace():
            pos += 1
        return pos

    pos = _skip_ws(0)
    flags = {}
    while pos + 1 < len(line) and line[pos : pos + 2] == "--":
        space = line.find(" ", pos + 2)
        if space == -1:
            space = len(line)

        parts = line[pos + 2 : space].split("=", 1)
        if len(parts) == 2:
            flags[parts[0]] = parts[1]
        else:
            flags[parts[0]] = ""
        pos = _skip_ws(space)

    if not flags:
        return line, {}
    return line[pos:], flags


def format_command_with_flags(line: str, flags: Dict[str, str]) -> str:
    """
    The inverse of _extract_command_flags

    Returns:
        The command line with the flags added into the front of the command.
    """
    if not flags:
        return line
    flags_str = " ".join(f"--{key}={val}" for key, val in flags.items())
    if not line:
        return flags_str
    return f"{flags_str} {line}"


def ignore_escape(path: str) -> str:
    """
    Escape a path appropriately for a docker ignore file.
    """
    special_chars = "\\*?[]"
    return "".join("\\" + ch if ch in special_chars else ch for ch in path)
