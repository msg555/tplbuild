import asyncio
import random
import time

import pytest

from .hashing import HASHER
from .sync_to_async_pipe import SyncToAsyncPipe


def asyncio_run(func):
    """Utility decorator to run an event loop around a coroutine"""

    def invoke(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return invoke


@pytest.mark.unit
@asyncio_run
async def test_write_bulk():
    """Test passing through the pipe using writes of differnet sizes"""
    TEST_CASES = (
        (1, 4, 4),
        (10, 20, 20),
        (1024, 128, 128),
        (2**10, 2**9, 2**9),
        (2**10, 2**4, 2**14),
        (2**10, 2**14, 2**4),
    )
    SLEEP_OFFSETS = (
        (0, 0),
        (0.1, 0),
        (0, 0.1),
    )
    rng = random.Random(555)

    for sync_sleep, async_sleep in SLEEP_OFFSETS:
        for pipe_buf_size, max_chunk_size, chunks in TEST_CASES:
            pipe = SyncToAsyncPipe(buf_max=pipe_buf_size)

            def write_sync(rng, pipe, max_chunk_size, chunks, sync_sleep):
                """Write some random data to the pipe and return its hex digest"""
                time.sleep(sync_sleep)

                hsh = HASHER()
                for _ in range(chunks):
                    data = bytes(
                        rng.randrange(256)
                        for _ in range(1 + rng.randrange(max_chunk_size))
                    )
                    hsh.update(data)
                    pipe.write(data)
                pipe.close()
                return hsh.hexdigest()

            write_task = asyncio.get_running_loop().run_in_executor(
                None, write_sync, rng, pipe, max_chunk_size, chunks, sync_sleep
            )

            await asyncio.sleep(async_sleep)

            hsh = HASHER()
            while chunk := await pipe.read():
                hsh.update(chunk)

            assert hsh.hexdigest() == await write_task
