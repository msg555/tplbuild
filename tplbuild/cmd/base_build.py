import argparse

from tplbuild.cmd.utility import CliUtility
from tplbuild.tplbuild import TplBuild


class BaseBuildUtility(CliUtility):
    """CLI utility entrypoint for building base images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        # Add support for
        #   --profile xyz (default to all profiles)
        #   --image xyz (repeatable)
        #   --check
        pass

    async def main(self, args, tplbld: TplBuild) -> int:
        # Render all build stages
        stage_mapping = tplbld.render()

        # Only build base image stages
        stages_to_build = [
            stage for stage in stage_mapping.values() if stage.base_image is not None
        ]

        # Resolve the locked source image manifest content address from cached
        # build data.
        await tplbld.resolve_source_images(stages_to_build)

        # Replace BaseImage nodes in the build graph with their underlying
        # build definition.
        await tplbld.resolve_base_images(stages_to_build, dereference=True)

        # Create a plan of build operations to execute the requested build.
        build_ops = tplbld.plan(stages_to_build)

        # Execute the build operations.
        await tplbld.build(build_ops)

        return 0
