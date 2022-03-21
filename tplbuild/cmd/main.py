import argparse
import asyncio
import logging
import os
import sys
from typing import Callable, Dict, Mapping

import yaml
from aioregistry import (
    AsyncRegistryClient,
    ChainedCredentialStore,
    DockerCredentialStore,
    default_credential_store,
)

from tplbuild.cmd.base_build import BaseBuildUtility
from tplbuild.cmd.base_lookup import BaseLookupUtility
from tplbuild.cmd.build import BuildUtility
from tplbuild.cmd.publish import PublishUtility
from tplbuild.cmd.source_lookup import SourceLookupUtility
from tplbuild.cmd.source_update import SourceUpdateUtility
from tplbuild.cmd.utility import CliUtility
from tplbuild.config import UserConfig
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
        "--auth-file",
        required=False,
        default=None,
        help="Path to the container auth file",
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
    parser.add_argument(
        "--load-default-certs",
        required=False,
        const=True,
        action="store_const",
        default=False,
        help="Load system default certs always",
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


def load_user_config(args) -> UserConfig:
    """Load the user config."""
    user_config_locations = {
        os.path.join(args.base_dir, ".tplbuildconfig.yml"),
        os.path.expanduser("~/.tplbuildconfig.yml"),
    }
    user_config_data: Dict = {}
    for user_config_path in user_config_locations:
        try:
            with open(user_config_path, encoding="utf-8") as fconfig:
                user_config_data.update(**yaml.safe_load(fconfig))
        except FileNotFoundError:
            continue
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            raise TplBuildException(f"Failed to load user config: {exc}") from exc
    try:
        user_config = UserConfig(**user_config_data)
    except ValueError as exc:
        raise TplBuildException(f"Failed to load user config: {exc}") from exc

    if args.auth_file:
        user_config.auth_file = args.auth_file
    if args.insecure:
        user_config.ssl_context.insecure = True
    if args.cafile:
        user_config.ssl_context.cafile = args.cafile
    if args.capath:
        user_config.ssl_context.capath = args.capath
    if args.load_default_certs:
        user_config.ssl_context.load_default_certs = True
    return user_config


def create_registry_client(user_config: UserConfig) -> AsyncRegistryClient:
    """Create an AsyncRegistryClient context from the passed arguments."""
    creds = default_credential_store()
    if user_config.auth_file:
        try:
            creds = ChainedCredentialStore(
                DockerCredentialStore.from_file(user_config.auth_file),
                creds,
            )
        except FileNotFoundError as exc:
            raise TplBuildException(
                f"could not open auth file {repr(user_config.auth_file)}"
            ) from exc

    return AsyncRegistryClient(
        creds=creds,
        ssl_context=user_config.ssl_context.create_context(),
    )


def create_tplbld(
    args, user_config: UserConfig, registry_client: AsyncRegistryClient
) -> TplBuild:
    """Create a TplBuild context from the passed arguments."""
    return TplBuild.from_path(
        args.base_dir, user_config=user_config, registry_client=registry_client
    )


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
        user_config = load_user_config(args)
        async with create_registry_client(user_config) as registry_client:
            async with create_tplbld(args, user_config, registry_client) as tplbld:
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
