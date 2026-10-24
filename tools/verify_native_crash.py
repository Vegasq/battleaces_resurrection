"""Explicit owned crash169 check without Frida or replacement exception handlers.

Only the retained r169g diagnostic copy is eligible. This owner publishes a
closed gate; the game's original menu thread performs the checked native call.
No normal launcher, manual candidate, shared queue or global OS policy is changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import traceback

from tools.helper_provenance import validate
from tools.native_crash_gate import (FAULT, check_refusal, publish_arm,
                                     ready_saved_mode, validate_trigger, wait_for_crash_exit)
from tools.owned_job_tracker import OwnedJobTracker
from tools.owned_process_directory import snapshot
from tools.owned_suspended_launch import SuspendedChild
from tools.verify_unified_startup import shared_state

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ('Battle Aces.exe', 'GameAssembly.dll', 'UnityPlayer.dll', 'BattleAcesOffline.dll',
              'Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/chrome_elf.dll',
              'Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/libcef.dll')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def components(game):
    return {name: sha(game / name) for name in COMPONENTS}


def source_hashes():
    names = ['tools/verify_native_crash.py', 'tools/native_crash_gate.py',
             'tools/owned_suspended_launch.py', 'tools/owned_job_tracker.py',
             'tools/owned_process_directory.py', 'tools/helper_provenance.py',
             'tools/verify_unified_startup.py', 'client_patch/build.ps1']
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT / 'client_patch/src').rglob('*')
              if p.is_file() and p.suffix in ('.cpp', '.h', '.hpp')]
    return {name: sha(ROOT / name) for name in sorted(names)}


def run(game, helper, output):
    game, helper, output = (Path(p).resolve() for p in (game, helper, output))
    require(os.name == 'nt' and game == ROOT / 'local/r169g', 'Only the owned Windows r169g copy is eligible')
    require(output.parent == ROOT / 'local' and output.name.startswith('crash169-clean') and
            not output.exists(), 'A new crash169-clean output directory is required')
    require(helper.is_relative_to(ROOT / 'build'), 'An explicit built diagnostic helper is required')
    binding = validate(helper, (game / 'BattleAcesOffline.dll').read_bytes(), ROOT)
    profile = 'nativestest_crash169_' + secrets.token_hex(6)
    folder = game / '.battleaces-resurrection/profiles' / profile
    require(not folder.exists(), 'A new private profile is required')
    output.mkdir()
    (output / 'tmp').mkdir()
    shared = Path.home() / 'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
    report = dict(passed=False, instrumentation=False, profile=profile, game=str(game),
                  helper_binding=binding, components_before=components(game),
                  current166_before=components(ROOT / 'local/r134g'), shared_before=shared_state(shared),
                  source_before=source_hashes(), physical_input=False, visible_acceptance=False,
                  full_privacy_qualified=False, scope='owned original native crash and gate handoff only')
    child = tracker = None
    started = time.monotonic()

    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

    def log():
        path = game / 'investigation/runtime' / f'dedicated-native-{child.pid}.log'
        return path.read_text(encoding='utf-8') if path.exists() else ''

    try:
        command = [str(game / 'Battle Aces.exe'), '-offline-practice', '-practice-ai-experimental',
                   '-local-profile=' + profile, '-player-name=Clean native crash169',
                   '-telemetry-audit', '-native-crash-probe', '-screen-fullscreen', '0',
                   '-screen-width', '960', '-screen-height', '540', '-logFile', str(output / 'game.log')]
        environment = {'TEMP': str(output / 'tmp'), 'TMP': str(output / 'tmp'),
                       '_NT_SYMBOL_PATH': '', '_NT_ALT_SYMBOL_PATH': ''}
        old_environment = {name: os.environ.get(name) for name in environment}
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        os.environ.update(environment)
        try:
            child = SuspendedChild.create(command, cwd=game, startupinfo=startup,
                                          creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            for name, value in old_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        report.update(command=command, pid=child.pid, thread=child.tid,
                      child_environment_overrides=environment)
        tracker = OwnedJobTracker(child)
        tracker.observe()
        child.resume()
        deadline = time.monotonic() + 90
        while True:
            tracker.observe()
            text = log()
            check_refusal(text)
            if 'NATIVE CRASH ready:' in text:
                break
            require(child.poll() is None, 'Native process exited before readiness')
            if time.monotonic() >= deadline:
                raise TimeoutError('Native preflight readiness deadline exceeded')
            time.sleep(.01)
        report['saved_mode'] = saved_mode = ready_saved_mode(text, child.tid)
        require('crashSignatures=4/4' in text and 'recipeVersion=23' in text,
                'Current recipe audit is incomplete')
        require(source_hashes() == report['source_before'] and components(game) == report['components_before'] and
                components(ROOT / 'local/r134g') == report['current166_before'] and
                shared_state(shared) == report['shared_before'], 'Pre-arm inputs changed')
        report['cwd_ready'] = snapshot(child)
        save('prearm.json', dict(pid=child.pid, native_log=text, cwd=report['cwd_ready'], instrumentation=False))
        check_refusal(log())
        arm = publish_arm(folder)
        report.update(arm_published=True, arm_sha256=sha(arm), arm_publication='closed-file-no-replacement-rename')
        report['exit_code'] = wait_for_crash_exit(child, tracker, log, saved_mode=saved_mode)
        report['tracker'] = tracker.settle(timeout=5)
        validate_trigger(log(), child.tid, saved_mode=saved_mode)
        require(report['tracker']['complete'] and
                report['tracker']['final_accounting'] == dict(total=1, active=0, terminated=0),
                'Complete natural root-only lifetime required')
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        if tracker:
            report['tracker_before_cleanup'] = tracker.report()
            report['tracker_closed'] = tracker.close()
        if child:
            child.close()
            report['launch'] = child.receipt
            report['native_log'] = log()
        report.update(source_after=source_hashes(), components_after=components(game),
                      current166_after=components(ROOT / 'local/r134g'), shared_after=shared_state(shared),
                      elapsed_seconds=time.monotonic() - started)
        report['passed'] = (not report.get('error') and report.get('exit_code') == FAULT and
                            report.get('tracker', {}).get('complete') is True and
                            report.get('launch', {}).get('forced_cleanup') is False and
                            report.get('launch', {}).get('owned_process_reaped') is True and
                            report['components_before'] == report['components_after'] and
                            report['current166_before'] == report['current166_after'] and
                            report['shared_before'] == report['shared_after'] and
                            report['source_before'] == report['source_after'])
        save('verification.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', type=Path, required=True)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--arm-native-crash', action='store_true', required=True)
    args = parser.parse_args()
    result = run(args.game_dir, args.helper, args.output)
    print(json.dumps({key: result[key] for key in ('passed', 'exit_code', 'error', 'elapsed_seconds') if key in result}))
    return not result['passed']


if __name__ == '__main__':
    raise SystemExit(main())
