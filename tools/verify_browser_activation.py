"""Owned172 startup/menu/Quit census; does not create or activate a web view.

REA attaches only to this suspended owned process. Explicit observer receipts
must arrive before resume. The owner tracks job identities and natural exit.
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
from client_patch.transport.launcher import verify_game
from tools.extract_descriptors import PE
from tools.frida_browser_activation import ENTRIES, build_source
from tools.helper_provenance import validate
from tools.owned_job_tracker import OwnedJobTracker
from tools.owned_process_directory import snapshot
from tools.owned_suspended_launch import SuspendedChild
from tools.verify_unified_startup import shared_state
from tools.verify_native_quit import sources

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/r171g'
COMPONENTS = ('Battle Aces.exe', 'GameAssembly.dll', 'UnityPlayer.dll', 'BattleAcesOffline.dll',
              'Battle Aces_Data/RuntimeInitializeOnLoads.json',
              'Battle Aces_Data/Plugins/x86_64/VuplexWebViewWindows.dll',
              'Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/Vuplex WebView.vuplex',
              'Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/libcef.dll',
              'Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/chrome_elf.dll')


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def inputs():
    return dict(components={name: sha(GAME / name) for name in COMPONENTS},
                sources=sources() | {name: sha(ROOT / name) for name in (
                    'tools/frida_browser_activation.py', 'tools/verify_browser_activation.py',
                    'tools/owned_suspended_launch.py', 'tools/owned_job_tracker.py',
                    'tools/owned_process_directory.py', 'tools/frida_attribution_exit.py',
                    'tools/frida_attribution_cwd.py', 'tools/frida_attribution_paths.py',
                    'tools/frida_attribution_clock.py', 'tools/frida_attribution_source.py',
                    'tools/review_crash_policy170.py')})


def run(output):
    out = Path(output).resolve()
    if os.name != 'nt' or out.parent != ROOT / 'local' or not out.name.startswith('activation172-'):
        raise ValueError('Fresh owned activation172 output required')
    verify_game(GAME, community=True, bridge_version=2, unified=True)
    manifest = json.loads((GAME / '.battleaces-resurrection/patch-manifest.json').read_bytes())
    if manifest['legacy_account_flow']['korean_login_compliance'] != 'disabled' or manifest['diagnostics']['native_quit']:
        raise ValueError('Default171 disabled legacy-flow recipe required')
    binding = validate(ROOT / 'build/helper-crash169-fix01/BattleAcesOffline.dll', (GAME / 'BattleAcesOffline.dll').read_bytes(), ROOT)
    out.mkdir(exist_ok=False); (out / 'tmp').mkdir()
    profile = 'nativestest_activation172_' + secrets.token_hex(6)
    folder = GAME / '.battleaces-resurrection/profiles' / profile
    if folder.exists():
        raise ValueError('Fresh private profile required')
    shared = Path.home() / 'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
    report = dict(passed=False, profile=profile, before=inputs(), shared_before=shared_state(shared),
                  helper_binding=binding, physical_acceptance=False, full_privacy_qualified=False,
                  scope='Owned instrumented startup/menu/normal Quit and process lifetime; review observer separately')
    child = tracker = None; started = time.monotonic()

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

    def wait_file(name):
        deadline = time.monotonic() + 240
        while not (out / name).exists():
            tracker.observe()
            if child.poll() is not None or time.monotonic() > deadline:
                raise TimeoutError('Observer handshake: ' + name)
            time.sleep(.02)
        return json.loads((out / name).read_bytes())

    def log():
        p = GAME / 'investigation/runtime' / f'dedicated-native-{child.pid}.log'
        return p.read_text(encoding='utf-8') if p.exists() else ''

    try:
        command = [str(GAME / 'Battle Aces.exe'), '-offline-practice', '-practice-ai-experimental',
                   '-local-profile=' + profile, '-player-name=Activation census172', '-telemetry-audit',
                   '-native-quit-smoke', '-native-quit-mode=confirm', '-screen-fullscreen', '0',
                   '-screen-width', '960', '-screen-height', '540', '-logFile', str(out / 'game.log')]
        info = subprocess.STARTUPINFO(); info.dwFlags |= subprocess.STARTF_USESHOWWINDOW; info.wShowWindow = 0
        environment = {'TEMP': str(out / 'tmp'), 'TMP': str(out / 'tmp')}
        old = {name: os.environ.get(name) for name in environment}; os.environ.update(environment)
        try:
            child = SuspendedChild.create(command, cwd=GAME, startupinfo=info, creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            for name, value in old.items():
                if value is None: os.environ.pop(name, None)
                else: os.environ[name] = value
        tracker = OwnedJobTracker(child); tracker.observe()
        cwd = snapshot(child, allow_uninitialized=True)
        descriptors = []
        for name, entries in ENTRIES.items():
            data = (GAME / name).read_bytes(); pe = PE(data)
            descriptors.append(dict(module=str(GAME / name), entries=[dict(name=label, rva=rva,
                sha256=hashlib.sha256(data[pe.offset(pe.base+rva):pe.offset(pe.base+rva)+16]).hexdigest()) for label, rva in entries.items()]))
        config = dict(image=str(GAME / 'Battle Aces.exe'), runId=secrets.token_hex(16),
                      fileRoots=[str(out), str(folder)], eventLimit=4096)
        (out / 'observer.js').write_text(build_source(config, dict(pid=child.pid, pebAddress=cwd['pebAddress']), descriptors), encoding='utf-8')
        report.update(config=config, descriptors=descriptors, pid=child.pid, thread=child.tid,
                      command=command, cwd=cwd, observer_sha256=sha(out / 'observer.js'))
        save('inputs.json', report)
        save('request.json', dict(pid=child.pid, script=str(out / 'observer.js')))
        attached = wait_file('rea-start.json')['structuredContent']
        loaded = wait_file('rea-load.json')['structuredContent']
        if attached['pid'] != child.pid or attached['mode'] != 'attach' or loaded['parameters']['session_id'] != attached['session_id']:
            raise ValueError('Observer session identity differs')
        observed = loaded['normalized_result']
        if observed['source_sha256'] != report['observer_sha256'] or observed['messages_truncated'] or any(m['type'] == 'error' for m in observed['messages']):
            raise ValueError('Observer load incomplete')
        release = wait_file('release.json')
        if release != dict(pid=child.pid, session_id=attached['session_id'], observer_sha256=report['observer_sha256']):
            raise ValueError('Observer release differs')
        child.resume(); save('resume.json', child.receipt)
        deadline = time.monotonic() + 90
        while child.poll() is None:
            tracker.observe()
            if time.monotonic() > deadline: raise TimeoutError('Startup/normal Quit deadline')
            time.sleep(.005)
        report.update(exit_code=child.poll(), tracker=tracker.settle(timeout=5))
        trace_path = folder / 'quit-trace.jsonl'
        trace = [json.loads(line) for line in trace_path.read_text().splitlines() if line]
        expected = ['armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return']
        if [r['event'] for r in trace] != expected or any(r['pid'] != child.pid for r in trace) or 'NATIVE QUIT owned menu verified:' not in log():
            raise ValueError('Original menu/Quit trace missing')
        report['quit_trace'] = trace
        if report['exit_code'] != 0 or not report['tracker']['complete'] or report['tracker']['final_accounting']['active'] or report['tracker']['final_accounting']['terminated']:
            raise ValueError('Complete natural lifetime required')
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        if tracker: report['tracker_closed'] = tracker.close()
        if child:
            child.close(); report['launch'] = child.receipt
            (out / 'native.log').write_text(log(), encoding='utf-8')
        report.update(after=inputs(), shared_after=shared_state(shared), elapsed_seconds=time.monotonic() - started)
        report['passed'] = (not report.get('error') and report.get('launch', {}).get('forced_cleanup') is False and
                            report.get('launch', {}).get('owned_process_reaped') is True and
                            report['before'] == report['after'] and report['shared_before'] == report['shared_after'])
        save('verification.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--output', required=True)
    result = run(parser.parse_args().output)
    print(json.dumps({k: result[k] for k in ('passed', 'error', 'exit_code', 'elapsed_seconds') if k in result}))
    raise SystemExit(0 if result['passed'] else 1)
