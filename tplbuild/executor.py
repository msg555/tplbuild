import asyncio
import logging
import os
import sys
import uuid
from asyncio.subprocess import DEVNULL, PIPE
from typing import (
    AsyncIterable,
    Awaitable,
    BinaryIO,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
)

from aioregistry import (
    AsyncRegistryClient,
    Descriptor,
    ManifestListV2S2,
    RegistryException,
    RegistryManifestRef,
    parse_image_name,
)

from .arch import split_platform
from .config import ClientCommand, ClientConfig
from .context import BuildContext
from .exceptions import TplBuildException
from .images import (
    BaseImage,
    CommandImage,
    ContextImage,
    CopyCommandImage,
    ImageDefinition,
    MultiPlatformImage,
    SourceImage,
)
from .plan import BuildOperation
from .sync_to_async_pipe import SyncToAsyncPipe

LOGGER = logging.getLogger(__name__)


async def _create_subprocess(
    cmd: ClientCommand,
    params: Dict[str, str],
    *,
    capture_output: bool = False,
    output_prefix: Optional[bytes] = None,
    input_data: Optional[AsyncIterable[bytes]] = None,
) -> bytes:
    """
    Create a subprocess and process its streams.
    """
    env = dict(os.environ)
    env.update(cmd.render_environment(params))
    proc = await asyncio.create_subprocess_exec(
        *cmd.render_args(params),
        stdout=DEVNULL if output_prefix is None and not capture_output else PIPE,
        stderr=DEVNULL if output_prefix is None else PIPE,
        stdin=DEVNULL if input_data is None else PIPE,
        env=env,
    )

    async def copy_lines(
        src: asyncio.StreamReader,
        dst: BinaryIO,
        *,
        output_prefix: Optional[bytes] = None,
        output_arr: Optional[List[bytes]] = None,
    ) -> None:
        """
        Copy lines of output from src to dst. It's assumed that dst is a non
        blocking output stream.
        """
        while not src.at_eof():
            line = await src.readline()
            if not line:
                continue

            if output_arr is not None:
                output_arr.append(line)

            if output_prefix is not None:
                dst.write(output_prefix)
                dst.write(line)
                if not line.endswith(b"\n"):
                    dst.write(b"\n")
                dst.flush()

    async def copy_input_data():
        """
        Copy data from input_data into proc.stdin.
        """
        # TODO(msg): Maybe need to disable SIGPIPE/handle write fails here?
        try:
            async for data in input_data:
                proc.stdin.write(data)
                await proc.stdin.drain()
            proc.stdin.close()
            await proc.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.warning("process exited before finished writing input")

    output_data: List[bytes] = []
    coros: List[Awaitable] = []
    if output_prefix is not None or capture_output:
        assert proc.stdout is not None
        coros.append(
            copy_lines(
                proc.stdout,
                sys.stdout.buffer,
                output_prefix=output_prefix,
                output_arr=output_data,
            )
        )

    if output_prefix is not None:
        assert proc.stderr is not None
        coros.append(
            copy_lines(proc.stderr, sys.stderr.buffer, output_prefix=output_prefix)
        )

    if input_data is not None:
        coros.append(copy_input_data())

    coros.append(proc.wait())
    await asyncio.gather(*coros)

    if proc.returncode:
        raise TplBuildException("Client build command failed")

    return b"".join(output_data)


