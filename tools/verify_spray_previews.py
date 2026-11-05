"""Owned six-spray menu bindings and original Back lifecycle.

Native selected resources and graphic material bindings are runtime observations, not physical input,
rendered image or audible sound acceptance. Ordinary launchers never opt in.
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
COMPLETE = 'SPRAY MENU completed: items=6 selections=7 bindings=1 originalBack=1 inactive=1 loadoutUnchanged=1'

def require(value, message):
    if not value: raise AssertionError(message)

def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

def sources():
    return quit_probe.sources() | {Path(__file__).relative_to(ROOT).as_posix(): sha(__file__)}

def validate_cases(proof, returned, contract):
    require(contract.get('passed') is True and contract.get('runtime_executed') is False, 'reviewed static contract required')
    cases={c['item']:c for c in contract['cases']}
    sequence=[54,10,71,151,152,203,54]
    require(len(contract['cases'])==len(cases)==6 and set(cases)==set(sequence), 'complete six-spray contract required')
    require(contract['slot']['id']==8 and contract['slot']['default_item']==54, 'spray slot/default differs')
    require(proof.get('schema')==1 and proof.get('visual_audio_verified') is False and proof.get('physical_input_tested') is False
            and proof.get('loadout_unchanged') is True, 'scope or loadout evidence incomplete')
    rows=proof['observations']
    require(len(rows)==15 and [r['tick'] for r in rows]==sorted(r['tick'] for r in rows), 'ordered complete samples required')
    require([r['index'] for r in rows]==[i for i in range(7) for _ in range(2)]+[6], 'all six and ordered return required')
    owners=[];materials={};sprites={}
    for index,item in enumerate(sequence):
        group=rows[index*2:index*2+2];case=cases[item]
        require([r['phase'] for r in group]==['loaded','settled'] and group[1]['tick']>group[0]['tick'], 'load/settled sequence incomplete')
        for r in group:
            require(r['item']==r['model_item']==item and r['cosmetic_type']==4, 'selected spray identity differs')
            require(r['sprite']==case['assets']['AssetReferenceSprite']['name'] and r['sprite_id']!=0, 'wrong sprite subobject')
            require(r['material']==r['actual_material']==case['assets']['AssetReferenceMaterial']['name']
                    and r['material_id']==r['actual_material_id']!=0 and r['material_binding_matches'] is True, 'wrong graphic material binding')
            require(all(r[k] is True for k in ['vm_active','vm_initialized','graphic_active']), 'preview not active/initialized')
            require(r['image_present'] is True and r['image_enabled'] is True and r['override_present'] is False,
                    'original direct Image binding unavailable')
            require(r['vm_id']!=0 and r['graphic_id']!=0, 'preview owner missing')
            owners.append((r['vm_id'],r['graphic_id']))
            materials.setdefault(item,set()).add(r['material_id']);sprites.setdefault(item,set()).add(r['sprite_id'])
    require(len(set(owners))==1, 'preview ownership changed')
    require(all(len(v)==1 for v in materials.values()) and len(set.union(*materials.values()))==6, 'material switch/return identity differs')
    require(all(len(v)==1 for v in sprites.values()) and len(set.union(*sprites.values()))==6, 'sprite switch/return identity differs')
    require(rows[-1]==returned and returned['phase']=='back' and returned['item']==54
            and (returned['vm_id'],returned['graphic_id'])==owners[0], 'original Back ownership evidence missing')
    require(all(returned[k] is False for k in ['vm_active','vm_initialized','graphic_active']), 'Back retained active preview')


def run(args):
    game, output = args.game.resolve(), args.output.resolve()
    require(game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'), 'owned ignored paths required')
    contract=json.loads(args.contract.read_bytes())
    completed = COMPLETE
    output.mkdir(parents=True, exist_ok=False)
    profile = 'nativestest_spray_'+secrets.token_hex(6)
    folder = game/'.battleaces-resurrection/profiles'/profile
    require(not folder.exists(), 'fresh profile required')
    original_subprocess = quit_probe.subprocess
    original_spawn = original_subprocess.Popen
    original_job = quit_probe._WindowsJob
    stop = threading.Event()
    process = thread = None
    errors = []
    report = dict(passed=False, scope=__doc__, profile=profile, contract_sha256=sha(args.contract),
                  visual_review_complete=False, physical_input_tested=False, sources_before=sources())

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
                returned_path = game/'investigation/runtime'/f'spray-menu-return-{process.pid}.json'
                returned = json.loads(returned_path.read_bytes()) if returned_path.exists() else {}
                if completed not in text and 'SPRAY MENU failure returned to menu:' not in text:
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
        command = list(command)+['-local-cosmetics-experimental', '-cosmetics-spray-menu-smoke', '-native-quit-gate-smoke']
        # The graphic renderer is enabled; the automated window starts hidden.
        info = original_subprocess.STARTUPINFO()
        info.dwFlags |= original_subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0
        keywords['startupinfo'] = info
        keywords['creationflags'] = keywords.get('creationflags', 0) | original_subprocess.CREATE_NO_WINDOW
        process = original_spawn(command, *positional, **keywords)
        report.update(pid=process.pid, actual_arguments=command, automated_window_hidden=True)
        (output/'process.json').write_text(json.dumps(report, indent=2)+'\n')
        thread = threading.Thread(target=monitor, daemon=False)
        thread.start()
        return process

    try:
        control = SimpleNamespace(game=game, output=output/'native-quit', shared_settings=args.shared_settings,
            helper_build_receipt=args.helper_build_receipt, profile=profile, display_name='Spray Menu Probe',
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
        require(text.count(completed) == 1 and 'SPRAY MENU failed:' not in text, 'preview runtime reported failure')
        proof = json.loads((runtime/f'spray-menu-cases-{process.pid}.json').read_bytes())
        returned = json.loads((runtime/f'spray-menu-return-{process.pid}.json').read_bytes())
        validate_cases(proof, returned, contract)
        report.update(passed=True, native_cases=proof, returned=returned,
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
    raise SystemExit(run(parser.parse_args()))
