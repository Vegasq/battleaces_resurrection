"""Owned TLS/public-protocol coordinator measurements, never a live host.

Scripted endpoint peers are not Unity rendering/physical-input evidence. Delays
are deterministic application-message delivery holds over real loopback TLS,
not packet loss, remote TCP or a claim about Internet RTT. All timing differences
use this coordinator process's perf_counter; worker/QPC domains are never mixed.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from collections import defaultdict, deque
from dataclasses import dataclass
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import queue
import random
import struct
import sys
import threading
import time
import traceback

from server import admission, command_scheduling as wire, community_protocol as c
from server import dedicated_server as ds, protocol as p, public_protocol as q, tls_transport as tls
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.game_data import GameTemplate, encode_frame
from server.profiles import ProfileStore
from server.protobuf_wire import get_repeated_bytes
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker
from tools import benchmark_large_armies as army

ROOT = Path(__file__).resolve().parents[1]
require, digest, summary = army.require, army.digest, army.summary
MAX_EVENTS = 300000
# Eight TLS peers can emit >64 records in one ready-task burst before the
# interpreter schedules the writer. Keep that burst bounded without retaining
# an entire match; a slow/full sink still fails rather than blocking gameplay.
TRACE_QUEUE_ROWS = 256
MAX_TRACE_BYTES = 512*1024*1024


def file_digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(256*1024), b''): value.update(block)
    return value.hexdigest()


class EventRows:
    """Reiterable disk view; no decoded whole-trace retention."""
    def __init__(self, path, owner=None):
        self.path, self.owner = path, owner

    def __len__(self):
        require(self.owner is not None, 'row count requires an owned trace')
        return self.owner.count

    def __iter__(self):
        require(self.owner is None or self.owner.closed, 'trace must be finalized before analysis')
        with self.path.open(encoding='utf-8') as stream:
            for index, line in enumerate(stream):
                require(index < MAX_EVENTS and len(line) <= 2*1024*1024, 'trace row/count exceeds bound')
                yield json.loads(line)


class Trace:
    def __init__(self, output, *, queue_rows=TRACE_QUEUE_ROWS):
        self.origin = time.perf_counter()
        require(type(queue_rows) is int and 1 <= queue_rows <= TRACE_QUEUE_ROWS, 'invalid trace queue bound')
        self.path = output/'events.jsonl'
        self.rows = EventRows(self.path, self)
        self.pending_commands = defaultdict(set)
        self.unexpected_events = 0
        self.publications = {}
        self.emit_ms = defaultdict(float)
        self.stream = self.path.open('x', encoding='utf-8')
        self.queue = queue.Queue(queue_rows)
        self.count = self.written = self.bytes_written = self.high_water = 0
        self.maximum_row_bytes = 0
        self.sink_cpu_ms = self.sink_active_ms = 0.0
        self.failure, self.closed, self.complete = None, False, False
        self.sink = threading.Thread(target=self._write_loop, name='ba-benchmark-trace', daemon=True)
        self.sink.start()
        self.clock = dict(kind='coordinator-process-perf_counter', pid=os.getpid(), platform=sys.platform,
                          origin_seconds=self.origin, wall_origin_seconds=time.time(), unit='milliseconds')

    def now(self):
        return (time.perf_counter()-self.origin)*1000

    def emit(self, event, **fields):
        began = time.perf_counter()
        require(not self.closed and self.failure is None, 'diagnostic trace writer unavailable: '+str(self.failure))
        if self.count >= MAX_EVENTS:
            self.failure = 'bounded diagnostic event capacity exceeded'
            raise ValueError(self.failure)
        row = dict(event=event, at_ms=self.now(), **fields)
        try:
            self.queue.put_nowait(row)
        except queue.Full:
            self.failure = 'diagnostic trace queue saturated; run cannot qualify'
            raise ValueError(self.failure) from None
        self.count += 1
        self.high_water = max(self.high_water, self.queue.qsize())
        if event == 'client_command_created':
            self.pending_commands[fields['match']].add((fields['slot'], fields['sequence']))
        elif event == 'command_batch_committed':
            self.pending_commands[fields['match']].discard((fields['slot'], fields['sequence']))
        if event == 'frame_queued':
            self.publications[fields['match']] = fields['frame']
        if event == 'protocol_error' or (event == 'match_aborted' and fields.get('reason') != 'bounded benchmark episode teardown'):
            self.unexpected_events += 1
        self.emit_ms[event] += (time.perf_counter()-began)*1000
        return row

    def _write_loop(self):
        began = time.perf_counter()
        cpu = time.thread_time()
        self.sink_thread_id = threading.get_native_id()
        try:
            while True:
                row = self.queue.get()
                if row is None:
                    self.queue.task_done()
                    break
                active = time.perf_counter()
                encoded = json.dumps(row, sort_keys=True, allow_nan=False)+'\n'
                size = len(encoded.encode('utf-8'))
                require(size <= 2*1024*1024 and self.bytes_written+size <= MAX_TRACE_BYTES, 'trace byte limit exceeded')
                self.stream.write(encoded)
                self.bytes_written += size
                self.maximum_row_bytes = max(self.maximum_row_bytes, size)
                self.written += 1
                self.sink_active_ms += (time.perf_counter()-active)*1000
                self.queue.task_done()
            active = time.perf_counter()
            self.stream.flush()
            self.sink_active_ms += (time.perf_counter()-active)*1000
        except BaseException as error:
            self.failure = f'{type(error).__name__}: {error}'
        finally:
            try:
                self.stream.close()
            except BaseException as error:
                self.failure = f'{type(error).__name__} closing trace: {error}'
            self.sink_cpu_ms = (time.thread_time()-cpu)*1000
            self.sink_lifetime_ms = (time.perf_counter()-began)*1000

    def close(self):
        if not self.closed:
            began = time.perf_counter()
            if self.sink.is_alive():
                try: self.queue.put(None, timeout=10)
                except queue.Full: self.failure = 'trace shutdown queue remained full'
                self.sink.join(timeout=10)
            self.closed = True
            self.shutdown_ms = (time.perf_counter()-began)*1000
            self.complete = self.failure is None and not self.sink.is_alive() and self.written == self.count
        require(self.complete, 'diagnostic trace incomplete: '+str(self.failure))

    def report(self):
        return dict(persistence='bounded background JSON/disk writer; any saturation/write/shutdown error fails qualification',
                    queue_row_limit=self.queue.maxsize, queue_high_water=self.high_water, enqueued=self.count,
                    written=self.written, bytes_written=self.bytes_written, complete=self.complete, failure=self.failure,
                    maximum_row_json_bytes=self.maximum_row_bytes, retained_row_reference_limit=self.queue.maxsize+1,
                    sink_thread_id=getattr(self, 'sink_thread_id', None), sink_thread_id_domain=sys.platform,
                    sink_cpu_ms=self.sink_cpu_ms, sink_active_ms=self.sink_active_ms,
                    sink_lifetime_ms=getattr(self, 'sink_lifetime_ms', None), shutdown_ms=getattr(self, 'shutdown_ms', None),
                    emit_ms_by_event=dict(self.emit_ms), pending_command_keys=sum(map(len, self.pending_commands.values())),
                    retained_full_trace_rows=False, scope='writer CPU/GIL/disk overhead remains in process/cgroup measurements; no claim of zero observer cost')


class Delivery:
    """An ordered per-message schedule; no RNG/TCP-chunk-dependent jitter."""
    def __init__(self, rtt_ms, jitter, trace, identity, direction):
        require(rtt_ms in (0, 130, 475) and jitter and len(jitter) <= 256 and
                all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 100 for x in jitter), 'invalid delay trace')
        self.half, self.jitter, self.trace = rtt_ms/2, tuple(jitter), trace
        self.identity, self.direction, self.ordinal, self.previous_due = identity, direction, 0, 0.0

    def schedule(self, now):
        requested = max(0.0, self.half+self.jitter[self.ordinal % len(self.jitter)])
        due = max(self.previous_due, now+requested)
        self.previous_due, self.ordinal = due, self.ordinal+1
        return due, requested, max(0.0, due-now-requested)

    async def hold(self, tag):
        began = self.trace.now()
        due, requested, ordered = self.schedule(began)
        await self.wait(tag, began, due, requested, ordered, self.ordinal)

    async def wait(self, tag, began, due, requested, ordered, ordinal):
        await asyncio.sleep(max(0, due-self.trace.now())/1000)
        ended = self.trace.now()
        self.trace.emit('delivery_hold', peer=self.identity, direction=self.direction, tag=tag,
                        ordinal=ordinal, requested_ms=requested, ordering_ms=ordered,
                        actual_ms=ended-began, oversleep_ms=max(0, ended-due))


class Peer:
    def __init__(self, reader, writer, trace, name, rtt_ms, jitter):
        self.reader, self.writer, self.trace, self.name = reader, writer, trace, name
        self.request = self.sequence = 0
        self.slot = None
        self.match = None
        self.applied = -1
        self.queue = asyncio.Queue(128)
        self.pending = defaultdict(deque)
        self.frames = asyncio.Queue(128)
        self.up = Delivery(rtt_ms, jitter, trace, name, 'uplink')
        self.down = Delivery(rtt_ms, jitter, trace, name, 'downlink')
        self.delivery_queue = asyncio.Queue(128)
        self.tx_queue = asyncio.Queue(128)
        self.sender_lock = asyncio.Lock()
        self.tasks = [asyncio.create_task(self.read_loop()), asyncio.create_task(self.deliver_loop()),
                      asyncio.create_task(self.transmit_loop())]

    async def read_loop(self):
        try:
            while True:
                kind, payload = await p.receive(self.reader)
                if kind == q.FRAME:
                    frame, inputs = q.decode_frame(payload, self.count)
                    self.trace.emit('client_frame_received', peer=self.name, match=self.match, slot=self.slot,
                                    frame=frame, payload_sha256=digest(payload), input_sha256=digest(encode_frame(frame, inputs)))
                    began = self.trace.now()
                    due, requested, ordered = self.down.schedule(began)
                    await self.delivery_queue.put((frame, inputs, began, due, requested, ordered, self.down.ordinal))
                elif kind in (c.DIRECTORY, c.LOBBY, p.LOBBY, p.NOTICE):
                    continue
                else:
                    await self.queue.put((kind, payload))
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            await self.queue.put((None, repr(error).encode()))

    async def deliver_loop(self):
        while True:
            frame, inputs, began, due, requested, ordered, ordinal = await self.delivery_queue.get()
            await self.down.wait(str(frame), began, due, requested, ordered, ordinal)
            require(frame == self.applied+1, 'client publication loss/reordering')
            self.applied = frame
            self.trace.emit('client_frame_delivered', peer=self.name, match=self.match, slot=self.slot, frame=frame)
            await self.frames.put((frame, inputs))

    async def transmit_loop(self):
        while True:
            payload, sequence, began, due, requested, ordered, ordinal = await self.tx_queue.get()
            try:
                await self.up.wait(f'batch:{sequence}', began, due, requested, ordered, ordinal)
                await self.send(wire.BATCH, payload, sequence=sequence)
            finally:
                self.tx_queue.task_done()

    async def send(self, kind, payload=b'', *, delayed=False, tag='control', sequence=None):
        async with self.sender_lock:
            if delayed:
                await self.up.hold(tag)
            self.writer.write(p.encode(kind, payload))
            if sequence is not None:
                self.trace.emit('client_command_sent', peer=self.name, match=self.match, slot=self.slot, sequence=sequence)
            await asyncio.wait_for(self.writer.drain(), 5)

    async def receive(self, wanted):
        if self.pending[wanted]:
            return self.pending[wanted].popleft()
        async with asyncio.timeout(180):
            while True:
                kind, payload = await self.queue.get()
                require(kind not in (None, p.ERROR, c.ABORTED), 'peer protocol/transport failed')
                if kind == wanted:
                    return payload
                self.pending[kind].append(payload)
                require(sum(len(values) for values in self.pending.values()) <= 128, 'peer control backlog exceeded')

    async def command(self, kind, **kwargs):
        self.request += 1
        await self.send(kind, q.command(kind, self.request, 1, **kwargs))
        reply = c.Reader(await self.receive(c.ACK))
        require((reply.number('I'), reply.number('B')) == (self.request, kind), 'command ACK mismatch')
        accepted, reason, identity = reply.flag(), reply.text(), reply.text()
        reply.end()
        require(accepted, 'public command refused: '+reason)
        return identity

    async def batch(self, body, *, intent=None):
        self.sequence += 1
        sequence = self.sequence
        self.trace.emit('client_command_created', peer=self.name, match=self.match, slot=self.slot,
                        sequence=sequence, body_sha256=digest(body), intent=intent)
        began = self.trace.now()
        due, requested, ordered = self.up.schedule(began)
        await self.tx_queue.put((wire.batch(self.match, sequence, body), sequence, began, due, requested, ordered, self.up.ordinal))

    async def close(self):
        self.writer.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except (OSError, TimeoutError):
            self.writer.transport.abort()


class FixedTemplate(GameTemplate):
    def build_match(self, roster, decks, seed=None, game_name=None, **kwargs):
        return super().build_match(roster, decks, seed=self.benchmark_seed,
                                  game_name=f'owned-coordinator-benchmark-{self.benchmark_seed}', **kwargs)


def benchmark_token(seed, name):
    """Publicly reproducible diagnostic identity, used only on our owned loopback host."""
    raw = hashlib.sha256(json.dumps(['owned-coordinator-benchmark-v1', seed, name]).encode()).digest()
    return 'ba1_'+base64.urlsafe_b64encode(raw).decode().rstrip('=')


class ObservedWorker:
    def __init__(self, worker, trace, spec):
        self.worker, self.trace, self.spec = worker, trace, spec
        self.halt, self.match = False, None
        self.last_observation = None
        self.ai_ms = 0.0
        self.idle = asyncio.Event()
        self.idle.set()

    def __getattr__(self, name):
        return getattr(self.worker, name)

    async def bot_inputs(self, frame):
        if self.halt:
            await asyncio.Event().wait()
        started = self.trace.now()
        self.idle.clear()
        try:
            result = await self.worker.bot_inputs(frame)
        finally:
            self.idle.set()
        self.ai_ms = self.trace.now()-started
        return result

    async def process_frame(self, payload, dt_ms=None):
        if self.halt:
            # Teardown barrier BEFORE an original RPC, never inside measured work.
            await asyncio.Event().wait()
        prior = self.worker.last_state
        started = self.trace.now()
        self.idle.clear()
        try:
            result = await self.worker.process_frame(payload, dt_ms)
        finally:
            self.idle.set()
        ended = self.trace.now()
        observation = army.observation(result.state, prior, self.spec)
        self.last_observation = observation
        state_sha = army.state_digest(result.state)
        observed = self.trace.now()
        self.trace.emit('worker_frame', match=self.match, frame=result.frame, worker_pid=self.pid,
                        input_sha256=digest(payload), state_sha256=state_sha,
                        step_rpc_ms=ended-started, ai_rpc_ms=self.ai_ms,
                        observer_ms=observed-ended, **observation)
        self.ai_ms = 0
        return result

    async def stop_requests(self):
        self.halt = True
        await asyncio.wait_for(self.idle.wait(), 20)


def active_load(observation, scripted, target, fraction):
    return observation is not None and not observation.get('game_complete', False) and all(
        observation['unit_counts'][str(s)] >= math.ceil(target*fraction) for s in scripted)


def active_intervals(rows, episode, start_ms, end_ms, target, fraction, motion_fraction=None):
    """Integrate observed frame-state occupancy; setup/depletion/gaps get no credit."""
    selected = [r for r in rows if r['event'] == 'worker_frame' and r['match'] == episode.room.match_id]
    lower = max(start_ms, episode.active_started if episode.active_started is not None else end_ms)
    intervals = []
    for index, row in enumerate(selected):
        left = max(lower, row['at_ms'])
        right = min(end_ms, selected[index+1]['at_ms'] if index+1 < len(selected) else episode.ended)
        motion = motion_fraction is None or all(row['moving_units'][str(s)] >= max(1, math.ceil(
            row['unit_counts'][str(s)]*motion_fraction)) for s in episode.driver.scripted)
        if right > left and motion and active_load(row, episode.driver.scripted, target, fraction):
            if intervals and abs(intervals[-1][1]-left) < 1e-6:
                intervals[-1] = (intervals[-1][0], right)
            else:
                intervals.append((left, right))
    return intervals


def overlap_seconds(by_lane):
    events = []
    for lane, intervals in by_lane.items():
        for start, end in intervals:
            events.extend(((start, 1, lane), (end, -1, lane)))
    active, previous, total = {}, None, 0.0
    for at, delta, lane in sorted(events):
        if previous is not None and len(active) == len(by_lane):
            total += at-previous
        active[lane] = active.get(lane, 0)+delta
        if active[lane] == 0:
            del active[lane]
        previous = at
    return total/1000


def proc_stat(value):
    tail = value[value.rfind(')')+2:].split()
    require(len(tail) >= 22, 'truncated Linux task stat')
    return dict(cpu_ticks=int(tail[11])+int(tail[12]), start_ticks=int(tail[19]), rss_pages=int(tail[21]))


class ResourceSampler:
    """Read ONLY an operator-selected isolated cgroup and its Linux task members."""
    def __init__(self, args, trace):
        self.args, self.trace, self.samples, self.stopped = args, trace, [], False
        self.previous_cpu, self.cpu_count, self.cpu_sum, self.cpu_max = {}, 0, 0.0, 0.0

    def read(self):
        began = self.trace.now()
        proc, group = self.args.proc_root, self.args.resource_cgroup
        sample = dict(capture_ms=began, linux_clock_ticks=self.args.linux_clock_ticks, tasks=[], errors=[])
        def small(path, limit=65536):
            try:
                with path.open('r', encoding='utf-8') as stream:
                    value = stream.read(limit+1)
                require(len(value) <= limit, 'resource counter exceeds bounded size')
                return value
            except OSError:
                sample['errors'].append(path.name)
                return ''
        memory = {}
        for line in small(proc/'meminfo').splitlines():
            name, value = line.split(':', 1)
            if name in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
                memory[name] = int(value.split()[0])*1024
        sample['host_memory_bytes'] = memory
        for name in ('cpu', 'memory', 'io'):
            sample['pressure_'+name] = small(proc/'pressure'/name)
        for name in ('cpu.stat', 'memory.current', 'memory.peak', 'memory.swap.current', 'memory.events', 'io.stat'):
            sample['cgroup_'+name] = small(group/name)
        groups = list(group.rglob('cgroup.procs'))
        if (group/'cgroup.procs').is_file() and group/'cgroup.procs' not in groups:
            groups.append(group/'cgroup.procs')
        require(len(groups) <= 64, 'resource cgroup descendants exceed bound')
        pids = {int(value) for file in groups for value in small(file).split()}
        require(len(pids) <= 256, 'resource cgroup process count exceeds bound')
        for pid in sorted(pids):
            directory = proc/str(pid)
            process = small(directory/'stat')
            if not process:
                continue
            identity = proc_stat(process)
            tasks = list((directory/'task').glob('*/stat'))
            require(len(tasks) <= 256 and len(sample['tasks'])+len(tasks) <= 1024, 'resource thread count exceeds bound')
            for task in tasks:
                value = small(task)
                if value:
                    sample['tasks'].append(dict(pid=pid, tid=int(task.parent.name), process_start_ticks=identity['start_ticks'],
                                                **proc_stat(value)))
        sample['task_count'] = len(sample['tasks'])
        current = {}
        for task in sample['tasks']:
            identity = tuple(task[k] for k in ('pid', 'process_start_ticks', 'tid', 'start_ticks'))
            if identity in self.previous_cpu:
                old, at = self.previous_cpu[identity]
                elapsed = sample['capture_ms']-at
                if elapsed > 0:
                    rate = max(0, task['cpu_ticks']-old)*100000/(sample['linux_clock_ticks']*elapsed)
                    self.cpu_count += 1
                    self.cpu_sum += rate
                    self.cpu_max = max(self.cpu_max, rate)
            current[identity] = (task['cpu_ticks'], sample['capture_ms'])
        self.previous_cpu = current
        sample['sampler_ms'] = self.trace.now()-began
        # Full task dictionaries go only to the bounded writer; retain small counters.
        self.samples.append({key: value for key, value in sample.items() if key != 'tasks'})
        self.trace.emit('resource_sample', **sample)

    async def run(self):
        if self.args.resource_cgroup is None:
            return
        while not self.stopped:
            self.read()
            await asyncio.sleep(1)

    def report(self):
        complete = bool(self.samples) and all(s['host_memory_bytes'].get('MemAvailable') is not None and
            s['task_count'] and s['cgroup_memory.current'] and s['cgroup_memory.swap.current'] and s['cgroup_cpu.stat']
            and not {'io.stat', 'memory.events', 'memory.peak'} & set(s['errors'])
            and all(s['pressure_'+name] for name in ('cpu', 'memory', 'io')) for s in self.samples)
        return dict(scope='explicit isolated Linux cgroup; Linux PID/start_ticks identity, never Windows PID',
            cgroup=str(self.args.resource_cgroup) if self.args.resource_cgroup else None, complete=complete,
            samples=len(self.samples), sampler_ms=summary([s['sampler_ms'] for s in self.samples]),
            per_thread_cpu_percent=dict(count=self.cpu_count, mean=self.cpu_sum/self.cpu_count if self.cpu_count else None,
                                        maximum=self.cpu_max if self.cpu_count else None,
                                        detail='full per-thread counters retained in streamed resource_sample events'),
            retained_resource_task_dicts=0, retained_resource_summary_rows=len(self.samples),
            minimum_available_bytes=min((s['host_memory_bytes'].get('MemAvailable', 0) for s in self.samples), default=None),
            peak_cgroup_memory_bytes=max((int(s['cgroup_memory.peak'] or 0) for s in self.samples), default=None),
            maximum_sampled_cgroup_memory_bytes=max((int(s['cgroup_memory.current'] or 0) for s in self.samples), default=None),
            maximum_cgroup_swap_bytes=max((int(s['cgroup_memory.swap.current'] or 0) for s in self.samples), default=None))


def count_summary(values):
    return {k: v for k, v in summary(values).items() if not k.startswith('above_')}


def publication_stats(rows, start_ms=None, end_ms=None):
    if len(rows) < 2:
        return dict(frames=len(rows), effective_hz=None, gaps_ms=summary([]), cadence_pass=False)
    gaps = [b['at_ms']-a['at_ms'] for a, b in zip(rows, rows[1:])]
    require(all(gap > 0 for gap in gaps), 'publication clock/order differs')
    elapsed = (rows[-1]['at_ms']-rows[0]['at_ms'])/1000
    hz = (len(rows)-1)/elapsed
    if start_ms is not None and end_ms is not None:
        require(start_ms <= rows[0]['at_ms'] < rows[-1]['at_ms'] <= end_ms, 'publication outside measurement interval')
        gaps = [rows[0]['at_ms']-start_ms] + gaps + [end_ms-rows[-1]['at_ms']]
        hz = len(rows)/((end_ms-start_ms)/1000)
    return dict(frames=len(rows), effective_hz=hz, gaps_ms=summary(gaps),
                cadence_pass=19.8 <= hz <= 20.2 and max(gaps) <= 100)


def measurements(rows, origins, lane_matches, measurement_start=None, measurement_end=None):
    def commands(event):
        result = {}
        for row in (r for r in rows if r['event'] == event):
            key = row['match'], row['slot'], row['sequence']
            require(key not in result, 'duplicate command event: '+event)
            result[key] = {name: row[name] for name in ('at_ms', 'body_sha256', 'frame') if name in row}
        return result
    accepted, commits = commands('command_batch_accepted'), commands('command_batch_committed')
    created, sent = commands('client_command_created'), commands('client_command_sent')
    def frames(event, fields, client=False):
        result = {}
        for row in (r for r in rows if r['event'] == event):
            key = (row['match'], row['slot'], row['frame']) if client else (row['match'], row['frame'])
            require(key not in result, 'duplicate frame event: '+event)
            result[key] = {name: row[name] for name in fields}
        return result
    pubs = frames('frame_queued', ('at_ms', 'frame_work_ms', 'frame_payload_sha256'))
    sealed = frames('command_frame_sealed', ('at_ms', 'batches'))
    delivered = frames('client_frame_delivered', ('at_ms',), client=True)
    workers = frames('worker_frame', ('at_ms', 'step_rpc_ms', 'ai_rpc_ms', 'observer_ms', 'input_sha256'))
    times = {k: [] for k in ('injected_uplink_ms', 'sent_to_accepted_ms', 'accepted_to_sealed_ms',
                            'sealed_to_published_ms', 'created_to_delivered_ms', 'coordinator_outside_worker_ms')}
    missing = sorted((created.keys() | sent.keys() | accepted.keys() | commits.keys()) -
                     (created.keys() & sent.keys() & accepted.keys() & commits.keys()))
    for key, commit in commits.items():
        match, slot, sequence = key
        frame_key = match, commit['frame']
        pieces = [created.get(key), sent.get(key), accepted.get(key), sealed.get(frame_key), pubs.get(frame_key),
                  delivered.get((match, slot, commit['frame'])), workers.get(frame_key)]
        if any(piece is None for piece in pieces):
            if key not in missing: missing.append(key)
            continue
        origin, tx, accept, seal, pub, delivery, worker = pieces
        require(origin['body_sha256'] == accept['body_sha256'] == commit['body_sha256'], 'command bytes changed in transit')
        require(sequence in seal['batches'].get(slot, seal['batches'].get(str(slot), ())), 'committed command was not sealed into frame')
        selected = commit['at_ms'] >= (measurement_start if measurement_start is not None else origins.get(match, float('inf')))
        selected &= measurement_end is None or commit['at_ms'] <= measurement_end
        for name, end, start in (('injected_uplink_ms', tx, origin), ('sent_to_accepted_ms', accept, tx),
                                 ('accepted_to_sealed_ms', seal, accept), ('sealed_to_published_ms', pub, seal),
                                 ('created_to_delivered_ms', delivery, origin)):
            require(end['at_ms'] >= start['at_ms'], 'same-domain event timestamps are out of order')
            if selected: times[name].append(end['at_ms']-start['at_ms'])
        residual = pub['frame_work_ms']-worker['step_rpc_ms']-worker['ai_rpc_ms']-worker['observer_ms']
        require(residual >= -.01, 'worker/observer timing exceeds enclosing frame work')
        if selected: times['coordinator_outside_worker_ms'].append(residual)
    frame_times = {name: [] for name in ('step_rpc_ms', 'ai_rpc_ms', 'observer_ms', 'frame_work_ms', 'coordinator_outside_worker_ms')}
    for key, pub in pubs.items():
        lower = measurement_start if measurement_start is not None else origins.get(key[0], float('inf'))
        if pub['at_ms'] < lower or (measurement_end is not None and pub['at_ms'] > measurement_end):
            continue
        require(key in workers, 'published frame has no native worker receipt')
        worker = workers[key]
        residual = pub['frame_work_ms']-worker['step_rpc_ms']-worker['ai_rpc_ms']-worker['observer_ms']
        require(residual >= -.01, 'worker/observer timing exceeds enclosing frame work')
        for name in ('step_rpc_ms', 'ai_rpc_ms', 'observer_ms'): frame_times[name].append(worker[name])
        frame_times['frame_work_ms'].append(pub['frame_work_ms'])
        frame_times['coordinator_outside_worker_ms'].append(residual)
    lanes = {}
    for lane, matches in lane_matches.items():
        start = measurement_start if measurement_start is not None else min((origins[m] for m in matches if m in origins), default=float('inf'))
        selected = [r for r in rows if r['event'] == 'frame_queued' and r['match'] in matches and r['at_ms'] >= start
                    and (measurement_end is None or r['at_ms'] <= measurement_end)]
        # Episode gaps remain here; an active-load filter may NOT erase stalls.
        lanes[str(lane)] = publication_stats(selected, start, measurement_end)
    waits = [r for r in rows if r['event'] == 'delivery_hold']
    for row in (r for r in rows if r['event'] == 'client_frame_received'):
        publication = pubs.get((row['match'], row['frame']))
        require(publication is not None and row['payload_sha256'] == publication['frame_payload_sha256'],
                'TLS client received different authoritative frame bytes')
        native = workers.get((row['match'], row['frame']))
        require(native is not None and row['input_sha256'] == native['input_sha256'],
                'TLS publication differs from original native worker inputs')
    return dict(command_timings_ms={k: summary(v) for k, v in times.items()}, unmatched_committed_commands=missing,
                frame_timings_ms={k: summary(v) for k, v in frame_times.items()},
                conservation=dict(created=len(created), sent=len(sent), accepted=len(accepted), committed=len(commits),
                                  complete=not missing),
                residual_scope='frame work outside AI/STEP RPC and observer; excludes work inside worker RPC and is not full causal coordinator attribution',
                publication=lanes, injected_delivery={k: summary([r[k] for r in waits]) for k in
                ('requested_ms', 'ordering_ms', 'actual_ms', 'oversleep_ms')})


@dataclass
class Episode:
    lane: int
    number: int
    room: object
    peers: list
    driver: object
    started: float
    active_started: float | None = None
    active_seconds: float = 0.0
    depleted_since: float | None = None
    last_sample: float | None = None
    ended: float = float('inf')


class Experiment:
    def __init__(self, args, trace, template, spec, backend):
        self.args, self.trace, self.template, self.spec, self.backend = args, trace, template, spec, backend
        self.workers, self.peers, self.episodes = [], [], []
        self.origins, self.lane_matches = {}, {lane: [] for lane in range(args.matches)}
        self.server = None
        self.startups = []
        self.measurement_start = self.target_end = None

    async def factory(self, data, bots=None):
        directory = self.args.output/f'worker-{len(self.workers)}'
        directory.mkdir()
        started = self.trace.now()
        worker = await SimulationWorker.create(data, self.args.assets/'Simulation.dll', working_directory=directory,
            ai=AISetup(self.args.assets, bots) if bots else None, backend=self.backend,
            **({'snapshot_decoder_library': self.args.snapshot_decoder_library,
                'snapshot_decoder_sha256': self.args.snapshot_decoder_sha256}
               if getattr(self.args, 'snapshot_decoder_library', None) else {}),
            startup_timeout=120, request_timeout=15, close_timeout=3)
        self.startups.append(dict(start_ms=started, elapsed_ms=self.trace.now()-started, worker_pid=worker.pid,
                                 native_pid=worker.native_pid, runtime=worker.runtime_info,
                                 snapshot_decoder=worker.decoder_info))
        wrapped = ObservedWorker(worker, self.trace, self.spec)
        self.workers.append(wrapped)
        return wrapped

    async def start(self):
        catalog = BotCatalog(self.args.assets, template=self.template, rules=RuleBook(self.args.assets))
        original_choose = catalog.choose
        def choose(*a, **kw):
            excluded = sorted(kw.get('excluded_names', ()))
            humans = [name for name in excluded if name.startswith('Bench')]
            seed = int(digest(json.dumps([self.spec['seed'], humans, len(excluded)-len(humans)]).encode()), 16)
            return original_choose(*a, **(kw | dict(difficulty='normal', randbelow=random.Random(seed).randrange)))
        catalog.choose = choose
        templates = {self.template.game_mode: self.template}
        if self.template.game_mode != 1:
            templates[1] = GameTemplate.load(self.args.assets/'map-1v1.pb.gz', catalog_path=self.args.assets/'unit-catalog.json',
                                             descriptors_path=self.args.assets/'descriptors')
        self.server = ds.DedicatedServer(templates[1], ProfileStore(self.args.output/'profiles', templates[1]),
            templates=templates, bot_catalog=catalog, sim_factory=self.factory, ai_factory=self.factory,
            audit=self.trace.emit, data_dir=self.args.output, audit_state=False,
            tls_context=tls.load_server_context(self.args.tls_cert, self.args.tls_key),
            admission=admission.AdmissionController(None, rc_open=True, burst=32),
            experimental_command_scheduling=True, loading_timeout=180, input_timeout=30)
        self.port = (await self.server.start('127.0.0.1', 0))[1]
        self.client_tls = tls.load_client_context(self.args.tls_ca, 'localhost')

    async def connect(self, name):
        reader, writer = await tls.open_verified_connection('127.0.0.1', self.port, self.client_tls)
        profile = await admission.authenticate_client(reader, writer, benchmark_token(self.spec['seed'], name), rc_open=True)
        peer = Peer(reader, writer, self.trace, name, self.args.rtt_ms, self.args.jitter)
        self.peers.append(peer)
        await peer.send(c.HELLO, c.hello(profile, name))
        await peer.receive(c.WELCOME)
        await peer.send(wire.NEGOTIATE, b'\x02')
        require(await peer.receive(wire.ACK) == b'\x02', 'arrival scheduling capability not negotiated')
        return peer

    async def prepare(self, lane, number):
        began = self.trace.now()
        count = self.template.player_count if not self.args.ai else (2 if self.template.game_mode == 5 else 1)
        peers = [await self.connect(f'Bench{lane} ep{number} seat{index}') for index in range(count)]
        deck = self.spec.get('decks', {}).get('0', list(self.template.default_decks[0]))
        # Retain the full normal human-search deadline for original AI fallback.
        for peer in peers:
            await peer.command(q.ENTER, mode=self.template.game_mode, deck=deck, wait_ms=30000)
        offers = []
        for peer in peers:
            while True:
                state = q.decode_state(await peer.receive(q.STATE))
                if state['phase'] == q.OFFERED:
                    offers.append(state['match'])
                    break
        require(len(set(offers)) == 1, 'intended peers did not share one public offer')
        for peer in peers:
            await peer.command(q.READY, match=offers[0])
        for peer in peers:
            assignment = q.decode_assignment(await peer.receive(q.MATCH))
            peer.match, peer.slot, peer.count = assignment['match'], assignment['slot'], self.template.player_count
            peer.bootstrap = await peer.receive(p.BOOTSTRAP)
        require(len({peer.bootstrap for peer in peers}) == 1, 'peer bootstrap mismatch')
        room = self.server.rooms['public_'+offers[0]]
        room.sim.match = room.match_id
        spec = dict(self.spec, scripted_armies=sorted(room.peers), opponent='ai' if room.bots else 'scripted')
        driver = army.Workload(self.template, room.match, spec, 10000, 100000)
        episode = Episode(lane, number, room, peers, driver, began)
        self.episodes.append(episode)
        self.lane_matches[lane].append(room.match_id)
        self.trace.emit('episode_prepared', lane=lane, episode=number, match=room.match_id,
                        elapsed_ms=self.trace.now()-began, humans=sorted(room.peers), bots={s: b.profile_id for s, b in room.bots.items()},
                        workload=spec, effective_decks={str(s): list(d) for s, d in room.match.decks_by_slot.items()},
                        bootstrap_sha256=digest(room.match.raw_game_data))
        return episode

    async def load(self, episode):
        for peer in episode.peers:
            await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        for peer in episode.peers:
            await peer.receive(p.START)
        bodies, _ = episode.driver.inputs(0)
        await asyncio.gather(*(peer.batch(bodies[peer.slot], intent=dict(phase='join', ordinal=0)) for peer in episode.peers))
        for peer in episode.peers:
            frame, _ = await asyncio.wait_for(peer.frames.get(), 30)
            require(frame == 0, 'initial native JoinArmy frame missing')
        await asyncio.gather(*(peer.send(wire.READY, wire.ready(peer.match)) for peer in episode.peers))

    async def play(self, episode):
        room, driver, peers = episode.room, episode.driver, episode.peers
        frame, last_order, next_heartbeat = -1, None, 0.0
        while (self.target_end is None or self.trace.now() < self.target_end) and room.state == 'running':
            now = self.trace.now()
            require(all(not task.done() for peer in peers for task in peer.tasks), 'peer read/delivery/transmit task stopped early')
            if room.sim is None:
                break
            current = room.sim.last_state
            if current and current['frame'] != frame:
                frame = current['frame']
                driver.entities = {e['id']: e for e in current['entities']}
                driver.hqs.update({e['army']: e for e in current['entities'] if e.get('type') == 3 and 'position' in e})
                observation = room.sim.last_observation
                if episode.active_started is None and active_load(observation, driver.scripted,
                        self.spec['target_units_per_scripted_army'], 1.0):
                    episode.active_started = now
                    self.origins[room.match_id] = now
                    self.trace.emit('active_load_started', lane=episode.lane, episode=episode.number, match=room.match_id,
                                    counts=observation['army_unit_counts'])
                if episode.active_started is not None:
                    loaded = active_load(observation, driver.scripted, self.spec['target_units_per_scripted_army'], self.args.minimum_load_fraction)
                    if loaded:
                        if episode.last_sample is not None:
                            episode.active_seconds += (now-episode.last_sample)/1000
                        episode.depleted_since = None
                    elif episode.depleted_since is None:
                        episode.depleted_since = now
                    episode.last_sample = now
                    if episode.depleted_since is not None and now-episode.depleted_since >= self.args.depletion_seconds*1000:
                        self.trace.emit('active_load_depleted', lane=episode.lane, episode=episode.number, match=room.match_id,
                                        counts=observation['army_unit_counts'])
                        break
                if current['game_state']['complete']:
                    self.trace.emit('observed_natural_result', lane=episode.lane, episode=episode.number,
                                    match=room.match_id, result=current['game_state'])
                    break
            if current:
                phase = self.args.activity if episode.active_started is not None else 'setup'
                order = int((now-episode.active_started)/5000) if episode.active_started is not None else current['frame']
                if order != last_order:
                    driver.phase, driver.phase_frame = phase, order*(100 if phase == 'movement' else 20)
                    bodies, _ = driver.inputs(max(1, current['frame']+1))
                    await asyncio.gather(*(peer.batch(bodies[peer.slot], intent=dict(phase=phase, ordinal=order,
                        due_phase_ms=order*5000 if phase != 'setup' else None, observed_frame=current['frame']))
                        for peer in peers if get_repeated_bytes(bodies[peer.slot], 2)))
                    last_order = order
                if now >= next_heartbeat:
                    await asyncio.gather(*(peer.send(wire.HEARTBEAT, wire.heartbeat(peer.match, peer.applied)) for peer in peers))
                    next_heartbeat = now+250
            for peer in peers:
                while not peer.frames.empty():
                    peer.frames.get_nowait()
            await asyncio.sleep(.05)
        # Finish already accepted work and client delivery; no new commands.
        await asyncio.gather(*(asyncio.wait_for(peer.tx_queue.join(), 10) for peer in peers))
        await asyncio.sleep((self.args.rtt_ms+250)/1000)
        async def committed():
            while True:
                if not self.trace.pending_commands[room.match_id]:
                    return
                await asyncio.sleep(.02)
        await asyncio.wait_for(committed(), 20)
        if room.sim is not None:
            await room.sim.stop_requests()
            await room.finish('bounded benchmark episode teardown', aborted=True)
        last = self.trace.publications.get(room.match_id, -1)
        async def delivered():
            while not all(peer.applied >= last for peer in peers):
                for peer in peers:
                    while not peer.frames.empty():
                        peer.frames.get_nowait()
                await asyncio.sleep(.02)
        await asyncio.wait_for(delivered(), 20)
        for peer in peers:
            await peer.close()
        episode.ended = self.trace.now()
        self.trace.emit('episode_ended', lane=episode.lane, episode=episode.number, match=room.match_id,
                        active_seconds=episode.active_seconds, elapsed_ms=self.trace.now()-episode.started)

    async def lane(self, first):
        episode = first
        for number in range(self.args.max_episodes):
            await self.play(episode)
            if self.target_end is not None and self.trace.now() >= self.target_end:
                return
            require(number+1 < self.args.max_episodes, 'episode budget exhausted before measurement duration')
            episode = await self.prepare(first.lane, number+1)
            await self.load(episode)

    async def start_measurement(self):
        while self.measurement_start is None:
            latest = {episode.lane: episode for episode in self.episodes}
            if len(latest) == self.args.matches and all(e.active_started is not None and e.room.state == 'running'
                and e.room.sim is not None and active_load(e.room.sim.last_observation, e.driver.scripted,
                self.spec['target_units_per_scripted_army'], 1.0) for e in latest.values()):
                self.measurement_start = self.trace.now()
                self.target_end = self.measurement_start+self.args.duration_seconds*1000
                self.trace.emit('measurement_started', end_ms=self.target_end, matches=self.args.matches)
                return
            await asyncio.sleep(.05)

    async def close(self):
        failures = []
        if self.server:
            failures.extend(await asyncio.gather(self.server.close(), return_exceptions=True))
        failures.extend(await asyncio.gather(*(peer.close() for peer in self.peers), return_exceptions=True))
        failures.extend(await asyncio.gather(*(worker.close() for worker in self.workers), return_exceptions=True))
        require(not any(isinstance(result, BaseException) for result in failures), 'owned coordinator cleanup failed')


def source_hashes():
    return army.source_hashes() | {'tools/benchmark_hybrid_coordinator.py': digest(Path(__file__).read_bytes())}


def compare_runs(report, rows, previous):
    """Pair evidence only; one pair cannot replace the required alternating repeats."""
    prior = json.loads((previous/'benchmark.json').read_text(encoding='utf-8'))
    event_file = previous/'events.jsonl'
    require(event_file.stat().st_size <= 512*1024*1024, 'paired trace exceeds bounded size')
    require(file_digest(event_file) == prior['events_sha256'], 'paired trace digest differs')
    other = EventRows(event_file)
    require(prior.get('passed') and prior.get('native_qualified') and prior.get('source_unchanged'),
            'paired run must be complete, source-bound and native')
    contract = ('asset_manifest_sha256', 'source_bootstrap_sha256', 'source_journal_report_sha256',
                'source_at_start', 'duration_seconds', 'matches', 'rtt_ms', 'jitter_trace_ms', 'activity', 'ai')
    require(all(name in report and name in prior for name in contract), 'paired measurement contract missing fields')
    mismatches = [name for name in contract if report.get(name) != prior.get(name)]
    def indexes(events):
        episodes, bootstrap = {}, {}
        for row in (r for r in events if r['event'] == 'episode_prepared'):
            identity = row['lane'], row['episode']
            require(row['match'] not in episodes and identity not in bootstrap, 'paired episode identity is duplicated')
            episodes[row['match']] = identity
            bootstrap[identity] = row['bootstrap_sha256']
        intents, frames, applied = {}, {}, {}
        for row in events:
            if row['event'] not in ('client_command_created', 'worker_frame', 'command_batch_committed'):
                continue
            require(row['match'] in episodes, 'paired event has unknown episode')
            identity = episodes[row['match']]
            if row['event'] == 'worker_frame':
                key = (*identity, row['frame'])
                require(key not in frames, 'paired worker frame duplicated')
                frames[key] = (row['input_sha256'], row['state_sha256'])
            else:
                key = (*identity, row['slot'], row['sequence'])
                target = intents if row['event'] == 'client_command_created' else applied
                require(key not in target, 'paired command sequence duplicated')
                target[key] = (row['body_sha256'], row.get('intent')) if target is intents else row['frame']
        return bootstrap, intents, applied, frames
    left, right = indexes(rows), indexes(other)
    differences = {}
    for name, current, old in zip(('bootstrap', 'intent_sequence', 'applied_command_frames', 'input_and_observable_state'), left, right):
        keys = sorted(current.keys() | old.keys())
        changed = [key for key in keys if current.get(key) != old.get(key)]
        differences[name] = dict(equal=not changed, differences=len(changed), first_differences=[list(k) for k in changed[:20]],
                                 current_count=len(current), prior_count=len(old))
    return dict(previous_report_sha256=digest((previous/'benchmark.json').read_bytes()), contract_mismatches=mismatches,
                differences=differences, exact_pair=not mismatches and all(v['equal'] for v in differences.values()),
                scope='Live arrival may change applied frames; differences remain visible. Exact observable state is not an opaque native world checksum. Three alternating pairs and P4 assessment remain separate.')


async def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    trace = Trace(args.output)
    report = dict(passed=False, native_qualified=False, scope=__doc__, clock=trace.clock,
                  source_at_start=source_hashes(), duration_seconds=args.duration_seconds, matches=args.matches,
                  rtt_ms=args.rtt_ms, jitter_trace_ms=args.jitter, activity=args.activity, ai=args.ai,
                  synthetic=False, profiling=False)
    experiment = None
    sampler, sampler_task = ResourceSampler(args, trace), None
    started = time.perf_counter()
    try:
        verify_assets(args.assets)
        baseline = json.loads((args.journal/'benchmark.json').read_text(encoding='utf-8'))
        require(baseline['passed'] and baseline['native_qualified'], 'a completed original large-army bootstrap is required')
        require(baseline['asset_manifest_sha256'] == digest((args.assets/'asset-manifest.json').read_bytes()), 'asset inventory differs')
        raw = gzip.decompress((args.journal/'bootstrap.pb.gz').read_bytes())
        require(digest(raw) == baseline['bootstrap_sha256'], 'recorded bootstrap hash differs')
        template = FixedTemplate(raw, catalog_path=args.assets/'unit-catalog.json', descriptors_path=args.assets/'descriptors')
        template.benchmark_seed = baseline['workload']['seed']
        require(template.game_mode in (1, 2, 5) and (template.game_mode != 5 or args.ai),
                'public2vAI requires --ai; only public modes1/2/5 are supported')
        spec = baseline['workload']
        if 'decks' not in spec:
            spec = dict(spec, decks={str(s): list(template.template_decks[s]) for s in template.armies})
        backend = army.select_backend(args)
        report.update(backend=army.backend_identity(backend), source_workload=spec,
                      workload_scope='source bootstrap resource staging retained for all armies; actual human/AI rosters and decks are recorded per episode',
                      coordinator=dict(python=sys.version, platform=platform.platform(), machine=platform.machine(), logical_cpus=os.cpu_count()),
                      asset_manifest_sha256=baseline['asset_manifest_sha256'],
                      source_journal_report_sha256=digest((args.journal/'benchmark.json').read_bytes()),
                      source_journal_sha256=baseline['input_journal_sha256'],
                      source_bootstrap_sha256=baseline['bootstrap_sha256'])
        experiment = Experiment(args, trace, template, spec, backend)
        async with asyncio.timeout(args.timeout_seconds):
            sampler_task = asyncio.create_task(sampler.run())
            await experiment.start()
            first = [await experiment.prepare(lane, 0) for lane in range(args.matches)]
            await asyncio.gather(*(experiment.load(episode) for episode in first))
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(experiment.start_measurement())
                for episode in first: tasks.create_task(experiment.lane(episode))
            require(not trace.unexpected_events, 'unexpected coordinator protocol failure/abort')
        report.update(passed=True, native_qualified=True)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        sampler.stopped = True
        if sampler_task:
            sampler_task.cancel()
            outcomes = await asyncio.gather(sampler_task, return_exceptions=True)
            for outcome in outcomes:
                if isinstance(outcome, BaseException) and not isinstance(outcome, asyncio.CancelledError):
                    report.update(passed=False, resource_error=repr(outcome))
        if experiment:
            try:
                await experiment.close()
            except BaseException as error:
                report.update(passed=False, cleanup_error=repr(error))
        try:
            trace.close()
        except (ValueError, OSError) as error:
            report.update(passed=False, trace_error=repr(error))
            trace.rows = ()  # Partial raw spool is retained; never analyze it as complete evidence.
        report['resources'] = sampler.report()
        if experiment:
            report['worker_startups'] = experiment.startups
            report['workers'] = [dict(pid=w.pid, native_pid=w.native_pid, exit_code=w.process.poll(), failure=w.failure,
                                      backend_statistics=w.backend_statistics,
                                      threads_closed=not w._stderr_thread.is_alive() and all(not t.is_alive() for t in w._io._threads))
                                 for w in experiment.workers]
            clean = bool(experiment.workers) and all(w['exit_code'] == 0 and w['failure'] is None and w['threads_closed'] and
                    (experiment.backend is None or army.backend_cleanup_complete(w['backend_statistics'])) for w in report['workers'])
            report['passed'] &= clean
            intervals = {lane: [] for lane in range(args.matches)}
            for episode in experiment.episodes:
                ranges = active_intervals(trace.rows, episode, experiment.measurement_start or trace.now(),
                    experiment.target_end or trace.now(), experiment.spec['target_units_per_scripted_army'], args.minimum_load_fraction)
                episode.active_seconds = sum(end-start for start, end in ranges)/1000
                intervals[episode.lane].extend(ranges)
            report['episodes'] = [dict(lane=e.lane, number=e.number, match=e.room.match_id, active_seconds=e.active_seconds,
                active_started_ms=e.active_started, started_ms=e.started, ended_ms=e.ended if math.isfinite(e.ended) else None)
                for e in experiment.episodes]
            report['active_seconds_by_lane'] = {str(lane): sum(end-start for start, end in values)/1000 for lane, values in intervals.items()}
            report['concurrent_active_seconds'] = overlap_seconds(intervals)
            report['load_duration_scope'] = 'scripted HUMAN army population only; AI army populations retained separately and need not be at cap; motion fractions reported separately; setup/depletion gaps receive no credit'
            report['simultaneous_motion_seconds'] = {}
            for label, fraction in (('any_per_scripted_army', 0), ('half_per_scripted_army', .5)):
                moving = {lane: [] for lane in range(args.matches)}
                for episode in experiment.episodes:
                    moving[episode.lane].extend(active_intervals(trace.rows, episode,
                        experiment.measurement_start or trace.now(), experiment.target_end or trace.now(),
                        experiment.spec['target_units_per_scripted_army'], args.minimum_load_fraction, fraction))
                report['simultaneous_motion_seconds'][label] = overlap_seconds(moving)
            report['measurement_start_ms'] = experiment.measurement_start
            try:
                report['measurements'] = measurements(trace.rows, experiment.origins, experiment.lane_matches,
                                                      experiment.measurement_start, experiment.target_end)
                report['passed'] &= not report['measurements']['unmatched_committed_commands']
            except (ValueError, KeyError, TypeError) as error:
                report.update(passed=False, measurement_error=repr(error), measurements=dict(publication={}))
            measured = [r for r in trace.rows if r['event'] == 'worker_frame' and experiment.measurement_start is not None
                        and experiment.measurement_start <= r['at_ms'] <= experiment.target_end]
            report['load_samples'] = {str(slot): dict(
                population=count_summary([r['army_unit_counts'][str(slot)] for r in measured]),
                moving_units=count_summary([r['moving_units'][str(slot)] for r in measured]),
                frames_with_damage=sum(r['newly_damaged_units'][str(slot)] > 0 for r in measured))
                for slot in range(experiment.template.player_count)}
            report['scripted_army_activity'] = []
            for episode in experiment.episodes:
                samples = [r for r in measured if r['match'] == episode.room.match_id]
                for slot in episode.driver.scripted:
                    motion = sum(r['moving_units'][str(slot)] > 0 for r in samples)
                    damage = sum(r['newly_damaged_units'][str(slot)] > 0 or
                                 r['newly_lost_unit_resource_cost'][str(slot)] > 0 for r in samples)
                    report['scripted_army_activity'].append(dict(lane=episode.lane, episode=episode.number, slot=slot,
                        frames=len(samples), moving_frames=motion, damage_or_loss_frames=damage,
                        observed=(motion > 0 if args.activity == 'movement' else damage > 0)))
            report['workload_qualified'] = bool(report['scripted_army_activity']) and all(
                row['observed'] for row in report['scripted_army_activity'])
            report['activity_scope'] = 'at least one observed activity frame per scripted HUMAN army; sustained movement duration is reported separately, not inferred from this gate'
            del measured
            report['acceptance'] = dict(duration=report['concurrent_active_seconds']+1e-6 >= 300,
                activity_observed=report['workload_qualified'],
                continuous_cadence=bool(report['measurements']['publication']) and all(v['cadence_pass'] for v in report['measurements']['publication'].values()),
                resource_qualification=report['resources']['complete'], repeated_paired_runs=False, perceived_latency=False)
        report.update(elapsed_seconds=time.perf_counter()-started, source_at_finish=source_hashes())
        report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
        report['passed'] &= report['source_unchanged']
        report['native_qualified'] &= report['passed']
        report['performance_qualified'] = False  # Full alternating matrix/P4 and remaining acceptance evidence are separate.
        if args.compare is not None:
            try:
                report['pair_audit'] = compare_runs(report, trace.rows, args.compare)
            except (ValueError, KeyError, TypeError, OSError) as error:
                report.update(passed=False, native_qualified=False, pair_audit_error=repr(error))
        report['diagnostic_trace'] = trace.report()
        report['events_sha256'] = file_digest(args.output/'events.jsonl')
        (args.output/'benchmark.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'elapsed_seconds', 'error', 'acceptance') if k in report}))
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'output', 'journal', 'tls-cert', 'tls-key', 'tls-ca'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--matches', type=int, choices=(1, 2), default=1)
    parser.add_argument('--duration-seconds', type=float, default=300)
    parser.add_argument('--timeout-seconds', type=float, default=900)
    parser.add_argument('--rtt-ms', type=int, choices=(0, 130, 475), default=0)
    parser.add_argument('--jitter-ms', default='0', help='fixed comma-separated one-way offsets, repeated permessage')
    parser.add_argument('--activity', choices=('movement', 'combat'), default='movement')
    parser.add_argument('--ai', action='store_true')
    parser.add_argument('--snapshot-decoder-library', type=Path, help='explicit experimental Windows Rust DLL')
    parser.add_argument('--snapshot-decoder-sha256', help='required exact experimental DLL identity')
    parser.add_argument('--compare', type=Path, help='completed prior coordinator run; exact input/state pairing is audited, never assumed')
    parser.add_argument('--max-episodes', type=int, default=3)
    parser.add_argument('--depletion-seconds', type=float, default=5)
    parser.add_argument('--minimum-load-fraction', type=float, default=.8)
    parser.add_argument('--proc-root', type=Path, help='/proc on Linux; explicit Z:/proc for full-Wine counters')
    parser.add_argument('--resource-cgroup', type=Path, help='isolated experiment cgroup; never the whole host hierarchy')
    parser.add_argument('--linux-clock-ticks', type=int, help='Linux getconf CLK_TCK value for retained task counters')
    for name in ('wine-executable', 'windows-python', 'wine-prefix-template', 'wine-cgroup-parent'):
        parser.add_argument('--'+name, type=Path)
    args = parser.parse_args(argv)
    args.profile_worker = False
    args.jitter = [float(value) for value in args.jitter_ms.split(',')]
    for name in ('assets', 'output', 'journal', 'tls_cert', 'tls_key', 'tls_ca'):
        setattr(args, name, getattr(args, name).resolve())
    if args.compare:
        args.compare = args.compare.resolve()
        require(args.compare.is_dir() and not args.output.is_relative_to(args.compare), 'paired report and new output must be separate')
    hybrid = army.wine_requested(args)
    require(sys.platform.startswith('linux') if hybrid else os.name == 'nt', 'explicit supported worker backend required')
    require(args.output.is_relative_to(ROOT/'local') and not args.output.exists(), 'new ignored output required')
    require(not args.output.is_relative_to(args.assets) and not args.output.is_relative_to(args.journal), 'output must be separate')
    require(5 <= args.duration_seconds <= 600 and 30 <= args.timeout_seconds <= 3600, 'bounded duration required')
    require(1 <= args.max_episodes <= 6 and .5 <= args.minimum_load_fraction <= 1 and 1 <= args.depletion_seconds <= 30,
            'invalid load/episode bounds')
    resources = (args.proc_root, args.resource_cgroup, args.linux_clock_ticks)
    require(not any(value is not None for value in resources) or all(value is not None for value in resources),
            'proc root, isolated resource cgroup and Linux clock ticks must be supplied together')
    if args.proc_root:
        args.proc_root, args.resource_cgroup = args.proc_root.resolve(), args.resource_cgroup.resolve()
        require(args.proc_root.is_dir() and (args.resource_cgroup/'cgroup.procs').is_file() and
                (args.resource_cgroup/'memory.current').is_file() and 1 <= args.linux_clock_ticks <= 10000,
                'invalid isolated Linux resource counter paths')
    Delivery(args.rtt_ms, args.jitter, None, '', '')
    return args


def main():
    return asyncio.run(run(arguments()))


if __name__ == '__main__':
    raise SystemExit(main())
