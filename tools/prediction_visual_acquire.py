"""One first nonzero original subject click from observed empty selection.

This is an explicit one-episode contract; it never synthesizes a zero click or
substitutes for the legacy two-click/AIM proofs or physical input acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

from tools import prediction_visual_click as click
from tools import prediction_visual_input as queries
from tools import prediction_visual_correction as visual
from tools import prediction_correction_motion as motion

PREFIX='VISUAL ACQUIRE '
MARKER=b'BA_RESURRECTION_VISUAL_ACQUIRE_V1'
PREPOSITION_PREFIX='VISUAL PREPOSITION '
PREPOSITION_MARKER=b'BA_RESURRECTION_VISUAL_PREPOSITION_V1'
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
    if enabled:require(MARKER in data and PREFIX.encode() in data and PREPOSITION_MARKER in data and PREPOSITION_PREFIX.encode() in data and
        '-prediction-visual-click-acquire'.encode('utf-16-le') in data, 'helper lacks first-nonzero acquisition capability')


def rows(log):return click.rows(log,contract='first_nonzero')


def preposition_rows(log):return click.rows(log,contract='first_nonzero_preposition')


def _preposition(prepared,own,zero):
    require(len(prepared)==2 and [r['event']for r in prepared]==['queued','consumed'], 'two actual neutral queue/consumption observations required')
    queued,consumed=prepared;position=own[0]
    stable=('world','match','entity','unit_type','army','incarnation','lease','generation','thread','owner_thread',
            'focus_ordinal','focus_returned_us',*sorted(click.POINTERS))
    require(all(r[k]==queued[k] for r in (consumed,position,zero)for k in stable), 'neutral preparation/zero query/acquisition owner differs')
    require(queued['viewport']==consumed['viewport']==zero['viewport'], 'neutral viewport changed')
    center=click.point2([value*.5 for value in queued['viewport']]);bits=lambda p:struct.pack('<ff',*p)
    require(all(bits(r['queued_point'])==bits(center) for r in prepared) and bits(consumed['pointer'])==bits(center) and
            bits(position['pointer'])==bits(center), 'original neutral center was not consumed before first click position')
    require(queued['frontend_ordinal']==queued['queued_ordinal']==consumed['queued_ordinal'] and
            consumed['frontend_ordinal']>queued['frontend_ordinal'] and position['frontend_ordinal']>consumed['frontend_ordinal'] and
            queued['queued_us']==consumed['queued_us'] and zero['query_end_us']<=queued['queued_us']<=queued['sampled_us']<
            consumed['sampled_us']<position['sampled_us'] and consumed['sampled_us']-queued['queued_us']<=250000,
            'neutral queue/normal consumption/first click chronology differs')
    require(queued['pending_commands']==consumed['pending_commands'], 'neutral preparation changed pending commands')
    require(all(r['mouse'][k]==position['mouse'][k] for r in prepared for k in ('action','control','device')),
            'neutral preparation did not retain the same borrowed Mouse')
    require(all(not r['current_ids'] and not r['casting_ids'] and
                all(r['history'][k] is False for k in ('primary','context','drag')) and
                r['mouse']['primary'] is r['mouse']['context'] is False and r['mouse']['queued_sequence']==1 and
                r['primary_callback_count']==0 and r['roots_retained']==15 for r in prepared),
            'neutral preparation is not naturally empty/released without primary callbacks')
    require(all(r['history'][k]==queued['history'][k] for r in (consumed,position)for k in ('mode','last_up')) and
            queued['history']['now']<=consumed['history']['now']<=position['history']['now'],
            'neutral preparation changed original release history')
    require(all(v==0 for v in queued['pose']['offset']), 'neutral queue was not acquired at the original zero-before control')
    return dict(passed=True,point=center,queue_sequence=1,consumed_us=consumed['sampled_us'],
                delivery_us=consumed['sampled_us']-queued['queued_us'],primary_callback_count=0,roots_retained=15,records=prepared)


def evaluate(records,visual_records,bindings,*,focus_records,preposition_records,query_records):
    require(type(bindings) is list and len(bindings)==2 and len({b['world']for b in bindings})==2 and
            len({b['match']for b in bindings})==2, 'two bound worlds required')
    require(type(focus_records) is list and len(focus_records)==2 and
            [(f['world'],f['match'])for f in focus_records]==[(b['world'],b['match'])for b in bindings], 'original focus owners missing')
    require(all((r['world'],r['match']) in {(b['world'],b['match'])for b in bindings}for r in records+preposition_records), 'unbound acquisition world')
    worlds=[];joined={}
    for binding,focus in zip(bindings,focus_records):
        own=[r for r in records if r['world']==binding['world']]
        prepared=[r for r in preposition_records if r['world']==binding['world']]
        zeros=[r for r in query_records if r['world']==binding['world'] and r['control']=='zero_before']
        require(len(zeros)==1, 'actual Stage1 zero-before preparation source missing')
        for row in prepared+own:
            pose=click._join(row,visual_records,binding,focus);joined[(pose['world'],pose['sampled_us'])]=pose
        require(all(b['frame']>=a['frame'] and b['pose']['revision']>=a['pose']['revision'] for a,b in zip(prepared+own,(prepared+own)[1:])),
                'acquisition physical frame/revision regressed')
        if len(own)!=10:
            worlds.append(dict(binding=binding,component_observation_passed=False,missing_gates=['incomplete first nonzero callback/close'],records=own))
            continue
        preparation=_preposition(prepared,own,zeros[0])
        episode=click._episode(own,queue_contract='neutral_prefix_four_events')
        require(all(not r['current_ids'] and not r['casting_ids']for r in own[:8]),
                'first nonzero click did not stay committed-empty through original Up entry')
        require(all(math.hypot(*r['pose']['offset'])>=.5 for r in own), 'acquisition sample lacks0.5unit correction')
        episode.update(initial_current_ids=own[0]['current_ids'],before_up_current_ids=own[7]['current_ids'],
                       after_up_current_ids=own[8]['current_ids'],minimum_offset=min(math.hypot(*r['pose']['offset'])for r in own))
        worlds.append(dict(binding=binding,component_observation_passed=episode['passed'],missing_gates=episode['missing_gates'],
                           episode=episode,preposition=preparation,records=own))
    valid=all(w['component_observation_passed']for w in worlds)
    return dict(schema=1,passed=valid,component_observation_passed=valid,status='observed'if valid else'incomplete',
        scope='first_nonzero_original_primary_acquisition',worlds=worlds,joined_visual_poses=list(joined.values()),
        focus_records=focus_records,preposition_records=preposition_records,query_records=query_records,
        physical_input_accepted=False,commands_accepted=False,full_feature_accepted=False,
        actual_zero_click_claimed=False,legacy_two_click_proof_claimed=False,
        limitations=['One first diagnostic nonzero original subject click per world; Stage1 zero queries remain separate controls.',
            'One neutral released position is consumed in the same Mouse session before actual position/Down/Up queues2/3/4; no zero click.',
            'Preview may already contain subject; committed current remains empty through original Up entry.',
            'No direct selection clearing,history-sentinel reset,physical gesture,unit-target command or Internet acceptance.'])


def analyze(plan,report,run):
    validate_plan(plan);require(plan.get('visual_click_acquire') is True, 'explicit acquisition option missing')
    run=Path(run);inputs={}
    def read(path):
        require(path.stat().st_size<=64*1024*1024, 'closed input exceeds bound')
        raw=path.read_bytes();inputs[str(path)]=hashlib.sha256(raw).hexdigest();return raw
    log_path=run/'native-0.log';log=read(log_path).decode('utf-8');peer=read(run/'native-1.log').decode('utf-8')
    require(PREFIX not in peer and PREPOSITION_PREFIX not in peer and click.FAILURE not in peer, 'unrequested peer acquisition/failure')
    require(all(prefix not in log and prefix not in peer for prefix in (click.PREFIX,'VISUAL AIM ','VISUAL EMPTY ')),
            'mixed legacy/retired callback fixture')
    observed=rows(log);prepared=preposition_rows(log);query_records=queries.rows(log);poses=visual.rows(log);focus=queries.focus_rows(log)
    bindings=[w['binding'] for w in report['native_position_trace']['worlds']]
    result=evaluate(observed,poses,bindings,focus_records=focus,preposition_records=prepared,query_records=query_records)
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
                focus==[w['focus'] for w in report['visual_input']['worlds']] and
                query_records==[r for w in report['visual_input']['worlds']for r in w['records']], 'acquisition/query source/focus binding differs')
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
        require(proof['query_records']==[r for w in report['visual_input']['worlds']for r in w['records']], 'saved original zero query source differs')
        bindings=[w['binding'] for w in report['visual_correction']['worlds']]
        observed=rows('\n'.join(PREFIX+json.dumps(r) for w in proof['worlds'] for r in w['records']))
        poses=visual.rows('\n'.join(visual.PREFIX+json.dumps(r) for r in proof['joined_visual_poses']))
        focus=queries.focus_rows('\n'.join(queries.FOCUS_PREFIX+json.dumps(r) for r in proof['focus_records']))
        prepared=preposition_rows('\n'.join(PREPOSITION_PREFIX+json.dumps(r)for r in proof['preposition_records']))
        query_records=queries.rows('\n'.join(queries.PREFIX+json.dumps(r)for r in proof['query_records']))
        rebuilt=evaluate(observed,poses,bindings,focus_records=focus,preposition_records=prepared,query_records=query_records)
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
