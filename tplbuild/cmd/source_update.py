import argparse

from aioregistry import parse_image_name

from tplbuild.cmd.utility import CliUtility
from tplbuild.exceptions import TplBuildException, TplBuildNoSourceImageException
from tplbuild.graph import visit_graph
from tplbuild.images import ImageDefinition, SourceImage
from tplbuild.tplbuild import TplBuild


class SourceUpdateUtility(CliUtility):
    """CLI utility entrypoint for updating source images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.description = (
            "explicitly update source image digests from their repositories"
        )
        parser.add_argument(
            "source",
            nargs="*",
            help="Source images to update in repo:tag format. "
            "Will update all source images if none provided.",
        )
        parser.add_argument(
            "--profile",
            action="append",
            help="Profiles to update, can be given multiple times. Defaults to all profiles.",
        )
        parser.add_argument(
            "--platform",
            action="append",
            help="Platforms to build, may be specified multiple times. Defaults to all platforms",
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

        profiles = args.profile or list(tplbld.config.profiles)
        platforms = args.platform or tplbld.config.platforms

        all_source_images = set()
        for profile in profiles:
            for platform in platforms:
                stage_mapping = await tplbld.render(profile=profile, platform=platform)
                for stage_data in stage_mapping.values():

                    def _add_source_image(img: ImageDefinition) -> ImageDefinition:
                        if isinstance(img, SourceImage):
                            all_source_images.add((img.repo, img.tag, img.platform))
                        return img

                    visit_graph(
                        [stage_data.image],
                        _add_source_image,
                    )

        source_images = set()
        for image in args.source:
            image_ref = parse_image_name(image)

            found_one = False
            for platform in platforms:
                img = (image_ref.name(include_ref=False), image_ref.ref, platform)
                if img in all_source_images:
                    found_one = True
                    source_images.add(img)
            if not found_one:
                raise TplBuildException(f"No source image {image_ref} referenced")

        if not source_images:
            source_images = all_source_images

        for repo, tag, platform in source_images:
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

            prev_digest = prev_digest or "<missing>"
            new_digest = new_digest or "<missing>"
            if new_digest == prev_digest:
                print(f"No update for {repo}:{tag} on {platform}")
            else:
                print(f"Updated {repo}:{tag} on {platform}")
                print(f"  {prev_digest} -> {new_digest[:32]}")

        tplbld.save_build_data()

        return 0
