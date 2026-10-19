"""Run the real packaged Start Client command on an owned game, without seams.

Uses the shipped CMD, bundled runtime, package integrity check and ordinary
launcher. No automatic gameplay, screenshot or diagnostic game flags are added.
An owned Windows job forcibly reaps the whole process tree after menu readiness;
this is not native Quit, physical input, clean-PC or Internet acceptance.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import traceback

from client_patch.transport import client, launcher
from server.worker_client import _WindowsJob
from tools.package_integrity import verify
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require
from tools import verify_unified_startup as startup_probe

ROOT = Path(__file__).resolve().parents[1]


def cmd_command(wrapper, config, game):
    # All values are owned paths. Reject cmd expansion/control characters even
    # inside quotes; % and ! can expand before the called wrapper sees them.
    values = [str(path.resolve()) for path in (wrapper, config, game)]
    require(not any(any(c in value for c in '\r\n\0"&|<>^%!') for value in values),
            'CMD probe paths contain expansion or control characters')
    shell = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/cmd.exe'
    return f'"{shell}" /d /s /c ""{values[0]}" --config "{values[1]}" --game "{values[2]}""'


def run(args):
    package, game, output = (path.resolve() for path in (args.package, args.game, args.output))
    require(os.name == 'nt' and 60 <= args.timeout <= 300, 'bounded Windows probe required')
    require(all(path.is_relative_to(ROOT/'local') for path in (package, game, output)),
            'owned package, game and evidence paths below local/ required')
    inventory = verify(package, 'client')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=True)
    helper = package/'program/client-helper/BattleAcesOffline.dll'
    require(helper.read_bytes() == (game/'BattleAcesOffline.dll').read_bytes(),
            'install the same packaged helper into the owned game first')
    wrapper = package/'Start Client.cmd'
    expected = ('@echo off\nsetlocal\n"%~dp0program\\runtime\\python.exe" -I -B '
                '-m tools.package_client start %*\nexit /b %errorlevel%\n')
    require(wrapper.read_text() == expected, 'Start Client wrapper differs from the qualified command')
    output.mkdir(parents=True, exist_ok=False)
    cwd = output/'foreign cwd';cwd.mkdir()
    for name in ('sitecustomize.py', 'tools.py', 'client_patch.py'):
        (cwd/name).write_text('raise RuntimeError("foreign module must not run")\n')
    config_path = output/'relocated config/client.json'
    profile = 'packageprobe_'+secrets.token_hex(6)
    settings = client.defaults(game)
    settings.update(local_profile=profile, display_name='Packaged Player')
    config_path.parent.mkdir()
    config_path.write_text(json.dumps(settings, indent=2)+'\n', encoding='utf-8')
    config_before = config_path.read_bytes()
    command = cmd_command(wrapper, config_path, game)
    runtime = game/'investigation/runtime'
    existing_logs = set(runtime.glob('client-session-*.log'))
    own_source = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = dict(passed=False, scope=__doc__, package=str(package), game=str(game), command=command,
                  profile=profile, config_sha256=hashlib.sha256(config_before).hexdigest(),
                  package_inventory_sha256=hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest(),
                  shared_settings_before=startup_probe.shared_state(args.shared_settings.resolve()),
                  source_sha256_at_start=startup_probe.source_hashes(), verifier_sha256=own_source,
                  forced_cleanup=True, natural_quit=False)
    started = time.monotonic()
    parent = job = None
    game_handle = None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetTickCount64.restype = ctypes.c_ulonglong
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.WaitForSingleObject.restype = ctypes.c_ulong
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    tick = kernel.GetTickCount64()
    environment = os.environ.copy()
    environment.update(PATH=str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'), PYTHONPATH=str(cwd))
    try:
        with (output/'stdout.txt').open('wb') as stdout, (output/'stderr.txt').open('wb') as stderr:
            info = subprocess.STARTUPINFO();info.dwFlags |= subprocess.STARTF_USESHOWWINDOW;info.wShowWindow = 1
            parent = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stdout, stderr=stderr,
                                      startupinfo=info, close_fds=True)
            job = _WindowsJob(parent.pid)
            report.update(wrapper_pid=parent.pid, launch_tick=tick)
            (output/'process.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
            while True:
                require(parent.poll() is None, 'packaged command exited before native readiness')
                out = (output/'stdout.txt').read_text(encoding='utf-8', errors='replace')
                pids = re.findall(r'^Client started \(PID (\d+)\)\.$', out, re.M)
                require(len(pids) <= 1, 'packaged command started multiple games')
                if pids:
                    pid = int(pids[0])
                    if game_handle is None:
                        game_handle = kernel.OpenProcess(0x100000, False, pid)
                        require(game_handle, 'cannot retain owned game exit observation')
                        report['game_pid'] = pid
                    log = read_native_log(game, pid, since_tick=tick)
                    require(not any(marker in log for marker in ('Local menu initialization failed:',
                        'Offline initialization failed:', 'Client lifecycle invariant failed:', 'Cosmetics unlock failed:')),
                        'packaged native startup failed')
                    markers = ('Local menu ready:', 'Unified client ready:',
                               'Online connection is not configured; localWorldUnaffected=1',
                               'Client control retired: reason=optional connection failed',
                               'BA_RESURRECTION_COSMETICS_UNLOCK_V1 ready:', 'BA_RESURRECTION_COSMETICS_PERSIST_V1 ready:')
                    if all(marker in log for marker in markers):
                        require(not any(marker in log for marker in ('Practice requested:', 'Native world lease acquired:',
                            'worldReady=1', 'SMOKE', 'BA_RESURRECTION_COSMETIC_CATALOG_V1 exported:')),
                            'ordinary packaged startup performed diagnostic/gameplay work')
                        report['local_settings'] = startup_probe.native_settings_evidence(game, output, pid, tick, profile)
                        created_logs = set(runtime.glob('client-session-*.log')) - existing_logs
                        require(len(created_logs) == 1, 'packaged launcher log ownership is ambiguous')
                        game_log = created_logs.pop()
                        report['game_log'] = str(game_log)
                        unity = game_log.read_text(encoding='utf-8', errors='replace')
                        commands = [line for line in unity.splitlines() if line.startswith('Command Line Args: ')]
                        require(len(commands) == 1 and all(value in commands[0] for value in (
                            '-player-name=Packaged Player', '-local-profile='+profile, '-unified-client',
                            '-public-queue-experimental', '-local-cosmetics-experimental', '-secure-transport-version=2')) and
                            not re.search(r'(?:^|\s)-\S*(?:smoke|audit|capture|proof|export|auto-)\S*', commands[0]),
                            'actual ordinary game command omitted features or added diagnostics')
                        report['actual_game_command'] = commands[0]
                        report['menu_ready_seconds'] = time.monotonic()-started
                        report['ordinary_features_ready'] = True
                        report['no_match_or_diagnostic_actions'] = True
                        report['passed'] = True
                        break
                require(time.monotonic()-started < args.timeout, 'packaged native startup timed out')
                time.sleep(.2)
    except BaseException as error:
        report.update(passed=False, error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if job is not None: job.close()
        if parent is not None:
            if parent.poll() is None:
                try: parent.wait(timeout=15)
                except subprocess.TimeoutExpired: parent.kill();parent.wait(timeout=15)
            report['wrapper_reaped'] = parent.poll() is not None
        report['game_reaped'] = game_handle is None or kernel.WaitForSingleObject(game_handle, 15000) == 0
        if game_handle: kernel.CloseHandle(game_handle)
        if 'game_pid' in report:
            (output/'native.log').write_text(read_native_log(game, report['game_pid'], since_tick=tick), encoding='utf-8')
            if report.get('game_log'):
                (output/'game.log').write_bytes(Path(report['game_log']).read_bytes())
        try:
            report['package_files_unchanged'] = verify(package, 'client') == inventory
        except BaseException as error:
            report.update(package_files_unchanged=False, integrity_error=str(error))
        report['config_unchanged'] = config_path.read_bytes() == config_before
        report['source_files_unchanged'] = (report['source_sha256_at_start'] == startup_probe.source_hashes() and
            report['verifier_sha256'] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        report['shared_settings_after'] = startup_probe.shared_state(args.shared_settings.resolve())
        report['shared_settings_unchanged'] = report['shared_settings_before'] == report['shared_settings_after']
        report['elapsed_seconds'] = time.monotonic()-started
        report['passed'] &= all(report.get(key, False) for key in ('wrapper_reaped','game_reaped',
            'package_files_unchanged','config_unchanged','source_files_unchanged','shared_settings_unchanged'))
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed','error','elapsed_seconds','menu_ready_seconds') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('package','game','output','shared-settings'): parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=180)
    return run(parser.parse_args())


if __name__ == '__main__': raise SystemExit(main())
