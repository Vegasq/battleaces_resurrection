"""Pure evidence for partial canonical-death group purge; never a replay claim."""
from __future__ import annotations
import re
from tools import prediction_cohort_survivor_evidence as survivor
from tools import prediction_multi_unit_evidence as shared
from tools import prediction_mobile_evidence as mobile
from tools.prediction_mobile_plan import validate_cohort_survivor_plan

PREFIX='COHORT CANONICAL DEATH '
EVENTS=(survivor.EVENTS-{'restored'})|{'confirmed_loss','purge_observed'}
SNAPSHOTS={'selected','setup','sample','native_dead','released','confirmed_loss','purge_observed','complete'}
require=shared.require


def authority(rows,states):
    require([r['frame']for r in rows]==list(range(130,221)),'canonical death authority window incomplete')
    for r in rows:
        f=r['frame'];s=r.get('survivor')
        require(r['parsed_state_sha256']==states.get(f)and r['game_state'].get('complete')is False,
                'canonical death full authority hash differs')
        for key,entity,army in(('attacker',10,0),('victim',11,1)):
            u=r.get(key)
            if f>=154:require(u is None,'canonically dead unit returned')
            else:require(type(u)is dict and(u.get('id'),u.get('type'),u.get('army'),u.get('max_health'),u.get('current_damage'))==
                (entity,1,army,100,0 if f<142 else 50 if f<153 else 100),'retained native baseline duel changed')
        require(type(s)is dict and(s.get('id'),s.get('type'),s.get('army'),s.get('max_health'),s.get('current_damage'))==(12,1,1,100,0),
                'canonical survivor12 missing or damaged')


def markers(log,*,world,match,token):
    found={k:[]for k in('retained','purged')}
    pattern=re.compile(r'Prediction group intent (retained|purged): world=(\d+) match=([a-f0-9]{32}) group=(\d+) entity=(\d+) (.*)$')
    for line_number,line in enumerate(log.splitlines(),1):
        m=pattern.search(line)
        if not m or m[3]!=match or int(m[4])!=4 or int(m[5])!=11:continue
        require(int(m[2])==world,'partial purge marker rebound to another world')
        suffix=f'token={token} originalMemberUnchanged=1 readd=0'if m[1]=='retained'else'originalAPI=1 rawBuckets=1 rawCacheChanged=1 readd=0'
        require(m[6]==suffix,'original partial purge API/raw mutation marker differs')
        found[m[1]].append(line_number)
    require(len(found['retained'])==len(found['purged'])==1 and found['retained'][0]<found['purged'][0],
            'one actual pending retention and completed raw purge are required')
    return {k:v[0]for k,v in found.items()}


def death_receipt(rows,*,world,match,bridge_frames,canonical_payloads,native_receipts):
    # The general MOVEMENT AUTHORITY stream is intentionally sparse for empty
    # batches. This variant logs every successful65 in130..240, including the
    # no-input canonical death153. Bind that ORIGINAL row directly to both
    # independent raw wire captures; never synthesize a sparse-stream record.
    own=[x['row']for x in rows if x['row']['event']=='authority'and x['row']['canonical_frame']==153]
    bridge=[r for r in bridge_frames if(r.get('match'),r.get('frame'))==(match,153)]
    native=[r for r in native_receipts.get((1,match),[])if r['frame']==153]
    require(len(own)==len(bridge)==len(native)==1,'canonical death153 exact65/bridge/native receipt missing or repeated')
    r=own[0]
    require((r['world'],r['match'],r['slot'])==(world,match,1)and shared._hex(r['canonical_sha256'])and
        r['wire_sha256']==bridge[0]['payload_sha256']==native[0]['sha256']==canonical_payloads.get(153),
        'canonical death153 original accepted65/native/raw/server wire differs')
    return r,bridge[0]


