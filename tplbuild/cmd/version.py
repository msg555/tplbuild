import argparse

from tplbuild._version import __version__ as version
from tplbuild.cmd.utility import CliUtility
from tplbuild.tplbuild import TplBuild


class VersionUtility(CliUtility):
    """CLI utility entrypoint for building base images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.description = "Print tplbuild version information"

    async def main(self, args, tplbld: TplBuild) -> int:
        """Just print the current tplbuild version"""

        print(version)
        return 0
