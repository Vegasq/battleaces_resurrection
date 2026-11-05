"""Owned packaged startup with one real read lock AFTER successful validation.

Observe original loader failure, release only that lock, and require menu/Quit
recovery. A bounded observation ending in forced cleanup remains FAILED.
No game bytes, ACLs, loader callbacks or production deadlines are changed.
"""
import argparse
import contextlib
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import threading
import time
import tomllib
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
OWNED = Path.home()/'AppData/Local/BattleAcesDiagnostics/local'
LOCK = ROOT/'tools/verify_profile_storage.py'
TARGET = '22afcd27e427dc74c718d35a50f695e4.bundle'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix+'.staging')
    temporary.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    os.replace(temporary, path)


def refusal_lines(text, target):
    """Require the exact target path on an original file-open failure line."""
    target = str(target).replace('\\', '/').lower()
    return [line for line in text.splitlines() if target in line.replace('\\', '/').lower()
            and any(marker in line.lower() for marker in
                    ('unable to open archive file', 'failed to open', 'unable to load assetbundle'))]


def last_event_state(raw):
    """Only complete append-only records; no shared-file rename/read race."""
    complete = raw[:raw.rfind(b'\n')+1]
    if not complete: return {}
    return json.loads(complete.splitlines()[-1])['state']


def observed_state(out):
    path = out/'events.jsonl'
    return last_event_state(path.read_bytes()) if path.exists() else {}


def child(request_path):
    from tools import package_client
    from tools.package_integrity import verify
    from client_patch.transport import launcher
    from client_patch.patcher import bundle_loading as loading
    req = json.loads(request_path.read_bytes()); out = request_path.parent
    game, package = Path(req['game']), Path(req['package'])
    assert sha(__file__) == req['driver_sha256'] and sha(LOCK) == req['lock_sha256']
    assert Path(package_client.__file__).resolve() == package/'program/app/tools/package_client.py'
    assert Path(loading.__file__).resolve() == package/'program/app/client_patch/patcher/bundle_loading.py'
    verify(package, 'client')
    spec = importlib.util.spec_from_file_location('postcheck_lock', LOCK)
    locks = importlib.util.module_from_spec(spec); spec.loader.exec_module(locks)
    target = game/loading.BUNDLE_DIR/TARGET
    assert sha(target) == req['bundle_sha256'] == loading.BUILD.BUNDLES[TARGET][1]
    clock = ctypes.WinDLL('kernel32').GetTickCount64; clock.restype = ctypes.c_ulonglong
    state = dict(validation_completed=False, lock_acquired=False, lock_released=False,
                 failure_observed=False, process_started=False)
    real_socket, real_subprocess, real_verify = launcher.socket, launcher.subprocess, launcher.verify_game
    lock = native = monitor = None
    recovering = False
    stop = threading.Event()
    journal = (out/'events.jsonl').open('x', encoding='utf-8')
    mutex = threading.Lock()

    def event(kind, **values):
        with mutex:
            journal.write(json.dumps(dict(kind=kind, tick=int(clock()), state=state, **values))+'\n'); journal.flush()

    def verified(*args, **kwargs):
        value = real_verify(*args, **kwargs)
        state['validation_completed'] = True; event('validation-complete')
        return value

    def pair(*args, **kwargs):
        nonlocal lock
        if recovering:
            assert state['validation_completed'] and state['lock_released'] and lock.handle is None
            event('relaunch-validated-with-read-access')
            return real_socket.socketpair(*args, **kwargs)
        assert state['validation_completed'] and lock is None
        lock = locks.OwnedFileLock(target, game, allow_read=False)
        state['lock_acquired'] = True
        event('read-lock-acquired', probe_winerror=lock.probe_winerror, target=str(target))
        return real_socket.socketpair(*args, **kwargs)

    def watch(log):
        try:
            while not stop.wait(.1):
                if not log.exists(): continue
                with log.open('rb') as stream:
                    stream.seek(max(0, log.stat().st_size-2*1024*1024))
                    text = stream.read(2*1024*1024).decode('utf-8', errors='replace')
                lines = refusal_lines(text, target)
                if not lines: continue
                state['failure_observed'] = True
                event('original-read-failure', lines=lines[:8])
                lock.close(); state['lock_released'] = True
                event('read-lock-released')
                return
        except BaseException:
            state['observer_error'] = traceback.format_exc(); event('observer-error')

    def popen(command, **kwargs):
        nonlocal native, monitor
        assert state['lock_acquired'] and (native is None or recovering and native.poll() == 78)
        command = list(command)
        assert '-unified-client' in command and not any('smoke' in a for a in command)
        command += ['-native-quit-smoke', '-native-quit-mode=confirm']
        log = Path(command[command.index('-logFile')+1])
        if recovering:
            log = log.with_name(log.stem+'-recovery'+log.suffix)
            command[command.index('-logFile')+1] = str(log)
        assert log.is_relative_to(game) and not log.exists()
        info = kwargs['startupinfo'].copy(); info.wShowWindow = 0; kwargs['startupinfo'] = info
        launch_tick = int(clock())
        native = real_subprocess.Popen(command, **kwargs)
        state.update(process_started=True, pid=native.pid, log=str(log), command=command, launch_tick=launch_tick)
        event('native-started')
        if not recovering:
            monitor = threading.Thread(target=watch, args=(log,), name='postcheck-read-observer')
            monitor.start()
        return native

    launcher.verify_game = verified
    launcher.socket = SimpleNamespace(**{**vars(real_socket), 'socketpair': pair})
    launcher.subprocess = SimpleNamespace(**{**vars(real_subprocess), 'Popen': popen})
    stdout, stderr = io.StringIO(), io.StringIO()
    result = dict(passed=False)
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = package_client.main(['start', '--config', req['config']])
        result['first_launcher_exit_code'] = code
        result['first_game_exit_code'] = native.poll() if native else None
        if req.get('expect_startup_refusal'):
            if monitor: monitor.join(2)
            assert code == 1 and native.poll() == 78 and state['failure_observed'] and state['lock_released']
            assert monitor is not None and not monitor.is_alive() and 'observer_error' not in state
            assert 'Game startup failed.' in stdout.getvalue() and 'start the client again' in stdout.getvalue()
            raw = (game/'investigation/runtime'/f"dedicated-native-{state['pid']}.log").read_bytes()
            lines = raw[:raw.rfind(b'\n')+1].decode('utf-8').splitlines()
            scoped = [line for line in lines if (match := re.match(r'\[(\d+)\] ', line)) and int(match[1]) >= state['launch_tick']]
            fault_log = '\n'.join(scoped)+'\n'
            assert fault_log.count('BA_RESURRECTION_STARTUP_FAILURE_V1') == 1
            assert 'Offline initial state reached' not in fault_log
            (out/'fault-native.log').write_text(fault_log, encoding='utf-8')
            shutil.copyfile(state['log'], out/'fault-unity.log')
            result['fault'] = dict(state=json.loads(json.dumps(state)), game_exit_code=78,
                                   launcher_exit_code=code, stdout=stdout.getvalue())
            save(out/'fault-report.json', result['fault'])
            recovering = True; state['validation_completed'] = False; state['recovering'] = True
            event('same-profile-relaunch')
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = package_client.main(['start', '--config', req['config']])
        result['exit_code'] = code
        assert code == 0 and state['failure_observed'] and state['lock_released']
        assert 'observer_error' not in state and native.poll() == 0
        result['passed'] = True
    except BaseException:
        result['error'] = traceback.format_exc()
    finally:
        stop.set()
        if monitor: monitor.join(5); assert not monitor.is_alive()
        if lock: lock.close()
        launcher.verify_game, launcher.socket, launcher.subprocess = real_verify, real_socket, real_subprocess
        result.update(state=state, stdout=stdout.getvalue(), stderr=stderr.getvalue())
        save(out/'child-report.json', result); journal.close()
    return 0 if result['passed'] else 1


