"""Owned all46 emote previews, original Play progression and Back lifecycle.

Native animation time and component bindings are runtime observations, not physical input,
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
COMPLETE = 'EMOTE PREVIEW completed: items=46 selections=47 playableTime=1 originalBack=1 stopped=1 loadoutUnchanged=1'

def require(value, message):
    if not value: raise AssertionError(message)

def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

def sources():
    return quit_probe.sources() | {Path(__file__).relative_to(ROOT).as_posix(): sha(__file__)}

def validate_cases(proof, returned, contract, clip_curve=None):
    require(contract.get('passed') is True and contract.get('runtime_executed') is False, 'reviewed static contract required')
    cases=contract['cases'];require(len(cases)==46 and len({c['item'] for c in cases})==46, 'complete expected emote set required')
    expected=cases+[cases[0]]
    remap={}
    if clip_curve is not None:
        binding=clip_curve['binding'];script=clip_curve['script']
        require(clip_curve['source_clip']=='Emote_Special' and clip_curve['target_clip']['m_Name']=='Emote_Mad_Rare'
                and clip_curve['field']=='_Clip' and binding['attribute']==clip_curve['field_crc32']==1345833794
                and binding['path']==0 and binding['isPPtrCurve']==1 and binding['typeID']==114
                and script['m_ClassName']=='SoloAnimation' and script['m_Namespace']=='Animancer'
                and clip_curve['all_clip_pptr_counts'].get('Emote_Special')==1
                and sum(clip_curve['all_clip_pptr_counts'].values())==1, 'original clip curve contract differs')
        remap[clip_curve['source_clip']]=clip_curve['target_clip']['m_Name']
    materials={p['item']:{m['emotion']:Path(m['path']).stem for m in p['materials']} for p in contract['portrait_cases']}
    require(proof.get('schema')==1 and proof.get('visual_audio_verified') is False and proof.get('physical_input_tested') is False
            and proof.get('loadout_unchanged') is True, 'scope or loadout evidence incomplete')
    rows=proof['observations']
    require(rows and [r['tick'] for r in rows]==sorted(r['tick'] for r in rows), 'sample order differs')
    require([r['index'] for r in rows]==sorted(r['index'] for r in rows) and set(r['index'] for r in rows)==set(range(47)),
            'all46 plus ordered return required')
    players=[];remapped_ids=[]
    for index,case in enumerate(expected):
        group=[r for r in rows if r['index']==index and r['phase']!='back']
        require(len(group)>=4 and [r['phase'] for r in group[:2]]==['loaded','play-return']
                and all(r['phase']=='progress' for r in group[2:]), 'load/Play/progress sequence incomplete')
        for r in group:
            require(r['item']==r['model_item']==case['item'] and r['portrait']==contract['default_portrait']
                    and r['animation']==case['animation_name'] and r['material']==materials[r['portrait']][case['emotion']]
                    and all(r[k] is True for k in ['material_binding_matches','dialog_matches_definition',
                                                  'vm_initialized','vm_active','solo_active']), 'selected component binding differs')
            require(r['text_key']==case['text']['m_TableEntryReference']['m_KeyId'] and r['effects']==case['text_effects']
                    and r['typewriter']==case['typewriter'], 'selected text/effect metadata differs')
            # Original TAnimCore.SetTypewriterText (0xae7a10) prepends this
            # exact empty tag pair to nonempty text; preserve all authored tags.
            expected_text=('<noparse></noparse>' if r['typewriter'] else '')+r['localized_text']
            require(bool(r['localized_text'].strip()) and expected_text==r['animator_text'], 'localized text did not reach animator')
            if r['animation'] in remap:
                require(r['actual_animation']==remap[r['animation']] and r['clip_binding_matches'] is False
                        and r['actual_animation_id']!=r['animation_id'] and r['actual_animation_id']!=0
                        and r['animation_id']!=0, 'authored clip curve target differs')
                remapped_ids.append((r['animation_id'],r['actual_animation_id']))
            else:
                require(r['actual_animation']==r['animation'] and r['actual_animation_id']==r['animation_id']
                        and r['animation_id']!=0 and r['clip_binding_matches'] is True, 'actual animation identity differs')
        require(len({r['solo_id'] for r in group})==1, 'animation owner changed during playback')
        progress=[r for r in group[2:] if r['playing'] is True and r['graph_ready'] is True and r['pending_show'] is False]
        require(any(b['tick']>a['tick'] and b['seconds']>a['seconds']>=0
                    for i,a in enumerate(progress) for b in progress[i+1:]), 'animation time did not advance')
        players.append(group[0]['solo_id'])
    require(len(set(players))==1, 'unexpected preview animation owner switch')
    require(not remapped_ids or len(set(remapped_ids))==1, 'authored curve target identity changed')
    require(rows[-1]==returned and returned['phase']=='back' and returned['solo_id']==players[-1]
            and sum(r['phase']=='back' for r in rows)==1, 'Back ownership evidence missing')
    require(all(returned[k] is False for k in ['playing','vm_active','vm_initialized','solo_active']), 'Back retained active playback')


def run(args):
    game, output = args.game.resolve(), args.output.resolve()
    require(game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'), 'owned ignored paths required')
    contract=json.loads(args.contract.read_bytes())
    clip_curve=json.loads(args.clip_curve.read_bytes()) if args.clip_curve else None
    completed = COMPLETE
    output.mkdir(parents=True, exist_ok=False)
    profile = 'nativestest_emote_'+secrets.token_hex(6)
    folder = game/'.battleaces-resurrection/profiles'/profile
    require(not folder.exists(), 'fresh profile required')
    original_subprocess = quit_probe.subprocess
    original_spawn = original_subprocess.Popen
    original_job = quit_probe._WindowsJob
    stop = threading.Event()
    process = thread = None
    errors = []
    report = dict(passed=False, scope=__doc__, profile=profile, contract_sha256=sha(args.contract),
                  clip_curve_sha256=sha(args.clip_curve) if args.clip_curve else None,
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
                returned_path = game/'investigation/runtime'/f'emote-preview-return-{process.pid}.json'
                returned = json.loads(returned_path.read_bytes()) if returned_path.exists() else {}
                if completed not in text and 'EMOTE PREVIEW failure returned to menu:' not in text:
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
        command = list(command)+['-local-cosmetics-experimental', '-cosmetics-emote-smoke', '-native-quit-gate-smoke']
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
            helper_build_receipt=args.helper_build_receipt, profile=profile, display_name='Emote Preview Probe',
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
        require(text.count(completed) == 1 and 'EMOTE PREVIEW failed:' not in text, 'preview runtime reported failure')
        proof = json.loads((runtime/f'emote-preview-cases-{process.pid}.json').read_bytes())
        returned = json.loads((runtime/f'emote-preview-return-{process.pid}.json').read_bytes())
        validate_cases(proof, returned, contract, clip_curve)
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
    parser.add_argument('--clip-curve', type=Path, help='original serialized clip-field curve evidence')
    raise SystemExit(run(parser.parse_args()))
