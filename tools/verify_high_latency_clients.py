"""Two owned native clients over independent asymmetric delayed TLS streams.

Records accepted per-peer input arrivals, authoritative input waits, and native
arrival/application/presentation clocks. No production endpoints or processes
are used. Forced owned teardown does not qualify results or native Quit.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import ctypes
import gzip
import hashlib
import json
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

from client_patch.transport import bridge, launcher
from server import admission, protocol as p, tls_transport as tls
from server.assets import verify_assets
from server.ai_rules import RuleBook
from server.bot_catalog import BotCatalog
from server.cosmetics import CosmeticCatalog
from server.credentials import AuthenticationError
from server.dedicated_server import Audit, DedicatedServer, Room
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server.worker_client import SimulationWorker, _WindowsJob
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools import frame_timing
from tools.run_secure_match import read_native_log
from tools.stream_shaper import StreamShaper
from tools.verify_custom_lobby import require

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def state_digest(state):
    # The raw native buffer fingerprint includes bytes that can change after
    # diagnostic view queries. Compare every parsed state field instead.
    canonical = {key: value for key, value in state.items() if key != 'raw_sha256'}
    return digest(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode())


def summary(values):
    values = sorted(values)
    if not values:
        return dict(count=0)
    return dict(count=len(values), minimum=values[0], median=values[len(values)//2],
                p95=values[(len(values)-1)*95//100], maximum=values[-1])


def source_hashes():
    names = ('tools/verify_high_latency_clients.py', 'tools/stream_shaper.py',
             'tools/frame_timing.py', 'client_patch/src/lan_transport.cpp',
             'client_patch/src/online_presentation.cpp', 'client_patch/src/online_frame_clock.hpp',
             'client_patch/transport/launcher.py', 'client_patch/transport/bridge.py',
             'server/dedicated_server.py', 'server/protocol.py', 'server/tls_transport.py',
             'server/latency_policy.py', 'server/community.py', 'server/public_matchmaking.py')
    return {name: digest((ROOT/name).read_bytes()) for name in names}


def prefix_trace(rows, frames):
    return [row for row in rows if (row['event'] == 'view' and row['presented'] < frames) or
            (row['event'] != 'view' and row['frame'] < frames)]


async def replay_check(assets, output, match, expected, frames):
    """Compare delayed authority with a fresh unpaced worker on identical bytes."""
    folder = output/'matches'/match
    worker = await SimulationWorker.create(gzip.decompress((folder/'bootstrap.pb.gz').read_bytes()),
                                           assets/'Simulation.dll', working_directory=output)
    checked = 0
    try:
        with (folder/'frames.bin').open('rb') as stream:
            for frame in range(frames):
                header = stream.read(4)
                require(len(header) == 4, 'authoritative journal is incomplete')
                size, = struct.unpack('<I', header)
                require(0 < size <= p.MAX_INPUT*2+1024, 'unbounded journal frame')
                body = stream.read(size)
                require(len(body) == size, 'truncated journal input')
                result = await worker.process_frame(body, dt_ms=50)
                require(result.frame == frame and state_digest(result.state) == expected[frame],
                        f'unpaced replay state differs at frame{frame}')
                checked += 1
    finally:
        await worker.close()
    require(worker.process.poll() == 0 and not worker.failure, 'replay worker did not close cleanly')
    return dict(passed=True, frames=checked, exit_code=worker.process.poll(),
                scope='same authoritative bootstrap/input bytes; normalized observable worker state, not hidden state')


async def run(args):
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(os.name == 'nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'),
            'only an owned Windows game and ignored evidence directory are permitted')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    helper_hash = digest((game/'BattleAcesOffline.dll').read_bytes())
    require(helper_hash == args.expected_helper_sha256, 'owned helper is not the exact requested binary')
    p.validate_input_window(args.input_window)
    verify_assets(assets)
    output.mkdir(exist_ok=False, parents=True)
    pki_folder = output/'ephemeral-pki'
    pki = generate_test_pki(pki_folder)
    audit, events, workers, clients, shapers = Audit(output), [], [], [], []
    identities = [('p_'+secrets.token_hex(16), 'ba1_'+secrets.token_urlsafe(32)) for _ in range(2)]
    clock = ctypes.WinDLL('kernel32').GetTickCount64
    clock.restype = ctypes.c_ulonglong
    canonical_states = {}
    started = time.monotonic()
    runtime = game/'investigation/runtime'
    gate = runtime/('public-queue-'+secrets.token_hex(16)+'.ready')
    gate_opened = False
    class Store:
        def authenticate(self, token):
            for player, expected in identities:
                if secrets.compare_digest(token, expected):
                    return player
            raise AuthenticationError()
    def observe(event, **fields):
        row = dict(event=event, probe_tick_ms=int(clock()), observed_at=time.monotonic(), **fields)
        if event == 'frame_queued':
            room = server.rooms[fields['room']]
            row['peer_next_inputs'] = {slot: peer.next_input for slot, peer in room.peers.items()}
            row['pending_by_slot'] = {slot: sum(slot in value for value in room.pending.values()) for slot in room.peers}
            row['input_window'] = room.input_window
            row['input_windows'] = dict(getattr(room, 'input_windows',
                                       {slot: room.input_window for slot in room.peers}))
            canonical_states[fields['frame']] = state_digest(room.sim.last_state)
        events.append(row)
        audit(event, **{key: value for key, value in row.items() if key != 'event'})
    async def factory(data):
        worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output)
        workers.append(worker)
        return worker
    async def unexpected_ai_worker(data, bots):
        raise AssertionError('two-human high-latency proof must not allocate AI')
    template = GameTemplate.load(assets/'map-1v1.pb.gz', catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
    cosmetics = CosmeticCatalog(assets)
    bot_catalog = BotCatalog(assets, template=template, rules=RuleBook(assets))
    server = DedicatedServer(template, ProfileStore(output/'profiles', template, catalog=cosmetics),
        templates={1: template}, sim_factory=factory, ai_factory=unexpected_ai_worker, bot_catalog=bot_catalog,
        audit=observe, data_dir=output,
        audit_state=args.state_audit, input_window=args.input_window, input_timeout=30,
        adaptive_input_window=args.policy == 'adaptive',
        tls_context=tls.load_server_context(pki['cert'], pki['key']), admission=admission.AdmissionController(Store()))
    report = dict(passed=False, scope=__doc__, helper_sha256=helper_hash,
                  source_sha256_at_start=source_hashes(), input_window=args.input_window,
                  rtt_ms=args.rtt_ms, target_frames=args.frames, state_audit=args.state_audit, policy=args.policy,
                  expected_peer_windows=args.expected_peer_windows,
                  state_digest_scope='all parsed worker state fields except raw_sha256 (raw native buffer fingerprint)',
                  delay_model='ordered independent stream delay, end-to-end verified TLS; no packet loss or remote TCP model')
    original_message = Room.on_message
    async def witnessed_message(room, peer, kind, payload):
        if room.server is not server or kind != p.INPUT:
            return await original_message(room, peer, kind, payload)
        frame, = struct.unpack_from('<I', payload)
        tick = int(clock())
        result = await original_message(room, peer, kind, payload)
        observe('probe_input_accepted', match=room.match_id, slot=peer.slot, frame=frame,
                received_tick_ms=tick, server_frame=room.frame, next_input=peer.next_input,
                present_slots=sorted(room.pending.get(frame, {})),
                missing_slots=sorted(set(room.peers)-set(room.pending.get(frame, {}))))
        return result
    try:
        port = (await server.start('127.0.0.1', 0))[1]
        context = tls.load_client_context(pki['ca'], 'localhost')
        shutil.copyfile(game/'.battleaces-resurrection/patch-manifest.json', output/'patch-manifest.json')
        with mock.patch.object(Room, 'on_message', witnessed_message):
            for index in range(2):
                shaper = StreamShaper(port, rtt_ms=args.rtt_ms[index], jitter_ms=0, seed=71+index)
                shapers.append(shaper)
                delayed_port = await shaper.start()
                parent, child = socket.socketpair(socket.AF_INET)
                parent.setblocking(False)
                reader, writer = await asyncio.open_connection(sock=parent)
                record = dict(index=index, writer=writer, parent=parent, child=child, log='')
                clients.append(record)
                async def resolve(index=index, delayed_port=delayed_port):
                    return bridge.Remote('127.0.0.1', delayed_port, context, *identities[index])
                config = dict(game_directory=game, server_host='127.0.0.1', server_port=delayed_port,
                    display_name=f'High latency probe {index+1}', room='community', fullscreen=False,
                    local_profile='latency_'+secrets.token_hex(8), solo_ai_host='server')
                options = argparse.Namespace(run_name=f'high-latency-{index}', unified_experimental=True, player_features=True)
                command = launcher.game_arguments(config, None, child.fileno(), options)
                command[command.index('-logFile')+1] = str(output/f'game-{index}.log')
                command += ['-public-queue-smoke', '-public-queue-smoke-mode=1',
                    '-public-queue-smoke-gate='+gate.stem.removeprefix('public-queue-'), '-lan-smoke',
                    '-dedicated-rematch-smoke', '-frame-timing', f'-frame-timing-frames={args.frames}']
                if args.state_audit:
                    command += ['-lan-audit']
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 0
                startup.lpAttributeList = {'handle_list': [child.fileno()]}
                record['tick'] = int(clock())
                child.set_inheritable(True)
                try:
                    record['process'] = subprocess.Popen(command, cwd=game, startupinfo=startup, close_fds=True,
                                                        creationflags=subprocess.CREATE_NO_WINDOW)
                finally:
                    child.set_inheritable(False)
                    child.close()
                record['job'] = _WindowsJob(record['process'].pid)
                record['task'] = asyncio.create_task(bridge.Bridge(reader, writer, resolve, version=2).run())
                record['trace'] = runtime/f'frame-timing-{record["process"].pid}.tsv'
                require(not record['trace'].exists(), 'timing evidence already exists for reused PID')
                (output/'processes.json').write_text(json.dumps(dict(helper_sha256=helper_hash,
                    clients=[dict(index=row['index'], pid=row['process'].pid, launch_tick=row['tick']) for row in clients]), indent=2)+'\n')
            while True:
                for row in clients:
                    require(row['process'].poll() is None and not row['task'].done(), 'owned client/bridge exited early')
                    row['log'] = await asyncio.to_thread(read_native_log, game, row['process'].pid, since_tick=row['tick'])
                    for failure in ('Offline loop stopped in ', 'Public client failure:', 'Client lifecycle invariant failed:', 'LAN audit disabled:', 'Frame timing capture stopped:'):
                        require(failure not in row['log'], 'native high-latency failure: '+failure)
                require(not any(row['event'] in ('protocol_error', 'match_aborted') for row in events), 'local authoritative match failed')
                if not gate_opened and all('PUBLIC QUEUE SMOKE waiting for shared gate:' in row['log'] for row in clients):
                    with gate.open('xb'):
                        pass
                    gate_opened = True
                    observe('probe_shared_gate_released')
                if all(row['trace'].exists() for row in clients):
                    await asyncio.sleep(1)
                    break
                require(time.monotonic()-started < args.timeout, 'bounded high-latency deadline reached')
                await asyncio.sleep(.25)
            require(gate_opened and len(workers) == 1, 'clients did not share one authoritative worker')
            offers = [row for row in events if row['event'] == 'public_match_offered']
            require(len(offers) == 1 and len(offers[0]['humans']) == 2, 'two humans did not share one offer')
            match = offers[0]['match']
            queued = [row for row in events if row['event'] == 'frame_queued' and row['frame'] < args.frames]
            require([row['frame'] for row in queued] == list(range(args.frames)), 'incomplete canonical prefix')
            elapsed = queued[-1]['observed_at']-queued[0]['observed_at']
            report['authority'] = dict(match=match, frames=len(queued), effective_hz=(args.frames-1)/elapsed,
                frozen_input_window=queued[0]['input_window'],
                frozen_input_windows=queued[0]['input_windows'],
                input_wait_ms=summary([row['input_wait_ms'] for row in queued]),
                waits_over_100=sum(row['input_wait_ms'] > 100 for row in queued),
                waits_over_200=sum(row['input_wait_ms'] > 200 for row in queued),
                worker_ms=summary([row['worker_ms'] for row in queued]))
            accepted = [row for row in events if row['event'] == 'probe_input_accepted' and row['frame'] < args.frames]
            ready = {frame: [row for row in accepted if row['frame'] == frame] for frame in range(args.frames)}
            require(all(len(rows) == 2 and {row['slot'] for row in rows} == {0, 1} for rows in ready.values()),
                    'accepted per-peer input coverage differs from canonical prefix')
            report['input_readiness'] = dict(
                ready_span_ms=summary([max(row['received_tick_ms'] for row in rows)-min(row['received_tick_ms'] for row in rows)
                                       for rows in ready.values()]),
                last_input_slot_counts={slot: sum(max(rows, key=lambda row: row['received_tick_ms'])['slot'] == slot
                                                 for rows in ready.values()) for slot in (0, 1)},
                window_events=[row for row in events if row['event'] == 'input_window_selected'])
            report['clients'] = []
            for row in clients:
                data = prefix_trace(frame_timing.read_trace(row['trace']), args.frames)
                measured = frame_timing.measure(data)
                require(measured['first_arrived'] == measured['first_applied'] == 0 and
                        measured['last_arrived'] == measured['last_applied'] == args.frames-1 and
                        measured['arrival_frames'] == measured['applied_frames'] == args.frames,
                        'native client did not receive/apply every canonical prefix frame')
                applied = {value['frame']: value['ms'] for value in data if value['event'] == 'apply'}
                submitted = [(int(tick), int(frame), int(actions)) for tick, frame, actions in re.findall(
                    r'\[(\d+)\] LAN submitted frame (\d+) with (\d+) local actions', row['log'])]
                delays = [dict(frame=frame, actions=actions, submit_to_apply_ms=applied[frame]-tick)
                          for tick, frame, actions in submitted if frame in applied]
                builds = re.findall(r'\[(\d+)\] LAN NORMAL BUILD smoke frame(\d+) [^\r\n]+', row['log'])
                require(len(builds) == 1 and int(builds[0][1]) in applied and
                        'queued=1 commandQueueDelta=1' in row['log'], 'original native build command was not exercised')
                build_tick, build_frame = map(int, builds[0])
                assignment = re.search(r'Public match assignment: [^\r\n]* inputWindow=(\d+)', row['log'])
                seat = re.search(r'Public match assignment: [^\r\n]* seat=(\d+)', row['log'])
                require(assignment is not None and seat is not None, 'native negotiated input window/seat is missing')
                require(queued[0]['input_windows'][int(seat[1])] == int(assignment[1]),
                        'native assignment differs from its frozen peer window')
                if args.expected_peer_windows is not None:
                    require(int(assignment[1]) == args.expected_peer_windows[row['index']],
                            'native negotiated peer window differs from the requested expectation')
                report['clients'].append(dict(index=row['index'], pid=row['process'].pid, rtt_ms=args.rtt_ms[row['index']],
                    assigned_input_window=int(assignment[1]), seat=int(seat[1]),
                    command_delays=delays, build_frame=build_frame,
                    build_enqueue_to_apply_ms=applied[build_frame]-build_tick,
                    submit_to_apply_ms=summary([value['submit_to_apply_ms'] for value in delays if value['frame'] > 0]),
                    latency_scope='original queued build/submission to native input application, not click-to-presentation RTT',
                    **measured))
            if args.state_audit:
                expected = {(row['frame'], row['viewer']): row['canonical_fnv1a64'] for row in events
                            if row['event'] == 'native_snapshot' and row['frame'] < args.frames}
                comparisons = []
                for row in clients:
                    path = runtime/f'lan-audit-{row["process"].pid}-{match}.tsv'
                    with path.open(newline='', encoding='utf-8') as stream:
                        samples = {(int(value['frame']), int(value['viewer'])): value['canonical_fnv1a64']
                                   for value in csv.DictReader(stream, delimiter='\t')}
                    common = expected.keys() & samples.keys()
                    require(len(common) >= args.frames//20 and all(samples[key] == expected[key] for key in common),
                            'sampled native client state differs from authoritative native snapshots')
                    shutil.copyfile(path, output/path.name)
                    comparisons.append(dict(pid=row['process'].pid, comparisons=len(common), passed=True))
                report['native_sampled_state_equivalence'] = comparisons
            if args.expect_starvation:
                require(report['authority']['effective_hz'] < 17 and report['authority']['waits_over_100'] > 10,
                        'expected six-frame high-latency starvation was not reproduced')
            if args.require_smooth:
                require(all(19 <= row['effective_presented_hz'] <= 21 and row['skipped_presented_frames'] == 0 and
                            row['gaps_under_25_ms'] == 0 and row['gaps_over_100_ms'] == 0 and
                            row['p95_gap_ms'] <= 80 for row in report['clients']),
                        'candidate missed unchanged native 20Hz/no-skip/no-burst/no-pause gates')
            require(all(worker.process.poll() is None and not worker.failure for worker in workers),
                    'authoritative worker failed during the native prefix')
            report['passed'] = True
    except BaseException as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if report['passed']:
            # Observations are complete. Stop admitting new work in this owned
            # fixture before closing its clients, then let any IPC request drain.
            # This is forced prefix teardown, not a native completed-game result.
            for room in server.rooms.values():
                if room.state == 'running':
                    room.state = 'completed'
            drain_deadline = time.monotonic()+3
            while any(worker._lock.locked() for worker in workers) and time.monotonic() < drain_deadline:
                await asyncio.sleep(.005)
            report['owned_worker_requests_drained'] = not any(worker._lock.locked() for worker in workers)
        for row in clients:
            process = row.get('process')
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                await asyncio.to_thread(process.wait, timeout=15)
                (output/f'native-{process.pid}.log').write_text(read_native_log(game, process.pid, since_tick=row['tick']), encoding='utf-8')
            if row.get('job'):
                row['job'].close()
            if row.get('task'):
                row['task'].cancel()
            row['child'].close()
        await asyncio.gather(*(row['task'] for row in clients if row.get('task')), return_exceptions=True)
        for row in clients:
            row['writer'].close()
            try:
                await asyncio.wait_for(row['writer'].wait_closed(), 2)
            except (OSError, TimeoutError):
                row['writer'].transport.abort()
        await server.close()
        await asyncio.gather(*(worker.close() for worker in workers))
        for shaper in shapers:
            await shaper.close()
        for row in clients:
            if row.get('trace') and row['trace'].exists():
                shutil.copyfile(row['trace'], output/row['trace'].name)
        if gate_opened:
            gate.unlink()
        remove_test_pki(pki_folder)
        audit.close()
        report.update(elapsed_seconds=time.monotonic()-started, source_sha256_at_finish=source_hashes(),
            owned_processes_reaped=all(row.get('process') is None or row['process'].poll() is not None for row in clients),
            worker_cleanup=[dict(pid=worker.pid, exit_code=worker.process.poll(), failure=worker.failure,
                reaped=worker.process.poll() is not None and worker._cleanup_task is not None and
                       worker._cleanup_task.done() and not worker._stderr_thread.is_alive()) for worker in workers],
            shapers=[dict(rtt_ms=args.rtt_ms[index], **shaper.stats) for index, shaper in enumerate(shapers)],
            teardown='forced owned test termination; no normal Quit/result claim')
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['owned_processes_reaped'] and report['source_files_unchanged'] and all(
            row['reaped'] for row in report['worker_cleanup'])
        if report['passed']:
            try:
                report['authoritative_replay'] = await replay_check(assets, output, report['authority']['match'], canonical_states, args.frames)
            except BaseException as error:
                report.update(passed=False, replay_error=f'{type(error).__name__}: {error}')
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'replay_error', 'authority', 'clients', 'elapsed_seconds') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'assets', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--expected-helper-sha256', required=True)
    parser.add_argument('--rtt-ms', type=float, nargs=2, default=(130, 425))
    parser.add_argument('--input-window', type=int, default=6)
    parser.add_argument('--expected-peer-windows', type=int, nargs=2)
    parser.add_argument('--policy', choices=('fixed', 'adaptive'), default='fixed')
    parser.add_argument('--frames', type=int, default=600)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--state-audit', action='store_true')
    parser.add_argument('--expect-starvation', action='store_true')
    parser.add_argument('--require-smooth', action='store_true')
    args = parser.parse_args()
    require(600 <= args.frames <= 1800 and 90 <= args.timeout <= 360, 'bounded native prefix required')
    require(re.fullmatch('[a-f0-9]{64}', args.expected_helper_sha256) is not None, 'exact helper SHA256 required')
    require(not (args.expect_starvation and args.require_smooth), 'choose baseline or candidate expectation')
    for rtt in args.rtt_ms:
        StreamShaper(1, rtt_ms=rtt)
    if args.expected_peer_windows is not None:
        for window in args.expected_peer_windows:
            p.validate_input_window(window)
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
