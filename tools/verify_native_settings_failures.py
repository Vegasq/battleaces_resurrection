"""Owned Windows native settings rejection/concurrent-profile probe.

Runs menu-only offline clients. Rejected starts must exit1610 before the native
startup marker; healthy menu processes are forcibly reaped,not native Quit tests.
All fixtures/evidence stay in ignored local/. Shared settings are read/hashed only.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import traceback

from client_patch.transport import launcher
from server.worker_client import _WindowsJob
from tools import verify_unified_startup as startup

ROOT = Path(__file__).resolve().parents[1]


def sources():
    return startup.source_hashes() | {Path(__file__).relative_to(ROOT).as_posix(): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def run(args):
    require = startup.require
    game, output = args.game.resolve(), args.output.resolve()
    require(os.name == 'nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'), 'owned ignored Windows paths required')
    require(60 <= args.timeout <= 300, 'bounded native phase timeout required')
    launcher.verify_game(game, community=True, bridge_version=2, unified=True)
    output.mkdir(parents=True, exist_ok=False)
    runtime = game/'investigation/runtime';runtime.mkdir(parents=True, exist_ok=True)
    profiles = game/'.battleaces-resurrection/profiles'
    key = 'nativestest_'+secrets.token_hex(6)
    processes = [];readonly = junction = None
    report = dict(passed=False, utc=datetime.now(timezone.utc).isoformat(), scope=__doc__,
                  source_sha256_at_start=sources(), cases=[], teardown='forced owned menu cleanup; not native Quit')
    started = time.monotonic()
    clock = ctypes.WinDLL('kernel32').GetTickCount64;clock.restype = ctypes.c_ulonglong
    attributes = ctypes.WinDLL('kernel32', use_last_error=True).SetFileAttributesW
    attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32];attributes.restype = ctypes.c_int

    def launch(label, profile, extra=()):
        command = [str(game/'Battle Aces.exe'), '-offline-practice', '-practice-ai-experimental',
                   '-local-profile='+profile, '-player-name=Settings Guard Probe', '-native-settings-deck-proof',
                   '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
                   '-logFile', str(output/(label+'-game.log')), *extra]
        info = subprocess.STARTUPINFO();info.dwFlags |= subprocess.STARTF_USESHOWWINDOW;info.wShowWindow = 0
        tick = clock();process = subprocess.Popen(command, cwd=game, startupinfo=info, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        record = dict(label=label, profile=profile, pid=process.pid, tick=tick, command=command, process=process, job=None)
        processes.append(record);record['job'] = _WindowsJob(process.pid)
        (output/'processes.json').write_text(json.dumps([{k:v for k,v in row.items() if k not in ('process','job')} for row in processes], indent=2)+'\n')
        return record

    def log(record):
        path = runtime/f'dedicated-native-{record["pid"]}.log'
        raw = path.read_bytes() if path.exists() else b''
        complete = raw[:raw.rfind(b'\n')+1].decode('utf-8')
        return '\n'.join(line for line in complete.splitlines() if (m := re.match(r'^\[(\d+)\]', line)) and int(m[1]) >= record['tick'])

    def shared_unchanged():
        require(startup.shared_state(args.shared_settings.resolve()) == report['shared_settings_before'], 'shared native settings changed')

    def ready(record):
        deadline = time.monotonic()+args.timeout
        while True:
            require(record['process'].poll() is None, 'healthy offline menu exited early')
            text = log(record)
            require('isolation failed:' not in text and 'Native settings deck proof failed:' not in text and 'Local menu initialization failed:' not in text,
                    'healthy native profile failed initialization')
            if 'NATIVE SETTINGS DECK proof: ' in text and 'Offline practice menu ready:' in text: break
            require(time.monotonic() < deadline, 'healthy native profile did not reach its menu')
            time.sleep(.1)
        rows = [json.loads(line.split('NATIVE SETTINGS DECK proof: ',1)[1]) for line in text.splitlines() if 'NATIVE SETTINGS DECK proof: ' in line]
        require(len(rows)==1 and rows[0]['profile']==record['profile'] and rows[0]['owned'] and rows[0]['pathVerified'], 'healthy profile proof missing')
        shared_unchanged();return rows[0]

    def reject(label, profile, expected, extra=()):
        record = launch(label, profile, extra)
        process = record['process'];deadline = time.monotonic()+args.timeout
        while process.poll() is None:
            require(time.monotonic() < deadline, 'invalid native profile did not refuse startup')
            time.sleep(.05)
        text = log(record)
        require(process.returncode==1610 and 'Native local-user settings isolation failed: ' in text and expected in text and
                'originalPathUnused=1' in text and 'NATIVE SETTINGS path selected: ' not in text and
                'Offline initial state reached' not in text, 'invalid profile did not fail at the early isolated path boundary')
        require(keeper['process'].poll() is None, 'rejected startup disturbed the active profile')
        require(startup.shared_state(keeper_path)==keeper_state, 'rejected startup changed active profile settings')
        shared_unchanged();report['cases'].append(dict(case=label, passed=True, pid=record['pid'], exit_code=process.returncode, early_refusal=True))

    try:
        report['shared_settings_before'] = startup.shared_state(args.shared_settings.resolve())
        keeper = launch('keeper', key+'_a');first = ready(keeper)
        keeper_path = profiles/(key+'_a')/'gameconfig-localuser.toml';keeper_state = startup.shared_state(keeper_path)
        reject('same-key', key+'_a', 'already in use or unavailable')
        reject('traversal', '../'+key, 'invalid native local profile key')
        reject('reserved', 'con', 'invalid native local profile key')
        reject('duplicate-option', key+'_duplicate', 'duplicate native local profile option', ['-local-profile='+key+'_second'])
        blocked = profiles/(key+'_blocked');blocked.write_bytes(b'authored ordinary-file blocker')
        reject('parent-file', blocked.name, 'ordinary local file/directory')
        require(blocked.read_bytes()==b'authored ordinary-file blocker', 'blocked parent changed')
        folder = profiles/(key+'_readonly');folder.mkdir()
        readonly = folder/'gameconfig-localuser.toml';readonly.write_bytes(b'authored readonly config')
        require(attributes(str(readonly), 1), 'readonly fixture failed')
        reject('readonly-file', folder.name, 'unavailable or unwritable')
        require(readonly.read_bytes()==b'authored readonly config', 'readonly native config changed')
        folder = profiles/(key+'_hardlink');folder.mkdir()
        linked = output/'hardlink-target.toml';linked.write_bytes(b'authored hard-link config')
        os.link(linked, folder/'gameconfig-localuser.toml')
        reject('hardlink-file', folder.name, 'cannot use hard links')
        require(linked.read_bytes()==b'authored hard-link config', 'hard-link target changed')
        import _winapi
        target = output/'junction-target';target.mkdir()
        junction = profiles/(key+'_junction')
        _winapi.CreateJunction(str(target), str(junction))
        reject('junction-directory', junction.name, 'ordinary local file/directory')
        require(not list(target.iterdir()), 'junction target was written')
        other = launch('different-profile', key+'_b');second = ready(other)
        require(keeper['process'].poll() is None and startup.shared_state(keeper_path)==keeper_state and
                first['units']==second['units'] and first['activeAbilityGroups']==second['activeAbilityGroups'],
                'concurrent independent native profiles changed one another')
        report['cases'].append(dict(case='different-profile', passed=True, pid=other['pid'], concurrent_menus=True))
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        for record in reversed(processes):
            process = record['process']
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)
            (output/(record['label']+'-native.log')).write_text(log(record)+'\n', encoding='utf-8')
            if record['job'] is not None: record['job'].close()
        if readonly is not None: require(attributes(str(readonly), 128), 'owned readonly fixture reset failed')
        if junction is not None and junction.is_junction():
            require(junction.parent.resolve()==profiles.resolve(), 'junction cleanup escaped its owned fixture')
            os.rmdir(junction)  # Remove only this junction,never the target/tree.
        try:
            report['shared_settings_after'] = startup.shared_state(args.shared_settings.resolve())
        except OSError as error:
            report.update(passed=False, shared_settings_read_error=repr(error))
        report.update(elapsed_seconds=time.monotonic()-started, owned_processes_reaped=all(row['process'].poll() is not None for row in processes),
                      source_sha256_at_finish=sources())
        report['source_files_unchanged'] = report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['shared_settings_unchanged'] = ('shared_settings_before' in report and 'shared_settings_after' in report and
                                              report['shared_settings_before']==report['shared_settings_after'])
        report['passed'] &= report['owned_processes_reaped'] and report['source_files_unchanged'] and report['shared_settings_unchanged']
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','error','elapsed_seconds') if key in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game','output','shared-settings'): parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=180)
    raise SystemExit(run(parser.parse_args()))
