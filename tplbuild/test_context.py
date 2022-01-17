import contextlib
import io
import os
import re
import tarfile
import tempfile
from typing import Optional

import pytest

from .context import BuildContext, _create_pattern, _create_pattern_part


@contextlib.contextmanager
def set_umask(msk):
    """Set the umask in a context manager"""
    prev_msk = os.umask(msk)
    try:
        yield
    finally:
        os.umask(prev_msk)


def make_test(base_dir: str, mode: int, testdata, path: Optional[str] = None) -> None:
    """
    Create a file hierarchy for testing.

    Arguments:
        mode: the access mode that the root file should be created with.
        testdata:
            - If a dictionary then the root file will be a directory
              with children file names given by the keys of the dictionary
              and the values being tuples of access modes and recursive
              testdata structures that indicate how to create those sub files.
            - Otherwise should be a 'bytes' object giving the data to write
              to the file.
        path: The path to write the file hiearchy. If `path` is None
              it will use the tempdir path.
    """
    if isinstance(testdata, dict):
        if path is None:
            os.chmod(base_dir, mode)
        else:
            os.mkdir(path, mode)

        path = path or base_dir
        for subfile, subfile_data in testdata.items():
            make_test(base_dir, *subfile_data, path=os.path.join(path, subfile))  # type: ignore
    else:
        assert path is not None
        assert isinstance(testdata, bytes)
        with open(os.open(path, os.O_CREAT | os.O_WRONLY, mode), "wb") as fout:
            fout.write(testdata)


