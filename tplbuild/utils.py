import contextlib
import os
import tempfile
from typing import Iterable, List, Tuple


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
