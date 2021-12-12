import functools
import os.path
import re
from typing import Iterable, Tuple


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

    result = []
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


def _compile_pattern(pat: str) -> re.Pattern:
    return re.compile(pat)


class ContextPattern:
    """
    Represents a pattern used to control what files are availble in a
    build context.
    """

    def __init__(self, pattern: str):
        if pattern.startswith("!"):
            self.ignoring = False
            self.pattern = _compile_pattern(pattern[1:])
        else:
            self.ignoring = True
            self.pattern = _compile_pattern(pattern)

    def match(self, path: str) -> bool:
        """Returns True if this pattern matches the path"""
        return bool(self.pattern.fullmatch(path))


class BuildContext:
    def __init__(self, base_dir: str, ignore_patterns: Iterable[str]) -> None:
        self.base_dir = base_dir
        self.context_patterns = tuple(
            ContextPattern(pattern.strip())
            for pattern in self.ignore_patterns
            if pattern.strip() and pattern.strip()[0] != "#"
        )

    def ignored(self, path: str):
        ignored = False
        for pattern in self.ignore_patterns:
            if pattern.ignoring == ignored:
                continue
            if pattern.matches(path):
                ignored = pattern.ignoring
        return ignored

    @functools.cached_property
    def full_hash(self):
        pass

    @functools.cached_property
    def symbolic_hash(self):
        return json_hash(
            [
                type(self).__name__,
                [[pat.ignoring, pat.pattern.pattern] for pat in self.ignore_patterns],
            ]
        )
