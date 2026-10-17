"""Bounded loopback byte-stream delay for qualification; not a packet-loss model.

TLS stays end to end. This relay never decrypts, logs or persists payloads. Each
direction schedules ordered chunks independently, so a delayed chunk does not
add another whole RTT to every chunk queued behind it. OS TCP behavior is local.
"""
from __future__ import annotations

import asyncio
import math
import random


class StreamShaper:
    def __init__(self, target_port, *, rtt_ms=0, jitter_ms=0, seed=1, maximum=8):
        if type(target_port) is not int or not 1 <= target_port <= 65535:
            raise ValueError('Invalid local target port')
        for value, upper in ((rtt_ms, 500), (jitter_ms, 100)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= upper:
                raise ValueError('Delay must be finite: RTT0..500ms,jitter0..100ms')
        if type(seed) is not int or type(maximum) is not int or not 1 <= maximum <= 16:
            raise ValueError('Invalid relay seed or connection limit')
        self.target_port, self.delay, self.jitter = target_port, rtt_ms / 2000, jitter_ms / 1000
        self.seed, self.maximum = seed, maximum
        self.listener, self.closing = None, False
        self.tasks = set()
        self.stats = dict(accepted=0, rejected=0, forwarded_bytes=0, chunks=0,
                          maximum_queued_chunks=0, failures=0)

    async def start(self):
        if self.listener is not None or self.closing:
            raise ValueError('Relay already started or closed')
        self.listener = await asyncio.start_server(self.handle, '127.0.0.1', 0, limit=65536)
        return self.listener.sockets[0].getsockname()[1]

    async def pipe(self, reader, writer, seed):
        queue = asyncio.Queue(32)  # <=2MiB, plus one in-flight chunk and stream buffers.
        rng, loop = random.Random(seed), asyncio.get_running_loop()

        async def produce():
            previous = 0.0
            while data := await reader.read(65536):
                due = max(previous, loop.time() + max(0, self.delay + rng.uniform(-self.jitter, self.jitter)))
                previous = due  # TCP bytes remain ordered even with jitter.
                await queue.put((due, data))
                self.stats['maximum_queued_chunks'] = max(self.stats['maximum_queued_chunks'], queue.qsize())
            await queue.put(None)

        async def consume():
            while item := await queue.get():
                due, data = item
                await asyncio.sleep(max(0, due - loop.time()))
                writer.write(data)
                await asyncio.wait_for(writer.drain(), 5)
                self.stats['forwarded_bytes'] += len(data)
                self.stats['chunks'] += 1

        children = [asyncio.create_task(produce()), asyncio.create_task(consume())]
        try:
            await asyncio.gather(*children)
        finally:
            for task in children: task.cancel()
            await asyncio.gather(*children, return_exceptions=True)

    async def handle(self, reader, writer):
        if self.closing or len(self.tasks) >= self.maximum:
            self.stats['rejected'] += 1
            writer.transport.abort()
            return
        task = asyncio.current_task()
        self.tasks.add(task)
        self.stats['accepted'] += 1
        identity = self.stats['accepted']
        upstream_writer = None
        pipes = []
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection('127.0.0.1', self.target_port, limit=65536), 5)
            pipes = [asyncio.create_task(self.pipe(reader, upstream_writer, self.seed + 2 * identity)),
                     asyncio.create_task(self.pipe(upstream_reader, writer, self.seed + 2 * identity + 1))]
            done, _ = await asyncio.wait(pipes, return_when=asyncio.FIRST_COMPLETED)
            for finished in done:
                finished.result()
        except (OSError, TimeoutError):
            self.stats['failures'] += 1
        finally:
            for child in pipes: child.cancel()
            owned = [selected for selected in (writer, upstream_writer) if selected is not None]
            for selected in owned: selected.close()
            try:
                await asyncio.gather(*pipes, return_exceptions=True)
                for selected in owned:
                    try: await asyncio.wait_for(selected.wait_closed(), 1)
                    except (OSError, TimeoutError): selected.transport.abort()
            finally:
                # close() can cancel a handler already draining after peer EOF.
                # Both handles and the reservation must survive that second exit.
                for selected in owned: selected.transport.abort()
                self.tasks.discard(task)

    async def close(self):
        self.closing = True
        if self.listener is not None:
            self.listener.close()
        pending = list(self.tasks)
        for task in pending: task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if self.listener is not None:
            await self.listener.wait_closed()
