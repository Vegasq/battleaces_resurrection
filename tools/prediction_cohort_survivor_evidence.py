"""Pure proof of an initial selected pair through one member's false death.

The source rows stay intact. No singleton projection, repair reselection, native
query, input or process is created here. RouteA wire/pose and mobile replay joins
supply the existing strict contracts.
"""
from __future__ import annotations
import re
from tools import prediction_multi_unit_evidence as shared
from tools import prediction_mobile_evidence as mobile
from tools.prediction_mobile_plan import validate_cohort_survivor_plan
from tools.prediction_actor_fixture import mobile_survivor_metadata

PREFIX='COHORT SURVIVOR '
SPEC=dict(type=1,army=1,first_frame=130,last_frame=220,max_entities=8)
COMMON=shared.COMMON|{'physicalUI'}
SNAPSHOT={'members','selector','manager','simulation','group_generation','current_ids','preview_ids','casting_ids','active_caster','primary','context','drag',
 'last_click_id','click_mode','pending_commands','selection_calls','group_assign_calls','selection_scope_player_initiated','history_writes',
 'current_count','current_all_ids','current_typed_ids','current_frame_owner','group','helper','group_ids','group_count','group_all_ids','group_typed_ids',
 'group_frame_owner','tracked_released_ids','auto_type1'}
MEMBER={'id','unit_type','army','original_token','incarnation','canonical_token','actor','native_present','native_state','admitted','initialized',
 'original_actor','original_active','original_retained','original_dead','original_component','position','position_bits','position_sampled_us','jobs_joined',
 'current_has_type','group_has_type'}
EVENTS={'selected','setup','sample','native_dead','released','restored','move_queued','serialized','batch_registered','authority','complete'}
require=shared.require

def records(log,match,slot,*,prefix=PREFIX,events=EVENTS):
    require(type(log)is str and len(log.encode('utf8'))<=64*1024*1024,'survivor log bound')
    out=[];last_us=last_tick=-1
    for line_number,line in enumerate(log.splitlines(),1):
        if prefix not in line:continue
        raw=line.split(prefix,1)[1];require(0<len(raw)<=16384,'survivor row bound');r=shared._decode(raw)
        require(type(r)is dict and COMMON<=set(r)and type(r['schema'])is int and r['schema']==1 and r['event']in events and
            type(r['match'])is str and re.fullmatch('[a-f0-9]{32}',r['match'])and r['slot']==slot and type(r['slot'])is int and
            shared.integer(r['world'],1)and shared.integer(r['frame'],-1,2**31-1)and shared.integer(r['completed_frame'],-1,2**31-1)and
            shared.integer(r['sampled_us'])and shared.integer(r['tick_ms'])and r['sampled_us']>=last_us and r['tick_ms']>=last_tick and
            r['physicalUI']is False,'survivor common/event/identity/clock differs')
        last_us,last_tick=r['sampled_us'],r['tick_ms']
        if r['match']==match:out.append(dict(row=r,line=line_number))
        require(len(out)<=4096,'survivor observation budget')
    require(out,'survivor observation missing');return out

