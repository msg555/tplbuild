import argparse

from tplbuild.cmd.utility import CliUtility
from tplbuild.exceptions import TplBuildException
from tplbuild.tplbuild import TplBuild


class BuildUtility(CliUtility):
    """CLI utility entrypoint for building top-level images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "image",
            nargs="*",
            help="Images to build. Use 'stage_name=target_name' to "
            "override the default image name for stage_name or "
            "'stage_name=' to use the stage name as the image name.",
        )
        parser.add_argument(
            "--profile",
            required=False,
            default=None,
            help="Profile to build. Defaults to default profile.",
        )
        parser.add_argument(
            "--platform",
            required=False,
            default=None,
            help="Platform to build images for. "
            "Defaults to current executor platform.",
        )

    async def main(self, args, tplbld: TplBuild) -> int:
        profile = args.profile or tplbld.config.default_profile

        # Render all build stages
        stage_mapping = await tplbld.render(
            profile=profile,
            platform=args.platform,
        )

        # Remove push names
        for stage_data in stage_mapping.values():
            stage_data.config.push_names.clear()

        # Figure out what images to build, override image_names where requested.
        images_to_build = set()
        for image_arg in args.image:
            image_parts = image_arg.split("=", maxsplit=1)
            images_to_build.add(image_parts[0])
            if image_parts[0] not in stage_mapping:
                raise TplBuildException(f"Unknown build stage {repr(image_parts[0])}")
            if len(image_parts) > 1:
                stage_mapping[image_parts[0]].config.image_names = [
                    image_parts[1] or image_parts[0],
                ]

        # Only explicitly build stages that have image_names associated with them.
        # Anything else that is needed will be included implicitly in the build graph.
        stages_to_build = [
            stage
            for stage_name, stage in stage_mapping.items()
            if stage.config.image_names
            and (not images_to_build or stage_name in images_to_build)
        ]

        # Resolve the locked source image manifest content address from cached
        # build data.
        await tplbld.resolve_source_images(stages_to_build)

        # Resolve BaseImage nodes' content_hash so that their prebuilt image
        # can be referenced correctly.
        await tplbld.resolve_base_images(stages_to_build, dereference=False)

        # Create a plan of build operations to execute the requested build.
        build_ops = tplbld.plan(stages_to_build)

        # Execute the build operations.
        await tplbld.build(build_ops)

        return 0
