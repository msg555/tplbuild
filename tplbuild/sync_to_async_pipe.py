import asyncio
import threading


class SyncToAsyncPipe:
    """
    Provides a pipe interface that allows synchronous writes and asyncrhonous
    reads of byte data.

    Arguments:
        loop: The event loop from which the pipe will be read. If not provided
            the current event loop will be used. It is an error to read from
            any other event loop.
        buf_max: The maximum number of bytes that that can be buffered in the pipe.
    """

    def __init__(self, loop=None, *, buf_max=2**16) -> None:
        if loop is None:
            loop = asyncio.get_running_loop()
        self.loop = loop
        self.buf = bytearray(0 for _ in range(buf_max))
        self.buf_pos = 0
        self.buf_size = 0
        self.buf_lock = threading.Condition()
        self.waiter = None
        self.closed = False

    def write(self, data: bytes) -> None:
        """
        Write `data` to the stream. This will block if the stream buffers have
        already filled up.
        """
        data_pos = 0
        with self.buf_lock:
            while data_pos < len(data):
                while self.buf_size == len(self.buf):
                    self.buf_lock.wait()

                write_offset = (self.buf_pos + self.buf_size) % len(self.buf)
                amt = min(
                    len(data) - data_pos,
                    len(self.buf) - self.buf_size,
                    len(self.buf) - write_offset,
                )

                self.buf[write_offset : write_offset + amt] = data[
                    data_pos : data_pos + amt
                ]
                self.buf_size += amt
                data_pos += amt
                self._notify_reader()

    async def read(self) -> bytes:
        """
        Read data from the stream. Only one task can read from a pipe concurrently.

        If the stream is closed returns b"". Otherwise returns a non-empty bytes
        data object.
        """
        waiter = None
        while True:
            if waiter is not None:
                # Wait for someone to write some data.
                await waiter

            with self.buf_lock:
                if self.buf_size == 0 and not self.closed:
                    # Create new waiter, release lock, and wait for notification.
                    if self.waiter is not None:
                        raise RuntimeError(
                            "Cannot read from the same pipe multiple times concurrently"
                        )

                    waiter = self.loop.create_future()
                    self.waiter = waiter
                    continue

                if self.closed and self.buf_size == 0:
                    return b""

                amt = min(self.buf_size, len(self.buf) - self.buf_pos)
                result = bytes(self.buf[self.buf_pos : self.buf_pos + amt])
                self.buf_pos = (self.buf_pos + amt) % len(self.buf)
                self.buf_size -= amt
                self.buf_lock.notify()
                return result

    def close(self) -> None:
        """
        Close the stream. This can be called from the synchronous or asynchronous
        context.

        If a thread attempts to/is currently writing to the stream it will raise
        a BrokenPipeError.

        Readers will continue to be able to read the rest of the data in the buffer
        and then get an empty b"" object when the stream is exhausted.
        """
        with self.buf_lock:
            self.closed = True
            self.buf_lock.notify()
            self._notify_reader()

    def _notify_reader(self) -> None:
        """
        Wake up any readers that are waiting for data to be written.
        """
        if self.waiter is not None:
            self.loop.call_soon_threadsafe(self.waiter.set_result, None)
            self.waiter = None
