"""Owned normal-menu replay API entry/observation/exit/original-Quit control.

An external spawn adapter adds explicit diagnostics to the existing direct-game
Quit verifier. This is not a user-exposed replay browser or a physical UI test.
The original high-level file loader owns Load and Play; original ReplayEndGame
is invoked only as a diagnostic exit API, never mislabeled as a button click.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import secrets
import threading
import traceback
import zlib
from pathlib import Path
from types import SimpleNamespace

from tools import verify_native_quit as quit_probe
from tools import replay_menu_evidence as evidence
from tools.verify_native_storage import replay_evidence
from tools.replay_retention import api_path
from tools.run_secure_match import read_native_log

ROOT = Path(__file__).resolve().parents[1]
require = evidence.require


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    return quit_probe.sources() | {p.relative_to(ROOT).as_posix(): sha(p) for p in (
        Path(__file__), Path(evidence.__file__), ROOT/'tools/verify_native_storage.py', ROOT/'tools/replay_retention.py')}


def scoped_spawn_module(original,spawn):
    # The Quit module's game spawn is the seam. Mutating subprocess.Popen on
    # the shared module would also intercept Git/source checks and other tools.
    return SimpleNamespace(**{**vars(original),'Popen':spawn})


def run(args):
    invalid_first=getattr(args,'invalid_first',False)
    semantic_first=getattr(args,'semantic_first',False)
    partial_first=getattr(args,'partial_first',False)
    require(not partial_first or (getattr(args,'button_exit',False) and getattr(args,'cancel_first',False) and not invalid_first and not semantic_first),
            '--partial-first requires separate --button-exit --cancel-first without early-refusal cases')
    require(not semantic_first or invalid_first,'--semantic-first requires --invalid-first')
    require(not invalid_first or (getattr(args,'button_exit',False) and getattr(args,'cancel_first',False)),
            '--invalid-first requires --button-exit and --cancel-first')
    game, output, source_report = (p.resolve() for p in (args.game, args.output, args.source_verification))
    require(args.visible and 60 <= args.timeout <= 300 and all(p.is_relative_to(ROOT/'local') for p in
            (game, output, source_report)), 'owned bounded graphical Windows control required')
    source_raw = source_report.read_bytes()
    source = json.loads(source_raw)
    request = json.loads((source_report.parent/'request.json').read_bytes())
    require(source['passed'] is True and source['native_codec']['original_codec'] is True,
            'source must have passed original native codec qualification')
    original = Path(request['game'])/'.battleaces-resurrection/profiles'/source['profile']/'AutoSaveReplays'/source['replay']['native_filename']
    require(original.resolve().is_relative_to(ROOT/'local'), 'source must be an owned retained recording')
    raw = api_path(original).read_bytes()
    replay = replay_evidence(raw)
    require(all(replay[k] == source['replay'][k] for k in replay), 'original codec recording changed')
    output.mkdir(parents=True, exist_ok=False)
    profile = 'nativestest_replayui_'+secrets.token_hex(6)
    folder = game/'.battleaces-resurrection/profiles'/profile
    (folder/'AutoSaveReplays').mkdir(parents=True, exist_ok=False)
    seed = folder/'AutoSaveReplays/native-menu-replay.rep'
    with api_path(seed).open('xb') as stream:
        stream.write(raw)
    invalid_seed=None
    if invalid_first:
        # The existing owned codec enumerator excludes authored-retention-*;
        # only the explicit high-level malformed control opens this file.
        invalid_seed=folder/'AutoSaveReplays/authored-retention-invalid-menu.rep'
        with api_path(invalid_seed).open('xb') as stream:stream.write(bytes([7]))
    semantic_seeds=[]
    if semantic_first:
        for name,leaf,decoded,expected in (
            ('empty-replay','authored-retention-empty-menu.rep',b'',bytes.fromhex('0300')),
            ('missing-game-config','authored-retention-missing-config-menu.rep',bytes.fromhex('0a00'),bytes.fromhex('e3620000'))):
            compressor=zlib.compressobj(level=9,wbits=-zlib.MAX_WBITS)
            encoded=compressor.compress(decoded)+compressor.flush()
            require(encoded==expected,'authored semantic fixture encoding differs from the native guard')
            path=folder/'AutoSaveReplays'/leaf
            with api_path(path).open('xb') as stream:stream.write(encoded)
            semantic_seeds.append(dict(case=name,path=str(path),bytes=len(encoded),sha256=sha(path),
                                       decoded_bytes=len(decoded),decoded_hex=decoded.hex()))
    partial_seed=None
    if partial_first:
        compressor=zlib.compressobj(level=9,wbits=-zlib.MAX_WBITS)
        encoded=compressor.compress(bytes.fromhex('0a020a00'))+compressor.flush()
        require(encoded==bytes.fromhex('e362e2620000'),'partial fixture encoding differs from the native guard')
        path=folder/'AutoSaveReplays/authored-retention-partial-menu.rep'
        with api_path(path).open('xb') as stream:stream.write(encoded)
        partial_seed=dict(path=str(path),sha256=sha(path),bytes=len(encoded),decoded_hex='0a020a00')
    report = dict(passed=False, scope=__doc__, profile=profile, replay=replay,
                  source_verification=str(source_report), source_verification_sha256=sha(source_report),
                  source_replay=str(original), seed=str(seed), sources_before=sources())
    button_exit=getattr(args,'button_exit',False)
    cancel_first=getattr(args,'cancel_first',False)
    require(not cancel_first or button_exit,'--cancel-first requires --button-exit')
    report['cancel_first']=cancel_first
    report['invalid_first']=invalid_first
    report['semantic_first']=semantic_first
    report['semantic_seeds']=semantic_seeds
    report['partial_first']=partial_first
    report['partial_seed']=partial_seed
    if invalid_seed:report['invalid_seed']=dict(path=str(invalid_seed),bytes=1,sha256=sha(invalid_seed))
    report['exit_route']='original-visible-button' if button_exit else 'original-exit-api'
    stop = threading.Event()
    process = thread = None
    original_subprocess = quit_probe.subprocess
    original_spawn = original_subprocess.Popen
    gate_errors = []
    clock = ctypes.WinDLL('kernel32').GetTickCount64
    clock.restype = ctypes.c_ulonglong

    def monitor(tick):
        try:
            while not stop.wait(.05) and process.poll() is None:
                text = read_native_log(game, process.pid, since_tick=tick)
                completed=evidence.PARTIAL_COMPLETE if partial_first else evidence.SEMANTIC_COMPLETE if semantic_first else evidence.INVALID_COMPLETE if invalid_first else evidence.CANCEL_COMPLETE if cancel_first else evidence.BUTTON_COMPLETE if button_exit else evidence.COMPLETE
                failed_cleanup=(button_exit and 'Native replay menu control failed:' in text and
                    'NATIVE REPLAY BUTTON failure cleanup:' in text)
                if completed not in text and not failed_cleanup:
                    continue
                require(failed_cleanup or (text.count(completed) == 1 and 'Native replay menu control failed:' not in text),
                        'original exit completion is ambiguous')
                # This gate permits cleanup, not acceptance. The original Quit
                # verifier independently rechecks idle ownership before dispatch.
                # Final metadata/UI assertions can still fail after natural Quit.
                temporary = folder/'native-quit.ready.tmp'
                with temporary.open('xb'):
                    pass
                temporary.rename(folder/'native-quit.ready')
                report['quit_gate_released'] = True
                report['failure_cleanup_gate']=failed_cleanup
                return
        except BaseException as error:
            gate_errors.append(repr(error))

    def spawn(command, *positional, **keywords):
        nonlocal process, thread
        require(process is None and Path(command[0]).resolve() == game/'Battle Aces.exe' and
                '-local-profile='+profile in command and '-practice-ai-smoke' not in command,
                'one owned ordinary direct-game spawn required')
        extras = ['-native-replay-menu-smoke', '-native-quit-gate-smoke', '-replay-binding-inventory',
                  '-replay-signal-inventory', '-replay-nody-inventory']
        if button_exit:extras.append('-native-replay-menu-button-smoke')
        if cancel_first:extras.append('-native-replay-menu-cancel-smoke')
        if invalid_first:extras.append('-native-replay-menu-invalid-smoke')
        if semantic_first:extras.append('-native-replay-menu-semantic-smoke')
        if partial_first:extras.append('-native-replay-menu-partial-smoke')
        require(not any(flag in command for flag in extras), 'replay control already injected')
        report['quit_control_arguments_before_adapter'] = list(command)
        command.extend(extras)
        report['actual_arguments'] = list(command)
        tick = clock()
        process = original_spawn(command, *positional, **keywords)
        report.update(pid=process.pid, launch_tick=tick)
        thread = threading.Thread(target=monitor, args=(tick,), daemon=False)
        thread.start()
        return process

    try:
        control = SimpleNamespace(game=game, output=output/'native-quit', shared_settings=args.shared_settings,
                                  helper_build_receipt=args.helper_build_receipt, profile=profile,
                                  helper_source_revision=getattr(args,'helper_source_revision',None),
                                  display_name='Replay Menu API Control', mode='confirm', visible=True,
                                  timeout=args.timeout, capture_dialog=False, after_practice=False,
                                  default_recipe=True, startup_tasks_audit=False)
        quit_probe.subprocess = scoped_spawn_module(original_subprocess,spawn)
        result = quit_probe.run(control)
        quit_probe.subprocess = original_subprocess
        native = json.loads((output/'native-quit/verification.json').read_bytes())
        report.update(native_verification_sha256=sha(output/'native-quit/verification.json'),
                      natural_exit=native['natural_exit'], forced_cleanup=native['forced_cleanup'])
        require(result == 0, 'owned native Quit control failed; retain its original report')
        require(native['passed'] is True and native['natural_exit'] is True and not native['forced_cleanup'] and
                native['exit_code'] == 0 and report.get('quit_gate_released') is True and not gate_errors,
                'original replay API cleanup/natural Quit incomplete')
        report['entry'] = evidence.validate((output/'native-quit/native.log').read_text(), replay,button_exit=button_exit,cancel_first=cancel_first,invalid_first=invalid_first,semantic_first=semantic_first,partial_first=partial_first)
        report['passed'] = True
    except BaseException as error:
        report.update(passed=False, error=repr(error), traceback=traceback.format_exc())
    finally:
        quit_probe.subprocess = original_subprocess
        stop.set()
        if thread:
            thread.join(timeout=10)
        report.update(monitor_stopped=thread is None or not thread.is_alive(), gate_errors=gate_errors,
                      seed_unchanged=False, source_unchanged=False, sources_unchanged=False)
        try:
            report.update(seed_unchanged=api_path(seed).read_bytes() == raw,
                          source_unchanged=api_path(original).read_bytes() == raw and source_report.read_bytes() == source_raw,
                          sources_after=sources())
            report['sources_unchanged'] = report['sources_before'] == report['sources_after']
            report['invalid_seed_unchanged']=invalid_seed is None or api_path(invalid_seed).read_bytes()==bytes([7])
            report['semantic_seeds_unchanged']=all(sha(Path(row['path']))==row['sha256'] for row in semantic_seeds)
            report['partial_seed_unchanged']=partial_seed is None or sha(Path(partial_seed['path']))==partial_seed['sha256']
        except BaseException as error:
            report.update(passed=False, final_file_check_error=repr(error))
        report['passed'] &= all(report.get(k,False) for k in ('monitor_stopped', 'seed_unchanged', 'source_unchanged', 'sources_unchanged','invalid_seed_unchanged','semantic_seeds_unchanged','partial_seed_unchanged'))
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('passed', 'pid', 'natural_exit', 'forced_cleanup', 'error') if k in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'output', 'source-verification', 'shared-settings', 'helper-build-receipt'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--visible', action='store_true')
    parser.add_argument('--helper-source-revision',help='explicit ancestor hash binding the tested frozen installed helper')
    parser.add_argument('--button-exit',action='store_true',help='invoke the existing leave input binding and original owned confirmation; no physical-input claim')
    parser.add_argument('--cancel-first',action='store_true',help='Cancel the first confirmation, require same-world playback, then reopen and Confirm')
    parser.add_argument('--invalid-first',action='store_true',help='first refuse an owned invalid Deflate file through the original high-level loader')
    parser.add_argument('--semantic-first',action='store_true',help='also refuse parsed empty Replay and missing GameConfig before healthy playback')
    parser.add_argument('--partial-first',action='store_true',help='observe later initialization failure, replace data through the original loader, require healthy playback')
    parser.add_argument('--timeout', type=int, default=180)
    raise SystemExit(run(parser.parse_args()))
