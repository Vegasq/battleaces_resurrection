"""Pure evidence for original slot5 Instant Hold14 and a stop before authority."""
from __future__ import annotations

import json
import math
import re

from client_patch.prediction_worker.commands import _action
from server.game_data import decode_player_input
from server.protobuf_wire import get_bytes, get_repeated_bytes, get_repeated_uint, get_uint, parse_fields
from tools import prediction_context_move_evidence as ctx
from tools import prediction_mobile_evidence as mobile

PREFIX='CONTEXT HOLD '
SERIALIZED_PREFIX='CONTEXT HOLD SERIALIZED '
FIELDS=set(('schema,event,sequence,world,match,generation,selector,manager,simulation,server,thread,frame,tick_ms,sampled_us,'
    'slot,entity,unit_type,army,incarnation,current_token,canonical_token,actor,button,panel,source_set,mapped_set,group,'
    'activation,activation_serial,mapping,activation_type,activation_count,from_hotkey,held,perform_calls,pending_commands,'
    'command,command_class,queued,primary,context,drag,active_caster,casting_ids,current_ids,preview_ids,current_count,'
    'position,position_sampled_us,context_input_closed,move_command,originalCtor,original_callback,selection_writes,'
    'history_writes,physicalUI').split(','))
SERIALIZED_FIELDS=set(('schema,world,match,generation,selector,manager,thread,activation_serial,frame,source_next_frame,'
    'sequence,command,action,tick_ms,sampled_us,physicalUI').split(','))


def require(value,why):
    if not value:raise AssertionError('context Hold evidence: '+why)


def _rows(log,prefix,fields,limit):
    result=[]
    require(type(log) is str and len(log)<=32*1024*1024,'log exceeds bound')
    for index,line in enumerate(log.splitlines()):
        if prefix not in line or prefix==PREFIX and SERIALIZED_PREFIX in line:continue
        raw=line.split(prefix,1)[1]
        require(0<len(raw)<=16384,'row exceeds bound')
        try:row=json.loads(raw,object_pairs_hook=ctx._unique)
        except (ValueError,TypeError) as error:raise AssertionError('context Hold evidence: invalid JSON') from error
        require(type(row) is dict and set(row)==fields and ctx.integer(row['schema'],1,1) and
            ctx.integer(row['world'],1,2) and type(row['match']) is str and re.fullmatch('[a-f0-9]{32}',row['match']) and
            ctx.integer(row['frame'],0,1000) and ctx.integer(row['tick_ms']) and ctx.integer(row['sampled_us'],1) and
            row['physicalUI'] is False,'strict schema1/owner/clock differs')
        result.append((index,row));require(len(result)<=limit,'extra rows')
    return result