def run(args):
    from tools.owned_suspended_launch import SuspendedChild
    from tools.package_integrity import verify
    from tools.verify_native_storage import snapshot
    from tools import verify_native_quit as quit_probe, verify_unified_startup as startup
    from tools.run_secure_match import read_native_log
    from client_patch.patcher.bundle_loading import BUNDLE_DIR, BUILD
    game, package, seed, out, receipt = (getattr(args, k).resolve() for k in
                                      ('game', 'package', 'seed', 'output', 'helper_receipt'))
    assert all(p != OWNED and p.is_relative_to(OWNED) for p in (game, package, seed, out, receipt))
    assert 'replay230-manual01' not in str(game) and not out.exists()
    verify(package, 'client'); build = quit_probe.verify_build_receipt(game, receipt)
    out.mkdir()
    profile = 'nativestest_postcheck_'+secrets.token_hex(6)
    folder = game/'.battleaces-resurrection/profiles'/profile; folder.mkdir(parents=True)
    settings = folder/'gameconfig-localuser.toml'; shutil.copyfile(seed, settings)
    before = settings.read_bytes(); (out/'settings-before.toml').write_bytes(before)
    config = out/'client.json'
    save(config, dict(schema=3, game_directory=str(game), display_name='Postcheck Recovery', local_profile=profile))
    target = game/BUNDLE_DIR/TARGET; target_sha = sha(target)
    assert target_sha == BUILD.BUNDLES[TARGET][1]
    req = dict(game=str(game), package=str(package), config=str(config), bundle_sha256=target_sha,
               driver_sha256=sha(__file__), lock_sha256=sha(LOCK), expect_startup_refusal=args.expect_startup_refusal)
    save(out/'request.json', req)
    shared = Path.home()/'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
    def channels():
        return dict(settings=startup.shared_state(shared), replays=snapshot(shared.parent/'AutoSaveReplays'),
                    backup=snapshot(shared.parent/'StorageSyncBackup'))
    def identities():
        return {p:sha(game/p) for p in ('Battle Aces.exe', 'BattleAcesOffline.dll', 'GameAssembly.dll',
                                       '.battleaces-resurrection/patch-manifest.json')}
    source = quit_probe.sources() | {str(p.relative_to(ROOT)).replace('\\','/'):sha(p)
                                    for p in (Path(__file__), LOCK, ROOT/'tools/owned_suspended_launch.py')}
    for name in source:
        dest = out/'source'/name; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT/name, dest)
    report = dict(passed=False, scope=__doc__, helper_build=build, profile=profile,
                  source_sha256=source, shared_before=channels(), identities_before=identities(),
                  package_manifest_sha256=sha(package/'package-manifest.json'), config_sha256=sha(config))
    owner = None; started = time.monotonic(); observed_release = None
    try:
        owner = SuspendedChild.create([str(package/'program/runtime/python.exe'), '-I', '-B',
            str(Path(__file__).resolve()), '--child-request', str(out/'request.json')],
            cwd=out, creationflags=subprocess.CREATE_NO_WINDOW, owned_root=OWNED)
        owner.resume()
        while owner.poll() is None and time.monotonic()-started < 120:
            if (out/'events.jsonl').exists():
                live = observed_state(out)
                if live.get('observer_error'): raise AssertionError('original-read observer failed')
                if live.get('lock_released'):
                    if observed_release is None: observed_release = time.monotonic()
                    if time.monotonic()-observed_release >= 45:
                        raise AssertionError('no menu/Quit recovery within 45 seconds after read access restored')
            time.sleep(.1)
        assert owner.poll() is not None, 'owned observation exceeded 120 seconds'
        result = json.loads((out/'child-report.json').read_bytes()); report['child'] = result
        assert owner.poll() == 0 and result['passed'], 'owned child reported failure'
        live = result['state']
        text = read_native_log(game, live['pid'])
        (out/'native.log').write_text(text, encoding='utf-8')
        trace = quit_probe.current_trace_rows((folder/'quit-trace.jsonl').read_bytes(), live['pid'], owner.receipt['create_before_tick'])
        assert [r['event'] for r in trace] == ['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return']
        assert 'NATIVE QUIT owned menu verified:' in text and 'NATIVE QUIT original confirmation dispatch:' in text
        report['quit_trace'] = trace; report['passed'] = True
    except BaseException:
        report['error'] = traceback.format_exc()
    finally:
        if owner: owner.close(); report['owner'] = owner.receipt
        if (out/'events.jsonl').exists():
            live = observed_state(out); report['observed'] = live
            save(out/'live.json', live)
            if live.get('log') and Path(live['log']).is_file(): shutil.copyfile(live['log'], out/'unity.log')
            if live.get('pid'):
                text = read_native_log(game, live['pid'], since_tick=owner.receipt['create_before_tick'])
                (out/'native.log').write_text(text, encoding='utf-8')
        after = settings.read_bytes(); (out/'settings-after.toml').write_bytes(after)
        report.update(shared_after=channels(), identities_after=identities(), bundle_restored=sha(target)==target_sha,
                      source_unchanged=all(sha(ROOT/p)==h for p,h in source.items()),
                      saved_preferences_unchanged=tomllib.loads(before.decode('utf-8-sig'))==tomllib.loads(after.decode('utf-8-sig')),
                      elapsed_seconds=time.monotonic()-started)
        report['passed'] &= bool(owner and not owner.receipt['forced_cleanup'] and report['bundle_restored'] and
                                report['shared_before']==report['shared_after'] and report['identities_before']==report['identities_after'] and
                                report['source_unchanged'] and report['saved_preferences_unchanged'] and sha(config)==report['config_sha256'])
        verify(package, 'client'); save(out/'verification.json', report)
    print(json.dumps({k:report.get(k) for k in ('passed','error','elapsed_seconds')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child-request', type=Path)
    parser.add_argument('--expect-startup-refusal', action='store_true')
    for name in ('game', 'package', 'seed', 'output', 'helper-receipt'): parser.add_argument('--'+name, type=Path)
    args = parser.parse_args()
    raise SystemExit(child(args.child_request) if args.child_request else run(args))
