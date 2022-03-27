import argparse
import uuid
from typing import List

from tplbuild.cmd.utility import CliUtility
from tplbuild.exceptions import TplBuildException
from tplbuild.images import StageData
from tplbuild.tplbuild import TplBuild


class BaseBuildUtility(CliUtility):
    """CLI utility entrypoint for building base images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "image",
            nargs="*",
            help="Base image stage names to build. Defaults to all base stages",
        )
        parser.add_argument(
            "--profile",
            action="append",
            help="Profile to build, can be given multiple times. Defaults to all profiles.",
        )
        parser.add_argument(
            "--platform",
            action="append",
            help="Platforms to build, may be specified multiple times. Defaults to all platforms",
        )
        parser.add_argument(
            "--update-sources",
            default=False,
            const=True,
            action="store_const",
            help="If set the digest for each source image will be updated",
        )
        parser.add_argument(
            "--update-salt",
            default=False,
            const=True,
            action="store_const",
            help="Update salt forcing base images to be rebuilt",
        )
        parser.add_argument(
            "--check",
            required=False,
            const=True,
            default=False,
            action="store_const",
            help="Only verify that all requested base images are already built",
        )

    async def main(self, args, tplbld: TplBuild) -> int:
        images = set(args.image)
        profiles = args.profile or list(tplbld.config.profiles)
        platforms = args.platform or tplbld.config.platforms

        if args.update_salt:
            tplbld.build_data.hash_salt = str(uuid.uuid4())

        # Render all build stages
        stages_to_build: List[StageData] = []
        for profile in profiles:
            for platform in platforms:
                stage_mapping = await tplbld.render(profile=profile, platform=platform)
                stages_to_build.extend(
                    stage_data
                    for stage_name, stage_data in stage_mapping.items()
                    if stage_data.base_image is not None
                    and (not images or stage_name in images)
                )

        if args.check and args.update_sources:
            raise TplBuildException("Cannot pass --check and --update-sources")

        # Resolve the locked source image manifest content address from cached
        # build data.
        await tplbld.resolve_source_images(
            stages_to_build,
            check_only=args.check,
            force_update=args.update_sources,
        )

        # Replace BaseImage nodes in the build graph with their underlying
        # build definition.
        await tplbld.resolve_base_images(stages_to_build, dereference=True)

        # Create a plan of build operations to execute the requested build.
        build_ops = tplbld.plan(stages_to_build)
        if args.check:
            if not build_ops:
                return 0
            print(f"Needed {len(build_ops)} build operations")
            return 1

        # Execute the build operations.
        await tplbld.build(build_ops)

        return 0
