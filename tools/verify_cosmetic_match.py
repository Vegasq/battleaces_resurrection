"""Qualify frozen human cosmetics in real native 1v1/2v2/2vAI simulation.

Uses locally imported assets and an actual changed native cosmetic selection.
Checks authoritative deck/identity bytes, JoinArmy canonicalization and twenty
native frames, then unforced worker close. It does not qualify client submission,
graphical effects, AI tactics, complete matches or protected backup deployment.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import traceback

from client_patch.transport.launcher import read_json
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.cosmetics import CosmeticCatalog
from server.game_data import GameTemplate, InputValidation, InputError, encode_player_input, encode_frame
from server.protobuf_wire import field_bytes, field_uint, field_packed_uint, get_uint, get_repeated_bytes, replace_fields
from server.worker_client import SimulationWorker
from server.worker_ai import BotRoster
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def sources():
    return core_hashes() | {Path(__file__).relative_to(ROOT).as_posix(): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


async def run(args):
    assets, output = args.assets.resolve(), args.output.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT/'local'), 'fresh ignored native Windows evidence required')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, scope=__doc__, source_sha256_at_start=sources(), modes=[])
    worker = None
    try:
        manifest = verify_assets(assets)
        require('cosmetic-catalog.json' in manifest['files'], 'import the current cosmetic catalog first')
        catalog = CosmeticCatalog(assets)
        value = read_json(args.selection, 4096);state = value.get('state', value)
        require(state['schema'] == 1 and state['build'] == 37822 and state['catalog_sha256'] == catalog.sha256,
                'native selection/catalog mismatch')
        changed, defaults = catalog.validate_selection(state['slots']), catalog.normalize_local()
        require(changed != defaults, 'changed native selection required')
        for mode, filename in ((1, 'map-1v1.pb.gz'), (2, 'map-2v2.pb.gz'), (5, 'map-2vai.pb.gz')):
            template = GameTemplate.load(assets/filename, catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
            bots, humans, names, roster, decks = {}, {}, set(), [], {}
            book = BotCatalog(assets, template=template)
            for slot in range(template.player_count):
                if mode == 5 and slot % 2:
                    bot = book.choose(mode, excluded_names=names, difficulty='normal')
                    bots[slot] = bot;names.add(bot.name)
                    roster.append(dict(slot=slot, player_id=slot+1, army_id=slot, name=bot.name, ai_profile_id=bot.profile))
                    decks[slot] = bot.deck.units
                else:
                    humans[slot] = changed if slot == 0 else defaults
                    roster.append(dict(slot=slot, player_id=slot+1, army_id=slot, name='Cosmetic Probe '+str(slot)))
                    decks[slot] = template.default_decks[slot]
            match = template.build_match(roster, decks, seed=1, game_name='cosmetic-probe-mode-'+str(mode),
                human_cosmetics=humans, cosmetic_catalog=catalog, bot_choices=bots if mode == 5 else None)
            validator = InputValidation(match, template)
            bot_inputs = BotRoster(match.raw_game_data, {slot:bot.profile for slot,bot in bots.items()}).make_inputs(0, {}) if bots else {}
            canonical = {}
            for slot in range(template.player_count):
                army = match.armies_by_slot[slot]
                if slot in humans:
                    snapshot = humans[slot]
                    require(match.cosmetics_by_slot[slot] == snapshot and
                        get_repeated_bytes(match.deck_messages_by_slot[slot], 3) == (snapshot.entitlement,) and
                        (get_uint(army, 5), get_uint(army, 6)) == (snapshot.banner, snapshot.portrait),
                        'authoritative human entitlement or identity mismatch')
                else:
                    require(match.deck_messages_by_slot[slot] == bots[slot].deck_message, 'human selection changed a frozen bot')
                join = field_uint(1, slot)+field_bytes(2, match.deck_messages_by_slot[slot])
                join += field_uint(3, get_uint(army, 5))+field_uint(4, get_uint(army, 6))
                canonical[slot] = (validator.validate_player_input(slot,
                    encode_player_input(match.identities_by_slot[slot], [field_bytes(3, join)]))
                    if slot in humans else bot_inputs[slot])
                if slot in humans:
                    forged_deck = replace_fields(match.deck_messages_by_slot[slot], {3:[field_bytes(3, field_packed_uint(3, (0xffffffff,)))]})
                    forged_join = replace_fields(join, {2:[field_bytes(2, forged_deck)]})
                    cleaned = validator.validate_player_input(slot,
                        encode_player_input(match.identities_by_slot[slot], [field_bytes(3, forged_join)]))
                    require(cleaned == canonical[slot], 'client cosmetic metadata escaped authoritative canonicalization')
                    wrong_identity = replace_fields(join, {4:[field_uint(4, 0xffffffff)]})
                    try:
                        validator.validate_player_input(slot,
                            encode_player_input(match.identities_by_slot[slot], [field_bytes(3, wrong_identity)]))
                    except InputError: pass
                    else: raise AssertionError('wrong portrait identity was accepted')
            working = output/('mode-'+str(mode));working.mkdir()
            worker = await SimulationWorker.create(match.raw_game_data, assets/'Simulation.dll', working_directory=working)
            result = dict(mode=mode, worker_pid=worker.pid, human_slots=list(humans), bot_slots=list(bots),
                raw_match_sha256=match.raw_sha256, catalog_sha256=catalog.sha256,
                human_state={slot:dict(slots=snapshot.slots, portrait=snapshot.portrait, banner=snapshot.banner,
                                      entitlement_sha256=hashlib.sha256(snapshot.entitlement).hexdigest()) for slot,snapshot in humans.items()},
                initial_state=await worker.state(31, include_entities=True))
            frames = []
            for number in range(20):
                inputs = canonical if number == 0 else {slot:encode_player_input(match.identities_by_slot[slot]) for slot in range(template.player_count)}
                frame = encode_frame(number, inputs)
                processed = await worker.process_frame(frame)
                require(processed.frame == number, 'native frame sequence differs')
                frames.append(dict(number=number, input_sha256=hashlib.sha256(frame).hexdigest()))
            result.update(frames=frames, final_state=await worker.state(31, include_entities=True))
            await worker.close()
            require(worker.process.poll() == 0, 'native worker did not exit cleanly')
            result.update(worker_exit_code=0, reaped=True)
            report['modes'].append(result);worker = None
        report.update(passed=True, complete_slots=17, join_canonicalization=True, identity_rejection=True,
                      native_frames=60, catalog_sha256=catalog.sha256)
    except BaseException as error:
        report.update(passed=False, error=repr(error), traceback=traceback.format_exc())
    finally:
        if worker is not None: await worker.close()
        report['source_sha256_at_finish'] = sources()
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged']
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps({key:report[key] for key in ('passed', 'native_frames', 'catalog_sha256', 'error') if key in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('assets', 'output', 'selection'): parser.add_argument('--'+key, type=Path, required=True)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