def records(log,match,*,context=None,original_hold=False):
    require(type(original_hold) is bool,'original Hold scope must be Boolean')
    if original_hold:
        require(context is None and not any(p in log for p in ctx.PREFIXES),'standalone Hold contains context-input evidence')
    elif context is None:
        context=ctx.records(log,match)
    all_rows=_rows(log,PREFIX,FIELDS,6);all_serialized=_rows(log,SERIALIZED_PREFIX,SERIALIZED_FIELDS,2)
    own=[(i,r) for i,r in all_rows if r['match']==match]
    serialized=[(i,r) for i,r in all_serialized if r['match']==match]
    require(len(own)==3 and len(serialized)==1,'three original activation rows and one normal serialization required')
    rows=[r for _,r in own];normal=serialized[0][1];before,returned,complete=rows
    world,token=before['world'],before['incarnation']
    require(ctx.integer(token,1),'original current token missing')
    if not original_hold:
        require(world==context['world'] and token==context['token'],'context/Hold owner token differs')
    require([r['event'] for r in rows]==['before','returned','complete'] and [r['sequence'] for r in rows]==[1,2,3] and
        before['frame']==returned['frame']==198 and complete['frame'] in (260,261),'activation event/frame order differs')
    owner=('world','match','generation','selector','manager','simulation','server','thread')
    retained=('actor','button','panel','source_set','mapped_set','group','activation','mapping','activation_serial',
        'incarnation','current_token','canonical_token','activation_type','activation_count','from_hotkey','held','move_command')
    require(all(all(r[k]==before[k] for k in (*owner,*retained)) for r in rows),'activation owner/retained descriptors changed')
    for n,row in enumerate(rows):
        require(row['world']==world and row['match']==match and
            ctx.integer(row['sequence'],n+1,n+1) and
            all(ctx.integer(row[k],v,v) for k,v in (('slot',1),('entity',11),('unit_type',1),('army',1),
                ('activation_type',1),('activation_count',1),('activation_serial',world),('current_count',1),
                ('perform_calls',0 if n==0 else 1),('pending_commands',1 if n==1 else 0),('selection_writes',0),('history_writes',0))) and
            ctx.integer(row['generation'],1) and ctx.integer(row['thread'],1,ctx.UINT32) and
            all(ctx.integer(row[k],token,token) for k in ('incarnation','current_token','canonical_token')) and
            row['from_hotkey'] is True and row['held'] is False and
            (row['context_input_closed'] is None if original_hold else row['context_input_closed'] is True) and
            (row['move_command'] is None if original_hold else True) and
            row['originalCtor'] is False and row['original_callback']=='Uncapped.AbilityButtonAction.PerformButtonAction' and
            all(row[k] is False for k in ('primary','context','drag')),'activation scope/input/identity differs')
        for key in ('selector','manager','simulation','server','actor','button','panel','source_set','mapped_set','group','activation'):
            ctx.pointer(row[key])
        ctx.pointer(row['active_caster'],optional=True)
        for key in ('current_ids','preview_ids','casting_ids'):
            require(type(row[key]) is list and row[key] in ([],[11]),'unexpected original selection/scratch IDs')
        require(row['current_ids']==[11] and ctx.vector(row['position'],3) and
            ctx.integer(row['position_sampled_us'],1,row['sampled_us']-1),'actual selected pose/clock missing')
        mapping=row['mapping']
        require(type(mapping) is dict,'missing original mapping')
        mobile._caster_survey_button(mapping,mapping.get('index'))
        require(mapping['present'] is True and mapping['button_class']=='Uncapped.AbilityButtonAction' and
            mapping['slot']==5 and mapping['config_id']==14 and mapping['cast_type']==2 and mapping['group_kind']==0 and
            mapping['smart_casting'] is False and mapping['valid_button'] is True and mapping['panel_group_matches'] is True and
            mapping['group_unity_truth'] is True and mapping['mapped_ids']==[11] and mapping['mapped_count']==1 and
            mapping['has_mapped_casters'] is True,'slot5 original Hold14 readiness/mapping differs')
        if n==0:
            require(row['command'] is None and row['command_class'] is None and row['queued'] is None and
                row['active_caster'] is None and not row['casting_ids'],'command/caster preceded original activation')
        else:
            ctx.pointer(row['command'])
            require(row['command_class']=='Uncapped.ExecuteInstantCommand' and row['queued'] is False,
                'original activation did not enqueue an unqueued Instant command')
    require(returned['command']==complete['command'] and all(b['sampled_us']>a['sampled_us'] and
        b['tick_ms']>=a['tick_ms'] for a,b in zip(rows,rows[1:])),'return/completion command or clock differs')
    if not original_hold:
        closed=context['events']['context_closed'];end=context['events']['complete'];callback=context['callbacks'][0]
        require(before['selector']==closed['selector'] and before['generation']==callback['generation'] and
            all(before[k]==callback[k] for k in ('manager','simulation','server','thread')) and
            before['move_command']==context['order']['command'] and closed['sampled_us']<before['position_sampled_us'] and
            complete['frame']==end['frame'] and complete['sampled_us']>end['sampled_us'],
            'Hold is not after the same real context release/completion')
    for key in ('world','match','generation','selector','manager','thread','activation_serial','command'):
        require(normal[key]==returned[key],'normal serialization owner/activation/command changed')
    ctx.pointer(normal['action'])
    require(all(ctx.integer(normal[k],1) for k in ('generation','thread','activation_serial','sequence')) and
        (original_hold or normal['sequence']>context['serialized']['sequence']) and
        ctx.integer(normal['source_next_frame'],0,1000) and returned['frame']<=normal['frame']<=returned['frame']+1 and
        returned['sampled_us']<normal['sampled_us']<complete['sampled_us'] and
        returned['tick_ms']<=normal['tick_ms']<=complete['tick_ms'] and
        own[1][0]<serialized[0][0]<own[2][0],'normal ToProto is early/duplicated/late')
    # Every HOLD event is immediately sourced from the last actual same-owner pose.
    for index,row in own:
        candidates=[]
        for i,line in enumerate(log.splitlines()[:index]):
            if 'MOBILE FEEL ' in line:
                pose=json.loads(line.split('MOBILE FEEL ',1)[1],object_pairs_hook=ctx._unique)
                if pose.get('match')==match:candidates.append(pose)
        require(candidates,'activation lacks actual preceding Transform pose')
        pose=candidates[-1]
        require(pose.get('world')==row['world'] and pose.get('incarnation')==row['incarnation'] and
            pose.get('frame')==row['frame'] and pose.get('sampled_us')==row['position_sampled_us'] and
            pose.get('position')==row['position'] and pose.get('baseline') is False and pose.get('jobsJoined') is True and
            pose.get('source')=='UnityEngine.Transform.get_position','HOLD position is not its actual raw preceding pose')
    return dict(rows=rows,indices=[i for i,_ in own],serialized=normal,serialized_index=serialized[0][0],
        world=world,match=match,token=token,scope='scripted_move_original_button' if original_hold else 'context')


