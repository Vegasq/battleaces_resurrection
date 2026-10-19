"""Bounded owned Windows TOML refusal and explicit fixture repair qualification.

Never edits the shared file. Three authored invalid inputs must survive early
native refusal byte-for-byte. A deliberately repaired owned fixture must then
reach its offline menu. Deny writes after startup,distinguish live/disk choices,
restore access,retry original Save and verify a new process retains that deck.
Healthy cleanup is forced,not native Quit acceptance.
"""
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
    manifest = json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
    require(manifest.get('local_settings', {}).get('error_hooks') is True, 'install current native settings error hooks')
    require(args.valid_fixture.resolve().is_relative_to(ROOT/'local'), 'owned valid native fixture required')
    good = args.valid_fixture.resolve().read_bytes()
    require(0 < len(good) <= 1024*1024, 'bounded valid native fixture required')
    output.mkdir(parents=True, exist_ok=False)
    runtime = game/'investigation/runtime';runtime.mkdir(parents=True, exist_ok=True)
    profiles = game/'.battleaces-resurrection/profiles'
    key = 'nativestest_'+secrets.token_hex(6)
    report = dict(passed=False, scope=__doc__, cases=[], source_sha256_at_start=sources(),
                  helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest())
    processes = [];write_lock = None;started = time.monotonic()
    clock = ctypes.WinDLL('kernel32').GetTickCount64;clock.restype = ctypes.c_ulonglong
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    open_file = kernel.CreateFileW;open_file.restype = ctypes.c_void_p
    open_file.argtypes = [ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    close_file = kernel.CloseHandle;close_file.argtypes = [ctypes.c_void_p];close_file.restype = ctypes.c_int

    def shared_unchanged():
        require(startup.shared_state(args.shared_settings.resolve()) == report['shared_settings_before'], 'shared native settings changed')

    def log(row):
        path = runtime/f'dedicated-native-{row["pid"]}.log'
        raw = path.read_bytes() if path.exists() else b''
        text = raw[:raw.rfind(b'\n')+1].decode('utf-8')
        return '\n'.join(line for line in text.splitlines() if (m := re.match(r'^\[(\d+)\]',line)) and int(m[1]) >= row['tick'])

    def launch(label, profile, write_smoke=False):
        command = [str(game/'Battle Aces.exe'), '-offline-practice', '-practice-ai-experimental', '-local-profile='+profile,
                   '-native-settings-deck-proof', '-player-name=Settings Error Probe', '-screen-fullscreen', '0',
                   '-screen-width', '960', '-screen-height', '540', '-logFile', str(output/(label+'-game.log'))]
        if write_smoke: command.append('-native-settings-write-smoke')
        info = subprocess.STARTUPINFO();info.dwFlags |= subprocess.STARTF_USESHOWWINDOW;info.wShowWindow = 0
        tick = clock();process = subprocess.Popen(command, cwd=game, startupinfo=info, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        row = dict(label=label, profile=profile, pid=process.pid, tick=tick, command=command, process=process, job=None)
        processes.append(row);row['job'] = _WindowsJob(process.pid)
        (output/'processes.json').write_text(json.dumps([{k:v for k,v in r.items() if k not in ('process','job')} for r in processes],indent=2)+'\n')
        return row

    def write_phase(row, phase):
        deadline = time.monotonic()+args.timeout
        while True:
            require(row['process'].poll() is None, 'writer smoke exited early')
            text = log(row)
            require('Native settings write smoke failed:' not in text, 'native write smoke failed')
            proofs = [json.loads(line.split('NATIVE SETTINGS WRITE smoke: ',1)[1]) for line in text.splitlines() if 'NATIVE SETTINGS WRITE smoke:' in line]
            found = [p for p in proofs if p['phase']==phase]
            if found:
                require(len(found)==1 and found[0]['profile']==row['profile'] and found[0]['owned'] and found[0]['worldIdle'] and
                        found[0]['saveAttempts'] > 0, 'invalid owned original-write proof')
                return found[0]
            require(time.monotonic() < deadline, 'writer smoke deadline reached')
            time.sleep(.1)

    try:
        report['shared_settings_before'] = startup.shared_state(args.shared_settings.resolve())
        first = None
        for label, data in (('broken-header', b'[account\n'), ('unterminated-string', b"[account]\ndecks = 'unfinished\n"),
                            ('duplicate-key', b"[account]\ndecks = 'one'\ndecks = 'two'\n")):
            profile = key+'_'+str(len(report['cases']))
            folder = profiles/profile;folder.mkdir(parents=True, exist_ok=False)
            target = folder/'gameconfig-localuser.toml';target.write_bytes(data)
            (output/(label+'-input.toml')).write_bytes(data)
            if first is None: first = (profile, target)
            row = launch(label, profile);deadline = time.monotonic()+args.timeout
            while row['process'].poll() is None:
                require(time.monotonic() < deadline, 'malformed TOML did not refuse startup')
                time.sleep(.05)
            text = log(row)
            require(row['process'].returncode == 1610 and f'NATIVE SETTINGS load result: profile={profile} sequence=1 parsed=0' in text and
                    'NATIVE SETTINGS load refused: parsedTable=0 inputPreserved=1 sharedPathUnused=1' in text and
                    'Offline initial state reached' not in text and 'NATIVE SETTINGS save result:' not in text,
                    'malformed input did not stop before fallback/startup/native save')
            require(target.read_bytes() == data, 'malformed input was overwritten')
            shared_unchanged()
            report['cases'].append(dict(case=label, passed=True, pid=row['pid'], exit_code=row['process'].returncode,
                                        input_sha256=hashlib.sha256(data).hexdigest(), input_preserved=True))
        # Explicit test-fixture repair after its owned process exits. Product
        # recovery remains user-directed; never reset unrelated settings.
        profile, target = first;target.write_bytes(good)
        row = launch('explicit-fixture-repair', profile, write_smoke=True);deadline = time.monotonic()+args.timeout
        while True:
            require(row['process'].poll() is None, 'repaired fixture exited before menu')
            text = log(row)
            require('NATIVE SETTINGS load refused:' not in text and 'Native settings deck proof failed:' not in text,
                    'repaired native settings failed')
            if 'Offline practice menu ready:' in text and 'NATIVE SETTINGS DECK proof:' in text: break
            require(time.monotonic() < deadline, 'repaired fixture did not reach menu')
            time.sleep(.1)
        proof = startup.native_settings_evidence(game, output, row['pid'], row['tick'], profile)
        require(f'NATIVE SETTINGS load result: profile={profile} sequence=1 parsed=1' in text and
                re.search(r'NATIVE SETTINGS save result: profile='+re.escape(profile)+r' sequence=\d+ succeeded=1 failures=0',text),
                'healthy original load/save results missing')
        shared_unchanged();report['cases'].append(dict(case='explicit-fixture-repair', passed=True, pid=row['pid'], native_settings=proof))
        before = target.read_bytes();(output/'before-write-failure.toml').write_bytes(before)
        # Deny writes only AFTER native menu/preflight. A reader sharing only
        # reads makes the original StreamWriter report its handled failure.
        write_lock = open_file(str(target),0x80000000,1,None,3,0x00200080,None)
        require(write_lock not in (None,ctypes.c_void_p(-1).value), 'cannot lock owned native target for write-error fixture')
        Path(str(target)+'.write-test-1.gate').write_text('owned first original native edit\n')
        failed = write_phase(row,1)
        require(failed['lastSucceeded'] is False and failed['failedWrites']>0 and target.read_bytes()==before and
                failed['units']!=proof['selected_deck']['units'], 'post-startup failure did not distinguish live selection from disk')
        shared_unchanged()
        require(close_file(write_lock), 'owned target read lock release failed');write_lock = None
        Path(str(target)+'.write-test-2.gate').write_text('owned original Save retry\n')
        retry = write_phase(row,2)
        require(retry['lastSucceeded'] is True and retry['failedWrites']==0 and retry['units']==failed['units'] and
                retry['activeAbilityGroups']==failed['activeAbilityGroups'] and target.read_bytes()!=before,
                'original Save retry did not persist the same live choice')
        retry_output = output/'retry';retry_output.mkdir()
        retried = startup.native_settings_evidence(game,retry_output,row['pid'],row['tick'],profile)
        require(all(retried['selected_deck'][k]==retry[k] for k in ('units','activeAbilityGroups')), 'retry disk differs from live native deck')
        report['cases'].append(dict(case='post-startup-writer-error-and-retry',passed=True,pid=row['pid'],failed=failed,retry=retry,native_settings=retried))
        row['process'].terminate();row['process'].wait(timeout=15)
        row = launch('retry-restart',profile);deadline = time.monotonic()+args.timeout
        while True:
            require(row['process'].poll() is None,'retry restart exited before menu')
            text = log(row)
            if 'Offline practice menu ready:' in text and 'NATIVE SETTINGS DECK proof:' in text: break
            require(time.monotonic() < deadline,'retry restart deadline reached');time.sleep(.1)
        restart_output = output/'restart';restart_output.mkdir()
        restarted = startup.native_settings_evidence(game,restart_output,row['pid'],row['tick'],profile)
        native = [json.loads(line.split('NATIVE SETTINGS DECK proof: ',1)[1]) for line in text.splitlines() if 'NATIVE SETTINGS DECK proof:' in line]
        require(len(native)==1 and all(native[0][k]==retry[k]==restarted['selected_deck'][k] for k in ('units','activeAbilityGroups')),
                'fresh native process did not retain original Save retry')
        shared_unchanged();report['cases'].append(dict(case='retry-restart',passed=True,pid=row['pid'],native_settings=restarted))
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        if write_lock not in (None,ctypes.c_void_p(-1).value): close_file(write_lock)
        for row in reversed(processes):
            process = row['process']
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)
            (output/(row['label']+'-native.log')).write_text(log(row)+'\n',encoding='utf-8')
            if row['job'] is not None: row['job'].close()
        try: report['shared_settings_after'] = startup.shared_state(args.shared_settings.resolve())
        except OSError as error: report.update(passed=False, shared_settings_read_error=repr(error))
        report['shared_settings_unchanged'] = ('shared_settings_before' in report and 'shared_settings_after' in report and
                                              report['shared_settings_before']==report['shared_settings_after'])
        report.update(elapsed_seconds=time.monotonic()-started, owned_processes_reaped=all(r['process'].poll() is not None for r in processes),
                      source_sha256_at_finish=sources())
        report['source_files_unchanged'] = report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['passed'] &= report['owned_processes_reaped'] and report['source_files_unchanged'] and report['shared_settings_unchanged']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','error','elapsed_seconds') if k in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game','output','shared-settings','valid-fixture'): parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=180)
    raise SystemExit(run(parser.parse_args()))
