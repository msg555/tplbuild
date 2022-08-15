from typing import Iterator, Tuple

from jinja2.ext import Extension
from jinja2.lexer import Token


class TokenMetadata:
    def __init__(self, lineno, token_length):
        self.lineno = lineno
        self.token_length = token_length


class SourceMapper:
    def __init__(self, line_breaks: Iterator[Tuple[int, int]]) -> None:
        self.line_breaks = tuple(line_breaks)

    def get_source_line_data(self, pos: int) -> (str, int):
        if not self.line_breaks:
            return -1

        idx = 0
        while idx + 1 < len(self.line_breaks) and pos > self.line_breaks[idx][0]:
            idx += 1
        return (
            self.line_breaks[idx][2],
            self.line_breaks[idx][1],
        )

    def get_source_line(self, pos: int) -> (str, int):
        result = self.get_source_line_data(pos)
        return f"{result[0]}:{result[1]}"


class SourceMapperExtension(Extension):
    def filter_stream(self, stream):
        yield Token(1, "block_begin", "{%")
        yield Token(1, "name", "print")
        yield Token(1, "string", f"\u00001;{stream.filename}")
        yield Token(1, "block_end", "%}")

        for token in stream:
            if token.type == "data":
                yield Token(1, "block_begin", "{%")
                yield Token(1, "name", "print")
                yield Token(1, "string", f"\u0000{token.lineno};{stream.filename}")
                yield Token(1, "block_end", "%}")
            yield token

    def render(self, generator):
        cur_pos = 0
        cur_lineno = 0
        cur_filename = "<none>"
        line_breaks = []
        result = []
        for data in generator:
            if data.startswith("\u0000"):
                s1 = data.find(";")
                cur_lineno = int(data[1:s1])
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
