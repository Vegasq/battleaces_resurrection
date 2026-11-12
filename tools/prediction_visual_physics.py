"""Closed, file-only evidence for production visual write/physics join batches."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools import prediction_visual_correction as visual
from tools import prediction_visual_input as queries
from tools import prediction_visual_acquire as acquire
from tools import prediction_visual_sync as intervention
from tools import prediction_correction_motion as motion

PREFIX='VISUAL PHYSICS SYNC '
FIELDS={'schema','event','world','match','frame','revision','policy_us','prepare_started_us','prepared_us',
        'entered_us','returned_us','thread','owner_thread','writes','restorations'}
PRODUCERS=('client_patch/src/prediction_visual_physics.hpp','client_patch/src/prediction_visual_batch.hpp',
    'client_patch/src/prediction_visual_correction.cpp','client_patch/src/prediction_visual_correction.hpp')


def require(value,why):
    if not value:raise AssertionError('prediction visual physics: '+why)


def rows(log):
    require(type(log) is str and len(log.encode())<=64*1024*1024,'bounded closed log required')
    require(intervention.PREFIX not in log,'diagnostic Sync intervention cannot qualify production join')
    def unique(pairs):
        result={}
        for k,v in pairs:require(k not in result,'duplicate JSON field');result[k]=v
        return result
    result=[];seen=set();worlds=[];last=0
    for line in log.splitlines():
        if PREFIX not in line:continue
        raw=line.split(PREFIX,1)[1];require(len(raw.encode())<=2048,'batch row exceeds bound')
        r=json.loads(raw,object_pairs_hook=unique)
        require(type(r) is dict and set(r)==FIELDS and type(r['schema']) is int and r['schema']==1 and r['event']=='batch',
            'batch schema differs')
        require(all(queries.integer(r[k],1)for k in ('world','policy_us','prepare_started_us','prepared_us','entered_us','returned_us','thread','owner_thread')) and
            queries.integer(r['frame'],400,650) and queries.integer(r['revision']) and queries.integer(r['writes'],1,2048) and
            queries.integer(r['restorations'],0,r['writes']) and r['thread']==r['owner_thread'] and
            r['policy_us']<=r['prepare_started_us']<=r['prepared_us']<=r['entered_us']<=r['returned_us'] and
            r['policy_us']>=last,'batch owner/count/clock differs')
        key=(r['world'],r['match']);require(type(r['match']) is str and len(r['match'])==32 and all(c in '0123456789abcdef'for c in r['match']),
            'batch match identity differs')
        if not worlds or worlds[-1]!=key:
            require(key not in worlds and len(worlds)<2,'batch world interleaved');worlds.append(key)
        require((r['world'],r['policy_us'])not in seen,'duplicate actual Sync for one observed policy batch')
        seen.add((r['world'],r['policy_us']));last=r['policy_us'];result.append(r)
        require(len(result)<=20000,'batch observation budget exceeded')
    return result


def evaluate(records,poses,bindings,*,completed_joins=()):
    require(len(bindings)==2 and len({b['world']for b in bindings})==len({b['match']for b in bindings})==2,'two original worlds required')
    by_key={(r['world'],r['policy_us']):r for r in records}
    require(len(by_key)==len(records),'duplicate batch')
    require(all((r['world'],r['match'])in{(b['world'],b['match'])for b in bindings}for r in records),'unbound batch')
    worlds=[]
    for b in bindings:
        own=[r for r in records if r['world']==b['world']];traced=[p for p in poses if p['event']=='visual_pose'and all(p[k]==b[k]for k in b)]
        changed=[p for p in traced if p['wrote']]
        require(own and changed,'actual observed changed-write batches missing')
        require(all(any(p['sampled_us']==r['policy_us']for p in traced)for r in own),'Sync batch lacks its actual observed visual pose')
        restorations=0
        for p in changed:
            require((b['world'],p['sampled_us'])in by_key,'observed changed visual write lacks actual completed Sync')
            r=by_key[(b['world'],p['sampled_us'])]
            require(r['match']==p['match'] and r['frame']==p['frame'],'changed write and Sync physical frame differ')
            if p['displayed']==p['raw'] and p['pulses']==0:
                require(r['restorations']>=1,'zero-offset restoration did not synchronize');restorations+=1
        require(restorations>=1,'zero-offset restoration control missing')
        for join in completed_joins:
            if join['world']!=b['world']:continue
            r=by_key.get((b['world'],join['policy_us']))
            if r:
                require(join['joined_us']>=r['returned_us'],'frontend completed before actual Sync return')
                require(all(join[k]==r[k]for k in ('revision','frame','thread','owner_thread')if k in join),
                    'frontend and physics batch owner/frame/revision differ')
        worlds.append(dict(binding=b,calls=len(own),observed_changed_writes=len(changed),observed_restorations=restorations,
            maximum_prepare_us=max(r['prepared_us']-r['prepare_started_us']for r in own),
            maximum_setter_window_us=max(r['entered_us']-r['prepared_us']for r in own),
            maximum_sync_us=max(r['returned_us']-r['entered_us']for r in own),
            maximum_prepare_through_sync_us=max(r['returned_us']-r['prepare_started_us']for r in own),records=own))
    return dict(schema=1,passed=True,scope='observed_production_visual_physics_batches',worlds=worlds,
        diagnostic_intervention=False,physical_input_accepted=False,full_feature_accepted=False,
        limitations=['Counts cover the explicitly observed subject/window; untraced entities may contribute to batch writes.',
            'Costs are actual measured intervals, not an invented global performance budget.',
            'This proof supplements the unchanged full native/wire/movement/visual/query/callback/lifetime parent gates.'])


def analyze(plan,report,run):
    require(plan.get('visual_correction') is True and plan.get('visual_input') is True and plan.get('visual_click_acquire') is True and
            not plan.get('visual_sync_probe'),'normal visual/query/acquisition candidate required; diagnostic flag must be off')
    visual.parent_gate(plan,report)
    require(report['visual_input_witness_passed'] is True and queries.gate(plan,report) and acquire.gate(plan,report),
        'unchanged original query/acquisition parents did not pass')
    module=plan['files']['unityplayer'];require(module['sha256']==intervention.UNITYPLAYER_SHA256 and
        motion.sha(module['path'])==module['sha256'],'consumed original UnityPlayer differs')
    run=Path(run);inputs={};texts=[]
    for name in ('native-0.log','native-1.log'):
        path=run/name;require(path.stat().st_size<=64*1024*1024,'closed log exceeds bound')
        raw=path.read_bytes();inputs[str(path)]=hashlib.sha256(raw).hexdigest();texts.append(raw.decode('utf-8'))
    require(inputs==report['visual_input']['input_sha256'],'original query/log source differs')
    log,peer=texts;require(PREFIX not in peer and intervention.PREFIX not in peer,'unexpected peer diagnostic')
    records=rows(log);poses=visual.rows(log);original=queries.rows(log);callbacks=acquire.rows(log)
    require(original==[r for w in report['visual_input']['worlds']for r in w['records']],'original frontend records differ from parent')
    if plan.get('visual_click_acquire'):
        require(callbacks==[r for w in report['visual_click_acquire']['worlds']for r in w['records']],'original acquisition records differ from parent')
    joins=[{k:r[k]for k in ('world','policy_us','joined_us','revision','frame','thread','owner_thread')}for r in original]
    joins.extend(dict(world=r['world'],policy_us=r['pose']['policy_us'],joined_us=r['pose']['joined_us'],revision=r['pose']['revision'],
        frame=r['frame'],thread=r['thread'],owner_thread=r['owner_thread'])for r in callbacks)
    result=evaluate(records,poses,[w['binding']for w in report['visual_correction']['worlds']],completed_joins=joins)
    batch_lines={};pose_lines=[]
    for number,line in enumerate(log.splitlines()):
        if PREFIX in line:
            r=json.loads(line.split(PREFIX,1)[1]);batch_lines[(r['world'],r['policy_us'])]=number
        if visual.PREFIX in line:
            for p in visual.rows(line):
                if p['event']=='visual_pose':pose_lines.append((number,p))
    for number,p in pose_lines:
        key=(p['world'],p['sampled_us'])
        if key in batch_lines:require(batch_lines[key]<number,'visual receipt published before actual Sync receipt')
    producers={}
    for name in PRODUCERS:
        path=run.parent/'source-at-prepare'/name;require(path.stat().st_size<=256*1024,'source snapshot exceeds bound')
        require(motion.sha(path)==plan['source_sha256'][name],'consumed production join source differs');producers[name]=motion.sha(path)
    for m in (visual,queries,acquire,intervention,motion):
        require(motion.sha(m.__file__)==plan['source_sha256']['tools/'+Path(m.__file__).name],'consumed checker differs')
    require(motion.sha(__file__)==plan['source_sha256']['tools/prediction_visual_physics.py'],'consumed batch checker differs')
    require(all(motion.sha(r['path'])==r['sha256']for r in plan['files'].values()),'consumed prepared file changed')
    require(all(motion.sha(path)==digest for path,digest in inputs.items()),'closed captures changed')
    result.update(file_only=True,input_sha256=inputs,producer_sha256=producers,original_report_passed=True,
        original_report_sha256=motion.sha(run/'verification.json'),runtime_module=module)
    return result
