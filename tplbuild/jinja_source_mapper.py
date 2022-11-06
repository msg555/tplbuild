from typing import Iterable, Tuple

from jinja2.ext import Extension
from jinja2.lexer import Token


class SourceMapper:
    """
    Container class that can be used to map lines of rendered text to the
    template file and line that generated that text.
    """

    def __init__(self, line_breaks: Iterable[Tuple[int, int, str]]) -> None:
        self.line_breaks = tuple(line_breaks)

    def get_source_line_data(self, pos: int) -> Tuple[str, int]:
        """
        Given a character position in the rendered document return the template
        file and line number that produced it.
        """
        if not self.line_breaks:
            return "<none>", -1

        idx = 0
        while idx + 1 < len(self.line_breaks) and pos > self.line_breaks[idx][0]:
            idx += 1
        return (
            self.line_breaks[idx][2],
            self.line_breaks[idx][1],
        )

    def get_source_line(self, pos: int) -> str:
        """
        Like `get_source_line_data` except return a single string in the form
        {file}:{line_no}.
        """
        result = self.get_source_line_data(pos)
        return f"{result[0]}:{result[1]}"


class SourceMapperExtension(Extension):
    """
    Jinja extension used to correlate template files and line numbers to each
    character of output in the rendered document. It does this by inserting
    instructions to print metadata within the template and removing these
    metadata chunks when passing the template output back through the render
    function.
    """

    def filter_stream(self, stream):
        """
        Extension filter function that adds output to track the template file
        and line numbers in the output stream.
        """
        yield Token(1, "block_begin", "{%")
        yield Token(1, "name", "print")
        yield Token(1, "string", f"\u00001;{stream.filename}\u0000")
        yield Token(1, "block_end", "%}")

        for token in stream:
            if token.type == "data":
                yield Token(1, "block_begin", "{%")
                yield Token(1, "name", "print")
                yield Token(
                    1, "string", f"\u0000{token.lineno};{stream.filename}\u0000"
                )
                yield Token(1, "block_end", "%}")
            yield token

    def render(self, generator) -> Tuple[str, SourceMapper]:
        """
        Given a generator created from jinja_env.generate, output the complete
        rendered document and a SourceMapper object to map each character to a
        file and line number in the source template.
        """
        cur_pos = 0
        cur_lineno = 0
        cur_filename = "<none>"
        line_breaks = []
        result = []

        chunks = "".join(generator).split("\u0000")
        for ind, data in enumerate(chunks):
            if ind % 2 == 1:
                s1 = data.find(";")
                cur_lineno = int(data[:s1])
                cur_filename = data[s1 + 1 :]
                line_breaks.append((cur_pos, cur_lineno, cur_filename))
            else:
                result.append(data)
                for idx, ch in enumerate(data):
                    if ch == "\n":
                        line_breaks.append((cur_pos + idx, cur_lineno, cur_filename))
                        cur_lineno += 1
                cur_pos += len(data)

        return "".join(result), SourceMapper(line_breaks)

    def parse(self, parser):
        raise NotImplementedError("No parse method needed")
