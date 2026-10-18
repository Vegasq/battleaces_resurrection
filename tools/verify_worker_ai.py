"""Opt-in mixed native room and replay proof; accelerated clock, scripted human.

This is not graphical play, public queue/AI selection, or real-time performance
qualification. Native bot decisions and the simulation still use 50 ms frames.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import traceback

from server import dedicated_server as coordinator, protocol as p
from server.assets import verify_assets
from server.game_data import GameTemplate, encode_frame, encode_player_input
from server.profiles import ProfileStore
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_bytes, get_repeated_bytes, get_repeated_uint, get_uint
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker
from tools.verify_worker_rooms import Audit, ScriptedPeer, require
from tools.verify_custom_lobby import source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    return core_hashes() | {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                           ('server/worker_ai.py', 'tools/verify_worker_ai.py', 'tools/verify_worker_rooms.py')}


async def run(args):
    started = time.monotonic()
    output, assets = args.output, args.assets
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, scope=__doc__, source_sha256_at_start=source_hashes(),
                  frame_timestep_ms=50, accelerated_wall_clock=True, profile=args.profile)
    workers, peer, server, audit, room = [], None, None, None, None
    original_tick = coordinator.TICK
    try:
        verify_assets(assets)
        template = GameTemplate.load(assets/'map-1v1.pb.gz', catalog_path=assets/'unit-catalog.json',
                                     descriptors_path=assets/'descriptors')
        audit = Audit(output)
        async def factory(data, bots):
            worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output,
                                                   ai=AISetup(assets, bots))
            workers.append(worker)
            return worker
        server = coordinator.DedicatedServer(template, ProfileStore(output/'profiles', template),
                    ai_factory=factory, audit=audit, data_dir=output, audit_state=False, input_timeout=30)
        address = await server.start('127.0.0.1', 0)
        bot = coordinator.BotSeat(1, args.profile, 'Native server bot', template.default_decks[1])
        room = coordinator.Room(server, 'native_ai', bots=[bot]); server.rooms[room.name] = room
        coordinator.TICK = 0.001  # Only this owned verifier's coordinator; native dt remains50.
        reader, writer = await asyncio.open_connection(*address[:2])
        peer = ScriptedPeer(reader, writer)
        await peer.send(p.HELLO, p.hello(p.AUTO_SEAT, 'scripted_human', 'Scripted human', room.name))
        slot, _, _ = p.decode_welcome(await peer.receive(p.WELCOME))
        require(slot == 0, 'bot reserved seat was assigned to human')
        await peer.send(p.LOBBY_READY, b'\x01')
        bootstrap = await peer.receive(p.BOOTSTRAP)
        require(bootstrap == room.match.gzip_game_data, 'received bootstrap differs')
        replay = await SimulationWorker.create(room.match.raw_game_data, assets/'Simulation.dll', working_directory=output)
        workers.append(replay)
        native = room.sim
        report.update(worker_pids=[worker.pid for worker in workers], ai=native.ai_info,
                      raw_game_data_sha256=room.match.raw_sha256,
                      imported_manifest_sha256=hashlib.sha256((assets/'asset-manifest.json').read_bytes()).hexdigest())
        await peer.send(p.LOADED, hashlib.sha256(bootstrap).digest())
        await peer.receive(p.START)
        expected_journal, actual_journal = hashlib.sha256(), hashlib.sha256()
        produced, moved, ordered, initial, positions = set(), set(), set(), set(), {}
        command_count, max_supply, max_damage, matched_frames = 0, 0, 0, 0
        with (output/'observations.jsonl').open('w', encoding='utf-8') as trace:
            for frame in range(args.frames):
                actions = []
                if frame == 0:
                    actions.append(field_bytes(3, field_uint(1, 0) + field_bytes(2, room.match.deck_messages_by_slot[0])))
                # The human test peer uses ordinary owned-HQ build commands. It
                # never sends an AI identity, generated bot orders or surrender.
                if frame >= 200 and frame % 60 == 20:
                    hq = next((entity['id'] for entity in native.last_state['entities']
                               if entity.get('army') == 0 and entity.get('type') == 3), None)
                    if hq is not None:
                        group = field_uint(1, 3) + field_uint(2, 34) + field_packed_uint(3, [hq])
                        actions.append(field_bytes(1, field_bytes(1, group) + field_bytes(3, field_bytes(1, b''))))
                human = encode_player_input(room.match.identities_by_slot[0], actions)
                await peer.send(p.INPUT, struct.pack('<I', frame)+human)
                payload = await peer.receive(p.FRAME, timeout=20)
                number, length = struct.unpack_from('<II', payload)
                require(number == frame and length <= len(payload)-8, 'received frame envelope differs')
                by_slot = {0: payload[8:8+length], 1: payload[8+length:]}
                require(by_slot[0] == human, 'server changed canonical human actions')
                canonical = encode_frame(frame, by_slot)
                expected_journal.update(struct.pack('<I', len(canonical))+canonical)
                replica = await replay.process_frame(canonical)
                # No next human input has been submitted, so the room cannot
                # advance past this exact authoritative native frame.
                require(native.last_state['frame'] == frame and
                        native.last_state['canonical_fnv1a64'] == replica.state['canonical_fnv1a64'],
                        'delivered frame does not reproduce authoritative state')
                matched_frames += 1
                for action in get_repeated_bytes(by_slot[1], 2):
                    command = get_bytes(action, 1)
                    if command:
                        command_count += 1
                        for group in get_repeated_bytes(command, 1):
                            if get_uint(group, 2) in (12, 88): ordered.update(get_repeated_uint(group, 3))
                state = replica.state
                if frame == 0: initial = {entity['id'] for entity in state['entities']}
                for entity in state['entities']:
                    if entity.get('army') != 1: continue
                    key = entity['id']
                    max_damage = max(max_damage, entity.get('current_damage', 0))
                    if key not in initial and entity.get('type') in room.match.decks_by_slot[1]:
                        produced.add(key)
                        if 'position' in entity:
                            position = entity['position']
                            if key in positions and positions[key] != position: moved.add(key)
                            positions[key] = position
                max_supply = max(max_supply, state['resources'][1]['current_supply'])
                if frame % 100 == 0:
                    trace.write(json.dumps({'frame': frame, 'canonical_fnv1a64': state['canonical_fnv1a64'],
                                           'resources': state['resources'], 'game_state': state['game_state']})+'\n')
                if state['game_state']['complete'] and frame >= room.result_frame + 19: break
        result = json.loads(await peer.receive(p.MATCH_END, timeout=10))
        require(result['result']['complete'], 'match did not complete naturally')
        require(produced & moved & ordered, 'server bot did not build and move under native orders')
        require(max_damage > 0, 'server bot saw no combat damage')
        journal = output/'matches'/room.match_id/'frames.bin'
        with journal.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''): actual_journal.update(chunk)
        require(actual_journal.digest() == expected_journal.digest(), 'delivered and accepted frame journals differ')
        report.update(passed=True, final_frame=frame, matched_native_replay_frames=matched_frames,
                      game_state=result['result'], bot_commands=command_count, bot_max_supply=max_supply,
                      bot_max_damage=max_damage, bot_produced_units=len(produced),
                      bot_ordered_moving_units=len(produced & moved & ordered),
                      exact_delivered_journal_sha256=expected_journal.hexdigest())
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        coordinator.TICK = original_tick
        if server is not None: await server.close()
        if peer is not None: await peer.close()
        await asyncio.gather(*(worker.close() for worker in workers))
        if audit is not None: audit.close()
        report.update(worker_exit_codes=[worker.process.poll() for worker in workers],
                      owned_workers_reaped=all(worker.process.poll() is not None for worker in workers),
                      elapsed_seconds=time.monotonic()-started, source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= (report['source_files_unchanged'] and report['owned_workers_reaped'] and
                             report['worker_exit_codes'] == [0, 0])
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'error', 'elapsed_seconds', 'final_frame',
                         'bot_ordered_moving_units', 'matched_native_replay_frames', 'worker_exit_codes') if k in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', type=int, default=58)
    parser.add_argument('--frames', type=int, default=16000)
    args = parser.parse_args()
    args.assets, args.output = args.assets.resolve(), args.output.resolve()
    require(os.name == 'nt' and args.output.is_relative_to(ROOT/'local') and 1200 <= args.frames <= 24000,
            'bounded Windows/ignored evidence probe required')
    return asyncio.run(run(args))


if __name__ == '__main__': raise SystemExit(main())