def snapshot(r,slot,*,canonical_death=False):
    extra={'confirmed_frame','group_raw_has_victim','group_helper_suspended','group_victim_intent_pending'}if canonical_death else set()
    require(set(r)==COMMON|SNAPSHOT|extra and type(r['members'])is list and [m.get('id')for m in r['members']]==([10]if slot==0 else[11,12]),'survivor snapshot fields/fixed IDs differ')
    require(all(shared.ptr(r[k])for k in('selector','manager','simulation','current_frame_owner'))and shared.integer(r['group_generation'])and
        all(shared.ids(r[k])for k in('current_ids','preview_ids','casting_ids','current_all_ids','current_typed_ids'))and
        r['current_ids']==r['current_all_ids']and shared.integer(r['current_count'],0,8)and r['active_caster']is None and
        r['primary']is r['context']is r['drag']is False and not r['casting_ids']and r['pending_commands']==0 and
        shared.integer(r['last_click_id'],0,2**32-1)and type(r['click_mode'])is int and r['click_mode']==0 and
        r['history_writes']==0,'survivor root/cache/input snapshot differs')
    for m in r['members']:
        require(set(m)==MEMBER and m['unit_type']==1 and m['army']==slot and shared.integer(m['original_token'],1)and
            shared.integer(m['incarnation'])and shared.integer(m['canonical_token'])and shared.ptr(m['original_actor'])and
            (m['actor']is None or shared.ptr(m['actor']))and all(type(m[k])is bool for k in('native_present','admitted','initialized','original_active','original_retained','original_dead','original_component','jobs_joined','current_has_type')),
            'survivor member typed state/lease differs')
        require((m['native_state']is None)==(not m['native_present'])and(m['native_state']is None or shared.integer(m['native_state'],0,2**32-2)), 'survivor native presence/state differs')
        if m['actor']is None:require(m['incarnation']==0 and not m['initialized']and not m['admitted'],'absent actor invented current lease')
        eligible=m['native_present']and m['native_state']!=6 and m['initialized']and m['admitted']
        if eligible:
            shared.bits_point(m['position'],m['position_bits']);require(m['jobs_joined']is True and shared.integer(m['position_sampled_us'])and m['position_sampled_us']<=r['sampled_us'],'survivor Transform query provenance differs')
        else:require(m['position']is m['position_bits']is m['position_sampled_us']is None and m['jobs_joined']is False,'unavailable member invented pose')
        if m['native_present']:require(m['current_has_type']is True,'native-present member lacks source original HasType')
        if slot==0:require(m['group_has_type']is None,'host invented group HasType')
        else:require(type(m['group_has_type'])is bool and m['group_has_type']==m['current_has_type'],'same frame owner HasType differs')
    if canonical_death:
        require(shared.integer(r['confirmed_frame'],0,2**31-1),'canonical loss actual admission frame missing')
        if slot==0:require(all(r[k]is None for k in extra-{'confirmed_frame'}),'host invented group purge observation')
        else:require(all(type(r[k])is bool for k in extra-{'confirmed_frame'})and r['group_helper_suspended']is False,'group purge scope is still suspended')
    if slot==0:
        require(r['selection_calls']==r['group_assign_calls']==0 and r['selection_scope_player_initiated']is None and all(r[k]is None for k in
            ('group','helper','group_ids','group_count','group_all_ids','group_typed_ids','group_frame_owner','tracked_released_ids','auto_type1')),'host selection/group mutation invented')
        return r
    a,b=r['members'];require((a['canonical_token']in(0,a['original_token'])if canonical_death else a['canonical_token']==a['original_token'])and b['canonical_token']==b['original_token']and
        b['native_present']and b['native_state']!=6 and b['admitted']and b['initialized']and b['current_has_type']and
        b['actor']==b['original_actor']and b['incarnation']==b['original_token']and b['original_active']and
        not b['original_retained']and not b['original_dead']and b['original_component'],'survivor12 lease/native identity did not survive')
    require(r['selection_calls']==r['group_assign_calls']==1 and r['selection_scope_player_initiated']is False and
        all(shared.ptr(r[k])for k in('group','helper','group_frame_owner'))and r['current_frame_owner']==r['group_frame_owner']and
        all(shared.ids(r[k])and(set(r[k])in({12},{11,12})if canonical_death else set(r[k])=={11,12})for k in('current_ids','current_all_ids','group_ids','group_all_ids'))and
        all(shared.ids(r[k])and 12 in r[k]and set(r[k])<={11,12}for k in('current_typed_ids','group_typed_ids'))and
        shared.ids(r['tracked_released_ids'])and r['auto_type1']is False and
        r['current_count']==sum(m['current_has_type']for m in(a,b))and r['group_count']==sum(m['group_has_type']for m in(a,b)),
        'selected pair raw intent/HasType Count/type1 survivor/frame owner differs')
    if canonical_death:
        require(r['group_ids']==r['group_all_ids']and r['group_raw_has_victim']==(11 in r['group_all_ids'])and
            set(r['group_typed_ids'])==set(r['group_all_ids']),'canonical loss raw group all/type cache differs')
        if a['canonical_token']:
            require(set(r['group_all_ids'])=={11,12},'original group purged before confirmed loss')
    if a['native_present']and a['native_state']!=6 and a['initialized']and a['admitted']:
        require(set(r['current_typed_ids'])==set(r['group_typed_ids'])=={11,12}and r['current_count']==r['group_count']==2 and
            a['incarnation']==a['original_token'],'restored pair source/cache is incomplete')
    return r