def binding(log,witness,*,commits,raw_bodies,journal):
    normal=witness['serialized'];match=witness['match'];sequence=normal['sequence']
    body=raw_bodies.get((match,1,sequence));require(type(body) is bytes,'normal native67 body missing')
    decoded=decode_player_input(body)
    require(len(decoded['actions'])==1 and decoded['identity']['player_id']==2 and decoded['identity']['is_aliased'] and
        not decoded['identity']['ai_profile_id'],'Hold batch is not one original victim-human action')
    action=decoded['actions'][0];require([f.number for f in parse_fields(action)]==[1],'Hold action is not Execute')
    execute=get_bytes(action,1,required=True);groups=get_repeated_bytes(execute,1)
    target=get_bytes(execute,3,required=True)
    require(len(groups)==1 and get_uint(groups[0],1)==1 and get_uint(groups[0],2)==14 and
        get_repeated_uint(groups[0],3)==(11,) and get_uint(execute,2)==0 and
        [f.number for f in parse_fields(target)]==[1] and get_bytes(target,1,required=True)==b'',
        'original Hold must be own11/type1/ability14/unqueued/Instant{}')
    normalized,predictive,join=_action(action,1)
    require(normalized==action and predictive is True and join is False,'original Hold eligibility differs')
    digest=mobile.digest(action)
    reg=re.findall(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) tick=(\d+) match='+re.escape(match)+r'(?:\s|$)',log)
    reg=[tuple(map(int,r)) for r in reg if int(r[0])==sequence]
    sent=re.findall(r'Original command batch submitted: match='+re.escape(match)+
        r' sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)',log)
    sent=[x for x in sent if int(x[0])==sequence]
    require(len(reg)==len(sent)==1 and reg[0][2]>=normal['tick_ms'] and int(sent[0][4])>=reg[0][2] and
        int(sent[0][1])==1 and int(sent[0][2])==len(body) and sent[0][3]==mobile.digest(body) and
        int(sent[0][5])==normal['source_next_frame'],'normal Hold67/72/body/sequence join differs')
    committed=[r for r in commits if (r.get('event'),r.get('match'),r.get('slot'),r.get('sequence'))==
        ('command_batch_committed',match,1,sequence)]
    require(len(committed)==1 and ctx.integer(committed[0].get('frame'),0,1000),'unique canonical Hold commit missing')
    frame=committed[0]['frame']
    require(198<=frame<=200 and abs(reg[0][1]-frame)<=1 and
        [(r['frame'],s) for r in journal for s,actions in r['players'].items() for a in actions if mobile.digest(a)==digest]==[(frame,1)],
        'canonical Hold occurrence/phase differs')
    return dict(passed=True,ability=14,instant=True,prediction_eligible=True,sequence=sequence,action_sha256=digest,
        body_sha256=mobile.digest(body),canonical_commit_frame=frame,speculative_frame=reg[0][1],
        speculative_minus_canonical_frames=reg[0][1]-frame,native67_tick_ms=reg[0][2],native72_send_tick_ms=int(sent[0][4]))


