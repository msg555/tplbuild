import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Iterable, Optional

from aioregistry import (
    AsyncRegistryClient,
    RegistryException,
    parse_image_name,
)
import yaml

from .config import (
    BuildData,
    TplConfig,
)
from .exceptions import TplBuildException
from .executor import BuildExecutor
from .images import (
    ImageDefinition,
    SourceImage,
)
from .plan import (
    BuildPlanner,
    BuildOperation,
)
from .render import (
    BuildRenderer,
    StageData,
)
from .utils import (
    open_and_swap,
    visit_graph,
)

LOGGER = logging.getLogger(__name__)


class TplBuild:
    """
    Container class for all top level build operations.

    Arguments:
        base_dir: The base directory of the build
        config: The build configuration
    """

    @classmethod
    def from_path(cls, base_dir: str) -> "TplBuild":
        """
        Create a TplBuild object from just the base directory. This will
        attempt to load a file named "tplbuild.yml" from within `base_dir`
        to load the configuration. If not found an empty configuration will
        be used.

        Arguments:
            base_dir: The base directory of the build
        """
        try:
            with open(
                os.path.join(base_dir, "tplbuild.yml"), encoding="utf-8"
            ) as fconfig:
                config = yaml.safe_load(fconfig)
        except FileNotFoundError:
            config = {}
        return TplBuild(base_dir, config)

    def __init__(
        self,
        base_dir: str,
        config: Dict[str, Any],
        *,
        registry_client: AsyncRegistryClient = None,
    ) -> None:
        self.base_dir = base_dir
        self.config = TplConfig(**config)
        self.planner = BuildPlanner()
        self.renderer = BuildRenderer(self.base_dir, self.config)
        self.executor = BuildExecutor(
            self.config.client, self.config.base_image_repo or ""
        )
        self.registry_client = registry_client or AsyncRegistryClient()
        try:
            with open(
                os.path.join(base_dir, ".tplbuilddata.json"), encoding="utf-8"
            ) as fbuilddata:
                self.build_data = BuildData(**json.load(fbuilddata))
        except FileNotFoundError:
            LOGGER.warning(".tplbuilddata.json not found, using empty bulid data")
            self.build_data = BuildData()

    def _get_config_data(
        self,
        config_name: Optional[str] = None,
        *,
        platform: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Returns the config data associated with the passed config name.
        """
        if config_name is None:
            config_name = self.config.default_config
            if config_name is None and self.config.configs:
                config_name = next(iter(self.config.configs))

        if config_name is None:
            # If no config was requested nor are any configured use an emtpy
            # configuration dictionary.
            config_data = {}
        else:
            try:
                config_data = self.config.configs[config_name]
            except KeyError as exc:
                raise TplBuildException(
                    f"Config {repr(config_name)} does not exist"
                ) from exc

        return {
            "config": config_data,
            "config_name": config_name,
            "platform": platform,
        }

    def render(
        self,
        config_name: Optional[str] = None,
        *,
        platform: Optional[str] = None,
    ) -> Dict[str, StageData]:
        """
        Render all contexts and stages into StageData.
        """
        return self.renderer.render(
            self._get_config_data(config_name, platform=platform)
        )

    def plan(self, stages: Iterable[StageData]) -> List[BuildOperation]:
        """
        Plan how to build the given list of stage names.
        """
        # pylint: disable=unused-argument,no-self-use
        return self.planner.plan(stages)

    async def build(self, build_ops: Iterable[BuildOperation]) -> None:
        """
        Execute the build operatoins.
        """
        await self.executor.build(build_ops)

    async def resolve_image(
        self,
        image: SourceImage,
        *,
        check_only=False,
        force_update=True,
    ) -> SourceImage:
        """
        Resolves a SourceImage returning a new SourceImage object with the
        digest field set. If digest is already set on `image` then this will
        just return `image` itself.

        Arguments:
            image: Source image definition to resolve
            check_only: Do not attempt to fetch the image if it is not cached.
                This will trigger a TplBuildException if the image is not available.
            force_update: Update the image digest even if it is locally cached
        """
        if image.digest is not None:
            return image

        manifest = self.build_data.source.get(image.repo, {}).get(image.tag)
        if manifest is None or force_update:
            if check_only:
                raise TplBuildException("Source image does not exist, check only")

        # Grab the latest digest for the given source image.
        manifest_ref = parse_image_name(image.repo)
        manifest_ref.ref = image.tag
        try:
            manifest_ref = await self.registry_client.manifest_resolve_tag(manifest_ref)
        except RegistryException as exc:
            raise TplBuildException("Failed to resolve source image") from exc

        # Save the result into our build data
        self.build_data.source.setdefault(image.repo, {})[image.tag] = manifest_ref.ref

        return SourceImage(
            repo=image.repo,
            tag=image.tag,
            digest=manifest_ref.ref,
        )

    async def resolve_source_images(self, stages: Dict[str, BuildOperation]) -> None:
        """
        Resolve the manifest digest for each source image in the build graph.
        """
        # Find all the source images first
        source_images = set()

        def _visit_image(image: ImageDefinition) -> ImageDefinition:
            if isinstance(image, SourceImage):
                source_images.add(image)
            return image

        visit_graph((stage.image for stage in stages.values()), _visit_image)

        # Resolve all images into self.build_data.source.
        async with self.registry_client:
            source_image_map = dict(
                zip(
                    source_images,
                    await asyncio.gather(
                        *(self.resolve_image(image) for image in source_images)
                    ),
                )
            )
        self._save_build_data()

        # Swap out SourceImage for the resolved ExternalImages
        def _replace_source_image(image: ImageDefinition) -> ImageDefinition:
            if isinstance(image, SourceImage):
                return source_image_map[image]
            return image

        images = visit_graph(
            (stage.image for stage in stages.values()), _replace_source_image
        )
        for stage, image in zip(stages.values(), images):
            stage.image = image

    def _save_build_data(self):
        """
        Save build data to disk.
        """
        with open_and_swap(
            os.path.join(self.base_dir, ".tplbuilddata.json"),
            mode="w",
            encoding="utf-8",
        ) as fdata:
            json.dump(
                self.build_data.dict(),
                fdata,
                indent=2,
            )
