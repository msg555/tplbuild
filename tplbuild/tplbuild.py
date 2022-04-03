import asyncio
import dataclasses
import functools
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import jinja2
import yaml
from aioregistry import (
    AsyncRegistryClient,
    ManifestListV2S2,
    ManifestV1,
    ManifestV2S2,
    RegistryBlobRef,
    RegistryException,
    parse_image_name,
)

from .arch import client_platform, normalize_platform, normalize_platform_string
from .config import BaseImageBuildData, BuildData, StageConfig, TplConfig, UserConfig
from .exceptions import (
    TplBuildException,
    TplBuildNoSourceImageException,
    TplBuildTemplateException,
)
from .graph import hash_graph, visit_graph
from .images import BaseImage, ImageDefinition, SourceImage, StageData
from .output import OutputStreamer
from .plan import BuildOperation, BuildPlanner
from .utils import open_and_swap

LOGGER = logging.getLogger(__name__)


class TplBuild:
    """
    Container class for all top level build operations.

    Arguments:
        base_dir: The base directory of the build
        config: The build configuration
    """

    @classmethod
    def from_path(
        cls,
        base_dir: str,
        *,
        user_config: UserConfig,
        registry_client: Optional[AsyncRegistryClient] = None,
    ) -> "TplBuild":
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
                config = TplConfig(**yaml.safe_load(fconfig))
        except FileNotFoundError:
            LOGGER.warning("No tplbuild.yml found, using default configuration")
            config = TplConfig()
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            raise TplBuildException(f"Failed to load configuration: {exc}") from exc
        return TplBuild(
            base_dir, config, user_config=user_config, registry_client=registry_client
        )

    def __init__(
        self,
        base_dir: str,
        config: TplConfig,
        *,
        user_config: Optional[UserConfig] = None,
        registry_client: Optional[AsyncRegistryClient] = None,
    ) -> None:
        # pylint: disable=import-outside-toplevel,cyclic-import
        from .executor import BuildExecutor

        self.base_dir = base_dir
        self.config = config
        self.user_config = user_config or UserConfig()
        self.planner = BuildPlanner()
        self.custom_client = bool(registry_client)
        self.registry_client = registry_client or AsyncRegistryClient()
        self.executor = BuildExecutor(self)
        self.jinja_env = jinja2.Environment()
        self.jinja_file_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(base_dir)
        )
        self.output_streamer = OutputStreamer()
        try:
            with open(
                os.path.join(base_dir, ".tplbuilddata.json"), encoding="utf-8"
            ) as fbuilddata:
                self.build_data = BuildData(**json.load(fbuilddata))
        except FileNotFoundError:
            LOGGER.warning(".tplbuilddata.json not found, using empty bulid data")
            self.build_data = BuildData()

    async def __aenter__(self) -> "TplBuild":
        return self

    async def __aexit__(self, exc_type, exc_value, exc_traceback) -> None:
        if not self.custom_client:
            await self.registry_client.__aexit__(exc_type, exc_value, exc_traceback)

    def jinja_render(
        self,
        template: str,
        params: Dict[str, Any],
        *,
        file_template=False,
        file_env=False,
    ) -> str:
        """
        Renders a Jinja template in the appropriate jinja environment and returns
        the rendered result. If `file_env` is True this will allow other templates
        to be loaded using include commands. If `file_template` is True this will
        interpret `template` as a file path to a template rather than a template.

        On Failure this will raise a TplBuildTempalteException.
        """
        jinja_env = self.jinja_file_env if file_env else self.jinja_env
        try:
            if file_template:
                jtpl = jinja_env.get_template(template)
            else:
                jtpl = jinja_env.from_string(template)
            return jtpl.render(**params)
        except jinja2.TemplateError as exc:
            if file_template:
                raise TplBuildTemplateException(
                    f"Failed to render file template {repr(file_template)}"
                ) from exc
            raise TplBuildTemplateException("Failed to render template") from exc

    def get_base_image_name(
        self,
        base_image: BaseImage,
        *,
        use_digest: bool = False,
    ) -> str:
        """
        Return the base image name by rendering the base image name
        config template.
        """
        if self.config.base_image_name is None:
            raise TplBuildException("Must configure base_image_name to use base images")
        try:
            base_image_repo = self.jinja_render(
                self.config.base_image_name,
                dict(
                    stage_name=base_image.stage,
                    profile=base_image.profile,
                    platform=base_image.platform,
                ),
            )
        except TplBuildTemplateException as exc:
            exc.update_message("Failed to render base image name template")
            raise exc

        if use_digest:
            return f"{base_image_repo}@{base_image.digest}"
        return f"{base_image_repo}:{base_image.content_hash}"

    def get_stage_config(
        self, stage_name: str, profile: str, platform: str
    ) -> StageConfig:
        """
        Return the StageConfig for the given stage name. This will first check
        :attr:`TplConfig.stages` to see if there is an explicit configuration
        for this stage.

        Otherwise, if the stage name starts with "base-" or "base_" a base
        image `StageConfig` will be returned.

        If the name starts with "anon-" or "anon_" instead the stage will be
        considered an "anonymous" stage. This means that it will neither be built
        as a base image nor will it be tagged or pushed to any image name. Such
        images are used for intermediate build operations and are not an output
        of the build themselves.

        For every other image the :attr:`TplConfig.stage_image_name` template
        will be used to determine the desired image name for the stage. This
        name will be used to tag the built image and push to remote registries.
        """
        if stage_config := self.config.stages.get(stage_name):
            return stage_config.copy()
        if stage_name[0:5] in ("base-", "base_"):
            return StageConfig(base=True)
        if stage_name[0:5] in ("anon-", "anon_"):
            return StageConfig()
        params = dict(
            stage_name=stage_name,
            profile=profile,
            platform=platform,
        )
        try:
            image_names = [self.jinja_render(self.config.stage_image_name, params)]
        except TplBuildTemplateException as exc:
            exc.update_message("Failed to render stage image name template")
            raise exc

        push_names = []
        if self.config.stage_push_name:
            try:
                push_names.append(
                    self.jinja_render(self.config.stage_push_name, params)
                )
            except TplBuildTemplateException as exc:
                exc.update_message("Failed to render stage push name template")
                raise exc

        return StageConfig(
            image_names=image_names,
            push_names=push_names,
        )

    def lookup_base_image(
        self,
        stage_name: str,
        platform: str,
        *,
        profile: str = "",
    ) -> Tuple[str, BaseImage]:
        """
        Returns the full image name and unrendered :class:`BaseImage` image node
        that represents the requested base image.

        Raises:
            KeyError: If the base image does not exist or has not been built
            TplBuildException: If no base image repo is configured
        """
        if self.config.base_image_name is None:
            raise TplBuildException("No base image repo format configured")

        profile = profile or self.default_profile
        cached_build_data = self.build_data.base[profile][stage_name][platform]
        image = BaseImage(
            profile=profile,
            stage=stage_name,
            platform=platform,
            content_hash=cached_build_data.build_hash,
            digest=cached_build_data.image_digest,
        )
        return (
            self.get_base_image_name(image, use_digest=True),
            image,
        )

    @property
    def default_profile(self) -> str:
        """
        Returns the default configuration name. If there are no configuration
        profiles then this will return an empty string.
        """
        return self.config.default_profile or next(iter(self.config.profiles), "")

    async def get_default_platform(self) -> str:
        """
        Calculate the default platform.
        """
        options = [
            await self.executor.platform(),
            client_platform(),
        ]
        for platform in options:
            if platform:
                platform = normalize_platform_string(platform)
                if platform in self.config.platforms:
                    return platform
        return self.config.platforms[0]

    def get_render_context(self, profile: str) -> Dict[str, Any]:
        """
        Returns the render context to pass into Jinja to render the build file
        for the given profile.
        """
        if not profile:
            profile_data = {}
        else:
            try:
                profile_data = self.config.profiles[profile]
            except KeyError as exc:
                raise TplBuildException(
                    f"Profile {repr(profile)} does not exist"
                ) from exc

        return {
            "profile": profile,
            **profile_data,
        }

    async def render(
        self,
        *,
        profile: str = "",
        platform: str = "",
    ) -> Dict[str, StageData]:
        """
        Render all contexts and stages into StageData.

        Returns:
            dict mapping stage names/context names to their
            respective :class:`StageData`.
        """
        # pylint: disable=import-outside-toplevel,cyclic-import
        from .render import render

        profile = profile or self.default_profile
        platform = platform or await self.get_default_platform()
        return render(self, profile, self.get_render_context(profile), platform)

    def plan(
        self,
        stages: List[StageData],
    ) -> List[BuildOperation]:
        """
        Plan how to build the given list of stages.

        Arguments:
            stages: The list of stages to build in the form of
                :class:`StageData` objects. Use :meth:`render`
                to render all the stages for a given profile.
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

        async def complete_callback(build_op: BuildOperation, primary_tag: str) -> None:
            """
            Update our internal build data cache for base images.
            """
            # pylint: disable=unused-argument
            for stage in build_op.stages:
                if stage.base_image:
                    assert stage.base_image.content_hash is not None
                    try:
                        descriptor = await self.registry_client.ref_lookup(
                            parse_image_name(self.get_base_image_name(stage.base_image))
                        )
                    except RegistryException as exc:
                        raise TplBuildException(
                            "Could not find pushed base image in registry"
                        ) from exc
                    if descriptor is None:
                        raise TplBuildException(
                            "Could not find pushed base image in registry"
                        )

                    self.build_data.base.setdefault(
                        stage.base_image.profile, {}
                    ).setdefault(stage.base_image.stage, {})[
                        stage.base_image.platform
                    ] = BaseImageBuildData(
                        build_hash=stage.base_image.content_hash,
                        image_digest=descriptor.digest,
                    )

                # Save base images as soon as their done in case the build
                # is later interrupted.
                self.save_build_data()

        await self.executor.build(build_ops, complete_callback=complete_callback)

    async def resolve_image(
        self,
        image: SourceImage,
        *,
        check_only=False,
        force_update=False,
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

        Raises:
            TplBuildException if the image could not be fetched or if it
            has no matching platform.
        """
        if image.digest is not None:
            return image

        source_digest = (
            self.build_data.source.get(image.repo, {})
            .get(image.tag, {})
            .get(image.platform)
        )
        if source_digest is not None and not force_update:
            return dataclasses.replace(image, digest=source_digest)

        if check_only:
            raise TplBuildNoSourceImageException(
                "Source image does not exist, check only"
            )

        # Grab the latest digest for the given source image.
        manifest_ref = parse_image_name(f"{image.repo}:{image.tag}")
        try:
            descriptor = await self.registry_client.ref_lookup(manifest_ref)
            if descriptor is None:
                raise TplBuildException(
                    f"Failed to lookup source image {repr(str(manifest_ref))}"
                )
            manifest_ref = manifest_ref.copy(update=dict(ref=descriptor.digest))
        except RegistryException as exc:
            raise TplBuildException(
                f"Failed to lookup source image {repr(str(manifest_ref))}"
            ) from exc

        # Download the manifest
        try:
            manifest = await self.registry_client.manifest_download(manifest_ref)
        except RegistryException as exc:
            raise TplBuildException("Failed to download source manifest") from exc

        # TODO: Should probably add some support in aioregistry itself for inspecting
        #       image configs and getting platform information.
        if isinstance(manifest, ManifestV1):
            # Only one platform available, make sure it's the one we want.
            image_platform = "linux/" + manifest.architecture
            if image.platform != image_platform:
                raise TplBuildException(
                    f"Source image has incorrect architecture {repr(image_platform)}"
                )
        elif isinstance(manifest, ManifestV2S2):
            # Only one platform available, make sure it's the one we want. V2 images
            # require us to download the config to inspect.
            config_ref = RegistryBlobRef(
                registry=manifest_ref.registry,
                repo=manifest_ref.repo,
                ref=manifest.config.digest,
            )
            config_raw_data = [
                chunk
                async for chunk in self.registry_client.ref_content_stream(config_ref)
            ]
            config = json.loads(b"".join(config_raw_data).decode("utf-8"))
            image_platform = normalize_platform(
                config["os"],
                config["architecture"],
                config.get("variant", ""),
            )
            if image.platform != image_platform:
                raise TplBuildException(
                    f"Source image has incorrect architecture {repr(image_platform)}"
                )
        elif isinstance(manifest, ManifestListV2S2):
            # Select appropriate sub-manifest based on the platform
            for sub_manifest in manifest.manifests:
                platform = sub_manifest.platform
                if platform is None:
                    continue
                image_platform = normalize_platform(
                    platform.os, platform.architecture, platform.variant
                )
                if image.platform == image_platform:
                    manifest_ref = manifest_ref.copy(
                        update=dict(ref=sub_manifest.digest)
                    )
                    break
            else:
                raise TplBuildException(
                    "No appropriate platform found in manifest list"
                )

        # Save the result into our build data
        self.build_data.source.setdefault(image.repo, {}).setdefault(image.tag, {})[
            image.platform
        ] = manifest_ref.ref
        return dataclasses.replace(image, digest=manifest_ref.ref)

    async def resolve_base_images(
        self,
        stages: List[StageData],
        *,
        dereference=False,
        resolve_from_registry=True,
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
            resolve_from_registry: Modifies behavior when dereferencing to first
                check if the image is present in the registry before dereferencing
                the image. If the image is present the build data will be updated
                automatically.

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
                    salt=self.build_data.hash_salt,
                    symbolic=False,
                ),
            )

            for stage in stages:
                if stage.base_image:
                    stage.base_image.content_hash = full_hash_mapping[stage.image]
                    stage.image = stage.base_image

            if resolve_from_registry:
                base_images: List[BaseImage] = [
                    stage.base_image
                    for stage in stages
                    if stage.base_image and stage.base_image.image
                ]

                for base_image in base_images:
                    cached_build_data = (
                        self.build_data.base.get(base_image.profile, {})
                        .get(base_image.stage, {})
                        .get(base_image.platform)
                    )
                    cached_content_hash = (
                        cached_build_data.build_hash if cached_build_data else None
                    )

                    assert base_image.image
                    if full_hash_mapping[base_image.image] != cached_content_hash:
                        try:
                            descriptor = await self.registry_client.ref_lookup(
                                parse_image_name(self.get_base_image_name(base_image))
                            )
                        except RegistryException as exc:
                            raise TplBuildException(
                                "Failed to lookup base image in registry"
                            ) from exc

                        if descriptor:
                            self.build_data.base.setdefault(
                                base_image.profile, {}
                            ).setdefault(base_image.stage, {})[
                                base_image.platform
                            ] = BaseImageBuildData(
                                build_hash=full_hash_mapping[base_image.image],
                                image_digest=descriptor.digest,
                            )

                            LOGGER.info(
                                "Updating base image %s:%s:%s from registry",
                                base_image.stage,
                                base_image.profile,
                                base_image.platform,
                            )
                            self.save_build_data()

        def _resolve_base(image: ImageDefinition) -> ImageDefinition:
            if not isinstance(image, BaseImage):
                return image

            cached_build_data = (
                self.build_data.base.get(image.profile, {})
                .get(image.stage, {})
                .get(image.platform)
            )

            if dereference:
                if image.image is None:
                    raise TplBuildException(
                        "Attempt to dereference base image that has no image definition"
                    )

                if (
                    cached_build_data is None
                    or full_hash_mapping[image.image] != cached_build_data.build_hash
                ):
                    return image.image

            if cached_build_data is None:
                raise TplBuildException(
                    f"No cached build of {image.profile}/{image.stage}"
                )

            image.image = None
            image.content_hash = cached_build_data.build_hash
            image.digest = cached_build_data.image_digest

            return image

        images = visit_graph((stage.image for stage in stages), _resolve_base)
        for stage, image in zip(stages, images):
            stage.image = image

            # If we're really building a base image add its push name.
            if stage.base_image and stage.image is not stage.base_image:
                stage.config.push_names.append(
                    self.get_base_image_name(stage.base_image)
                )

    async def resolve_source_images(
        self,
        stages: List[StageData],
        *,
        check_only=False,
        force_update=False,
    ) -> None:
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
        source_image_map = dict(
            zip(
                source_images,
                await asyncio.gather(
                    *(
                        self.resolve_image(
                            image, check_only=check_only, force_update=force_update
                        )
                        for image in source_images
                    )
                ),
            )
        )
        self.save_build_data()

        # Swap out SourceImage for the resolved ExternalImages
        def _replace_source_image(image: ImageDefinition) -> ImageDefinition:
            if isinstance(image, SourceImage):
                return source_image_map[image]
            return image

        images = visit_graph((stage.image for stage in stages), _replace_source_image)
        for stage, image in zip(stages, images):
            stage.image = image

    def save_build_data(self):
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
