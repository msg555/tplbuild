import asyncio
import logging
import os
import sys
from argparse import SUPPRESS, ArgumentParser
from typing import Callable, Dict, Mapping

import yaml
from aioregistry import (
    AsyncRegistryClient,
    ChainedCredentialStore,
    CredentialStore,
    DockerCredentialStore,
    default_credential_store,
)

from tplbuild.cmd.base_build import BaseBuildUtility
from tplbuild.cmd.base_lookup import BaseLookupUtility
from tplbuild.cmd.base_prune import BasePruneUtility
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
    "base-prune": BasePruneUtility,
    "publish": PublishUtility,
    "source-lookup": SourceLookupUtility,
    "source-update": SourceUpdateUtility,
}


def create_main_parser(utilities: Mapping[str, CliUtility]) -> ArgumentParser:
    """Setup the argument parser configuration for each utility."""
    parents = [
        create_base_parser(),
        create_config_parser(),
    ]

    parser = ArgumentParser(
        description="templated build tool",
        parents=parents,
    )
    subparsers = parser.add_subparsers(
        required=True,
        dest="utility",
        help="what tplbuild sub-utility to invoke",
    )

    for subcommand, utility in utilities.items():
        utility.setup_parser(subparsers.add_parser(subcommand, parents=parents))

    return parser


def create_base_parser() -> ArgumentParser:
    """
    Create shared parser for basic CLI options.
    """
    parser = ArgumentParser(description="Base tplbuild options", add_help=False)
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=SUPPRESS,
    )
    parser.add_argument(
        "-C",
        "--base-dir",
        required=False,
        default=SUPPRESS,
        help="Base directory for tplbuild",
    )
    return parser


def create_config_parser() -> ArgumentParser:
    """
    Create shared parser that overrides user configuration tplbuild options.
    """
    parser = ArgumentParser(description="Use config options", add_help=False)
    parser.add_argument(
        "--auth-file",
        required=False,
        default=SUPPRESS,
        help="Path to the container auth file",
    )
    parser.add_argument(
        "--insecure",
        required=False,
        const=True,
        action="store_const",
        default=SUPPRESS,
        help="Disable server certificate verification",
    )
    parser.add_argument(
        "--cafile",
        required=False,
        default=SUPPRESS,
        help="SSL context CA file",
    )
    parser.add_argument(
        "--capath",
        required=False,
        default=SUPPRESS,
        help="SSL context CA directory",
    )
    parser.add_argument(
        "--load-default-certs",
        required=False,
        const=True,
        action="store_const",
        default=SUPPRESS,
        help="Load system default certs always",
    )
    parser.add_argument(
        "--build-jobs",
        required=False,
        default=SUPPRESS,
        help="Set max concurrent build jobs",
    )
    parser.add_argument(
        "--push-jobs",
        required=False,
        default=SUPPRESS,
        help="Set max concurrent push or pull jobs",
    )
    return parser


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
    """Load the user config. Override with settings from args as requested."""
    user_config_locations = {
        os.path.expanduser("~/.tplbuildconfig.yml"),
        os.path.join(args.base_dir, ".tplbuildconfig.yml"),
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
    if args.build_jobs is not None:
        if args.build_jobs <= 0:
            user_config.build_jobs = os.cpu_count() or 4
        else:
            user_config.build_jobs = args.build_jobs
    if args.push_jobs is not None:
        if args.build_jobs <= 0:
            user_config.push_jobs = os.cpu_count() or 4
        else:
            user_config.push_jobs = args.push_jobs
    return user_config


def create_registry_client(user_config: UserConfig) -> AsyncRegistryClient:
    """Create an AsyncRegistryClient context from the passed arguments."""
    creds: CredentialStore = default_credential_store()
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


def apply_default_args(args) -> None:
    """
    Apply default valeus to CLI arguments as needed. The normal default behavior
    of argparse does not work well with parsers shared across subparsers.
    """
    defaults = dict(
        verbose=0,
        base_dir=".",
        auth_file=None,
        insecure=False,
        cafile=None,
        capath=None,
        load_default_certs=False,
        build_jobs=None,
        push_jobs=None,
    )
    for key, val in defaults.items():
        setattr(args, key, getattr(args, key, val))


async def amain() -> int:
    """Parse CLI options, setup logging, then invoke the requested utility"""
    utilities = {
        subcommand: utility_cls() for subcommand, utility_cls in ALL_UTILITIES.items()
    }

    parser = create_main_parser(utilities)
    args = parser.parse_args()
    apply_default_args(args)
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
