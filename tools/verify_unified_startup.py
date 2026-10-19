"""Run the real unified launcher without a config, server, CA or invite.

Only window visibility/log location are overridden in the spawn seam. The actual
configuration, patch verification, inherited bridge and native menu run. Teardown
forcibly reaps the owned game; this does not qualify visible UI or native Quit.
The optional cosmetic export adds one read-only diagnostic after checking that
the ordinary launcher arguments contain no automation/capture flags. The separate
unlock smoke constructs native cosmetic item models and compares original
dictionary/ownership behavior. The separate picker smoke opens the original
menu, changes only its slot/filter view and captures it. The separate equip smoke
changes a disposable test profile through original callbacks, and the persistence
proof reads the effective full loadout.
Native settings proof compares the early isolated loader path and actual TOML;
the optional native deck edit uses original setters in an owned test profile.
"""
import argparse
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import threading
import time
import traceback
import tomllib
from unittest import mock

from client_patch.transport import client, launcher
from server.worker_client import _WindowsJob
from server.cosmetics import CosmeticCatalog
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    paths = [Path(__file__), ROOT/'tools/run_secure_match.py']
    paths += list((ROOT/'client_patch/transport').glob('*.py'))
    return core_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def shared_state(path):
    if not path.exists(): return dict(exists=False)
    raw = path.read_bytes()
    return dict(exists=True, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def native_settings_evidence(game, output, pid, tick, profile):
    raw = (game/'investigation/runtime'/f'dedicated-native-{pid}.log').read_bytes()
    complete = raw[:raw.rfind(b'\n')+1].decode('utf-8').replace('\r\n', '\n')
    rows = []
    for line in complete.splitlines():
        match = re.match(r'^\[(\d+)\] NATIVE SETTINGS path selected: (.+) BA_RESURRECTION_NATIVE_SETTINGS_V1$', line)
        if match and int(match[1]) >= tick: rows.append((int(match[1]), json.loads(match[2])))
    starts = [int(value) for value in re.findall(r'^\[(\d+)\] Offline initial state reached after game initialization\. PID='+str(pid), complete, re.M)
              if int(value) >= tick]
    require(len(rows) == len(starts) == 1 and rows[0][0] < starts[0], 'isolated path was not selected before this process initialized')
    proof = rows[0][1]
    expected = game/'.battleaces-resurrection/profiles'/profile/'gameconfig-localuser.toml'
    require(proof['profile'] == profile and all(proof[key] is True for key in ('beforeNativeLoad', 'isolated', 'writerLock')) and
            Path(proof['path']) == expected and expected.resolve() == expected, 'native settings destination differs from the configured installation/profile')
    verified = [int(value) for value in re.findall(r'^\[(\d+)\] NATIVE SETTINGS path verified: profile='+re.escape(profile)+
                r' staticField=1 getterCalled=0 isolated=1$', complete, re.M) if int(value) >= tick]
    require(len(verified) == 1 and verified[0] >= starts[0],
            'initialized native loader field was not checked')
    data = expected.read_bytes();require(0 < len(data) <= 1024*1024, 'native TOML missing or oversized')
    table = tomllib.loads(data.decode('utf-8-sig'))
    deck = json.loads(table['account']['decks'])['SelectedDeck']
    selected = dict(units=[item['_id'] for item in deck['_units']], activeAbilityGroups=[item['_id'] for item in deck['_activeAbilities']])
    require(len(selected['units']) == 8 and len(selected['activeAbilityGroups']) == 4, 'isolated native deck has unexpected dimensions')
    require(all(type(value) is int and 0 < value <= 0xffffffff for value in selected['units']) and
            all(type(value) is int and 0 <= value <= 0xffffffff for value in selected['activeAbilityGroups']),
            'isolated native deck has invalid identifier types/ranges')
    (output/'isolated-localuser.toml').write_bytes(data)
    return dict(path=str(expected), profile=profile, early_tick=rows[0][0], startup_tick=starts[0], static_field_verified=True,
                native_toml_sha256=hashlib.sha256(data).hexdigest(), native_toml_bytes=len(data), selected_deck=selected)


def run(args):
    # Internal callers such as the cosmetic restart harness predate these
    # optional probes; missing options retain ordinary, non-editing behavior.
    for key, default in (('display_name', None), ('menu_profile_proof', False), ('native_deck_proof', False),
                         ('edit_native_deck', False), ('shared_settings', None)):
        if not hasattr(args, key): setattr(args, key, default)
    require(os.name == 'nt' and 60 <= args.timeout <= 300, 'bounded Windows probe required')
    game, output = args.game.resolve(), args.output.resolve()
    require(game.is_relative_to(ROOT/'local'), 'ordinary player qualification requires an owned disposable game copy')
    require(output.is_relative_to(ROOT/'local'), 'evidence must remain under ignored local/')
    output.mkdir(parents=True, exist_ok=False)
    (game/'investigation/runtime').mkdir(parents=True, exist_ok=True)
    path = output/'client.json'
    if args.local_profile or args.display_name:
        settings = client.defaults(game)
        if args.local_profile: settings['local_profile'] = client.profile_key(args.local_profile)
        if args.display_name: settings['display_name'] = args.display_name
        path.write_text(json.dumps(settings, indent=2)+'\n', encoding='utf-8')
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), scope=__doc__,
                  settings_absent_at_start=not path.exists(), source_sha256_at_start=source_hashes(),
                  local_profile=args.local_profile,
                  cosmetics_export=args.cosmetics_export,
                  cosmetics_unlock_smoke=args.cosmetics_unlock_smoke,
                  cosmetics_ui_trace=args.cosmetics_ui_trace, cosmetics_picker_smoke=args.cosmetics_picker_smoke,
                  cosmetics_equip_smoke=args.cosmetics_equip_smoke, cosmetics_persistence_proof=args.cosmetics_persistence_proof,
                  visible_window_requested=args.visible,
                  menu_profile_proof=args.menu_profile_proof, requested_display_name=args.display_name,
                  native_deck_proof=args.native_deck_proof, edit_native_deck=args.edit_native_deck,
                  helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest())
    (output/'patch-manifest.json').write_bytes((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
    if args.edit_native_deck:
        require(args.native_deck_proof and args.local_profile and args.local_profile.startswith('nativestest_') and game.is_relative_to(ROOT/'local'),
                'native deck edits require an explicit owned nativestest_ profile/install and proof')
    if args.shared_settings: report['shared_settings_before'] = shared_state(args.shared_settings.resolve())
    cosmetic_flags = (args.cosmetics_unlock_smoke, args.cosmetics_ui_trace, args.cosmetics_picker_smoke,
                      args.cosmetics_equip_smoke, args.cosmetics_persistence_proof)
    if any(cosmetic_flags):
        require(args.local_profile, 'cosmetic probes require an explicit disposable profile key')
        require(not (args.cosmetics_equip_smoke and args.cosmetics_picker_smoke), 'equip and read-only picker probes run separately')
        require(not args.cosmetics_equip_smoke or args.cosmetics_export, 'equip probe requires independent exported catalog validation')
        require(json.loads((output/'patch-manifest.json').read_bytes()).get('cosmetics', {}).get('experimental'),
                'install the experimental cosmetic recipe in the disposable copy first')
    process = job = monitor = None
    started = time.monotonic()
    tick = None

    def watch():
        try:
            while True:
                require(process.poll() is None, 'client exited before local menu readiness')
                log = read_native_log(game, process.pid, since_tick=tick)
                require(not any(marker in log for marker in ('Client lifecycle invariant failed:',
                    'Local menu initialization failed:', 'Offline initialization failed:',
                    'Cosmetics catalog export failed:', 'Cosmetics unlock failed:',
                    'Local menu header binding failed:')), 'native startup/export failed')
                require('Native settings deck proof failed:' not in log, 'native deck persistence proof failed')
                markers = ('Local menu ready:', 'Unified client ready:',
                           'Online connection is not configured; localWorldUnaffected=1',
                           'Client control retired: reason=optional connection failed')
                catalog_done = not args.cosmetics_export or 'BA_RESURRECTION_COSMETIC_CATALOG_V1 exported:' in log
                unlock_done = not args.cosmetics_unlock_smoke or 'COSMETICS UNLOCK SMOKE passed:' in log
                trace_done = not args.cosmetics_ui_trace or 'COSMETICS UI TRACE complete:' in log
                picker_done = not args.cosmetics_picker_smoke or 'COSMETICS PICKER SMOKE passed:' in log
                equip_done = not args.cosmetics_equip_smoke or 'COSMETICS EQUIP SMOKE passed:' in log
                persist_done = not args.cosmetics_persistence_proof or 'COSMETICS PERSISTENCE PROOF passed:' in log
                profile_done = not args.menu_profile_proof or 'MENU PROFILE PROOF passed: ' in log
                deck_done = not args.native_deck_proof or 'NATIVE SETTINGS DECK proof: ' in log
                features_done = 'BA_RESURRECTION_COSMETICS_UNLOCK_V1 ready:' in log and 'BA_RESURRECTION_COSMETICS_PERSIST_V1 ready:' in log
                if all(marker in log for marker in markers) and features_done and catalog_done and unlock_done and trace_done and picker_done and equip_done and persist_done and profile_done and deck_done:
                    settings = native_settings_evidence(game, output, process.pid, tick, report['configured_local_profile'])
                    report['local_settings'] = settings
                    if args.native_deck_proof:
                        rows = [json.loads(line.split('NATIVE SETTINGS DECK proof: ', 1)[1]) for line in log.splitlines()
                                if 'NATIVE SETTINGS DECK proof: ' in line]
                        require(len(rows) == 1 and rows[0]['profile'] == report['configured_local_profile'] and
                                all(rows[0][key] is True for key in ('owned', 'pathVerified', 'worldIdle')) and
                                rows[0]['edited'] == args.edit_native_deck and
                                all(rows[0][key] == settings['selected_deck'][key] for key in ('units', 'activeAbilityGroups')),
                                'current native selector and isolated on-disk deck differ')
                        report['native_deck'] = rows[0]
                    require('Practice requested:' not in log, 'ordinary startup unexpectedly automated a match')
                    require('worldReady=1' not in log and 'Native world lease acquired:' not in log,
                            'startup/export unexpectedly created a match world')
                    if args.cosmetics_export:
                        raw = (game/'investigation/runtime'/f'player-cosmetics-catalog-{process.pid}.json').read_bytes()
                        catalog = CosmeticCatalog.from_bytes(raw)
                        snapshot = catalog.normalize_local({})
                        (output/'player-cosmetics-catalog.json').write_bytes(raw)
                        report.update(catalog_sha256=hashlib.sha256(raw).hexdigest(),
                                      catalog_items=len(catalog.items), catalog_slots=len(catalog.slots),
                                      catalog_default_keys=len(snapshot.keys))
                    else:
                        require('BA_RESURRECTION_COSMETIC_CATALOG_V1' not in log,
                                'ordinary startup unexpectedly exported cosmetic data')
                    if args.cosmetics_unlock_smoke:
                        raw = (game/'investigation/runtime'/f'cosmetics-unlock-{process.pid}.json').read_bytes()
                        proof = json.loads(raw)
                        require(proof['passed'] and proof['items'] > 0 and proof['entitlement_keys'] > 0 and
                                all(proof[key] is True for key in ('unknown_signed_fallback', 'rarity_preserved',
                                    'inventory_unchanged', 'loadout_unchanged', 'world_idle', 'native_save_case37_suppressed')), 'cosmetic unlock proof incomplete')
                        (output/'cosmetics-unlock.json').write_bytes(raw)
                        report['cosmetics_unlock_proof'] = proof
                    else:
                        require('COSMETICS UNLOCK SMOKE passed:' not in log, 'ordinary startup unexpectedly automated cosmetic model checks')
                    if args.cosmetics_ui_trace:
                        raw = (game/'investigation/runtime'/f'cosmetics-ui-trace-{process.pid}.json').read_bytes()
                        (output/'cosmetics-ui-trace.json').write_bytes(raw)
                        report['ui_trace_nodes'] = json.loads(raw)['nodes']
                    if args.cosmetics_picker_smoke:
                        base = game/'investigation/runtime'/f'cosmetics-picker-{process.pid}'
                        raw = base.with_suffix('.json').read_bytes();proof = json.loads(raw)
                        require(proof['passed'] and proof['loadout_unchanged'] and
                                len(proof['slots'])+proof['empty_slots_skipped'] == 17 and
                                proof['filter_cases'] == len(proof['slots'])*3 and
                                all(row['all'] == row['owned'] > 0 and row['unowned'] == 0 for row in proof['slots']),
                                'cosmetic picker proof incomplete')
                        (output/'cosmetics-picker.json').write_bytes(raw)
                        capture = base.with_suffix('.png').read_bytes()
                        require(capture.startswith(b'\x89PNG\r\n\x1a\n'), 'cosmetic picker capture missing/invalid')
                        (output/'cosmetics-picker.png').write_bytes(capture)
                        report.update(cosmetics_picker_proof=proof, picker_capture_sha256=hashlib.sha256(capture).hexdigest())
                    if args.cosmetics_equip_smoke:
                        base = game/'investigation/runtime'/f'cosmetics-equip-{process.pid}'
                        raw = base.with_suffix('.json').read_bytes();proof = json.loads(raw)
                        require(proof['passed'] and proof['writes'] > 0 and all(proof[key] is True for key in
                            ('selection_callback', 'equip_callback', 'confirm_callback', 'swap_prior_item',
                             'valid_reset_preserved', 'projection12', 'world_idle')), 'cosmetic equip proof incomplete')
                        catalog = CosmeticCatalog.from_bytes((game/'investigation/runtime'/f'player-cosmetics-catalog-{process.pid}.json').read_bytes())
                        for phase in ('before', 'after'):
                            catalog.validate_selection(proof[phase]['slots'])
                        (output/'cosmetics-equip.json').write_bytes(raw)
                        capture = base.with_suffix('.png').read_bytes()
                        require(capture.startswith(b'\x89PNG\r\n\x1a\n'), 'cosmetic equip capture missing')
                        (output/'cosmetics-equip.png').write_bytes(capture)
                        report.update(cosmetics_equip_proof=proof, equip_capture_sha256=hashlib.sha256(capture).hexdigest())
                    if args.cosmetics_persistence_proof:
                        raw = (game/'investigation/runtime'/f'cosmetics-persistence-{process.pid}.json').read_bytes()
                        proof = json.loads(raw)
                        require(proof['passed'] and proof['projection12'] and proof['state']['profile'] == args.local_profile and
                                len(proof['state']['slots']) == 17, 'cosmetic persistence proof incomplete')
                        (output/'cosmetics-persistence.json').write_bytes(raw)
                        report['cosmetics_persistence_proof'] = proof
                    if args.menu_profile_proof:
                        rows = [json.loads(line.split('MENU PROFILE PROOF passed: ', 1)[1]) for line in log.splitlines()
                                if 'MENU PROFILE PROOF passed: ' in line]
                        require(len(rows) == 1 and rows[0]['owned'] and rows[0]['worldIdle'] and not rows[0]['networkRequest'] and
                                rows[0]['capture'] and rows[0]['renderStateRestored'] and
                                rows[0]['name'] == rows[0]['label'] == report['configured_display_name'],
                                'native header model/rendered label differs from configured name')
                        report['header_profile'] = rows[0]
                        capture = (game/'investigation/runtime'/f'menu-profile-{process.pid}-1.png').read_bytes()
                        require(capture.startswith(b'\x89PNG\r\n\x1a\n'), 'menu header capture missing/invalid')
                        (output/'menu-profile.png').write_bytes(capture)
                        report['header_capture_sha256'] = hashlib.sha256(capture).hexdigest()
                    report.update(menu_ready=True, observed_menu_seconds=time.monotonic()-started)
                    break
                require(time.monotonic()-started < args.timeout, 'native startup deadline reached')
                time.sleep(.2)
        except BaseException as error:
            report.update(error=repr(error), traceback=traceback.format_exc())
        finally:
            if process.poll() is None: process.terminate()

    def spawn(config, remote, options, child):
        nonlocal process, job, monitor, tick
        command = launcher.game_arguments(config, None, child.fileno(), options)
        report['configured_display_name'] = config['display_name']
        report['configured_local_profile'] = config.get('local_profile', 'default')
        require(not any('smoke' in value or 'audit' in value or 'auto-' in value for value in command),
                'ordinary launcher added diagnostic actions')
        require('-player-cosmetics-catalog-export' not in command,
                'ordinary launcher enabled cosmetic export')
        require('-public-queue-experimental' in command and '-local-cosmetics-experimental' in command,
                'ordinary player features were omitted')
        report['ordinary_player_features'] = dict(public_queues=True, cosmetics=True, isolated_persistence=True)
        report['ordinary_arguments_contain_no_diagnostics'] = True
        if args.menu_profile_proof: command.append('-menu-profile-proof')
        if args.native_deck_proof: command.append('-native-settings-deck-proof')
        if args.edit_native_deck: command.append('-native-settings-deck-edit')
        if args.cosmetics_export:
            command.append('-player-cosmetics-catalog-export')
        if args.cosmetics_unlock_smoke:
            command += ['-local-cosmetics-experimental', '-cosmetics-unlock-smoke']
        if args.cosmetics_ui_trace:
            if '-local-cosmetics-experimental' not in command:
                command.append('-local-cosmetics-experimental')
            command.append('-cosmetics-ui-trace')
        if args.cosmetics_picker_smoke:
            if '-local-cosmetics-experimental' not in command:
                command.append('-local-cosmetics-experimental')
            command.append('-cosmetics-picker-smoke')
        if args.cosmetics_equip_smoke or args.cosmetics_persistence_proof:
            if '-local-cosmetics-experimental' not in command:
                command.append('-local-cosmetics-experimental')
            if args.cosmetics_equip_smoke:
                command.append('-cosmetics-equip-smoke')
            if args.cosmetics_persistence_proof:
                command.append('-cosmetics-persistence-proof')
        command[command.index('-logFile')+1] = str(output/'game.log')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 5 if args.visible else 0
        startup.lpAttributeList = {'handle_list': [child.fileno()]}
        clock = ctypes.WinDLL('kernel32').GetTickCount64;clock.restype = ctypes.c_ulonglong
        tick = clock()
        try:
            child.set_inheritable(True)
            process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                creationflags=0 if args.visible else subprocess.CREATE_NO_WINDOW, close_fds=True)
        finally: child.set_inheritable(False)
        job = _WindowsJob(process.pid)
        report.update(game_pid=process.pid, launch_tick=tick, client_arguments=command)
        (output/'process.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        monitor = threading.Thread(target=watch, name='unified-startup-monitor')
        monitor.start()
        return process

    try:
        with (mock.patch.object(launcher, 'spawn_game', side_effect=spawn),
              mock.patch.object(launcher.tls, 'open_verified_connection', side_effect=AssertionError('unexpected remote connection')) as connect,
              mock.patch.object(launcher, 'read_credential_file', side_effect=AssertionError('unexpected invite read')) as invite):
            report['launcher_return_code'] = client.main(['--config', str(path), '--game', str(game)])
            if monitor is not None: monitor.join(timeout=15)
            require(report.get('menu_ready') and 'error' not in report, 'local menu did not become ready')
            require(connect.call_count == invite.call_count == 0, 'local startup required remote credentials/network')
        saved = json.loads(path.read_text())
        require(saved['schema'] == 3 and all(saved[key] == '' for key in
            ('server_host', 'server_name', 'ca_bundle', 'credential_file')), 'unexpected online default configuration')
        report.update(passed=True, default_settings_created=args.local_profile is None and args.display_name is None, remote_connections=0, invite_reads=0)
    except BaseException as error:
        report.update(passed=False, error=report.get('error', repr(error)))
        raise
    finally:
        if process is not None:
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)
            (output/f'native-{process.pid}.log').write_text(read_native_log(game, process.pid, since_tick=tick), encoding='utf-8')
            raw = game/'investigation/runtime'/f'dedicated-native-{process.pid}.log'
            if raw.exists(): (output/f'raw-native-{process.pid}.log').write_bytes(raw.read_bytes())
        if monitor is not None: monitor.join(timeout=15)
        if job is not None: job.close()
        report.update(elapsed_seconds=time.monotonic()-started, owned_process_reaped=process is None or process.poll() is not None,
                      source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['owned_process_reaped'] and report['source_files_unchanged']
        if args.shared_settings:
            report['shared_settings_after'] = shared_state(args.shared_settings.resolve())
            report['shared_settings_unchanged'] = report['shared_settings_before'] == report['shared_settings_after']
            report['passed'] &= report['shared_settings_unchanged']
        (output/'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print('Evidence: ' + str(output/'verification.json'))
    require(report['passed'], 'unified startup qualification failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'output'): parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--visible', action='store_true', help='show the owned diagnostic game window')
    parser.add_argument('--display-name', help='seed an owned local-only config with this player name')
    parser.add_argument('--menu-profile-proof', action='store_true', help='read back the owned main-menu header model and bound TMP label')
    parser.add_argument('--native-deck-proof', action='store_true', help='compare the original selected graph with the actual isolated native TOML')
    parser.add_argument('--edit-native-deck', action='store_true', help='change one unit through native setters in an explicit nativestest_ profile')
    parser.add_argument('--shared-settings', type=Path, help='read-only shared-file baseline; require its existence/content to remain unchanged')
    parser.add_argument('--cosmetics-export', action='store_true',
                        help='explicit read-only export and validation of installed cosmetic tables')
    parser.add_argument('--cosmetics-unlock-smoke', action='store_true',
                        help='explicit catalog-scoped ownership/model check; no equip or gameplay')
    parser.add_argument('--cosmetics-ui-trace', action='store_true', help='explicit read-only native menu button inventory')
    parser.add_argument('--cosmetics-picker-smoke', action='store_true', help='explicit original picker/filter callbacks and capture; no equip or gameplay')
    parser.add_argument('--local-profile', help='explicit disposable profile for cosmetic probes')
    parser.add_argument('--cosmetics-equip-smoke', action='store_true', help='original select/equip/confirm/swap callbacks; requires cosmeticstest_ profile')
    parser.add_argument('--cosmetics-persistence-proof', action='store_true', help='read back all 17 effective cosmetic slots and 12-field native profile projection')
    run(parser.parse_args())
