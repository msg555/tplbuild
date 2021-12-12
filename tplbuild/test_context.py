import pytest
import os.path
import re

from .context import _create_pattern_part


def test_create_pattern_part():
    """Test _create_pattern_part functionality"""
    no_sep = f"[^{re.escape(os.path.sep)}]"
    pass_tests = {
        "**": (".*", False),
        "?": (f"{no_sep}?", False),
        "*": (f"{no_sep}*", False),
        "hello world": (r"hello\ world", True),
        r"hello\[world": (r"hello\[world", True),
        "[^^]": (r"[^\^]", False),
        "[^a-b]": ("[^a-b]", False),
        r"[\^\]]": (r"[\^\]]", False),
        "_[ab-yz]?.*": (f"_[ab-yz]{no_sep}?\\.{no_sep}*", False),
        ".{ }^": (r"\.\{\ \}\^", True),
    }
    value_error_tests = {
        "[hi": "Unclosed character class",
        "[hi\\]": "Unclosed character class",
        "hi\\": "Trailing escape character",
        "[hi\\": "Trailing escape character",
        "[^-c]": "Unexpected '-' in character class",
        "[a-b-c]": "Unexpected '-' in character class",
        "[b-a]": "Invalid character range",
        "[]": "Empty character class",
        "[^]": "Empty character class",
        "[a-]": "Unclosed character range",
        "[a[b]": "'[' in character class should be escaped",
        "hi]there": "Unmatched ']' should be escaped",
    }

    for path_pat, (expected_pat, expected_simple) in pass_tests.items():
        actual_pat, actual_simple = _create_pattern_part(path_pat)
        assert actual_pat == expected_pat
        assert actual_simple == expected_simple

    for path_pat, value_err_str in value_error_tests.items():
        try:
            _create_pattern_part(path_pat)
            assert False, "expected ValueError thrown"
        except ValueError as exc:
            assert str(exc) == value_err_str
