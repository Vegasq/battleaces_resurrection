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
import time


class StreamShaper:
    def __init__(self, target_port, *, rtt_ms=0, jitter_ms=0, seed=1, maximum=8, metadata_limit=0):
        if type(target_port) is not int or not 1 <= target_port <= 65535:
            raise ValueError('Invalid local target port')
        for value, upper in ((rtt_ms, 500), (jitter_ms, 100)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= upper:
                raise ValueError('Delay must be finite: RTT0..500ms,jitter0..100ms')
        if type(seed) is not int or type(maximum) is not int or not 1 <= maximum <= 16:
            raise ValueError('Invalid relay seed or connection limit')
        if type(metadata_limit) is not int or not 0 <= metadata_limit <= 8192:
            raise ValueError('Metadata limit must be an integer0..8192 per direction')
        self.target_port, self.delay, self.jitter = target_port, rtt_ms / 2000, jitter_ms / 1000
        self.seed, self.maximum = seed, maximum
        self.listener, self.closing = None, False
        self.listen_port, self.paused = None, False
        self.tasks = set()
        self._owner_loop = None
        self._configured_rtt_ms, self._revision, self._setting = float(rtt_ms), 0, False
        self._directional_active = None
        self._directional_records = []
        self._directional_enabled = set()
        self.metadata_limit = metadata_limit
        self._metadata = {direction: dict(seen=0, dropped=0, rows=[]) for direction in
                          ('client_to_server', 'server_to_client')}
        self.stats = dict(accepted=0, rejected=0, forwarded_bytes=0, chunks=0,
                          maximum_queued_chunks=0, failures=0,delay_samples=0,
                          delay_total_ms=0.0,minimum_delay_ms=None,maximum_delay_ms=0.0)

    async def start(self,listen_port=0):
        if type(listen_port) is not int or not 0<=listen_port<=65535:
            raise ValueError('Invalid local listener port')
        if self.listener is not None or self.closing:
            raise ValueError('Relay already started or closed')
        self.listener = await asyncio.start_server(self.handle, '127.0.0.1', listen_port, limit=65536)
        self._owner_loop = asyncio.get_running_loop()
        self.listen_port = self.listener.sockets[0].getsockname()[1]
        return self.listen_port

    def set_rtt_ms(self, rtt_ms, *, tick=None):
        """Change future read chunks only, synchronously on the active owner loop.

        Returned perf-counter nanoseconds and optional caller ticks have separate
        clock domains. Configured delay is never a measured network/app RTT.
        Already queued chunks keep their deadlines, bytes and ordering.
        """
        if type(rtt_ms) not in (int, float) or not math.isfinite(rtt_ms) or not 0 <= rtt_ms <= 500:
            raise ValueError('RTT must be finite0..500ms')
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise ValueError('RTT changes require the active owning event loop') from None
        if (loop is not self._owner_loop or self.listener is None or self.closing or self.paused
                or not self.listener.is_serving() or self._setting):
            raise ValueError('RTT changes require the active owning event loop')
        if self._revision >= 32:
            raise ValueError('RTT change limit32 reached')
        if tick is not None and not callable(tick):
            raise ValueError('Tick must be a callable or None')
        def observed_tick():
            value = tick() if tick is not None else None
            if tick is not None and (type(value) is not int or value < 0):
                raise ValueError('Tick must return a nonnegative integer')
            return value
        old = self.delay, self._configured_rtt_ms, self._revision
        self._setting = True
        try:
            requested_perf = time.perf_counter_ns()
            requested_tick = observed_tick()
            self.delay, self._configured_rtt_ms = rtt_ms / 2000, float(rtt_ms)
            self._revision += 1
            effective_tick = observed_tick()
            effective_perf = time.perf_counter_ns()
            if requested_tick is not None and effective_tick < requested_tick:
                raise ValueError('Tick regressed during RTT change')
        except BaseException:
            self.delay, self._configured_rtt_ms, self._revision = old
            raise
        finally:
            self._setting = False
        return dict(revision=self._revision, configured_rtt_ms=self._configured_rtt_ms,
                    requested_tick_ms=requested_tick, effective_tick_ms=effective_tick,
                    requested_perf_counter_ns=requested_perf, effective_perf_counter_ns=effective_perf)

    def set_directional_delay(self, direction, extra_ms, duration_ms, *, tick=None):
        """Add noncumulative delay to future reads in one bounded loop-time window.

        The base ordered schedule includes any existing RTT queue debt. The
        extra delay is added to that base, then final byte order is preserved.
        Already queued chunks are never changed. Expiry affects future reads;
        their final deadlines can still follow an earlier delayed chunk.
        """
        if direction not in ('client_to_server', 'server_to_client') or type(direction) is not str:
            raise ValueError('Direction must be client_to_server or server_to_client')
        if (type(extra_ms) not in (int, float) or not math.isfinite(extra_ms) or not 0 < extra_ms <= 100 or
                type(duration_ms) not in (int, float) or not math.isfinite(duration_ms) or not 1 <= duration_ms <= 1000):
            raise ValueError('Directional delay must be finite: extra>0..100ms,duration1..1000ms')
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            raise ValueError('Directional delay requires the active owning event loop') from None
        if (loop is not self._owner_loop or self.listener is None or self.closing or self.paused or
                not self.listener.is_serving() or self._setting):
            raise ValueError('Directional delay requires the active owning event loop')
        if len(self._directional_records) >= 32:
            raise ValueError('Directional delay window limit32 reached')
        if self._directional_active is not None and loop.time() < self._directional_active['end_loop']:
            raise ValueError('Directional delay windows must not overlap')
        if tick is not None and not callable(tick):
            raise ValueError('Tick must be a callable or None')
        def observed_tick():
            value = tick() if tick is not None else None
            if tick is not None and (type(value) is not int or value < 0):
                raise ValueError('Tick must return a nonnegative integer')
            return value
        old = self._directional_active
        self._setting = True
        try:
            requested_perf = time.perf_counter_ns()
            requested_tick = observed_tick()
            start = loop.time()
            record = dict(window_id=len(self._directional_records)+1, direction=direction,
                          extra_ms=float(extra_ms), duration_ms=float(duration_ms),
                          requested_tick_ms=requested_tick, effective_tick_ms=None,
                          requested_perf_counter_ns=requested_perf, effective_perf_counter_ns=None,
                          start_loop=start, end_loop=start+duration_ms/1000)
            self._directional_active = record
            effective_tick = observed_tick()
            effective_perf = time.perf_counter_ns()
            if requested_tick is not None and effective_tick < requested_tick:
                raise ValueError('Tick regressed during directional delay change')
            record.update(effective_tick_ms=effective_tick, effective_perf_counter_ns=effective_perf)
            self._directional_records.append(record)
            self._directional_enabled.add(direction)
        except BaseException:
            self._directional_active = old
            raise
        finally:
            self._setting = False
        return dict(record)

    def _directional_for_read(self, direction, received):
        active = self._directional_active
        if (active is not None and active['direction'] == direction and
                active['start_loop'] <= received < active['end_loop']):
            return active['extra_ms'], active['window_id']
        return 0.0, None

    def delay_metadata(self):
        """Detached payload-free snapshot; first N records retained per direction.

        Loop times describe read scheduling/write/drain observations. None means
        the corresponding operation has not completed (including cancellation).
        The default0 performs no chunk capture and leaves ordinary stats intact.
        """
        result = dict(schema=1, metadata_limit=self.metadata_limit, revision=self._revision,
                    configured_rtt_ms=self._configured_rtt_ms, directions={
                        key: dict(seen=value['seen'], dropped=value['dropped'],
                                  rows=[dict(row) for row in value['rows']])
                        for key, value in self._metadata.items()})
        if self._directional_records:
            result['directional_delays'] = [dict(record) for record in self._directional_records]
        return result

    def _chunk_metadata(self, direction, connection, received, due, size):
        if not self.metadata_limit:
            return None
        bucket = self._metadata[direction]
        bucket['seen'] += 1
        if len(bucket['rows']) >= self.metadata_limit:
            bucket['dropped'] += 1
            return None
        row = dict(connection=connection, chunk=bucket['seen'], revision=self._revision,
                   configured_rtt_ms=self._configured_rtt_ms, received_loop=received,
                   due_loop=due, byte_count=size, forwarded_loop=None, drained_loop=None, held_ms=None)
        bucket['rows'].append(row)
        return row

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

    async def pipe(self, reader, writer, seed, *, direction='client_to_server', connection=0):
        queue = asyncio.Queue(32)  # <=2MiB, plus one in-flight chunk and stream buffers.
        rng, loop = random.Random(seed), asyncio.get_running_loop()

        async def produce():
            previous_base = previous_final = 0.0
            while data := await reader.read(65536):
                received=loop.time()
                base_due = max(previous_base, received + max(0, self.delay + rng.uniform(-self.jitter, self.jitter)))
                extra_ms, window_id = self._directional_for_read(direction, received)
                due = max(previous_final, base_due + extra_ms / 1000)
                previous_base, previous_final = base_due, due  # Separate debt avoids per-chunk accumulation.
                metadata = self._chunk_metadata(direction, connection, received, due, len(data))
                if metadata is not None and direction in self._directional_enabled:
                    metadata.update(base_due_loop=base_due, directional_extra_ms=extra_ms,
                                    directional_window_id=window_id, final_due_loop=due)
                await queue.put((due, data,received,metadata))
                self.stats['maximum_queued_chunks'] = max(self.stats['maximum_queued_chunks'], queue.qsize())
            await queue.put(None)

        async def consume():
            while item := await queue.get():
                due, data,received,metadata = item
                await asyncio.sleep(max(0, due - loop.time()))
                held_ms=(loop.time()-received)*1000
                self.stats['delay_samples']+=1;self.stats['delay_total_ms']+=held_ms
                minimum=self.stats['minimum_delay_ms']
                self.stats['minimum_delay_ms']=held_ms if minimum is None else min(minimum,held_ms)
                self.stats['maximum_delay_ms']=max(self.stats['maximum_delay_ms'],held_ms)
                writer.write(data)
                if metadata is not None:
                    metadata['forwarded_loop'] = loop.time()
                    metadata['held_ms'] = (metadata['forwarded_loop'] - received) * 1000
                await asyncio.wait_for(writer.drain(), 5)
                if metadata is not None:
                    metadata['drained_loop'] = loop.time()
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
            pipes = [asyncio.create_task(self.pipe(reader, upstream_writer, self.seed + 2 * identity,
                                                  direction='client_to_server', connection=identity)),
                     asyncio.create_task(self.pipe(upstream_reader, writer, self.seed + 2 * identity + 1,
                                                  direction='server_to_client', connection=identity))]
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