def _one(rows,event):return shared._one(rows,event)
def _command(log,rows,context,slot,*,canonical_death=False):
    qx,sx,rx=(_one(rows,n)for n in('move_queued','serialized','batch_registered'));q,s,r=qx['row'],sx['row'],rx['row']
    require(set(q)==shared.COMMON|shared.ORDER and set(s)==shared.COMMON|shared.SERIAL and set(r)==shared.COMMON|shared.REGISTERED,'survivor command fields differ')
    expected=[12]if canonical_death else[10]if slot==0 else[11,12]
    require(q['frame']==(150 if slot==0 else 180)and q['source_ids']==expected and len(q['incarnations'])==len(q['origins'])==len(q['origins_sampled_us'])==len(expected)and
        all(shared.integer(x,1)for x in q['incarnations'])and all(shared.point(p)for p in q['origins'])and
        all(shared.integer(t)and t<=q['sampled_us']for t in q['origins_sampled_us'])and
        q['ability']==12 and q['queue_before']==0 and q['queue_after']==1 and q['queued']is False and q['originalCtor']is True and
        q['original_callback']=='Uncapped.ExecuteTargetGroundCommand..ctor'and q['command_class']=='Uncapped.ExecuteTargetGroundCommand'and
        shared.ptr(q['command'])and q['sampled_us']<=q['enqueue_sampled_us'],'survivor original Move source/queue/constructor differs')
    require(qx['line']<sx['line']<rx['line']and q['enqueue_sampled_us']<=s['sampled_us']<=r['sampled_us']and
        q['command']==s['command']==r['command']and shared.ptr(s['action'])and s['action']==r['action']and
        s['sequence']==r['sequence']and shared.integer(s['sequence'],1)and s['action_index']==r['action_index']==0,'survivor normal serializer/67 same-command proof differs')
    mobile._perspective(q);order=dict(q,sequence=r['sequence'])
    binding=shared.bind_move(log,order,slot=slot,match=context['match'],raw_bodies=context['raw_bodies'],commits=context['commits'],journal=context['journal'])
    require(r['speculative_frame']==binding['assigned_frame']and r['action_sha256']==binding['action_sha256']and r['body_sha256']==binding['body_sha256'],'survivor native67 bytes differ')
    if slot==0:require(order['target']==[-32,0,0]and binding['canonical_frame']in(151,152),'qualified escape target/canonical frame changed')
    return order,binding

def _authority(rows,states,metadata):
    require([r['frame']for r in rows]==list(range(130,221)),'survivor full native authority window missing')
    for r in rows:
        f=r['frame'];a=r.get('attacker');v=r.get('victim');s=r.get('survivor')
        require(r['parsed_state_sha256']==states.get(f)and r['game_state'].get('complete')is False,'survivor canonical fullstate hash differs')
        require(type(v)is dict and(v.get('id'),v.get('type'),v.get('army'),v.get('max_health'))==(11,1,1,100)and
            type(v.get('current_damage'))in(int,float)and 0<=v['current_damage']<100 and(f>173 or v['current_damage']==(0 if f<142 else 50)), 'qualified victim authority changed')
        require(type(s)is dict and(s.get('id'),s.get('type'),s.get('army'),s.get('max_health'),s.get('current_damage'))==(12,1,1,100,0),'authority survivor12 absent/dead/damaged')
        require((type(a)is dict and(a.get('id'),a.get('type'),a.get('army'),a.get('max_health'),a.get('current_damage'))==(10,1,0,100,0 if f<142 else 50 if f<153 else 100))if f<=153 else a is None,'qualified attacker authority changed')

