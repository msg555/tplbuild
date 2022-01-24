import argparse
import sys

from tplbuild.cmd.utility import CliUtility
from tplbuild.tplbuild import TplBuild


class BaseLookupUtility(CliUtility):
    """CLI utility entrypoint for building base images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "image",
            nargs="*",
            help="The base image stage name to lookup",
        )
        parser.add_argument(
            "--profile",
            required=False,
            help="Profile to lookup the base image for",
        )
        parser.add_argument(
            "--platform",
            required=False,
            help="Platform to lookup the base image of. Defaults to current executor platform",
        )
        parser.add_argument(
            "--tag-only",
            required=False,
            const=True,
            default=False,
            action="store_const",
            help="Only print the image tag",
        )

    async def main(self, args, tplbld: TplBuild) -> int:
        """Print out all the base image names/tags requested"""
        platform = args.platform or await tplbld.get_default_platform()
        for stage_name in args.image:
            try:
                image_name, image = tplbld.lookup_base_image(
                    stage_name, platform, profile=args.profile
                )
            except KeyError:
                sys.stderr.write(f"could not find base image {repr(stage_name)}\n")
                return 1

            if args.tag_only:
                print(image.content_hash)
            else:
                print(image_name)

        return 0
