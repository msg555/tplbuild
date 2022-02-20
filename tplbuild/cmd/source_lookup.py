import argparse

from tplbuild.cmd.utility import CliUtility
from tplbuild.images import SourceImage
from tplbuild.tplbuild import TplBuild


class SourceLookupUtility(CliUtility):
    """CLI utility entrypoint for looking up source images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "source",
            nargs="*",
            help="Source images to update in repo:tag format",
        )
        parser.add_argument(
            "--platform",
            action="append",
            help="Platforms to lookup. Defautls to the current executor platform.",
        )
        parser.add_argument(
            "--digest-only",
            required=False,
            const=True,
            default=False,
            action="store_const",
            help="Only print the digest of the source images",
        )

    async def main(self, args, tplbld: TplBuild) -> int:
        platform = args.platform or await tplbld.get_default_platform()

        for image in args.source:
            colon = image.find(":")
            if colon == -1:
                repo, tag = image, "latest"
            else:
                repo, tag = image[:colon], image[colon + 1 :]
            resolved_image = await tplbld.resolve_image(
                SourceImage(repo=repo, tag=tag, platform=platform),
                check_only=True,
            )
            if args.digest_only:
                print(resolved_image.digest)
            else:
                print(f"{repo}@{resolved_image.digest}")

        return 0
