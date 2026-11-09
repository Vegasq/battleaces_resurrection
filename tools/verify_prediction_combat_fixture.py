"""Create an owned original-native combat journal for later checkpoint parity.

No game client, live server, DLL patch, synthetic spawn, damage injection or
checkpoint is used. Parsed observations do not prove complete hidden state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.native_simulation import NativeSimulation, SUPPORTED_DLL_SHA256, _Buffer, decode_snapshot
from server.protobuf_wire import field_bytes, parse_fields
from server.worker_client import _WindowsJob
from tools.prediction_native import own_thread_ids
from tools.verify_movement_prediction import (canonical_frame, decode_cooldowns, execute,
                                             fixture, opening_actions, position_message)

SOURCE_FILES = ('tools/verify_prediction_combat_fixture.py', 'tools/verify_movement_prediction.py',
                'tools/prediction_native.py', 'server/native_simulation.py', 'server/game_data.py',
                'server/protobuf_wire.py', 'server/worker_client.py')
BUILD_FRAMES = (140, 180, 220)
ORDER_AFTER = 240


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def source_hashes():
    return {name: digest((ROOT / name).read_bytes()) for name in SOURCE_FILES}


def attack_ability(template, crab):
    # Exact shipped AbilityConfig oneof field11 is attack_ability. The original
    # ObjectiveOwner.AttackMoveUnitsToTarget resolves the configured attack
    # group, creates ExecuteTargetGroundCommand, then EnqueueInputCommand.
    choices = [key for key in template.entity_abilities[crab]
               if any(field.number == 11 for field in parse_fields(template.abilities[key]))]
    require(len(choices) == 1, 'original Crab must have exactly one configured AttackAbility')
    return choices[0]


def attack_move_action(entity, ability, target):
    # Shipped CommandData.target_ground_command_data=3, position=1; Position
    # int64 Q32.32 is encoded by the already qualified original float32 rule.
    return execute(entity, ability, field_bytes(3, field_bytes(1, position_message(target))))


def entity_states(raw):
    # Original SimFrame.get_States selects field4. UpdateStateBuffer378d240
    # consumes sparse entity IDs and four-byte state values. Shipped
    # game_types_pb EntityState defines DEAD6 and COOLDOWN4.
    buffer = _Buffer(raw)
    table = buffer.table(buffer.read('I', 0), 4)
    ids, count = buffer.vector(table, 0, 4)
    states, state_count = buffer.vector(table, 1, 4)
    require(count == state_count and count <= 32768, 'invalid native entity-state vector')
    result = {buffer.read('I', ids+4*index): buffer.read('I', states+4*index) for index in range(count)}
    require(len(result) == count, 'duplicate native entity-state ID')
    return result


def owned_crabs(state, crab, slot=None):
    return [row for row in state['entities'] if row.get('type') == crab and
            row.get('army') in ((0, 1) if slot is None else (slot,)) and 'position' in row]


def actions_for_frame(template, match, crab, ability, frame, state, ordered):
    actions = opening_actions(template, match, 0, state) if frame == 0 else {0: [], 1: []}
    if frame in BUILD_FRAMES:
        for slot in (0, 1):
            choices = [(row, key) for row in state['entities'] if row.get('army') == slot
                       for key in template.entity_abilities.get(row.get('type'), ())
                       if template.build_ability_slots.get(key) == 0]
            require(choices, 'army has no original deck-slot0 build ability')
            builder, key = min(choices, key=lambda item: (item[0]['id'], item[1]))
            actions[slot].append(execute(builder, key, field_bytes(1, b'')))
    if frame >= ORDER_AFTER:
        for unit in owned_crabs(state, crab):
            identity = (unit['army'], unit['id'])
            if identity not in ordered:
                actions[unit['army']].append(attack_move_action(unit, ability, [0., 0., 0.]))
                ordered.add(identity)
    return actions


def child(args):
    output, shared, assets = args.output.resolve(), args.shared.resolve(), args.assets.resolve()
    require(output.is_relative_to(ROOT / 'local') and output.is_dir(), 'owned local child output required')
    deadline = time.monotonic()+10
    while not (output/'start-after-job-assigned').exists():
        require(time.monotonic() < deadline, 'parent did not assign owned Job before native start')
        time.sleep(.01)
    os.chdir(output)
    report = dict(passed=False, pid=os.getpid(), scope=__doc__, source_sha256_at_start=source_hashes())
    started, world, frame = time.perf_counter(), None, -1
    try:
        original_sha = digest((assets/'Simulation.dll').read_bytes())
        require(original_sha == SUPPORTED_DLL_SHA256, 'exact unmodified original Simulation.dll required')
        template, match, crab = fixture(assets)
        ability = attack_ability(template, crab)
        report.update(simulation_sha256=original_sha, bootstrap_sha256=digest(match.raw_game_data),
                      crab_type=crab, attack_ability=ability, selected_decks=dict(match.decks_by_slot),
                      asset_manifest_sha256=digest((assets/'asset-manifest.json').read_bytes()),
                      descriptor_sha256={name: digest((assets/'descriptors'/name).read_bytes()) for name in
                        ('game_config_pb.proto.json', 'game_structures_pb.proto.json', 'game_types_pb.proto.json')},
                      static_encoding_evidence=dict(original_gameassembly_sha256='e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758',
                        attack_move='ObjectiveOwner.AttackMoveUnitsToTarget RVA3d797f0: resolves attack group then creates ExecuteTargetGroundCommand at3d79f1e and enqueues3d79fb4',
                        to_proto='ExecuteTargetGroundCommand.ToProto RVA37ae100; ground CommandData field3, Position Q32.32'))
        (shared/'bootstrap.pb').write_bytes(match.raw_game_data)
        before_threads = own_thread_ids()
        world = NativeSimulation(match.raw_game_data, assets/'Simulation.dll')
        after_threads = own_thread_ids()
        report['added_world_thread_ids'] = sorted(set(after_threads)-set(before_threads))
        require(len(report['added_world_thread_ids']) == 3, 'ordinary unmodified world did not create its three workers')
        state = world.state(31, include_entities=True)
        state.pop('raw_sha256', None)
        ordered, spawned, disappeared, dead, damage, cooldown_states = set(), {}, {}, {}, {}, set()
        positions, maximum_charges, charge_changes, previous_charge_hash = {}, 0, 0, None
        min_pair = None
        observations, action_rows = [], []
        with (shared/'canonical-frames.bin').open('xb') as journal, (output/'states.jsonl').open('x', encoding='utf-8') as states:
            for frame in range(args.frames):
                actions = actions_for_frame(template, match, crab, ability, frame, state, ordered)
                raw = canonical_frame(template, match, frame, actions, state)
                journal.write(struct.pack('<I', len(raw))+raw)
                world.process_frame(raw, dt_ms=50)
                snapshot = world.snapshot(31)
                state = decode_snapshot(snapshot, 31, include_entities=True)
                state.pop('raw_sha256', None)
                require(state['frame'] == frame, 'native frame counter differs')
                modes = entity_states(snapshot)
                units = owned_crabs(state, crab)
                visible = {unit['id'] for unit in units}
                for unit in units:
                    entity = unit['id']
                    spawned.setdefault(entity, dict(frame=frame, army=unit['army']))
                    positions.setdefault(entity, []).append(unit['position'])
                    if unit.get('current_damage', 0) > 0:
                        damage.setdefault(entity, dict(frame=frame, army=unit['army'], damage=unit['current_damage'],
                                                       max_health=unit.get('max_health')))
                    if modes.get(entity) == 4:
                        cooldown_states.add(entity)
                health_lookup = {row['id']: row for row in state['entities']}
                for entity, row in spawned.items():
                    if modes.get(entity) == 6:
                        health = health_lookup.get(entity, {})
                        dead.setdefault(entity, dict(frame=frame, army=row['army'], damage=health.get('current_damage'),
                                                     max_health=health.get('max_health')))
                    if entity not in visible:
                        disappeared.setdefault(entity, dict(frame=frame, army=row['army'], previous_damage=damage.get(entity)))
                for index, unit in enumerate(units):
                    for other in units[index+1:]:
                        distance = math.dist(unit['position'], other['position'])
                        if min_pair is None or distance < min_pair['distance']:
                            min_pair = dict(frame=frame, entities=[unit['id'], other['id']], distance=distance,
                                            armies=[unit['army'], other['army']])
                charges = {str(viewer): decode_cooldowns(world.snapshot(viewer)) for viewer in sorted(set(template.alliances.values()))}
                maximum_charges = max(maximum_charges, sum(len(rows) for rows in charges.values()))
                charge_hash = digest(charges)
                if previous_charge_hash is not None and charge_hash != previous_charge_hash:
                    charge_changes += 1
                previous_charge_hash = charge_hash
                row = dict(frame=frame, input_sha256=digest(raw), state_sha256=digest(state), state=state,
                           entity_states=modes, ability_charges=charges)
                states.write(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n')
                observations.append({key: row[key] for key in ('frame', 'input_sha256', 'state_sha256')})
                if any(actions.values()):
                    action_rows.append(dict(frame=frame, counts={slot: len(values) for slot, values in actions.items()},
                                            input_sha256=row['input_sha256']))
                if frame%100 == 0:
                    journal.flush();states.flush()
                    write(output/'progress.json', dict(pid=os.getpid(), frame=frame, spawned=len(spawned),
                                                      damaged=len(damage), dead=len(dead), disappeared=len(disappeared)))
        displacements = {entity: max(math.dist(values[0], point) for point in values) for entity, values in positions.items()}
        report.update(frames=observations, frame_count=len(observations), action_frames=action_rows,
                      ordinary_build_frames=BUILD_FRAMES, attack_orders=len(ordered), spawned=spawned,
                      damaged=damage, dead=dead, disappeared=disappeared, maximum_displacement=displacements,
                      closest_crab_pair=min_pair, attack_cooldown_state_entities=sorted(cooldown_states),
                      maximum_ability_charge_entries=maximum_charges, ability_charge_vector_changes=charge_changes,
                      canonical_journal_sha256=digest((shared/'canonical-frames.bin').read_bytes()))
        require(all(sum(row['army'] == slot for row in spawned.values()) >= 2 for slot in (0, 1)),
                'both armies did not ordinarily build multiple original Crabs')
        require(all(any(row['army'] == slot for row in damage.values()) for slot in (0, 1)), 'both armies lacked actual HP damage')
        require(dead and disappeared and any(entity in disappeared for entity in dead), 'no actual DEAD6 followed by despawn observed')
        require(all(any(spawned[entity]['army'] == slot and value > 1 for entity, value in displacements.items()) for slot in (0, 1)),
                'validated original AttackMove did not move both armies')
        report['limitations'] = ['No checkpoint/rollback, graphical rendering or live-network proof.',
            'Parsed observables do not establish complete hidden native state equality.',
            'Closest unit-pair distance is crowd/proximity evidence, not an instrumented collision-solver assertion.',
            'Ability charge vectors are reported separately; empty entries do not prove ability-charge cooldown behavior.']
        report['passed'] = True
    except BaseException as error:
        report.update(error=type(error).__name__+': '+str(error), traceback=traceback.format_exc())
    finally:
        try:
            if world is not None:
                world.close()
            report['native_world_closed'] = world is None or world.closed
            if 'before_threads' in locals():
                require(own_thread_ids() == before_threads, 'owned native pool threads remained after world close')
            require(digest((assets/'Simulation.dll').read_bytes()) == SUPPORTED_DLL_SHA256, 'original disk DLL changed')
        except BaseException as error:
            report.update(passed=False, cleanup_error=repr(error))
        report.update(last_frame=frame, elapsed_seconds=time.perf_counter()-started,
                      source_sha256_at_finish=source_hashes())
        report['passed'] &= report['source_sha256_at_start'] == report['source_sha256_at_finish']
        write(output/'report.json', report)
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'frame_count', 'attack_orders', 'elapsed_seconds') if key in report}))
    return 0 if report['passed'] else 1


def parent(args):
    output = args.output.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT/'local') and not output.exists(), 'fresh owned local Windows output required')
    output.mkdir(parents=True);shared=output/'shared';shared.mkdir();folder=output/'baseline';folder.mkdir()
    report = dict(passed=False, scope=__doc__, source_sha256_at_start=source_hashes(), children=[])
    started=time.perf_counter();process=job=None;forced=False
    try:
        command=[sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--child', '--assets', str(args.assets.resolve()),
                 '--output', str(folder), '--shared', str(shared), '--frames', str(args.frames)]
        with (folder/'stdout.log').open('xb') as stdout, (folder/'stderr.log').open('xb') as stderr:
            process=subprocess.Popen(command, cwd=folder, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            row=dict(pid=process.pid, command=command, retained_popen_handle=True, job_assigned=False)
            report['children'].append(row)
            try:
                job=_WindowsJob(process.pid);row['job_assigned']=True;write(output/'processes.json', report['children'])
                (folder/'start-after-job-assigned').write_text('owned Job assigned\n')
                row['exit_code']=process.wait(timeout=args.timeout)
            finally:
                if process.poll() is None:
                    forced=True;process.terminate()
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                if job is not None:job.close()
                row.update(exit_code=process.poll(), reaped=process.poll() is not None, forced_cleanup=forced)
                write(output/'processes.json', report['children'])
        require(row['exit_code'] == 0 and not forced, 'owned combat child failed; retain its report/logs')
        report['baseline']=json.loads((folder/'report.json').read_text())
        require(report['baseline']['passed'], 'combat fixture did not meet positive evidence gates')
        report['passed']=True
    except BaseException as error:
        report.update(error=type(error).__name__+': '+str(error), traceback=traceback.format_exc())
    finally:
        report.update(source_sha256_at_finish=source_hashes(), elapsed_seconds=time.perf_counter()-started)
        report['passed'] &= report['source_sha256_at_start'] == report['source_sha256_at_finish']
        write(output/'verification.json', report)
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'elapsed_seconds', 'children') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=1200)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--shared', type=Path, help=argparse.SUPPRESS)
    args=parser.parse_args()
    require(600 <= args.frames <= 1200 and 10 <= args.timeout <= 180, 'bounded600..1200frames/10..180seconds required')
    require(not args.child or args.shared is not None, 'owned child requires explicit shared output')
    return child(args) if args.child else parent(args)


if __name__ == '__main__':
    raise SystemExit(main())
