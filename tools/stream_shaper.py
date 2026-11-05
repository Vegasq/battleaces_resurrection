"""Bounded loopback byte-stream delay for qualification; not a packet-loss model.

TLS stays end to end. This relay never decrypts, logs or persists payloads. Each
direction schedules ordered chunks independently, so a delayed chunk does not
add another whole RTT to every chunk queued behind it. OS TCP behavior is local.
"""
from __future__ import annotations

import asyncio
import math
import random
from concurrent.futures import Future
import threading


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
        self.listen_port, self.paused = None, False
        self.tasks = set()
        self.stats = dict(accepted=0, rejected=0, forwarded_bytes=0, chunks=0,
                          maximum_queued_chunks=0, failures=0,delay_samples=0,
                          delay_total_ms=0.0,minimum_delay_ms=None,maximum_delay_ms=0.0)

    async def start(self,listen_port=0):
        if type(listen_port) is not int or not 0<=listen_port<=65535:
            raise ValueError('Invalid local listener port')
        if self.listener is not None or self.closing:
            raise ValueError('Relay already started or closed')
        self.listener = await asyncio.start_server(self.handle, '127.0.0.1', listen_port, limit=65536)
        self.listen_port = self.listener.sockets[0].getsockname()[1]
        return self.listen_port

    async def outage(self):
        """Drop every owned relay stream and refuse new connections until restore."""
        if self.listener is None or self.closing or self.paused:
            raise ValueError('Relay is not serving')
        self.paused = True
        self.listener.close()
        pending = list(self.tasks)
        for task in pending: task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.listener.wait_closed()
        if self.tasks:
            raise RuntimeError('Relay streams survived outage')
        return dict(port=self.listen_port, disconnected=len(pending))

    async def restore(self):
        """Reopen the same loopback port after an owned outage."""
        if self.listener is None or self.closing or not self.paused or self.tasks:
            raise ValueError('Relay is not in a drained outage')
        listener = await asyncio.start_server(self.handle, '127.0.0.1', self.listen_port, limit=65536)
        self.listener, self.paused = listener, False
        return self.listen_port

    async def pipe(self, reader, writer, seed):
        queue = asyncio.Queue(32)  # <=2MiB, plus one in-flight chunk and stream buffers.
        rng, loop = random.Random(seed), asyncio.get_running_loop()

        async def produce():
            previous = 0.0
            while data := await reader.read(65536):
                received=loop.time()
                due = max(previous, received + max(0, self.delay + rng.uniform(-self.jitter, self.jitter)))
                previous = due  # TCP bytes remain ordered even with jitter.
                await queue.put((due, data,received))
                self.stats['maximum_queued_chunks'] = max(self.stats['maximum_queued_chunks'], queue.qsize())
            await queue.put(None)

        async def consume():
            while item := await queue.get():
                due, data,received = item
                await asyncio.sleep(max(0, due - loop.time()))
                held_ms=(loop.time()-received)*1000
                self.stats['delay_samples']+=1;self.stats['delay_total_ms']+=held_ms
                minimum=self.stats['minimum_delay_ms']
                self.stats['minimum_delay_ms']=held_ms if minimum is None else min(minimum,held_ms)
                self.stats['maximum_delay_ms']=max(self.stats['maximum_delay_ms'],held_ms)
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
        if self.closing or self.paused or len(self.tasks) >= self.maximum:
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


class ThreadedStreamShaper:
    """Owned event-loop thread for synchronous diagnostic controllers only."""
    def __init__(self,target_port,*,listen_port=0,**settings):
        self.shaper=StreamShaper(target_port,**settings)
        if type(listen_port) is not int or not 0<=listen_port<=65535:raise ValueError('Invalid listener port')
        self.ready=Future();self.finished=Future();self.loop=None;self.stop=None
        async def serve():
            self.loop=asyncio.get_running_loop();self.stop=asyncio.Event()
            try:
                port=await self.shaper.start(listen_port)
                self.ready.set_result(port)
                await self.stop.wait()
            finally:await self.shaper.close()
        def run():
            try:
                asyncio.run(serve())
                self.finished.set_result(dict(self.shaper.stats,active_connections=len(self.shaper.tasks),
                                              listener_closed=not self.shaper.listener.is_serving()))
            except BaseException as error:
                if not self.ready.done():self.ready.set_exception(error)
                self.finished.set_exception(error)
        self.thread=threading.Thread(target=run,name='owned-stream-delay',daemon=True);self.thread.start()
        try:self.port=self.ready.result(timeout=10)
        except BaseException:
            if self.loop and self.stop and not self.loop.is_closed():self.loop.call_soon_threadsafe(self.stop.set)
            self.thread.join(timeout=10)
            raise

    def close(self):
        if not self.finished.done():self.loop.call_soon_threadsafe(self.stop.set)
        try:result=self.finished.result(timeout=10)
        finally:self.thread.join(timeout=10)
        if self.thread.is_alive():raise RuntimeError('Owned relay thread did not stop')
        return result|dict(thread_stopped=True)

    def outage(self):
        return asyncio.run_coroutine_threadsafe(self.shaper.outage(),self.loop).result(timeout=10)

    def restore(self):
        return asyncio.run_coroutine_threadsafe(self.shaper.restore(),self.loop).result(timeout=10)
