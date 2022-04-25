import pytest

from tplbuild.render import _extract_command_flags, _format_command_with_flags


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
    new_line, flags = _extract_command_flags(line)
    assert exp_new_line == new_line
    assert exp_flags == flags
    assert _format_command_with_flags(new_line, flags) == exp_format_line