def evaluate(log,*,attacker_log,match,commits,raw_bodies,journal,bridge_frames,canonical_payloads,canonical_states,native_states,worker_states,
             escape_check,join_check,authority_rows,cohort_trace,native_receipts,peer_bridge_frames):
    context=dict(match=match,raw_bodies=raw_bodies,commits=commits,journal=journal,canonical_states=canonical_states,canonical_payloads=canonical_payloads,bridge_frames=bridge_frames)
    own=records(log,match,1);other=records(attacker_log,match,0);critical={n:_one(own,n)['row']for n in('selected','native_dead','released','restored','complete')};setup,dead,released,restored,complete=(critical[n]for n in critical)
    world=setup['world'];require({x['row']['world']for x in own}=={world},'survivor current world mismatch')
    samples=[x['row']for x in own if x['row']['event']in('selected','sample','native_dead','released','restored','complete')]
    for slot,rows in((1,own),(0,other)):
        for x in rows:
            r=x['row']
            if r['event']in('selected','setup','sample','native_dead','released','restored','complete'):snapshot(r,slot)
            elif r['event']=='authority':require(set(r)==shared.COMMON|shared.AUTHORITY,'survivor accepted65 fields differ')
    require(set(r['frame']for r in samples)==set(range(130,221))and setup['frame']==130 and complete['frame']==220,'selected pair lifecycle frame coverage incomplete')
    roots=('selector','manager','simulation','group_generation','group','helper','current_frame_owner','group_frame_owner')
    tokens=[m['original_token']for m in setup['members']];origins=[m['original_actor']for m in setup['members']]
    require(all(all(r[k]==setup[k]for k in roots)and[m['original_token']for m in r['members']]==tokens and
        [m['original_actor']for m in r['members']]==origins for r in samples),'pair owners/initial tokens/roots changed')
    require(dead['members'][0]['native_state']==6 and dead['frame']>=153 and
        not released['members'][0]['native_present']and not released['members'][0]['original_component']and
        not released['members'][0]['original_active']and not released['members'][0]['original_retained']and
        released['current_count']==released['group_count']==1 and not released['members'][0]['current_has_type']and
        restored['members'][0]['native_present']and restored['members'][0]['native_state']!=6 and
        restored['members'][0]['admitted']and restored['members'][0]['initialized']and restored['current_count']==2 and
        dead['sampled_us']<released['sampled_us']<restored['sampled_us']and dead['frame']<released['frame']<=restored['frame']<=164,
        'actual one-member native death/release/reinit chronology missing')
    order,binding=_command(log,own,context,1);escape,escape_binding=_command(attacker_log,other,context,0)
    require(order['incarnations']==tokens and restored['sampled_us']<order['sampled_us']and setup['sampled_us']<escape['sampled_us'],'cohort constructor rebound from current original selection')
    ar,br=shared.exact_receipt(log,world=world,match=match,frame=escape_binding['canonical_frame'],bridge_frames=bridge_frames,canonical_payloads=canonical_payloads,authority_rows=authority_rows)
    require(dead['tick_ms']<min(ar['tick_ms'],br['received_tick_ms'])and restored['tick_ms']>=ar['tick_ms'],'native false death was not before both authority receipts')
    replay=mobile._joined(join_check,worker_states,world=world,receipt=ar,states=canonical_states,journal=journal,action_hash=escape_binding['action_sha256'],slot=0,replay=True,latest_tick=restored['tick_ms'])
    receipt,bridge=shared.exact_receipt(log,world=world,match=match,frame=binding['canonical_frame'],bridge_frames=bridge_frames,canonical_payloads=canonical_payloads,authority_rows=authority_rows)
    confirmation=mobile._joined(join_check,worker_states,world=world,receipt=receipt,states=canonical_states,journal=journal,action_hash=binding['action_sha256'],slot=1,replay=False)
    _authority(native_states,canonical_states,mobile_survivor_metadata());native=shared.validate_native_trace(cohort_trace,spec=SPEC);native=[r for r in native if r['world']==world]
    confirmed={r['frame']:r for r in worker_states if r['world']==world}
    require(all(f in confirmed and confirmed[f]['parsed_state_sha256']==canonical_states.get(f)for f in range(min(binding['assigned_frame'],binding['canonical_frame']),binding['canonical_frame']+21)),'pair assigned-span/+20 hash differs')
    motion=[]
    for i,entity in enumerate((11,12)):
        poses=[dict(position=r['members'][i]['position'],sampled_us=r['members'][i]['position_sampled_us'],tick_ms=r['tick_ms'])for r in samples if r['sampled_us']>=restored['sampled_us']and r['members'][i]['position']is not None]
        motion.append(dict(entity=entity,incarnation=tokens[i],render=shared.rendered_response(poses,order,member=dict(position=order['origins'][i]),receipt=receipt,bridge=bridge),native=shared.native_response(native,order,binding,entity=entity,receipt=receipt,bridge=bridge)))
    actual=[(s,shared.digest(a))for r in journal if 130<=r['frame']<=220 for s,aa in r['players'].items()for a in aa]
    require(actual==[(0,escape_binding['action_sha256']),(1,binding['action_sha256'])],'survivor observation has unrelated/missing commands')
    return dict(passed=True,match=match,world=world,selection_frame=130,death_frame=dead['frame'],release_frame=released['frame'],restored_frame=restored['frame'],
        critical_rows=critical,selected_ids=[11,12],selection_calls=1,group_assign_calls=1,reselection_calls=0,selection_scope_player_initiated=False,
        absent_count=1,restored_count=2,has_type_counts_verified=True,survivor_lease_preserved=True,victim_canonical_token=tokens[0],survivor_canonical_token=tokens[1],
        fresh=binding,escape=escape_binding,escape_native_replay=replay,fresh_native_confirmation=confirmation,members=motion,
        typed_membership_observations=[dict(frame=r['frame'],current=r['current_typed_ids'],group=r['group_typed_ids'])for r in( dead,released,restored)],
        all_retained_wire_triples_checked=shared.all_wire(context=context,peer_bridge_frames=peer_bridge_frames,native_receipts=native_receipts),physicalUI=False,full_mobile_controls_accepted=False)

