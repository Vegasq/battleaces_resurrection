"""Opt-in two-game TLS/rematch qualification with ephemeral test PKI/in-memory invites.

This is NOT a credential-store/ACL deployment test. No production invite is read,
printed, persisted or passed to either game. The supplied game must already have
the secure helper installed. Runtime evidence remains under ignored local/.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import time
from unittest import mock

from client_patch.transport import launcher
from client_patch.transport.bridge import Remote
from server.admission import AdmissionController
from server.assets import verify_assets
from server.credentials import AuthenticationError
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server import tls_transport as tls
from server import protocol as p
from server.worker_client import SimulationWorker
from server.verify_dedicated_run import verify
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools.stream_shaper import StreamShaper

ROOT = Path(__file__).resolve().parents[1]


def current_native_log(log):
    """Exclude append-only evidence from an earlier invocation with a reused PID."""
    start = log.rfind('Offline initial state reached after game initialization. PID=')
    return log[start:] if start >= 0 else ''


def read_native_log(game, pid):
    path = game / 'investigation/runtime' / ('dedicated-native-' + str(pid) + '.log')
    return current_native_log(path.read_text() if path.exists() else '')


def recovery_evidence(log, match, *, postgame=False):
    log = current_native_log(log)
    markers = dict(
        button_invoked='RECOVERY SMOKE invoking original disconnected modal OnConfirm',
        intent_queued='Dedicated Reconnect callback queued',
        returned_before_release='RECOVERY SMOKE original OnConfirm returned; modalStillOwned=1 queued=1',
        deferred_release='Dedicated retry modal released on later update')
    if postgame:
        markers['native_continue']='Dedicated postgame Reconnect invokes original OnContinue: match=' + match
    markers.update(
        reset_old_match='Dedicated session reset: match=' + match,
        explicit_unready_retry='Dedicated explicit retry opening fresh lobby; readyIntent=0',
        lobby_not_ready='RECOVERY SMOKE fresh lobby is not ready; invoking native Play')
    positions = [log.find(marker) for marker in markers.values()]
    result = {key: position >= 0 for key, position in zip(markers, positions)}
    result['ordered'] = all(a >= 0 and b > a for a,b in zip(positions,positions[1:]))
    queued = re.search(r'Dedicated Reconnect callback queued: update=(\d+) [^\n]*thenPlay=0', log)
    released = re.search(r'Dedicated retry modal released on later update: requested=(\d+) current=(\d+) [^\n]*worldIdle=1', log)
    result['later_update'] = bool(queued and released and
        int(queued[1]) == int(released[1]) < int(released[2]))
    result['new_match_waited_for_play'] = (result['ordered'] and not re.search(
        r'Dedicated session \d+ joined match=', log[positions[-2]:positions[-1]]))
    return result


def frame_timing(events, match):
    rows = [row for row in events if row.get('match') == match and row['event'] == 'frame_queued']
    times = [row['perf_counter_ns'] / 1e9 for row in rows]
    intervals = sorted((b-a)*1000 for a,b in zip(times,times[1:]))
    if not intervals: return None
    return dict(effective_hz=round((len(times)-1)/(times[-1]-times[0]),3),
        mean_ms=round(sum(intervals)/len(intervals),3), p95_ms=round(intervals[int((len(intervals)-1)*.95)],3),
        maximum_ms=round(intervals[-1],3),
        cadence_resets=sum(row['event']=='cadence_reset' and row.get('match')==match for row in events))


async def run(args):
    if os.name != 'nt': raise ValueError('Windows game runtime required')
    if not 60 <= args.duration <= 600: raise ValueError('duration must be60..600 seconds')
    if not __import__('re').fullmatch('[A-Za-z0-9_-]{1,48}', args.run_name): raise ValueError('invalid run name')
    game, assets = args.game.resolve(), args.assets.resolve()
    launcher.verify_game(game)
    verify_assets(assets)
    # Validate shaping before creating files or processes. Only the harness uses
    # this relay; production transport and certificate verification are unchanged.
    StreamShaper(1, rtt_ms=args.rtt_ms, jitter_ms=args.jitter_ms, seed=args.network_seed)
    p.validate_input_window(args.input_window)
    if args.disconnect_frame is not None and not 20 <= args.disconnect_frame < 500:
        raise ValueError('disconnect frame must be20..499')
    if args.disconnect_frame is not None and args.postgame_error:
        raise ValueError('choose one failure scenario per run')
    recovery_mode = args.disconnect_frame is not None or args.postgame_error
    destination = ROOT / 'local/matches' / args.run_name
    destination.mkdir(parents=True, exist_ok=False)
    pki = generate_test_pki(destination / 'ephemeral-test-pki')
    audit = Audit(destination)
    processes, tasks, records, completions, faults = [], [], [], [], []
    relay = None
    players = [('p_' + secrets.token_hex(16), 'ba1_' + secrets.token_urlsafe(32)) for _ in range(2)]
    class Store:
        def authenticate(self, token):
            for player, expected in players:
                if secrets.compare_digest(token, expected): return player
            raise AuthenticationError()
    class Gate(AdmissionController):
        async def authenticate(self, reader, writer):
            player = await super().authenticate(reader, writer)
            channel = writer.get_extra_info('ssl_object')
            row = dict(player=player, tls=channel.version(), cipher=channel.cipher()[0])
            records.append(row)
            audit('qualification_tls_authenticated', **row)
            return player
    def observe(event, **data):
        audit(event, **data)
        if event == 'match_completed': completions.append(data['match'])
        if (args.disconnect_frame is not None and not faults and event == 'frame_queued'
                and data['frame'] == args.disconnect_frame):
            room = coordinator.rooms[data['room']]
            fault = dict(match=room.match_id, frame=data['frame'], disconnected_slot=0)
            faults.append(fault)
            audit('qualification_abrupt_peer_disconnect', **fault)
            # Cut exactly one authenticated game stream without an application
            # error packet. Normal coordinator detach must abort the other peer.
            room.peers[0].writer.transport.abort()
    template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json',
                                 descriptors_path=assets / 'descriptors')
    coordinator = DedicatedServer(template, ProfileStore(destination / 'profiles', template),
        audit=observe, data_dir=destination, audit_state=True, input_window=args.input_window,
        sim_factory=lambda data: SimulationWorker.create(data, assets / 'Simulation.dll'),
        tls_context=tls.load_server_context(pki['cert'], pki['key']), admission=Gate(Store()))
    manifest = dict(RunName=args.run_name, Started=datetime.now(timezone.utc).isoformat(), ServerPid=os.getpid(),
                    GamePids=[], AutoReady=True, Smoke=True, DeckSmoke=True, SurrenderSmoke=True,
                    RematchSmoke=True, TelemetryAudit=True, Transport='verified-TLS-private-inherited-stream',
                    CredentialStorage='test-only-in-memory', GameDirectory=str(game),
                    GameProtocol=p.VERSION, InputWindow=args.input_window,
                    DisconnectFrame=args.disconnect_frame, RecoverySmoke=recovery_mode,
                    PostgameError=args.postgame_error)
    manifest_path = destination / 'processes.json'
    original_spawn = launcher.spawn_game
    def record_spawn(*positional, **keywords):
        process = original_spawn(*positional, **keywords)
        processes.append(process)
        manifest['GamePids'].append(process.pid)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        return process
    try:
        source_paths = sorted({path for pattern in ('server/*.py','client_patch/src/*.cpp',
            'client_patch/src/*.hpp','client_patch/transport/*.py','client_patch/patcher/*.py',
            'client_patch/build.ps1','tools/run_secure_match.py','tools/stream_shaper.py') for path in ROOT.glob(pattern)})
        (destination / 'source-sha256.json').write_text(json.dumps(dict(
            note='Working source digests captured before game launch; installed binaries are identified separately by patch-manifest.json.',
            files={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}),
            indent=2),encoding='utf-8')
        address = await coordinator.start('127.0.0.1', 0)
        route_port = address[1]
        if args.rtt_ms or args.jitter_ms:
            relay = StreamShaper(address[1], rtt_ms=args.rtt_ms, jitter_ms=args.jitter_ms, seed=args.network_seed)
            route_port = await relay.start()
        context = tls.load_client_context(pki['ca'], 'localhost')
        shutil.copyfile(game / '.battleaces-resurrection/patch-manifest.json', destination / 'patch-manifest.json')
        (destination / 'transport-test.json').write_text(json.dumps(dict(ca_sha256=hashlib.sha256(pki['ca'].read_bytes()).hexdigest(),
            server_port=address[1], route_port=route_port, rtt_ms=args.rtt_ms, jitter_ms=args.jitter_ms,
            network_seed=args.network_seed, input_window=args.input_window, game_protocol=p.VERSION,
            model='ordered stream delay; not packet loss or remote TCP',
            note='Ephemeral local test trust; not production credential storage'), indent=2), encoding='utf-8')
        options = argparse.Namespace(run_name=args.run_name, auto_ready=True, smoke=True, deck_smoke=True,
                                     surrender_smoke=True, rematch_smoke=True, telemetry_audit=True, audit=True,
                                     recovery_smoke=recovery_mode, postgame_recovery_smoke=args.postgame_error)
        with mock.patch.object(launcher, 'spawn_game', record_spawn):
            for index, (player, token) in enumerate(players):
                config = dict(game_directory=game, server_host='127.0.0.1', server_port=route_port,
                              display_name='TLS Player ' + str(index + 1), room='tls-rematch')
                tasks.append(asyncio.create_task(launcher.launch(config, Remote('127.0.0.1', route_port, context, player, token), options)))
            deadline = time.monotonic() + args.duration
            final_result_at = None
            while time.monotonic() < deadline and not any(task.done() for task in tasks):
                if args.postgame_error and completions and not faults and len(processes)==2:
                    match = completions[0]
                    marker = 'gate=continue-handler-ready'
                    # Wait for both actual native result states, inactive worlds
                    # and empty navigation; never inject merely on server finish.
                    if all(any(marker in line and ('match=' + match) in line
                               for line in read_native_log(game,process.pid).splitlines()) for process in processes):
                        room = next((room for room in coordinator.retired if room.match_id == match), None)
                        if room is not None and len(room.peers)==2:
                            fault = dict(match=match, phase='native-postgame', slots=sorted(room.peers))
                            faults.append(fault)
                            audit('qualification_postgame_error', **fault)
                            for peer in list(room.peers.values()):
                                peer.send(p.ERROR,b'Qualification: connection failed after completed result')
                if len(completions) >= (1 if args.disconnect_frame is not None else 2):
                    if final_result_at is None: final_result_at = time.monotonic()
                    if time.monotonic() - final_result_at >= 15: break
                await asyncio.sleep(.5)
    finally:
        # These exact Popen handles own only this harness's two test clients.
        # The user's separate visible test clients are never selected by name/PID.
        for process in processes:
            if process.poll() is None: process.terminate()
        await asyncio.gather(*(asyncio.to_thread(process.wait, timeout=10) for process in processes), return_exceptions=True)
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if relay is not None: await relay.close()
        await coordinator.close()
        audit.close()
        remove_test_pki(destination / 'ephemeral-test-pki')
    results = []
    events = [json.loads(line) for line in (destination / 'events.jsonl').read_text().splitlines()]
    for match in completions:
        result = verify(destination, game / 'investigation/runtime', manifest_path, match)
        (destination / ('verification-' + match + '.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        results.append(dict(match=match, status=result['status'], frames=result['server_frame_count'],
            mismatches=result['mismatch_count'], errors=result['server_errors'], timing=frame_timing(events, match),
            clients=[dict(pid=row['pid'],slot=row['slot'],samples=row['common_snapshot_samples'],
                          receipts=len(row['logged_received_frames']),sufficient=row['evidence_sufficient']) for row in result['clients']]))
    recovery = []
    if recovery_mode:
        for process in processes:
            recovery.append(dict(pid=process.pid, **recovery_evidence(read_native_log(game,process.pid),
                faults[0]['match'] if faults else '<no-fault>',postgame=args.postgame_error)))
    aborted = [row for row in events if row['event'] == 'match_aborted']
    fault_ok = (len(faults) == len(aborted) == 1 and aborted[0]['match'] == faults[0]['match']
        and aborted[0].get('result') is None and all(row['match'] != faults[0]['match'] for row in results)
        if args.disconnect_frame is not None else len(faults)==1 and not aborted
        and len(results)>=2 and results[0]['match']==faults[0]['match'] and results[1]['match']!=faults[0]['match'])
    recovery_ok = not recovery_mode or (fault_ok and len(recovery)==2
        and all(all(value for key,value in row.items() if key != 'pid') for row in recovery))
    summary = dict(matches=results, authenticated_sessions=records, faults=faults, recovery=recovery,
                   game_protocol=p.VERSION, input_window=args.input_window,
                   stream_delay=dict(rtt_ms=args.rtt_ms, jitter_ms=args.jitter_ms, seed=args.network_seed,
                                     relay_stats=relay.stats if relay else None),
                   success=len(results) >= (1 if args.disconnect_frame is not None else 2)
                       and len(records) >= 4 and recovery_ok
                       and all(row['status']=='matching_sampled_server_and_clients' for row in results))
    (destination / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)
    return not summary['success']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--run-name', required=True)
    parser.add_argument('--duration', type=int, default=150)
    parser.add_argument('--input-window', type=int, choices=range(p.MIN_INPUT_WINDOW, p.MAX_INPUT_WINDOW+1),
                        default=p.DEFAULT_INPUT_WINDOW)
    parser.add_argument('--rtt-ms', type=float, default=0, help='loopback ordered-stream round-trip delay,0..500ms')
    parser.add_argument('--jitter-ms', type=float, default=0, help='uniform +/- one-way delay variation,0..100ms')
    parser.add_argument('--network-seed', type=int, default=1)
    failure = parser.add_mutually_exclusive_group()
    failure.add_argument('--disconnect-frame', type=int,
                        help='test-only abrupt peer disconnect during the first match; require native button recovery')
    failure.add_argument('--postgame-error', action='store_true',
                         help='test-only ERROR after both native results; require Reconnect/Continue/new lobby')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
