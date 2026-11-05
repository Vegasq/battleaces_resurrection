"""Own a recipe41 menu/Quit run for an exact loaded SDK expiry-entry probe."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time

from tools.owned_job_tracker import OwnedJobTracker
from tools.owned_suspended_launch import SuspendedChild

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy476-game01'
OUT = ROOT / 'local/privacy476-expiry-runtime01'
EXPECTED = {
    'Battle Aces.exe': '0ae4c67586e0aced96641e8e06c0b845d2d6d77c0cfb5b7533b9afee89eb77f6',
    'GameAssembly.dll': 'bc56260c985bcde5ae352654727ab88f89d28dd4f5754508e085fe860096dacc',
    'UnityPlayer.dll': 'd45b20470f41a05abf1513f7be65f27506f7dc63decfca625caab21792a04a98',
    'BattleAcesOffline.dll': '59aebb2db4a6778f817e6135b6ba767f54f1087cac69d9b65b5fda009fbb276f',
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> None:
    if OUT.exists() or any(sha(GAME / name) != digest for name, digest in EXPECTED.items()):
        raise ValueError('fresh owned output and exact recipe41 images required')
    OUT.mkdir()
    profile = 'nativestest_expiry_' + secrets.token_hex(6)
    run_id = secrets.token_hex(16)
    command = [str(GAME / 'Battle Aces.exe'), '-offline-practice', '-practice-ai-experimental',
               '-local-profile=' + profile, '-player-name=D5 expiry', '-native-quit-smoke',
               '-native-quit-mode=confirm', '-screen-fullscreen', '0', '-screen-width', '960',
               '-screen-height', '540', '-logFile', str(OUT / 'game.log')]
    report = dict(passed=False, game=str(GAME), profile=profile, run_id=run_id,
                  command=command, images=EXPECTED)
    child = tracker = None
    try:
        child = SuspendedChild.create(command, cwd=GAME, creationflags=subprocess.CREATE_NO_WINDOW)
        tracker = OwnedJobTracker(child)
        tracker.observe()
        ready = dict(pid=child.pid, tid=child.tid, run_id=run_id,
                     game=str(GAME / 'Battle Aces.exe'),
                     assembly=str(GAME / 'GameAssembly.dll'))
        (OUT / 'ready.json').write_text(json.dumps(ready, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(dict(ready=True, **ready)), flush=True)
        deadline = time.monotonic() + 180
        while not (OUT / 'release.flag').exists():
            tracker.observe()
            if child.poll() is not None: raise RuntimeError('owned game exited before release')
            if time.monotonic() > deadline: raise TimeoutError('observer release timeout')
            time.sleep(.05)
        child.resume()
        while child.poll() is None:
            tracker.observe()
            if time.monotonic() > deadline: raise TimeoutError('owned game runtime timeout')
            time.sleep(.05)
        report.update(ready=ready, exit_code=child.poll(), tracker=tracker.settle(timeout=5))
        report['passed'] = report['exit_code'] == 0 and report['tracker']['complete']
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if tracker: tracker.close()
        if child:
            child.close()
            report['launch'] = child.receipt
        report['images_unchanged'] = all(sha(GAME / name) == digest for name, digest in EXPECTED.items())
        report['passed'] = bool(report['passed'] and report['images_unchanged'] and
                                report.get('launch', {}).get('forced_cleanup') is False)
        (OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'], exit_code=report['exit_code'],
                          job=report['tracker']['final_accounting'],
                          forced_cleanup=report['launch']['forced_cleanup'])), flush=True)


if __name__ == '__main__':
    run()
