"""Opt-in public queue and native AI replay proof with scripted human clients.

Queue time and simulation delivery are accelerated; native simulation dt is50ms.
This does not qualify graphical clients, TLS, Internet play or real-time pacing.
No client surrender is injected: the selected native bots must finish the match.
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

from server import dedicated_server as coordinator, protocol as p, community_protocol as c, public_protocol as q
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.game_data import GameTemplate, encode_frame, encode_player_input
from server.profiles import ProfileStore
from server.protobuf_wire import field_bytes, field_uint, get_bytes, get_repeated_bytes, get_repeated_uint, get_uint
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker
from tools.verify_worker_rooms import Audit, ScriptedPeer, require
from tools.verify_custom_lobby import source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    return core_hashes() | {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                           ('tools/verify_public_queue.py', 'tools/verify_worker_rooms.py')}


async def command(peer, kind, **values):
    peer.request += 1
    await peer.send(kind, q.command(kind, peer.request, peer.ticket, **values))
    r = c.Reader(await peer.receive(c.ACK, timeout=15))
    request, acknowledged, success = r.number('I'), r.number('B'), r.flag()
    reason, obj = r.text(1024), r.text(48); r.end()
    require(request == peer.request and acknowledged == kind and success, 'public command rejected: ' + reason)
    return obj


async def run(args):
    started = time.monotonic()
    output, assets = args.output, args.assets
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, scope=__doc__, source_sha256_at_start=source_hashes(), mode=args.mode,
                  human_count=args.humans, frame_timestep_ms=50, accelerated_wall_clock=True, virtual_queue_clock=True)
    workers, peers, server, audit = [], [], None, None
    original_tick = coordinator.TICK
    try:
        verify_assets(assets)
        templates = {mode: GameTemplate.load(assets/filename, catalog_path=assets/'unit-catalog.json',
                     descriptors_path=assets/'descriptors') for mode, filename in
                     ((1, 'map-1v1.pb.gz'), (2, 'map-2v2.pb.gz'), (5, 'map-2vai.pb.gz'))}
        catalog = BotCatalog(assets, template=templates[1], rules=RuleBook(assets))
        audit = Audit(output)
        async def factory(data, bots):
            worker = await SimulationWorker.create(data, assets/'Simulation.dll', working_directory=output,
                                                   ai=AISetup(assets, bots))
            workers.append(worker)
            return worker
        server = coordinator.DedicatedServer(templates[1], ProfileStore(output/'profiles', templates[1]),
                    templates=templates, bot_catalog=catalog, ai_factory=factory, audit=audit, data_dir=output,
                    audit_state=False, input_timeout=30)
        now = [1000.0]
        server.community.public.clock = lambda: now[0]
        address = await server.start('127.0.0.1', 0)
        coordinator.TICK = .001
        for index in range(args.humans):
            reader, writer = await asyncio.open_connection(*address[:2])
            peer = ScriptedPeer(reader, writer); peers.append(peer)
            peer.profile, peer.request, peer.ticket = 'scripted_' + str(index), 0, 1
            await peer.send(c.HELLO, c.hello(peer.profile, 'Scripted human ' + str(index+1)))
            welcome = c.Reader(await peer.receive(c.WELCOME))
            require(welcome.number('H') == 1 and welcome.number('H') == 3 and welcome.key() == peer.profile,
                    'community welcome differs')
            peer.deck = welcome.deck(); welcome.end()
            await command(peer, q.ENTER, mode=args.mode, wait_ms=30000, deck=peer.deck)
        partial = args.humans < len(q.MODES[args.mode][1])
        if partial:
            require(not server.community.public.offers and not workers, 'partial group launched before deadline')
            now[0] += 29.999; server.community.public.maintain()
            require(not server.community.public.offers and not workers, 'partial group launched early')
            now[0] = 1030.0; server.community.public.maintain()
        offers = list(server.community.public.offers.values())
        require(len(offers) == 1 and len(offers[0].entries) == args.humans, 'human group split across proposals')
        offer = offers[0]
        for index, peer in enumerate(peers):
            await command(peer, q.READY, match=offer.id)
            if index+1 < len(peers): require(not workers, 'worker created before all humans acknowledged')
        for peer in peers:
            peer.assignment = q.decode_assignment(await peer.receive(q.MATCH))
            peer.slot = peer.assignment['slot']
            require(peer.assignment['generation'] == peer.ticket and peer.assignment['match'] == offer.id,
                    'assignment crossed queue ticket/proposal')
            peer.bootstrap = await peer.receive(p.BOOTSTRAP)
        room = offer.room
        require(room and all(peer.bootstrap == room.match.gzip_game_data for peer in peers), 'human bootstraps differ')
        expected_seats = set(q.MODES[args.mode][1][:args.humans])
        require(set(room.peers) == expected_seats and {peer.slot for peer in peers} == expected_seats,
                'human team seats differ')
        require(len(workers) == 1 and room.bots, 'expected one shared native AI worker')
        native = room.sim
        replay = await SimulationWorker.create(room.match.raw_game_data, assets/'Simulation.dll', working_directory=output)
        workers.append(replay)
        report.update(worker_pids=[worker.pid for worker in workers], ai=native.ai_info, match=offer.id,
            human_slots=sorted(expected_seats), bot_slots=sorted(room.bots), queue_filled_at_deadline=partial,
            bot_choices={slot: dict(profile=bot.choice.profile, source_mode=bot.choice.source_mode, name=bot.choice.name,
                portrait=bot.choice.portrait, banner=bot.choice.banner, difficulty=bot.choice.difficulty,
                deck=list(bot.choice.deck.units)) for slot, bot in room.bots.items()},
            raw_game_data_sha256=room.match.raw_sha256,
            imported_manifest_sha256=hashlib.sha256((assets/'asset-manifest.json').read_bytes()).hexdigest())
        for peer in peers: await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        for peer in peers: await peer.receive(p.START)
        # Keep per-bot observations: an active teammate must not hide an idle opponent.
        produced, moved, ordered = ({slot: set() for slot in room.bots} for _ in range(3))
        positions, damage, initial, commands = {}, {slot: 0 for slot in room.bots}, set(), {slot: 0 for slot in room.bots}
        participant_damage = {slot: 0 for slot in room.slots}
        expected_journal, actual_journal = hashlib.sha256(), hashlib.sha256()
        matched_frames = 0
        with (output/'observations.jsonl').open('w', encoding='utf-8') as trace:
            for frame in range(args.frames):
                human_inputs = {}
                for peer in peers:
                    actions = [field_bytes(3, field_uint(1, peer.slot) + field_bytes(2, room.match.deck_messages_by_slot[peer.slot]))] if frame == 0 else []
                    human = human_inputs[peer.slot] = encode_player_input(room.match.identities_by_slot[peer.slot], actions)
                    await peer.send(p.INPUT, struct.pack('<I', frame)+human)
                payloads = [await peer.receive(q.FRAME, timeout=20) for peer in peers]
                require(len(set(payloads)) == 1, 'human participants received different canonical frames')
                number, by_slot = q.decode_frame(payloads[0], len(room.slots))
                require(number == frame and all(by_slot[slot] == body for slot, body in human_inputs.items()),
                        'public frame number or human input differs')
                canonical = encode_frame(frame, by_slot)
                expected_journal.update(struct.pack('<I', len(canonical))+canonical)
                replica = await replay.process_frame(canonical)
                require(native.last_state['frame'] == frame and native.last_state['canonical_fnv1a64'] == replica.state['canonical_fnv1a64'],
                        'public frame does not reproduce authoritative native state')
                matched_frames += 1
                state = replica.state
                if frame == 0: initial = {entity['id'] for entity in state['entities']}
                for slot in room.bots:
                    for action in get_repeated_bytes(by_slot[slot], 2):
                        value = get_bytes(action, 1)
                        if value:
                            commands[slot] += 1
                            for group in get_repeated_bytes(value, 1):
                                if get_uint(group, 2) in (12, 88): ordered[slot].update(get_repeated_uint(group, 3))
                for entity in state['entities']:
                    slot = entity.get('army')
                    if slot in participant_damage:
                        participant_damage[slot] = max(participant_damage[slot], entity.get('current_damage', 0))
                    if slot not in room.bots: continue
                    key = entity['id']
                    damage[slot] = max(damage[slot], entity.get('current_damage', 0))
                    if key not in initial and entity.get('type') in room.match.decks_by_slot[slot]:
                        produced[slot].add(key)
                        if 'position' in entity:
                            position = entity['position']
                            if key in positions and positions[key] != position: moved[slot].add(key)
                            positions[key] = position
                if frame % 100 == 0:
                    trace.write(json.dumps(dict(frame=frame, canonical_fnv1a64=state['canonical_fnv1a64'],
                                                resources=state['resources'], game_state=state['game_state']))+'\n')
                if state['game_state']['complete'] and frame >= room.result_frame+19: break
        results = [json.loads(await peer.receive(p.MATCH_END, timeout=10)) for peer in peers]
        require(all(value == results[0] for value in results) and results[0]['result']['complete'], 'shared natural result missing')
        moving = {slot: len(produced[slot] & moved[slot] & ordered[slot]) for slot in room.bots}
        report.update(final_frame=frame, matched_native_replay_frames=matched_frames, game_state=results[0]['result'],
            bot_commands=commands, bot_max_damage=damage, bot_produced_units={slot: len(value) for slot, value in produced.items()},
            bot_ordered_moving_units=moving, participant_max_damage=participant_damage)
        require(all(moving.values()), 'one or more native bots did not produce and autonomously move units')
        # An unopposed attacker can win without taking damage. Observe actual
        # health loss in the shared match, not mandatory wounds on every bot.
        require(any(participant_damage.values()), 'no combat damage observed in the native match')
        with (output/'matches'/room.match_id/'frames.bin').open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''): actual_journal.update(chunk)
        require(actual_journal.digest() == expected_journal.digest(), 'delivered and accepted public frame journals differ')
        for peer in peers: await command(peer, q.RETURN, match=room.match_id)
        require(not server.community.public.entries and not server.community.public.offers and server.room_count() == 0,
                'public result return did not release all tickets/capacity')
        require(all(server.community.sessions[peer.profile].peer.room is None for peer in peers), 'returned player retained old room')
        report.update(passed=True, final_frame=frame, matched_native_replay_frames=matched_frames, game_state=results[0]['result'],
            bot_commands=commands, bot_max_damage=damage, bot_produced_units={slot: len(value) for slot, value in produced.items()},
            bot_ordered_moving_units=moving, exact_delivered_journal_sha256=expected_journal.hexdigest(),
            all_humans_returned=True, shared_worker_count=1)
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        coordinator.TICK = original_tick
        if server is not None: await server.close()
        await asyncio.gather(*(peer.close() for peer in peers))
        await asyncio.gather(*(worker.close() for worker in workers))
        if audit is not None: audit.close()
        report.update(worker_exit_codes=[worker.process.poll() for worker in workers],
            owned_workers_reaped=all(worker.process.poll() is not None for worker in workers),
            elapsed_seconds=time.monotonic()-started, source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_workers_reaped'] and report['worker_exit_codes'] == [0, 0]
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'mode', 'human_count', 'elapsed_seconds', 'final_frame',
                     'bot_ordered_moving_units', 'matched_native_replay_frames', 'worker_exit_codes') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', type=int, choices=(1, 2, 5), required=True)
    parser.add_argument('--humans', type=int, required=True)
    parser.add_argument('--frames', type=int, default=16000)
    args = parser.parse_args()
    args.assets, args.output = args.assets.resolve(), args.output.resolve()
    require(os.name == 'nt' and args.output.is_relative_to(ROOT/'local') and 1200 <= args.frames <= 24000,
            'bounded Windows/ignored evidence probe required')
    require(1 <= args.humans <= len(q.MODES[args.mode][1]) and args.humans < q.MODES[args.mode][0],
            'probe requires a supported human group and at least one server bot')
    return asyncio.run(run(args))


if __name__ == '__main__': raise SystemExit(main())
