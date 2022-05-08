import pytest

from tplbuild.utils import extract_command_flags, format_command_with_flags, line_reader


@pytest.mark.unit
def test_line_reader():
    """Test line reader behavior"""

    assert list(line_reader("hello \\")) == [(0, "hello")]
    assert list(line_reader("hi\n\nthere")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n\nthere\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n\nthe\\\nre\n")) == [(0, "hi"), (3, "there")]
    assert list(line_reader("hi\n\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n# comment\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n# comment\\\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\nthere\\\n# comment")) == [
        (0, "hi"),
        (2, "there"),
    ]
    assert not list(line_reader(""))
    assert not list(line_reader(" #comment\n# comment\n  #  comment 2\n\n"))
    assert list(line_reader("\n\nhi\n\nthere")) == [(2, "hi"), (4, "there")]
    assert list(line_reader("  \\\n\nhi\n\nthere")) == [(2, "hi"), (4, "there")]
    assert list(line_reader("\\\nhi\n\nthere")) == [(1, "hi"), (3, "there")]
    assert list(line_reader("hi \\\n # comment\nthere")) == [(2, "hi there")]
    assert list(line_reader("hi \\\n # comment \\\nthere")) == [(2, "hi there")]
    assert not list(line_reader("\n\n\n"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "line,exp_new_line,exp_flags,exp_format_line",
    [
        pytest.param(" hello ", " hello ", {}, " hello ", id="noflags"),
        pytest.param(
            "--doh=reh hello", "hello", {"doh": "reh"}, "--doh=reh hello", id="oneflag"
        ),
        pytest.param(
            "\t \v--foo=bar --bar=baz \t hello there! ",
            "hello there! ",
            {"foo": "bar", "bar": "baz"},
            "--foo=bar --bar=baz hello there! ",
            id="twoflags",
        ),
        pytest.param(
            "--bar=baz    --foo=bar   hello",
            "hello",
            {"foo": "bar", "bar": "baz"},
            "--bar=baz --foo=bar hello",
            id="twoflagsrev",
        ),
        pytest.param(
            "  --foo=bar --foo=baz hello",
            "hello",
            {"foo": "baz"},
            "--foo=baz hello",
            id="dupflag",
        ),
        pytest.param(
            " --only=flag ", "", {"only": "flag"}, "--only=flag", id="onlyflag"
        ),
    ],
)
def test_command_flags(line, exp_new_line, exp_flags, exp_format_line):
    """Test flag extraction and formatting behavior"""
    new_line, flags = extract_command_flags(line)
    assert exp_new_line == new_line
    assert exp_flags == flags
    assert format_command_with_flags(new_line, flags) == exp_format_line
