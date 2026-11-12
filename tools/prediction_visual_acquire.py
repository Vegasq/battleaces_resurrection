"""One first nonzero original subject click from observed empty selection.

This is an explicit one-episode contract; it never synthesizes a zero click or
substitutes for the legacy two-click/AIM proofs or physical input acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from tools import prediction_visual_click as click
from tools import prediction_visual_input as queries
from tools import prediction_visual_correction as visual
from tools import prediction_correction_motion as motion

PREFIX='VISUAL ACQUIRE '
MARKER=b'BA_RESURRECTION_VISUAL_ACQUIRE_V1'
PRODUCERS=(*click.PRODUCERS,'client_patch/src/prediction_visual_click_protocol.hpp')


def require(value,why):
    if not value:raise AssertionError('prediction visual acquire: '+why)


def validate_plan(plan):
    require(not plan.get('visual_click_empty'), 'retired empty-ground setup is not supported')
    require('visual_click_acquire' not in plan or type(plan['visual_click_acquire']) is bool, 'option must be Boolean')
    if not plan.get('visual_click_acquire'):return
    require(plan.get('visual_input') is True and plan.get('visual_correction') is True and
            all(type(plan.get(k,False)) is bool and not plan.get(k,False) for k in ('visual_click','visual_click_spatial')),
            'requires visual input/correction and excludes legacy two-click/spatial modes')
    queries.validate_plan(plan)


def option(args,frames,trace,delay):
    enabled=getattr(args,'visual_click_acquire',False)
    require(type(enabled) is bool, 'option must be Boolean')
    require(not getattr(args,'visual_click_empty',False), 'retired empty-ground setup is not supported')
    if enabled:
        require(getattr(args,'visual_input',False) is True and queries.option(args,frames,trace,delay) is True and
                all(getattr(args,k,False) is False for k in ('visual_click','visual_click_spatial')),
                'requires input/correction, excludes --visual-click/--visual-click-spatial')
    return enabled


def helper(enabled,data):
    if enabled:require(MARKER in data and PREFIX.encode() in data and
        '-prediction-visual-click-acquire'.encode('utf-16-le') in data, 'helper lacks first-nonzero acquisition capability')


def rows(log):return click.rows(log,contract='first_nonzero')


def evaluate(records,visual_records,bindings,*,focus_records):
    require(type(bindings) is list and len(bindings)==2 and len({b['world']for b in bindings})==2 and
            len({b['match']for b in bindings})==2, 'two bound worlds required')
    require(type(focus_records) is list and len(focus_records)==2 and
            [(f['world'],f['match'])for f in focus_records]==[(b['world'],b['match'])for b in bindings], 'original focus owners missing')
    require(all((r['world'],r['match']) in {(b['world'],b['match'])for b in bindings}for r in records), 'unbound acquisition world')
    worlds=[];joined={}
    for binding,focus in zip(bindings,focus_records):
        own=[r for r in records if r['world']==binding['world']]
        for row in own:
            pose=click._join(row,visual_records,binding,focus);joined[(pose['world'],pose['sampled_us'])]=pose
        require(all(b['frame']>=a['frame'] and b['pose']['revision']>=a['pose']['revision'] for a,b in zip(own,own[1:])),
                'acquisition physical frame/revision regressed')
        if len(own)!=10:
            worlds.append(dict(binding=binding,component_observation_passed=False,missing_gates=['incomplete first nonzero callback/close'],records=own))
            continue
        episode=click._episode(own)
        require(all(not r['current_ids'] and not r['casting_ids']for r in own[:8]),
                'first nonzero click did not stay committed-empty through original Up entry')
        require(all(math.hypot(*r['pose']['offset'])>=.5 for r in own), 'acquisition sample lacks0.5unit correction')
        episode.update(initial_current_ids=own[0]['current_ids'],before_up_current_ids=own[7]['current_ids'],
                       after_up_current_ids=own[8]['current_ids'],minimum_offset=min(math.hypot(*r['pose']['offset'])for r in own))
        worlds.append(dict(binding=binding,component_observation_passed=episode['passed'],missing_gates=episode['missing_gates'],
                           episode=episode,records=own))
    valid=all(w['component_observation_passed']for w in worlds)
    return dict(schema=1,passed=valid,component_observation_passed=valid,status='observed'if valid else'incomplete',
        scope='first_nonzero_original_primary_acquisition',worlds=worlds,joined_visual_poses=list(joined.values()),
        focus_records=focus_records,physical_input_accepted=False,commands_accepted=False,full_feature_accepted=False,
        actual_zero_click_claimed=False,legacy_two_click_proof_claimed=False,
        limitations=['One first diagnostic nonzero original subject click per world; Stage1 zero queries remain separate controls.',
            'Preview may already contain subject; committed current remains empty through original Up entry.',
            'No direct selection clearing,history-sentinel reset,physical gesture,unit-target command or Internet acceptance.'])


def analyze(plan,report,run):
    validate_plan(plan);require(plan.get('visual_click_acquire') is True, 'explicit acquisition option missing')
    run=Path(run);inputs={}
    def read(path):
        require(path.stat().st_size<=64*1024*1024, 'closed input exceeds bound')
        raw=path.read_bytes();inputs[str(path)]=hashlib.sha256(raw).hexdigest();return raw
    log_path=run/'native-0.log';log=read(log_path).decode('utf-8');peer=read(run/'native-1.log').decode('utf-8')
    require(PREFIX not in peer and click.FAILURE not in peer, 'unrequested peer acquisition/failure')
    require(all(prefix not in log and prefix not in peer for prefix in (click.PREFIX,'VISUAL AIM ','VISUAL EMPTY ')),
            'mixed legacy/retired callback fixture')
    observed=rows(log);poses=visual.rows(log);focus=queries.focus_rows(log)
    bindings=[w['binding'] for w in report['native_position_trace']['worlds']]
    result=evaluate(observed,poses,bindings,focus_records=focus)
    producers={}
    for name in PRODUCERS:
        path=run.parent/'source-at-prepare'/name
        require(path.stat().st_size<=256*1024, 'producer snapshot exceeds bound')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        require(digest==plan['source_sha256'][name], 'consumed original acquisition producer differs')
        producers[name]=digest
    parent_error=None
    try:
        visual.parent_gate(plan,report)
        require(queries.gate(plan,report) and report['visual_input_witness_passed'] is True,
                'unchanged Stage1/visual/native/wire/lifetime parents missing')
        require(inputs==report['visual_input']['input_sha256'] and
                focus==[w['focus'] for w in report['visual_input']['worlds']], 'acquisition/query source/focus binding differs')
        for module in (click,queries,visual,motion):
            require(motion.sha(module.__file__)==plan['source_sha256']['tools/'+Path(module.__file__).name], 'consumed callback/join source differs')
        require(motion.sha(__file__)==plan['source_sha256']['tools/prediction_visual_acquire.py'], 'consumed acquisition checker differs')
    except (AssertionError,KeyError,TypeError,ValueError) as error:parent_error=repr(error)
    require(all(motion.sha(path)==digest for path,digest in inputs.items()), 'closed acquisition captures changed')
    result.update(file_only=True,input_sha256=inputs,producer_sha256=producers,parent_gates_passed=parent_error is None,
                  parent_error=parent_error)
    result['passed']=result['component_observation_passed'] and parent_error is None
    if parent_error is not None:result['status']='parent_unqualified'
    return result


def gate(plan,report):
    if not plan.get('visual_click_acquire'):return True
    try:
        validate_plan(plan);visual.parent_gate(plan,report);require(queries.gate(plan,report), 'query parent missing')
        proof=report['visual_click_acquire']
        require(proof['passed'] is proof['component_observation_passed'] is proof['parent_gates_passed'] is True and
                proof['status']=='observed' and proof['scope']=='first_nonzero_original_primary_acquisition' and
                proof['actual_zero_click_claimed'] is proof['legacy_two_click_proof_claimed'] is
                proof['physical_input_accepted'] is proof['commands_accepted'] is proof['full_feature_accepted'] is False and
                proof['input_sha256']==report['visual_input']['input_sha256'] and
                proof['producer_sha256']=={name:plan['source_sha256'][name] for name in PRODUCERS} and
                proof['focus_records']==[w['focus'] for w in report['visual_input']['worlds']],
                'saved acquisition scope/parent/source proof differs')
        bindings=[w['binding'] for w in report['visual_correction']['worlds']]
        observed=rows('\n'.join(PREFIX+json.dumps(r) for w in proof['worlds'] for r in w['records']))
        poses=visual.rows('\n'.join(visual.PREFIX+json.dumps(r) for r in proof['joined_visual_poses']))
        focus=queries.focus_rows('\n'.join(queries.FOCUS_PREFIX+json.dumps(r) for r in proof['focus_records']))
        rebuilt=evaluate(observed,poses,bindings,focus_records=focus)
        require(rebuilt['component_observation_passed'] and rebuilt['worlds']==proof['worlds'], 'saved first acquisition callback/empty/Up proof differs')
        return True
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError):return False


def finalize(plan,report,run):
    if not plan.get('visual_click_acquire'):return
    parent=report.get('passed') is True
    try:report['visual_click_acquire']=analyze(plan,report,run)
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OSError,OverflowError) as error:
        proof=dict(passed=False,component_observation_passed=False,parent_gates_passed=False,status='unqualified',error=repr(error),
            scope='first_nonzero_original_primary_acquisition',physical_input_accepted=False,commands_accepted=False,
            full_feature_accepted=False,actual_zero_click_claimed=False,legacy_two_click_proof_claimed=False)
        try:proof['preserved_observations']=rows((Path(run)/'native-0.log').read_text(encoding='utf-8'))
        except (AssertionError,KeyError,TypeError,ValueError,OSError) as parse_error:proof['observation_error']=repr(parse_error)
        report['visual_click_acquire']=proof
    report['visual_click_acquire_witness_passed']=report['visual_click_acquire'].get('passed') is True
    report['passed']=parent and report['visual_click_acquire_witness_passed'] and gate(plan,report)