def evaluate(log,*,attacker_log,match,commits,raw_bodies,journal,bridge_frames,canonical_payloads,canonical_states,native_states,worker_states,
             escape_check,join_check,authority_rows,cohort_trace,native_receipts,peer_bridge_frames):
    own=survivor.records(log,match,1,prefix=PREFIX,events=EVENTS)
    other=survivor.records(attacker_log,match,0,prefix=PREFIX,events=EVENTS)
    critical={n:shared._one(own,n)for n in('selected','native_dead','released','confirmed_loss','purge_observed','complete')}
    setup,dead,released,lost,purged,complete=(critical[n]['row']for n in critical)
    world=setup['world'];require({x['row']['world']for x in own}=={world},'partial purge world differs')
    samples=[x['row']for x in own if x['row']['event']in SNAPSHOTS]
    for slot,rows in((1,own),(0,other)):
        for x in rows:
            r=x['row']
            if r['event']in SNAPSHOTS:survivor.snapshot(r,slot,canonical_death=True)
            elif r['event']=='authority':require(set(r)==shared.COMMON|shared.AUTHORITY,'canonical death accepted65 schema differs')
    require(not any(x['row']['event']in('move_queued','serialized','batch_registered','selected','native_dead','released','confirmed_loss','purge_observed')for x in other),
            'no-escape host issued a command or borrowed guest lifecycle')
    require(shared._one(other,'setup')['row']['frame']==130 and shared._one(other,'complete')['row']['frame']==220,
            'no-escape host lifecycle incomplete')
    require(set(r['frame']for r in samples)==set(range(130,221))and setup['frame']==130 and complete['frame']==220,
            'partial purge dense lifecycle coverage incomplete')
    roots=('selector','manager','simulation','group_generation','group','helper','current_frame_owner','group_frame_owner')
    tokens=[m['original_token']for m in setup['members']];actors=[m['original_actor']for m in setup['members']]
    require(all(all(r[k]==setup[k]for k in roots)and[m['original_token']for m in r['members']]==tokens and
        [m['original_actor']for m in r['members']]==actors for r in samples),'partial purge original owners/leases changed')
    require(dead['frame']==153 and dead['members'][0]['native_state']==6 and released['frame']==154 and
        not released['members'][0]['native_present']and not released['members'][0]['original_active']and
        not released['members'][0]['original_retained']and not released['members'][0]['original_component']and
        released['group_ids']==[11,12]and released['group_count']==1 and released['group_victim_intent_pending']is True,
        'actual provisional disappearance did not retain the pair intent')
    require(lost['members'][0]['canonical_token']==0 and lost['confirmed_frame']>=153 and
        dead['sampled_us']<released['sampled_us']<=lost['sampled_us']<=purged['sampled_us']and
        154<=lost['frame']<=purged['frame']<=170,'canonical loss/purge chronology missing')
    for r in samples:
        if r['sampled_us']>=purged['sampled_us']:
            a,b=r['members']
            require(not a['native_present']and a['canonical_token']==a['incarnation']==0 and a['actor']is None and
                r['group_ids']==r['group_all_ids']==r['group_typed_ids']==[12]and r['group_count']==1 and
                r['group_raw_has_victim']is False and r['group_victim_intent_pending']is False and
                b['actor']==actors[1]and b['incarnation']==b['canonical_token']==tokens[1],
                'partial purge retained a ghost, lost survivor or failed acknowledgment')
    mutation=markers(log,world=world,match=match,token=tokens[0])
    require(critical['selected']['line']<mutation['retained']<critical['released']['line']<mutation['purged']<critical['purge_observed']['line'],
            'raw purge marker is not between actual pending retention and completed observation')
    context=dict(match=match,raw_bodies=raw_bodies,commits=commits,journal=journal,canonical_states=canonical_states,
                 canonical_payloads=canonical_payloads,bridge_frames=bridge_frames)
    loss_receipt,loss_bridge=death_receipt(own,world=world,match=match,bridge_frames=bridge_frames,
                                         canonical_payloads=canonical_payloads,native_receipts=native_receipts)
    require(lost['tick_ms']>=max(loss_receipt['tick_ms'],loss_bridge['received_tick_ms']),
            'group loss was claimed before canonical death authority')
    order,binding=survivor._command(log,own,context,1,canonical_death=True)
    require(order['incarnations']==[tokens[1]]and purged['sampled_us']<order['sampled_us'],
            'survivor Move lacks the original admitted lease after completed purge')
    receipt,bridge=shared.exact_receipt(log,world=world,match=match,frame=binding['canonical_frame'],bridge_frames=bridge_frames,
                                      canonical_payloads=canonical_payloads,authority_rows=authority_rows)
    confirmation=mobile._joined(join_check,worker_states,world=world,receipt=receipt,states=canonical_states,journal=journal,
                               action_hash=binding['action_sha256'],slot=1,replay=False)
    authority(native_states,canonical_states)
    native=[r for r in shared.validate_native_trace(cohort_trace,spec=survivor.SPEC)if r['world']==world]
    confirmed={r['frame']:r for r in worker_states if r['world']==world}
    require(all(f in confirmed and confirmed[f]['parsed_state_sha256']==canonical_states.get(f)for f in
        range(min(binding['assigned_frame'],binding['canonical_frame']),binding['canonical_frame']+21)),
        'survivor assigned-span/20-state continuation differs')
    poses=[dict(position=r['members'][1]['position'],sampled_us=r['members'][1]['position_sampled_us'],tick_ms=r['tick_ms'])for r in samples]
    motion=dict(entity=12,incarnation=tokens[1],render=shared.rendered_response(poses,order,member=dict(position=order['origins'][0]),receipt=receipt,bridge=bridge),
                native=shared.native_response(native,order,binding,entity=12,receipt=receipt,bridge=bridge))
    actual=[(s,shared.digest(a))for r in journal if 130<=r['frame']<=220 for s,aa in r['players'].items()for a in aa]
    require(actual==[(1,binding['action_sha256'])],'canonical death fixture has an escape/unrelated/missing command')
    return dict(passed=True,match=match,world=world,critical_rows={k:x['row']for k,x in critical.items()},
        selected_ids=[11,12],remaining_group_ids=[12],reselection_calls=0,selection_calls=1,group_assign_calls=1,
        survivor_lease_preserved=True,partial_canonical_purge=True,original_purge_marker_lines=mutation,
        death_frame=153,release_frame=154,confirmed_loss_frame=lost['frame'],purge_frame=purged['frame'],
        canonical_death_native65=loss_receipt,
        fresh=binding,fresh_native_confirmation=confirmation,members=[motion],
        all_retained_wire_triples_checked=shared.all_wire(context=context,peer_bridge_frames=peer_bridge_frames,native_receipts=native_receipts),
        escape_exercised=False,independent_correction_exercised=False,physicalUI=False,full_mobile_controls_accepted=False)


