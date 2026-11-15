"""Owned public server-AI command scheduling, with no movement prediction.

Runs one original native client and native authoritative AI worker behind a
loopback TLS stream delay. Original public/build callbacks are automated; mode1
also completes Concede/Continue. Team modes stop after a measured prefix because
conceding one human need not end its AI ally's game. Owned teardown does not qualify
native Quit, physical input, Internet jitter or player-perceived smoothness.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import ctypes
import gzip
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import struct
import subprocess
import time
import traceback
from unittest import mock

from client_patch.transport import bridge, client, launcher
from server import admission, command_scheduling as command_wire, loadout_protocol, protocol as p, public_protocol as q, tls_transport as tls
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.cosmetics import CosmeticCatalog
from server.dedicated_server import Audit, DedicatedServer, Room
from server.game_data import GameTemplate, decode_frame, decode_player_input
from server.profiles import ProfileStore
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker, _WindowsJob
from tests.test_admission import Store
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools import frame_timing
from tools.run_secure_match import read_native_log
from tools.stream_shaper import StreamShaper
from tools.verify_custom_lobby import require
from tools.verify_high_latency_clients import digest, prefix_trace, state_digest, summary
from tools.verify_original_command_scheduling import build_frames, cleanup_step, first_output_ready, native_builds, stop_owned_process

ROOT = Path(__file__).resolve().parents[1]
MARKER = b'BA_RESURRECTION_SERVER_AI_COMMAND_SCHEDULING_V1'
RETURNED = 'PUBLIC QUEUE completed return:'


def source_hashes():
    paths = {Path(__file__), ROOT/'tools/verify_original_command_scheduling.py',
             ROOT/'tools/verify_high_latency_clients.py', ROOT/'tools/stream_shaper.py',
             ROOT/'tools/frame_timing.py', ROOT/'tools/run_secure_match.py',
             ROOT/'tests/test_admission.py', ROOT/'tests/test_tls_transport.py'}
    for folder, patterns in (('server', ('*.py',)), ('client_patch/transport', ('*.py',)),
                             ('client_patch/src', ('*.cpp', '*.hpp', '*.h'))):
        for pattern in patterns:
            paths.update((ROOT/folder).glob(pattern))
    return {path.relative_to(ROOT).as_posix(): digest(path.read_bytes()) for path in sorted(paths)}


def validate_options(args):
    require(args.scheduling in ('buffered', 'arrival'), 'explicit scheduling mode required')
    require(type(args.frames) is int and 600 <= args.frames <= 1200, 'bounded 600..1200-frame prefix required')
    require(type(args.timeout) in (int, float) and math.isfinite(args.timeout) and 90 <= args.timeout <= 240,
            'bounded native deadline required')
    require(type(args.rtt_ms) in (int, float) and math.isfinite(args.rtt_ms) and 0 <= args.rtt_ms <= 500,
            'bounded finite stream delay required')
    require(re.fullmatch('[a-f0-9]{64}', args.expected_helper_sha256) is not None, 'exact helper SHA256 required')
    require(getattr(args, 'mode', 1) in q.MODES, 'supported public mode required')


def diagnostic_arguments(frames, mode=1):
    flags = ['-public-queue-smoke', '-public-queue-smoke-mode='+str(mode), '-lan-smoke',
             '-dedicated-rematch-smoke', '-frame-timing', '-frame-timing-frames='+str(frames)]
    if mode == 1:
        flags += ['-dedicated-surrender-smoke', '-dedicated-surrender-frame='+str(frames+70)]
    return flags


def read_journal(output, match, frames, participants):
    rows = []
    with (output/'matches'/match/'frames.bin').open('rb') as stream:
        for number in range(frames):
            header = stream.read(4); require(len(header) == 4, 'truncated journal header')
            size, = struct.unpack('<I', header)
            require(0 < size <= participants*p.MAX_INPUT+1024, 'unbounded journal input')
            raw = stream.read(size); require(len(raw) == size, 'truncated journal body')
            frame = decode_frame(raw)
            require(frame['frame'] == number and frame['timestep_ms'] == 50 and frame['frames_per_second'] == 20 and frame['speed'] == 1,
                    'canonical timing or frame sequence differs')
            # encode_frame omits players whose action list is empty.
            players, seen = {slot:() for slot in range(participants)}, set()
            for body in frame['players']:
                player = decode_player_input(body); slot = player['identity']['player_id']-1
                require(slot in range(participants) and slot not in seen, 'duplicate or invalid journal player')
                seen.add(slot)
                players[slot] = player['actions']
            rows.append(dict(frame=number, players=players, input_sha256=digest(raw)))
    return rows


async def replay_check(assets, output, match, expected, frames, participants):
    folder = output/'matches'/match
    worker = await SimulationWorker.create(gzip.decompress((folder/'bootstrap.pb.gz').read_bytes()),
                                           assets/'Simulation.dll', working_directory=output)
    try:
        with (folder/'frames.bin').open('rb') as stream:
            for frame in range(frames):
                header = stream.read(4); require(len(header) == 4, 'replay input header incomplete')
                size, = struct.unpack('<I', header)
                require(0 < size <= participants*p.MAX_INPUT+1024, 'replay input unbounded')
                body = stream.read(size); require(len(body) == size, 'replay input truncated')
                result = await worker.process_frame(body, dt_ms=50)
                require(result.frame == frame and state_digest(result.state) == expected[frame],
                        f'fresh native replay differs at frame{frame}')
    finally: await worker.close()
    require(worker.process.poll() == 0 and not worker.failure, 'replay worker cleanup failed')
    return dict(passed=True, frames=frames, participants=participants, scope='normalized observable worker state; no hidden-state claim')


class PublicBridge(bridge.Bridge):
    """Hash the actual TLS-delivered public frames before private native handoff."""
    def __init__(self, *args, evidence, mode=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.evidence, self.pending, self.matches = evidence, defaultdict(bytearray), {}
        self.mode = mode

    async def send(self, kind, identity, data=b''):
        if kind == bridge.DATA:
            pending = self.pending[identity]
            pending.extend(data)
            while len(pending) >= 4:
                size, = struct.unpack_from('<I', pending)
                require(1 <= size <= p.MAX_BODY, 'observed public packet length invalid')
                if len(pending) < size+4: break
                packet, body = pending[4], bytes(pending[5:size+4])
                del pending[:size+4]
                if packet in (q.MATCH, loadout_protocol.MATCH_LOADOUT):
                    value = q.decode_assignment(body, complete=packet == loadout_protocol.MATCH_LOADOUT)
                    require(value['mode'] == self.mode and value['count'] == q.MODES[self.mode][0] and
                            value['slot'] == 0 and value['human_mask'] == 1,
                            'server-AI assignment differs from one human and its bot roster')
                    self.matches[identity] = value['match']
                elif packet == q.FRAME:
                    require(identity in self.matches and len(body) >= 4, 'public frame precedes assignment')
                    frame, = struct.unpack_from('<I', body)
                    self.evidence.append(dict(match=self.matches[identity], frame=frame, payload_sha256=digest(body)))
        await super().send(kind, identity, data)


def human_conservation(match, journal, events, bodies, raw_bodies, log, frames):
    accepted = [row for row in events if row['event'] == 'command_batch_accepted' and row.get('match') == match]
    committed = [row for row in events if row['event'] == 'command_batch_committed' and row.get('match') == match and row['frame'] < frames]
    require(accepted and committed and {row['slot'] for row in accepted+committed} == {0},
            'only the human may submit scheduled command batches')
    indexed = {row['sequence']: row for row in accepted}
    require(len(indexed) == len(accepted), 'accepted human sequence repeated')
    committed_ids = [row['sequence'] for row in committed]
    require(len(set(committed_ids)) == len(committed_ids), 'human batch committed twice')
    native = {int(sequence):(int(count), int(size), sha) for identity, sequence, count, size, sha in re.findall(
        r'Original command batch submitted: match=([a-f0-9]{32}) sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64})', log)
        if identity == match}
    expected = defaultdict(list)
    for row in committed:
        sequence = row['sequence']; prior = indexed[sequence]
        body = bodies[(match, 0, sequence)]; raw = raw_bodies[(match, 0, sequence)]
        actions = decode_player_input(body)['actions']
        require(row['body_sha256'] == prior['body_sha256'] == digest(body) and
                row['action_count'] == prior['action_count'] == len(actions) and actions and
                row['frame'] == prior['earliest_frame'], 'human command content or next legal seal differs')
        require(native.get(sequence) == (len(decode_player_input(raw)['actions']), len(raw), digest(raw)),
                'native batch differs from actual socket submission')
        expected[row['frame']].extend(actions)
    require(all(row['sequence'] in committed_ids for row in accepted if row['earliest_frame'] < frames),
            'accepted prefix command was lost')
    require(all(frame['players'][0] == tuple(expected[frame['frame']]) for frame in journal),
            'human canonical command order/content differs')
    return dict(committed_batches=len(committed), exact_ordered_human_actions=True, native_socket_bytes_match=True)


def ai_conservation(match, journal, bot_bodies):
    actions = defaultdict(int)
    bots = set(journal[0]['players'])-{0}
    for frame in journal:
        for slot in bots:
            body = bot_bodies[(match, frame['frame'], slot)]
            decoded = decode_player_input(body)
            require(decoded['identity']['player_id'] == slot+1 and decoded['actions'] == frame['players'][slot],
                    'canonical AI commands differ from native worker producer')
            if frame['frame'] > 0: actions[slot] += len(decoded['actions'])
    require(sum(actions.values()) > 0, 'AI produced no non-startup actions')
    return dict(frames=len(journal), non_startup_actions=sum(actions.values()), actions_by_slot=dict(actions), exact_native_ai_actions=True)


def solo_startup(match, events):
    rows = [row for row in events if row.get('match') == match]
    waiting = [row for row in rows if row['event'] == 'command_startup_waiting']
    ready = [row for row in rows if row['event'] == 'command_startup_ready']
    released = [row for row in rows if row['event'] == 'command_startup_released']
    require(len(waiting) == len(ready) == len(released) == 1, 'one-human readiness barrier incomplete')
    wait, ack, release = waiting[0], ready[0], released[0]
    require(wait['ready_slots'] == release['ready_slots'] == [0] and ack['slot'] == 0 and
            ack['ready_count'] == 1 and ack['all_ready'] and wait['frame'] == 0 and release['frame'] == 1,
            'AI must not be required to send client readiness')
    require(wait['observed_at'] <= ack['observed_at'] <= release['observed_at'] and
            abs(release['next_tick']-release['rebased_at']-.05) < .000001, 'startup clock rebase differs')
    seals = {row['frame']:row for row in rows if row['event'] == 'probe_command_frame_sealed'}
    require(set(seals) == {0, 1} and seals[1]['observed_perf_counter'] >= release['next_tick'],
            'frame1 sealed before actual first-output readiness')
    return dict(human_ready_slots=[0], wait_ms=release['wait_ms'], frame1_after_ready=True)


def human_search_deadline(match, events, log, mode):
    entered = [row for row in events if row['event'] == 'public_queue_entered']
    offered = [row for row in events if row['event'] == 'public_match_offered' and row.get('match') == match]
    require(len(entered) == len(offered) == 1, 'one public search and offer required')
    entry, offer = entered[0], offered[0]
    require(entry['mode'] == offer['mode'] == mode and offer['fallback'] and
            offer['humans'] == [entry['profile']] and offer['tickets'] == [entry['ticket']] and
            0 < entry['wait_ms'] <= 30000, 'solo offer identity or remaining search budget differs')
    # apply() snapshots now before awaiting save_loadout(). Its audit is emitted
    # afterwards, so audit-to-audit elapsed time is not the queue's deadline.
    require(math.isclose(entry['queue_deadline']-entry['queue_started_at'], q.FALLBACK_SECONDS,
                         rel_tol=0, abs_tol=1e-6), 'server human-search duration differs')
    require(entry['queue_deadline'] <= offer['queue_decision_at'] <= entry['queue_deadline']+3,
            'solo offer preceded actual search deadline or arrived too late')
    ticket = str(entry['ticket'])
    starts = re.findall(r'\[(\d+)\] Native search began: ticket='+ticket+r' mode='+str(mode)+r'\b', log)
    clicks = re.findall(r'\[(\d+)\] PUBLIC QUEUE SMOKE original OnMapSelected: mode='+str(mode)+r'\b', log)
    require(len(starts) == len(clicks) == 1, 'original native search start/callback missing or repeated')
    started, clicked = int(starts[0]), int(clicks[0])
    native_elapsed_ms = offer['probe_tick_ms']-started
    require(started <= clicked <= offer['probe_tick_ms'] and 30000 <= native_elapsed_ms <= 33000,
            'original native human search did not wait the normal thirty seconds')
    return dict(native_search_to_offer_ms=native_elapsed_ms,
                server_deadline=entry['queue_deadline'], server_offer_decision=offer['queue_decision_at'],
                server_deadline_lateness_ms=(offer['queue_decision_at']-entry['queue_deadline'])*1000,
                queue_audit_delay_ms=(entry['observed_at']-(entry['queue_deadline']-entry['wait_ms']/1000))*1000,
                audit_to_audit_seconds=offer['observed_at']-entry['observed_at'])


def classify_worker_cleanup(worker, events, *, complete_match):
    starts = [(index, row) for index, row in enumerate(events)
              if row['event'] == 'worker_started' and row['worker_pid'] == worker.pid]
    match = starts[0][1]['match'] if len(starts) == 1 else None
    releases = [index for index, row in enumerate(events) if row['event'] == 'worker_released' and
                row['worker_pid'] == worker.pid and row.get('match') == match]
    released = match is not None and len(releases) == 1 and starts[0][0] < releases[0]
    cleanup = worker._cleanup_task
    cleanup_done = bool(cleanup is not None and cleanup.done() and not cleanup.cancelled() and
                        cleanup.exception() is None)
    reaped = (worker.process.poll() is not None and worker.closed and cleanup_done and
              not worker._stderr_thread.is_alive())
    teardown = [index for index, row in enumerate(events) if
                row['event'] == 'probe_owned_team_prefix_teardown' and row.get('match') == match and
                worker.pid in row['healthy_worker_pids']]
    aborted = [(index, row) for index, row in enumerate(events)
               if row['event'] == 'match_aborted' and row.get('match') == match]
    # A live team prefix deliberately ends by closing our owned peer. That can
    # cancel an in-flight worker request, whose owned abort path exits with1.
    # Never apply this exception to a completed game or a pre-existing failure.
    cancelled = bool(not complete_match and released and len(teardown) == len(aborted) == 1 and
                     starts[0][0] < teardown[0] < aborted[0][0] < releases[0] and
                     aborted[0][1]['reason'] in ('public player disconnected', 'server stopped') and
                     not any(row['event'] == 'match_completed' and row.get('match') == match for row in events) and
                     worker.process.poll() == 1 and (worker.failure or '').startswith('CancelledError:'))
    return dict(pid=worker.pid, match=match, exit_code=worker.process.poll(), failure=worker.failure,
                stderr_tail=worker.stderr_tail[-4096:], matching_worker_released=released,
                cleanup_task_completed=cleanup_done, owned_resources_reaped=reaped,
                expected_cancelled_request=cancelled,
                passed=released and reaped and ((worker.process.poll() == 0 and not worker.failure) or cancelled))


async def run(args):
    validate_options(args)
    mode = getattr(args, 'mode', 1); participants = q.MODES[mode][0]
    bot_slots = set(range(1, participants)); complete_match = mode == 1
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    root = (ROOT/'local').resolve()
    require(os.name == 'nt' and game.is_relative_to(root) and output.is_relative_to(root) and
            game != root and output != root and not game.is_relative_to(output) and not output.is_relative_to(game),
            'separate owned Windows game and ignored evidence directories required')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    helper = (game/'BattleAcesOffline.dll').read_bytes()
    require(digest(helper) == args.expected_helper_sha256 and MARKER in helper, 'exact scheduling-AI helper required')
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    pki_folder = output/'ephemeral-pki'; pki = generate_test_pki(pki_folder)
    audit, events, workers, wire = Audit(output), [], [], []
    states, bodies, raw_bodies, bot_bodies = defaultdict(dict), {}, {}, {}
    credentials = Store(); started = time.monotonic()
    clock = ctypes.WinDLL('kernel32').GetTickCount64; clock.restype = ctypes.c_ulonglong
    report = dict(passed=False, scope=__doc__, mode=mode, scheduling=args.scheduling, rtt_ms=args.rtt_ms,
                  frames=args.frames, state_audit=args.state_audit, helper_sha256=digest(helper),
                  source_sha256_at_start=source_hashes(), prediction=False)
    def observe(event, **fields):
        row = dict(event=event, observed_at=time.monotonic(), observed_perf_counter=time.perf_counter(),
                   probe_tick_ms=int(clock()), **fields)
        if event == 'public_queue_entered':
            entry = server.community.public.entries[fields['profile']]
            row.update(queue_started_at=entry.entered, queue_deadline=entry.deadline)
        elif event == 'public_match_offered':
            public = server.community.public
            # Offer.deadline is set from maintain()'s actual decision clock.
            row['queue_decision_at'] = public.offers[fields['match']].deadline-public.offer_timeout
        if event == 'frame_queued':
            room = server.rooms[fields['room']]
            row.update(command_scheduling=room.command_scheduling, human_slots=sorted(room.peers), bot_slots=sorted(room.bots))
            states[room.match_id][fields['frame']] = state_digest(room.sim.last_state)
        events.append(row); audit(event, **{key:value for key,value in row.items() if key != 'event'})
    async def factory(data, bots=None):
        require(bots and set(bots) == bot_slots, 'authoritative native AI roster differs')
        worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output, ai=AISetup(assets, bots))
        workers.append(worker); original = worker.bot_inputs
        async def witnessed_bots(frame):
            value = await original(frame)
            room = next(room for room in server.rooms.values() if room.sim is worker)
            require(set(value) == bot_slots, 'native AI input slot differs')
            for slot, body in value.items():
                key = room.match_id, frame, slot
                require(key not in bot_bodies, 'native AI frame input requested twice')
                bot_bodies[key] = body
            return value
        worker.bot_inputs = witnessed_bots
        return worker
    templates = {key:GameTemplate.load(assets/name, catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
                 for key,name in ((1,'map-1v1.pb.gz'),(2,'map-2v2.pb.gz'),(5,'map-2vai.pb.gz'))}
    template = templates[1]
    cosmetics = CosmeticCatalog(assets)
    server = DedicatedServer(template, ProfileStore(output/'profiles', template, catalog=cosmetics),
        templates=templates, bot_catalog=BotCatalog(assets, template=template, rules=RuleBook(assets)),
        sim_factory=factory, ai_factory=factory, audit=observe, data_dir=output, audit_state=args.state_audit,
        input_timeout=30, experimental_command_scheduling=True,
        tls_context=tls.load_server_context(pki['cert'], pki['key']), admission=admission.AdmissionController(credentials))
    original_message, original_accept, original_seal = Room.on_message, command_wire.ArrivalScheduler.accept, command_wire.ArrivalScheduler.seal
    async def witnessed_message(room, peer, kind, payload):
        result = await original_message(room, peer, kind, payload)
        if room.server is server and kind in (p.INPUT, command_wire.BATCH, command_wire.HEARTBEAT, command_wire.READY):
            observe('probe_client_message', match=room.match_id, kind=kind, slot=peer.slot)
            if kind == command_wire.BATCH:
                match, sequence, body = command_wire.decode_batch(payload); raw_bodies[(match, peer.slot, sequence)] = body
        return result
    def witnessed_accept(scheduler, slot, sequence, body):
        value = original_accept(scheduler, slot, sequence, body)
        room = next((room for room in server.rooms.values() if room.command_scheduler is scheduler), None)
        if room is not None: bodies[(room.match_id, slot, sequence)] = value.body
        return value
    def witnessed_seal(scheduler, frame):
        value = original_seal(scheduler, frame)
        if value is not None and frame in (0, 1):
            room = next(room for room in server.rooms.values() if room.command_scheduler is scheduler)
            observe('probe_command_frame_sealed', match=room.match_id, frame=frame)
        return value
    process = job = parent = child = writer = task = shaper = trace = None
    log = ''; launch_tick = None; cleanup_errors = []
    try:
        port = (await server.start('127.0.0.1', 0))[1]
        shaper = StreamShaper(port, rtt_ms=args.rtt_ms, seed=117); delayed_port = await shaper.start()
        context = tls.load_client_context(pki['ca'], 'localhost')
        async def resolve(): return bridge.Remote('127.0.0.1', delayed_port, context, credentials.player, credentials.token)
        config = dict(game_directory=game, server_host='127.0.0.1', server_port=delayed_port,
                      display_name='Scheduling AI Probe', room='community', fullscreen=False,
                      local_profile='sched_ai_'+secrets.token_hex(8), solo_ai_host='server')
        options = client.player_options(original_command_scheduling_experimental=args.scheduling == 'arrival')
        parent, child = socket.socketpair(socket.AF_INET); parent.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=parent)
        command = launcher.game_arguments(config, None, child.fileno(), options)
        require(('-buffered-input-experimental' in command) == (args.scheduling == 'buffered') and
                ('-original-command-scheduling-experimental' in command) == (args.scheduling == 'arrival'),
                'requested native scheduling control differs from generated launch')
        command[command.index('-logFile')+1] = str(output/'game.log')
        command += diagnostic_arguments(args.frames, mode)
        if args.state_audit: command += ['-lan-audit']
        startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
        startup.lpAttributeList = {'handle_list':[child.fileno()]}
        with mock.patch.object(Room, 'on_message', witnessed_message), mock.patch.object(command_wire.ArrivalScheduler, 'accept', witnessed_accept), mock.patch.object(command_wire.ArrivalScheduler, 'seal', witnessed_seal):
            launch_tick = int(clock()); child.set_inheritable(True)
            try:
                process = subprocess.Popen(command, cwd=game, startupinfo=startup, close_fds=True,
                                           creationflags=subprocess.CREATE_NO_WINDOW | 4)
            finally: child.set_inheritable(False); child.close(); child = None
            job = _WindowsJob(process.pid)
            trace = game/'investigation/runtime'/f'frame-timing-{process.pid}.tsv'
            require(not trace.exists(), 'refusing reused native timing artifact')
            resume = ctypes.WinDLL('ntdll').NtResumeProcess
            resume.argtypes = [ctypes.c_void_p]; resume.restype = ctypes.c_long
            require(resume(process._handle) == 0, 'owned suspended process resume failed')
            report.update(pid=process.pid, launch_tick=launch_tick, created_suspended=True,
                          job_assigned_before_resume=True, arguments=command)
            (output/'process.json').write_text(json.dumps(report, indent=2)+'\n')
            task = asyncio.create_task(PublicBridge(reader, writer, resolve, version=2, evidence=wire, mode=mode).run())
            while True:
                require(process.poll() is None and not task.done(), 'owned client or bridge exited before result/Continue')
                log = await asyncio.to_thread(read_native_log, game, process.pid, since_tick=launch_tick)
                for failure in ('Public client failure:', 'Offline loop stopped in ', 'Client lifecycle invariant failed:',
                                'Frame timing capture stopped:', 'Original command scheduling failed:', 'LAN audit disabled:'):
                    require(failure not in log, 'native failure: '+failure)
                require(not any(row['event'] in ('protocol_error', 'match_aborted', 'public_match_setup_error') for row in events),
                        'authority reported a protocol or match failure')
                if trace.exists() and (not complete_match or RETURNED in log): break
                require(time.monotonic()-started < args.timeout, 'bounded native server-AI deadline reached')
                await asyncio.sleep(.2)
            created = [row for row in events if row['event'] == 'match_created']
            require(len(created) == 1 and len(workers) == 1, 'exactly one public AI match required')
            match = created[0]['match']
            completed = [row for row in events if row['event'] == 'match_completed' and row.get('match') == match]
            require(len(completed) == 1 if complete_match else not completed, 'completed result scope differs')
            report['human_search'] = human_search_deadline(match, events, log, mode)
            require(f'PUBLIC QUEUE SMOKE original OnMapSelected: mode={mode}' in log and 'owner=remote' in log and
                    'owner=local-practice' not in log and 'Practice requested:' not in log and
                    (not complete_match or 'Public native return:' in log and 'owner=remote nativeIdle=1' in log),
                    'original public server-AI route not exercised')
            for room in server.rooms.values():
                if room.history: room.history.flush()
            journal = read_journal(output, match, args.frames, participants)
            queued = [row for row in events if row['event'] == 'frame_queued' and row.get('match') == match and row['frame'] < args.frames]
            require([row['frame'] for row in queued] == list(range(args.frames)) and all(
                row['command_scheduling'] == (args.scheduling == 'arrival') and row['human_slots'] == [0] and row['bot_slots'] == sorted(bot_slots) for row in queued),
                'actual scheduling mode, roster or authority prefix differs')
            delivered = [row for row in wire if row['match'] == match and row['frame'] < args.frames]
            require([row['frame'] for row in delivered] == list(range(args.frames)) and all(
                row['payload_sha256'] == queued[row['frame']]['frame_payload_sha256'] for row in delivered),
                'native bridge did not receive exact contiguous authority frames')
            rows = prefix_trace(frame_timing.read_trace(trace), args.frames)
            timing = frame_timing.qualify(rows, [args.frames], max_skips=0, max_p95_ms=80, min_hz=19, max_hz=21,
                                         max_short_gaps=0, max_gap_ms=100)
            report['timing'] = timing
            require(timing['passed'] or args.state_audit, 'native smoothness gate failed: '+repr(timing['errors']))
            require([row['frame'] for row in rows if row['event'] == 'apply'] == list(range(args.frames)),
                    'actual native application prefix incomplete')
            builds = native_builds(log); require(len(builds) == 1, 'original queued build missing/repeated')
            queued_tick, smoke_frame, slot, ability = map(int, builds[0]); require(slot == 0, 'wrong human build owner')
            executed = build_frames(journal, slot, ability); require(len(executed) == 1, 'native build lacks one canonical execution')
            applied = {row['frame']:row['ms'] for row in rows if row['event'] == 'apply'}
            published = {row['frame']:row['ms'] for row in rows if row['event'] == 'publication'}
            frame = executed[0][0]; require(frame in applied and frame in published, 'command result not published')
            report.update(match=match, timing=timing, ai=ai_conservation(match, journal, bot_bodies),
                          worker_ms=summary([row['worker_ms'] for row in queued]),
                          real_queue_wait_seconds=report['human_search']['native_search_to_offer_ms']/1000,
                          queue_to_apply_ms=applied[frame]-queued_tick, queue_to_publication_ms=published[frame]-queued_tick,
                          command_latency_scope='one original native build queue sample; not physical click latency',
                          original_result_and_continue=complete_match, canonical_prefix_frames=args.frames,
                          human_playtest=False, native_quit_qualified=False)
            if args.scheduling == 'arrival':
                require(re.search(r'Original command scheduling negotiated: [^\r\n]*capability=2\b', log),
                        'AI capability negotiation absent')
                kinds = {row['kind'] for row in events if row['event'] == 'probe_client_message'}
                require(p.INPUT not in kinds and {command_wire.BATCH, command_wire.HEARTBEAT, command_wire.READY} <= kinds,
                        'arrival client used legacy input or omitted readiness/liveness')
                report.update(human=human_conservation(match, journal, events, bodies, raw_bodies, log, args.frames),
                              startup=solo_startup(match, events), first_output=first_output_ready(log, match, 0, rows, events))
            else:
                require('Original command scheduling negotiated:' not in log, 'buffered control negotiated arrival mode')
            if args.state_audit:
                import csv
                path = game/'investigation/runtime'/f'lan-audit-{process.pid}-{match}.tsv'
                with path.open(newline='', encoding='utf-8') as stream:
                    samples = {(int(row['frame']), int(row['viewer'])):row['canonical_fnv1a64'] for row in csv.DictReader(stream, delimiter='\t')}
                expected = {(row['frame'], row['viewer']):row['canonical_fnv1a64'] for row in events if row['event'] == 'native_snapshot' and row.get('match') == match and row['frame'] < args.frames}
                require(expected and expected.keys() <= samples.keys() and all(samples[key] == value for key,value in expected.items()),
                        'actual client snapshot differs from authority')
                shutil.copyfile(path, output/path.name)
                receipts = game/'investigation/runtime'/f'dedicated-receipts-{process.pid}-{match}.tsv'
                with receipts.open(newline='', encoding='utf-8') as stream:
                    native_receipts = list(csv.DictReader(stream, delimiter='\t'))
                authority = {row['frame']:row['frame_payload_sha256'] for row in events if row['event'] == 'frame_queued' and row.get('match') == match and
                             (complete_match or row['frame'] < args.frames)}
                if not complete_match: native_receipts = [row for row in native_receipts if int(row['frame']) < args.frames]
                require([int(row['frame']) for row in native_receipts] == list(range(len(authority))) and
                        all(row['sha256'] == authority[int(row['frame'])] for row in native_receipts),
                        'actual native applied bytes differ from authority')
                shutil.copyfile(receipts, output/receipts.name)
                report['native_state_comparisons'] = len(expected)
                report['native_receipt_comparisons'] = len(native_receipts)
            report['passed'] = True
    except BaseException as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if not complete_match and report['passed']:
            observe('probe_owned_team_prefix_teardown', match=report['match'], frames=args.frames,
                    healthy_worker_pids=[worker.pid for worker in workers
                                         if not worker.closed and worker.process.poll() is None and not worker.failure])
        if child is not None: child.close()
        if process is not None:
            await cleanup_step(cleanup_errors, 'owned client', lambda:stop_owned_process(process))
            await cleanup_step(cleanup_errors, 'native log', lambda:(output/f'native-{process.pid}.log').write_text(
                read_native_log(game, process.pid, since_tick=launch_tick), encoding='utf-8'))
        if job is not None: await cleanup_step(cleanup_errors, 'owned client Job', job.close)
        if task is not None:
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
        if writer is not None:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(), 2)
            except (OSError, TimeoutError): writer.transport.abort()
        elif parent is not None: parent.close()
        await cleanup_step(cleanup_errors, 'authority', lambda:asyncio.wait_for(server.close(), 30))
        for worker in workers: await cleanup_step(cleanup_errors, 'native worker', worker.close)
        if shaper is not None: await cleanup_step(cleanup_errors, 'stream shaper', shaper.close)
        if trace is not None and trace.exists(): await cleanup_step(cleanup_errors, 'timing trace', lambda:shutil.copyfile(trace, output/trace.name))
        await cleanup_step(cleanup_errors, 'ephemeral PKI', lambda:remove_test_pki(pki_folder))
        await cleanup_step(cleanup_errors, 'audit', audit.close)
        report.update(elapsed_seconds=time.monotonic()-started, events=events, cleanup_errors=cleanup_errors,
                      source_sha256_at_finish=source_hashes(), owned_process_reaped=process is None or process.poll() is not None,
                      worker_cleanup=[classify_worker_cleanup(worker, events, complete_match=complete_match) for worker in workers],
                      teardown='forced owned '+('menu termination after original result/Continue' if complete_match else 'team-match prefix termination')+'; native Quit unqualified')
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        clean_workers = all(row['passed'] for row in report['worker_cleanup'])
        if not clean_workers: report.setdefault('error', 'worker cleanup failed; see worker_cleanup')
        elif cleanup_errors or not report['owned_process_reaped']:
            report.setdefault('error', 'owned runtime cleanup failed; see cleanup_errors and owned_process_reaped')
        elif not report['source_files_unchanged']: report.setdefault('error', 'bound source files changed during verification')
        report['passed'] &= not cleanup_errors and report['owned_process_reaped'] and report['source_files_unchanged'] and clean_workers
        if report['passed']:
            try: report['authoritative_replay'] = await replay_check(assets, output, report['match'], states[report['match']], args.frames, participants)
            except BaseException as error: report.update(passed=False, replay_error=f'{type(error).__name__}: {error}')
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','error','replay_error','scheduling','rtt_ms','queue_to_apply_ms','queue_to_publication_ms','elapsed_seconds') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'assets', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--expected-helper-sha256', required=True)
    parser.add_argument('--scheduling', choices=('buffered','arrival'), required=True)
    parser.add_argument('--mode', type=int, choices=(1,2,5), default=1)
    parser.add_argument('--rtt-ms', type=float, default=475)
    parser.add_argument('--frames', type=int, default=600)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--state-audit', action='store_true', help='separate native state comparison; timing is observed but not qualified')
    return asyncio.run(run(parser.parse_args()))


if __name__ == '__main__': raise SystemExit(main())
