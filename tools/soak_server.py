"""Opt-in Windows multi-room soak with persistent community TCP peers.

Run with locally imported assets. Evidence is bounded and local. Scripted native
worlds do not establish graphical-client, internet or Windows service health.
Explicit --rc-tls adds original RC admission with an owned ordinary TLS fixture;
it does not qualify protected owner storage or optional verified/invite mode.
This file can run through the pinned package Python without importing a checkout.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import secrets
import struct
import sys
import threading
import time
import traceback

from server import community_protocol as c, protocol as p
from server import dedicated_server, worker_client, simulation_worker, native_simulation
# Anchor these real server dependencies before the initial source manifest;
# current server construction/secure listener setup imports them lazily.
from server import profile_io,public_matchmaking,tls_listener
from server.assets import verify_assets
from server.game_data import GameTemplate, encode_frame, encode_player_input, decompress_game_data
from server.host_audit import HostAudit
from server.profiles import ProfileStore
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_uint, parse_fields
from server.state_lock import exclusive_state
from server.worker_client import SimulationWorker

ROOT = Path(__file__).resolve().parents[1]


def require(value, message):
    if not value: raise AssertionError(message)


def utc(): return datetime.now(timezone.utc).isoformat()
def digest(data): return hashlib.sha256(data).hexdigest()
def record(data): return struct.pack('<I', len(data)) + data


def assess(report, *, seconds, rooms, minimum_rounds):
    cadence, work = report['timings']['publish_interval_ms'],report['timings']['worker_ms']
    baseline, final = report['baseline_idle'],report['final_idle']
    concurrent = report['concurrent_room_seconds']
    # Keys are integers in memory and strings after JSON roundtrip.
    coverage = concurrent.get(rooms,concurrent.get(str(rooms),0))
    return dict(all_workers_reaped=report['all_workers_reaped'],source_unchanged=report['source_unchanged'],
        assets_unchanged=report['asset_manifest_sha256'] == report['asset_manifest_sha256_at_finish'],
        duration_met=report['elapsed_seconds'] >= seconds,
        rematches_met=report['rounds'] >= minimum_rounds,
        expected_matches=report['matches'] == report['rounds']*rooms,
        expected_worker_lives=report['created_workers'] == report['matches']*3,
        persistent_connections=report['connections_created'] == rooms*2,
        multiple_rooms_active=coverage >= seconds*.9,
        cadence=cadence['count'] > 0 and cadence['mean_ms'] <= 1000/19.5,
        publication_gap=cadence['max_ms'] <= 1000,
        worker_budget=work['count'] > 0 and work['over50ms'] <= work['count']*.01,
        handles_bounded=baseline is not None and final is not None and final['handles'] <= baseline['handles']+16,
        private_growth_bounded=baseline is not None and final is not None and final['private_bytes'] <= baseline['private_bytes']+64*1024*1024)


def write_json(path, value):
    # Only fixed owned status filenames are replaced; no recursive cleanup.
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


class Distribution:
    """Fixed-size1ms histogram; quantiles are bin upper bounds, never samples."""
    def __init__(self):
        self.bins = [0]*5002
        self.count = 0
        self.total = self.maximum = 0.0
        self.over50 = 0

    def add(self, value):
        require(math.isfinite(value) and value >= 0, 'Invalid timing observation')
        self.bins[min(5001, math.ceil(value))] += 1
        self.count += 1; self.total += value; self.maximum = max(self.maximum, value)
        self.over50 += value > 50

    def summary(self):
        def quantile(fraction):
            target = max(1, math.ceil(self.count*fraction)); seen = 0
            for index, count in enumerate(self.bins):
                seen += count
                if seen >= target: return index if index < 5001 else '>5000'
            return None
        return dict(count=self.count, mean_ms=self.total/self.count if self.count else None,
                    max_ms=self.maximum, p95_ms_upper=quantile(.95), p99_ms_upper=quantile(.99), over50ms=self.over50)


class EvidenceWrites:
    """One awaited disk operation at a time, outside the measured event loop."""
    def __init__(self):
        self.lock = asyncio.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='soak-evidence')
        self.io_ms, self.wait_ms = Distribution(), Distribution()
        self.active = None
        self.slowest = []

    async def call(self, name, operation, *args):
        queued = time.perf_counter()
        async with self.lock:
            self.wait_ms.add((time.perf_counter()-queued)*1000)
            timing = dict(operation=name, started=time.perf_counter())
            self.active = timing
            def perform():
                started = time.perf_counter()
                try: return operation(*args)
                finally:
                    timing['finished'] = time.perf_counter()
                    timing['io_ms'] = (timing['finished']-started)*1000
            pending = asyncio.get_running_loop().run_in_executor(self.executor,perform)
            cancelled = None
            try:
                while True:
                    try:
                        result = await asyncio.shield(pending)
                        break
                    except asyncio.CancelledError as error:
                        # A running fsync cannot be cancelled. Retain the lock and
                        # drain it before any later status write or stream close.
                        if pending.cancelled(): raise
                        cancelled = error
            finally:
                if 'io_ms' in timing:
                    self.io_ms.add(timing['io_ms'])
                    self.slowest.append(dict(timing))
                    self.slowest.sort(key=lambda value:value['io_ms'],reverse=True)
                    del self.slowest[8:]
                self.active = None
            if cancelled is not None: raise cancelled
            return result

    def summary(self):
        return dict(io_ms=self.io_ms.summary(), wait_ms=self.wait_ms.summary(),
                    slowest=[dict(value) for value in self.slowest])

    def close(self):
        require(not self.lock.locked(), 'Evidence writer closed before pending write drained')
        self.executor.shutdown(wait=True)


class ProcessSampler:
    """Read only owned PIDs. No process enumeration, debug privilege or WMI."""
    def __init__(self):
        if os.name != 'nt': raise ValueError('Native soak requires Windows')
        dword, size = C.c_uint32, C.c_size_t
        class Memory(C.Structure):
            _fields_ = [('cb', dword), ('faults', dword)] + [(name, size) for name in
                ('peak_working', 'working', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
        self.Memory = Memory
        self.kernel = k = C.WinDLL('kernel32', use_last_error=True)
        self.psapi = a = C.WinDLL('psapi', use_last_error=True)
        k.OpenProcess.argtypes = [dword, C.c_int, dword]; k.OpenProcess.restype = C.c_void_p
        k.CloseHandle.argtypes = [C.c_void_p]; k.CloseHandle.restype = C.c_int
        k.GetProcessHandleCount.argtypes = [C.c_void_p, C.POINTER(dword)]; k.GetProcessHandleCount.restype = C.c_int
        k.GetProcessTimes.argtypes = [C.c_void_p] + [C.POINTER(C.c_uint64)]*4; k.GetProcessTimes.restype = C.c_int
        a.GetProcessMemoryInfo.argtypes = [C.c_void_p, C.POINTER(Memory), dword]; a.GetProcessMemoryInfo.restype = C.c_int

    def sample(self, pid):
        handle = self.kernel.OpenProcess(0x410, False, pid)  # QUERY_INFORMATION | VM_READ.
        if not handle: raise OSError('Cannot inspect owned process resources')
        try:
            memory = self.Memory(); memory.cb = C.sizeof(memory)
            handles = C.c_uint32()
            times = [C.c_uint64() for _ in range(4)]
            if not self.psapi.GetProcessMemoryInfo(handle, C.byref(memory), memory.cb): raise OSError('Memory sample failed')
            if not self.kernel.GetProcessHandleCount(handle, C.byref(handles)): raise OSError('Handle sample failed')
            if not self.kernel.GetProcessTimes(handle, *(C.byref(value) for value in times)): raise OSError('CPU sample failed')
            return dict(pid=pid, created_filetime=times[0].value, private_bytes=memory.private,
                        working_set_bytes=memory.working, handles=handles.value,
                        cpu_seconds=(times[2].value+times[3].value)/10000000)
        finally: self.kernel.CloseHandle(handle)


class Peer:
    def __init__(self, reader, writer, profile):
        self.reader, self.writer, self.profile = reader, writer, profile
        self.request = 0
        self.queue = asyncio.Queue(64)
        self.lobby = None
        self.frames = 0
        self.journal = hashlib.sha256()
        self.last_frames = deque(maxlen=8)
        self.pump = asyncio.create_task(self.read_loop())

    async def read_loop(self):
        try:
            while True:
                kind, payload = await p.receive(self.reader)
                if kind == c.DIRECTORY: continue
                if kind == c.LOBBY:
                    self.lobby = payload  # Latest-only; command checks use ACKs.
                    continue
                if kind == c.INVITATION or kind == p.MATCH_INFO or kind == p.LOBBY: continue
                if kind == p.WELCOME:
                    self.frames = 0; self.journal = hashlib.sha256(); self.last_frames.clear()
                if kind == p.FRAME:
                    number, first_size = struct.unpack_from('<II', payload)
                    require(number == self.frames and first_size <= len(payload)-8, 'Noncontiguous received frame')
                    self.journal.update(record(encode_frame(number, {0:payload[8:8+first_size], 1:payload[8+first_size:]})))
                    self.frames += 1; self.last_frames.append(dict(frame=number, sha256=digest(payload)))
                require(not self.queue.full(), 'Soak peer queue exceeded its bound')
                self.queue.put_nowait((kind, payload))
        except asyncio.CancelledError: raise
        except BaseException as error:
            if not self.queue.full(): self.queue.put_nowait((None, type(error).__name__.encode()))
            raise

    async def send(self, kind, payload=b''):
        self.writer.write(p.encode(kind, payload))
        await asyncio.wait_for(self.writer.drain(), 5)

    async def receive(self, expected):
        async with asyncio.timeout(30):
            while True:
                kind, payload = await self.queue.get()
                if kind == expected: return payload
                require(kind not in (None, p.ERROR, c.ABORTED), 'Peer failed or match aborted')

    async def command(self, kind, body=b''):
        self.request += 1
        await self.send(kind, struct.pack('<I', self.request)+body)
        r = c.Reader(await self.receive(c.ACK))
        require((r.number('I'),r.number('B')) == (self.request,kind), 'Wrong command acknowledgement')
        accepted, reason, identity = r.flag(), r.text(), r.text(); r.end()
        require(accepted, 'Soak command rejected: '+reason)
        return identity

    async def close(self):
        self.writer.close()
        try: await asyncio.wait_for(self.writer.wait_closed(), 2)
        except (OSError, TimeoutError): pass
        if not self.pump.done(): self.pump.cancel()
        await asyncio.gather(self.pump, return_exceptions=True)


class ObservedWorker:
    def __init__(self, worker):
        self.worker = worker
        self.journal = hashlib.sha256()
        self.frames = 0
    def __getattr__(self, name): return getattr(self.worker, name)
    async def process_frame(self, actions, **kwargs):
        result = await self.worker.process_frame(actions, **kwargs)
        self.journal.update(record(actions)); self.frames += 1
        return result


class Soak:
    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        require(self.output.is_relative_to((ROOT/'local').resolve()), 'Evidence must stay under the runner local directory')
        self.output.mkdir(parents=True, exist_ok=False)
        self.workdir = self.output/'workers'; self.workdir.mkdir()
        self.assets = verify_assets(args.assets)
        self.template = GameTemplate.load(args.assets/'map-1v1.pb.gz', catalog_path=args.assets/'unit-catalog.json',
                                          descriptors_path=args.assets/'descriptors')
        self.audit = HostAudit(self.output/'logs', max_bytes=1024*1024, backups=2)
        self.samples = (self.output/'samples.jsonl').open('x', encoding='utf-8', buffering=1)
        self.matches = (self.output/'matches.jsonl').open('x', encoding='utf-8', buffering=1)
        self.evidence = EvidenceWrites()
        self.diagnostics = {key:Distribution() for key in ('snapshot_ms','loop_delay_ms','audit_ms')}
        self.worst_gaps = []
        self.sampler = ProcessSampler()
        self.peers, self.active_workers = [], set()
        self.created = self.reaped = self.finished = self.rounds = 0
        self.started = time.monotonic()
        self.active_started = self.started
        self.running_rooms = set()
        self.concurrent_seconds = Counter()
        self.events = Counter()
        self.timings = {key:Distribution() for key in ('publish_interval_ms','interval_ms','worker_ms','input_wait_ms','tick_late_ms','frame_work_ms')}
        self.last_published = {}
        self.baseline = self.final_idle = None
        self.server = None
        self.tls_context = None
        self.cosmetic_catalog = None
        if getattr(args,'rc_tls',False):
            from server import rc_host,tls_transport
            from server.cosmetics import CosmeticCatalog
            certificate,key=rc_host.generate_certificate()
            (self.output/'server.pem').write_bytes(certificate)
            (self.output/'server.key').write_bytes(key)
            self.tls_context=tls_transport.load_server_context(self.output/'server.pem',self.output/'server.key')
            self.cosmetic_catalog=CosmeticCatalog(args.assets)
        self.report = dict(schema=1, passed=False, state='starting', pid=os.getpid(), utc=utc(),
            scope='scripted persistent community peers with native replay worlds; no graphical/internet/SCM/protected-owner acceptance',
            transport='rc-tls' if self.tls_context else 'loopback-development',authentication=[],
            requested_seconds=args.seconds, rooms=args.rooms, match_frames=args.match_frames, minimum_rounds=args.minimum_rounds,
            python=sys.version, platform=platform.platform(), cpu_count=os.cpu_count(), tick_ms=50,
            source_sha256=self.source_hashes(), asset_manifest_sha256=digest((args.assets/'asset-manifest.json').read_bytes()))
        self.decks = self.choose_decks()

    @staticmethod
    def source_hashes():
        modules = [sys.modules[name] for name in sys.modules if name.startswith('server.')]
        paths = {Path(module.__file__).resolve() for module in modules if getattr(module, '__file__', None)}
        paths.add(Path(__file__).resolve())
        return {str(path):digest(path.read_bytes()) for path in sorted(paths)}

    def choose_decks(self):
        base = self.template.default_decks[0]
        for candidate in sorted(self.template.allowed_entity_ids):
            if candidate in base: continue
            try: other = self.template.validate_deck([candidate,*base[1:]])
            except ValueError: continue
            # Both basic selections must support the documented Attack88 order.
            if 88 in self.template.entity_abilities[candidate] and 88 in self.template.entity_abilities[base[0]]:
                return [base,other]
        raise ValueError('No two distinct supported basic-unit decks for the soak workload')

    def event(self, event, **fields):
        self.events[event] += 1
        if event in ('match_started','match_completed','match_aborted'):
            now = time.monotonic()
            self.concurrent_seconds[len(self.running_rooms)] += now-self.active_started
            self.active_started = now
            if event == 'match_started': self.running_rooms.add(fields['match'])
            else:
                self.running_rooms.discard(fields['match'])
                self.last_published.pop(fields['match'],None)
        if event == 'frame_queued':
            now = time.perf_counter()
            previous = self.last_published.get(fields['match'])
            if previous is not None:
                gap = (now-previous)*1000
                self.timings['publish_interval_ms'].add(gap)
                if gap > 100:
                    self.worst_gaps.append(dict(elapsed_seconds=time.monotonic()-self.started,
                        match=fields['match'],frame=fields['frame'],gap_ms=gap,perf_counter=now,
                        worker_ms=fields.get('worker_ms'),
                        evidence_operation=self.evidence.active['operation'] if self.evidence.active else None))
                    self.worst_gaps.sort(key=lambda value:value['gap_ms'],reverse=True)
                    del self.worst_gaps[8:]
            self.last_published[fields['match']] = now
            for key, distribution in self.timings.items():
                if key == 'publish_interval_ms': continue
                if key != 'interval_ms' or fields['frame'] > 0: distribution.add(fields[key])
        if event not in HostAudit.HIGH_FREQUENCY:
            started = time.perf_counter()
            try: self.audit(event, **fields)
            finally: self.diagnostics['audit_ms'].add((time.perf_counter()-started)*1000)

    async def factory(self, data):
        worker = ObservedWorker(await SimulationWorker.create(data, self.args.assets/'Simulation.dll', working_directory=self.workdir))
        self.created += 1; self.active_workers.add(worker)
        return worker

    async def connect(self, profile):
        display_name='Soak '+profile
        if self.tls_context:
            from server import admission,tls_transport
            reader,writer=await tls_transport.open_verified_connection('127.0.0.1',self.address[1],tls_transport.rc_client_context('127.0.0.1'))
            try:
                token='ba1_'+secrets.token_urlsafe(32)
                profile=await admission.authenticate_client(reader,writer,token,rc_open=True)
                require(profile==admission.rc_player_id(token),'RC authenticated profile differs')
                self.report['authentication'].append(dict(profile=profile,tls_version=writer.get_extra_info('ssl_object').version(),certificate_verified=False,authenticated=True))
            except BaseException:
                writer.close()
                try:await asyncio.wait_for(writer.wait_closed(),2)
                except (OSError,TimeoutError):writer.transport.abort()
                raise
        else:reader, writer = await asyncio.open_connection(*self.address[:2])
        peer = Peer(reader, writer, profile); self.peers.append(peer)
        await peer.send(c.HELLO, c.hello(profile,display_name))
        r = c.Reader(await peer.receive(c.WELCOME))
        require((r.number('H'),r.number('H'),r.key()) == (c.VERSION,p.VERSION,profile), 'Community identity mismatch')
        r.deck(); r.end()
        return peer

    async def pair(self, number):
        peers = [await self.connect(f'soak_{number}_{slot}') for slot in (0,1)]
        lobby = await peers[0].command(c.CREATE,b'\x01')
        invitation = await peers[0].command(c.INVITE,p.encode_string(peers[1].profile))
        require(await peers[1].command(c.REPLY,p.encode_string(invitation)+b'\x01') == lobby, 'Wrong invitation target')
        return lobby, peers

    @staticmethod
    def execute(entity_type, ability, ids, command):
        group = field_uint(1,entity_type)+field_uint(2,ability)+field_packed_uint(3,ids)
        return field_bytes(1,field_bytes(1,group)+field_bytes(3,command))

    def inputs(self, room, frame, combat):
        bodies = []
        entities = room.sim.last_state['entities'] if room.sim.last_state else []
        playing = room.result is None
        for slot in (0,1):
            actions = []
            owned = [entity for entity in entities if entity.get('army') == slot and 'type' in entity]
            if frame == 0:
                join = field_uint(1,slot)+field_bytes(2,room.match.deck_messages_by_slot[slot])
                for target, source in ((3,5),(4,6)):
                    value = get_uint(room.match.armies_by_slot[slot],source)
                    if value: join += field_uint(target,value)
                actions.append(field_bytes(3,join))
            if playing and 140 <= frame < self.args.match_frames-20 and frame % 40 == 20:
                builders = [(e['id'],e['type'],ability) for e in owned for ability in self.template.entity_abilities[e['type']]
                            if self.template.build_ability_slots.get(ability) == 0]
                require(builders, 'No selected-deck basic unit builder')
                entity, entity_type, ability = min(builders)
                actions.append(self.execute(entity_type,ability,[entity],field_bytes(1,b'')))
                combat['build_commands'][slot] += 1
            units = [e for e in owned if e['type'] == room.match.decks_by_slot[slot][0]]
            combat['produced'][slot].update(e['id'] for e in units)
            combat['peak_units'][slot] = max(combat['peak_units'][slot],len(units))
            for entity in units:
                position = entity.get('position')
                if position:
                    before = combat['positions'][slot].get(entity['id'])
                    if before is not None and position != before: combat['moved'][slot].add(entity['id'])
                    combat['positions'][slot][entity['id']] = position
                if entity.get('current_damage',0): combat['damaged'][slot].add(entity['id'])
            if playing and units and frame % 100 == 50:
                # Use the already documented exact-build Attack88/target-unit
                # command. IDs/ownership/type come from this match's native state.
                enemies = [e for e in entities if e.get('army') == 1-slot and 'type' in e]
                targets = [e for e in enemies if any(self.template.build_ability_slots.get(a) == 0
                    for a in self.template.entity_abilities.get(e['type'],()))]
                if targets:
                    target = min(targets,key=lambda e:e['id'])
                    actions.append(self.execute(units[0]['type'],88,[e['id'] for e in units],field_bytes(2,field_uint(1,target['id']))))
                    combat['attack_commands'][slot] += 1
            if frame == self.args.match_frames and slot == 0 and room.result is None:
                choices = [(e['id'],e['type'],ability) for e in owned for ability in self.template.entity_abilities[e['type']]
                    if any(field.number == 24 for field in parse_fields(self.template.abilities[ability]))]
                require(choices, 'No native self-destruct ability for match completion')
                entity, entity_type, ability = min(choices)
                actions.append(self.execute(entity_type,ability,[entity],field_bytes(1,b'')))
            bodies.append(encode_player_input(room.match.identities_by_slot[slot],actions))
        return bodies

    async def match(self, pair, cycle):
        lobby_id, peers = pair
        lobby = self.server.community.lobbies[lobby_id]
        for slot,peer in enumerate(peers):
            deck = self.decks[(cycle+slot)%2]
            await peer.command(c.SET_DECK,p.deck_bytes(deck))
            require(self.server.profiles.load(peer.profile,[]) == list(deck), 'Deck save/read mismatch')
        await peers[0].command(c.START,p.encode_string(lobby_id)+struct.pack('<Q',lobby.revision))
        await peers[1].command(c.READY,p.encode_string(lobby_id)+struct.pack('<IB',lobby.epoch,1))
        for slot,peer in enumerate(peers):
            assigned,window,deck = p.decode_welcome(await peer.receive(p.WELCOME))
            require(assigned == slot and window == p.DEFAULT_INPUT_WINDOW and deck == list(self.decks[(cycle+slot)%2]), 'Seat/window/deck changed at start')
        bootstrap = await asyncio.gather(*(peer.receive(p.BOOTSTRAP) for peer in peers))
        require(bootstrap[0] == bootstrap[1], 'Peers received different bootstrap data')
        room = lobby.room
        require(bootstrap[0] == room.match.gzip_game_data, 'Public/server bootstrap mismatch')
        worker = room.sim
        references = []
        combat = {key:[set(),set()] for key in ('produced','moved','damaged')}
        combat.update(positions=[{},{}],peak_units=[0,0],build_commands=[0,0],attack_commands=[0,0])
        started = time.monotonic()
        try:
            for _ in peers:
                reference = await SimulationWorker.create(decompress_game_data(bootstrap[0]),self.args.assets/'Simulation.dll',working_directory=self.workdir)
                references.append(reference); self.active_workers.add(reference); self.created += 1
            await asyncio.gather(*(peer.send(p.LOADED,hashlib.sha256(bootstrap[0]).digest()) for peer in peers))
            await asyncio.gather(*(peer.receive(p.START) for peer in peers))
            for frame in range(self.args.match_frames+60):
                bodies = self.inputs(room,frame,combat)
                await asyncio.gather(*(peer.send(p.INPUT,struct.pack('<I',frame)+body) for peer,body in zip(peers,bodies)))
                payloads = await asyncio.gather(*(peer.receive(p.FRAME) for peer in peers))
                require(payloads[0] == payloads[1], 'Peer frame histories diverged')
                number, first_size = struct.unpack_from('<II',payloads[0])
                require(number == frame, 'Public frame number mismatch')
                actions = encode_frame(frame,{0:payloads[0][8:8+first_size],1:payloads[0][8+first_size:]})
                observed = await asyncio.gather(*(reference.process_frame(actions) for reference in references))
                for result in observed:
                    require(result.frame == frame and result.state['canonical_fnv1a64'] == worker.last_state['canonical_fnv1a64'],
                            'Native public-stream replay state mismatch')
                    require(result.state['game_state'] == worker.last_state['game_state'], 'Native result/checksum mismatch')
                if room.result is not None and frame >= room.result_frame+19: break
            results = await asyncio.gather(*(peer.receive(p.MATCH_END) for peer in peers))
            require(results[0] == results[1], 'Peer final results differ')
            result = json.loads(results[0])
            require(result['result'] == worker.last_state['game_state'] and result['result']['complete'], 'Native/public result mismatch')
            require(all(peer.frames == worker.frames and peer.journal.digest() == worker.journal.digest() for peer in peers),
                    'Native ordered input journal differs from received public frames')
            async with asyncio.timeout(10):
                while not worker.closed or worker.process.poll() is None: await asyncio.sleep(.02)
            require(worker.process.poll() == 0, 'Native match worker did not exit cleanly')
            self.reaped += 1; self.active_workers.remove(worker)
            for peer in peers: await peer.command(c.RETURN,p.encode_string(room.match_id))
            require(lobby.phase == c.OPEN and lobby.room is None, 'Custom lobby did not reopen')
            summary = dict(utc=utc(),cycle=cycle,lobby=lobby_id,match=room.match_id,frames=worker.frames,
                bootstrap_sha256=digest(bootstrap[0]),input_journal_sha256=worker.journal.hexdigest(),
                state_comparisons=worker.frames*len(references),worker_pids=[worker.pid,*[r.pid for r in references]],
                result=result['result'],elapsed_seconds=time.monotonic()-started,peak_units=combat['peak_units'],
                build_commands=combat['build_commands'],attack_commands=combat['attack_commands'],
                produced=[len(v) for v in combat['produced']],moved=[len(v) for v in combat['moved']],damaged=[len(v) for v in combat['damaged']])
            require(all(summary['produced']), 'Workload did not produce units for both players')
            if self.args.match_frames >= 400:
                require(all(summary['moved']), 'Workload did not move units for both players')
            self.finished += 1
        finally:
            for reference in references:
                await reference.close()
                require(reference.process.poll() == 0, 'Reference worker did not exit cleanly')
                self.reaped += 1; self.active_workers.discard(reference)
        summary['worker_exit_codes'] = [worker.process.poll(),*[r.process.poll() for r in references]]
        await self.evidence.call('match',self.matches.write,json.dumps(summary,separators=(',',':'))+'\n')

    def status(self):
        now = time.monotonic()
        coverage = dict(self.concurrent_seconds)
        count = len(self.running_rooms)
        coverage[count] = coverage.get(count,0)+now-self.active_started
        return dict(utc=utc(),pid=os.getpid(),state='running',elapsed_seconds=now-self.started,rounds=self.rounds,
            matches=self.finished,created_workers=self.created,reaped_workers=self.reaped,
            concurrent_room_seconds=coverage,active_workers=len(self.active_workers),
            coordinator=self.sampler.sample(os.getpid()),timings={key:value.summary() for key,value in self.timings.items()},
            diagnostics=dict(**{key:value.summary() for key,value in self.diagnostics.items()},
                             evidence=self.evidence.summary()),worst_publication_gaps=list(self.worst_gaps))

    async def loop_probe(self):
        while True:
            started = time.perf_counter()
            await asyncio.sleep(.1)
            self.diagnostics['loop_delay_ms'].add(max(0,(time.perf_counter()-started-.1)*1000))

    def write_sample(self, sample):
        self.samples.write(json.dumps(sample,separators=(',',':'))+'\n')
        write_json(self.output/'progress.json',sample)

    async def heartbeat(self):
        while True:
            started = time.perf_counter()
            sample = self.status()
            sample['workers'] = []
            for worker in tuple(self.active_workers):
                if worker.process.poll() is not None: continue
                try: sample['workers'].append(self.sampler.sample(worker.pid))
                except OSError:
                    if worker.process.poll() is None: raise
            self.diagnostics['snapshot_ms'].add((time.perf_counter()-started)*1000)
            await self.evidence.call('sample',self.write_sample,sample)
            if (self.output/'stop.request').exists(): raise RuntimeError('Owner requested soak stop')
            if self.timings['publish_interval_ms'].maximum > 1000:
                raise RuntimeError('Publication gap exceeded the predeclared 1000ms limit')
            await asyncio.sleep(10)

    async def run(self):
        monitor = batch = probe = None
        try:
            from server.admission import AdmissionController
            self.server = dedicated_server.DedicatedServer(self.template,ProfileStore(self.output/'profiles',self.template,catalog=getattr(self,'cosmetic_catalog',None)),
                sim_factory=self.factory,audit=self.event,data_dir=None,audit_state=False,max_rooms=self.args.rooms,
                tls_context=getattr(self,'tls_context',None),admission=AdmissionController(None,rc_open=True) if getattr(self,'tls_context',None) else None)
            self.address = await self.server.start('127.0.0.1',0)
            self.report['address'] = list(self.address[:2])
            pairs = [await self.pair(index) for index in range(self.args.rooms)]
            monitor = asyncio.create_task(self.heartbeat())
            probe = asyncio.create_task(self.loop_probe())
            while time.monotonic()-self.started < self.args.seconds or self.rounds < self.args.minimum_rounds:
                async def play_round():
                    async with asyncio.TaskGroup() as group:
                        for pair in pairs: group.create_task(self.match(pair,self.rounds))
                batch = asyncio.create_task(play_round())
                done,_ = await asyncio.wait((batch,monitor,probe),return_when=asyncio.FIRST_COMPLETED)
                if monitor in done:
                    batch.cancel(); await asyncio.gather(batch,return_exceptions=True)
                    await monitor
                    raise RuntimeError('Heartbeat stopped unexpectedly')
                if probe in done:
                    await probe
                    raise RuntimeError('Event-loop probe stopped unexpectedly')
                await batch
                self.rounds += 1
                require(not self.active_workers and not self.server.rooms and not self.server.retired, 'Round left active match resources')
                self.final_idle = self.sampler.sample(os.getpid())
                if self.rounds == 3: self.baseline = self.final_idle
                await self.evidence.call('round',write_json,self.output/'progress.json',self.status())
                print(json.dumps(dict(utc=utc(),round=self.rounds,matches=self.finished,elapsed_seconds=time.monotonic()-self.started)),flush=True)
            self.report['passed'] = True
        except BaseException as error:
            self.report.update(error=type(error).__name__+': '+str(error),traceback=traceback.format_exc())
            raise
        finally:
            if batch and not batch.done():
                batch.cancel(); await asyncio.gather(batch,return_exceptions=True)
            for observer in (monitor,probe):
                if observer:
                    observer.cancel()
                    outcome, = await asyncio.gather(observer,return_exceptions=True)
                    if isinstance(outcome,BaseException) and not isinstance(outcome,asyncio.CancelledError):
                        self.report['passed'] = False
                        if 'error' not in self.report:
                            self.report.update(error=type(outcome).__name__+': '+str(outcome),
                                               traceback=''.join(traceback.format_exception(outcome)))
            if self.server: await self.server.close()
            await asyncio.gather(*(peer.close() for peer in self.peers),return_exceptions=True)
            for worker in list(self.active_workers):
                await worker.close()
                if worker.process.poll() is not None: self.reaped += 1
                self.active_workers.discard(worker)
            self.report.update(self.status(),state='finished' if self.report['passed'] else 'failed',
                baseline_idle=self.baseline,final_idle=self.final_idle,event_counts=dict(self.events),
                connections_created=len(self.peers),
                source_sha256_at_finish=self.source_hashes(),
                asset_manifest_sha256_at_finish=digest((self.args.assets/'asset-manifest.json').read_bytes()))
            self.report['all_workers_reaped'] = self.created == self.reaped
            self.report['source_unchanged'] = self.report['source_sha256'] == self.report['source_sha256_at_finish']
            verify_assets(self.args.assets)
            checks = assess(self.report,seconds=self.args.seconds,rooms=self.args.rooms,minimum_rounds=self.args.minimum_rounds)
            self.report['checks'] = checks
            self.report['passed'] = self.report['passed'] and all(checks.values())
            self.report['eight_hour_gate'] = self.report['passed'] and self.args.seconds >= 28800 and self.rounds >= 21
            if not self.report['passed']: self.report['state'] = 'failed'
            try: await self.evidence.call('verification',write_json,self.output/'verification.json',self.report)
            finally:
                self.evidence.close()
                self.samples.close(); self.matches.close(); self.audit.close()


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=28800)
    parser.add_argument('--rooms',type=int,default=2)
    parser.add_argument('--match-frames',type=int,default=3600)
    parser.add_argument('--minimum-rounds',type=int,default=20)
    parser.add_argument('--rc-tls',action='store_true',help='owned ordinary self-signed TLS fixture and original RC admission; no protected owner setup')
    args = parser.parse_args(argv)
    if not 10 <= args.seconds <= 32400 or not 2 <= args.rooms <= 4 or not 200 <= args.match_frames <= 10000 or not 4 <= args.minimum_rounds <= 1000:
        parser.error('seconds10..32400, rooms2..4, match-frames200..10000, minimum-rounds4..1000 required')
    if args.minimum_rounds*(args.match_frames+60)*.05 > 32400:
        parser.error('Minimum rounds exceed the nine-hour simulation workload bound')
    args.assets = args.assets.resolve()
    return args


def main(argv=None):
    args = arguments(argv)
    limit = max(args.seconds,args.minimum_rounds*(args.match_frames+60)*.05) + args.match_frames*.1+180
    timer = threading.Timer(limit+30,lambda:os._exit(2)); timer.daemon=True; timer.start()
    run = Soak(args)
    try:
        with exclusive_state(run.output):
            async def bounded():
                async with asyncio.timeout(limit): await run.run()
            asyncio.run(bounded())
        return 0 if run.report['passed'] else 1
    finally: timer.cancel()


if __name__ == '__main__': raise SystemExit(main())