def decorate(report,episodes):
    report['cohort_canonical_death']=dict(passed=len(episodes)==2 and all(e['passed']for e in episodes),episodes=[{k:e[k]for k in
        ('passed','match','world','selected_ids','remaining_group_ids','reselection_calls','survivor_lease_preserved','partial_canonical_purge')}for e in episodes],physicalUI=False)
    report['partial_canonical_purge_witness_passed']=report['cohort_canonical_death']['passed']


def gate(plan,report):
    try:validate_cohort_survivor_plan(plan)
    except AssertionError:return False
    if plan.get('cohort_canonical_death')is not True:return False
    own=report.get('cohort_canonical_death',{});eps=own.get('episodes',[]);mobile_eps=report.get('mobile_correction',{}).get('episodes',[])
    return bool(report.get('partial_canonical_purge_witness_passed')is True and own.get('passed')is True and
        not report.get('survivor_witness_passed')and len(eps)==len(mobile_eps)==2 and
        [e.get('match')for e in eps]==[m.get('match')for m in report.get('matches',[])]and all(
        e.get('passed')is True and e.get('world')==m.get('world')and e.get('selected_ids')==[11,12]and
        e.get('remaining_group_ids')==[12]and e.get('reselection_calls')==0 and e.get('survivor_lease_preserved')is True and
        e.get('partial_canonical_purge')is True for e,m in zip(eps,mobile_eps)))