class BuildExecutor:
    """
    Utility class that acts as an interface between tplbuild and the client
    build commands.
    """

    def __init__(
        self,
        client_config: ClientConfig,
        base_image_repo: str,
        registry_client: AsyncRegistryClient,
    ) -> None:
        self.client_config = client_config
        self.base_image_repo = base_image_repo
        self.registry_client = registry_client
        self.transient_prefix = "tplbuild"

        self.sem_build_jobs = asyncio.BoundedSemaphore(client_config.build_jobs)
        self.sem_push_jobs = asyncio.BoundedSemaphore(client_config.push_jobs)
        self.sem_tag_jobs = asyncio.BoundedSemaphore(client_config.tag_jobs)

    async def build(
        self,
        build_ops: Iterable[BuildOperation],
        *,
        complete_callback: Optional[Callable[[BuildOperation, str], None]] = None,
    ) -> None:
        """
        Build each of the passed build ops and tag/push all images.

        Arguments:
            build_ops: The list of build operations to be completed. These build
                operations should be topologically sorted (every build operation
                should be listed after all of its dependencies).
            complete_callback: If present this callback will be invoked for each
                build operation as `complete_callback(build_op, primary_tag)`.
                Note for multi platform images the 'primary_tag' will just be the
                first push tag.
        """
        transient_images: List[str] = []
        image_tag_map: Dict[ImageDefinition, str] = {}
        build_tasks: Dict[BuildOperation, Awaitable] = {}

        async def _build_single(build_op: BuildOperation):

            # Construct mapping of all tags to a bool indicating if the
            # tag should be pushed. The dict is ordered in the same order
            # as the stages with the tags from each stage keeping the same
            # relative order with push tags after tags.
            tags: Dict[str, bool] = {}
            for stage in build_op.stages:
                for tag in stage.tags:
                    tags.setdefault(tag, False)
                for tag in stage.push_tags:
                    tags[tag] = True

            # Wait for dependencies to finish
            for dep in build_op.dependencies:
                await build_tasks[dep]

            if isinstance(build_op.image, MultiPlatformImage):
                primary_tag = ""
                await self._build_multi_platform(build_op.image, tags, image_tag_map)
            else:
                if tags:
                    primary_tag = next(iter(tags))
                else:
                    primary_tag = f"{self.transient_prefix}-{uuid.uuid4()}"

                if isinstance(build_op.image, ContextImage):
                    await self._build_context(primary_tag, build_op.image)
                else:
                    await self._build_work(primary_tag, build_op, image_tag_map)

                if not tags:
                    transient_images.append(primary_tag)

                image_tag_map[build_op.image] = primary_tag

                for tag, push in tags.items():
                    if tag != primary_tag:
                        await self.tag_image(primary_tag, tag)
                    if push:
                        # TODO: Local build dependants should be able to
                        #       progress while we're pushing.
                        await self.push_image(tag)

            if complete_callback:
                complete_callback(build_op, primary_tag)

        build_tasks.update(
            (build_op, asyncio.create_task(_build_single(build_op)))
            for build_op in build_ops
        )
        try:
            for task in build_tasks.values():
                await task
        finally:
            excs = await asyncio.gather(
                *(self.untag_image(image) for image in transient_images),
                return_exceptions=True,
            )

            # If we're not in an exception already, raise any exception that
            # occurred untagging transient images. Otherwise we're just going to
            # ignore the exceptions and assume any failures were a direct result
            # of the previous failure and not worth mentioning.
            _, cur_exc, _ = sys.exc_info()
            if cur_exc is None:
                for exc in excs:
                    if isinstance(exc, BaseException):
                        raise exc

    async def _build_multi_platform(
        self,
        image: MultiPlatformImage,
        tags: Dict[str, bool],
        image_tag_map: Dict[ImageDefinition, str],
    ) -> None:
        """
        Push a multi-architecture image with the given tags. All tags
        must be push tags for this kind of node.
        """
        if not all(push for push in tags.values()):
            raise TplBuildException("Multi platform images only support push tags")

        async def push_sub_image(
            image_ref: RegistryManifestRef,
            platform: str,
            sub_image: ImageDefinition,
        ) -> Descriptor:
            sub_image_ref = image_ref.copy(
                update=dict(ref=f"{image_ref.ref}-{platform.replace('/', '-')}")
            )
            sub_image_tag = image_tag_map[sub_image]
            await self.tag_image(sub_image_tag, str(sub_image_ref))
            await self.push_image(str(sub_image_ref))
            try:
                desc = await self.registry_client.ref_lookup(sub_image_ref)
            except RegistryException as exc:
                raise TplBuildException("Failed to look up image digest") from exc
            if desc is None:
                raise TplBuildException("Could not look up pushed image on registry")
            return desc

        for tag in tags:
            image_ref = parse_image_name(tag)
            sub_descriptors = await asyncio.gather(
                *(
                    push_sub_image(image_ref, platform, sub_image)
                    for platform, sub_image in image.images.items()
                )
            )
            sub_manifest_items = []
            for platform, sub_descriptor in zip(image.images, sub_descriptors):
                image_os, architecture, variant = split_platform(platform)
                sub_manifest_items.append(
                    dict(
                        platform=dict(
                            architecture=architecture,
                            os=image_os,
                            variant=variant,
                        ),
                        **sub_descriptor.dict(by_alias=True),
                    )
                )

            manifest = ManifestListV2S2(
                schemaVersion=2,
                mediaType="application/vnd.docker.distribution.manifest.list.v2+json",
                manifests=sub_manifest_items,
            )
            await self.registry_client.manifest_write(image_ref, manifest)
            print(f"Wrote multi architecture platform {image_ref}")

    async def _build_context(self, tag: str, image: ContextImage) -> None:
        """
        Perform a build operation where the image is an ImageContext.
        """
        await self.client_build(
            tag,
            "",
            b"FROM scratch\nCOPY . /\n",
            image.context,
        )

    async def _build_work(
        self,
        tag: str,
        build_op: BuildOperation,
        image_tag_map: Dict[ImageDefinition, str],
    ) -> None:
        """
        Perform a build operation as a series of Dockerfile commands.
        """
        lines = []

        img = build_op.image
        while img is not build_op.root:
            if isinstance(img, CommandImage):
                lines.append(f"{img.command} {img.args}")
                img = img.parent
            elif isinstance(img, CopyCommandImage):
                if img.context is build_op.inline_context:
                    lines.append(f"COPY {img.command}")
                else:
                    lines.append(
                        f"COPY --from={ self._name_image(img.context, image_tag_map) } {img.command}"
                    )
                img = img.parent
            else:
                raise AssertionError("Unexpected image type in build operation")

        lines.append(f"FROM { self._name_image(img, image_tag_map) }")

        dockerfile_data = "\n".join(reversed(lines)).encode("utf-8")
        await self.client_build(
            tag,
            build_op.platform,
            dockerfile_data,
            build_op.inline_context.context if build_op.inline_context else None,
        )

    def _name_image(
        self, image: ImageDefinition, image_tag_map: Dict[ImageDefinition, str]
    ) -> str:
        """
        Construct the name of an image from its ImageDefinition. `image` should always be
        either an ExternalImage or the resulting image of a previously calculated
        bulid operation.
        """
        tag = image_tag_map.get(image)
        if tag is not None:
            return tag
        if isinstance(image, SourceImage):
            assert image.digest is not None
            return f"{image.repo}@{image.digest}"
        if isinstance(image, BaseImage):
            return image.get_image_name(self.base_image_repo)
        raise AssertionError("unexpected image type")

    async def client_build(
        self,
        image: str,
        platform: str,
        dockerfile_data: bytes,
        context: Optional[BuildContext] = None,
    ) -> None:
        """Wrapper that executes the client command to start a build"""

        if platform and self.client_config.build_platform is None:
            raise TplBuildException("No platform build client command configured")

        async with self.sem_build_jobs:
            if context is None:
                context = BuildContext(None, None, [])

            pipe = SyncToAsyncPipe()

            def sync_write_context():
                context.write_context(
                    pipe,
                    extra_files={"Dockerfile": (0o444, dockerfile_data)},
                )
                pipe.close()

            async def pipe_reader():
                try:
                    while data := await pipe.read():
                        yield data
                finally:
                    pipe.close()

            cmd = self.client_config.build
            params = {"image": image}
            if platform:
                assert self.client_config.build_platform is not None
                cmd = self.client_config.build_platform
                params["platform"] = platform

            await asyncio.gather(
                asyncio.get_running_loop().run_in_executor(None, sync_write_context),
                _create_subprocess(
                    cmd,
                    params,
                    output_prefix=b"hello: ",
                    input_data=pipe_reader(),
                ),
            )

    async def tag_image(self, source_image: str, target_image: str) -> None:
        """Wrapper that executes the client tag command"""
        async with self.sem_tag_jobs:
            await _create_subprocess(
                self.client_config.tag,
                {"source_image": source_image, "target_image": target_image},
            )

    async def untag_image(self, image: str) -> None:
        """Wrapper that executes the client untag command"""
        async with self.sem_tag_jobs:
            await _create_subprocess(
                self.client_config.untag,
                {"image": image},
            )

    async def push_image(self, image: str) -> None:
        """Wrapper that executes the client push command"""
        async with self.sem_push_jobs:
            await _create_subprocess(
                self.client_config.push,
                {"image": image},
                output_prefix=b"pushing stuff: ",
            )

    async def platform(self) -> str:
        """
        Returns the platform of the build daemon or an empty string if it
        cannot be determined. No normalization of the returned platform is done.
        """
        if self.client_config.platform is None:
            return ""

        output = await _create_subprocess(self.client_config.platform, {})
        try:
            return output.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise TplBuildException("Failed to decode executor platform") from exc
