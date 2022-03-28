import pytest

from .utils import line_reader


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
