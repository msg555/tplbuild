import argparse
import asyncio
import logging
import sys
from typing import Callable, Mapping

from tplbuild.cmd.base_build import BaseBuildUtility
from tplbuild.cmd.base_lookup import BaseLookupUtility
from tplbuild.cmd.build import BuildUtility
from tplbuild.cmd.utility import CliUtility
from tplbuild.exceptions import TplBuildException
from tplbuild.tplbuild import TplBuild

LOGGER = logging.getLogger(__name__)

ALL_UTILITIES: Mapping[str, Callable[[], CliUtility]] = {
    "build": BuildUtility,
    "base-build": BaseBuildUtility,
    "base-lookup": BaseLookupUtility,
}


def setup_parser(
    parser: argparse.ArgumentParser, utilities: Mapping[str, CliUtility]
) -> None:
    """Setup the argument parser configuration for each utility."""
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
    )

    subparsers = parser.add_subparsers(
        required=True,
        dest="utility",
        help="what tplbuild sub-utility to invoke",
    )

    for subcommand, utility in utilities.items():
        utility.setup_parser(subparsers.add_parser(subcommand))


def setup_logging(verbose: int) -> None:
    """Setup tplbuild default logging based on the verbosity level"""
    internal_level, external_level = logging.WARNING, logging.CRITICAL
    if verbose > 2:
        internal_level, external_level = logging.DEBUG, logging.INFO
    elif verbose > 1:
        internal_level, external_level = logging.DEBUG, logging.WARNING
    elif verbose:
        internal_level, external_level = logging.INFO, logging.ERROR

    tplbuild_root = logging.getLogger("tplbuild")
    tplbuild_root.propagate = False
    tplbuild_root.setLevel(internal_level)

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(levelname)s: %(message)s"),
    )
    tplbuild_root.addHandler(handler)

    logging.basicConfig(
        format="%(levelname)s(%(module)s): %(message)s",
        level=external_level,
    )


def create_tplbld(args) -> TplBuild:
    """Create a TplBuild context from the passed arguments."""
    # pylint: disable=unused-argument
    return TplBuild.from_path(".")


async def main() -> int:
    """Parse CLI options, setup logging, then invoke the requested utility"""
    utilities = {
        subcommand: utility_cls() for subcommand, utility_cls in ALL_UTILITIES.items()
    }

    parser = argparse.ArgumentParser(description="templated build tool")
    setup_parser(parser, utilities)
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        return await utilities[args.utility].main(
            args,
            create_tplbld(args),
        )
    except TplBuildException as exc:
        sys.stderr.write(f"{exc}\n")
        LOGGER.debug("got top level tplbuild exception", exc_info=True)
        return 1
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected top-level exception")
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
