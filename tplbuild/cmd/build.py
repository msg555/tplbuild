import argparse

from tplbuild.cmd.utility import CliUtility
from tplbuild.tplbuild import TplBuild


class BuildUtility(CliUtility):
    """CLI utility entrypoint for building top-level images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        # Add support for
        #   --profile xyz (default to default profile)
        #   --image xyz (repeatable)
        #   --multi-platform
        pass

    async def main(self, args, tplbld: TplBuild) -> int:
        # Render all build stages
        stage_mapping = tplbld.render()

        # Only explicitly build stages that have tags/push_tags associated with them.
        # Anything else that is needed will be included implicitly in the build graph.
        stages_to_build = [
            stage for stage in stage_mapping.values() if stage.tags or stage.push_tags
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
