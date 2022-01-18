import contextlib
import json
import os
import tempfile
from typing import Any, Iterable, List, Tuple


def json_encode(data: Any) -> str:
    """Helper function to encode JSON data"""
    return json.dumps(data)


def json_decode(data: str) -> Any:
    """Helper function to decode JSON data"""
    return json.loads(data)


def json_raw_decode(data: str) -> Tuple[Any, int]:
    """Helper function to decode raw JSON data"""
    return json.JSONDecoder().raw_decode(data)


def format_simple(fmt: str, **params) -> str:
    """
    Do format replacements using a scheme similar to str.format except
    only support simple keyword substitutions.
    """
    result = []
    in_braces = False
    pos = 0
    i = 0
    while i < len(fmt):
        ch = fmt[i]
        i += 1

        if in_braces:
            if ch == "}":
                in_braces = False
                key = fmt[pos : i - 1].strip()
                pos = i
                result.append(str(params[key]))
            continue

        if fmt[i - 1 : i + 1] in ("{{", "}}"):
            result.append(fmt[pos:i])
            i += 1
            pos = i
            continue

        if ch == "{":
            result.append(fmt[pos : i - 1])
            pos = i
            in_braces = True

    result.append(fmt[pos:])
    return "".join(result)


def line_reader(document: str) -> Iterable[Tuple[int, str]]:
    """
    Yield lines from `document`. Lines will have leading and trailing whitespace
    stripped. Lines that being with a '#' character will be omitted. Lines that
    end with a single backslash character will be treated as continuations with
    the following line concatenated onto itself, not including the backslash or
    line feed character.
    """
    line_parts: List[str] = []
    lines = document.splitlines()
    for idx, line_part in enumerate(lines):
        line_part = line_part.rstrip()
        if not line_parts and line_part.lstrip().startswith("#"):
            continue
        if line_part.endswith("\\") and not line_part.endswith("\\\\"):
            line_parts.append(line_part[:-1])
            if idx + 1 < len(lines):
                continue
            line_part = ""

        line = ("".join(line_parts) + line_part).strip()
        line_parts.clear()
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
