import contextlib
import json
import os
import tempfile
from typing import Any, Dict, Iterable, List, Sequence, Tuple


def line_reader(document: str) -> Iterable[Tuple[int, int, str]]:
    """
    Yield lines from `document` in the form (source_character_position,
    source_line_position, line_content).

    Lines will have leading and trailing whitespace
    stripped. Lines that being with a '#' character will be omitted. Lines that
    end with a single backslash character will be treated as continuations with
    the following line concatenated onto itself, not including the backslash or
    line feed character.

    `source_character_position` will give the character index that the line
    begins in the original passed `document`.

    `source_line_position` will give the line index that the line begins in
    the original passed `document`. This may differ than the output line index
    in the precense of empty lines, comments, and line continuations.
    """
    lines = []
    line_start_idx = 0
    line_last_ch = ""
    for idx, ch in enumerate(document):
        if ch == "\n":
            end_idx = idx - 1 if line_last_ch == "\r" else idx
            lines.append((line_start_idx, document[line_start_idx:end_idx]))
            line_start_idx = idx + 1
        elif line_last_ch == "\r":
            lines.append((line_start_idx, document[line_start_idx : idx - 1]))
            line_start_idx = idx
        line_last_ch = ch
    if line_start_idx < len(document):
        lines.append((line_start_idx, document[line_start_idx:]))

    idx = -1
    start_line_pos = -1
    start_line_idx = -1
    line_parts: List[str] = []
    for idx, (line_pos, line_part) in enumerate(lines):
        line_part = line_part.rstrip()
        if not line_parts and not line_part:
            continue
        if not line_parts:
            start_line_pos = line_pos
            start_line_idx = idx
        if line_part.lstrip().startswith("#"):
            continue
        if line_part.endswith("\\") and not line_part.endswith("\\\\"):
            line_parts.append(line_part[:-1])
            continue

        line = ("".join(line_parts) + line_part).strip()
        line_parts.clear()
        if line:
            yield start_line_pos, start_line_idx, line

    line = "".join(line_parts).strip()
    if line:
        yield start_line_pos, start_line_idx, line


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


def deep_merge_json(lhs: Any, rhs: Any) -> Any:
    """
    Merge JSON-like data `rhs` into `lhs`. This will only merge dicts, lists
    will simply replace rather than concatenate.

    This will not modify any objects referenced by `lhs` or `rhs` but may
    return an object which points to objects originally in `lhs` and `rhs`.
    """

    if not isinstance(lhs, dict) or not isinstance(rhs, dict):
        return rhs
    if not rhs:
        return lhs
    if not lhs:
        return rhs

    result = dict(lhs)
    for key, val in rhs.items():
        lval = result.setdefault(key, val)
        if lval is not val:
            result[key] = deep_merge_json(lval, val)

    return result


def compute_extra_vars(set_args: Sequence[Tuple[bool, str]]) -> Dict[str, Any]:
    """
    Convert arguments passed to --set and --set-json into a dictionary of
    arguments to pass to the render. Later arguments have precedence over
    earlier arguments.
    """
    result: Dict[str, Any] = {}

    def _set_value(key: str, val: Any):
        obj = result
        key_parts = key.split(".")
        for key_part in key_parts[:-1]:
            obj = obj.setdefault(key_part, {})
            if not isinstance(obj, dict):
                obj[key_part] = {}
        obj[key_parts[-1]] = val

    for is_json, set_arg in set_args:
        arg_type = "--set-json" if is_json else "--set"

        equal_pos = set_arg.find("=")
        if equal_pos == -1:
            raise ValueError(f"Invalid {arg_type} value, expected '='")

        key = set_arg[:equal_pos]
        val = set_arg[equal_pos + 1 :]
        if is_json:
            try:
                val = json.loads(val)
            except ValueError as exc:
                raise ValueError(f"Invalid {arg_type} value JSON") from exc

        key_parts = key.split(".")
        merge_value = val
        for key_part in reversed(key_parts):
            if not key_part:
                raise ValueError(f"Cannot {arg_type} variable with empty key part")
            merge_value = {key_part: merge_value}  # type: ignore

        result = deep_merge_json(result, merge_value)

    return result
