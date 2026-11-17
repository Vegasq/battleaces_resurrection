"""Exact-input diagnostic replay through the supported legacy BUFFERED protocol.

This is not arrival-mode latency acceptance. Human actions stay on their recorded
frames; original AI runs freshly and must reproduce the recorded bytes/states.
No journal looping, simulation-input substitution, or synthetic CLI fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
import traceback

from server import admission, community_protocol as c, protocol as p, public_protocol as q, tls_transport as tls
from server.bot_catalog import BotCatalog, BotChoice, cosmetic_keys
from server.game_data import decode_deck, decode_frame, decode_identity, encode_player_input
from server.protobuf_wire import get_bytes, get_repeated_bytes, get_uint, replace_fields
from tools import benchmark_hybrid_coordinator as base

ROOT, require, digest = base.ROOT, base.require, base.digest
WINDOW = 12
MAX_JOURNAL_BYTES = 32*1024*1024


class ReplaySource:
    """Bind a completed native army journal or one completed public episode."""
    def __init__(self, directory, phase, duration):
        self.directory = directory
        report_path = directory/'benchmark.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        require(report.get('passed') and report.get('native_qualified') and report.get('source_unchanged'),
                'replay requires a completed source-bound native journal')
        sources = report.get('source_at_start')
        require(isinstance(sources, dict) and sources and sources == report.get('source_at_finish') and
                all(isinstance(name, str) and name and isinstance(value, str) and len(value) == 64 and
                    all(ch in '0123456789abcdef' for ch in value) for name, value in sources.items()),
                'source hash maps are missing, malformed or differ')
        self.binding = {'benchmark.json': base.file_digest(report_path)}
        self.asset_sha = report['asset_manifest_sha256']
        self.spec = report.get('workload', report.get('source_workload'))
        require(isinstance(self.spec, dict), 'source workload missing')
        if 'workload' in report:
            folder = directory
            metadata = directory/'frames.jsonl'
            require(metadata.stat().st_size <= 128*1024*1024, 'source frame metadata exceeds bound')
            with metadata.open(encoding='utf-8') as stream:
                rows = [json.loads(line) for line in stream]
            raw_sha = report['bootstrap_sha256']
            self.binding['frames.jsonl'] = base.file_digest(metadata)
            expected_journal_sha = report['input_journal_sha256']
        else:
            require(report['activity'] == phase, 'public source activity differs from selected phase')
            events = directory/'events.jsonl'
            require(base.file_digest(events) == report['events_sha256'], 'source public trace digest differs')
            self.binding['events.jsonl'] = report['events_sha256']
            source_episode = next((e for e in report['episodes'] if (e['lane'], e['number']) == (0, 0)), None)
            require(source_episode is not None, 'source first episode missing')
            match = source_episode['match']
            require(len(match) == 32 and all(ch in '0123456789abcdef' for ch in match), 'invalid source match identifier')
            folder = directory/'matches'/match
            prepared, end_ms, rows = None, None, []
            for row in base.EventRows(events):
                if row['event'] == 'measurement_started': end_ms = row['end_ms']
                if row['event'] == 'episode_prepared' and row['match'] == match: prepared = row
                if row['event'] == 'worker_frame' and row['match'] == match: rows.append(row)
            require(prepared is not None and end_ms is not None, 'source public episode/window missing')
            lower = max(source_episode['active_started_ms'], report['measurement_start_ms'])
            for row in rows: row['phase'] = phase if lower <= row['at_ms'] <= end_ms else 'outside'
            self.spec = dict(self.spec, scripted_armies=prepared['humans'],
                             opponent='ai' if prepared['bots'] else 'scripted', decks=prepared['effective_decks'])
            raw_sha, expected_journal_sha = prepared['bootstrap_sha256'], None
        bootstrap = folder/'bootstrap.pb.gz'
        require(bootstrap.stat().st_size <= 2*1024*1024, 'source bootstrap exceeds bound')
        self.raw = gzip.decompress(bootstrap.read_bytes())
        require(len(self.raw) <= 32*1024*1024 and digest(self.raw) == raw_sha, 'source bootstrap digest differs')
        config = get_bytes(self.raw, 1, required=True)
        army_rows = get_repeated_bytes(config, 2)
        armies = {get_uint(army, 1): army for army in army_rows}
        require(len(armies) == len(army_rows) and set(armies) in ({0, 1}, {0, 1, 2, 3}), 'source army topology differs')
        humans = [slot for slot, army in sorted(armies.items()) if not decode_identity(get_bytes(army, 2, required=True))['ai_profile_id']]
        decks = {str(slot): list(decode_deck(get_bytes(army, 3, required=True))['units']) for slot, army in armies.items()}
        require('scripted_armies' not in self.spec or self.spec['scripted_armies'] == humans, 'source human metadata differs from bootstrap')
        require('decks' not in self.spec or self.spec['decks'] == decks, 'source deck metadata differs from bootstrap')
        require(self.spec['seed'] == get_uint(config, 38) and (self.spec['opponent'] == 'ai') == (len(humans) < len(armies)),
                'source seed/AI metadata differs from bootstrap')
        # Older qualified 1v1 journals predate these descriptive fields. Derive
        # them from their hash-bound original bootstrap, never from assumptions.
        self.spec = dict(self.spec, scripted_armies=humans, decks=decks, player_count=len(armies), mode=get_uint(config, 36))
        require(1 <= len(rows) <= 40000 and [r['frame'] for r in rows] == list(range(len(rows))),
                'source frame sequence/count differs')
        candidates = [r['frame'] for r in rows if r['phase'] == phase]
        wanted = math.ceil(duration*20)
        require(len(candidates) >= wanted, 'source phase is too short; record a longer qualifying workload, never loop it')
        self.first, self.last = candidates[0], candidates[wanted-1]
        require(candidates[:wanted] == list(range(self.first, self.last+1)), 'source phase is not contiguous')
        selected = rows[self.first:self.last+1]
        self.load_evidence = []
        for slot in self.spec['scripted_armies']:
            counts = [row['unit_counts'][str(slot)] for row in selected]
            motion = sum(row['moving_units'][str(slot)] > 0 for row in selected)
            combat = sum(row['newly_damaged_units'][str(slot)] > 0 or
                         row.get('newly_lost_unit_resource_cost', {}).get(str(slot), 0) > 0 for row in selected)
            target = self.spec['target_units_per_scripted_army']
            require(counts[0] >= target and (motion if phase == 'movement' else combat) > 0,
                    'source phase lacks initial target population or per-human activity')
            if phase == 'movement':
                require(min(counts) >= target, 'source movement phase lost the target population')
            self.load_evidence.append(dict(slot=slot, minimum_units=min(counts), maximum_units=max(counts),
                target_population_frames=sum(count >= target for count in counts), frames=len(counts),
                moving_frames=motion, damage_or_loss_frames=combat,
                resource_loss_counter_available=all('newly_lost_unit_resource_cost' in row for row in selected),
                scope='scripted human army only; combat depletion remains explicit'))
        self.expected = [{k: row[k] for k in ('frame', 'phase', 'input_sha256', 'state_sha256')} for row in rows[:self.last+1]]
        journal = folder/'frames.bin'
        require(journal.stat().st_size <= MAX_JOURNAL_BYTES, 'source replay journal exceeds32MiB bound')
        journal_sha = base.file_digest(journal)
        require(expected_journal_sha is None or journal_sha == expected_journal_sha, 'source input journal digest differs')
        self.binding['bootstrap.pb.gz'], self.binding['frames.bin'] = base.file_digest(bootstrap), journal_sha
        self.inputs = []
        with journal.open('rb') as stream:
            for row in rows:
                payload = base.army.read_frame(stream)
                require(digest(payload) == row['input_sha256'] and decode_frame(payload)['frame'] == row['frame'],
                        'source recorded input bytes/frame differ')
                if row['frame'] <= self.last: self.inputs.append(payload)
            require(not stream.read(1), 'source journal has extra frames')
        self.retained_input_bytes = sum(map(len, self.inputs))
        self.identities = {}
        self.humans = tuple(self.spec['scripted_armies'])

    def attach_template(self, template):
        self.identities = {slot: get_bytes(value, 2, required=True) for slot, value in template.armies.items()}
        roster = {slot: decode_identity(value) for slot, value in self.identities.items()}
        mode = template.game_mode
        require(mode in q.MODES and tuple(q.MODES[mode][1][:len(self.humans)]) == self.humans,
                'source human slots cannot be produced by this public matchmaking mode')
        require(set(self.humans) == {slot for slot, value in roster.items() if not value['ai_profile_id']},
                'source AI/human ownership differs')
        supported_humans = template.player_count if len(self.humans) == template.player_count else (2 if mode == 5 else 1)
        require(len(self.humans) == supported_humans, 'source human cohort is unsupported by this bounded replay preparer')
        require(all(decode_deck(get_bytes(template.armies[slot], 3, required=True))['units'] ==
                    decode_deck(get_bytes(template.armies[self.humans[0]], 3, required=True))['units'] for slot in self.humans),
                'heterogeneous human decks are unsupported by this bounded replay preparer')
        self.roster = roster

    def bodies(self, frame):
        bodies = {slot: encode_player_input(identity) for slot, identity in self.identities.items()}
        seen = set()
        for body in decode_frame(self.inputs[frame])['players']:
            identity = get_bytes(body, 1, required=True)
            matching = [slot for slot, expected in self.identities.items() if identity == expected]
            require(len(matching) == 1 and matching[0] not in seen, 'source player identity duplicated/unknown')
            seen.add(matching[0]); bodies[matching[0]] = body
        require(base.encode_frame(frame, bodies) == self.inputs[frame], 'source frame is not canonical')
        return bodies


class SourceTemplate(base.FixedTemplate):
    def build_match(self, *args, **kwargs):
        match = super().build_match(*args, **kwargs)
        require(match.raw_game_data == self.expected_raw, 'public roster/deck/cosmetics changed source bootstrap')
        return match


def source_bot_choices(catalog, template, source):
    """Only already exported compatible decks/cosmetics; no invented AI roster."""
    choices = {}
    for slot, identity in source.roster.items():
        profile = identity['ai_profile_id']
        if not profile: continue
        require(profile in catalog.profiles, 'source AI profile absent from public catalog')
        mode, decks = catalog.profiles[profile]
        require(mode in ((2, 5) if template.game_mode == 5 else (template.game_mode,)), 'source AI mode differs')
        army = template.armies[slot]
        message = get_bytes(army, 3, required=True)
        candidates = [deck for deck in decks if replace_fields(deck.message, {3: []}) == replace_fields(message, {3: []})]
        require(candidates, 'source custom AI deck is not a supported public catalog deck')
        deck = candidates[0]
        name, portrait, banner = identity['name'], get_uint(army, 6), get_uint(army, 5)
        if deck.kind == 1:
            require((name, portrait, banner, message) == (deck.name, deck.portrait, deck.banner, deck.message),
                    'source character bot cosmetics differ')
        else:
            require(name in catalog.names and portrait in catalog.portraits and banner in catalog.banners,
                    'source worker-only AI identity is not a public catalog selection')
            require(set(cosmetic_keys(message, catalog.cosmetic_ids)) == {portrait, banner}, 'source AI cosmetics differ')
        choices[slot] = BotChoice(profile, mode, name, portrait, banner, deck, message, 'normal', catalog.strengths[18])
    return choices


class ReplayPeer(base.Peer):
    async def numbered(self, frame, body):
        self.trace.emit('buffered_input_created', peer=self.name, match=self.match, slot=self.slot,
                        frame=frame, body_sha256=digest(body))
        began = self.trace.now()
        due, requested, ordered = self.up.schedule(began)
        await self.tx_queue.put((struct.pack('<I', frame)+body, frame, began, due, requested, ordered, self.up.ordinal))

    async def transmit_loop(self):
        while True:
            payload, frame, began, due, requested, ordered, ordinal = await self.tx_queue.get()
            try:
                await self.up.wait(f'buffered:{frame}', began, due, requested, ordered, ordinal)
                async with self.sender_lock:
                    self.writer.write(p.encode(p.INPUT, payload))
                    self.trace.emit('buffered_input_sent', peer=self.name, match=self.match, slot=self.slot, frame=frame)
                    await asyncio.wait_for(self.writer.drain(), 5)
            finally: self.tx_queue.task_done()


class ReplayWorker(base.ObservedWorker):
    def __init__(self, worker, trace, spec, source):
        super().__init__(worker, trace, spec)
        self.source = source

    async def process_frame(self, payload, dt_ms=None):
        if self.halt: await asyncio.Event().wait()
        before = self.trace.now()
        frame = decode_frame(payload)['frame']
        require(frame <= self.source.last and digest(payload) == self.source.expected[frame]['input_sha256'],
                'fresh human/AI native frame differs from recorded input')
        prior = self.worker.last_state
        self.idle.clear()
        started = self.trace.now()
        try: result = await self.worker.process_frame(payload, dt_ms)
        finally: self.idle.set()
        ended = self.trace.now()
        state_sha = base.army.state_digest(result.state)
        require(result.frame == frame and state_sha == self.source.expected[frame]['state_sha256'],
                'fresh native observable state differs from recorded state')
        self.last_observation = base.army.observation(result.state, prior, self.spec)
        observer = (started-before)+(self.trace.now()-ended)
        self.trace.emit('worker_frame', match=self.match, frame=frame, worker_pid=self.pid,
                        input_sha256=digest(payload), state_sha256=state_sha, step_rpc_ms=ended-started,
                        ai_rpc_ms=self.ai_ms, observer_ms=observer, **self.last_observation)
        self.ai_ms = 0
        return result


async def wait_for_input_eligibility(room, peers, frame, bodies, trace):
    began, eligibility = trace.now(), False
    while True:
        require(room.state == 'running' and all(not task.done() for peer in peers for task in peer.tasks),
                'buffered replay peer/match stopped early')
        for peer in peers:
            while not peer.frames.empty(): peer.frames.get_nowait()
        if all(frame <= peer.applied+WINDOW for peer in peers):
            try:
                for peer in peers: room.validation.validate_player_input(peer.slot, bodies[peer.slot])
                break
            except ValueError:
                require(room.frame < frame, 'source action still invalid when its native frame is due')
                eligibility = True
        await asyncio.sleep(.005)
    trace.emit('buffered_replay_wait', match=room.match_id, frame=frame, elapsed_ms=trace.now()-began,
               ownership_eligibility_wait=eligibility, scope='diagnostic source lookahead; no validation relaxed')


class ReplayExperiment(base.Experiment):
    def __init__(self, args, trace, template, source, backend):
        super().__init__(args, trace, template, source.spec, backend)
        self.source = source

    async def factory(self, data, bots=None):
        wrapped = await super().factory(data, bots)
        actual = ReplayWorker(wrapped.worker, self.trace, self.spec, self.source)
        self.workers[-1] = actual
        return actual

    async def start(self):
        await super().start()
        self.server.input_window = WINDOW
        self.server.adaptive_input_window = False
        frozen = source_bot_choices(self.server.bot_catalog, self.template, self.source)
        def choose(mode, *, role='opponents', excluded_names=(), **kwargs):
            possible = [choice for slot, choice in sorted(frozen.items()) if choice.name not in excluded_names]
            require(possible, 'recorded bot roster exhausted')
            return possible[0]
        self.server.bot_catalog.choose = choose

    async def connect(self, name):
        # Base prepare's deterministic seat names carry lane/seat; display names
        # must remain exactly those in the frozen source bootstrap.
        lane = int(name.split()[0][5:]); index = int(name.rsplit('seat', 1)[1])
        slot = self.source.humans[index]
        display = self.source.roster[slot]['name']
        reader, writer = await tls.open_verified_connection('127.0.0.1', self.port, self.client_tls)
        profile = await admission.authenticate_client(reader, writer,
            base.benchmark_token(self.spec['seed'], f'buffered:{lane}:{display}'), rc_open=True)
        peer = ReplayPeer(reader, writer, self.trace, display, self.args.rtt_ms, self.args.jitter)
        self.peers.append(peer)
        await peer.send(c.HELLO, c.hello(profile, display))
        await peer.receive(c.WELCOME)
        # No arrival capability negotiation: this is the ordinary buffered cohort.
        return peer

    async def prepare(self, lane, number):
        episode = await super().prepare(lane, number)
        require(not episode.room.command_scheduling and set(episode.room.peers) == set(self.source.humans),
                'buffered public roster/mode differs')
        require(set(episode.room.input_windows.values()) == {WINDOW}, 'buffered input window differs')
        original = episode.room.on_message
        async def observed(peer, kind, payload):
            await original(peer, kind, payload)
            if kind == p.INPUT:
                frame, = struct.unpack_from('<I', payload)
                self.trace.emit('buffered_input_accepted', match=episode.room.match_id, slot=peer.slot,
                                frame=frame, body_sha256=digest(payload[4:]))
        episode.room.on_message = observed  # Owned diagnostic receipt wrapper only.
        return episode

    async def load(self, episode):
        for peer in episode.peers: await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        for peer in episode.peers: await peer.receive(p.START)

    async def replay(self, episode):
        room, peers = episode.room, episode.peers
        for frame in range(self.source.last+1):
            bodies = self.source.bodies(frame)
            await wait_for_input_eligibility(room, peers, frame, bodies, self.trace)
            await asyncio.gather(*(peer.numbered(frame, bodies[peer.slot]) for peer in peers))
        await asyncio.gather(*(peer.tx_queue.join() for peer in peers))
        async with asyncio.timeout(30):
            while any(peer.applied < self.source.last for peer in peers):
                for peer in peers:
                    while not peer.frames.empty(): peer.frames.get_nowait()
                require(room.state == 'running', 'buffered replay ended before final delivery')
                await asyncio.sleep(.01)
        await room.sim.stop_requests()
        await room.finish('bounded benchmark episode teardown', aborted=True)
        for peer in peers: await peer.close()
        episode.ended = self.trace.now()


def qualify_replay(rows, episodes, source):
    def indexed(event, fields):
        values = {}
        for row in (r for r in rows if r['event'] == event):
            key = tuple(row[name] for name in fields)
            require(key not in values, 'duplicate buffered evidence: '+event)
            values[key] = row
        return values
    created = indexed('buffered_input_created', ('match', 'slot', 'frame'))
    sent = indexed('buffered_input_sent', ('match', 'slot', 'frame'))
    accepted = indexed('buffered_input_accepted', ('match', 'slot', 'frame'))
    delivered = indexed('client_frame_delivered', ('match', 'slot', 'frame'))
    received = indexed('client_frame_received', ('match', 'slot', 'frame'))
    published = indexed('frame_queued', ('match', 'frame'))
    workers = indexed('worker_frame', ('match', 'frame'))
    expected = {(episode.room.match_id, slot, frame) for episode in episodes
                for slot in source.humans for frame in range(source.last+1)}
    require(created.keys() == sent.keys() == accepted.keys() == delivered.keys() == received.keys() == expected,
            'buffered source input/send/receipt/publication/delivery conservation failed')
    expected_frames = {(episode.room.match_id, frame) for episode in episodes for frame in range(source.last+1)}
    require(workers.keys() == published.keys() == expected_frames, 'buffered native/publication frame count differs')
    timings = {name: [] for name in ('injected_uplink_ms', 'sent_to_accepted_ms', 'accepted_to_published_ms', 'created_to_delivered_ms')}
    for key in expected:
        match, slot, frame = key
        original, tx, receipt, applied = created[key], sent[key], accepted[key], delivered[key]
        publication, native, network = published[match, frame], workers[match, frame], received[key]
        participants = publication['participant_sha256']
        require(original['body_sha256'] == receipt['body_sha256'] == participants.get(slot, participants.get(str(slot))),
                'buffered input body changed before publication')
        require(network['payload_sha256'] == publication['frame_payload_sha256'] and
                network['input_sha256'] == native['input_sha256'] == source.expected[frame]['input_sha256'] and
                native['state_sha256'] == source.expected[frame]['state_sha256'], 'buffered native/TLS/source bytes or state differ')
        for name, before, after in (('injected_uplink_ms', original, tx), ('sent_to_accepted_ms', tx, receipt),
                                   ('accepted_to_published_ms', receipt, publication), ('created_to_delivered_ms', original, applied)):
            require(after['at_ms'] >= before['at_ms'], 'buffered same-clock ordering differs')
            if frame >= source.first: timings[name].append(after['at_ms']-before['at_ms'])
    windows, frame_times, loads = {}, {}, []
    for episode in episodes:
        match = episode.room.match_id
        selected = [published[match, frame] for frame in range(source.first, source.last+1)]
        if source.first:
            start = published[match, source.first-1]['at_ms']
        else:
            start = next(row['at_ms'] for row in rows if row['event'] == 'match_started' and row['match'] == match)
        end = selected[-1]['at_ms']
        windows[str(episode.lane)] = dict(start_ms=start, end_ms=end, elapsed_seconds=(end-start)/1000,
            **base.publication_stats(selected, start, end))
        for frame in range(source.first, source.last+1):
            native, pub = workers[match, frame], published[match, frame]
            residual = pub['frame_work_ms']-native['step_rpc_ms']-native['ai_rpc_ms']-native['observer_ms']
            require(residual >= -.01, 'buffered worker/observer timing exceeds enclosing frame work')
            values = dict(step_rpc_ms=native['step_rpc_ms'], ai_rpc_ms=native['ai_rpc_ms'], observer_ms=native['observer_ms'],
                          frame_work_ms=pub['frame_work_ms'], coordinator_outside_worker_ms=residual)
            for name, value in values.items(): frame_times.setdefault(name, []).append(value)
        for slot in source.humans:
            sample = [workers[match, frame] for frame in range(source.first, source.last+1)]
            loads.append(dict(lane=episode.lane, slot=slot, frames=len(sample),
                target_units=source.spec['target_units_per_scripted_army'],
                target_population_frames=sum(row['unit_counts'][str(slot)] >= source.spec['target_units_per_scripted_army'] for row in sample),
                moving_frames=sum(row['moving_units'][str(slot)] > 0 for row in sample),
                damage_or_loss_frames=sum(row['newly_damaged_units'][str(slot)] > 0 or
                                          row['newly_lost_unit_resource_cost'][str(slot)] > 0 for row in sample)))
    overlap = max(0, min(value['end_ms'] for value in windows.values())-max(value['start_ms'] for value in windows.values()))/1000
    return dict(complete=True, frames_per_match=source.last+1, participant_inputs=len(expected), exact_source_inputs=True,
                exact_observable_states=True, fresh_ai=source.spec['opponent'] == 'ai',
                scope='observable parsed state, not an opaque native world checksum; when present AI is regenerated, never replay-injected',
                measured_source_frames=[source.first, source.last], windows=windows, concurrent_window_seconds=overlap,
                input_timings_ms={k: base.summary(v) for k, v in timings.items()},
                frame_timings_ms={k: base.summary(v) for k, v in frame_times.items()}, scripted_human_load=loads,
                eligibility_wait_ms=base.summary([row['elapsed_ms'] for row in rows if row['event'] == 'buffered_replay_wait'
                                                  and row['ownership_eligibility_wait']]))


def source_hashes():
    return base.source_hashes() | {'tools/benchmark_buffered_coordinator.py': digest(Path(__file__).read_bytes())}


async def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    trace = base.Trace(args.output)
    started = time.perf_counter()
    report = dict(passed=False, native_qualified=False, workload_qualified=False, performance_qualified=False,
                  arrival_qualified=False, protocol='legacy-buffered', scope=__doc__, clock=trace.clock,
                  source_at_start=source_hashes(), matches=args.matches, duration_seconds=args.duration_seconds,
                  rtt_ms=args.rtt_ms, jitter_trace_ms=args.jitter, activity=args.phase, input_window=WINDOW)
    experiment, sampler_task, source = None, None, None
    sampler = base.ResourceSampler(args, trace)
    try:
        base.verify_assets(args.assets)
        source = ReplaySource(args.journal, args.phase, args.duration_seconds)
        require(source.asset_sha == digest((args.assets/'asset-manifest.json').read_bytes()), 'source assets differ')
        template = SourceTemplate(source.raw, catalog_path=args.assets/'unit-catalog.json', descriptors_path=args.assets/'descriptors')
        template.benchmark_seed, template.expected_raw = source.spec['seed'], source.raw
        source.attach_template(template)
        args.ai = len(source.humans) < template.player_count
        backend = base.army.select_backend(args)
        report.update(ai=args.ai, backend=base.army.backend_identity(backend), source_binding=source.binding,
                      source_load_evidence=source.load_evidence,
                      source_workload=source.spec, asset_manifest_sha256=source.asset_sha,
                      source_bootstrap_sha256=digest(source.raw), source_journal_report_sha256=source.binding['benchmark.json'],
                      retained_source_input_bytes=source.retained_input_bytes)
        experiment = ReplayExperiment(args, trace, template, source, backend)
        async with asyncio.timeout(args.timeout_seconds):
            sampler_task = asyncio.create_task(sampler.run())
            await experiment.start()
            episodes = [await experiment.prepare(lane, 0) for lane in range(args.matches)]
            await asyncio.gather(*(experiment.load(episode) for episode in episodes))
            async with asyncio.TaskGroup() as tasks:
                for episode in episodes: tasks.create_task(experiment.replay(episode))
            require(not trace.unexpected_events, 'unexpected buffered protocol failure/abort')
        report.update(passed=True, native_qualified=True)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        sampler.stopped = True
        if sampler_task:
            sampler_task.cancel()
            outcomes = await asyncio.gather(sampler_task, return_exceptions=True)
            if any(isinstance(v, BaseException) and not isinstance(v, asyncio.CancelledError) for v in outcomes):
                report.update(passed=False, resource_error='resource sampler failed')
        if experiment:
            try: await experiment.close()
            except BaseException as error: report.update(passed=False, cleanup_error=repr(error))
            report['worker_startups'] = experiment.startups
            report['workers'] = [dict(pid=w.pid, native_pid=w.native_pid, exit_code=w.process.poll(), failure=w.failure,
                backend_statistics=w.backend_statistics,
                threads_closed=not w._stderr_thread.is_alive() and all(not t.is_alive() for t in w._io._threads))
                for w in experiment.workers]
            report['passed'] &= bool(experiment.workers) and all(w['exit_code'] == 0 and w['failure'] is None and w['threads_closed']
                and (experiment.backend is None or base.army.backend_cleanup_complete(w['backend_statistics'])) for w in report['workers'])
        try: trace.close()
        except (ValueError, OSError) as error: report.update(passed=False, trace_error=repr(error))
        report['diagnostic_trace'], report['resources'] = trace.report(), sampler.report()
        if trace.complete and experiment and source and experiment.episodes:
            try:
                result = qualify_replay(trace.rows, experiment.episodes, source)
                report['buffered_replay'] = result
                report['workload_qualified'] = all(row['target_population_frames'] == row['frames'] and
                    (row['moving_frames'] if args.phase == 'movement' else row['damage_or_loss_frames']) > 0
                    for row in result['scripted_human_load'])
                report['acceptance'] = dict(exact_buffered_replay=True, measured_overlap_300s=result['concurrent_window_seconds'] >= 300,
                    buffered_cadence=all(row['cadence_pass'] for row in result['windows'].values()),
                    scripted_human_load=report['workload_qualified'], resource_qualification=report['resources']['complete'],
                    arrival_M2=False, arrival_P4=False, repeated_alternating_pairs=False)
            except (ValueError, KeyError, TypeError) as error:
                report.update(passed=False, replay_evidence_error=repr(error))
        report.update(elapsed_seconds=time.perf_counter()-started, source_at_finish=source_hashes())
        report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
        report['passed'] &= report['source_unchanged']
        report['native_qualified'] &= report['passed']
        report['events_sha256'] = base.file_digest(args.output/'events.jsonl')
        (args.output/'benchmark.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({name: report[name] for name in ('passed', 'error', 'elapsed_seconds', 'acceptance') if name in report}))
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'output', 'journal', 'tls-cert', 'tls-key', 'tls-ca'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--phase', choices=('movement', 'combat'), default='movement')
    parser.add_argument('--duration-seconds', type=float, default=5)
    parser.add_argument('--timeout-seconds', type=float, default=900)
    parser.add_argument('--matches', type=int, choices=(1, 2), default=1)
    parser.add_argument('--rtt-ms', type=int, choices=(0, 130, 475), default=0)
    parser.add_argument('--jitter-ms', default='0')
    for name in ('proc-root', 'resource-cgroup', 'wine-executable', 'windows-python', 'wine-prefix-template', 'wine-cgroup-parent'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--linux-clock-ticks', type=int)
    args = parser.parse_args(argv)
    for name in ('assets', 'output', 'journal', 'tls_cert', 'tls_key', 'tls_ca'):
        setattr(args, name, getattr(args, name).resolve())
    args.profile_worker = False
    args.jitter = [float(value) for value in args.jitter_ms.split(',')]
    require(sys.platform.startswith('linux') if base.army.wine_requested(args) else os.name == 'nt', 'explicit supported backend required')
    require(args.output.is_relative_to(ROOT/'local') and not args.output.exists(), 'new ignored output required')
    require(not args.output.is_relative_to(args.assets) and not args.output.is_relative_to(args.journal), 'output must be separate')
    require(5 <= args.duration_seconds <= 600 and 30 <= args.timeout_seconds <= 3600, 'bounded replay duration required')
    resource = (args.proc_root, args.resource_cgroup, args.linux_clock_ticks)
    require(not any(v is not None for v in resource) or all(v is not None for v in resource), 'complete isolated resource paths required')
    if args.proc_root:
        args.proc_root, args.resource_cgroup = args.proc_root.resolve(), args.resource_cgroup.resolve()
        require(args.proc_root.is_dir() and (args.resource_cgroup/'cgroup.procs').is_file() and
                (args.resource_cgroup/'memory.current').is_file() and 1 <= args.linux_clock_ticks <= 10000, 'invalid resource paths')
    base.Delivery(args.rtt_ms, args.jitter, None, '', '')
    return args


def main():
    return asyncio.run(run(arguments()))


if __name__ == '__main__':
    raise SystemExit(main())
