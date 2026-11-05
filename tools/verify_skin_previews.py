"""Owned13-skin original picker preview/switch/Back/Quit runtime observations.

Screenshots require a separate visual review. A non-null native unit and event
membership do not establish correct pixels, audio, or in-match effects.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
from types import SimpleNamespace

from tools import verify_native_quit as quit_probe
from tools.verify_native_replay_menu import scoped_spawn_module
from tools.run_secure_match import read_native_log
from tools.owned_suspended_launch import job_accounting

ROOT = Path(__file__).resolve().parents[1]
COMPLETE = 'SKIN PREVIEW completed: uniqueSkins=13 selections=14 originalBack=1 sceneInactive=1 unitInactive=1 loadoutUnchanged=1 visualReviewRequired=1'
POOL_COMPLETE = 'SKIN POOL completed: families=3 selections=4 originalBack=1 rendererCleared=1 returnedToPool=1 sceneInactive=1 loadoutUnchanged=1'


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sources():
    return quit_probe.sources() | {Path(__file__).relative_to(ROOT).as_posix(): sha(__file__)}


def failed_return_can_quit(text, returned):
    """Cleanup permission only; the final case/cleanup validator still fails."""
    return ('SKIN PREVIEW failed:' in text and returned.get('original_back') is True
            and returned.get('loadout_unchanged') is True and returned.get('scene_active_after_back') is False)


def validate_cases(proof, returned, expected):
    require(proof.get('runtime_observations_complete') is True and proof.get('loadout_unchanged') is True,
            'preview runtime observations/loadout preservation incomplete')
    require(proof.get('visual_review_complete') is False, 'native observer must not assert visual acceptance')
    cases = proof['cases']
    require(len(expected) == 13 and len(cases) == 14 and [r['index'] for r in cases] == list(range(14)),
            'complete ordered13-skin plus return sequence required')
    require({r['item'] for r in cases[:13]} == set(expected) and cases[-1]['item'] == cases[0]['item'],
            'missing/duplicated skin or missing return to first skin')
    for row in cases:
        key = expected[row['item']]
        require(row['expected_event'] == key and key in row['preview_events'] and row['unit_type'] > 0
                and row['loaded_event_count'] > 0 and row['registered_event_count'] == row['loaded_event_count'],
                'selected skin config did not reach scene and unit event cache')
        require(not row['prior_unit_active'] or row['pooled_unit_reused'],
                'distinct prior preview unit remains active')
    require(returned.get('original_back') is True and returned.get('loadout_unchanged') is True and
            returned.get('scene_active_after_back') is False and returned.get('unit_active_after_back') is False,
            'original Back did not clear the preview')


def validate_pool_cases(proof, returned, expected, families):
    cases = proof['cases']
    require(proof.get('runtime_observations_complete') is True and proof.get('loadout_unchanged') is True
            and proof.get('visual_review_complete') is False, 'pool observations incomplete')
    require(len(cases) == 4 and [r['index'] for r in cases] == list(range(4))
            and len({families[r['item']] for r in cases[:3]}) == 3
            and cases[-1]['item'] == cases[0]['item'], 'three-family switch and return required')
    for row in cases:
        require(row['expected_event'] == expected[row['item']] and expected[row['item']] in row['preview_events'],
                'pool case selected unexpected skin')
        current = row['current_pool']
        require(current['available_contains_unit'] is False and current['count_all'] > current['count_available'] >= 0,
                'current renderer unit must be borrowed from its pool')
        if current['created_tracker_present']:
            require(current['created_tracker_contains_unit'] is True, 'pool does not track current unit')
        if row['index']:
            require(row['previous_pool']['available_contains_unit'] is True, 'previous unit was not returned')
    require(cases[-1]['first_unit_reused'] is True and cases[-1]['current_pool']['unit_instance'] == cases[0]['current_pool']['unit_instance'],
            'return did not reuse the first available unit')
    require(returned.get('original_back') is True and returned.get('loadout_unchanged') is True
            and returned.get('scene_active_after_back') is False and returned.get('renderer_unit_cleared') is True
            and returned.get('returned_to_available_pool') is True and returned['pool']['available_contains_unit'] is True,
            'Back did not release renderer/pool ownership')


def run(args):
    game, output = args.game.resolve(), args.output.resolve()
    require(game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'), 'owned ignored paths required')
    contract = json.loads(args.contract.read_bytes())
    expected = {r['item']: r['event_key'] for r in contract['cases']}
    families = {r['item']: r['family'] for r in contract['cases']}
    pool_only = getattr(args, 'pool_only', False)
    completed = POOL_COMPLETE if pool_only else COMPLETE
    require(len(contract['cases']) == len(expected) == 13, 'expected static13-skin contract required')
    output.mkdir(parents=True, exist_ok=False)
    profile = 'nativestest_skins_'+secrets.token_hex(6)
    folder = game/'.battleaces-resurrection/profiles'/profile
    require(not folder.exists(), 'fresh profile required')
    original_subprocess = quit_probe.subprocess
    original_spawn = original_subprocess.Popen
    original_job = quit_probe._WindowsJob
    stop = threading.Event()
    process = thread = None
    errors = []
    report = dict(passed=False, scope=__doc__, profile=profile, contract_sha256=sha(args.contract),
                  visual_review_complete=False, physical_input_tested=False, pool_only=pool_only, sources_before=sources())

    class AccountingJob(original_job):
        def close(self):
            if self.handle:
                deadline = time.monotonic()+5
                value = job_accounting(self)
                while value['active_processes'] and process is not None and process.poll() is not None and time.monotonic()<deadline:
                    time.sleep(.05)
                    value = job_accounting(self)
                report['owned_job_before_close'] = value
            super().close()

    def monitor():
        try:
            while not stop.wait(.1) and process.poll() is None:
                text = read_native_log(game, process.pid)
                returned_path = game/'investigation/runtime'/f'skin-preview-return-{process.pid}.json'
                returned = json.loads(returned_path.read_bytes()) if returned_path.exists() else {}
                failed_return = failed_return_can_quit(text, returned)
                if completed not in text and 'SKIN PREVIEW failure returned to menu:' not in text and not failed_return:
                    continue
                temporary = folder/'native-quit.ready.tmp'
                with temporary.open('xb'):
                    pass
                temporary.rename(folder/'native-quit.ready')
                report['quit_gate_released'] = True
                report['failure_cleanup_gate'] = completed not in text
                return
        except Exception as error:
            errors.append(repr(error))

    def spawn(command, *positional, **keywords):
        nonlocal process, thread
        require(Path(command[0]).resolve() == game/'Battle Aces.exe' and process is None, 'one owned game spawn required')
        command = list(command)+['-local-cosmetics-experimental', '-cosmetics-preview-smoke', '-native-quit-gate-smoke']
        if pool_only: command.append('-cosmetics-preview-pool-smoke')
        # The graphic renderer is enabled; the automated window starts hidden.
        info = original_subprocess.STARTUPINFO()
        info.dwFlags |= original_subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0
        keywords['startupinfo'] = info
        process = original_spawn(command, *positional, **keywords)
        report.update(pid=process.pid, actual_arguments=command, automated_window_hidden=True)
        (output/'process.json').write_text(json.dumps(report, indent=2)+'\n')
        thread = threading.Thread(target=monitor, daemon=False)
        thread.start()
        return process

    try:
        control = SimpleNamespace(game=game, output=output/'native-quit', shared_settings=args.shared_settings,
            helper_build_receipt=args.helper_build_receipt, profile=profile, display_name='Skin Preview Probe',
            mode='confirm', visible=True, timeout=240, capture_dialog=False, after_practice=False, default_recipe=True)
        quit_probe.subprocess = scoped_spawn_module(original_subprocess, spawn)
        quit_probe._WindowsJob = AccountingJob
        result = quit_probe.run(control)
        native = json.loads((output/'native-quit/verification.json').read_bytes())
        require(result == 0 and native['passed'] and native['natural_exit'] and not native['forced_cleanup']
                and native['exit_code'] == 0 and not errors, 'original normal Quit incomplete')
        require(report['owned_job_before_close']['active_processes'] == 0 and
                report['owned_job_before_close']['total_terminated_processes'] == 0,
                'owned job did not settle without termination')
        runtime = game/'investigation/runtime'
        text = read_native_log(game, process.pid)
        require(text.count(completed) == 1 and 'SKIN PREVIEW failed:' not in text, 'preview runtime reported failure')
        proof = json.loads((runtime/f'skin-preview-cases-{process.pid}.json').read_bytes())
        returned = json.loads((runtime/f'skin-preview-return-{process.pid}.json').read_bytes())
        if pool_only: validate_pool_cases(proof, returned, expected, families)
        else: validate_cases(proof, returned, expected)
        images = []
        for index in range(0 if pool_only else 14):
            path = runtime/f'skin-preview-{process.pid}-{index}.png'
            raw = path.read_bytes()
            require(raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw) > 1024, 'preview capture missing/invalid')
            images.append(dict(index=index, path=str(path), sha256=sha(path), bytes=len(raw)))
        report.update(passed=True, native_cases=proof, returned=returned, captures=images,
                      natural_exit=True, forced_cleanup=False, native_verification_sha256=sha(output/'native-quit/verification.json'))
    except Exception as error:
        report['error'] = repr(error)
    finally:
        quit_probe.subprocess = original_subprocess
        quit_probe._WindowsJob = original_job
        stop.set()
        if thread is not None:
            thread.join(timeout=5)
        report.update(monitor_stopped=thread is None or not thread.is_alive(), monitor_errors=errors,
                      sources_after=sources())
        report['passed'] &= report['monitor_stopped'] and report['sources_before'] == report['sources_after']
        (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ['passed', 'visual_review_complete', 'error'] if k in report}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['game', 'output', 'shared-settings', 'helper-build-receipt', 'contract']:
        parser.add_argument('--'+key, required=True, type=Path)
    parser.add_argument('--pool-only', action='store_true', help='three-family switch/reuse/Back ownership check; no screenshots')
    raise SystemExit(run(parser.parse_args()))
