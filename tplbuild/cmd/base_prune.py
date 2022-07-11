import argparse
import asyncio
import collections
import json
import os
from typing import Dict, Set

from aioregistry import RegistryException, parse_image_name

from tplbuild.cmd.utility import CliUtility
from tplbuild.config import BuildData
from tplbuild.exceptions import TplBuildException
from tplbuild.images import BaseImage
from tplbuild.tplbuild import TplBuild


async def _run_git_command(*args):
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode:
            raise TplBuildException("git command failed")
        return stdout.decode("utf-8")
    except OSError as exc:
        raise TplBuildException("git command failed") from exc


class BasePruneUtility(CliUtility):
    """CLI utility entrypoint for building base images"""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.description = (
            "Remove base images not referenced by a passed git commit. "
            "Images deleted cannot be recovered without rebuilding."
        )
        parser.add_argument(
            "git_commits",
            nargs="*",
            help="A list of git commits to preserve base images",
        )
        parser.add_argument(
            "--force",
            required=False,
            const=True,
            default=False,
            action="store_const",
            help="Do not prompt for confirmation",
        )

    def _collect_build_data(
        self, tplbld: TplBuild, build_data: BuildData, known_tags: Dict[str, Set[str]]
    ) -> None:
        """
        Add all known tags in the build data.
        """
        for profile, bases_for_profile in build_data.base.items():
            for stage, bases_for_stage in bases_for_profile.items():
                for platform, base_data in bases_for_stage.items():
                    base_image = BaseImage(
                        profile=profile,
                        stage=stage,
                        platform=platform,
                        content_hash=base_data.build_hash,
                    )
                    image_ref = parse_image_name(tplbld.get_base_image_name(base_image))
                    known_tags[image_ref.name(include_ref=False)].add(image_ref.ref)

    async def main(self, args, tplbld: TplBuild) -> int:
        """TODO"""

        known_tags: Dict[str, Set[str]] = collections.defaultdict(set)

        # Always collect the current base image build data
        self._collect_build_data(tplbld, tplbld.build_data, known_tags)

        # Collect base image build data from each git commit passed.
        if args.git_commits:
            git_path = (
                await _run_git_command(
                    "git",
                    "ls-files",
                    "--full-name",
                    os.path.join(tplbld.base_dir, ".tplbuilddata.json"),
                )
            ).rstrip()

            for commit in args.git_commits:
                build_data_json = await _run_git_command(
                    "git", "show", f"{commit}:{git_path}"
                )
                build_data = BuildData(**json.loads(build_data_json))
                self._collect_build_data(tplbld, build_data, known_tags)

        refs_to_delete = []
        for repo, repo_tags in known_tags.items():
            image_ref = parse_image_name(repo)
            tags = await tplbld.registry_client.registry_repo_tags(
                image_ref.registry, image_ref.repo
            )

            for tag in tags:
                if tag not in repo_tags:
                    refs_to_delete.append(image_ref.copy(update=dict(ref=tag)))

        if not refs_to_delete:
            print("Nothing to delete")
            return 0

        print(f"Going to delete {len(refs_to_delete)} tags")
        if not args.force:
            for ref in refs_to_delete:
                print(f"  {ref}")

            data = input("Delete tags [yN]: ")
            if data not in ("y", "Y"):
                return 1

        delete_sem = asyncio.BoundedSemaphore(8)

        async def _delete_ref(ref) -> bool:
            async with delete_sem:
                delete_okay = False
                try:
                    delete_okay = await tplbld.registry_client.ref_delete(ref)
                    if delete_okay:
                        print(f"Deleted ref {ref}")
                    else:
                        print(f"Failed to delete ref {ref}")
                except RegistryException as exc:
                    print(f"Failed to delete ref {ref}: {exc}")
            return delete_okay

        result = await asyncio.gather(*(_delete_ref(ref) for ref in refs_to_delete))
        return 0 if all(result) else 1