def post_return_scope(witness,row):
    returned,complete=witness['rows'][1:]
    return (returned['sampled_us']<=row['sampled_us']<=complete['sampled_us'] and
        returned['frame']<=row['frame']<=complete['frame'])


def bind_mobile(witness,rows,indices):
    last=rows[-1];complete=witness['rows'][-1]
    require(last['event']=='mobile_observation_complete' and last['frame']==complete['frame'] and
        last['sampled_us']<=complete['position_sampled_us'] and indices[-1]<witness['indices'][-1] and
        last['selected_ids']==complete['current_ids'] and last['preview_ids']==complete['preview_ids'] and
        last['casting_ids']==complete['casting_ids'] and
        ctx.pointer(last['active_caster'],optional=True)==ctx.pointer(complete['active_caster'],optional=True) and
        ctx.pointer(last['current_actor'])==ctx.pointer(complete['actor']) and last['current_admitted'] is True and
        last['current_incarnation']==complete['incarnation'],'final raw mobile/Hold snapshot differs')


def stop(log,witness,move_order,receipt,bridge):
    before,returned,_=witness['rows'];poses=mobile._rows(log,'MOBILE FEEL ',witness['match'],1024)
    for row in poses:
        mobile._common(row,world=witness['world'])
        require(row.get('event')=='transform' and (row['entity'],row['unit_type'],row['army'])==(11,1,1) and
            type(row.get('incarnation')) is int and row['incarnation']==witness['token'] and
            row.get('move_id')==1 and type(row.get('baseline')) is bool and row.get('jobsJoined') is True and
            row.get('source')=='UnityEngine.Transform.get_position' and row.get('presented_frame')==row['frame'] and
            ctx.integer(row.get('completed_frame'),-1,1000),'Hold pose owner/source differs')
        mobile._vector(row.get('position'))
    require(all(b['sampled_us']>a['sampled_us'] and b['tick_ms']>=a['tick_ms'] and b['frame']>=a['frame']
        for a,b in zip(poses,poses[1:])),'Hold pose clocks regressed')
    pre=[r for r in poses if before['sampled_us']-200000<=r['sampled_us']<=before['position_sampled_us']]
    direction=[b-a for a,b in zip(move_order['origin'],move_order['target'])];distance=math.sqrt(sum(x*x for x in direction))
    require(distance>1 and len(pre)>=3 and pre[-1]['sampled_us']-pre[0]['sampled_us']>=150000 and
        before['sampled_us']-pre[-1]['sampled_us']<=50000 and
        sum((b-a)*d for a,b,d in zip(pre[0]['position'],pre[-1]['position'],direction))/distance>=.15 and
        math.dist(before['position'],move_order['target'])>1,'Hold lacks sustained unfinished targetward motion')
    cutoff=min(receipt['tick_ms'],bridge['received_tick_ms'])
    post=[r for r in poses if r['sampled_us']>returned['sampled_us'] and r['tick_ms']<cutoff]
    for start in range(len(post)):
        if post[start]['sampled_us']>returned['sampled_us']+150000:break
        for end in range(start+2,len(post)):
            window=post[start:end+1]
            if window[-1]['sampled_us']-window[0]['sampled_us']<150000:continue
            drift=max(math.dist(a['position'],b['position']) for a in window for b in window)
            if drift<=.025 and all(math.dist(p['position'],move_order['target'])>1 for p in window):
                return dict(passed=True,moving_rows=pre,settled_rows=window,max_drift=drift,
                    settle_after_enqueue_ms=(window[0]['sampled_us']-returned['sampled_us'])/1000,
                    before_native65_ms=receipt['tick_ms']-window[-1]['tick_ms'],
                    before_raw_bridge_ms=bridge['received_tick_ms']-window[-1]['tick_ms'])
            break
    require(False,'no genuine stable stop interval before both native65 and raw bridge')


