"""Optional same-point original Physics.SyncTransforms attribution.

An intervention observation never replaces an original Stage1 ray result and
does not identify a collider cause or qualify physical input.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct

from tools import prediction_visual_input as queries
from tools import prediction_visual_correction as visual
from tools import prediction_correction_motion as motion
from tools import prediction_visual_acquire as acquire

PREFIX='VISUAL SYNC '
MARKER=b'BA_RESURRECTION_VISUAL_SYNC_V1'
UNITYPLAYER_SHA256='935c78e7a1b7fae3f0bc6892e390d521e5d24cf40539112559d64312df6107e4'
PRODUCERS=('client_patch/src/prediction_visual_sync_smoke.hpp','client_patch/src/prediction_visual_input_smoke.hpp',
           'client_patch/src/offline_client.cpp','client_patch/src/prediction_visual_correction.cpp',
           'client_patch/src/prediction_visual_click_smoke.hpp','client_patch/src/prediction_virtual_mouse_smoke.hpp',
           'client_patch/src/prediction_visual_click_protocol.hpp','client_patch/src/prediction_visual_physics.hpp',
           'client_patch/src/prediction_visual_batch.hpp')
FIELDS={'schema','event','world','match','sequence','source','module','point','point_bits','pre','sync','post',
        'before','after','checked_us','invariants_unchanged','selection_writes','history_writes','physical_input'}
SNAPSHOT={'checked_us','selector','camera','camera_controller','actor','transform','manager','simulation','handler',
          'thread','owner_thread','frame','revision','joined_us','policy_us','publication_us','alpha','lease','generation',
          'entity','unit_type','army','incarnation','actual','projected','pointer','history','current_ids','preview_ids',
          'casting_ids','pending_commands','mouse','raw','displayed','offset','drag_mode'}
MODULE={'base','pe_timestamp','pe_image_size','pe_offset','resolver','icall','target','target_rva','wrapper_hex','engine_rva'}


def require(value,why):
    if not value:raise AssertionError('prediction visual sync: '+why)


def validate_plan(plan):
    require('visual_sync_probe' not in plan or type(plan['visual_sync_probe']) is bool,'option must be Boolean')
    if not plan.get('visual_sync_probe'):return
    require(plan.get('visual_input') is True and plan.get('visual_correction') is True and plan.get('visual_click_acquire') is True,
            'requires original visual input/correction and acquisition Mouse owner scope')
    acquire.validate_plan(plan)
    pin=plan['files']['unityplayer']
    require(pin['sha256']==UNITYPLAYER_SHA256 and Path(pin['path']).name=='UnityPlayer.dll' and
            Path(pin['path']).parent.resolve()==Path(plan['game']).resolve(),'exact owned UnityPlayer binding missing')


def option(args,frames,trace,delay):
    enabled=getattr(args,'visual_sync_probe',False)
    require(type(enabled) is bool,'option must be Boolean')
    if enabled:require(getattr(args,'visual_click_acquire',False) is True and acquire.option(args,frames,trace,delay) is True,
                       'requires --visual-click-acquire/--visual-input/--visual-correction')
    return enabled


def helper(enabled,data):
    if enabled:require(MARKER in data and PREFIX.encode() in data and
        '-prediction-visual-sync-smoke'.encode('utf-16-le') in data,'helper lacks optional sync probe capability')


def _point(value):
    require(type(value) is list and len(value)==2 and all(queries.finite(v)for v in value),'finite Single point required')
    return motion.vec([*value,0])[:2]


def _bits(point):return list(struct.unpack('<II',struct.pack('<ff',*point)))


def _ray(value):
    require(type(value) is dict and set(value)=={'begin_us','end_us','hit','identity'} and
            queries.integer(value['begin_us'],1) and queries.integer(value['end_us'],value['begin_us']) and
            type(value['hit']) is bool,'original ray/timing schema differs')
    if value['identity'] is not None:queries._identity(value['identity'])


def _snapshot(value,source):
    require(type(value) is dict and set(value)==SNAPSHOT,'stable snapshot schema differs')
    for key in ('selector','camera','camera_controller','actor','transform','manager','simulation','handler'):
        require(queries.pointer(value[key]),'snapshot original root pointer differs')
    require(all(queries.integer(value[k])for k in ('thread','owner_thread','frame','revision','joined_us','policy_us','publication_us',
                'lease','generation','entity','unit_type','army','incarnation')) and queries.finite(value['alpha']) and
            all(value[k]==source[k]for k in ('thread','owner_thread','frame','revision','joined_us','policy_us','publication_us',
                'alpha','lease','generation','entity','unit_type','army','incarnation',*queries.POINTERS)) and
            queries.integer(value['checked_us'],source['query_end_us']) and value['checked_us']-value['joined_us']<=50000 and
            queries.integer(value['pending_commands'],0,4) and queries.integer(value['drag_mode'],-2**31,2**31-1) and
            value['drag_mode']==source['drag_mode'],
            'snapshot lost exact original query owner/join')
    for key in ('actual','raw','displayed','projected'):value[key]=motion.vec(value[key])
    require(type(value['offset']) is list and len(value['offset'])==3 and all(queries.finite(n)for n in value['offset']) and
            value['actual']==source['actual'] and value['raw']==source['raw'] and value['displayed']==source['displayed'] and
            value['projected']==source['displayed_screen'] and value['offset']==source['offset'],'snapshot pose/projection differs')
    value['pointer']=_point(value['pointer'])
    h=value['history']
    require(type(h) is dict and set(h)=={'id','mode','primary','context','drag','last_up','window'} and
            queries.integer(h['id'],0,0xffffffff) and queries.integer(h['mode'],-2**31,2**31-1) and
            all(type(h[k]) is bool for k in ('primary','context','drag')) and
            all(queries.finite(h[k]) and h[k]>=0 for k in ('last_up','window')),'original selector history differs')
    for key in ('current_ids','preview_ids','casting_ids'):
        ids=value[key];require(type(ids) is list and len(ids)<=65536 and len(set(ids))==len(ids) and
            all(queries.integer(n,0,0xfffffffe)for n in ids),'snapshot numeric selection set differs')
    m=value['mouse'];require(type(m) is dict and set(m)=={'device','controls','actions','references','primary','context','session_active','session_sequence'} and
        all(type(m[k]) is bool for k in ('primary','context','session_active')) and queries.integer(m['session_sequence']),
        'original Mouse snapshot schema differs')
    reference=queries.pointer
    require(reference(m['device']) and all(type(m[k]) is list and len(m[k])==3 and all(reference(p)for p in m[k])
            for k in ('controls','actions','references')),'snapshot Mouse owner pointers differ')


def rows(log):
    require(type(log) is str and len(log.encode())<=64*1024*1024,'bounded closed log required')
    require('Visual sync probe failed:' not in log,'original sync diagnostic failed')
    def unique(pairs):
        result={}
        for k,v in pairs:require(k not in result,'duplicate JSON field');result[k]=v
        return result
    def constant(value):raise AssertionError('prediction visual sync: nonfinite JSON '+value)
    result=[];seen=set();last=0
    for line in log.splitlines():
        if PREFIX not in line:continue
        raw=line.split(PREFIX,1)[1];require(len(raw.encode())<=32768,'probe row budget exceeded')
        r=json.loads(raw,object_pairs_hook=unique,parse_constant=constant)
        require(type(r) is dict and set(r)==FIELDS and type(r['schema']) is int and r['schema']==1 and
                r['event'] in ('probe','no_trigger') and type(r['sequence']) is int and r['sequence']==1,
                'sync record schema/event/sequence differs')
        source=queries.rows(queries.PREFIX+json.dumps(r['source']))
        require(len(source)==1,'original source query missing');r['source']=source[0];s=r['source']
        require(r['world']==s['world'] and type(r['world']) is int and r['match']==s['match'] and
                r['world'] not in seen and queries.integer(r['checked_us'],max(last,s['query_end_us'])),
                'world/source/order differs')
        seen.add(r['world']);last=r['checked_us'];r['point']=_point(r['point'])
        require(type(r['point_bits']) is list and len(r['point_bits'])==2 and all(queries.integer(v,0,0xffffffff)for v in r['point_bits']) and
                r['point_bits']==_bits(r['point'])==_bits(s['displayed_screen'][:2]),'probe did not freeze exact original Single point')
        require(r['invariants_unchanged'] is True and r['physical_input'] is False and
                type(r['selection_writes']) is int and r['selection_writes']==0 and
                type(r['history_writes']) is int and r['history_writes']==0,'probe scope/invariants differ')
        if r['event']=='no_trigger':
            require(all(r[k] is None for k in ('module','pre','post','before','after')) and
                    type(r['sync']) is dict and r['sync']=={'calls':0} and type(r['sync']['calls']) is int and
                    s['control']=='zero_after','no-trigger fabricated an intervention or omitted terminal control')
        else:
            m=r['module'];require(type(m) is dict and set(m)==MODULE and queries.pointer(m['base']) and queries.pointer(m['target']) and
                m['pe_timestamp']==1721777247 and type(m['pe_timestamp']) is int and m['pe_image_size']==0x1e58000 and
                type(m['pe_image_size']) is int and m['pe_offset']==328 and type(m['pe_offset']) is int and
                m['resolver']=='il2cpp_resolve_icall' and m['icall']=='UnityEngine.Physics::SyncTransforms' and
                m['target_rva']=='0x1771f0' and int(m['target'],16)==int(m['base'],16)+0x1771f0 and
                m['wrapper_hex']=='e98b1a5600' and m['engine_rva']=='0x6d8c80','exact original resolver/module/entry binding differs')
            _ray(r['pre']);_ray(r['post']);_snapshot(r['before'],s);_snapshot(r['after'],s)
            stable=lambda v:{k:x for k,x in v.items()if k!='checked_us'}
            require(stable(r['before'])==stable(r['after']),'Sync changed an observed owner/pose/input/selection/queue predicate')
            sync=r['sync'];require(type(sync) is dict and set(sync)=={'entered_us','returned_us','calls'} and
                type(sync['calls']) is int and sync['calls']==1 and queries.integer(sync['entered_us'],1) and
                queries.integer(sync['returned_us'],sync['entered_us']) and
                s['query_end_us']<=r['before']['checked_us']<=r['pre']['begin_us']<=r['pre']['end_us']<=sync['entered_us']<=
                sync['returned_us']<=r['post']['begin_us']<=r['post']['end_us']<=r['after']['checked_us']<=r['checked_us'],
                'original source/pre-ray/Sync return/post-ray/check causality differs')
        result.append(r);require(len(result)<=2,'two-world probe budget exceeded')
    return result


def _subject(ray,source):
    return ray['hit'] is True and ray['identity']=={k:source[k]for k in queries.IDENTITY}


def evaluate(records,query_records,visual_records,bindings):
    require(type(bindings) is list and len(bindings)==2 and len({b['world']for b in bindings})==2 and
            len({b['match']for b in bindings})==2 and all(type(b['world']) is int for b in bindings),'two original worlds required')
    require(len(records)==2 and [(r['world'],r['match'])for r in records]==[(b['world'],b['match'])for b in bindings],
            'one terminal probe or no-trigger record per world required')
    worlds=[]
    for r,b in zip(records,bindings):
        s=r['source'];own=[q for q in query_records if q['world']==b['world']]
        require(all(s[k]==b[k]for k in b) and sum(q==s for q in own)==1,'probe lacks its exact unchanged Stage1 query')
        candidates=[q for q in own if q['control']=='nonzero' and q['displayed_inside'] and not _subject(q['displayed_ray'],q)]
        poses=[p for p in visual_records if p['event']=='visual_pose' and p['sampled_us']==s['policy_us'] and
            all(p[k]==s[k]for k in ('world','match','frame','entity','unit_type','army','incarnation','lease'))]
        require(len(poses)==1 and all(poses[0][k]==s[k]for k in ('raw','displayed','alpha','publication_us')) and
                poses[0]['transform']==s['actual'],'probe source lacks the exact completed visual policy pose')
        if r['event']=='no_trigger':
            require(not candidates,'no-trigger omitted an eligible original miss');classification='no_trigger'
        else:
            require(candidates and candidates[0]==s and math.hypot(*s['offset'])>=.5,'probe was not the first eligible original nonzero miss')
            classification=('pre_already_hits_subject' if _subject(r['pre'],s) else
                'pre_result_changed_before_sync' if (r['pre']['hit'],r['pre']['identity'])!=(s['displayed_ray']['hit'],s['displayed_ray']['identity']) else
                'stable_miss_then_subject_hit_after_sync' if _subject(r['post'],s) else
                'miss_remains_after_sync' if (r['pre']['hit'],r['pre']['identity'])==(r['post']['hit'],r['post']['identity']) else
                'non_subject_result_changed_after_sync')
        worlds.append(dict(binding=b,classification=classification,intervention=r['event']=='probe',record=r))
    triggered=any(w['intervention']for w in worlds)
    return dict(schema=1,passed=False,protocol_valid=True,observation_valid=True,triggered=triggered,intervention=triggered,
        status='diagnostic_intervention'if triggered else'incomplete',scope='same_point_original_sync_intervention',worlds=worlds,
        old_stage1_promoted=False,physical_input_accepted=False,full_feature_accepted=False,
        limitations=['Pre/post differences are observations after a global physics intervention; no exclusive collider or synchronization cause is established.',
            'The post ray and all subsequent observations in an intervened world follow SyncTransforms; they cannot qualify the unintervened configuration.',
            'An unchanged result does not establish geometry correctness; no-trigger is incomplete.',
            'Original Stage1/native/wire/feel/visual/lifetime outcomes remain unchanged and mandatory for their own claims.'])


def analyze(plan,report,run):
    validate_plan(plan);require(plan.get('visual_sync_probe') is True,'explicit sync option missing')
    run=Path(run);inputs={}
    def read(path):
        require(path.stat().st_size<=64*1024*1024,'closed input exceeds bound')
        raw=path.read_bytes();inputs[str(path)]=hashlib.sha256(raw).hexdigest();return raw.decode('utf-8')
    log=read(run/'native-0.log');peer=read(run/'native-1.log');require(PREFIX not in peer,'unrequested peer sync probe')
    observed=rows(log);original=queries.rows(log);poses=visual.rows(log)
    require(original==[r for w in report['visual_input']['worlds']for r in w['records']] and
            inputs==report['visual_input']['input_sha256'],'probe did not retain the exact original Stage1/log evidence')
    result=evaluate(observed,original,poses,[w['binding']for w in report['native_position_trace']['worlds']])
    producers={}
    for name in PRODUCERS:
        path=run.parent/'source-at-prepare'/name;require(path.stat().st_size<=256*1024,'producer snapshot exceeds bound')
        digest=motion.sha(path);require(digest==plan['source_sha256'][name],'consumed probe producer differs');producers[name]=digest
    for module in (queries,visual,motion):
        require(motion.sha(module.__file__)==plan['source_sha256']['tools/'+Path(module.__file__).name],'consumed join checker differs')
    require(motion.sha(__file__)==plan['source_sha256']['tools/prediction_visual_sync.py'],'consumed sync checker differs')
    require(report.get('source_unchanged') is True and report.get('files_unchanged') is True and
            report.get('source_sha256_at_start')==report.get('source_sha256_at_finish')==plan['source_sha256'] and
            plan['files']['unityplayer']['sha256']==UNITYPLAYER_SHA256 and
            motion.sha(plan['files']['unityplayer']['path'])==UNITYPLAYER_SHA256,'original runtime module/source identity changed')
    require(all(motion.sha(path)==digest for path,digest in inputs.items()),'closed probe logs changed')
    result.update(file_only=True,input_sha256=inputs,producer_sha256=producers,original_parent_passed=report.get('passed') is True,
        original_stage1_passed=report['visual_input'].get('passed') is True,original_stage1_component_passed=report['visual_input'].get('component_observation_passed') is True,
        query_records=original,joined_visual_poses=[p for p in poses if p['event']=='visual_pose' and any(p['sampled_us']==r['source']['policy_us']for r in observed)],
        runtime_module=plan['files']['unityplayer'])
    return result


def gate(plan,report):
    if not plan.get('visual_sync_probe'):return True
    try:
        validate_plan(plan);proof=report['visual_sync_probe']
        require(proof['passed'] is proof['old_stage1_promoted'] is proof['physical_input_accepted'] is proof['full_feature_accepted'] is False and
            proof['protocol_valid'] is proof['observation_valid'] is True and proof['input_sha256']==report['visual_input']['input_sha256'] and
            proof['query_records']==[r for w in report['visual_input']['worlds']for r in w['records']] and
            proof['runtime_module']==plan['files']['unityplayer'] and
            proof['producer_sha256']=={k:plan['source_sha256'][k]for k in PRODUCERS},'saved diagnostic scope/source binding differs')
        observed=rows('\n'.join(PREFIX+json.dumps(w['record'])for w in proof['worlds']))
        original=queries.rows('\n'.join(queries.PREFIX+json.dumps(r)for r in proof['query_records']))
        poses=visual.rows('\n'.join(visual.PREFIX+json.dumps(p)for p in proof['joined_visual_poses']))
        rebuilt=evaluate(observed,original,poses,[w['binding']for w in report['native_position_trace']['worlds']])
        require(all(rebuilt[k]==proof[k]for k in ('worlds','status','triggered','intervention','scope')),'saved classification/phase/pose differs')
        return True
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError):return False


def finalize(plan,report,run):
    if not plan.get('visual_sync_probe'):return
    parent=report.get('passed') is True
    try:report['visual_sync_probe']=analyze(plan,report,run)
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OSError,OverflowError)as error:
        report['visual_sync_probe']=dict(passed=False,protocol_valid=False,observation_valid=False,status='unqualified',error=repr(error),
            original_parent_passed=parent,old_stage1_promoted=False,physical_input_accepted=False,full_feature_accepted=False)
    report['visual_sync_observation_valid']=report['visual_sync_probe'].get('observation_valid') is True and gate(plan,report)
    report['passed']=False
    report['full_feature_accepted']=False
