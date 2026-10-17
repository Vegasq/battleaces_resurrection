"""Verify native local startup timing and menu readiness on an isolated game copy.

Headless mode checks initialization/ABI only, not visible UI or loading performance.
Teardown terminates the owned probe; this is not native Quit qualification.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from client_patch.transport.launcher import verify_game
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def read_startup_log(game, pid, *, since_tick):
    """Keep pre-menu markers while excluding append-only records of a reused PID."""
    path = game / 'investigation/runtime' / f'dedicated-native-{pid}.log'
    text = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
    for match in re.finditer(r'^\[(\d+)\] ', text, re.MULTILINE):
        if int(match[1]) >= since_tick:
            return text[match.start():]
    return ''


def source_hashes():
    result = core_hashes()
    result['tools/verify_client_startup.py'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return result


def run(args):
    require(os.name == 'nt', 'Windows runtime required')
    game, output = args.game.resolve(), args.output.resolve()
    require(output.is_relative_to(ROOT / 'local'), 'evidence must be under ignored local/')
    verify_game(game, community=False)
    manifest = json.loads((game / '.battleaces-resurrection/patch-manifest.json').read_text())
    require(manifest.get('practice', {}).get('standalone'), 'offline practice helper required')
    require('OfflineStartupReady' in {h['name'] for h in manifest['call_hooks']}, 'startup timing hook required')
    output.mkdir(parents=True, exist_ok=False)
    (game / 'investigation/runtime').mkdir(parents=True, exist_ok=True)
    (output / 'patch-manifest.json').write_text(json.dumps(manifest, indent=2))
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), scope=__doc__,
                  headless=args.headless, source_sha256_at_start=source_hashes())
    process, launch_tick, log = None, None, ''
    started = time.monotonic()
    try:
        command = [str(game / 'Battle Aces.exe'), '-offline-practice', '-practice-ai-profile=18',
                   '-player-name=Startup Probe', '-screen-fullscreen', '0', '-screen-width', '960',
                   '-screen-height', '540', '-logFile', str(output / 'game.log')]
        if args.headless:
            command.extend(['-batchmode', '-nographics'])
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        clock = ctypes.WinDLL('kernel32').GetTickCount64
        clock.restype = ctypes.c_ulonglong
        launch_tick = clock()
        process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                                   creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        report.update(game_pid=process.pid, client_arguments=command, launch_tick=launch_tick)
        (output / 'process.json').write_text(json.dumps(report, indent=2))
        while True:
            require(process.poll() is None, 'native startup probe exited early')
            log = read_startup_log(game, process.pid, since_tick=launch_tick)
            require(not any(marker in log for marker in ('Offline initialization failed:',
                'Offline practice initialization failed:')), 'native startup failure; see logs')
            unity = output / 'game.log'
            unity_text = unity.read_text(encoding='utf-8', errors='replace') if unity.exists() else ''
            require(not any(marker in unity_text for marker in ('NullReferenceException:', 'ArgumentNullException:',
                'InvalidOperationException:')), 'managed startup exception; see game.log')
            timings = re.findall(r'RGameInit:Start time: ([0-9.]+)s', unity_text)
            if timings and 'Offline practice menu ready:' in log:
                require(len(timings) == 1, 'expected one original startup timing')
                require(log.count('Offline startup assets ready; original Start timing retained;') == 1,
                        'startup completion hook did not run exactly once')
                require(log.count('Offline initial state reached after game initialization.') == 1,
                        'native initial state did not run exactly once')
                require('Practice requested:' not in log, 'startup probe must not start a match')
                report.update(passed=True, original_start_seconds=float(timings[0]),
                              observed_menu_ready_seconds=time.monotonic()-started)
                break
            require(time.monotonic()-started < args.timeout, 'native startup deadline reached')
            time.sleep(.5)
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if process:
            log = read_startup_log(game, process.pid, since_tick=launch_tick)
            (output / f'native-{process.pid}.log').write_text(log, encoding='utf-8')
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
        report.update(elapsed_seconds=time.monotonic()-started,
                      owned_process_reaped=not process or process.poll() is not None,
                      source_sha256_at_finish=source_hashes())
        report['source_files_unchanged'] = report['source_sha256_at_start'] == report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_process_reaped']
        (output / 'verification.json').write_text(json.dumps(report, indent=2))
        print('Evidence: ' + str(output / 'verification.json'), flush=True)
    require(report['passed'], 'startup qualification failed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    require(30 <= args.timeout <= 300, 'timeout must be30..300 seconds')
    run(args)
