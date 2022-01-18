import pytest

from .utils import format_simple, line_reader


@pytest.mark.unit
def test_line_reader():
    """Test line reader behavior"""

    assert list(line_reader("hi\n\nthere")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n\nthere\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n\nthe\\\nre\n")) == [(0, "hi"), (3, "there")]
    assert list(line_reader("hi\n\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n# comment\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\n# comment\\\nthere\\\n")) == [(0, "hi"), (2, "there")]
    assert list(line_reader("hi\nthere\\\n# comment")) == [
        (0, "hi"),
        (2, "there# comment"),
    ]
    assert not list(line_reader(""))
    assert not list(line_reader(" #comment\n# comment\n  #  comment 2\n\n"))
    assert list(line_reader("\n\nhi\n\nthere")) == [(2, "hi"), (4, "there")]
    assert list(line_reader("  \\\n\nhi\n\nthere")) == [(2, "hi"), (4, "there")]
    assert list(line_reader("\\\nhi\n\nthere")) == [(1, "hi"), (3, "there")]


@pytest.mark.unit
def test_format_simple():
    """Test simple str.format fill-in works correctly"""

    assert format_simple("hello world") == "hello world"
    assert format_simple("he{{llo wor}}ld") == "he{llo wor}ld"
    assert format_simple("he{cool}ld", cool="beans") == "hebeansld"
    assert format_simple("he{ cool}ld", cool="beans") == "hebeansld"
    assert format_simple("he{cool }ld", cool="beans") == "hebeansld"
    assert format_simple("he{ cool }ld", cool="beans") == "hebeansld"

    with pytest.raises(KeyError):
        format_simple("did not pass {bar} field", foo="hi")

    # No nested expansions
    assert format_simple("{foo}{bar}", foo="{bar}", bar="{foo}") == "{bar}{foo}"

    with pytest.raises(KeyError):
        format_simple("cannot do {foo.__class__}", foo="hi")

    assert (
        format_simple("can do {foo.__class__}", **{"foo.__class__": "this"})
        == "can do this"
    )
