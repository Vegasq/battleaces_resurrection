"""Opt-in one-client mode4 practice probe on an isolated Windows game copy.

Automates native Edit Deck navigation/owned button callback, surrender and
Continue. It does not establish mouse input, victory, internet play or native Quit.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import csv
from datetime import datetime, timezone
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import time
import traceback
import uuid

from client_patch.transport.launcher import verify_game
from server.assets import verify_assets
from server.cosmetics import CosmeticCatalog
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes
from tools import match_loading_evidence

ROOT = Path(__file__).resolve().parents[1]
PASSED = 'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=1'
OFFLINE_PASSED = 'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1'


def source_hashes():
    import hashlib
    result = core_hashes()
    result['tools/verify_practice_ai.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['tools/run_secure_match.py'] = hashlib.sha256((ROOT / 'tools/run_secure_match.py').read_bytes()).hexdigest()
    result['tools/match_loading_evidence.py'] = hashlib.sha256(Path(match_loading_evidence.__file__).read_bytes()).hexdigest()
    return result


def movement_evidence(log, bot_units, army=1):
    """Correlate native owned units with original Move12/Attack88 orders.

    The DLL's unit orders omit protobuf entityType (default0). Resolve the
    entity IDs against the copied native view, rather than requiring that field.
    """
    positions, moved, ordered = {}, set(), set()
    for _, entity, unit, x, y, z in re.findall(
            rf'Practice AI entity: frame=(\d+) army={army} id=(\d+) type=(\d+) position=\((\d+),(\d+),(\d+)\)', log):
        if int(unit) not in bot_units: continue
        entity, point = int(entity), (int(x), int(y), int(z))
        if entity in positions and positions[entity] != point: moved.add(entity)
        positions[entity] = point
    owned = 'Local AI owned action: ' in log
    for line in log.splitlines():
        if owned:
            if f'Local AI owned action: identity={army+1} ' not in line: continue
            action = json.loads(line.split(' protobuf=', 1)[1])
        else:
            if army != 1 or 'Practice AI protobuf: ' not in line: continue
            action = json.loads(line.split('Practice AI protobuf: ', 1)[1])
        command = action.get('executeCommand', {})
        if not set(command.get('commandData', {})) & {'targetGroundCommandData', 'targetUnitCommandData'}: continue
        for group in command.get('entityTypeData', []):
            if group.get('abilityId') in (12, 88):
                ordered.update(group.get('entityIds', []))
    return moved, ordered & positions.keys()


async def run(args):
    require(os.name == 'nt', 'Windows runtime required')
    game, output = args.game.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must be under ignored local/')
    verify_game(game, community=not args.offline)
    output.mkdir(parents=True, exist_ok=False)
    (game / 'investigation/runtime').mkdir(parents=True, exist_ok=True)
    audit, events = Audit(output), []
    def observe(event, **fields):
        events.append(dict(event=event, **fields)); audit(event, **fields)
    async def unexpected_worker(_):
        raise AssertionError('practice must not allocate a multiplayer worker')
    server = None
    if not args.offline:
        require(args.assets is not None, '--assets is required for the community scenario')
        assets = args.assets.resolve(); verify_assets(assets)
        template = GameTemplate.load(assets / 'map-1v1.pb.gz', catalog_path=assets / 'unit-catalog.json', descriptors_path=assets / 'descriptors')
        server = DedicatedServer(template, ProfileStore(output / 'profiles', template), audit=observe,
            sim_factory=unexpected_worker, data_dir=output, lobby_timeout=300)
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), source_sha256_at_start=source_hashes(),
        scope=__doc__, teardown='owned test termination; not native Quit validation')
    started, process, launch_tick = time.monotonic(), None, None
    try:
        address = await server.start('127.0.0.1', 0) if server else None
        manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
        (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2))
        if args.offline: require(manifest.get('practice', {}).get('standalone'), 'helper does not support offline practice')
        if args.settings_first: require(manifest.get('practice', {}).get('difficulty_settings'), 'difficulty settings helper required')
        if args.loading_ui: require(manifest.get('ui', {}).get('match_loading'), 'loading UI helper required')
        command = [str(game / 'Battle Aces.exe'),
            '-local-profile='+(args.cosmetic_profile or 'nativeprobe_'+uuid.uuid4().hex[:16]),
            '-practice-ai-experimental', '-practice-ai-smoke', '-lan-audit',
            f'-practice-ai-profile={args.profile}',
            f'-practice-ai-smoke-matches={args.matches}',
            f'-practice-ai-smoke-frames={args.frames}',
            f'-practice-ai-smoke-delay-ms={max(3000, args.idle_seconds * 1000)}',
            '-player-id=practice_' + uuid.uuid4().hex, '-player-name=Practice Tester',
            '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
            '-logFile', str(output / 'game.log')]
        command.extend(['-offline-practice'] if args.offline else
            ['-offline-lan', f'-dedicated-server=127.0.0.1:{address[1]}', '-dedicated-community'])
        if args.human_build: command.append('-lan-smoke')
        if args.edit_deck_between: command.append('-practice-ai-deck-smoke')
        if args.settings_first: command.append('-practice-settings-smoke')
        if args.loading_ui: command.append('-match-loading-smoke')
        if args.focus_local_hq: command.append('-human-cosmetics-focus-hq')
        if args.cosmetic_profile:
            require(args.offline and game.is_relative_to(ROOT / 'local'), 'cosmetic probe requires an offline disposable copy')
            require(re.fullmatch(r'cosmeticstest_[a-z0-9_-]{1,34}', args.cosmetic_profile), 'use an owned cosmetic test profile')
            require(args.assets is not None, 'cosmetic proof requires the trusted imported catalog')
            catalog = CosmeticCatalog(args.assets.resolve())
            seeded = json.loads((game / '.battleaces-resurrection/profiles' / (args.cosmetic_profile+'.cosmetics.json')).read_text())
            require(seeded['profile'] == args.cosmetic_profile and seeded['catalog_sha256'] == catalog.sha256,
                    'test profile/catalog mismatch')
            expected_cosmetics = catalog.validate_selection(seeded['slots'])
            report['expected_cosmetics'] = seeded
            command.extend(['-local-cosmetics-experimental', '-human-cosmetics-smoke'])
        startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 4 if args.visible else 0 # SW_SHOWNOACTIVATE for explicit graphical qualification.
        clock = ctypes.WinDLL('kernel32').GetTickCount64; clock.restype = ctypes.c_ulonglong
        launch_tick = clock()
        process = subprocess.Popen(command, cwd=game, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        report.update(game_pid=process.pid, client_arguments=command, launch_tick=launch_tick)
        (output / 'process.json').write_text(json.dumps(report, indent=2))
        deadline, last_print, last_network = time.monotonic() + args.timeout, '', 0
        report['network_observation'] = dict(method='periodic netstat snapshots, not packet capture', samples=0, owned_rows=[])
        while True:
            require(process.poll() is None, 'native practice client exited early')
            if args.offline and time.monotonic()-last_network >= 5:
                snapshot = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                require(snapshot.returncode == 0, 'network observation failed')
                owned = [line.strip() for line in snapshot.stdout.splitlines()
                    if line.split() and line.split()[0] in ('TCP', 'UDP') and line.split()[-1] == str(process.pid)]
                report['network_observation']['samples'] += 1
                report['network_observation']['owned_rows'].extend(owned)
                require(not owned, 'standalone game owns network sockets; inspect evidence')
                last_network = time.monotonic()
            log = read_native_log(game, process.pid, since_tick=launch_tick)
            if args.cosmetic_profile and 'Cosmetic persistence unavailable:' in log:
                raise AssertionError('seeded cosmetic profile was not accepted; inspect retained file and native log')
            require(not any(marker in log for marker in ('Practice stopped in ', 'Offline loop stopped in ',
                'Offline practice initialization failed:', 'Local menu initialization failed:', 'Practice settings UI failed in ',
                'PRACTICE SETTINGS SMOKE failed')), 'native practice failure; see logs')
            unity_log = output / 'game.log'
            if unity_log.exists():
                unity_text = unity_log.read_text(encoding='utf-8', errors='replace')
                require(not any(error in unity_text for error in ('ArgumentNullException:', 'NullReferenceException:', 'InvalidOperationException:')),
                    'native managed exception; see game.log')
            lines = [line for line in log.splitlines() if 'Practice ' in line or 'PRACTICE ' in line]
            if lines and lines[-1] != last_print:
                last_print = lines[-1]; print(last_print, flush=True)
            marker = (OFFLINE_PASSED if args.offline else PASSED).replace('completed=1 ', f'completed={args.matches} ')
            if marker in log:
                break
            require(time.monotonic() < deadline, 'native practice deadline reached')
            await asyncio.sleep(.5)
        require(log.count('Practice AI join captured:') == args.matches and log.count('Practice AI JoinedGame delivered:') == args.matches,
            'practice AI service did not join exactly once per match')
        require(log.count('PRACTICE SMOKE original EditDeck mode4 callback: owned=1 visible=1 interactable=1 preamble=1') == args.matches,
            'practice did not exercise the available native Edit Deck callback')
        starts = list(re.finditer(r'Practice requested: match=([0-9a-f]{32}) ', log))
        require(len(starts) == args.matches and len({s[1] for s in starts}) == args.matches, 'wrong practice match count/identity')
        if args.settings_first:
            settings_done = log.find('PRACTICE SETTINGS SMOKE passed')
            require(0 <= settings_done < starts[0].start(), 'match did not follow the native Settings selections/return')
            report['native_settings_before_match'] = True
        report['matches'] = evidence = []
        for index, start in enumerate(starts):
            # Entity IDs can be reused in the next world: never correlate across matches.
            segment = log[start.start():starts[index+1].start() if index+1 < len(starts) else len(log)]
            resources = game / 'investigation/runtime' / f'lan-resources-{process.pid}-{start[1]}.tsv'
            with resources.open(encoding='utf-8') as source:
                bot_rows = [row for row in csv.DictReader(source, delimiter='\t') if row['viewer'] == '1' and row['army'] == '1']
            max_supply = max((int(row['current_supply']) for row in bot_rows), default=0)
            require(max_supply > 0, 'AI input stream did not produce native unit supply')
            joins = [json.loads(line.split('Practice original JoinArmy: ', 1)[1])
                     for line in segment.splitlines() if 'Practice original JoinArmy: ' in line]
            require(len(joins) == 2, 'expected two original JoinArmy snapshots per match')
            moved, unit_orders = movement_evidence(segment, set(joins[1]['deck']['units']))
            evidence.append(dict(match=start[1], human_deck=joins[0]['deck']['units'], bot_max_observed_supply=max_supply,
                bot_units_with_observed_position_change=sorted(moved),
                bot_deck_unit_ids_receiving_autonomous_orders=sorted(unit_orders),
                autonomous_action_records=segment.count('Practice AI action:')))
            if args.cosmetic_profile:
                if index:
                    changes = [json.loads(line.split('HUMAN COSMETICS rematch equipped: ', 1)[1])
                               for line in log.splitlines() if 'HUMAN COSMETICS rematch equipped: ' in line]
                    require(len(changes) == args.matches-1, 'missing fresh same-frame native cosmetic rematch edit')
                    fresh = catalog.validate_selection(changes[index-1]['slots'])
                    require(fresh.slots != expected_cosmetics.slots, 'rematch reused stale cosmetic map')
                    expected_cosmetics = fresh
                messages = [json.loads(line.split('HUMAN COSMETICS frozen message: ', 1)[1])
                            for line in segment.splitlines() if 'HUMAN COSMETICS frozen message: ' in line]
                require(len(messages) == 2, 'expected human config and JoinArmy cosmetic snapshots')
                require(messages[0]['deck'] == messages[1]['deck'] and
                        all(messages[0][key] == messages[1][key] for key in ('portraitId', 'bannerId')),
                        'human config and join cosmetics differ')
                actual = messages[0]
                require(actual['portraitId'] == expected_cosmetics.portrait and actual['bannerId'] == expected_cosmetics.banner,
                        'native human roles differ from seeded profile')
                require(actual['deck']['entitlements'] == [dict(cosmeticAssetKeys=list(expected_cosmetics.keys))],
                        'native human entitlement differs from seeded ordered full selection')
                require(segment.count('HUMAN COSMETICS SimPlayer passed:') == 1 and
                        all('HUMAN COSMETICS identity binding: phase='+phase in segment for phase in ('in-game', 'result')),
                        'full native human cosmetic map/live/result bindings missing')
                evidence[-1]['human_cosmetics'] = dict(config=messages[0], join=messages[1], native_full_map=True,
                                                       live_and_result_children=True)
                captures = []
                for phase in ('in-game', 'result'):
                    name = f'human-cosmetics-{process.pid}-{start[1]}-{phase}.png'
                    path = game / 'investigation/runtime' / name
                    require(path.is_file() and path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), 'native human cosmetic capture missing')
                    shutil.copyfile(path, output / name); captures.append(name)
                evidence[-1]['human_cosmetics']['captures_requiring_visual_review'] = captures
            if args.offline and manifest.get('practice', {}).get('difficulty_settings'):
                difficulty_profile = 18 if args.settings_first else args.profile
                selected = {17: 'easy', 18: 'normal', 19: 'hard'}[difficulty_profile]
                tuning = 18 if difficulty_profile == 17 else difficulty_profile
                require(f'Practice difficulty snapshot: selected={selected} modifierProfile={difficulty_profile} tuningProfile={tuning}' in segment,
                        'match did not snapshot the requested difficulty')
                require(f'Practice effective AI profile: id={tuning} expectedTableEntry=1 ' in segment,
                        'native AI did not use the expected tactical profile')
                strength = re.search(r'Practice difficulty modifiers: selected=(\w+) resourceQ=(\d+) damageQ=(\d+) healthQ=(\d+)', segment)
                require(strength is not None and strength[1] == selected, 'difficulty strength evidence missing')
                health = re.search(r'Practice AI entity: frame=\d+ army=1 id=\d+ type=3 position=\([^)]+\) health=(\d+)', segment)
                require(health is not None and int(health[1]) > 0, 'native bot core MaxHealth was not observed')
                human_health = re.search(r'Practice human core MaxHealth: frame=\d+ value=(\d+) viewer=0', segment)
                require(human_health is not None and int(human_health[1]) > 0, 'native human core MaxHealth was not observed')
                evidence[-1]['difficulty'] = dict(selected=selected, tuning_profile=tuning,
                    resource_q32=int(strength[2]), damage_q32=int(strength[3]), health_q32=int(strength[4]),
                    observed_bot_core_max_health=int(health[1]), observed_human_core_max_health=int(human_health[1]))
            if args.require_ai_movement:
                require(bool(moved & unit_orders), 'no produced bot deck unit both received an autonomous order and changed position')
            require(segment.count('Practice AI action:') >= 5, 'no sustained autonomous AI inputs')
        if args.edit_deck_between:
            require(evidence[0]['human_deck'] != evidence[1]['human_deck'], 'native deck edit did not change next match deck')
        require(log.count('Practice native EndOfGameResponse delivered;') == args.matches and
            log.count('PRACTICE SMOKE native Continue') == args.matches,
            'native result/Continue not completed')
        if server:
            sessions = list(server.community.sessions.values())
            require(len(sessions) == 1 and not sessions[0].practicing and sessions[0].lobby is None and sessions[0].peer.slot is None,
                'practice did not restore available presence without a match seat')
        else:
            require('Offline practice menu ready:' in log, 'offline menu was not initialized')
            require(not any(marker in log for marker in ('LAN connecting', 'Dedicated connecting', 'Community presence installed:',
                'Community connected:', 'Practice reservation')), 'offline test entered a network session')
            if args.idle_seconds >= 35:
                idle_samples = re.findall(r'Practice offline idle observation: generation=0 sample=(\d+) clear=(\d+)', log)
                require(idle_samples == [(str(i), '1') for i in range(1, 7)],
                    'offline idle menu did not remain clear for six observations')
                require(log.count('Practice offline idle disconnect release: generation=0 ') == 1,
                    'offline startup disconnect was not released exactly once')
                report['idle_menu_clear_samples'] = len(idle_samples)
        require(not any(e['event'] == 'match_created' for e in events), 'practice created a multiplayer worker')
        if args.loading_ui:
            report['loading_ui'] = match_loading_evidence.check(log, game, output, process.pid,
                source='practice', ready=args.matches)
        if args.focus_local_hq:
            require(log.count('HUMAN COSMETICS original HQ focus:')==args.matches and
                    log.count('ownedGraph=1 presentedHQ=1 cameraPermission=1 callbacks=1')==args.matches and
                    log.count('HUMAN COSMETICS HQ projected for capture:')==args.matches,
                    'original local HQ focus did not run once per owned match')
            report['original_local_hq_focus_callbacks'] = args.matches
        report.update(passed=True, autonomous_action_records=log.count('Practice AI action:'),
            standalone=args.offline, community_connections=0 if args.offline else 1,
            server_started=server is not None)
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        if process:
            native_log = read_native_log(game, process.pid, since_tick=launch_tick)
            (output / f'native-{process.pid}.log').write_text(native_log, encoding='utf-8')
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)
            for match in set(re.findall(r'Practice requested: match=([0-9a-f]{32}) ', native_log)):
                for prefix in ('lan-audit', 'lan-resources'):
                    sample = game / 'investigation/runtime' / f'{prefix}-{process.pid}-{match}.tsv'
                    if sample.is_file(): shutil.copyfile(sample, output / sample.name)
        if server: await server.close()
        report.update(elapsed_seconds=time.monotonic()-started, owned_processes_reaped=not process or process.poll() is not None,
            source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_processes_reaped']
        (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        audit.close(); print('Evidence: ' + str(output / 'verification.json'), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'output'): parser.add_argument('--' + key, required=True, type=Path)
    parser.add_argument('--assets', type=Path, help='community server inputs; unused for offline practice')
    parser.add_argument('--offline', action='store_true', help='run with no server, community presence or LAN transport')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--frames', type=int, default=1200)
    parser.add_argument('--idle-seconds', type=int, default=0, help='wait at the menu before each automated AI match (0..60)')
    parser.add_argument('--human-build', action='store_true', help='issue one ordinary human deck-slot0 build at frame300')
    parser.add_argument('--matches', type=int, choices=(1, 2), default=1)
    parser.add_argument('--edit-deck-between', action='store_true', help='use original native setters to change the deck before match2')
    parser.add_argument('--settings-first', action='store_true', help='cycle actual offline Settings and return with Normal18 before playing')
    parser.add_argument('--loading-ui', action='store_true', help='verify native loading status and retain Unity screenshots')
    parser.add_argument('--focus-local-hq',action='store_true',help='explicit original HQ camera action before owned offline cosmetic capture')
    parser.add_argument('--profile', type=int, choices=(17, 18, 19), default=17,
                        help='offline difficulty Easy17/Normal18/Hard19; community mode retains raw shipped profile selection')
    parser.add_argument('--require-ai-movement', action='store_true')
    parser.add_argument('--cosmetic-profile', help='owned cosmeticstest_ profile; enables explicit offline human cosmetic diagnostics')
    parser.add_argument('--visible', action='store_true', help='show the owned diagnostic window without taking focus')
    args = parser.parse_args(); require(60 <= args.timeout <= 600, 'timeout must be60..600 seconds')
    require(not args.edit_deck_between or args.matches == 2, 'deck edit requires two matches')
    require(not args.settings_first or args.offline, 'settings-first requires standalone offline mode')
    require(not args.focus_local_hq or args.offline and args.visible and args.cosmetic_profile,
            'local HQ focus requires an explicit visible owned offline cosmetic diagnostic')
    require(1200 <= args.frames <= 3600, 'frames must be1200..3600')
    require(0 <= args.idle_seconds <= 60, 'idle seconds must be0..60')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
