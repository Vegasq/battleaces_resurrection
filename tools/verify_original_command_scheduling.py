"""Owned Custom clients compare buffered inputs with arrival-sealed commands.

Uses loopback TLS, independent ordered stream delays and the original native
Create/Invite/Accept/Start/build/Continue callbacks. No production endpoint,
shared user profile or user-owned process is used. Prefix teardown is forced;
even --rematch does not qualify manual input, visual acceptance or native Quit.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import csv
import ctypes
import json
import inspect
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
from server import admission, command_scheduling as command_wire, protocol as p, tls_transport as tls
from server.assets import verify_assets
from server.cosmetics import CosmeticCatalog
from server.credentials import AuthenticationError
from server.dedicated_server import Audit, DedicatedServer, Room
from server.game_data import GameTemplate, decode_frame, decode_player_input
from server.profiles import ProfileStore
from server.protobuf_wire import get_repeated_bytes, get_uint, parse_fields
from server.worker_client import SimulationWorker, _WindowsJob
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools import frame_timing
from tools.run_secure_match import read_native_log
from tools.stream_shaper import StreamShaper
from tools.verify_custom_lobby import require
from tools.verify_high_latency_clients import digest, prefix_trace, replay_check, source_hashes as core_hashes, state_digest, summary

ROOT = Path(__file__).resolve().parents[1]
PASSED = 'COMMUNITY MATCH SMOKE passed: two native Start/result/Continue cycles; same lobby, presence retained, seat=-1'
MARKER = b'BA_RESURRECTION_ORIGINAL_COMMAND_SCHEDULING_V1'


def source_hashes():
    names = ('tools/verify_original_command_scheduling.py', 'server/command_scheduling.py',
             'client_patch/src/lan_smoke.cpp', 'client_patch/src/community_match.cpp',
             'client_patch/src/original_command_scheduling.hpp')
    return core_hashes() | {name: digest((ROOT/name).read_bytes()) for name in names}


async def cleanup_step(errors, label, operation):
    """A failed teardown step must not skip other retained resources or evidence."""
    try:
        result = operation()
        if inspect.isawaitable(result):
            await result
    except Exception as error:
        errors.append(dict(step=label,error=f'{type(error).__name__}: {error}'))


async def stop_owned_process(process, timeout=15):
    failures = []
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        except Exception as error:
            failures.append(f'terminate: {type(error).__name__}: {error}')
    try:
        await asyncio.to_thread(process.wait,timeout=timeout)
    except Exception as error:
        failures.append(f'wait: {type(error).__name__}: {error}')
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except Exception as kill_error:
                failures.append(f'kill: {type(kill_error).__name__}: {kill_error}')
        try:
            await asyncio.to_thread(process.wait,timeout=timeout)
        except Exception as final_error:
            failures.append(f'final wait: {type(final_error).__name__}: {final_error}')
    if failures:
        raise RuntimeError('; '.join(failures))


class ObservedBridge(bridge.Bridge):
    """Hash decoded game FRAME payloads before the existing private handoff.

    TLS authentication and the actual native transport remain unchanged. This
    observes bytes delivered to the private bridge, not native world state.
    Native arrival/application counters separately prove complete consumption.
    """
    def __init__(self, *args, evidence, tick, **kwargs):
        super().__init__(*args, **kwargs)
        self.evidence, self.tick = evidence, tick
        self.buffers, self.matches = defaultdict(bytearray), {}

    async def send(self, kind, identity, data=b''):
        if kind == bridge.DATA:
            pending = self.buffers[identity]
            pending.extend(data)
            while len(pending) >= 4:
                length, = struct.unpack_from('<I', pending)
                require(1 <= length <= p.MAX_BODY, 'invalid observed game packet length')
                if len(pending) < length + 4:
                    break
                packet, body = pending[4], bytes(pending[5:length+4])
                del pending[:length+4]
                if packet == p.MATCH_INFO:
                    require(re.fullmatch(b'[a-f0-9]{32}', body) is not None, 'invalid observed Custom match ID')
                    self.matches[identity] = body.decode('ascii')
                elif packet == p.FRAME:
                    require(identity in self.matches and len(body) >= 8, 'frame precedes Custom assignment')
                    frame, = struct.unpack_from('<I', body)
                    self.evidence.append(dict(match=self.matches[identity], frame=frame,
                                              payload_sha256=digest(body), received_tick_ms=self.tick()))
        await super().send(kind, identity, data)


def read_journal(output, match, frames):
    result = []
    with (output/'matches'/match/'frames.bin').open('rb') as stream:
        for expected in range(frames):
            header = stream.read(4)
            require(len(header) == 4, 'incomplete authoritative input journal')
            length, = struct.unpack('<I', header)
            require(0 < length <= 2*p.MAX_INPUT+1024, 'journal frame exceeds two-human bound')
            raw = stream.read(length)
            require(len(raw) == length, 'truncated authoritative input journal')
            frame = decode_frame(raw)
            require(frame['frame'] == expected and frame['timestep_ms'] == 50 and
                    frame['frames_per_second'] == 20 and frame['speed'] == 1,
                    'canonical input frame/timing contract differs')
            players = {0: (), 1: ()}
            for body in frame['players']:
                value = decode_player_input(body)
                slot = value['identity']['player_id']-1
                require(slot in players and not players[slot], 'duplicate/unassigned canonical player')
                players[slot] = value['actions']
            result.append(dict(frame=expected, players=players, input_sha256=digest(raw)))
    return result


def build_frames(journal, slot, ability):
    found = []
    for frame in journal:
        for action in frame['players'][slot]:
            fields = parse_fields(action)
            if len(fields) != 1 or fields[0].number != 1:
                continue
            groups = get_repeated_bytes(fields[0].value, 1)
            if any(get_uint(group, 2) == ability for group in groups):
                found.append((frame['frame'], digest(action)))
    return found


def native_builds(log):
    return re.findall(r'\[(\d+)\] LAN NORMAL BUILD smoke frame(\d+) slot(\d+) [^\r\n]* ability(\d+) '
                      r'[^\r\n]*queued=1 commandQueueDelta=1',log)


def startup_barrier(match, events):
    selected = [row for row in events if row.get('match') == match]
    waiting = [row for row in selected if row['event'] == 'command_startup_waiting']
    ready = [row for row in selected if row['event'] == 'command_startup_ready']
    released = [row for row in selected if row['event'] == 'command_startup_released']
    require(len(waiting) == len(released) == 1 and len(ready) == 2 and
            {row['slot'] for row in ready} == {0,1}, 'first-output startup barrier coverage differs')
    wait,release = waiting[0],released[0]
    require(wait['frame'] == 0 and release['frame'] == 1 and set(wait['ready_slots']) ==
            set(release['ready_slots']) == {0,1} and [row['ready_count'] for row in ready] == [1,2] and
            [row['all_ready'] for row in ready] == [False,True], 'first-output readiness roster/count differs')
    require(wait['observed_at'] <= min(row['observed_at'] for row in ready) and
            release['observed_at'] >= max(row['observed_at'] for row in ready) and
            abs(release['next_tick']-release['rebased_at']-.05) < .000001,
            'first-output barrier did not rebase its steady clock')
    seals = {row['frame']:row for row in selected if row['event'] == 'probe_command_frame_sealed'}
    queued = {row['frame']:row for row in selected if row['event'] == 'frame_queued' and row['frame'] in (0,1)}
    require(set(seals) == set(queued) == {0,1} and
            seals[0]['observed_at'] <= queued[0]['observed_at'] <= wait['observed_at'] and
            seals[1]['observed_at'] >= release['observed_at'] and
            seals[1]['observed_perf_counter'] >= release['next_tick'] and
            queued[1]['observed_at'] >= seals[1]['observed_at'], 'frame1 was sealed before the presented-output barrier')
    return dict(ready_slots=[0,1],wait_ms=release['wait_ms'],rebased_at=release['rebased_at'],
                next_tick=release['next_tick'],frame1_sealed_after_release=True)


def first_output_ready(log, match, slot, trace, events):
    sent = [(int(frame),int(tick)) for identity,frame,tick in re.findall(
        r'Original command first output ready: match=([a-f0-9]{32}) presentedFrame=(\d+) sendTick=(\d+)',log)
        if identity == match]
    published = [row for row in trace if row['event'] == 'publication' and row['frame'] == row['presented'] == 0]
    received = [row for row in events if row['event'] == 'command_startup_ready' and
                row.get('match') == match and row['slot'] == slot]
    require(len(sent) == len(published) == len(received) == 1 and sent[0][0] == 0 and
            published[0]['ms'] <= sent[0][1] <= received[0]['probe_tick_ms'],
            'READY did not follow actual first native output publication exactly once')
    return dict(first_publication_ms=published[0]['ms'],ready_sent_ms=sent[0][1],
                ready_received_ms=received[0]['probe_tick_ms'],actual_publication_before_ready=True)


def conservation(match, journal, events, bodies, target):
    accepted = [row for row in events if row['event'] == 'command_batch_accepted' and row.get('match') == match]
    committed = [row for row in events if row['event'] == 'command_batch_committed' and
                 row.get('match') == match and row['frame'] < target]
    require(accepted and committed, 'arrival mode lacks accepted/committed batch evidence')
    accepted_by_key = {(row['slot'], row['sequence']): row for row in accepted}
    require(len(accepted_by_key) == len(accepted), 'accepted command sequence repeats')
    committed_keys = [(row['slot'], row['sequence']) for row in committed]
    require(len(set(committed_keys)) == len(committed_keys), 'command batch committed twice')
    expected = defaultdict(list)
    for row in committed:
        key = row['slot'], row['sequence']
        require(key in accepted_by_key, 'committed command lacks accepted provenance')
        prior = accepted_by_key[key]
        require(row['body_sha256'] == prior['body_sha256'] and row['action_count'] == prior['action_count'] and
                row['frame'] == prior['earliest_frame'], 'command changed or missed its next legal seal')
        body = bodies[(match, *key)]
        actions = decode_player_input(body)['actions']
        require(digest(body) == row['body_sha256'] and len(actions) == row['action_count'] and actions,
                'canonical accepted batch evidence differs')
        expected[(row['frame'], row['slot'])].extend(actions)
    for row in accepted:
        if row['earliest_frame'] < target:
            require((row['slot'], row['sequence']) in committed_keys, 'accepted prefix batch was lost')
    for frame in journal:
        for slot in (0, 1):
            require(frame['players'][slot] == tuple(expected[(frame['frame'], slot)]),
                    f'accepted command order/content differs at frame{frame["frame"]} slot{slot}')
    return dict(accepted_batches=len(accepted), prefix_committed_batches=len(committed),
                prefix_actions=sum(row['action_count'] for row in committed),
                exact_ordered_action_conservation=True, next_legal_seal=True)


async def run(args):
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    require(os.name == 'nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'),
            'owned Windows game and ignored evidence directories required')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    helper = (game/'BattleAcesOffline.dll').read_bytes()
    require(digest(helper) == args.expected_helper_sha256 and MARKER in helper, 'exact experimental helper required for both controls')
    verify_assets(assets)
    output.mkdir(parents=True, exist_ok=False)
    runtime = game/'investigation/runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    pki_folder = output/'ephemeral-pki'
    pki = generate_test_pki(pki_folder)
    audit, events, workers, clients, shapers = Audit(output), [], [], [], []
    canonical_states, bodies, raw_bodies, hold = defaultdict(dict), {}, {}, {}
    tick = ctypes.WinDLL('kernel32').GetTickCount64
    tick.restype = ctypes.c_ulonglong
    identities = [('p_'+secrets.token_hex(16), 'ba1_'+secrets.token_urlsafe(32)) for _ in range(2)]
    started = time.monotonic()
    report = dict(passed=False, scheduling=args.scheduling, scenario=args.scenario, frames=args.frames,
                  rematch=args.rematch, rtt_ms=args.rtt_ms, helper_sha256=digest(helper),
                  source_sha256_at_start=source_hashes(), scope=__doc__,
                  state_scope='all parsed authoritative worker fields except raw_sha256; fresh-worker replay required',
                  delay_scope='local ordered independent stream delay with end-to-end TLS; no packet loss or remote TCP model')

    class Store:
        def authenticate(self, token):
            for identity, expected in identities:
                if secrets.compare_digest(token, expected):
                    return identity
            raise AuthenticationError()

    def observe(event, **fields):
        row = dict(event=event, probe_tick_ms=int(tick()), observed_at=time.monotonic(),
                   observed_perf_counter=time.perf_counter(), **fields)
        if event == 'frame_queued':
            room = server.rooms[fields['room']]
            row['input_windows'] = dict(room.input_windows)
            row['command_scheduling'] = room.command_scheduling
            row['observable_state_sha256'] = state_digest(room.sim.last_state)
            canonical_states[fields['match']][fields['frame']] = row['observable_state_sha256']
        events.append(row)
        audit(event, **{key: value for key, value in row.items() if key != 'event'})

    async def factory(data):
        worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output)
        workers.append(worker)
        original = worker.process_frame
        async def process_frame(actions, dt_ms=None):
            result = await original(actions, dt_ms=dt_ms)
            if args.scenario == 'held-worker' and len(workers) == 1 and result.frame == 300 and not hold:
                # Delay delivery of a completed real worker request. The room
                # has sealed300 and is still awaiting its worker result; input
                # callbacks remain live. This never suspends a native process.
                hold.update(start=time.monotonic(), frame=300)
                observe('probe_worker_result_hold_started', frame=300)
                await asyncio.sleep(args.hold_ms/1000)
                hold['end'] = time.monotonic()
                observe('probe_worker_result_hold_released', frame=300)
            return result
        worker.process_frame = process_frame
        return worker

    template = GameTemplate.load(assets/'map-1v1.pb.gz', catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
    cosmetics = CosmeticCatalog(assets)
    server = DedicatedServer(template, ProfileStore(output/'profiles', template, catalog=cosmetics),
        templates={1: template}, sim_factory=factory, audit=observe, data_dir=output,
        audit_state=args.state_audit, input_timeout=30, experimental_command_scheduling=args.scheduling == 'arrival',
        tls_context=tls.load_server_context(pki['cert'], pki['key']), admission=admission.AdmissionController(Store()))
    original_message, original_accept = Room.on_message, command_wire.ArrivalScheduler.accept
    original_seal = command_wire.ArrivalScheduler.seal

    async def witnessed_message(room, peer, kind, payload):
        active = room.state in ('loading','running')
        result = await original_message(room, peer, kind, payload)
        if active and room.server is server and kind in (p.INPUT, command_wire.BATCH, command_wire.HEARTBEAT,command_wire.READY):
            fields = dict(match=room.match_id,slot=peer.slot,kind=kind)
            if kind == p.INPUT and room.state == 'running':
                frame, = struct.unpack_from('<I',payload)
                canonical = room.pending[frame][peer.slot]
                bodies[(room.match_id,peer.slot,frame)] = canonical
                fields.update(frame=frame,body_sha256=digest(canonical),
                              action_count=len(decode_player_input(canonical)['actions']))
            elif kind == command_wire.BATCH:
                match,sequence,body = command_wire.decode_batch(payload)
                raw_bodies[(match,peer.slot,sequence)] = body
            elif kind == command_wire.READY:
                fields['ready_match'] = command_wire.decode_ready(payload)
            observe('probe_client_message_accepted', **fields)
        return result

    def witnessed_accept(scheduler, slot, sequence, body):
        batch = original_accept(scheduler, slot, sequence, body)
        room = next((room for room in server.rooms.values() if room.command_scheduler is scheduler), None)
        if room is not None:
            key = room.match_id, slot, sequence
            require(key not in bodies, 'duplicate observed accepted batch')
            bodies[key] = batch.body
        return batch

    def witnessed_seal(scheduler, frame):
        sealed = original_seal(scheduler,frame)
        if sealed is not None and frame in (0,1):
            room = next((room for room in server.rooms.values() if room.command_scheduler is scheduler),None)
            if room is not None:
                observe('probe_command_frame_sealed',match=room.match_id,frame=frame)
        return sealed

    try:
        port = (await server.start('127.0.0.1', 0))[1]
        context = tls.load_client_context(pki['ca'], 'localhost')
        shutil.copyfile(game/'.battleaces-resurrection/patch-manifest.json', output/'patch-manifest.json')
        with mock.patch.object(Room, 'on_message', witnessed_message), \
             mock.patch.object(command_wire.ArrivalScheduler, 'accept', witnessed_accept), \
             mock.patch.object(command_wire.ArrivalScheduler, 'seal', witnessed_seal):
            for index, role in enumerate(('host', 'guest')):
                shaper = StreamShaper(port, rtt_ms=args.rtt_ms[index], seed=101+index)
                shapers.append(shaper)
                delayed_port = await shaper.start()
                parent, child = socket.socketpair(socket.AF_INET)
                parent.setblocking(False)
                reader, writer = await asyncio.open_connection(sock=parent)
                row = dict(index=index, parent=parent, child=child, writer=writer, log='', wire=[])
                clients.append(row)
                async def resolve(index=index, delayed_port=delayed_port):
                    return bridge.Remote('127.0.0.1', delayed_port, context, *identities[index])
                config = dict(game_directory=game, server_host='127.0.0.1', server_port=delayed_port,
                    display_name='Original scheduling '+role, room='community', fullscreen=False,
                    local_profile='original_sched_'+secrets.token_hex(8), solo_ai_host='server')
                options = argparse.Namespace(run_name='original-scheduling-'+role, unified_experimental=True, player_features=True)
                command = launcher.game_arguments(config, None, child.fileno(), options)
                command[command.index('-logFile')+1] = str(output/f'game-{index}.log')
                command += [f'-community-match-{role}-smoke', '-lan-smoke', '-dedicated-surrender-smoke',
                            f'-dedicated-surrender-frame={args.frames+70}', '-dedicated-rematch-smoke',
                            '-frame-timing', f'-frame-timing-frames={args.frames}']
                if args.scheduling == 'arrival':
                    command += ['-original-command-scheduling-experimental']
                if args.state_audit:
                    command += ['-lan-audit']
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 0
                startup.lpAttributeList = {'handle_list': [child.fileno()]}
                row['tick'] = int(tick())
                child.set_inheritable(True)
                try:
                    row['process'] = subprocess.Popen(command, cwd=game, startupinfo=startup, close_fds=True,
                                                       creationflags=subprocess.CREATE_NO_WINDOW)
                finally:
                    child.set_inheritable(False)
                    child.close()
                row['job'] = _WindowsJob(row['process'].pid)
                row['task'] = asyncio.create_task(ObservedBridge(reader, writer, resolve, version=2,
                                                               evidence=row['wire'], tick=lambda: int(tick())).run())
                row['trace'] = runtime/f'frame-timing-{row["process"].pid}.tsv'
                require(not row['trace'].exists(), 'timing trace already exists for reused PID')
                (output/'processes.json').write_text(json.dumps(dict(helper_sha256=digest(helper),
                    clients=[dict(index=c['index'], pid=c['process'].pid, launch_tick=c['tick']) for c in clients]), indent=2)+'\n')
            while True:
                for row in clients:
                    require(row['process'].poll() is None and not row['task'].done(), 'owned native client/bridge exited early')
                    row['log'] = await asyncio.to_thread(read_native_log, game, row['process'].pid, since_tick=row['tick'])
                    for marker in ('Offline loop stopped in ', 'Client lifecycle invariant failed:',
                                   'LAN audit disabled:', 'Frame timing capture stopped:', 'Original command scheduling failed:'):
                        require(marker not in row['log'], 'native scheduling failure: '+marker)
                require(not any(row['event'] in ('protocol_error', 'match_aborted', 'custom_match_setup_error') for row in events),
                        'local Custom authority failed')
                if all(row['trace'].exists() for row in clients) and (not args.rematch or all(PASSED in row['log'] for row in clients)):
                    await asyncio.sleep(.25)
                    break
                require(time.monotonic()-started < args.timeout, 'bounded scheduling deadline reached')
                await asyncio.sleep(.25)
            created = [row for row in events if row['event'] == 'match_created']
            require(len(created) == (2 if args.rematch else 1), 'unexpected Custom match count')
            require(sum(row['event'] == 'community_joined' for row in events) == 2 and
                    sum(row['event'] == 'custom_lobby_created' for row in events) == 1,
                    'Custom route reconnected or created extra lobbies')
            matches = [row['match'] for row in created]
            report['matches'], report['clients'] = [], []
            # Measurement has finished. Flush only this owned observer's
            # journal writer before reading its potentially buffered tail.
            for room in server.rooms.values():
                if room.history:
                    room.history.flush()
            for match in matches:
                queued = [row for row in events if row['event'] == 'frame_queued' and row.get('match') == match and row['frame'] < args.frames]
                require([row['frame'] for row in queued] == list(range(args.frames)), 'incomplete authoritative prefix')
                journal = read_journal(output, match, args.frames)
                authority = dict(match=match, frames=args.frames,
                    effective_hz=(args.frames-1)/(queued[-1]['observed_at']-queued[0]['observed_at']),
                    worker_ms=summary([row['worker_ms'] for row in queued]),
                    input_wait_ms=summary([row['input_wait_ms'] for row in queued]),
                    input_windows=queued[0]['input_windows'])
                if args.scenario == 'timing' and not args.state_audit:
                    require(19 <= authority['effective_hz'] <= 21,'authority missed the20Hz timing gate')
                require(all(row['command_scheduling'] == (args.scheduling == 'arrival') for row in queued),
                        'actual room scheduling mode differs')
                wire_expected = {row['frame']: row['frame_payload_sha256'] for row in queued}
                for client in clients:
                    delivered = [row for row in client['wire'] if row['match'] == match and row['frame'] < args.frames]
                    require([row['frame'] for row in delivered] == list(range(args.frames)) and
                            all(row['payload_sha256'] == wire_expected[row['frame']] for row in delivered),
                            'private bridge payload prefix differs from authority')
                if args.scheduling == 'arrival':
                    authority['conservation'] = conservation(match, journal, events, bodies, args.frames)
                    authority['startup_barrier'] = startup_barrier(match,events)
                    messages = [row for row in events if row['event'] == 'probe_client_message_accepted' and row.get('match') == match]
                    require(not any(row['kind'] == p.INPUT for row in messages), 'arrival mode still sends per-frame input packets')
                    require({row['slot'] for row in messages if row['kind'] == command_wire.HEARTBEAT} == {0,1},
                            'independent heartbeat missing for a human')
                    require({row['slot'] for row in messages if row['kind'] == command_wire.READY and row['ready_match'] == match} == {0,1},
                            'first-output READY packet coverage differs')
                    first = [row for row in events if row['event'] == 'command_batch_accepted' and row.get('match') == match and row['sequence'] == 1]
                    require({row['slot'] for row in first} == {0,1}, 'startup lacks both human first batches')
                    for row in first:
                        actions = decode_player_input(bodies[(match,row['slot'],1)])['actions']
                        require(actions and parse_fields(actions[0])[0].number == 3 and
                                row['observed_at'] <= queued[0]['observed_at'], 'JoinArmy start barrier differs')
                    empty = [frame['frame'] for frame in journal if not any(frame['players'].values())]
                    idle_runs = []
                    for frame in empty:
                        if idle_runs and frame == idle_runs[-1][-1]+1:
                            idle_runs[-1].append(frame)
                        else:
                            idle_runs.append([frame])
                    require(idle_runs and max(map(len,idle_runs)) >= 30, 'no-input idle progress was not observed')
                    authority['no_input_idle_frames'] = max(map(len,idle_runs))
                else:
                    accepted = [row for row in events if row['event'] == 'probe_client_message_accepted' and
                                row.get('match') == match and row['kind'] == p.INPUT and row.get('frame',args.frames) < args.frames]
                    require(len(accepted) == 2*args.frames and
                            {(row['frame'],row['slot']) for row in accepted} ==
                            {(frame,slot) for frame in range(args.frames) for slot in (0,1)},
                            'buffered per-peer accepted input coverage differs')
                    for frame in journal:
                        for slot in (0,1):
                            require(decode_player_input(bodies[(match,slot,frame['frame'])])['actions'] == frame['players'][slot],
                                    'buffered accepted input differs from canonical journal')
                    authority['conservation'] = dict(accepted_inputs=len(accepted),exact_ordered_action_conservation=True)
                if args.state_audit:
                    expected = {(row['frame'],row['viewer']):row['canonical_fnv1a64'] for row in events if
                                row['event'] == 'native_snapshot' and row.get('match') == match and row['frame'] < args.frames}
                    compared = []
                    for client in clients:
                        path = runtime/f'lan-audit-{client["process"].pid}-{match}.tsv'
                        with path.open(newline='',encoding='utf-8') as stream:
                            samples = {(int(row['frame']),int(row['viewer'])):row['canonical_fnv1a64']
                                       for row in csv.DictReader(stream,delimiter='\t')}
                        common = samples.keys() & expected.keys()
                        require(len(common) >= args.frames//20 and all(samples[key] == expected[key] for key in common),
                                'actual native client sampled state differs from authoritative snapshot')
                        shutil.copyfile(path,output/path.name)
                        compared.append(dict(pid=client['process'].pid,comparisons=len(common),passed=True,
                                             scope='shared-frame canonical observable native snapshot fields, not hidden world state'))
                    authority['native_sampled_state_equivalence'] = compared
                if match == matches[0]:
                    for client in clients:
                        trace = prefix_trace(frame_timing.read_trace(client['trace']), args.frames)
                        measured = frame_timing.measure(trace)
                        gate = frame_timing.qualify(trace,[args.frames],max_skips=0,max_short_gaps=0,max_gap_ms=100)
                        require([row['frame'] for row in trace if row['event'] == 'arrival'] == list(range(args.frames)) and
                                [row['frame'] for row in trace if row['event'] == 'apply'] == list(range(args.frames)) and
                                measured['last_presented'] >= args.frames-1, 'native prefix arrival/application/presentation incomplete')
                        if args.scenario == 'timing' and not args.state_audit:
                            require(gate['passed'], 'native presentation gate failed: '+repr(gate['errors']))
                        applied = {row['frame']:row['ms'] for row in trace if row['event'] == 'apply'}
                        builds = native_builds(client['log'])
                        require(len(builds) == len(matches), 'original queued build command missing/repeated')
                        queued_tick, smoke_frame, slot, ability = map(int,builds[0])
                        found = build_frames(journal,slot,ability)
                        require(len(found) == 1 and found[0][0] in applied, 'queued native build lacks unique canonical execution frame')
                        actual_frame = found[0][0]
                        client_report = dict(index=client['index'],pid=client['process'].pid,rtt_ms=args.rtt_ms[client['index']],
                            slot=slot,smoke_frame=smoke_frame,actual_frame=actual_frame,
                            queue_to_apply_ms=applied[actual_frame]-queued_tick,build_action_sha256=found[0][1],
                            latency_scope='original native build queue timestamp to native authoritative input application; no physical click claim',
                            timing=measured,timing_gate=gate)
                        if args.scheduling == 'arrival':
                            require('Original command scheduling negotiated: version=1' in client['log'], 'native negotiation marker absent')
                            client_report['startup_first_output'] = first_output_ready(client['log'],match,slot,trace,events)
                            bound = [(row['sequence'],row['body_sha256']) for row in events if row['event'] == 'command_batch_committed' and
                                     row.get('match') == match and row['slot'] == slot and row['frame'] == actual_frame and
                                     any(digest(action) == found[0][1] for action in decode_player_input(bodies[(match,slot,row['sequence'])])['actions'])]
                            require(len(bound) == 1, 'build action lacks unique batch-to-frame provenance')
                            client_report['batch_sequence'],client_report['batch_body_sha256'] = bound[0]
                            native_batches = [(int(sequence),int(count),int(length),sha,int(sent),int(source))
                                for identity,sequence,count,length,sha,sent,source in re.findall(
                                    r'Original command batch submitted: match=([a-f0-9]{32}) sequence=(\d+) actions=(\d+) bytes=(\d+) '
                                    r'body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)',client['log']) if identity == match]
                            by_sequence = {row[0]:row for row in native_batches}
                            require(len(by_sequence) == len(native_batches), 'native command submission sequence repeats')
                            for event in (row for row in events if row['event'] == 'command_batch_accepted' and
                                          row.get('match') == match and row['slot'] == slot and row['earliest_frame'] < args.frames):
                                sequence = event['sequence']
                                raw = raw_bodies[(match,slot,sequence)]
                                require(sequence in by_sequence and by_sequence[sequence][2] == len(raw) and
                                        by_sequence[sequence][3] == digest(raw), 'native submitted batch differs from server-received bytes')
                            submission = by_sequence[bound[0][0]]
                            client_report['batch_send_to_apply_ms'] = applied[actual_frame]-submission[4]
                            client_report['native_batch_raw_sha256'] = submission[3]
                            require('LAN submitted frame ' not in client['log'], 'arrival mode still used legacy native frame submissions')
                        else:
                            require('Original command scheduling negotiated:' not in client['log'],
                                    'buffered control negotiated experimental scheduling')
                        report['clients'].append(client_report)
                report['matches'].append(authority)
            if args.scenario == 'held-worker':
                require(hold.get('end') is not None, 'worker-result hold did not execute')
                during = [row for row in events if row['event'] == 'command_batch_accepted' and hold['start'] < row['observed_at'] < hold['end']]
                require(during and all(row['earliest_frame'] == 301 for row in during), 'commands did not arrive during the sealed worker hold')
                committed = {(row['match'],row['slot'],row['sequence']):row['frame'] for row in events if row['event'] == 'command_batch_committed'}
                require(all(committed[(row['match'],row['slot'],row['sequence'])] == 301 for row in during),
                        'held-worker arrival rewrote current frame or missed next seal')
                report['held_worker_result'] = dict(**hold,received_batches=len(during),all_committed_frame=301,
                    scope='completed native result delivery held; native process itself was not paused')
            if args.rematch:
                require(len([row for row in events if row['event'] == 'match_completed']) == 2,
                        'two same-lobby native result/Continue cycles did not complete')
                report['rematch_scope'] = 'two original Custom Start/result/Continue cycles, one lobby, fresh worker per match; timing covers first prefix'
            require(all(worker.process.poll() is None or worker.process.poll() == 0 for worker in workers) and
                    not any(worker.failure for worker in workers), 'authoritative native worker failed')
            report['passed'] = True
    except BaseException as error:
        report.update(passed=False,error=f'{type(error).__name__}: {error}',traceback=traceback.format_exc())
    finally:
        cleanup_errors = []
        for room in list(server.rooms.values()):
            if room.state == 'running':
                room.state = 'completed'
        deadline = time.monotonic()+3
        while any(worker._lock.locked() for worker in workers) and time.monotonic() < deadline:
            await asyncio.sleep(.005)
        for row in clients:
            if row.get('process'):
                await cleanup_step(cleanup_errors,'stop client '+str(row['process'].pid),
                                   lambda row=row:stop_owned_process(row['process']))
                await cleanup_step(cleanup_errors,'retain client log '+str(row['process'].pid),lambda row=row:
                    (output/f'native-{row["process"].pid}.log').write_text(
                        read_native_log(game,row['process'].pid,since_tick=row['tick']),encoding='utf-8'))
            if row.get('job'):
                await cleanup_step(cleanup_errors,'close client job',row['job'].close)
            if row.get('task'):
                row['task'].cancel()
            await cleanup_step(cleanup_errors,'close inherited child socket',row['child'].close)
        await asyncio.gather(*(row['task'] for row in clients if row.get('task')),return_exceptions=True)
        for row in clients:
            await cleanup_step(cleanup_errors,'start closing private bridge writer',row['writer'].close)
            async def close_writer(row=row):
                try:
                    await asyncio.wait_for(row['writer'].wait_closed(),2)
                except OSError:
                    pass  # Expected reset after intentionally terminating this owned peer.
                finally:
                    row['writer'].transport.abort()
            await cleanup_step(cleanup_errors,'close private bridge writer',close_writer)
        await cleanup_step(cleanup_errors,'close local authority',lambda:asyncio.wait_for(server.close(),30))
        for worker in workers:
            await cleanup_step(cleanup_errors,'close worker '+str(worker.pid),worker.close)
        for shaper in shapers:
            await cleanup_step(cleanup_errors,'close local stream shaper',lambda shaper=shaper:asyncio.wait_for(shaper.close(),5))
        for row in clients:
            if row.get('trace') and row['trace'].exists():
                await cleanup_step(cleanup_errors,'retain native timing trace',lambda row=row:shutil.copyfile(row['trace'],output/row['trace'].name))
        await cleanup_step(cleanup_errors,'remove ephemeral PKI',lambda:remove_test_pki(pki_folder))
        await cleanup_step(cleanup_errors,'close audit',audit.close)
        report.update(elapsed_seconds=time.monotonic()-started,source_sha256_at_finish=source_hashes(),
            owned_processes_reaped=all(row.get('process') is None or row['process'].poll() is not None for row in clients),
            worker_cleanup=[dict(pid=worker.pid,exit_code=worker.process.poll(),failure=worker.failure) for worker in workers],
            shapers=[dict(rtt_ms=args.rtt_ms[index],**shaper.stats) for index,shaper in enumerate(shapers)],
            cleanup_errors=cleanup_errors,
            teardown='forced owned prefix/process teardown; no native Quit claim')
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= not cleanup_errors and report['owned_processes_reaped'] and report['source_files_unchanged'] and all(
            row['exit_code'] == 0 and not row['failure'] for row in report['worker_cleanup'])
        if report['passed']:
            try:
                report['authoritative_replay'] = {row['match']:await replay_check(assets,output,row['match'],
                    canonical_states[row['match']],args.frames) for row in report['matches']}
            except BaseException as error:
                report.update(passed=False,replay_error=f'{type(error).__name__}: {error}')
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','error','replay_error','scheduling','scenario','matches','clients','elapsed_seconds') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game','assets','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--expected-helper-sha256',required=True)
    parser.add_argument('--scheduling',choices=('buffered','arrival'),required=True)
    parser.add_argument('--scenario',choices=('timing','held-worker'),default='timing')
    parser.add_argument('--rtt-ms',type=float,nargs=2,default=(130,475))
    parser.add_argument('--frames',type=int,default=600)
    parser.add_argument('--timeout',type=int,default=240)
    parser.add_argument('--hold-ms',type=int,default=1500)
    parser.add_argument('--state-audit',action='store_true',help='separate snapshot comparison run; adds timing I/O')
    parser.add_argument('--rematch',action='store_true',help='complete two original Custom result/Continue cycles')
    args = parser.parse_args()
    require(600 <= args.frames <= 1800 and 90 <= args.timeout <= 360,'bounded native prefix required')
    require(re.fullmatch('[a-f0-9]{64}',args.expected_helper_sha256) is not None,'exact helper SHA256 required')
    require(args.scenario != 'held-worker' or (args.scheduling == 'arrival' and 500 <= args.hold_ms <= 3000),
            'worker hold requires explicit arrival mode and bounded duration')
    require(not args.state_audit or args.scenario == 'timing','snapshot and worker-hold scopes must be separate')
    for rtt in args.rtt_ms:
        StreamShaper(1,rtt_ms=rtt)
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
