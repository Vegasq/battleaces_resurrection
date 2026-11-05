"""Own one recipe23 Try Deck/result/Continue/Quit caller observation.

Use --prepare once to copy the existing owned r171g build to a fresh diagnostic
directory on C: (E: lacks space). No shared profiles, links or prior runtime logs
are copied. REA attach/load receipts and exact release are required before resume.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time
import traceback

from client_patch.transport.launcher import verify_game
from tools.frida_ads_caller import describe_unity
from tools.frida_ads_game import build_source, review_rows
from tools.helper_provenance import validate as helper_validate
from tools.owned_job_tracker import OwnedJobTracker
from tools.owned_suspended_launch import SuspendedChild
from tools.verify_browser_activation import COMPONENTS, sha
from tools.verify_native_quit import sources, practice_evidence
from tools.verify_unified_startup import shared_state

ROOT = Path(__file__).resolve().parents[1]
BASE = Path.home() / 'AppData/Local/BattleAcesDiagnostics/local'
SOURCE = ROOT / 'local/r171g'
ORIGINAL = ROOT.parent.parent / 'BattleAcesBeta_untouched/UnityPlayer.dll'


def save(folder, name, value):
    (folder / name).write_bytes((json.dumps(value, indent=2) + '\n').encode())


def read(folder, name):
    return json.loads((folder / name).read_bytes())


def inputs(game):
    return dict(components={n: sha(game/n) for n in COMPONENTS},
                sources=sources() | {n: sha(ROOT/n) for n in (
                    'tools/frida_ads_caller.py', 'tools/frida_ads_game.py', 'tools/verify_ads_game.py',
                    'tools/owned_suspended_launch.py', 'tools/owned_job_tracker.py',
                    'tools/verify_browser_activation.py')})


def prepare(out, reuse=None):
    out.mkdir(exist_ok=False)
    BASE.mkdir(parents=True, exist_ok=True)
    if reuse is not None:
        previous = read(reuse, 'verification.json'); copied = read(reuse, 'copy.json')
        game = Path(copied['game'])
        if game.parent != BASE or not re.fullmatch('adscaller_[0-9a-f]{12}', game.name) or \
                previous['launch']['owned_process_reaped'] is not True or previous['launch']['forced_cleanup'] is not False or \
                previous['launch']['job_final']['active_processes'] != 0 or previous['game'] != str(game):
            raise ValueError('Reuse requires a closed owned copy with no active job')
        (game/'investigation/runtime').mkdir(parents=True, exist_ok=True)
        save(out, 'copy.json', copied | dict(reused_after=str(reuse)))
        print(json.dumps(dict(prepared=True, game=str(game), reused_after=str(reuse))), flush=True)
        return
    game = BASE / ('adscaller_' + secrets.token_hex(6))
    # Exclude only prior profiles/runtime and top-level logs; preserve all assets.
    def ignore(path, names):
        relative = Path(path).relative_to(SOURCE)
        if relative == Path('.'):
            return [n for n in names if n == 'investigation' or n.lower().endswith('.log')]
        if relative == Path('.battleaces-resurrection'):
            return [n for n in names if n in ('profiles', '.rc-setup.lock')]
        return []
    if shutil.disk_usage(BASE).free < 12 * 1024**3:
        raise ValueError('12GiB free required for independent client copy')
    shutil.copytree(SOURCE, game, ignore=ignore)
    (game/'investigation/runtime').mkdir(parents=True, exist_ok=True)
    verify_game(game, community=True, bridge_version=2, unified=True)
    copied = {n: sha(game/n) for n in COMPONENTS}
    if copied != {n: sha(SOURCE/n) for n in COMPONENTS}:
        raise ValueError('Independent copied components differ')
    save(out, 'copy.json', dict(source=str(SOURCE), game=str(game), independent_copy=True,
                              excluded=['investigation', 'top-level *.log', 'profiles', '.rc-setup.lock'], components=copied))
    print(json.dumps(dict(prepared=True, game=str(game))), flush=True)


def run(out):
    copy = read(out, 'copy.json'); game = Path(copy['game'])
    if game.parent != BASE or not re.fullmatch('adscaller_[0-9a-f]{12}', game.name) or not copy['independent_copy']:
        raise ValueError('Fresh independent owned diagnostic copy required')
    for name in ('inputs.json', 'request.json', 'verification.json', 'release.json'):
        if (out/name).exists(): raise ValueError('Fresh observation artifacts required')
    verify_game(game, community=True, bridge_version=2, unified=True)
    manifest = read(game/'.battleaces-resurrection', 'patch-manifest.json')
    if manifest['legacy_account_flow']['korean_login_compliance'] != 'disabled' or manifest['diagnostics']['native_quit']:
        raise ValueError('Default current recipe required')
    descriptor = describe_unity(ORIGINAL.read_bytes(), (game/'UnityPlayer.dll').read_bytes())
    binding = helper_validate(ROOT/'build/helper-crash169-fix01/BattleAcesOffline.dll', (game/'BattleAcesOffline.dll').read_bytes(), ROOT)
    (out/'tmp').mkdir()
    (game/'investigation/runtime').mkdir(parents=True, exist_ok=True)
    profile = 'nativestest_adscaller_' + secrets.token_hex(6)
    folder = game/'.battleaces-resurrection/profiles'/profile
    if folder.exists(): raise ValueError('Fresh private profile required')
    shared = Path.home()/'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
    report = dict(passed=False, game=str(game), profile=profile, before=inputs(game), shared_before=shared_state(shared),
                  helper_binding=binding, physical_acceptance=False, full_privacy_qualified=False)
    child = tracker = None; started = time.monotonic()

    def wait_file(name):
        deadline = time.monotonic() + 240
        while not (out/name).exists():
            tracker.observe()
            if child.poll() is not None or time.monotonic() > deadline:
                raise TimeoutError('Observer handshake: ' + name)
            time.sleep(.02)
        return read(out, name)

    def log():
        path = game/'investigation/runtime'/f'dedicated-native-{child.pid}.log'
        return path.read_text(encoding='utf-8') if path.exists() else ''

    try:
        command = [str(game/'Battle Aces.exe'), '-offline-practice', '-practice-ai-experimental',
                   '-local-profile='+profile, '-player-name=Caller observation182',
                   '-native-quit-smoke', '-native-quit-mode=confirm', '-native-quit-after-practice',
                   '-practice-ai-smoke', '-practice-ai-smoke-matches=1', '-practice-ai-smoke-frames=3600',
                   '-practice-ai-smoke-delay-ms=3000', '-lan-audit', '-lan-smoke',
                   '-screen-fullscreen', '0', '-screen-width', '960', '-screen-height', '540', '-logFile', str(out/'game.log')]
        info = subprocess.STARTUPINFO(); info.dwFlags |= subprocess.STARTF_USESHOWWINDOW; info.wShowWindow = 0
        environment = {'TEMP': str(out/'tmp'), 'TMP': str(out/'tmp')}
        old = {n: os.environ.get(n) for n in environment}; os.environ.update(environment)
        try:
            child = SuspendedChild.create(command, cwd=game, startupinfo=info, creationflags=subprocess.CREATE_NO_WINDOW, owned_root=BASE)
        finally:
            for n, v in old.items():
                if v is None: os.environ.pop(n, None)
                else: os.environ[n] = v
        tracker = OwnedJobTracker(child); tracker.observe()
        config = dict(image=command[0], profile=str(folder), argv=command, pid=child.pid, runId=secrets.token_hex(16), unity=descriptor)
        (out/'observer.js').write_bytes(build_source(config).encode())
        report.update(config=config, pid=child.pid, thread=child.tid, command=command, observer_sha256=sha(out/'observer.js'))
        save(out, 'inputs.json', report)
        save(out, 'request.json', dict(pid=child.pid, script=str(out/'observer.js')))
        print(json.dumps(dict(ready=True, pid=child.pid, output=str(out))), flush=True)
        start = wait_file('rea-start.json')['structuredContent']
        loaded = wait_file('rea-load.json')['structuredContent']
        observed = loaded['normalized_result']
        if start['pid'] != child.pid or start['mode'] != 'attach' or loaded['parameters']['session_id'] != start['session_id'] or \
                observed['source_sha256'] != report['observer_sha256'] or observed['messages_truncated'] or \
                any(m['type'] == 'error' for m in observed['messages']) or \
                not any(m.get('payload', {}).get('kind') == 'ads-exit-armed' for m in observed['messages']):
            raise ValueError('Complete owned observer load required')
        release = wait_file('release.json')
        if release != dict(pid=child.pid, session_id=start['session_id'], observer_sha256=report['observer_sha256']):
            raise ValueError('Observer release differs')
        child.resume(); save(out, 'resume.json', child.receipt)
        deadline = time.monotonic() + 300
        while child.poll() is None:
            tracker.observe()
            if time.monotonic() > deadline: raise TimeoutError('Practice/Continue/normal Quit deadline')
            time.sleep(.005)
        report.update(exit_code=child.poll(), tracker=tracker.settle(timeout=5))
        trace = [json.loads(line) for line in (folder/'quit-trace.jsonl').read_text().splitlines() if line]
        if [r['event'] for r in trace] != ['armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return'] or \
                any(r['pid'] != child.pid for r in trace):
            raise ValueError('Original menu/Quit trace missing')
        report.update(quit_trace=trace, practice=practice_evidence(game, out, child.pid, log()))
        if report['exit_code'] != 0 or not report['tracker']['complete'] or report['tracker']['errors'] or \
                report['tracker']['final_accounting']['active'] or report['tracker']['final_accounting']['terminated']:
            raise ValueError('Complete natural lifetime required')
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        if tracker: report['tracker_closed'] = tracker.close()
        if child:
            child.close(); report['launch'] = child.receipt
            (out/'native.log').write_bytes(log().encode())
        report.update(after=inputs(game), shared_after=shared_state(shared), elapsed_seconds=time.monotonic()-started)
        report['passed'] = bool(not report.get('error') and report.get('launch', {}).get('forced_cleanup') is False and
                               report.get('launch', {}).get('owned_process_reaped') is True and
                               report['before'] == report['after'] and report['shared_before'] == report['shared_after'])
        save(out, 'verification.json', report)
    return report


def review(out):
    owner = read(out, 'verification.json'); ready = read(out, 'inputs.json'); config = ready['config']
    def require(value, message):
        if not value: raise ValueError(message)
    require(owner['passed'] is True and owner['config'] == config and owner['command'] == config['argv'] and
            owner['pid'] == config['pid'] == owner['launch']['pid'] and owner['exit_code'] == 0 and
            owner['launch']['forced_cleanup'] is False and owner['launch']['owned_process_reaped'] is True,
            'Owned natural game lifetime required')
    require(owner['before'] == owner['after'] == inputs(Path(owner['game'])) and
            owner['shared_before'] == owner['shared_after'], 'Source/component/shared state changed')
    tracker = owner['tracker']; accounting = tracker['final_accounting']
    require(tracker['complete'] is True and tracker['errors'] == [] and accounting['active'] == accounting['terminated'] == 0 and
            accounting['total'] == len(tracker['records']) and tracker['root_pid'] == config['pid'] and
            all(r['exit']['wait_signaled'] is True and r['exit']['exit_code'] == 0 for r in tracker['records']), 'Complete unforced job required')
    require(owner['practice'] == practice_evidence(Path(owner['game']), out, config['pid'], (out/'native.log').read_text()),
            'Practice evidence differs')
    require((out/'observer.js').read_bytes() == build_source(config).encode() and sha(out/'observer.js') == ready['observer_sha256'],
            'Exact observer source required')
    start, loaded, final = (read(out, n) for n in ('rea-start.json', 'rea-load.json', 'rea-final.json'))
    require(all(not r.get('isError', False) for r in (start, loaded, final)), 'REA operation error')
    start = start['structuredContent']; loaded = loaded['structuredContent']; final = final['structuredContent']
    sid = start['session_id']; normalized = final['normalized_result']
    for item, operation in ((loaded, 'load_frida_script'), (final, 'frida_session_status')):
        require(item['provider']['id'] == 'frida' and item['confidence'] == 'observed' and item['operation'] == operation and
                item['parameters']['session_id'] == sid and re.fullmatch('ev_[0-9a-f]{64}', item['evidence_id']), 'REA provider/session differs')
    require(start['pid'] == normalized['pid'] == config['pid'] and start['mode'] == normalized['mode'] == 'attach' and
            start['device_id'] == normalized['device_id'] == 'local' and normalized['session_id'] == sid and
            loaded['normalized_result']['source_sha256'] == ready['observer_sha256'], 'REA target/source differs')
    script = loaded['normalized_result']['script_id']
    require(len(normalized['scripts']) == 1 and normalized['scripts'][0]['script_id'] == script and
            loaded['normalized_result']['source_path'] == str(out/'observer.js') and
            normalized['messages'][:len(loaded['normalized_result']['messages'])] == loaded['normalized_result']['messages'] and
            all(m['script_id'] == script for m in normalized['messages']) and
            read(out, 'release.json') == dict(pid=config['pid'], session_id=sid, observer_sha256=ready['observer_sha256']),
            'Single loaded script and pre-resume receipt required')
    require(normalized['messages_truncated'] is False and loaded['normalized_result']['messages_truncated'] is False and
            all(m['type'] == 'send' for m in normalized['messages']), 'Complete error-free messages required')
    result = review_rows([m['payload'] for m in normalized['messages']], config)
    close = read(out, 'rea-close.json')
    require(not close.get('isError', False) and close['structuredContent'] == dict(target_state='unknown'), 'REA close receipt required')
    return result | dict(evidence_id=final['evidence_id'], observer_sha256=ready['observer_sha256'],
                         natural_exit=0, job=accounting, practice=owner['practice'], physical_acceptance=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--reuse-copy', type=Path, help='Prior completed owned evidence directory; always uses a fresh profile')
    parser.add_argument('--review', action='store_true')
    args = parser.parse_args(); out = args.output.resolve()
    if os.name != 'nt' or out.parent != ROOT/'local' or not out.name.startswith('adscaller182-'):
        raise ValueError('Owned ignored Windows output required')
    if args.reuse_copy is not None and (not args.prepare or args.reuse_copy.resolve().parent != ROOT/'local'):
        raise ValueError('Reuse is only for preparation from prior owned evidence')
    if args.prepare: prepare(out, args.reuse_copy.resolve() if args.reuse_copy else None)
    elif args.review:
        result = review(out); save(out, 'caller-review.json', result); print(json.dumps(result, indent=2))
    else:
        result = run(out)
        print(json.dumps({k: result[k] for k in ('passed', 'error', 'exit_code', 'elapsed_seconds') if k in result}))
        raise SystemExit(0 if result['passed'] else 1)
