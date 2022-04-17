import asyncio
import dataclasses
import logging
from typing import Optional

import pytest

from tplbuild.exit_context import (
    ScopedTaskExitStack,
    async_exit_context,
    get_exit_stack,
)


@dataclasses.dataclass
class IntWrapper:
    """Simple container for an int"""

    x: int = 0


async def spin(ctr: Optional[IntWrapper] = None):
    """Sleep forever and optionally increment ctr on cancellation"""
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.exceptions.CancelledError:
        if ctr is not None:
            ctr.x += 1
        raise


async def raise_it(exc):
    """Just raise an exception as a coroutine function"""
    raise exc


@pytest.mark.unit
async def test_cancel_coro(caplog):
    """
    Test that all coroutines get cancelled and their exceptions propagated
    """
    cancel_count = IntWrapper()

    async with ScopedTaskExitStack() as stack:
        stack.create_scoped_task(spin(cancel_count))
        stack.create_scoped_task(spin(cancel_count))
        await asyncio.sleep(0.1)
    assert cancel_count.x == 2

    with pytest.raises(asyncio.exceptions.CancelledError):
        async with ScopedTaskExitStack() as stack:
            stack.create_scoped_task(spin(cancel_count), propagate_cancel=True)
            stack.create_scoped_task(spin(cancel_count), propagate_cancel=True)
            await asyncio.sleep(0.1)
    assert cancel_count.x == 4

    with pytest.raises(Exception, match="exc2"):
        with caplog.at_level(logging.ERROR):
            assert not caplog.records
            async with ScopedTaskExitStack() as stack:
                with pytest.raises(Exception):
                    await stack.create_scoped_task(
                        raise_it(Exception("exc1")), propagate_exception=True
                    )
                stack.create_scoped_task(
                    raise_it(Exception("exc2")), propagate_exception=True
                )
                await asyncio.sleep(0.1)
            assert len(caplog.records) == 1


@pytest.mark.unit
async def test_async_exit_context(caplog):
    """
    Test async exit context functionality as a decorator
    """
    with pytest.raises(LookupError):
        get_exit_stack()

    cancel_count = IntWrapper()

    @async_exit_context
    async def work():
        stack = get_exit_stack()
        stack.create_scoped_task(spin(cancel_count))
        stack.create_scoped_task(spin(cancel_count))
        await asyncio.sleep(0.1)

    await work()
    assert cancel_count.x == 2
    with pytest.raises(LookupError):
        get_exit_stack()

    @async_exit_context
    async def work_cancel():
        stack = get_exit_stack()
        stack.create_scoped_task(spin(cancel_count), propagate_cancel=True)
        stack.create_scoped_task(spin(cancel_count), propagate_cancel=True)
        await asyncio.sleep(0.1)

    with pytest.raises(asyncio.exceptions.CancelledError):
        await work_cancel()
    assert cancel_count.x == 4
    with pytest.raises(LookupError):
        get_exit_stack()

    @async_exit_context
    async def work_prop():
        stack = get_exit_stack()
        with pytest.raises(Exception):
            await stack.create_scoped_task(
                raise_it(Exception("exc1")), propagate_exception=True
            )
        stack.create_scoped_task(raise_it(Exception("exc2")), propagate_exception=True)
        await asyncio.sleep(0.1)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(Exception, match="exc2"):
            assert not caplog.records
            await work_prop()
        assert len(caplog.records) == 1
    with pytest.raises(LookupError):
        get_exit_stack()


@pytest.mark.unit
async def test_nested():
    """
    Test that nested contexts get different stacks. Ensure that all tasks
    complete on exit.
    """
    all_stacks = set()
    all_tasks = []

    @async_exit_context
    async def nest(depth):
        stack = get_exit_stack()
        assert stack not in all_stacks
        all_stacks.add(stack)

        if depth > 0:
            all_tasks.append(stack.create_scoped_task(nest(depth - 1)))

        for _ in range(10 if depth == 10 else 100000000):
            await asyncio.sleep(1e-3)
            assert stack is get_exit_stack()

    await asyncio.gather(*(nest(10) for _ in range(10)))
    assert all(task.done() for task in all_tasks)
