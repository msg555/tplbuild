import pytest

from tplbuild.utils import (
    compute_extra_vars,
    deep_merge_json,
    extract_command_flags,
    format_command_with_flags,
    ignore_escape,
    line_reader,
)


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


@pytest.mark.unit
@pytest.mark.parametrize(
    "a,b",
    [
        pytest.param(r"hi\there", r"hi\\there"),
        pytest.param(r"./oh?", r"./oh\?"),
        pytest.param(r"./[].?\*/**", r"./\[\].\?\\\*/\*\*"),
    ],
)
def test_ignore_escape(a, b):
    """Test ignore_escape behavior"""
    assert ignore_escape(a) == b


@pytest.mark.unit
def test_deep_merge_simple():
    """Test edge behavior of deep merge"""
    x = {}
    y = {"a": "b"}
    z = {"c": "d"}
    o = [0, 1, 2]
    f = [3, 4, 5]
    assert deep_merge_json(x, y) is y
    assert deep_merge_json(y, x) is y
    assert deep_merge_json(y, z) == {"a": "b", "c": "d"}
    assert deep_merge_json(z, y) == {"a": "b", "c": "d"}
    assert deep_merge_json(y, o) is o
    assert deep_merge_json(o, y) is y
    assert deep_merge_json(o, f) is f
    assert deep_merge_json(f, o) is o


@pytest.mark.unit
@pytest.mark.parametrize(
    "lhs,rhs,result",
    [
        pytest.param(
            {"a": {"b": "c"}},
            {"a": {"d": "e"}},
            {"a": {"b": "c", "d": "e"}},
            id="merge dicts",
        ),
        pytest.param({"a": {"b": "c"}}, {"a": 123}, {"a": 123}, id="overwrite dicts"),
    ],
)
def test_deep_merge(lhs, rhs, result):
    """Test deep merge behavior"""
    assert deep_merge_json(lhs, rhs) == result


@pytest.mark.unit
@pytest.mark.parametrize(
    "set_args,expected",
    [
        pytest.param([], {}, id="no args"),
        pytest.param([(False, "a=b=c")], {"a": "b=c"}, id="more-equal"),
        pytest.param([(False, "a=123")], {"a": "123"}, id="int-like set"),
        pytest.param([(True, "a=123")], {"a": 123}, id="int set-json"),
        pytest.param(
            [(False, "a.b.c=x"), (False, "a.b.d=y")],
            {"a": {"b": {"c": "x", "d": "y"}}},
            id="set nested",
        ),
        pytest.param(
            [(True, 'a={"b":"c"}'), (True, 'a={"d":"e"}')],
            {"a": {"b": "c", "d": "e"}},
            id="merged",
        ),
        pytest.param(
            [(True, 'a={"b":"c"}'), (False, "a=x")], {"a": "x"}, id="overwrite"
        ),
    ],
)
def test_compute_extra_vars(set_args, expected):
    """Test compute_extra_vars behavior"""
    assert compute_extra_vars(set_args) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "set_args,err_match",
    [
        pytest.param(
            [(False, "x")], "Invalid --set value, expected '='", id="no equal"
        ),
        pytest.param(
            [(True, "x")], "Invalid --set-json value, expected '='", id="no equal json"
        ),
        pytest.param(
            [(False, "=x")], "Cannot --set variable with empty key part", id="no key"
        ),
        pytest.param(
            [(True, "=1")],
            "Cannot --set-json variable with empty key",
            id="no key json",
        ),
        pytest.param([(True, "a={")], "Invalid --set-json value JSON", id="bad json"),
        pytest.param(
            [(False, "a..b=c")],
            "Cannot --set variable with empty key part",
            id="empty key part",
        ),
    ],
)
def test_compute_extra_vars_error(set_args, err_match):
    """Test compute_extra_vars error handling"""
    with pytest.raises(ValueError, match=err_match):
        compute_extra_vars(set_args)
