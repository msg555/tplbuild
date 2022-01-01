import asyncio
from asyncio.subprocess import DEVNULL, PIPE
import logging
import sys
from typing import AsyncIterable, Awaitable, BinaryIO, Dict, Iterable, List, Optional
import uuid

from .config import ClientConfig
from .context import BuildContext
from .exceptions import TplBuildException
from .images import (
    BaseImage,
    CommandImage,
    ContextImage,
    CopyCommandImage,
    ImageDefinition,
    SourceImage,
)
from .plan import BuildOperation
from .sync_to_async_pipe import SyncToAsyncPipe

LOGGER = logging.getLogger(__name__)


async def _create_subprocess(
    args: List[str],
    params: Dict[str, str],
    *,
    output_prefix: Optional[bytes] = None,
    input_data: Optional[AsyncIterable[bytes]] = None,
) -> None:
    """
    Create a subprocess and process its streams.
    """
    proc = await asyncio.create_subprocess_exec(
        *(arg.format(**params) for arg in args),
        stdout=DEVNULL if output_prefix is None else PIPE,
        stderr=DEVNULL if output_prefix is None else PIPE,
        stdin=DEVNULL if input_data is None else PIPE,
    )

    async def copy_lines(src: asyncio.StreamReader, dst: BinaryIO) -> None:
        """
        Copy lines of output from src to dst. It's assumed that dst is a non
        blocking output stream.
        """
        assert output_prefix is not None

        while not src.at_eof():
            line = await src.readline()
            if not line:
                continue

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

    coros: List[Awaitable] = []
    if output_prefix is not None:
        assert proc.stdout is not None and proc.stderr is not None
        coros.append(copy_lines(proc.stdout, sys.stdout.buffer))
        coros.append(copy_lines(proc.stderr, sys.stderr.buffer))

    if input_data is not None:
        coros.append(copy_input_data())

    coros.append(proc.wait())
    await asyncio.gather(*coros)

    if proc.returncode:
        raise TplBuildException("Client build command failed")


class BuildExecutor:
    """
    Utility class that acts as an interface between tplbuild and the client
    build commands.
    """

    def __init__(self, client_config: ClientConfig, base_image_repo: str) -> None:
        self.client_config = client_config
        self.base_image_repo = base_image_repo
        self.transient_prefix = "tplbuild"

    async def build(self, build_ops: Iterable[BuildOperation]) -> None:
        """
        Build each of the passed build ops and tag/push all images.
        """
        transient_images: List[str] = []
        image_tag_map: Dict[ImageDefinition, str] = {}
        try:
            for build_op in build_ops:
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

                if tags:
                    primary_tag = next(iter(tags))
                else:
                    primary_tag = f"{self.transient_prefix}-{uuid.uuid4()}"
                    transient_images.append(primary_tag)

                if isinstance(build_op.image, ContextImage):
                    await self._build_context(primary_tag, build_op)
                else:
                    await self._build_work(primary_tag, build_op, image_tag_map)

                image_tag_map[build_op.image] = primary_tag

        finally:
            excs = await asyncio.gather(
                *(self.untag_image(image) for image in transient_images),
                return_exceptions=True,
            )

            # If we're not in an exception already, raise any exception that
            # ocurred untagging transient images. Otherwise we're just going to
            # ignore the exceptions and assume any failures were a direct result
            # of the previous failure and not worth mentioning.
            _, cur_exc, _ = sys.exc_info()
            if cur_exc is None:
                for exc in excs:
                    if isinstance(exc, BaseException):
                        raise exc

    async def _build_context(self, tag: str, build_op: BuildOperation) -> None:
        """
        Perform a build operation where the image is an ImageContext.
        """

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
        while img != build_op.root:
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
            assert image.content_hash is not None
            return (
                self.base_image_repo.format(
                    config=image.config,
                    stage_name=image.stage_name,
                )
                + ":"
                + image.content_hash
            )
        raise AssertionError("unexpected image type")

    async def client_build(
        self,
        image: str,
        dockerfile_data: bytes,
        context: Optional[BuildContext] = None,
    ) -> None:
        """Wrapper that executes the client command to start a build"""
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

        await asyncio.gather(
            asyncio.get_running_loop().run_in_executor(None, sync_write_context),
            _create_subprocess(
                self.client_config.build,
                {"image": image},
                output_prefix=b"hello: ",
                input_data=pipe_reader(),
            ),
        )

    async def untag_image(self, image: str) -> None:
        """Wrapper that executes the client untag command"""
        await _create_subprocess(
            self.client_config.untag,
            {"image": image},
        )