def decorate(report,episodes):
    report['cohort_survivor']=dict(passed=all(e['passed']for e in episodes),episodes=[{k:e[k]for k in('passed','match','world','selected_ids','reselection_calls','has_type_counts_verified','survivor_lease_preserved')}for e in episodes],physicalUI=False)
    report['survivor_witness_passed']=report['cohort_survivor']['passed']

def gate(plan,report):
    if plan.get('cohort_canonical_death'):
        from tools.prediction_cohort_canonical_death_evidence import gate as death_gate
        return death_gate(plan,report)
    if not plan.get('cohort_survivor'):return True
    try:validate_cohort_survivor_plan(plan)
    except AssertionError:return False
    own=report.get('cohort_survivor',{});eps=own.get('episodes',[]);mobile_eps=report.get('mobile_correction',{}).get('episodes',[])
    return bool(report.get('survivor_witness_passed')is True and own.get('passed')is True and len(eps)==len(mobile_eps)==2 and
        [e['match']for e in eps]==[m['match']for m in report.get('matches',[])]and all(e.get('passed')is True and e.get('world')==m.get('world')and
        e.get('selected_ids')==[11,12]and e.get('reselection_calls')==0 and e.get('has_type_counts_verified')is True and e.get('survivor_lease_preserved')is True for e,m in zip(eps,mobile_eps)))
