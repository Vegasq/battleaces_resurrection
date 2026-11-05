"""Own a tiny authored Windows process for a Frida hardware-watchpoint control."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from tools.owned_job_tracker import OwnedJobTracker
from tools.owned_suspended_launch import SuspendedChild

ROOT = Path(__file__).resolve().parents[1]
FIRST = 0x315977471
SECOND = 0x315977472


def own(folder: Path) -> None:
    folder = folder.resolve()
    if not folder.is_relative_to(ROOT/'local') or not re.fullmatch(r'adswatch_[0-9a-f]{12}', folder.name):
        raise ValueError('Fresh owned local/adswatch_<12hex> folder required')
    build = json.loads((folder/'build.json').read_text())
    source = ROOT/'tests/fixtures/ads_watch471/host.cpp'
    image = folder/'WatchControl.exe'
    if build != dict(authored_fixture=True,game_code=False,
                     source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                     exe_sha256=hashlib.sha256(image.read_bytes()).hexdigest()):
        raise ValueError('Authored fixture source/image receipt differs')
    for name in ('ready.json','wrote.json','finished.json','owner.json','write.flag','finish.flag'):
        if (folder/name).exists(): raise FileExistsError(folder/name)
    command = [str(image)]
    report = dict(authored_fixture=True, game_executed=False, passed=False,
                  command=command, build=build)
    launched = None
    tracker = None
    try:
        launched = SuspendedChild.create(command, cwd=folder,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
        tracker = OwnedJobTracker(launched)
        tracker.observe()
        launched.resume()
        deadline = time.monotonic() + 180
        while not (folder/'ready.json').exists():
            tracker.observe()
            if launched.poll() is not None: raise RuntimeError('authored child exited before ready')
            if time.monotonic() > deadline: raise TimeoutError('authored child ready timeout')
            time.sleep(.02)
        ready = json.loads((folder/'ready.json').read_text())
        if (ready['pid'] != launched.pid or ready['tid'] != launched.tid or
                ready['initial'] != 0 or int(ready['address'], 16) <= 0):
            raise RuntimeError('owned PID or initial slot differs')
        print(json.dumps(dict(ready=True,folder=str(folder),**ready)), flush=True)
        while launched.poll() is None:
            tracker.observe()
            if time.monotonic() > deadline: raise TimeoutError('authored child lifetime timeout')
            time.sleep(.05)
        report.update(ready=ready, exit_code=launched.poll(), tracker=tracker.settle(timeout=5),
                      wrote=json.loads((folder/'wrote.json').read_text()),
                      finished=json.loads((folder/'finished.json').read_text()))
        report['passed'] = (report['exit_code'] == 0 and report['tracker']['complete'] and
                            report['wrote'] == dict(value=FIRST, tid=ready['tid']) and
                            report['finished'] == dict(value=SECOND, tid=ready['tid']))
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if tracker: tracker.close()
        if launched:
            launched.close()
            report['launch'] = launched.receipt
        report['passed'] = bool(report['passed'] and report.get('launch', {}).get('forced_cleanup') is False and
                                hashlib.sha256(image.read_bytes()).hexdigest() == build['exe_sha256'])
        (folder/'owner.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(passed=report['passed'],exit_code=report['exit_code'],
                          job=report['tracker']['final_accounting'],
                          forced_cleanup=report['launch']['forced_cleanup'])), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    own(args.folder)