def qualify(log,*,context,move_order,move_sequence,commits,raw_bodies,journal,bridge_frames,canonical_payloads,
            canonical_states,worker_states,join_check,authority_rows,original_hold=False):
    match=move_order['match']
    witness=records(log,match,context=context,original_hold=original_hold)
    require(witness['serialized']['sequence']>move_sequence and
        move_order['enqueue_sampled_us']<witness['rows'][0]['position_sampled_us'] and
        (not original_hold or move_order.get('originalCtor') is True and move_order.get('frame')==180 and
            move_order.get('event')=='original_fresh_move' and move_order.get('incarnation')==witness['token']),
        'standalone Hold lacks the exact existing scripted original Move180')
    bound=binding(log,witness,commits=commits,raw_bodies=raw_bodies,journal=journal)
    receipt,bridge=mobile._receipt(bound['canonical_commit_frame'],witness['world'],witness['match'],
        authority_rows,bridge_frames,canonical_payloads)
    native=mobile._joined(join_check,worker_states,world=witness['world'],receipt=receipt,states=canonical_states,
        journal=journal,action_hash=bound['action_sha256'],slot=1,replay=False)
    span=mobile._assignment_span(worker_states,world=witness['world'],assigned=bound['speculative_frame'],
        canonical=bound['canonical_commit_frame'],states=canonical_states)
    settled=stop(log,witness,move_order,receipt,bridge)
    return dict(passed=True,evidence_schema=1,scope=witness['scope'],world=witness['world'],match=witness['match'],rows=witness['rows'],
        serialized=witness['serialized'],binding=bound,actual_native65=receipt,raw_bridge=bridge,native_confirmation=native,
        assignment_span=span,stop=settled,normal_serialization_only=True,originalCtor=False,selection_writes=0,history_writes=0,
        physicalUI=False,physical_keyboard=False,full_feature_accepted=False)


def evaluate(log,*,attacker_log,mobile_episodes,expected_matches,original_hold=False):
    require(type(original_hold) is bool,'original Hold scope must be Boolean')
    if original_hold:require(not any(p in log or p in attacker_log for p in ctx.PREFIXES),
        'standalone Hold contains a context-input route')
    require(PREFIX not in attacker_log and len(expected_matches)==len(set(expected_matches))==len(mobile_episodes)==2 and
        [x.get('match') for x in mobile_episodes]==expected_matches,'two ordered victim-only Hold episodes required')
    result=[]
    for world,(match,ep) in enumerate(zip(expected_matches,mobile_episodes),1):
        witness=records(log,match,original_hold=original_hold)
        proof=ep.get('mobile_original_hold' if original_hold else 'mobile_context_hold',{})
        require(ep.get('passed') is True and ep.get('world')==world==witness['world'] and
            (not ep.get('mobile_context_move') if original_hold else ep.get('mobile_context_move',{}).get('passed') is True) and
            ep.get('fresh_motion',{}).get('passed') is True and proof.get('scope')==witness['scope'] and
            proof.get('passed') is True and proof.get('rows')==witness['rows'] and proof.get('serialized')==witness['serialized'] and
            proof.get('stop',{}).get('passed') is True and proof.get('native_confirmation',{}).get('continuation_frames')==20,
            'Hold lacks unchanged context/mobile/native/stop proof')
        result.append(proof)
    require(len(_rows(log,PREFIX,FIELDS,6))==6 and len(_rows(log,SERIALIZED_PREFIX,SERIALIZED_FIELDS,2))==2,
        'unjoined Hold rows')
    return dict(passed=True,evidence_schema=1,scope='scripted_move_original_button' if original_hold else 'context',
        episodes=result,originalCtor=False,selection_writes=0,history_writes=0,
        physicalUI=False,physical_keyboard=False,full_feature_accepted=False)
