"""Own a recipe25 menu process for a read-only IL2CPP delegate-slot observation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

from tools.owned_suspended_launch import SuspendedChild
from tools.owned_job_tracker import OwnedJobTracker

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy291-runtime01/game'
OUT = ROOT / 'local/privacy299-reporter-delegates01'
GAME_ASSEMBLY_SHA = 'c6e4480475e515e71a46e9579ee48d4db1a7f22062db5282d73c314a204d6b4e'


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    if sha(GAME / 'GameAssembly.dll') != GAME_ASSEMBLY_SHA:
        raise ValueError('Owned recipe25 GameAssembly differs')
    manifest = json.loads((GAME / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    if manifest['telemetry']['recipe_version'] != 25 or manifest['diagnostics']['native_quit']:
        raise ValueError('Current default recipe25 owned install required')
    profile = 'nativestest_reporterdelegates_' + secrets.token_hex(6)
    profile_dir = GAME / '.battleaces-resurrection/profiles' / profile
    if profile_dir.exists():
        raise ValueError('Fresh private profile required')
    command = [str(GAME / 'Battle Aces.exe'), '-offline-practice',
               '-practice-ai-experimental', '-local-profile=' + profile,
               '-player-name=Reporter delegate observation', '-native-quit-smoke',
               '-native-quit-mode=confirm', '-native-quit-gate-smoke',
               '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540',
               '-logFile', str(OUT / 'game.log')]
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    child = tracker = None
    report = dict(passed=False, game=str(GAME), profile=profile,
                  gameassembly_sha256=GAME_ASSEMBLY_SHA, command=command)
    try:
        child = SuspendedChild.create(command, cwd=GAME, startupinfo=info,
                                      creationflags=subprocess.CREATE_NO_WINDOW,
                                      owned_root=ROOT / 'local')
        tracker = OwnedJobTracker(child)
        tracker.observe()
        report.update(pid=child.pid, tid=child.tid)
        write('launch.json', report)
        print(json.dumps(dict(ready=True, pid=child.pid, profile=str(profile_dir),
                              output=str(OUT))), flush=True)
        deadline = time.monotonic() + 120
        while not (OUT / 'resume.ready').exists():
            tracker.observe()
            if child.poll() is not None or time.monotonic() >= deadline:
                raise TimeoutError('Frida attach/load handshake missing')
            time.sleep(.05)
        child.resume()
        write('resume.json', child.receipt)
        deadline = time.monotonic() + 240
        while child.poll() is None:
            tracker.observe()
            if (OUT / 'allow-quit.ready').exists() and profile_dir.exists():
                gate = profile_dir / 'native-quit.ready'
                if not gate.exists():
                    with gate.open('xb'):
                        pass
            if time.monotonic() >= deadline:
                raise TimeoutError('Owned menu/normal Quit deadline')
            time.sleep(.05)
        report.update(exit_code=child.poll(), job=tracker.settle(timeout=5))
        if report['exit_code'] != 0 or not report['job']['complete'] or \
                report['job']['final_accounting']['active'] or \
                report['job']['final_accounting']['terminated']:
            raise ValueError('Original Quit or owned job accounting failed')
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        if tracker:
            report['tracker_closed'] = tracker.close()
        if child:
            child.close()
            report['launch'] = child.receipt
        report['passed'] = bool(not report.get('error') and
                                report.get('launch', {}).get('forced_cleanup') is False and
                                report.get('launch', {}).get('owned_process_reaped') is True)
        write('verification.json', report)
        print(json.dumps(dict(passed=report['passed'], error=report.get('error'),
                              output=str(OUT))), flush=True)


if __name__ == '__main__':
    main()
