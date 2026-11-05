"""Own one private recipe39 menu/Quit run for the native listener write sensor."""
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
GAME = ROOT/'local/privacy441-game01'
EXPECTED = {
    'Battle Aces.exe': '0ae4c67586e0aced96641e8e06c0b845d2d6d77c0cfb5b7533b9afee89eb77f6',
    'UnityPlayer.dll': 'ce5fb2e15d5997a9ed6e2971a61d25812b5f91ec918ce0eee8e88a7915c21cdd',
    'GameAssembly.dll': '368ccf4af6b8c94bdd5e1c7269b038c7c79b869b797c000c2a64d1daabbc9648',
    'BattleAcesOffline.dll': '3f97afc1f4247577a24a91fbcd789e01aa974939f661c9b3eecf95b1ab86a4c1',
}


def own(folder: Path) -> None:
    folder = folder.resolve()
    if not folder.is_relative_to(ROOT/'local') or folder.name != 'privacy472-adswatch01' or folder.exists():
        raise ValueError('Fresh owned privacy472-adswatch01 folder required')
    for name, digest in EXPECTED.items():
        if hashlib.sha256((GAME/name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Private game image differs: {name}')
    folder.mkdir()
    profile = 'nativestest_adswatch_'+secrets.token_hex(6)
    run_id = secrets.token_hex(16)
    command = [str(GAME/'Battle Aces.exe'),'-offline-practice','-practice-ai-experimental',
               '-local-profile='+profile,'-player-name=D5 watchpoint','-native-quit-smoke',
               '-native-quit-mode=confirm','-screen-fullscreen','0','-screen-width','960',
               '-screen-height','540','-logFile',str(folder/'game.log')]
    report = dict(passed=False,game=str(GAME),profile=profile,run_id=run_id,
                  command=command,images=EXPECTED)
    child = tracker = None
    try:
        child = SuspendedChild.create(command,cwd=GAME,creationflags=subprocess.CREATE_NO_WINDOW)
        tracker = OwnedJobTracker(child)
        tracker.observe()
        ready = dict(pid=child.pid,tid=child.tid,run_id=run_id,
                     game=str(GAME),unity=str(GAME/'UnityPlayer.dll'),images=EXPECTED)
        (folder/'ready.json').write_text(json.dumps(ready,indent=2))
        print(json.dumps(dict(ready=True,**ready)),flush=True)
        deadline = time.monotonic()+180
        while not (folder/'release.flag').exists():
            tracker.observe()
            if child.poll() is not None: raise RuntimeError('private game exited before release')
            if time.monotonic()>deadline: raise TimeoutError('observer release timeout')
            time.sleep(.05)
        child.resume()
        while child.poll() is None:
            tracker.observe()
            if time.monotonic()>deadline: raise TimeoutError('private game runtime timeout')
            time.sleep(.05)
        report.update(ready=ready,exit_code=child.poll(),tracker=tracker.settle(timeout=5))
        report['passed'] = report['exit_code']==0 and report['tracker']['complete']
    except BaseException as error:
        report['error']=repr(error)
        raise
    finally:
        if tracker: tracker.close()
        if child:
            child.close()
            report['launch']=child.receipt
        report['images_unchanged']=all(hashlib.sha256((GAME/name).read_bytes()).hexdigest()==digest
                                       for name,digest in EXPECTED.items())
        report['passed']=bool(report['passed'] and report['images_unchanged'] and
                              report.get('launch',{}).get('forced_cleanup') is False)
        (folder/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=report['passed'],exit_code=report['exit_code'],
                          job=report['tracker']['final_accounting'],
                          forced_cleanup=report['launch']['forced_cleanup'])),flush=True)


if __name__ == '__main__':
    own(ROOT/'local/privacy472-adswatch01')
