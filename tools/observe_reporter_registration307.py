"""Own a recipe28 menu process for a passive reporter SetEnabled call/argument observation."""
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
GAME = ROOT / 'local/privacy301-runtime01/game'
OUT = ROOT / 'local/privacy307-reporter-registration01'
GAME_ASSEMBLY_SHA = '5ae396233c1e48ec6a2043051030595d12c071bcdc4cc4a5b1ccf51a8aaeccb1'


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    if sha(GAME / 'GameAssembly.dll') != GAME_ASSEMBLY_SHA:
        raise ValueError('Owned recipe28 GameAssembly differs')
    manifest = json.loads((GAME / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    if manifest['telemetry']['recipe_version'] != 28 or manifest['diagnostics']['native_quit']:
        raise ValueError('Current default recipe28 owned install required')
    profile = 'nativestest_reporterregistration_' + secrets.token_hex(6)
    profile_dir = GAME / '.battleaces-resurrection/profiles' / profile
    if profile_dir.exists():
        raise ValueError('Fresh private profile required')
    command = [str(GAME / 'Battle Aces.exe'), '-offline-practice',
               '-practice-ai-experimental', '-local-profile=' + profile,
               '-player-name=Reporter registration observation', '-native-quit-smoke',
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
