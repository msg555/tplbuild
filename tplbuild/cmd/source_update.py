import argparse

from tplbuild.cmd.utility import CliUtility
from tplbuild.exceptions import TplBuildNoSourceImageException
from tplbuild.images import SourceImage
from tplbuild.tplbuild import TplBuild


class SourceUpdateUtility(CliUtility):
    """CLI utility entrypoint for updating source images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "source",
            nargs="*",
            help="Source images to update in repo:tag format",
        )
        parser.add_argument(
            "--platform",
            action="append",
            help="Platforms to update, may be specified multiple times. Defaults to all platforms",
        )
        parser.add_argument(
            "--clear",
            required=False,
            const=True,
            default=False,
            action="store_const",
            help="Clear any existing cached source image digests",
        )

    async def main(self, args, tplbld: TplBuild) -> int:
        if args.clear:
            tplbld.build_data.source.clear()

        source_images = set()
        for image in args.source:
            colon = image.find(":")
            if colon == -1:
                repo, tag = image, "latest"
            else:
                repo, tag = image[:colon], image[colon + 1 :]
            source_images.add((repo, tag))

        platforms = args.platform or tplbld.config.platforms
        for repo, tag in source_images:
            for platform in platforms:
                image = SourceImage(repo=repo, tag=tag, platform=platform)
                try:
                    prev_digest = (
                        await tplbld.resolve_image(image, check_only=True)
                    ).digest
                except TplBuildNoSourceImageException:
                    prev_digest = None

                new_digest = (
                    await tplbld.resolve_image(
                        SourceImage(repo=repo, tag=tag, platform=platform),
                        force_update=True,
                    )
                ).digest

                print(f"Updated {repo}:{tag} for {platform}")
                print(f"  {prev_digest} -> {new_digest}")

        tplbld.save_build_data()

        return 0
