"""Pure evidence for the exclusive two-born-Gunbot RouteA experiment.

No native query/process/input. Unity leases/tokens are supplied only by actual
client observations; native cohort rows contain native identities only.
"""
from __future__ import annotations
import hashlib,json,math,re,struct
from pathlib import Path
from server.game_data import decode_player_input
from server.protobuf_wire import get_bytes,get_repeated_bytes,get_repeated_uint,get_uint,parse_fields

PREFIX='COHORT '
MAX_ROWS=20000
EXCLUSIONS=('actor_correction','actor_mirror','terminal_timeline','expired_click','held_click','changing_rtt','transition_orders',
 'mobile_group_intent','mobile_group_user_edits','mobile_recovery_stall','mobile_recall','mobile_focus','mobile_focus_no_start',
 'mobile_focus_restart','mobile_caster_survey','mobile_caster_lifetime','mobile_ui_cast','mobile_held_click',
 'mobile_context_move','mobile_context_hold','mobile_original_hold','cohort_survivor')
def require(ok,why):
    if not ok:raise AssertionError('multi-unit evidence: '+why)
def integer(v,lo=0,hi=2**64-1):return type(v)is int and lo<=v<=hi
def digest(b):return hashlib.sha256(b).hexdigest()
def validate_plan(p):
    require('multi_unit_move'not in p or type(p['multi_unit_move'])is bool,'option must be Boolean')
    if not p.get('multi_unit_move'):return
    require(p.get('scenario')=='mobile'and p.get('mobile_correction')is True and p.get('lifecycle')=='natural'and
      type(p.get('frames'))is int and p['frames']==650 and type(p.get('expected_matches'))is int and p['expected_matches']==2 and
      type(p.get('move_slot'))is int and p['move_slot']==0 and p.get('rtt_ms')==[130,475] and p.get('native_position_trace')is None and
      all(type(p.get(k,False))is bool and not p.get(k,False)for k in EXCLUSIONS),'exclusive mobile/natural650/two-world130/475 contract differs')
    require('native_cohort_spec'not in p or p['native_cohort_spec']=='1:1:420:520:8','native cohort specification differs')
def gate(plan,report):
    if not plan.get('multi_unit_move'):return True
    try:validate_plan(plan)
    except AssertionError:return False
    own=report.get('multi_unit_move',{});eps=own.get('episodes',[]);base=report.get('mobile_correction',{}).get('episodes',[])
    return bool(report.get('multi_unit_witness_passed')is True and own.get('passed')is True and len(eps)==len(base)==2 and
      [e.get('match')for e in eps]==[e.get('match')for e in report.get('matches',[])] and all(
        e.get('passed')is True and e.get('world')==b.get('world') and e.get('rendered_members_verified')==2 and
        e.get('native_members_verified')==2 and e.get('late_remote_replay_verified')is True and e.get('continuity_verified')is True
        for e,b in zip(eps,base)))
def _unique(pairs):
    out={}
    for k,v in pairs:
        require(k not in out,'duplicate JSON key');out[k]=v
    return out
def _decode(text):
    return json.loads(text,object_pairs_hook=_unique,parse_constant=lambda x:require(False,'nonfinite JSON'))
def read_cohort_trace(path):
    p=Path(path);require(p.is_file()and p.stat().st_size<=16*1024*1024,'closed native cohort file bound')
    raw=p.read_bytes();require(raw.endswith(b'\n'),'partial closed native cohort trace')
    lines=raw.decode('utf8').splitlines();require(0<len(lines)<=8192 and all(0<len(x)<=16384 for x in lines),'native cohort row bound')
    return [_decode(x)for x in lines]
def point(v):return type(v)is list and len(v)==3 and all(type(x)in(int,float)and math.isfinite(x)for x in v)
def bits_point(p,b):
    require(point(p)and type(b)is list and len(b)==3 and all(integer(x,0,2**32-1)for x in b),'position/floatbits malformed')
    real=[struct.unpack('<f',struct.pack('<I',x))[0]for x in b]
    require(all(math.isfinite(x)for x in real)and all(struct.pack('<f',x)==struct.pack('<f',y)or x==y==0 for x,y in zip(p,real)),
      'position differs from finite original float32 bits')
    return real

