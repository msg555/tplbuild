import asyncio
import functools
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import yaml
from aioregistry import AsyncRegistryClient, RegistryException, parse_image_name

from .config import BuildData, TplConfig
from .exceptions import TplBuildException
from .executor import BuildExecutor
from .images import BaseImage, ImageDefinition, SourceImage
from .plan import BuildOperation, BuildPlanner
from .render import BuildRenderer, StageData
from .utils import hash_graph, open_and_swap, visit_graph

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

    def lookup_base_image(
        self,
        stage_name: str,
        *,
        config_name: Optional[str] = None,
    ) -> Tuple[str, BaseImage]:
        """
        Returns the full image name and unrendered :class:`BaseImage` image node
        that represents the requested base image.

        Raises:
            KeyError: If the base image does not exist or has not been built
            TplBuildException: If no base image repo is configured
        """
        if self.config.base_image_repo is None:
            raise TplBuildException("No base image repo format configured")

        config_name = config_name or self.default_config_name
        cached_content_hash = self.build_data.base[config_name][stage_name]
        image = BaseImage(
            config=config_name,
            stage=stage_name,
            content_hash=cached_content_hash,
        )
        return image.get_image_name(self.config.base_image_repo), image

    @property
    def default_config_name(self) -> str:
        """
        Returns the default configuration name. If there are no configuration
        profiles then this will return an empty string.
        """
        return self.config.default_config or next(iter(self.config.configs), "")

    def _get_config_data(
        self,
        config_name: Optional[str] = None,
        *,
        platform: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Returns the config name and config data for the default config or a specific
        config name.
        """
        config_name = config_name or self.default_config_name
        if not config_name:
            # If no config was requested nor are any configured use an emtpy
            # configuration dictionary.
            config_name = ""
            config_data = {}
        else:
            try:
                config_data = self.config.configs[config_name]
            except KeyError as exc:
                raise TplBuildException(
                    f"Config {repr(config_name)} does not exist"
                ) from exc

        return (
            config_name,
            {
                "config": config_data,
                "config_name": config_name,
                "platform": platform,
            },
        )

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
            *self._get_config_data(config_name, platform=platform)
        )

    def plan(
        self,
        stages: List[StageData],
    ) -> List[BuildOperation]:
        """
        Plan how to build the given list of stages.

        Arguments:
            stages: The list of stages to build in the form of
                :class:`StageData` objects. Use :meth:`render`
                to render all the stages for a given configuration.
                You should also use :meth:`resolve_source_images`
                and :meth:`resolve_base_images` before calling `plan`.

        Returns:
            A list of :class:`BuildOperation` objects that that define how
            the stages are to be built. This list is returned topologically
            sorted so that all dependencies of a stage appear before it.
            Typically this should be fed into :meth:`build`.
        """
        return self.planner.plan(stages)

    async def build(
        self,
        build_ops: List[BuildOperation],
    ) -> None:
        """
        Execute the build operations.

        Arguments:
            build_ops: The list of build operations to execute. This should be
                topologically sorted each build operation appears only after all
                of its dependencies have been listed. Typically this should just
                be the return value from :meth:`plan`.
        """

        def complete_callback(build_op: BuildOperation, primary_tag: str) -> None:
            """
            Update our internal build data cache for base images.
            """
            # pylint: disable=unused-argument
            for stage in build_op.stages:
                if stage.base_image:
                    assert stage.base_image.content_hash is not None
                    self.build_data.base.setdefault(stage.base_image.config, {})[
                        stage.base_image.stage
                    ] = stage.base_image.content_hash

                # Save base images as soon as their done in case the build
                # is later interrupted.
                self._save_build_data()

        await self.executor.build(build_ops, complete_callback=complete_callback)

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

    async def resolve_base_images(
        self,
        stages: List[StageData],
        *,
        dereference=False,
    ) -> None:
        """
        Resolve all :class:`BaseImage` nodes found in the image graph, setting
        their `content_hash` attribute based on cached build data.

        Arguments:
            dereference: If True then all BaseImage nodes will be fully hashed
                (including their build contexts) to produce a content hash
                that will be set in the BaseImage node. This content hash will
                be available at `stage.base_image` for any passed stages that
                represent base images.

                Further, when base images are resolved, if the computed
                `content_hash` does not match the cached `content_hash` then
                the node will be replaced with the base image's underlying
                build definition.

        This modifies the passed in build graph and does not return anything
        directly.
        """

        full_hash_mapping = {}
        if dereference:
            full_hash_mapping = await asyncio.get_running_loop().run_in_executor(
                None,
                functools.partial(
                    hash_graph,
                    (stage.image for stage in stages if stage.base_image),
                    symbolic=False,
                ),
            )

            for stage in stages:
                if stage.base_image:
                    stage.base_image.content_hash = full_hash_mapping[stage.image]
                    stage.image = stage.base_image

        def _resolve_base(image: ImageDefinition) -> ImageDefinition:
            if not isinstance(image, BaseImage):
                return image

            cached_content_hash = self.build_data.base.get(image.config, {}).get(
                image.stage
            )

            if dereference:
                if image.image is None:
                    raise TplBuildException(
                        "Attempt to derference base image that has no image definition"
                    )

                if full_hash_mapping[image.image] != cached_content_hash:
                    return image.image

            image.image = None
            image.content_hash = cached_content_hash
            if image.content_hash is None:
                raise TplBuildException(
                    f"No cached build of {image.config}/{image.stage}"
                )

            return image

        images = visit_graph((stage.image for stage in stages), _resolve_base)
        for stage, image in zip(stages, images):
            stage.image = image

            # If we're really building a base image add its push tag.
            if stage.base_image and stage.image is not stage.base_image:
                if self.config.base_image_repo is None:
                    LOGGER.warning(
                        "Attempting to build base image but no base image repo set"
                    )
                else:
                    stage.push_tags += (
                        stage.base_image.get_image_name(self.config.base_image_repo),
                    )

    async def resolve_source_images(self, stages: List[StageData]) -> None:
        """
        Resolve the manifest digest for each source image in the build graph.
        This updates the build graph passed in to resolve_source_images and does
        not return anything directly.
        """
        # Find all the source images first
        source_images = set()

        def _visit_image(image: ImageDefinition) -> ImageDefinition:
            if isinstance(image, SourceImage):
                source_images.add(image)
            return image

        visit_graph((stage.image for stage in stages), _visit_image)

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

        images = visit_graph((stage.image for stage in stages), _replace_source_image)
        for stage, image in zip(stages, images):
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
