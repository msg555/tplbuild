import asyncio
import contextlib
import functools
import inspect
import logging
from contextvars import ContextVar

LOGGER = logging.getLogger(__name__)


class ScopedTaskExitStack(contextlib.AsyncExitStack):
    """
    Small extension to AsyncExitStack that can handle cancelling incomplete tasks
    cretaed during the lifetime of the stack.
    """

    def create_scoped_task(
        self,
        coro_or_task,
        *,
        propagate_exception=False,
        propagate_cancel=False,
    ):
        """
        Wrap `coro_or_task` in a task if needed and return it. Simultaneously
        add an exit callback to the exit stack to cancel and join the task
        if it has not completed when the stack exits.

        Subclasses of Exception raised by these tasks will be ignored as well as
        CancelledError. Any other errors will be propagated if there is no existing
        exception.
        """
        if inspect.iscoroutine(coro_or_task):
            task = asyncio.create_task(coro_or_task)
        else:
            task = coro_or_task

        async def cancel_task(exc_typ, exc_val, exc_tb):
            # pylint: disable=unused-argument
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                if propagate_cancel and exc_typ is None:
                    raise
                LOGGER.debug("Supressing cancellation error for async task")
            except BaseException as exc:  # pylint: disable=broad-except
                if propagate_exception and exc_typ is None:
                    raise
                if exc is not exc_val:
                    LOGGER.exception("Unhandled exception in scoped async task dropped")

        self.push_async_exit(cancel_task)
        return task


_EXIT_STACK = ContextVar("exit_stack")  # type: ignore


def async_exit_context(func):
    """
    Decorator that creates a new ScopedTaskExitStack and makes it accessible
    in a context variable accessed through `get_exit_stack`. This exit stack will
    begin and end with the lifetime of the wrapped function.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with ScopedTaskExitStack() as stack:
            reset_token = _EXIT_STACK.set(stack)
            try:
                return await func(*args, **kwargs)
            finally:
                _EXIT_STACK.reset(reset_token)

    return wrapper


def get_exit_stack() -> ScopedTaskExitStack:
    """
    Returns the active exit stack for the current context. If no exit stack exists in
    the current context this will raise a LookupError.
    """
    return _EXIT_STACK.get()
