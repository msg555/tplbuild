import contextlib
import os
import shutil
import tempfile
from argparse import Namespace
from typing import Optional

import pytest

from tplbuild.cmd.base_build import BaseBuildUtility
from tplbuild.cmd.build import BuildUtility
from tplbuild.config import UserConfig
from tplbuild.tplbuild import TplBuild

BUILD_DATA_PATH = os.path.join(os.path.dirname(__file__), "builds")
TEST_CLIENT_TYPE = os.getenv("TEST_CLIENT_TYPE", "docker")
TEST_BASE_IMAGE_NAME = os.getenv("TEST_BASE_IMAGE_NAME", "localhost:8000/base")


@contextlib.asynccontextmanager
async def setup_build_test(name: str, user_config: Optional[UserConfig] = None):
    """Create the TplBuild object with default settings for the named build."""
    user_config = user_config or UserConfig(client_type=TEST_CLIENT_TYPE)
    with tempfile.TemporaryDirectory() as temp_dir:
        dst_dir = os.path.join(temp_dir, "data")
        shutil.copytree(
            os.path.join(BUILD_DATA_PATH, name),
            dst_dir,
            symlinks=True,
        )
        async with TplBuild.from_path(dst_dir, user_config=user_config) as tplbld:
            tplbld.config.base_image_repo = TEST_BASE_IMAGE_NAME
            yield dst_dir, tplbld


@pytest.mark.build
async def test_smartcopy():
    """Test that the smartcopy build works as expected."""
    params = dict(
        image=[], profile=[], platform=[], update_salt=False, update_sources=False
    )
    async with setup_build_test("smartcopy") as (base_dir, tplbld):
        result = await BaseBuildUtility().main(
            Namespace(**params, check=False),
            tplbld,
        )
        assert result == 0

        # Change file not used by base image, ensure check passes
        with open(os.path.join(base_dir, "someotherfile.txt"), "wb") as fdata:
            fdata.write(b"something something\n")
        result = await BaseBuildUtility().main(
            Namespace(**params, check=True),
            tplbld,
        )
        assert result == 0

        # Change file used by base image, ensure check fails
        with open(os.path.join(base_dir, "abc"), "wb") as fdata:
            fdata.write(b"abcdata\n")
        result = await BaseBuildUtility().main(
            Namespace(**params, check=True),
            tplbld,
        )
        assert result != 0

        # Restore file data used by base image, ensure check passes
        with open(os.path.join(base_dir, "abc"), "wb") as fdata:
            fdata.write(b"abc\n")
        result = await BaseBuildUtility().main(
            Namespace(**params, check=True),
            tplbld,
        )
        assert result == 0

        # Restore file data used by base image, ensure check passes
        with open(os.path.join(base_dir, "abc"), "wb") as fdata:
            fdata.write(b"abc\n")
        result = await BuildUtility().main(
            Namespace(**params),
            tplbld,
        )
        assert result == 0


@pytest.mark.build
async def test_multifile():
    """Test that the multifile build works as expected."""
    params = dict(image=[], profile=[], platform=[])
    async with setup_build_test("multifile") as (_, tplbld):
        result = await BuildUtility().main(
            Namespace(**params),
            tplbld,
        )
        assert result == 0
