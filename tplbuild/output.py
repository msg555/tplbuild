import random
import sys
from typing import List, Optional


class OutputStream:
    """
    Class that manages writing to output for a single sub-process.
    """

    def __init__(self, title: str, color: Optional[bytes] = None) -> None:
        self.title = title
        self.prefix = b""
        if title:
            if color:
                self.prefix = color + title.encode("utf-8") + b"\x1b[0m: "
            else:
                self.prefix = title.encode("utf-8") + b": "

    async def __aenter__(self) -> "OutputStream":
        return self

    async def __aexit__(self, exc_typ, exc_val, exc_tb) -> None:
        await self.end(exc_typ is None)

    async def write(self, line: bytes, *, err: bool = False) -> None:
        """
        Write a single line of data to the output stream. Set err=True
        to write to the error stream instead of output stream.
        """
        stream = sys.stderr.buffer if err else sys.stdout.buffer
        stream.write(self.prefix)
        stream.write(line)
        if not line.endswith(b"\n"):
            stream.write(b"\n")
        stream.flush()

    async def end(self, success: bool) -> None:
        """
        End the output stream. If success is False buffered error content
        may be redisplayed.
        """


class OutputStreamer:
    """
    Class responsible for creating output streams from sub-commands and organizing
    how those outputs are displayed. For now this is just a single concreate
    implementation that writes output as it comes in directly to stdout/stderr.

    Arguments:
        use_color: If true ANSI color escape codes will be used to highlight the
                   titles of the output streams.
    """

    def __init__(self, *, use_color: bool = True) -> None:
        self.use_color = use_color
        self.remaining_colors: List[bytes] = []

    def _reset_colors(self) -> None:
        """
        Title colors are picked randomly with replacement using the 16-color
        ANSI codes. We intentionally avoid white/black variants giving us in
        total 12 colors.
        """
        self.remaining_colors = [
            *(f"\u001b[{i}m".encode("utf-8") for i in range(31, 37)),
            *(f"\u001b[{i};1m".encode("utf-8") for i in range(31, 37)),
        ]
        random.shuffle(self.remaining_colors)

    def start_stream(self, title: str) -> OutputStream:
        """
        Create a new output stream with the given title.
        """
        color = None
        if self.use_color:
            if not self.remaining_colors:
                self._reset_colors()
            color = self.remaining_colors.pop()
        return OutputStream(title, color)
