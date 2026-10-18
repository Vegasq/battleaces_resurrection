"""Run the real unified launcher without a config, server, CA or invite.

Only window visibility/log location are overridden in the spawn seam. The actual
configuration, patch verification, inherited bridge and native menu run. Teardown
forcibly reaps the owned game; this does not qualify visible UI or native Quit.
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
    path = output/'client.json'
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), scope=__doc__,
                  settings_absent_at_start=not path.exists(), source_sha256_at_start=source_hashes())
    process = job = monitor = None
    started = time.monotonic()
    tick = None

    def watch():
        try:
            while True:
                require(process.poll() is None, 'client exited before local menu readiness')
                log = read_native_log(game, process.pid, since_tick=tick)
                require(not any(marker in log for marker in ('Client lifecycle invariant failed:',
                    'Local menu initialization failed:', 'Offline initialization failed:')), 'native startup failed')
                markers = ('Local menu ready:', 'Unified client ready:',
                           'Online connection is not configured; localWorldUnaffected=1',
                           'Client control retired: reason=optional connection failed')
                if all(marker in log for marker in markers):
                    require('Practice requested:' not in log, 'ordinary startup unexpectedly automated a match')
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
        require(not any('smoke' in value or 'audit' in value or 'auto-' in value for value in command),
                'ordinary launcher added diagnostic actions')
        command[command.index('-logFile')+1] = str(output/'game.log')
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        startup.lpAttributeList = {'handle_list': [child.fileno()]}
        clock = ctypes.WinDLL('kernel32').GetTickCount64;clock.restype = ctypes.c_ulonglong
        tick = clock()
        try:
            child.set_inheritable(True)
            process = subprocess.Popen(command, cwd=game, startupinfo=startup,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
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
        report.update(passed=True, default_settings_created=True, remote_connections=0, invite_reads=0)
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
    run(parser.parse_args())
