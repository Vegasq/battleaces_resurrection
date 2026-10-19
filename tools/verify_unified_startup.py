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
"""
import argparse
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import traceback
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


def run(args):
    require(os.name == 'nt' and 60 <= args.timeout <= 300, 'bounded Windows probe required')
    game, output = args.game.resolve(), args.output.resolve()
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
                  helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest())
    (output/'patch-manifest.json').write_bytes((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
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
                if all(marker in log for marker in markers) and catalog_done and unlock_done and trace_done and picker_done and equip_done and persist_done and profile_done:
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
                        require(any(cosmetic_flags) or 'BA_RESURRECTION_COSMETICS_UNLOCK_V1' not in log,
                                'ordinary startup unexpectedly enabled cosmetic unlock')
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
        require(not any('smoke' in value or 'audit' in value or 'auto-' in value for value in command),
                'ordinary launcher added diagnostic actions')
        require('-player-cosmetics-catalog-export' not in command,
                'ordinary launcher enabled cosmetic export')
        report['ordinary_arguments_contain_no_diagnostics'] = True
        if args.menu_profile_proof: command.append('-menu-profile-proof')
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
        if monitor is not None: monitor.join(timeout=15)
        if job is not None: job.close()
        report.update(elapsed_seconds=time.monotonic()-started, owned_process_reaped=process is None or process.poll() is not None,
                      source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['owned_process_reaped'] and report['source_files_unchanged']
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
