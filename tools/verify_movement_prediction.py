"""Headless native movement speculation and journal-rebuild qualification.

Uses only owned SimulationWorker processes and locally imported original assets.
No Unity client, live server, view teleport, memory copy or checkpoint restore.
Equality concerns decoded observable state; hidden-world equality is unproven.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import time
import traceback

from server.assets import verify_assets
from server.game_data import GameTemplate, InputValidation, encode_player_input
from server.native_simulation import _Buffer
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_uint
from server.worker_client import SimulationWorker

ROOT = Path(__file__).resolve().parents[1]
BUILD_FRAME = 140


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(value):
    raw = value if isinstance(value,bytes) else json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()


def position_message(point):
    """Original ProtocolUtil.ToProto: float32 coordinates times2**32, truncate."""
    if len(point) != 3:
        raise ValueError('a movement target requires three coordinates')
    result = b''
    for number,value in enumerate(point,1):
        if type(value) not in (int,float) or not math.isfinite(value) or not -2**31 < value < 2**31:
            raise ValueError('target coordinate outside native Q32.32 range')
        value = struct.unpack('<f',struct.pack('<f',value))[0]
        fixed = int(value*2**32)
        if not -2**63 <= fixed < 2**63:
            raise ValueError('target coordinate outside signed int64')
        result += field_uint(number,fixed & (2**64-1))
    return result


def execute(entity, ability, command):
    group = field_uint(1,entity['type'])+field_uint(2,ability)+field_packed_uint(3,[entity['id']])
    return field_bytes(1,field_bytes(1,group)+field_bytes(3,command))


def move_action(entity, target):
    return execute(entity,12,field_bytes(3,field_bytes(1,position_message(target))))


def decode_cooldowns(raw):
    """Selected original SimFrame.Charges structs, preserving native vector order.

    Static exact-build getters: SimFrame.get_Charges3a120e0 selects field16;
    EntityAbilityChargesBuffer.Charges3a04f90 uses field1/stride20;
    SimAbilityCharge getters read uint,float,uint,uint,float at0,4,8,12,16.
    The entity-to-vector lookup and hidden ability state remain outside scope.
    """
    b = _Buffer(raw)
    root = b.read('I',0)
    table = b.table(root,16)
    start,count = b.vector(table,1,20)
    require(count <= 32768,'cooldown observation vector exceeds bound')
    rows = []
    for index in range(count):
        ability,current,maximum,available,cooldown = struct.unpack_from('<IfIIf',raw,start+20*index)
        require(math.isfinite(current) and math.isfinite(cooldown),'nonfinite native cooldown observation')
        rows.append(dict(index=index,ability=ability,current_charges=current,max_charges=maximum,
                         available_recharges=available,cooldown=cooldown))
    return rows


def fixture(assets):
    verify_assets(assets)
    template = GameTemplate.load(assets/'map-1v1.pb.gz',catalog_path=assets/'unit-catalog.json',
                                 descriptors_path=assets/'descriptors')
    crab = next(key for key,value in template.catalog.items() if value.get('name','').casefold() == 'crab')
    require(template.default_decks[0][0] == crab and 12 in template.entity_abilities[crab],
            'fixture requires the original default-slot0 Crab and its Move12 ability')
    roster = [dict(slot=slot,army_id=slot,player_id=slot+1,name='Prediction fixture '+str(slot)) for slot in (0,1)]
    match = template.build_match(roster,template.default_decks,seed=20261109,game_name='movement-prediction-fixture')
    return template,match,crab


def canonical_frame(template,match,number,actions,state=None):
    lookup = {entity['id']:(entity.get('army'),entity.get('type')) for entity in (state or {}).get('entities',[])}
    validation = InputValidation(match,template,entity_lookup=lookup.get if state else None)
    bodies = {slot:encode_player_input(match.identities_by_slot[slot],actions.get(slot,())) for slot in (0,1)}
    return validation.encode_frame(number,bodies)


def opening_actions(template,match,number,state):
    actions = {0:[],1:[]}
    if number == 0:
        for slot in (0,1):
            join = field_uint(1,slot)+field_bytes(2,match.deck_messages_by_slot[slot])
            for target,source in ((3,5),(4,6)):
                value = get_uint(match.armies_by_slot[slot],source)
                if value:
                    join += field_uint(target,value)
            actions[slot].append(field_bytes(3,join))
    if number == BUILD_FRAME:
        builders = [(entity,ability) for entity in state['entities'] if entity.get('army') == 0
                    for ability in template.entity_abilities.get(entity.get('type'),())
                    if template.build_ability_slots.get(ability) == 0]
        require(builders,'original army has no slot0 build ability')
        builder,ability = min(builders,key=lambda item:(item[0]['id'],item[1]))
        actions[0].append(execute(builder,ability,field_bytes(1,b'')))
    return actions


def selected_unit(state,crab):
    units = [entity for entity in state['entities'] if entity.get('army') == 0 and entity.get('type') == crab]
    require(len(units) == 1 and 'position' in units[0],'ordinary build did not produce exactly one owned Crab')
    return units[0]


def targets(unit):
    x,y,z = unit['position']
    length = math.hypot(x,z)
    dx,dz = (-x/length,-z/length) if length > .1 else (1.,0.)
    return [x+8*dx,y,z+8*dz],[x-8*dz,y,z+8*dx]


async def observed(world, viewers):
    state = await world.state(31,include_entities=True)
    state = {key:value for key,value in state.items() if key != 'raw_sha256'}
    # The all-entity viewer31 omits private charge entries. Query each original
    # alliance separately; an empty result is reported as unavailable coverage.
    cooldowns = {viewer:decode_cooldowns(await world.snapshot(viewer)) for viewer in viewers}
    health = [[entity['id'],entity.get('max_health'),entity.get('current_damage')] for entity in state['entities']]
    return dict(state=state,cooldowns=cooldowns,
                hashes=dict(parsed_state=digest(state),resources=digest(state['resources']),
                            health=digest(health),cooldowns=digest(cooldowns)))


def equal_observations(actual,expected):
    require(actual['state'] == expected['state'],'all parsed native state fields differ after authoritative reconstruction')
    require(actual['cooldowns'] == expected['cooldowns'],'native observable cooldown/charge vector differs')


async def discovery(args,template,match,crab,create_world):
    world = await create_world(match.raw_game_data)
    before_build = None
    for number in range(240):
        state = world.last_state
        if number == BUILD_FRAME:
            before_build = [entity for entity in state['entities'] if entity.get('army') == 0 and entity.get('type') == crab]
        raw = canonical_frame(template,match,number,opening_actions(template,match,number,state),state)
        await world.process_frame(raw,dt_ms=50)
    require(before_build == [],'Crab existed before the original build action')
    unit = selected_unit(world.last_state,crab)
    wrong,_ = targets(unit)
    positions = [unit['position']]
    for number in range(240,252):
        actions = {0:[move_action(unit,wrong)]} if number == 240 else {}
        raw = canonical_frame(template,match,number,actions,world.last_state)
        await world.process_frame(raw,dt_ms=50)
        positions.append(selected_unit(world.last_state,crab)['position'])
    distance = math.dist(positions[0],positions[-1])
    require(distance > .05,'valid original Move12 did not change native Crab position')
    value = await observed(world,sorted(set(template.alliances.values())))
    return dict(mode='discovery',steps=252,crab_type=crab,entity=unit['id'],build_frame=BUILD_FRAME,
                move_frame=240,target=wrong,positions=positions,distance=distance,observations=value)


async def correction_case(args,template,match,crab,history,create_world):
    from client_patch.transport.prediction import PredictionController
    controller = await PredictionController.create(match.raw_game_data,create_world,max_ahead=12,max_replay_frames=1200)
    reference = await create_world(match.raw_game_data)
    journal = []
    viewers = sorted(set(template.alliances.values()))
    try:
        for number in range(history):
            state = controller.world.last_state
            raw = canonical_frame(template,match,number,opening_actions(template,match,number,state),state)
            await controller.confirm(raw)
            await reference.process_frame(raw,dt_ms=50)
            journal.append(raw)
        origin = selected_unit(controller.world.last_state,crab)
        wrong,right = targets(origin)
        predicted_positions = [origin['position']]
        authoritative = []
        for number in range(history,history+args.ahead):
            speculative = {0:[move_action(origin,wrong)]} if number == history else {}
            confirmed = {0:[move_action(origin,right)]} if number == history else {}
            raw = canonical_frame(template,match,number,speculative,controller.world.last_state)
            truth = canonical_frame(template,match,number,confirmed,reference.last_state)
            await controller.predict(raw)
            await reference.process_frame(truth,dt_ms=50)
            authoritative.append(truth)
            predicted_positions.append(selected_unit(controller.world.last_state,crab)['position'])
        predicted = await observed(controller.world,viewers)
        control = await observed(reference,viewers)
        require(controller.confirmed_frame == history-1,'wrong speculative movement was already confirmed')
        require(math.dist(predicted_positions[0],predicted_positions[-1]) > .05,'speculation did not move a real native unit')
        reference_unit = selected_unit(control['state'],crab)
        require(math.dist(predicted_positions[-1],reference_unit['position']) > .05,'different authoritative move did not diverge')
        started = time.perf_counter()
        confirmation = await controller.confirm(authoritative[0])
        rebuild_ms = (time.perf_counter()-started)*1000
        require(confirmation.status == 'corrected','wrong target did not trigger reconstruction')
        corrected = await observed(controller.world,viewers)
        equal_observations(corrected,control)
        for raw in authoritative[1:]:
            await controller.confirm(raw)
        journal.extend(authoritative)
        continuation = []
        for number in range(history+args.ahead,history+args.ahead+args.continuation):
            raw = canonical_frame(template,match,number,{},controller.world.last_state)
            await controller.predict(raw)
            await controller.confirm(raw)
            await reference.process_frame(raw,dt_ms=50)
            actual,expected = await observed(controller.world,viewers),await observed(reference,viewers)
            equal_observations(actual,expected)
            continuation.append(dict(frame=number,hashes=actual['hashes']))
            journal.append(raw)
        path = args.output/f'confirmed-history-{history}.bin'
        with path.open('xb') as stream:
            for raw in journal:
                stream.write(struct.pack('<I',len(raw))+raw)
        metrics = controller.metrics
        cooldown_count = sum(len(rows) for rows in corrected['cooldowns'].values())
        return dict(history_frames=history,prediction_frames=args.ahead,continuation_frames=len(continuation),
            crab_type=crab,entity=origin['id'],wrong_target=wrong,authoritative_target=right,
            speculative_positions=predicted_positions,authoritative_position=reference_unit['position'],
            corrected_position=selected_unit(corrected['state'],crab)['position'],rebuild_ms=rebuild_ms,
            replayed_frames=confirmation.replayed_frames,controller_metrics=metrics,
            reconstruction_cost_scope='fresh Python worker startup, IPC, parsed-state fingerprints, journal replay and old-worker cleanup; not engine-only SimStep',
            reconstruction_phases_ms={name:metrics[key]*1000 for name,key in
                (('factory_startup','last_factory_create_seconds'),('replay_with_ipc','last_replay_seconds'),('old_world_cleanup','last_cleanup_seconds'))},
            corrected_hashes=corrected['hashes'],reference_hashes=control['hashes'],
            cooldown_observations=cooldown_count,cooldown_positive_coverage=cooldown_count > 0,
            cooldown_viewers=viewers,continuation=continuation,
            confirmed_journal_sha256=digest(path.read_bytes()),parsed_state_equivalent=True)
    finally:
        await controller.close()
        await reference.close()


async def run(args):
    args.assets,args.output = args.assets.resolve(),args.output.resolve()
    require(os.name == 'nt' and args.output.is_relative_to(ROOT/'local'),'owned Windows worker output must be ignored local evidence')
    args.output.mkdir(parents=True,exist_ok=False)
    source_names = ['tools/verify_movement_prediction.py','server/native_simulation.py','server/worker_client.py','server/game_data.py']
    if not args.discovery_only:
        source_names.append('client_patch/transport/prediction.py')
    source_hashes = {name:digest((ROOT/name).read_bytes()) for name in source_names}
    report = dict(passed=False,scope=__doc__,source_sha256_at_start=source_hashes,
                  limitations=['No graphical client integration or network timing.','Parsed observables do not prove complete hidden-world equality.',
                    'Correction recreates a native world and replays its bounded journal; no checkpoint/clone API.',
                    'Cooldown vector entries are compared in original order; entity lookup and hidden ability state are not restored.'])
    workers = []
    started = time.perf_counter()
    async def create_world(data):
        worker = await SimulationWorker.create(data,args.assets/'Simulation.dll',working_directory=args.output)
        workers.append(worker)
        require(sum(worker.process.poll() is None for worker in workers) <= (1 if args.discovery_only else 3),
                'owned native worker concurrency exceeded declared bound')
        (args.output/'processes.json').write_text(json.dumps([dict(pid=w.pid,exit_code=w.process.poll()) for w in workers],indent=2)+'\n')
        return worker
    try:
        template,match,crab = fixture(args.assets)
        report.update(bootstrap_sha256=digest(match.raw_game_data),simulation_sha256=digest((args.assets/'Simulation.dll').read_bytes()),
                      asset_manifest_sha256=digest((args.assets/'asset-manifest.json').read_bytes()),
                      catalog_sha256=digest((args.assets/'unit-catalog.json').read_bytes()),crab_type=crab,
                      crab_catalog_name=template.catalog[crab]['name'],selected_decks=dict(match.decks_by_slot))
        if args.discovery_only:
            report['discovery'] = await discovery(args,template,match,crab,create_world)
        else:
            report['cases'] = []
            for history in args.histories:
                report['cases'].append(await correction_case(args,template,match,crab,history,create_world))
        report['passed'] = True
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}',traceback=traceback.format_exc())
    finally:
        cleanup = await asyncio.gather(*(worker.close() for worker in workers),return_exceptions=True)
        report.update(cleanup_errors=[repr(value) for value in cleanup if isinstance(value,BaseException)],
            workers=[dict(pid=w.pid,exit_code=w.process.poll(),failure=w.failure,
                          reaped=w.process.poll() is not None and w._cleanup_task is not None and
                                 w._cleanup_task.done() and not w._stderr_thread.is_alive()) for w in workers],
            source_sha256_at_finish={name:digest((ROOT/name).read_bytes()) for name in source_names},
            elapsed_seconds=time.perf_counter()-started)
        report['passed'] &= not report['cleanup_errors'] and report['source_sha256_at_start'] == report['source_sha256_at_finish'] and all(
            value['exit_code'] == 0 and not value['failure'] and value['reaped'] for value in report['workers'])
        (args.output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','error','elapsed_seconds','workers','cases') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--histories',type=int,nargs='+',default=(240,600))
    parser.add_argument('--ahead',type=int,default=8)
    parser.add_argument('--continuation',type=int,default=20)
    parser.add_argument('--discovery-only',action='store_true')
    args = parser.parse_args()
    require(1 <= len(args.histories) <= 3 and len(set(args.histories)) == len(args.histories) and
            all(160 <= value <= 1000 for value in args.histories) and
            2 <= args.ahead <= 12 and 1 <= args.continuation <= 40 and
            max(args.histories)+args.ahead+args.continuation <= 1200,'bounded native history/prediction/continuation required')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
