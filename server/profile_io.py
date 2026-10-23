"""Bounded, serialized profile I/O owned and drained by one server lifetime."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial


async def _await_owned(future):
    # asyncio.shield in the bundled Python3.14 reports a late failure after its
    # waiter is cancelled, even though our owner explicitly consumes it. Give
    # each waiter a disposable proxy; never cancel or relinquish the owned I/O.
    waiter = asyncio.get_running_loop().create_future()
    def completed(inner):
        if waiter.done(): return
        if inner.cancelled(): waiter.cancel()
        elif (error := inner.exception()) is not None: waiter.set_exception(error)
        else: waiter.set_result(inner.result())
    future.add_done_callback(completed)
    try: return await waiter
    finally: future.remove_done_callback(completed)


class ProfileIO:
    def __init__(self, store, *, max_pending=128):
        if type(max_pending) is not int or not 1 <= max_pending <= 1024:
            raise ValueError('invalid profile I/O limit')
        self.store, self.max_pending = store, max_pending
        self.pending = set()
        self._executor = None
        self._closing = False
        self._shutdown = None

    def _settled(self, future):
        self.pending.discard(future)
        # A cancelled network waiter leaves the actual operation owned here.
        # Consume failures even when that waiter can no longer receive them.
        if not future.cancelled(): future.exception()

    async def _call(self, function, *args, **kwargs):
        if self._closing: raise OSError('profile storage is stopping')
        if len(self.pending) >= self.max_pending: raise OSError('profile storage is busy')
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ba-profiles')
        future = asyncio.get_running_loop().run_in_executor(self._executor, partial(function, *args, **kwargs))
        self.pending.add(future)
        future.add_done_callback(self._settled)
        return await _await_owned(future)

    async def save(self, profile, deck, *, cosmetics=None):
        return await self._call(self.store.save, profile, tuple(deck), cosmetics=cosmetics)

    async def load_state(self, profile, fallback):
        # Reads share the same FIFO as writes, including writes whose network
        # waiter disconnected. Reconnecting must not read ahead of those writes.
        return await self._call(self.store.load_state, profile, tuple(fallback))

    async def _drain(self):
        await asyncio.gather(*tuple(self.pending), return_exceptions=True)
        if self._executor is not None:
            await asyncio.to_thread(self._executor.shutdown, wait=True)

    async def close(self):
        if self._shutdown is None:
            self._closing = True
            self._shutdown = asyncio.create_task(self._drain())
        try:
            await _await_owned(self._shutdown)
        except asyncio.CancelledError:
            # Finish ownership before a caller can release the state lock.
            while not self._shutdown.done():
                try: await _await_owned(self._shutdown)
                except asyncio.CancelledError: pass
            self._shutdown.result()
            raise