@pytest.mark.unit
def test_create_pattern_part():
    """Test _create_pattern_part functionality"""
    no_sep = f"[^{re.escape(os.path.sep)}]"
    pass_tests = {
        "**": (".*", False),
        "?": (f"/{no_sep}?", False),
        "*": (f"/{no_sep}*", False),
        "hello world": (r"/hello\ world", True),
        r"hello\[world": (r"/hello\[world", True),
        "[^^]": (r"/[^\^]", False),
        "[^a-b]": ("/[^a-b]", False),
        r"[\^\]]": (r"/[\^\]]", False),
        "_[ab-yz]?.*": (f"/_[ab-yz]{no_sep}?\\.{no_sep}*", False),
        ".{ }^|": (r"/\.\{\ \}\^\|", True),
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
        assert actual_pat == expected_pat.replace("/", os.path.sep)
        assert actual_simple == expected_simple

    for path_pat, value_err_str in value_error_tests.items():
        try:
            _create_pattern_part(path_pat)
            assert False, "expected ValueError thrown"
        except ValueError as exc:
            assert str(exc) == value_err_str


@pytest.mark.unit
def test_create_pattern():
    """Test _create_pattern functionality"""
    pass_tests = {
        ("a/b/*.c", True): dict(
            yes=["/a", "/a/b", "/a/b/x.c", "/a/b/y.c/d"],
            no=["/a/b/x.d", "/a/x.c", "/b", "/a/b/x.cd", "/ab", "/a/b/cc"],
        ),
        ("a/b/*.c", False): dict(
            yes=["/a/b/x.c", "/a/b/y.c/d"],
            no=["/a", "/a/b", "/a/b/x.d", "/a/x.c", "/b", "/a/b/x.cd", "/ab"],
        ),
        ("a/**/b", True): dict(
            yes=["/a/b", "/a/c/b", "/a/c/d/b", "/a/c/d/b/e"],
            no=["/a", "/b", "/a/c"],
        ),
        ("a/*/b", True): dict(
            yes=["/a/c/b", "/a/c/b/e"],
            no=["/a", "/b", "/a/c", "/a/b", "/a/c/d/b"],
        ),
    }

    for (path_pat, match_prefix), expected in pass_tests.items():
        pat = re.compile(
            _create_pattern(path_pat.replace("/", os.path.sep), match_prefix)
        )
        for yes_pat in expected["yes"]:
            assert pat.search(
                yes_pat.replace("/", os.path.sep)
            ), f"{path_pat},{match_prefix} should match {yes_pat}"
        for no_pat in expected["no"]:
            assert not pat.search(
                no_pat.replace("/", os.path.sep)
            ), f"{path_pat},{match_prefix} unexpectedly matched {no_pat}"

    pytest.raises(ValueError, _create_pattern, "a/[/]", True)


@pytest.mark.io
@set_umask(0)
def test_write_context():
    """Test writing a files context and hashing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        make_test(
            tmpdir,
            0o777,
            {
                "subdir": (
                    0o777,
                    {
                        "bar.txt": (0o600, b"wow\n"),
                        "bar.c": (0o600, b"stuff\n"),
                        "baz.c": (
                            0o751,
                            {
                                "deepfile": (0o752, b"deepdata\n"),
                                "oth": (0o752, b"othdata\n"),
                            },
                        ),
                    },
                ),
                "data.c": (0o731, b"nice\n"),
            },
        )

        ctx = BuildContext(tmpdir, 0o022, [])
        assert (
            ctx.full_hash
            == "595b212d34c969979978e87128f79f645088057007894a5457e89b5455ecd64a"
        )
        assert len(ctx.symbolic_hash) == 64

        iob = io.BytesIO()
        ctx.write_context(iob, extra_files={"./abc": (0o642, b"abcdata")})
        iob.seek(0)
        with tarfile.open(fileobj=iob) as tf:
            assert tf.getnames() == [
                ".",
                "./data.c",
                "./subdir",
                "./subdir/bar.c",
                "./subdir/bar.txt",
                "./subdir/baz.c",
                "./subdir/baz.c/deepfile",
                "./subdir/baz.c/oth",
                "./abc",
            ]

            # Check that file exists and had its metadata updated appropriately
            ti = tf.getmember("./data.c")
            assert ti.isreg()
            assert ti.uid == 0 and ti.gid == 0
            assert ti.mode == 0o755
            with tf.extractfile(ti) as tfile:
                assert tfile.read() == b"nice\n"

            ti = tf.getmember("./abc")
            assert ti.isreg()
            assert ti.uid == 0 and ti.gid == 0
            assert ti.mode == 0o644
            with tf.extractfile(ti) as tfile:
                assert tfile.read() == b"abcdata"

            # Check the same for a directory

            # Check the same for a directory
            ti = tf.getmember("./subdir/baz.c")
            assert ti.isdir()
            assert ti.uid == 0 and ti.gid == 0
            assert ti.mode == 0o755

        # Try again with None as the umask
        ctx = BuildContext(tmpdir, None, [])
        assert (
            ctx.full_hash
            == "eefa5a6389c48985a4cd4a4eeb7b59d653ac29502e87d9525c9d6a533498c76c"
        )
        assert len(ctx.symbolic_hash) == 64

        iob = io.BytesIO()
        ctx.write_context(iob)
        iob.seek(0)
        with tarfile.open(fileobj=iob) as tf:
            assert tf.getnames() == [
                ".",
                "./data.c",
                "./subdir",
                "./subdir/bar.c",
                "./subdir/bar.txt",
                "./subdir/baz.c",
                "./subdir/baz.c/deepfile",
                "./subdir/baz.c/oth",
            ]

            # Check that file exists and had its metadata updated appropriately
            ti = tf.getmember("./data.c")
            assert ti.isreg()
            assert ti.uid == 0 and ti.gid == 0
            assert ti.mode == 0o731
            with tf.extractfile(ti) as tfile:
                assert tfile.read() == b"nice\n"

            # Check the same for a directory
            ti = tf.getmember("./subdir/baz.c")
            assert ti.isdir()
            assert ti.uid == 0 and ti.gid == 0
            assert ti.mode == 0o751

        # Try one more time with ignore patterns
        ctx = BuildContext(tmpdir, 0o022, ["**/*.c", "!subdir/baz.c/deepfile"])
        assert (
            ctx.full_hash
            == "558ca8796a779d4b71742e7a53e8bd03891765c75328bf1b47ebda77666458f3"
        )
        assert len(ctx.symbolic_hash) == 64

        iob = io.BytesIO()
        ctx.write_context(iob)
        iob.seek(0)
        with tarfile.open(fileobj=iob) as tf:
            assert tf.getnames() == [
                ".",
                "./subdir",
                "./subdir/bar.txt",
                "./subdir/baz.c",
                "./subdir/baz.c/deepfile",
            ]

            # Check that file exists and had its metadata updated appropriately
            ti = tf.getmember("./subdir/bar.txt")
            assert ti.isreg()
            assert ti.uid == 0 and ti.gid == 0
            assert ti.mode == 0o644
            with tf.extractfile(ti) as tfile:
                assert tfile.read() == b"wow\n"

            # Check the same for a directory
            ti = tf.getmember("./subdir/baz.c")
            assert ti.isdir()
            assert ti.uid == 0 and ti.gid == 0
            assert ti.mode == 0o755


@pytest.mark.io
def test_null_context():
    """Test using a null context"""
    ctx = BuildContext(None, 0o022, [])

    assert (
        ctx.full_hash
        == "c4a048099cc72f0af94df1e9220c21551505d8b66ef533766e06bd897d19aea4"
    )

    iob = io.BytesIO()
    ctx.write_context(iob)
    iob.seek(0)
    with tarfile.open(fileobj=iob) as tf:
        assert tf.getnames() == ["."]

        ti = tf.getmember(".")
        assert ti.isdir()
        assert ti.mode == 0o755

    iob = io.BytesIO()
    ctx.write_context(
        iob, extra_files={"./abc": (0o742, b"abcdata"), "./def": (0o600, b"defdata")}
    )
    iob.seek(0)
    with tarfile.open(fileobj=iob) as tf:
        assert tf.getnames() == [".", "./abc", "./def"]

        ti = tf.getmember(".")
        assert ti.isdir()
        assert ti.uid == 0 and ti.gid == 0
        assert ti.mode == 0o755

        ti = tf.getmember("./abc")
        assert ti.isreg()
        assert ti.uid == 0 and ti.gid == 0
        assert ti.mode == 0o755
        with tf.extractfile(ti) as tfile:
            assert tfile.read() == b"abcdata"

        ti = tf.getmember("./def")
        assert ti.isreg()
        assert ti.uid == 0 and ti.gid == 0
        assert ti.mode == 0o644
        with tf.extractfile(ti) as tfile:
            assert tfile.read() == b"defdata"
