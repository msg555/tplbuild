import asyncio
from asyncio.subprocess import DEVNULL, PIPE
import logging
import sys
from typing import AsyncIterable, Awaitable, BinaryIO, Dict, Iterable, List, Optional

from .config import ClientConfig
from .exceptions import TplBuildException
from .plan import BuildOperation

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

    def __init__(self, client_config: ClientConfig) -> None:
        self.client_config = client_config

    async def build(self, build_ops: Iterable[BuildOperation]) -> None:
        """
        Build each of the passed build ops and tag/push all images.
        """

    async def client_build(self, image: str) -> None:
        """Wrapper that executes the client command to start a build"""
        _create_subprocess(
            self.client_config.build,
            {"image": image},
            output_prefix=b"hello: ",
        )
