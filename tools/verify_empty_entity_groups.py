"""Compare controlled native commands in two isolated simulation workers.

No game UI, production host, player identity, or native DLL in this coordinator.
Raw authored empty groups go only to the private owned native worker, to test
the shipped engine's semantics independently of the network validator.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from server.game_data import GameTemplate, InputValidation, encode_player_input, encode_frame
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint
from server.worker_client import SimulationWorker

ROOT = Path(__file__).resolve().parents[1]


def group(ids):
    return field_uint(1, 3) + field_uint(2, 34) + field_packed_uint(3, ids)


def command(groups, *, queued=False):
    return field_bytes(1, b''.join(field_bytes(1, value) for value in groups) +
                       (field_uint(2, 1) if queued else b'') + field_bytes(3, field_bytes(1, b'')))


async def run(args):
    output = args.output.resolve()
    assert output.is_relative_to(ROOT/'local')
    output.mkdir(parents=True, exist_ok=False)
    assets = args.assets.resolve()
    template = GameTemplate.load(assets/'map-1v1.pb.gz', catalog_path=assets/'unit-catalog.json',
                                 descriptors_path=assets/'descriptors')
    match = template.build_match([dict(slot=i, player_id=i+1, name=f'Owned empty group {i}')
                                  for i in (0, 1)], template.default_decks,
                                 seed=642301, game_name='empty-entity-group-proof')
    report = dict(passed=False, frames=260, command_frames=[200, 230], validated_input_path=args.validate,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    workers = []
    try:
        for _ in range(2):
            workers.append(await SimulationWorker.create(match.raw_game_data, assets/'Simulation.dll'))
        initial = await workers[0].state(31, include_entities=True)
        hq = next(e['id'] for e in initial['entities'] if e.get('army')==0 and e.get('type')==3)
        empty = command([group([])], queued=True)
        validator = InputValidation(match, template)
        try:
            normalized = validator.validate_player_input(0, encode_player_input(match.identities_by_slot[0], [empty]))
            report['validator_accepts_empty'] = True
            report['normalized_bytes'] = len(normalized)
        except ValueError as error:
            report['validator_accepts_empty'] = False
            report['validator_error'] = str(error)
        checked = []
        for frame in range(260):
            messages = []
            for changed in (False, True):
                players = {}
                for slot in (0, 1):
                    actions = []
                    if frame==0:
                        actions.append(field_bytes(3, field_uint(1, slot) +
                                                   field_bytes(2, match.deck_messages_by_slot[slot])))
                    if slot==0 and changed and frame==230:
                        actions.extend([empty]*16)
                    if slot==0 and frame==200:
                        groups = [group([]), group([hq]), group([])] if changed else [group([hq])]
                        actions.append(command(groups))
                        if changed: actions.extend([empty]*15)
                    players[slot] = encode_player_input(match.identities_by_slot[slot], actions)
                messages.append(validator.encode_frame(frame, players) if args.validate else encode_frame(frame, players))
            results = await asyncio.gather(*(worker.process_frame(message)
                                            for worker, message in zip(workers, messages)))
            assert results[0].state['canonical_fnv1a64']==results[1].state['canonical_fnv1a64'], frame
            assert results[0].state['resources']==results[1].state['resources'], frame
            checked.append(frame)
        report.update(passed=True, matching_frames=checked, processes=[w.pid for w in workers],
                      selected_unit=match.decks_by_slot[0][0],
                      created_units=[e['id'] for e in workers[1].last_state['entities']
                                     if e.get('army')==0 and e.get('type')==match.decks_by_slot[0][0]])
        assert report['created_units'], 'mixed empty groups must preserve the valid build'
    except BaseException as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}')
    finally:
        await asyncio.gather(*(worker.close() for worker in workers))
        report['exit_codes'] = [w.process.poll() for w in workers]
        report['passed'] = report['passed'] and report['exit_codes']==[0, 0]
        (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    return not report['passed']


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validate', action='store_true', help='run the production input validator before native simulation')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
