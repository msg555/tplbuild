import abc
import argparse

from tplbuild.tplbuild import TplBuild


class CliUtility(metaclass=abc.ABCMeta):
    """Abstract utility base class"""

    @abc.abstractmethod
    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        """Allow the utility to set up its arg parser.

        Arguments:
            parser (argparse.ArgumentParser): the parser to setup arguments for.
        """

    @abc.abstractmethod
    async def main(self, args, tplbld: TplBuild) -> int:
        """Run utility with parsed args and the `tplbld` configuration.

        Returns:
            The utility exit code
        """
