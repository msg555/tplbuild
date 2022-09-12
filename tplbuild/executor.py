import asyncio
import logging
import os
import uuid
from asyncio.subprocess import DEVNULL, PIPE
from dataclasses import dataclass
from typing import (
    Any,
    AsyncIterable,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

import jinja2
from aioregistry import (
    Descriptor,
    ManifestListV2S2,
    RegistryException,
    RegistryManifestRef,
    parse_image_name,
)

from .arch import split_platform
from .config import ClientCommand
from .context import BuildContext
from .exceptions import TplBuildException
from .exit_context import async_exit_context, get_exit_stack
from .images import (
    BaseImage,
    CommandImage,
    ContextImage,
    CopyCommandImage,
    ImageDefinition,
    MultiPlatformImage,
    ScratchImage,
    SourceImage,
)
from .output import OutputStream
from .plan import BuildOperation
from .sync_to_async_pipe import SyncToAsyncPipe
from .tplbuild import TplBuild

LOGGER = logging.getLogger(__name__)


@async_exit_context
async def _create_subprocess(
    cmd: ClientCommand,
    jinja_env: jinja2.Environment,
    params: Dict[str, Any],
    *,
    capture_output: bool = False,
    output_stream: Optional[OutputStream] = None,
    input_data: Optional[AsyncIterable[bytes]] = None,
) -> bytes:
    """
    Create a subprocess and process its streams.
    """
    env = dict(os.environ)
    render_args, render_env = cmd.render(jinja_env, params)
    env.update(render_env)
    proc = await asyncio.create_subprocess_exec(
        *render_args,
        stdout=PIPE,
        stderr=PIPE,
        stdin=DEVNULL if input_data is None else PIPE,
        env=env,
    )
    assert proc.stdout is not None and proc.stderr is not None

    async def copy_lines(
        src: asyncio.StreamReader,
        *,
        output_arr: Optional[List[bytes]] = None,
        err: bool = False,
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
            if output_stream is not None:
                await output_stream.write(line, err=err)

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

    output_arr: List[bytes] = []
    coros: List[Awaitable] = [
        copy_lines(proc.stdout, output_arr=output_arr if capture_output else None),
        copy_lines(proc.stderr, err=True),
    ]
    if input_data is not None:
        coros.append(copy_input_data())

    exit_stack = get_exit_stack()
    coros.append(proc.wait())
    await asyncio.gather(*(exit_stack.create_scoped_task(coro) for coro in coros))

    if proc.returncode:
        raise TplBuildException(f"Client command failed {render_args}")

    return b"".join(output_arr)


def _construct_title(data, *, seps=":", depth=0):
    """
    Construct image titles from trie structure.
    """
    if not data:
        return ""
    children = sorted(
        (key, _construct_title(val, seps=seps, depth=depth + 1))
        for key, val in data.items()
    )
    sep = seps[depth] if depth < len(seps) else seps[-1]
    if len(children) == 1:
        return sep.join(children[0])
    if len(set(child[1] for child in children)) == 1:
        return f"{{{','.join(child[0] for child in children)}}}{sep}{children[0][1]}"
    return ",".join(f"{{{child[0]}{sep}{child[1]}}}" for child in children)


def _compute_titles(build_ops: List[BuildOperation]) -> List[str]:
    all_profiles: Set[str] = set()
    all_platforms: Set[str] = set()

    for build_op in build_ops:
        descs = getattr(build_op.image, "stage_descs", ())
        all_profiles.update(desc.profile for desc in descs)
        all_platforms.update(desc.platform for desc in descs)

    titles = []
    for build_op in build_ops:
        descs = getattr(build_op.image, "stage_descs", ())

        hierarchy: dict = {}
        for desc in descs:
            parts = [desc.name]
            if len(all_profiles) > 1:
                parts.append(desc.profile)
            if len(all_platforms) > 1 and not isinstance(
                build_op.image, MultiPlatformImage
            ):
                osname, arch, var = split_platform(desc.platform)
                if var:
                    arch = f"{arch}/{var}"
                parts.append(osname)
                parts.append(arch)

            data = hierarchy
            for part in parts:
                data = data.setdefault(part, {})

        if not hierarchy:
            titles.append("intermediate")
            continue

        titles.append(
            _construct_title(
                hierarchy,
                seps="::/" if len(all_profiles) > 1 else ":/",
            )[:-1]
        )

    return titles


@dataclass(eq=False)
class RenderedBuildOperation:
    """
    Dataclass describing a rendered build operation.
    """

    #: Dockerfile data to pass to underlying builder.
    dockerfile: str
    #: Tags to set locally. If a tag is maps to True it should be pushed.
    tags: Dict[str, bool]
    #: Tag to initially build the image as. This may be a transient tag if
    #: there was no requested tag associated with this build operation.
    primary_tag: str
    #: User friendly title for the build operation.
    build_title: str
    #: Set to True if the build operation does not actually create a new image.
    #: This is the case for example when a base image is created solely from
    #: a source image.
    build_empty: bool


class BuildExecutor:
    """
    Utility class that acts as an interface between tplbuild and the client
    build commands.
    """

    def __init__(
        self,
        tplbld: TplBuild,
    ) -> None:
        self.tplbld = tplbld
        self.transient_prefix = "tplbuild"

        user_config = tplbld.user_config
        self.client_config = user_config.client
        self.sem_build_jobs = asyncio.BoundedSemaphore(user_config.build_jobs)
        self.sem_push_jobs = asyncio.BoundedSemaphore(user_config.push_jobs)
        self.sem_tag_jobs = asyncio.BoundedSemaphore(user_config.tag_jobs)
        self.build_retry = user_config.build_retry
        self.push_retry = user_config.push_retry

    @async_exit_context
    async def build(
        self,
        build_ops: List[BuildOperation],
        *,
        complete_callback: Optional[
            Callable[[BuildOperation, str], Awaitable[None]]
        ] = None,
    ) -> None:
        """
        Build each of the passed build ops and tag/push all images.

        Arguments:
            build_ops: The list of build operations to be completed. These build
                operations should be topologically sorted (every build operation
                should be listed after all of its dependencies).
            complete_callback: If present this callback will be invoked for each
                build operation as `await complete_callback(build_op, primary_tag)`.
                Note for multi platform images the 'primary_tag' will just be the
                first push tag.
        """
        transient_images: List[str] = []
        remote_pull_coros: Dict[str, Awaitable] = {}

        rendered_ops = self.render_build_ops(build_ops)
        image_tag_map: Dict[ImageDefinition, str] = {
            build_op.image: rendered_op.primary_tag
            for build_op, rendered_op in zip(build_ops, rendered_ops)
            if not rendered_op.build_empty
        }

        async def _build_single(
            build_op: BuildOperation, rendered_op: RenderedBuildOperation
        ):
            # Wait for dependencies to finish
            for dep in build_op.dependencies:
                await build_done_events[dep].wait()

            tags = rendered_op.tags
            primary_tag = rendered_op.primary_tag
            build_title = rendered_op.build_title

            if isinstance(build_op.image, MultiPlatformImage):
                await self._build_multi_platform(
                    build_op.image, tags, image_tag_map, build_title
                )
                build_done_events[build_op].set()
            else:
                if isinstance(build_op.image, ContextImage):
                    await self._build_context(primary_tag, build_op.image, build_title)
                else:
                    # Pull base images, source images
                    remote_deps, local_deps = self._get_build_deps(
                        build_op, image_tag_map
                    )
                    if self.client_config.pull is not None:
                        for remote_ref, remote_name in remote_deps.items():
                            if remote_ref not in remote_pull_coros:
                                remote_pull_coros[remote_ref] = asyncio.create_task(
                                    self.pull_image(remote_ref, remote_name)
                                )
                            await remote_pull_coros[remote_ref]

                    await self._build_work(
                        primary_tag,
                        build_op,
                        rendered_op.dockerfile,
                        local_deps,
                        build_title,
                    )
                build_done_events[build_op].set()

                if not tags:
                    transient_images.append(primary_tag)

                for tag, push in tags.items():
                    if tag != primary_tag:
                        await self.tag_image(primary_tag, tag)
                    if push:
                        await self.push_image(tag, build_title)

            if complete_callback:
                await complete_callback(build_op, primary_tag)

        stack = get_exit_stack()
        build_tasks = {
            build_op: stack.create_scoped_task(_build_single(build_op, rendered_op))
            for build_op, rendered_op in zip(build_ops, rendered_ops)
        }
        build_done_events = {build_op: asyncio.Event() for build_op in build_ops}
        try:
            done, _ = await asyncio.wait(
                build_tasks.values(),
                return_when=asyncio.FIRST_EXCEPTION,
            )
            # Propagate any exceptions that occurred
            for task in done:
                await task
        finally:
            await asyncio.gather(
                *(self.untag_image(image) for image in transient_images)
            )

    async def _build_multi_platform(
        self,
        image: MultiPlatformImage,
        tags: Dict[str, bool],
        image_tag_map: Dict[ImageDefinition, str],
        title: str,
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
            await self.push_image(str(sub_image_ref), f"{title}:{platform}")
            try:
                desc = await self.tplbld.registry_client.ref_lookup(sub_image_ref)
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
                        **sub_descriptor.dict(by_alias=True, exclude_unset=True),
                    )
                )

            manifest = ManifestListV2S2(
                schemaVersion=2,
                mediaType="application/vnd.docker.distribution.manifest.list.v2+json",
                manifests=sub_manifest_items,
            )
            await self.tplbld.registry_client.manifest_write(image_ref, manifest)
            async with self.tplbld.output_streamer.start_stream(title) as output_stream:
                await output_stream.write(
                    f"Wrote multi architecture platform {image_ref}".encode("utf-8")
                )

    async def _build_context(self, tag: str, image: ContextImage, title: str) -> None:
        """
        Perform a build operation where the image is an ImageContext.
        """
        await self.client_build(
            tag,
            image.platform,
            b"FROM scratch\nCOPY . /\n",
            title,
            context=image.context,
        )

    def _get_build_deps(
        self,
        build_op: BuildOperation,
        image_tag_map: Dict[ImageDefinition, str],
    ) -> Tuple[Dict[str, str], Set[str]]:
        """
        Return a list of remotely stored images this build depends on.
        """
        remote_deps = {}
        local_deps = set()
        img = build_op.image

        def _title_image(img):
            if isinstance(img, BaseImage):
                return f"{img.stage}:{img.profile}:{img.platform}"
            assert isinstance(img, SourceImage)
            return f"{img.repo}:{img.tag}:{img.platform}"

        while img is not build_op.root:
            if (
                isinstance(img, CopyCommandImage)
                and img.context is not build_op.inline_context
            ):
                image_name = self._name_image(img.context, image_tag_map)
                if isinstance(img.context, (BaseImage, SourceImage)):
                    remote_deps[image_name] = _title_image(img.context)
                else:
                    local_deps.add(image_name)

            img = img.parent  # type: ignore

        image_name = self._name_image(img, image_tag_map)
        if isinstance(img, (BaseImage, SourceImage)):
            remote_deps[image_name] = _title_image(img)
        else:
            local_deps.add(image_name)

        return remote_deps, local_deps

    def render_build_ops(
        self,
        build_ops: List[BuildOperation],
    ) -> List[RenderedBuildOperation]:
        """
        Render Dockerfiles for each build operation.
        """
        result: List[RenderedBuildOperation] = []
        image_tag_map: Dict[ImageDefinition, str] = {}

        for build_op, build_title in zip(build_ops, _compute_titles(build_ops)):
            # Construct mapping of all tags to a bool indicating if the
            # tag should be pushed. The dict is ordered in the same order
            # as the stages with the tags from each stage keeping the same
            # relative order with push tags after tags.
            tags: Dict[str, bool] = {}
            for stage in build_op.stages:
                for tag in stage.config.image_names or []:
                    tags.setdefault(tag, False)
                for tag in stage.config.push_names or []:
                    tags[tag] = True

            primary_tag = ""
            if isinstance(build_op.image, MultiPlatformImage):
                result.append(
                    RenderedBuildOperation(
                        "# Multi-arch image", tags, primary_tag, build_title, True
                    )
                )
                continue

            if tags:
                primary_tag = next(iter(tags))
            else:
                primary_tag = f"{self.transient_prefix}-{uuid.uuid4()}"

            if isinstance(build_op.image, ContextImage):
                result.append(
                    RenderedBuildOperation(
                        "# Shared context image", tags, primary_tag, build_title, False
                    )
                )
                image_tag_map[build_op.image] = primary_tag
                continue

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

            build_empty = not lines
            lines.append(f"FROM { self._name_image(img, image_tag_map) }")
            if syntax := self.tplbld.config.dockerfile_syntax:
                lines.append(f"# syntax={syntax}")

            result.append(
                RenderedBuildOperation(
                    "\n".join(reversed(lines)),
                    tags,
                    primary_tag,
                    build_title,
                    build_empty,
                )
            )
            if not build_empty:
                image_tag_map[build_op.image] = primary_tag

        return result

    async def _build_work(
        self,
        tag: str,
        build_op: BuildOperation,
        dockerfile: str,
        local_deps: Set[str],
        title: str,
    ) -> None:
        """
        Perform a build operation as a series of Dockerfile commands.
        """
        await self.client_build(
            tag,
            build_op.platform,
            dockerfile.encode("utf-8"),
            title,
            context=build_op.inline_context.context
            if build_op.inline_context
            else None,
            dependencies=local_deps,
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
            return self.tplbld.get_base_image_name(image, use_digest=True)
        if isinstance(image, ScratchImage):
            return "scratch"
        raise AssertionError("unexpected image type")

    async def client_build(
        self,
        image: str,
        platform: str,
        dockerfile_data: bytes,
        title: str,
        *,
        context: Optional[BuildContext] = None,
        dependencies: Optional[Set[str]] = None,
    ) -> None:
        """Wrapper that executes the client command to start a build"""

        async with self.sem_build_jobs:
            if context is None:
                context = BuildContext(None, None, [])

            async with self.tplbld.output_streamer.start_stream(title) as output_stream:
                for attempt in range(self.build_retry + 1):

                    def sync_write_context(pipe: SyncToAsyncPipe):
                        assert context is not None
                        context.write_context(
                            pipe,  # type: ignore
                            extra_files={"Dockerfile": (0o444, dockerfile_data)},
                        )
                        pipe.close()

                    async def pipe_reader(pipe: SyncToAsyncPipe):
                        try:
                            while data := await pipe.read():
                                yield data
                        finally:
                            pipe.close()

                    pipe = SyncToAsyncPipe()
                    try:
                        await asyncio.gather(
                            asyncio.get_running_loop().run_in_executor(
                                None, sync_write_context, pipe
                            ),
                            _create_subprocess(
                                self.client_config.build,
                                self.tplbld.jinja_env,
                                dict(
                                    image=image,
                                    platform=platform,
                                    dependencies=dependencies or set(),
                                ),
                                output_stream=output_stream,
                                input_data=pipe_reader(pipe),
                            ),
                        )
                        break
                    except TplBuildException:
                        await output_stream.write(
                            f"Build failed on attempt {attempt + 1}/{self.build_retry + 1}".encode(
                                "utf-8"
                            )
                        )
                        if attempt == self.build_retry:
                            raise

    async def tag_image(self, source_image: str, target_image: str) -> None:
        """Wrapper that executes the client tag command"""
        async with self.sem_tag_jobs:
            await _create_subprocess(
                self.client_config.tag,
                self.tplbld.jinja_env,
                dict(source_image=source_image, target_image=target_image),
            )

    async def untag_image(self, image: str) -> None:
        """Wrapper that executes the client untag command"""
        async with self.sem_tag_jobs:
            await _create_subprocess(
                self.client_config.untag,
                self.tplbld.jinja_env,
                dict(image=image),
            )

    async def pull_image(self, image: str, title: str) -> None:
        """Wrapper that executes the client pull command"""
        assert self.client_config.pull is not None
        async with self.sem_push_jobs:
            async with self.tplbld.output_streamer.start_stream(title) as output_stream:
                for attempt in range(self.push_retry + 1):
                    try:
                        await _create_subprocess(
                            self.client_config.pull,
                            self.tplbld.jinja_env,
                            dict(image=image),
                            output_stream=output_stream,
                        )
                    except TplBuildException:
                        await output_stream.write(
                            f"Pull failed on attempt {attempt + 1}/{self.push_retry + 1}".encode(
                                "utf-8"
                            )
                        )
                        if attempt == self.push_retry:
                            raise

    async def push_image(self, image: str, title: str) -> None:
        """Wrapper that executes the client push command"""
        async with self.sem_push_jobs:
            async with self.tplbld.output_streamer.start_stream(title) as output_stream:
                for attempt in range(self.push_retry + 1):
                    try:
                        await _create_subprocess(
                            self.client_config.push,
                            self.tplbld.jinja_env,
                            dict(image=image),
                            output_stream=output_stream,
                        )
                    except TplBuildException:
                        await output_stream.write(
                            f"Pull failed on attempt {attempt + 1}/{self.push_retry + 1}".encode(
                                "utf-8"
                            )
                        )
                        if attempt == self.push_retry:
                            raise

    async def platform(self) -> str:
        """
        Returns the platform of the build daemon or an empty string if it
        cannot be determined. No normalization of the returned platform is done.
        """
        if self.client_config.platform is None:
            return ""

        output = await _create_subprocess(
            self.client_config.platform,
            self.tplbld.jinja_env,
            {},
        )
        try:
            return output.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise TplBuildException("Failed to decode executor platform") from exc
