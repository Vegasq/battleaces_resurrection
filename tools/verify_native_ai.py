"""Isolated headless original AI + Simulation proof; no Unity client or service.

Uses locally imported assets and real native decisions, including the original
four-army maps with --catalog-bots. Does not qualify graphical clients,
four-player transport, public queues or online fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback

from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.game_data import GameTemplate, encode_frame, encode_player_input
from server.native_ai import NativeAI
from server.native_simulation import NativeSimulation
from server.protobuf_wire import field_bytes, field_uint, get_bytes, get_repeated_bytes, get_repeated_uint, get_uint
from server.worker_client import _WindowsJob
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    return core_hashes() | {'tools/verify_native_ai.py': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def child(args):
    began = time.monotonic()
    report = dict(passed=False, scope=__doc__, pid=os.getpid(), source_sha256_at_start=source_hashes())
    output, assets = args.output.resolve(), args.assets.resolve()
    try:
        verify_assets(assets)
        book = RuleBook(assets)
        map_name = {1: 'map-1v1.pb.gz', 2: 'map-2v2.pb.gz', 5: 'map-2vai.pb.gz'}[args.mode]
        template = GameTemplate.load(assets/map_name, catalog_path=assets/'unit-catalog.json',
                                     descriptors_path=assets/'descriptors')
        choices = None
        if args.catalog_bots:
            require(not args.decks, 'catalog bots must retain their original compatible decks')
            catalog = BotCatalog(assets, template=template, rules=book)
            generator = random.Random(args.selection_seed)  # Reproducible engineering selection only.
            choices, names = {}, []
            strengths = args.strengths.split(',')
            if len(strengths) == 1: strengths *= template.player_count
            require(len(strengths) == template.player_count and all(s in ('easy', 'normal', 'hard') for s in strengths),
                    'one strength or one per army required')
            for army in template.armies:
                role = 'teammates' if args.mode in (2, 5) and army % 2 == 0 else 'opponents'
                choices[army] = catalog.choose(args.mode, role=role, excluded_names=names,
                                               difficulty=strengths[army], randbelow=generator.randrange)
                names.append(choices[army].name)
            bots = {army: choice.profile for army, choice in choices.items()}
            roster = [dict(slot=army, army_id=army, player_id=army+1, name=choice.name, ai_profile_id=choice.profile)
                      for army, choice in choices.items()]
            decks = {army: choice.deck.units for army, choice in choices.items()}
            report['catalog_selections'] = {army: dict(profile=choice.profile, source_mode=choice.source_mode,
                name=choice.name, portrait=choice.portrait, banner=choice.banner, deck_kind=choice.deck.kind,
                deck_reference=choice.deck.reference, difficulty=choice.difficulty, strength=choice.strength)
                for army, choice in choices.items()}
        else:
            require(args.mode == 1, 'team probes require installed catalog selection')
            bots = {0: args.profile, 1: args.opponent_profile}
            roster = [dict(slot=army, army_id=army, player_id=army+1, name=f'Headless AI {army+1}', ai_profile_id=profile)
                      for army, profile in bots.items()]
            decks = template.default_decks
            if args.decks:
                decks = {int(army): deck for army, deck in json.loads(args.decks.read_text()).items()}
        match = template.build_match(roster, decks, seed=862431, bot_choices=choices)
        report.update(profiles=bots, raw_game_data_sha256=match.raw_sha256,
                      imported_manifest_sha256=hashlib.sha256((assets/'asset-manifest.json').read_bytes()).hexdigest(),
                      ai_rule_sha256={p: hashlib.sha256(book.rules[p]).hexdigest() for p in set(bots.values())},
                      decks=dict(match.decks_by_slot), mode=args.mode, alliances=template.alliances)
        actions_count = {army: 0 for army in bots}
        orders = {army: set() for army in bots}; moved = {army: set() for army in bots}
        positions, initial, produced = {}, set(), {army: set() for army in bots}
        max_supply = {army: 0 for army in bots}; max_damage = {army: 0 for army in bots}
        snapshots = output/'observations.jsonl'
        with NativeSimulation(match.raw_game_data, assets/'Simulation.dll') as sim:
            with NativeAI(sim, match.game_config, dll_path=assets/'aiprogram.dll', rules=book.rules,
                          default_profile=book.default_profile, bots=bots) as ai, snapshots.open('w', encoding='utf-8') as trace:
                for frame in range(args.frames):
                    decisions = ai.commands()
                    inputs = {}
                    for army in bots:
                        actions = list(decisions.get(army, ()))
                        actions_count[army] += len(actions)
                        if frame == 0:
                            join = field_uint(1, army) + field_bytes(2, match.deck_messages_by_slot[army])
                            for target, source in ((3, 5), (4, 6)):
                                value = get_uint(match.armies_by_slot[army], source)
                                if value: join += field_uint(target, value)
                            actions.append(field_bytes(3, join))
                        for action in actions:
                            command = get_bytes(action, 1)
                            if not command: continue
                            for group in get_repeated_bytes(command, 1):
                                if get_uint(group, 2) in (12, 88):
                                    orders[army].update(get_repeated_uint(group, 3))
                        inputs[army] = encode_player_input(match.identities_by_slot[army], actions)
                    sim.process_frame(encode_frame(frame, inputs))
                    if frame % 20 and frame != args.frames-1: continue
                    state = sim.state(include_entities=True)
                    if frame == 0: initial = {e['id'] for e in state['entities']}
                    for entity in state['entities']:
                        army, key = entity.get('army'), entity['id']
                        if army not in bots: continue
                        max_damage[army] = max(max_damage[army], entity.get('current_damage', 0))
                        if key not in initial and entity.get('type') in match.decks_by_slot[army]:
                            produced[army].add(key)
                            if 'position' in entity:
                                position = entity['position']
                                if key in positions and positions[key] != position: moved[army].add(key)
                                positions[key] = position
                    for army in bots:
                        resource = state['resources'].get(str(army), state['resources'].get(army, {}))
                        max_supply[army] = max(max_supply[army], resource.get('current_supply', 0))
                    trace.write(json.dumps({'frame': frame, 'resources': state['resources'], 'game_state': state['game_state'],
                                            'entities': state['entities']})+'\n')
                    if state['game_state']['complete']: break
                report.update(final_frame=sim.frame, ai_steps=ai.steps, game_state=state['game_state'],
                              max_command_body_bytes=ai.max_command_body_bytes,
                              action_counts=actions_count, max_supply=max_supply, max_damage=max_damage,
                              produced={a: sorted(v) for a,v in produced.items()},
                              ordered_moving_units={a: sorted(produced[a] & moved[a] & orders[a]) for a in bots},
                              native_ai_logs=ai.native_logs, native_sim_logs=sim.native_logs)
                require(all(produced[a] & moved[a] & orders[a] for a in bots), 'each bot must produce and move units under native orders')
                require(all(max_damage.values()), 'combat must damage both armies')
                require(state['game_state']['complete'], 'native match did not finish before frame limit')
        from server import native_ai, native_simulation
        require(native_ai._runtime is None and native_simulation._runtime is None, 'native runtimes were not released')
        report.update(passed=True, native_worlds_released=True)
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        report.update(elapsed_seconds=time.monotonic()-began, source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged']
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'error', 'elapsed_seconds', 'final_frame', 'action_counts') if k in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', type=int, default=58)
    parser.add_argument('--opponent-profile', type=int, default=62)
    parser.add_argument('--frames', type=int, default=12000)
    parser.add_argument('--decks', type=Path, help='local per-army deck JSON for native profile/deck qualification')
    parser.add_argument('--mode', type=int, choices=(1, 2, 5), default=1)
    parser.add_argument('--catalog-bots', action='store_true', help='select profile-compatible installed bot identities/decks')
    parser.add_argument('--selection-seed', type=int, default=75191)
    parser.add_argument('--strengths', default='normal', help='catalog probe strengths, single value or comma-separated per army')
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args()
    args.assets, args.output = args.assets.resolve(), args.output.resolve()
    if args.decks: args.decks = args.decks.resolve()
    require(os.name == 'nt' and args.output.is_relative_to(ROOT/'local') and 1200 <= args.frames <= 24000,
            'bounded Windows/ignored evidence probe required')
    if args.child: return child(args)
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, '-m', 'tools.verify_native_ai', '--child', '--assets', str(args.assets),
               '--output', str(args.output), '--profile', str(args.profile), '--opponent-profile', str(args.opponent_profile),
               '--frames', str(args.frames)]
    command += ['--mode', str(args.mode), '--selection-seed', str(args.selection_seed), '--strengths', args.strengths]
    if args.catalog_bots: command += ['--catalog-bots']
    if args.decks: command += ['--decks', str(args.decks)]
    environment = dict(os.environ, PYTHONPATH=str(ROOT))
    process = job = None
    with (args.output/'worker.log').open('w', encoding='utf-8') as log:
        try:
            process = subprocess.Popen(command, cwd=args.output, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            job = _WindowsJob(process.pid)
            (args.output/'process.json').write_text(json.dumps({'pid': process.pid}), encoding='utf-8')
            status = process.wait(timeout=300)
        finally:
            if process is not None and process.poll() is None:
                process.terminate(); process.wait(timeout=10)
            if job is not None: job.close()
    print(json.dumps({'exit_code': status, 'owned_process_reaped': process.poll() is not None,
                      'report': str(args.output/'verification.json')}))
    return 0 if status == 0 else 1


if __name__ == '__main__': raise SystemExit(main())