def bind_move(log,order,*,slot,match,raw_bodies,commits,journal):
    """Exact normal sequence/one-action body, cohort IDs, perspective and phase."""
    sequence=order['sequence'];body=raw_bodies.get((match,slot,sequence));require(type(body)is bytes,'normal72 body missing')
    decoded=decode_player_input(body);actions=decoded['actions'];identity=decoded['identity']
    require(len(actions)==1 and identity['player_id']==slot+1 and identity['is_aliased']and not identity['ai_profile_id'],
      'normal72 human identity or one-action conservation differs')
    action=actions[0];require([f.number for f in parse_fields(action)]==[1],'command is not original Execute')
    execute=get_bytes(action,1,required=True);groups=get_repeated_bytes(execute,1)
    require(len(groups)==1 and get_uint(groups[0],1)==1 and get_uint(groups[0],2)==12 and
      tuple(sorted(get_repeated_uint(groups[0],3)))==tuple(sorted(order['source_ids'])) and
      len(get_repeated_uint(groups[0],3))==len(set(order['source_ids'])) and get_uint(execute,2)==0,
      'actual type/ability/exact cohort IDs/queued differs')
    cmd=get_bytes(execute,3,required=True);require([f.number for f in parse_fields(cmd)]==[3],'target is not ground')
    position=get_bytes(get_bytes(cmd,3,required=True),1,required=True)
    target=bits_point(order['target'],order['target_bits']);perspective=order['map_perspective']
    require(type(perspective)is int and perspective in(0,1)and order['map_perspective_source']=='Uncapped.Map.GetAlliancePerspective'and
      order['map_perspective_enum_matches_ctor']is True,'original runtime Map Perspective proof differs')
    mapped=[-v if perspective==1 and a in(0,2)else v for a,v in enumerate(target)];raw=[]
    for i,x in enumerate(mapped,1):
        n=get_uint(position,i);require(n<2**64,'target Q32 overflow');signed=n-2**64 if n>=2**63 else n
        expected=x*2**32;require(math.floor(expected)<=signed<=math.ceil(expected),'actual protocol target differs from mapped float32/one Q32 LSB')
        raw.append(signed)
    regs=[tuple(map(int,r))for r in re.findall(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) tick=(\d+) match='+re.escape(match)+r'(?:\s|$)',log)if int(r[0])==sequence]
    sends=[r for r in re.findall(r'Original command batch submitted: match='+re.escape(match)+r' sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)',log)if int(r[0])==sequence]
    require(len(regs)==len(sends)==1 and regs[0][2]>=order['tick_ms']and int(sends[0][1])==1 and int(sends[0][2])==len(body)and
      sends[0][3]==digest(body)and int(sends[0][4])>=regs[0][2],'normal67/72 receipt/body differs')
    committed=[r for r in commits if r.get('event')=='command_batch_committed'and r.get('match')==match and r.get('slot')==slot and r.get('sequence')==sequence]
    require(len(committed)==1,'canonical commit not unique');frame=committed[0]['frame'];h=digest(action)
    require([(r['frame'],s)for r in journal for s,aa in r['players'].items()for a in aa if digest(a)==h]==[(frame,slot)],'canonical action lost/duplicated/rebound')
    require(abs(regs[0][1]-frame)<=1,'actual67/canonical command phase exceeds one frame')
    return dict(sequence=sequence,action_sha256=h,body_sha256=digest(body),assigned_frame=regs[0][1],canonical_frame=frame,
      assigned_minus_canonical=regs[0][1]-frame,native67_tick_ms=regs[0][2],native72_tick_ms=int(sends[0][4]),
      protocol_target=mapped,protocol_target_q32=raw,target_quantization='original float32 target mapped by runtime Map Perspective; exact or adjacent Q32 quantum')

def validate_native_trace(rows, *, spec=None):
    """Validate copied query provenance; cached pre-restore rows are not queries."""
    require(type(rows)is list and 0<len(rows)<=8192,'native cohort count bound')
    expected=spec or dict(type=1,army=1,first_frame=420,last_frame=520,max_entities=8)
    previous_world=None;seen_worlds=[];revision=0;end_us=end_tick=-1;records={}
    fields={'schema','event','world','frame','revision','query_revision','checkpoint_base','first_divergent_frame','cohort_spec',
      'context_source','stage','head','confirmed','received','corrections','replayed_frames','query_begin_us','query_end_us',
      'query_begin_tick_ms','query_end_tick_ms','status','count','entities','record','clock_source','query_scope'}
    for index,r in enumerate(rows):
        require(type(r)is dict and r.get('record')==index and r.get('schema')==1 and integer(r.get('world'),1),'native record/world/schema differs')
        before=r.get('event')=='before_restore_cached_head'
        require(set(r)==fields|({'cached_from_record','cached_physical_head'}if before else set()),'native cohort exact fields differ')
        if r['world']!=previous_world:
            require(r['world']not in seen_worlds and len(seen_worlds)<2,'native world interleaved/overflow');seen_worlds.append(r['world']);previous_world=r['world'];revision=0
        require(r['cohort_spec']==expected and
          r['clock_source']=='python.perf_counter_ns//1000'and r['query_scope']=='existing-native-make-get-and-decode','native source/spec differs')
        require(integer(r['frame'],-1,2**31-1)and integer(r['revision'])and integer(r['count'],0,8)and
          type(r['entities'])is list and r['count']==len(r['entities']),'native count/frame invalid')
        require(r['status']in('present','empty','outside_window','no_cached_state','cached_frame_not_head'),'unknown native status')
        ids=[]
        for e in r['entities']:
            require(type(e)is dict and set(e)=={'id','type','army','position','position_bits'}and integer(e['id'],0,2**32-1)and
              e['type']==1 and e['army']==1,'native entity identity malformed');bits_point(e['position'],e['position_bits']);ids.append(e['id'])
        require(ids==sorted(set(ids))and (r['status']=='present')==bool(ids),'native sorted census/status differs')
        if before:
            revision+=1;require(r['revision']==revision and integer(r['checkpoint_base'],-1,2**31-2)and
              r['first_divergent_frame']==r['checkpoint_base']+1 and r['context_source']=='cached_query_before_restore','native invalidation revision/base differs')
            old=records.get(r['cached_from_record'])
            if r['status']in('present','empty'):
                require(old is not None and old['world']==r['world']and r['cached_physical_head']==r['frame']and
                  all(r[k]==old[k]for k in ('frame','query_revision','stage','head','confirmed','received','corrections','replayed_frames',
                    'query_begin_us','query_end_us','query_begin_tick_ms','query_end_tick_ms','entities','count','status')),'cached pre-head record/provenance differs')
            else:require(not ids,'unavailable cache invented positions')
        else:
            require(r['event']in('native_cohort_positions','after_replay_same_head')and r['context_source']=='same_decoded_native_query'and
              r['status']in('present','empty')and expected['first_frame']<=r['frame']<=expected['last_frame']and r['revision']==r['query_revision']==revision,'native actual query/event/revision differs')
            require(r['stage']in('ordinary','replay')and all(integer(r[k],-1,2**31-1)for k in ('head','confirmed','received'))and
              r['confirmed']<=r['received']and (r['frame']==r['head']+1 if r['stage']=='ordinary'else integer(r['checkpoint_base'],-1)and
              r['checkpoint_base']<r['frame']<=r['head']),'native context/frame differs')
            require(all(integer(r[k])for k in ('query_begin_us','query_end_us','query_begin_tick_ms','query_end_tick_ms','corrections','replayed_frames'))and
              end_us<=r['query_begin_us']<=r['query_end_us']and end_tick<=r['query_begin_tick_ms']<=r['query_end_tick_ms'],'native query clock regressed')
            end_us,end_tick=r['query_end_us'],r['query_end_tick_ms'];records[index]=r
    return rows

def _delta(a,b):return [x-y for x,y in zip(a,b)]
def _norm(a):return math.sqrt(sum(x*x for x in a))
def _progress(point,origin,target):
    direction=_delta(target,origin);length=_norm(direction);require(length>.25,'zero/finished target')
    return sum(x*y for x,y in zip(_delta(point,origin),direction))/length

def rendered_response(samples,order,*,member,receipt,bridge):
    """Each current actor needs its own quiet baseline and post-enqueue motion."""
    own=sorted(samples,key=lambda r:r['sampled_us']);cut=order['enqueue_sampled_us'];before=[r for r in own if r['sampled_us']<=cut]
    require(before,'per-actor baseline missing');start=next((i for i in range(len(before)-1,-1,-1)if before[-1]['sampled_us']-before[i]['sampled_us']>=200000),None)
    baseline=before[start:]if start is not None else []
    require(len(baseline)>=3 and baseline[-1]['sampled_us']-baseline[0]['sampled_us']>=200000,'per-actor quiet baseline missing')
    origin=member['position'];require(all(_norm(_delta(r['position'],origin))<=.025 for r in baseline),'actor was moving before cohort command')
    moving=[r for r in own if r['sampled_us']>cut and r['tick_ms']<min(receipt['tick_ms'],bridge['received_tick_ms'])and
      _progress(r['position'],origin,order['target'])>.025]
    require(moving,'one cohort actor has no actual targetward render response before both authority receipts')
    first=moving[0]
    return dict(response_ms=(first['sampled_us']-cut)/1000,first_sampled_us=first['sampled_us'],origin=origin,first_position=first['position'],target=order['target'],
      before_native65_ms=receipt['tick_ms']-first['tick_ms'],before_raw_bridge_ms=bridge['received_tick_ms']-first['tick_ms'],baseline_samples=len(baseline))

def native_response(rows,order,binding,*,entity,receipt,bridge):
    own=[r for r in rows if r['event']!='before_restore_cached_head'and r['stage']=='ordinary'and any(e['id']==entity for e in r['entities'])]
    baseline=[r for r in own if r['frame']<binding['assigned_frame']and r['query_end_us']<=order['enqueue_sampled_us']]
    require(baseline,'native per-ID precommand query missing');base=baseline[-1];origin=next(e['position']for e in base['entities']if e['id']==entity)
    found=[]
    for r in own:
        if r['frame']<binding['assigned_frame']or r['query_begin_us']<order['enqueue_sampled_us']or r['query_end_tick_ms']>=min(receipt['tick_ms'],bridge['received_tick_ms']):continue
        pos=next(e['position']for e in r['entities']if e['id']==entity)
        if _progress(pos,origin,binding['protocol_target'])>.025:found.append(r)
    require(found,'one cohort actor has no actual native targetward response before BOTH receipt ticks')
    first=found[0]
    return dict(baseline_record=base['record'],baseline_frame=base['frame'],origin=origin,first_position=next(e['position']for e in first['entities']if e['id']==entity),motion_record=first['record'],motion_frame=first['frame'],
      query_end_tick_ms=first['query_end_tick_ms'],before_native65_ms=receipt['tick_ms']-first['query_end_tick_ms'],
      before_raw_bridge_ms=bridge['received_tick_ms']-first['query_end_tick_ms'],clock_scope='actual GetTickCount64 query-end before both receipts; no QPC/GTC epoch inference')

COMMON={'schema','event','world','match','slot','frame','completed_frame','tick_ms','sampled_us'}
SNAPSHOT={'members','selector','manager','simulation','group_generation','current_ids','preview_ids','casting_ids','active_caster','primary','context',
 'selection_calls','group_assign_calls','selection_scope_player_initiated','history_writes','physicalUI','drag','last_click_id','click_mode','current_count','current_all_ids','current_typed_ids','group','helper','frame_owner',
 'group_ids','group_count','group_all_ids','group_typed_ids','tracked_released_ids','auto_type1'}
MEMBER={'id','unit_type','army','incarnation','canonical_token','actor','native_state','admitted','initialized','position','position_bits','position_sampled_us','jobs_joined'}
def ptr(p,nullable=False):return p is None if nullable and p is None else type(p)is str and re.fullmatch('[0-9a-fA-F]{1,16}',p)is not None and int(p,16)>0
def ids(value):return type(value)is list and len(value)<=8 and all(integer(x,0,2**32-1)for x in value)and len(value)==len(set(value))
def parse_rows(log,*,slot,matches):
    require(type(log)is str and len(log.encode('utf8'))<=64*1024*1024,'client log bound')
    result=[];last_us=last_tick=-1
    for line_number,line in enumerate(log.splitlines(),1):
        if PREFIX not in line:continue
        raw=line.split(PREFIX,1)[1];require(0<len(raw)<=16384,'cohort line bound');r=_decode(raw)
        require(type(r)is dict and COMMON<=set(r)and r['schema']==1 and r['match']in matches and r['slot']==slot and
          integer(r['world'],1)and integer(r['frame'],-1,2**31-1)and integer(r['completed_frame'],-1,2**31-1)and
          integer(r['sampled_us'])and integer(r['tick_ms'])and r['sampled_us']>=last_us and r['tick_ms']>=last_tick,'cohort common identity/clocks differ')
        last_us,last_tick=r['sampled_us'],r['tick_ms'];result.append(dict(row=r,line=line_number));require(len(result)<=MAX_ROWS,'cohort count bound')
    return result

def validate_snapshot(r,*,slot,poses):
    require(set(r)==COMMON|SNAPSHOT and type(r['members'])is list and len(r['members'])<=8,'snapshot fields/count differ')
    require(all(ptr(r[k])for k in ('selector','manager','simulation'))and integer(r['group_generation'])and
      all(ids(r[k])for k in ('current_ids','preview_ids','casting_ids'))and r['active_caster']is None and
      r['primary']is False and r['context']is False and r['drag']is False and integer(r['last_click_id'],0,2**32-1)and r['click_mode']==0 and r['history_writes']==0 and r['physicalUI']is False and
      integer(r['selection_calls'],0,1)and integer(r['group_assign_calls'],0,1),'snapshot roots/input/counters differ')
    require((r['selection_scope_player_initiated'] is False if slot==1 and r['selection_calls']==1 else
             r['selection_scope_player_initiated'] is None) and
            (slot!=0 or r['selection_calls']==r['group_assign_calls']==0),
            'original selection scope must be false only for selected victim, otherwise null')
    members=[]
    for m in r['members']:
        require(type(m)is dict and set(m)==MEMBER and integer(m['id'],0,2**32-1)and m['unit_type']==1 and m['army']==slot and
          integer(m['incarnation'],1)and m['incarnation']==m['canonical_token']and ptr(m['actor'])and integer(m['native_state'],0,2**32-1)and
          m['native_state']!=6 and m['admitted']is True and m['initialized']is True,'cohort current member lease/readiness differs')
        if poses:
            bits_point(m['position'],m['position_bits']);require(m['jobs_joined']is True and integer(m['position_sampled_us'])and
              m['position_sampled_us']<=r['sampled_us'],'original joined Transform provenance differs')
        else:require(m['position']is None and m['position_bits']is None and m['position_sampled_us']is None and m['jobs_joined']is False,'prebuild invented pose')
        members.append(m['id'])
    require(members==sorted(set(members)),'duplicate/regressing native member census')
    if slot==1 and r['selection_calls']==1:
        require(len(members)==2 and 11 in members and r['group_assign_calls']==1 and r['auto_type1']is False and
          r['current_count']==r['group_count']==2 and all(ids(r[k])and set(r[k])==set(members)for k in ('current_ids','current_all_ids','current_typed_ids','group_ids','group_all_ids','group_typed_ids'))and
          all(ptr(r[k])for k in ('group','helper','frame_owner'))and ids(r['tracked_released_ids']),'two-member current/group/type caches differ')
    else:
        require(all(r[k]is None for k in ('current_count','current_all_ids','current_typed_ids','group','helper','frame_owner','group_ids','group_count','group_all_ids','group_typed_ids','tracked_released_ids','auto_type1')),
          'unexpected group-cache proof outside victim selection')
    return r

def exact_receipt(log,*,world,match,frame,bridge_frames,canonical_payloads,authority_rows):
    own=[r for r in authority_rows(log)if(r['world'],r['match'],r['frame'])==(world,match,frame)]
    wire=[r for r in bridge_frames if(r.get('match'),r.get('frame'))==(match,frame)]
    require(len(own)==len(wire)==1 and own[0]['wire_sha256']==wire[0]['payload_sha256']==canonical_payloads.get(frame),
      'actual accepted65/rawbridge/authority wire missing/differs')
    return own[0],wire[0]

def all_wire(*,context,peer_bridge_frames,native_receipts):
    match=context['match'];expected=set(context['canonical_states']);require(expected==set(range(len(expected))),'authority state frames not contiguous')
    counts=[]
    for slot,bridge in ((0,peer_bridge_frames),(1,context['bridge_frames'])):
        actual={r['frame']:r['sha256']for r in native_receipts[slot,match]};wire={r['frame']:r['payload_sha256']for r in bridge if r['match']==match};payload=context['canonical_payloads']
        require(len(actual)==len(native_receipts[slot,match])and set(actual)==set(wire)==set(payload)==expected and
          all(actual[f]==wire[f]==payload[f]for f in expected),'full retained native65/rawbridge/server wire differs')
        counts.append(len(expected))
    return sum(counts)

ORDER={'source_ids','incarnations','origins','origins_sampled_us','target','target_bits','command','command_class','queued','ability','queue_before','queue_after',
 'originalCtor','original_callback','enqueue_sampled_us','local_alliance','map_perspective','map_perspective_source','map_perspective_enum','map_perspective_enum_matches_ctor',
 'map_perspective_normal','map_perspective_flipped','map_perspective_value_name','physicalUI'}
SERIAL={'command','action','sequence','source_next_frame','action_index','physicalUI'}
REGISTERED={'command','action','sequence','speculative_frame','action_index','action_sha256','body_sha256','physicalUI'}
AUTHORITY={'canonical_frame','wire_sha256','canonical_sha256','physicalUI'}
def _one(rows,event):
    selected=[r for r in rows if r['row']['event']==event];require(len(selected)==1,'missing/duplicate '+event);return selected[0]
def _hex(value):return type(value)is str and re.fullmatch('[a-f0-9]{64}',value)is not None

def _build(log,pre,selected,*,slot,match,raw_bodies,journal,commits):
    text='\n'.join(log.splitlines()[pre['line']:selected['line']-1])
    found=re.findall(r'LAN NORMAL BUILD smoke frame250 slot(\d+) army(\d+) HQ(\d+) deckSlot(\d+) unitType(\d+) ability(\d+) cost=\((\d+),(\d+)\) prerequisite=1 queued=1 commandQueueDelta=1 presentedFrame=(\d+)(?:\s|$)',text)
    require(len(found)==1,'one original legal Build250 receipt missing/duplicate')
    owner,army,hq,deck,unit,ability,primary,secondary,presented=map(int,found[0]);require(owner==army==slot and deck==0 and unit==1 and
      250<=presented<selected['row']['frame'],'Build250 is not own legal deckslot0 Gunbot before selection')
    candidates=[]
    for (m,s,seq),body in raw_bodies.items():
        if(m,s)!=(match,slot):continue
        d=decode_player_input(body)
        for a in d['actions']:
            ex=get_bytes(a,1)
            if not ex:continue
            gg=get_repeated_bytes(ex,1)
            if len(gg)==1 and get_uint(gg[0],2)==ability:
                require(len(d['actions'])==1 and d['identity']['player_id']==slot+1 and d['identity']['is_aliased']and not d['identity']['ai_profile_id']and get_uint(gg[0],1)==3 and get_repeated_uint(gg[0],3)==(hq,)and get_uint(ex,2)==0,'Build serialized source/group/queue differs')
                candidates.append((seq,digest(a)))
    require(len(candidates)==1,'Build250 action not unique');seq,h=candidates[0]
    occ=[(r['frame'],s)for r in journal for s,aa in r['players'].items()for a in aa if digest(a)==h]
    require(len(occ)==1 and occ[0][1]==slot and 250<occ[0][0]<selected['row']['frame'],'original Build canonical frame/body missing or not before readiness')
    committed=[r for r in commits if r.get('event')=='command_batch_committed'and(r.get('match'),r.get('slot'),r.get('sequence'))==(match,slot,seq)]
    require(len(committed)==1 and committed[0]['frame']==occ[0][0],'Build normal sequence/canonical journal differs')
    body=raw_bodies[match,slot,seq]
    regs=[tuple(map(int,r))for r in re.findall(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) tick=(\d+) match='+re.escape(match)+r'(?:\s|$)',log)if int(r[0])==seq]
    sends=[r for r in re.findall(r'Original command batch submitted: match='+re.escape(match)+r' sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)',log)if int(r[0])==seq]
    require(len(regs)==len(sends)==1 and abs(regs[0][1]-occ[0][0])<=1 and int(sends[0][1])==1 and
      int(sends[0][2])==len(body)and sends[0][3]==digest(body)and int(sends[0][4])>=regs[0][2]and int(sends[0][5])==250,
      'Build normal67/72/body/request source250/phase differs')
    return dict(sequence=seq,action_sha256=h,body_sha256=digest(body),canonical_frame=occ[0][0],assigned_frame=regs[0][1],
      assigned_minus_canonical=regs[0][1]-occ[0][0],request_source_next_frame=250,presented_after_return=presented,
      native67_tick_ms=regs[0][2],native72_tick_ms=int(sends[0][4]),slot=slot,deck_slot=0,ability=ability,hq=hq,unit_type=1,
      prediction_scope='Nonpredicted Build; source request250, after-return presentation and actual assigned/canonical frames recorded separately')

def _command(log,rows,*,slot,context):
    queued=_one(rows,'move_queued');serial=_one(rows,'serialized');registered=_one(rows,'batch_registered')
    q,s,r=queued['row'],serial['row'],registered['row'];require(set(q)==COMMON|ORDER and set(s)==COMMON|SERIAL and set(r)==COMMON|REGISTERED,'command evidence fields differ')
    require(q['frame']==(440 if slot==1 else 460)and q['ability']==12 and q['queued']is False and q['queue_before']==0 and q['queue_after']==1 and
      q['originalCtor']is True and q['physicalUI']is False and q['command_class']=='Uncapped.ExecuteTargetGroundCommand'and
      q['original_callback']=='Uncapped.ExecuteTargetGroundCommand..ctor'and ptr(q['command'])and ids(q['source_ids'])and
      len(q['source_ids'])==(2 if slot==1 else 1)and len(q['incarnations'])==len(q['origins'])==len(q['origins_sampled_us'])==len(q['source_ids'])and
      all(integer(n,1)for n in q['incarnations'])and all(point(p)for p in q['origins'])and
      all(integer(t)and t<=q['sampled_us']for t in q['origins_sampled_us'])and q['enqueue_sampled_us']>=q['sampled_us'],'original queued Move/identity/QPC differs')
    from tools.prediction_mobile_evidence import _perspective
    _perspective(q)
    require(queued['line']<serial['line']<registered['line']and q['enqueue_sampled_us']<=s['sampled_us']<=r['sampled_us']and
      s['command']==r['command']==q['command']and ptr(s['action'])and s['action']==r['action']and
      s['sequence']==r['sequence']and integer(r['sequence'],1)and s['action_index']==r['action_index']==0 and
      integer(s['source_next_frame'],0,2**31-1)and s['physicalUI']is r['physicalUI']is False,'normal same-ICommand/action serializer/67 ordering differs')
    q=dict(q,sequence=r['sequence']);binding=bind_move(log,q,slot=slot,match=context['match'],raw_bodies=context['raw_bodies'],commits=context['commits'],journal=context['journal'])
    require(r['speculative_frame']==binding['assigned_frame']and r['body_sha256']==binding['body_sha256']and r['action_sha256']==binding['action_sha256'],'passive normal67 captured bytes/action differs')
    return q,binding

def evaluate(*,contexts,cohort_trace,worker_states,mobile_episodes,native_receipts,peer_bridge_frames,authority_rows,join_check):
    require(len(contexts)==len(mobile_episodes)==2 and all(x.get('passed')is True for x in mobile_episodes),'both unchanged early mobile episodes required')
    native=validate_native_trace(cohort_trace);matches=[c['match']for c in contexts]
    require(len(set(matches))==2,'two unique matches required')
    parsed={slot:parse_rows(contexts[0]['log'if slot==1 else'attacker_log'],slot=slot,matches=matches)for slot in(0,1)}
    episodes=[];wire_count=0
    for ctx,base in zip(contexts,mobile_episodes):
        match=ctx['match'];world=base['world'];require(base['match']==match,'early mobile world/match differs')
        own={slot:[x for x in parsed[slot]if x['row']['match']==match]for slot in(0,1)};all_orders={};builds=[];censuses={};selected_by_slot={}
        for slot,log in ((0,ctx['attacker_log']),(1,ctx['log'])):
            rows=own[slot];require(rows and {x['row']['world']for x in rows}=={world},'cohort evidence world differs from native BEGIN')
            for x in rows:
                r=x['row'];ev=r['event']
                if ev in('prebuild','selected','sample','complete'):validate_snapshot(r,slot=slot,poses=ev!='prebuild')
                elif ev=='authority':require(set(r)==COMMON|AUTHORITY and 400<=r['canonical_frame']<=540 and _hex(r['wire_sha256'])and _hex(r['canonical_sha256'])and r['physicalUI']is False,'accepted65 diagnostic differs')
                else:require(ev in('move_queued','serialized','batch_registered'),'unknown cohort event')
            pre=_one(rows,'prebuild');selected=_one(rows,'selected');complete=_one(rows,'complete');p,a,z=pre['row'],selected['row'],complete['row']
            require(p['frame']==249 and a['frame']==420 and z['frame']==520 and pre['line']<selected['line']<complete['line'],'census/selection/completion frames/order differ')
            before=[m['id']for m in p['members']];after=[m['id']for m in a['members']];born=set(after)-set(before)
            require(before==([11]if slot==1 else[])and len(born)==1 and len(after)==(2 if slot==1 else 1)and
              all(m['native_state']==0 for m in a['members']),'actual unique native-ready Gunbot birth differs')
            censuses[slot]=dict(before=before,selected=after,born=next(iter(born)));selected_by_slot[slot]=a
            snapshots=[x['row']for x in rows if x['row']['event']in('selected','sample','complete')]
            require(set(r['frame']for r in snapshots)==set(range(420,521)),'cohort current/cache frame observations missing')
            identities=[(m['id'],m['incarnation'],m['actor'])for m in a['members']]
            for row in snapshots:
                require([(m['id'],m['incarnation'],m['actor'])for m in row['members']]==identities and
                  all(row[k]==a[k]for k in ('selector','manager','simulation','group_generation')),'cohort current identity/owner changed')
                if slot==1:require(all(row[k]==a[k]for k in ('group','helper','frame_owner'))and row['selection_calls']==row['group_assign_calls']==1,'cohort selection/group recreated or reselected')
            builds.append(_build(log,pre,selected,slot=slot,match=match,raw_bodies=ctx['raw_bodies'],journal=ctx['journal'],commits=ctx['commits']))
            q,b=_command(log,rows,slot=slot,context=ctx);require(q['source_ids']==after and q['incarnations']==[m['incarnation']for m in a['members']],'command rebound from selected cohort')
            all_orders[slot]=(q,b)
        order,binding=all_orders[1];remote,remote_binding=all_orders[0]
        own65,ownbridge=exact_receipt(ctx['log'],world=world,match=match,frame=binding['canonical_frame'],bridge_frames=ctx['bridge_frames'],canonical_payloads=ctx['canonical_payloads'],authority_rows=authority_rows)
        late65,latebridge=exact_receipt(ctx['log'],world=world,match=match,frame=remote_binding['canonical_frame'],bridge_frames=ctx['bridge_frames'],canonical_payloads=ctx['canonical_payloads'],authority_rows=authority_rows)
        for canonical,receipt in ((binding['canonical_frame'],own65),(remote_binding['canonical_frame'],late65)):
            caught=[x['row']for x in own[1]if x['row']['event']=='authority'and x['row']['canonical_frame']==canonical]
            require(len(caught)==1 and caught[0]['wire_sha256']==receipt['wire_sha256']and caught[0]['canonical_sha256']==receipt['canonical_sha256'],
              'cohort actual accepted65 receipt missing/different')
        require(remote_binding['canonical_frame']>binding['canonical_frame']>420 and late65['tick_ms']>remote['tick_ms']and
          latebridge['received_tick_ms']>remote['tick_ms'],'NEW late remote correction missing/early')
        from tools.prediction_mobile_evidence import _joined
        replay=_joined(join_check,worker_states,world=world,receipt=late65,states=ctx['canonical_states'],journal=ctx['journal'],action_hash=remote_binding['action_sha256'],slot=0,replay=True,latest_tick=_one(own[1],'complete')['row']['tick_ms'])
        native_own=[r for r in native if r['world']==world];require(native_own,'native trace lacks cohort world')
        confirmed={r['frame']:r for r in worker_states if r['world']==world}
        span=range(min(binding['assigned_frame'],binding['canonical_frame']),binding['canonical_frame']+21)
        require(all(f in confirmed and confirmed[f]['parsed_state_sha256']==ctx['canonical_states'].get(f)for f in span),
          'cohort assigned/canonical command span plus20 native hashes differs')
        responses=[];samples=[r['row']for r in own[1]if r['row']['event']in('selected','sample','complete')]
        for index,member in enumerate(selected_by_slot[1]['members']):
            poses=[dict(position=next(m['position']for m in row['members']if m['id']==member['id']),sampled_us=next(m['position_sampled_us']for m in row['members']if m['id']==member['id']),tick_ms=row['tick_ms'])for row in samples]
            original_member=dict(member,position=order['origins'][index]);render=rendered_response(poses,order,member=original_member,receipt=own65,bridge=ownbridge)
            nr=native_response(native_own,order,binding,entity=member['id'],receipt=own65,bridge=ownbridge)
            responses.append(dict(entity=member['id'],unit_type=1,army=1,incarnation=member['incarnation'],render=render,native=nr))
        expected={(0,base['escape']['action_sha256']),(1,base['fresh']['action_sha256']),*( (b['slot'],b['action_sha256'])for b in builds),
          (1,binding['action_sha256']),(0,remote_binding['action_sha256'])}
        actual=[(s,digest(a))for row in ctx['journal']if 130<=row['frame']<=520 for s,aa in row['players'].items()for a in aa]
        require(len(actual)==len(expected)and set(actual)==expected,'unexpected/missing original action in exclusive130..520 route')
        wire_count+=all_wire(context=ctx,peer_bridge_frames=peer_bridge_frames,native_receipts=native_receipts)
        formations=[dict(frame=r['frame'],sampled_us=r['sampled_us'],offset=_delta(r['members'][1]['position'],r['members'][0]['position']),
          separation=_norm(_delta(r['members'][1]['position'],r['members'][0]['position'])))for r in samples]
        episodes.append(dict(passed=True,match=match,world=world,census=censuses,builds=builds,move=binding,remote_move=remote_binding,
          members=responses,rendered_members_verified=2,native_members_verified=2,late_remote_replay_verified=True,late_native_replay=replay,
          formation=dict(selected=formations[0],complete=formations[-1],minimum_observed_separation=min(r['separation']for r in formations)),
          continuity_verified=True,selection_calls=1,group_assign_calls=1,cache_observed_frames=101,
          actual_tracked_released_observations=sorted({tuple(r['tracked_released_ids'])for r in samples}),
          collision_exercised=False,type_change_retirement_exercised=False,physicalUI=False))
    return dict(passed=True,episodes=episodes,all_retained_wire_triples_checked=wire_count,physicalUI=False,full_feature_accepted=False,
      scope='Original Build and scripted two-ID selection/constructor; each original Unity and native response, NEW remote correction+20, observed cache continuity; no collision/type change/physical-input claim')
