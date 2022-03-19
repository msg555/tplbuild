import argparse
import asyncio
import json
import logging
import os
import ssl
import sys
from typing import Callable, Mapping

from aioregistry import AsyncRegistryClient, DockerCredentialStore

from tplbuild.cmd.base_build import BaseBuildUtility
from tplbuild.cmd.base_lookup import BaseLookupUtility
from tplbuild.cmd.build import BuildUtility
from tplbuild.cmd.publish import PublishUtility
from tplbuild.cmd.source_lookup import SourceLookupUtility
from tplbuild.cmd.source_update import SourceUpdateUtility
from tplbuild.cmd.utility import CliUtility
from tplbuild.exceptions import TplBuildException
from tplbuild.tplbuild import TplBuild

LOGGER = logging.getLogger(__name__)

ALL_UTILITIES: Mapping[str, Callable[[], CliUtility]] = {
    "build": BuildUtility,
    "base-build": BaseBuildUtility,
    "base-lookup": BaseLookupUtility,
    "publish": PublishUtility,
    "source-lookup": SourceLookupUtility,
    "source-update": SourceUpdateUtility,
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
    parser.add_argument(
        "-C",
        "--base-dir",
        required=False,
        default=".",
        help="Base directory for tplbuild",
    )
    parser.add_argument(
        "--auth-config",
        required=False,
        default=os.path.expanduser("~/.docker/config.json"),
        help="Path to Docker credential config file",
    )
    parser.add_argument(
        "--insecure",
        required=False,
        const=True,
        action="store_const",
        default=False,
        help="Disable server certificate verification",
    )
    parser.add_argument(
        "--cafile",
        required=False,
        default=None,
        help="SSL context CA file",
    )
    parser.add_argument(
        "--capath",
        required=False,
        default=None,
        help="SSL context CA directory",
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


def create_registry_client(args) -> AsyncRegistryClient:
    """Create an AsyncRegistryClient context from the passed arguments."""
    creds = None
    if args.auth_config:
        with open(args.auth_config, "r", encoding="utf-8") as fauth:
            creds = DockerCredentialStore(json.load(fauth))

    ssl_ctx = ssl.create_default_context(
        cafile=args.cafile,
        capath=args.capath,
    )
    if args.insecure:
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

    return AsyncRegistryClient(creds=creds, ssl_context=ssl_ctx)


def create_tplbld(args, registry_client: AsyncRegistryClient) -> TplBuild:
    """Create a TplBuild context from the passed arguments."""
    return TplBuild.from_path(args.base_dir, registry_client=registry_client)


async def amain() -> int:
    """Parse CLI options, setup logging, then invoke the requested utility"""
    utilities = {
        subcommand: utility_cls() for subcommand, utility_cls in ALL_UTILITIES.items()
    }

    parser = argparse.ArgumentParser(description="templated build tool")
    setup_parser(parser, utilities)
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        async with create_registry_client(args) as registry_client:
            async with create_tplbld(args, registry_client) as tplbld:
                return await utilities[args.utility].main(args, tplbld)
    except TplBuildException as exc:
        sys.stderr.write(f"{exc}\n")
        if exc.more_message:
            sys.stderr.write(f"{exc.more_message}\n")
        LOGGER.debug("got top level tplbuild exception", exc_info=True)
        return 1
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected top-level exception")
        return 2


def main() -> int:
    """Synchronous entry point"""
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
