import argparse
import dataclasses
from typing import Dict

from tplbuild.cmd.utility import CliUtility
from tplbuild.exceptions import TplBuildException
from tplbuild.images import MultiPlatformImage, StageData
from tplbuild.tplbuild import TplBuild


class PublishUtility(CliUtility):
    """CLI utility entrypoint for building and publishing top-level images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "image",
            nargs="*",
            help="Images to build. Use 'stage_name=target_name' to "
            "override the default push name for stage_name or "
            "'stage_name=' to push the image as its stage name",
        )
        parser.add_argument(
            "--profile",
            required=False,
            default=None,
            help="Profile to build. Defaults to default profile.",
        )
        parser.add_argument(
            "--platform",
            action="append",
            help="Platform to build images for. Can be given multiple times. "
            "Defaults to all configured platforms.",
        )

    async def main(self, args, tplbld: TplBuild) -> int:
        profile = args.profile or tplbld.config.default_profile
        platforms = args.platform or tplbld.config.platforms

        # Render all build stages
        multi_stage_mapping: Dict[str, StageData] = {}
        for platform in platforms:
            stage_mapping = await tplbld.render(
                profile=profile,
                platform=platform,
            )
            for stage_name, stage_data in stage_mapping.items():
                stage_data.config.image_names.clear()
                multi_stage = multi_stage_mapping.setdefault(stage_name, stage_data)

                if multi_stage is stage_data:
                    multi_stage.image = MultiPlatformImage(
                        stage_descs={
                            dataclasses.replace(desc, platform="*")
                            for desc in getattr(stage_data.image, "stage_descs", ())
                        },
                        images={platform: stage_data.image},
                    )
                    continue

                if multi_stage.config.push_names != stage_data.config.push_names:
                    raise TplBuildException(
                        "Push names must match for all platforms for stage {repr(stage_name)}"
                    )
                assert isinstance(multi_stage.image, MultiPlatformImage)
                multi_stage.image.images[platform] = stage_data.image

        # Simplify any MultiPlatformImages that only have one platform.
        for stage_data in multi_stage_mapping.values():
            assert isinstance(stage_data.image, MultiPlatformImage)
            if len(stage_data.image.images) == 1:
                stage_data.image = next(iter(stage_data.image.images.values()))

        # Figure out what images to build, override push_names where requested.
        images_to_build = set()
        for image_arg in args.image:
            image_parts = image_arg.split("=", maxsplit=1)
            images_to_build.add(image_parts[0])
            if image_parts[0] not in multi_stage_mapping:
                raise TplBuildException(f"Unknown build stage {repr(image_parts[0])}")
            if len(image_parts) > 1:
                multi_stage_mapping[image_parts[0]].config.push_names = [
                    image_parts[1] or image_parts[0],
                ]

        # Only explicitly build stages that have push_names associated with them.
        # Anything else that is needed will be included implicitly in the build graph.
        stages_to_build = [
            stage
            for stage_name, stage in multi_stage_mapping.items()
            if stage.config.push_names
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
