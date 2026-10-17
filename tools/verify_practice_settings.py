"""Exercise the native offline Settings dropdown and saved choice after restart.

Uses owned native callbacks, not mouse input. Terminates only its test clients;
does not qualify native Quit. Restores this installation's prior preference.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from client_patch.transport.launcher import verify_game
from tools.verify_client_startup import read_startup_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    values = core_hashes()
    for name in ('verify_practice_settings.py', 'verify_client_startup.py'):
        values['tools/' + name] = hashlib.sha256((ROOT / 'tools' / name).read_bytes()).hexdigest()
    return values


def run(args):
    require(os.name == 'nt', 'Windows runtime required')
    game, output = args.game.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must remain under ignored local/')
    verify_game(game, community=False)
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
    require(manifest.get('practice', {}).get('difficulty_settings'), 'difficulty settings helper required')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2))
    settings = (game / '.battleaces-resurrection/practice-settings.ini').resolve()
    require(settings.is_relative_to(game), 'preference path escapes game directory')
    before = settings.read_bytes() if settings.exists() else None
    report = dict(passed=False, scope=__doc__, utc=datetime.now(timezone.utc).isoformat(),
                  source_sha256_at_start=source_hashes(), runs=[],
                  original_preference_sha256=hashlib.sha256(before).hexdigest() if before is not None else None)
    processes = []
    started = time.monotonic()
    clock = ctypes.WinDLL('kernel32').GetTickCount64
    clock.restype = ctypes.c_ulonglong
    try:
        settings.unlink(missing_ok=True)
        for index in (0, 1):
            run = output / ('dropdown' if index == 0 else 'restart')
            run.mkdir()
            command = [str(game / 'Battle Aces.exe'), '-offline-practice', '-practice-ai-default-profile=19',
                       '-player-name=Settings Probe', '-screen-fullscreen', '0', '-screen-width', '960',
                       '-screen-height', '540', '-logFile', str(run / 'game.log')]
            if index == 0:
                command.append('-practice-settings-smoke')
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            tick = clock()
            process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                                       creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
            processes.append(process)
            details = dict(pid=process.pid, arguments=command, launch_tick=tick, network_samples=0)
            report['runs'].append(details)
            (run / 'process.json').write_text(json.dumps(details, indent=2))
            deadline, last_network = time.monotonic() + args.timeout, 0
            try:
                while True:
                    require(process.poll() is None, 'settings probe exited early')
                    log = read_startup_log(game, process.pid, since_tick=tick)
                    (run / 'native.log').write_text(log, encoding='utf-8')
                    require(not any(marker in log for marker in ('Practice settings UI failed in ',
                        'PRACTICE SETTINGS SMOKE failed', 'Offline practice initialization failed:')),
                        'native settings failure; see logs')
                    unity = run / 'game.log'
                    unity_text = unity.read_text(encoding='utf-8', errors='replace') if unity.exists() else ''
                    require(not any(marker in unity_text for marker in ('NullReferenceException:',
                        'ArgumentNullException:', 'InvalidOperationException:')), 'managed settings exception')
                    if time.monotonic() - last_network >= 5:
                        net = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=10,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
                        require(net.returncode == 0, 'network observation failed')
                        owned = [line.strip() for line in net.stdout.splitlines() if line.split() and
                                 line.split()[0] in ('TCP', 'UDP') and line.split()[-1] == str(process.pid)]
                        details['network_samples'] += 1
                        require(not owned, 'offline settings client owns network sockets: ' + str(owned))
                        last_network = time.monotonic()
                    if index == 0 and 'PRACTICE SETTINGS SMOKE passed' in log:
                        require('selected=hard profile=19 source=default' in log, 'wrong initial default')
                        for profile, name in ((17, 'easy'), (19, 'hard'), (18, 'normal')):
                            require(f'Practice difficulty selected: selected={name} profile={profile} saved=1' in log,
                                    'dropdown selection was not persisted: ' + name)
                        break
                    if index == 1 and 'Offline practice menu ready:' in log:
                        require('selected=normal profile=18 source=saved' in log,
                                'saved dropdown choice did not survive process restart')
                        break
                    require(time.monotonic() < deadline, 'native settings deadline reached')
                    time.sleep(.5)
                require('Practice requested:' not in log, 'settings-only probe unexpectedly started a match')
                require(settings.read_bytes() == b'schema=1\r\ndifficulty=normal\r\n', 'wrong persisted preference')
                details['passed'] = True
            finally:
                (run / 'native.log').write_text(read_startup_log(game, process.pid, since_tick=tick), encoding='utf-8')
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=15)
            print('Passed ' + run.name, flush=True)
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
        if before is None:
            settings.unlink(missing_ok=True)
        else:
            settings.write_bytes(before)
        report.update(elapsed_seconds=time.monotonic()-started,
                      owned_processes_reaped=all(process.poll() is not None for process in processes),
                      preference_restored=(settings.read_bytes() if settings.exists() else None) == before,
                      source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['owned_processes_reaped'] and report['source_files_unchanged'] and report['preference_restored']
        (output / 'verification.json').write_text(json.dumps(report, indent=2))
        print('Evidence: ' + str(output / 'verification.json'), flush=True)
    require(report['passed'], 'settings qualification failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    require(30 <= args.timeout <= 300, 'timeout must be30..300 seconds')
    run(args)
