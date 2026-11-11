"""Pure evidence for original scripted88 -> queued12 dependency integration.

No process/native/input action is performed here. The original ordinary fixture,
constructors, observed queueing and native/render/wire timelines are supplied.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct

from server.game_data import decode_player_input
from server.protobuf_wire import get_bytes, get_repeated_bytes, get_repeated_uint, get_uint, parse_fields
from tools import prediction_close_formation_evidence as close
from tools import prediction_multi_unit_evidence as shared
from tools import prediction_mobile_evidence as mobile
from tools.prediction_close_formation_fixture import metadata

PREFIX = 'QUEUED ORDERS '
IDS = close.IDS
SPEC = dict(type=1,army=1,first_frame=280,last_frame=420,max_entities=8)
TARGETS = {'target_a','target_a_bits','target_b','target_b_bits'}
SNAPSHOTS = {'setup','selected','sample','single_selected','targets_frozen','complete'}
EVENTS = SNAPSHOTS | {'move_queued','serialized','batch_registered','authority'}
EXCLUSIONS = (*close.EXCLUSIONS,'close_formation')
SCOPE = ('Original scripted88 then queued12 on one confirmed Gunbot after original4-to1 selection; '
    'no prematureB, native/render A-first then actual B turn+20, continuous manual4, real replay and full state/wire/natural lifecycle; '
    'no physical Shift, UI activation, hidden queue or collision-solver acceptance')


def require(ok,why):
    if not ok: raise AssertionError('queued-orders evidence: '+why)


def scope(plan):
    return SCOPE if plan.get('queued_orders') else None


def validate_plan(plan):
    require(type(plan.get('queued_orders',False)) is bool,'option must be Boolean')
    require(plan.get('scenario') != 'queued-orders' or plan.get('queued_orders') is True,'scenario requires explicit option')
    if not plan.get('queued_orders'): return
    require(plan.get('scenario') == 'queued-orders' and plan.get('lifecycle') == 'natural' and
        type(plan.get('frames')) is int and plan['frames'] == 650 and
        type(plan.get('expected_matches')) is int and plan['expected_matches'] == 2 and
        type(plan.get('move_slot')) is int and plan['move_slot'] == 0 and
        type(plan.get('rtt_ms')) is list and len(plan['rtt_ms']) == 2 and
        all(type(v) in (int,float) and math.isfinite(v) and v == expected for v,expected in zip(plan['rtt_ms'],(130,475))) and
        plan.get('native_position_trace') is plan.get('actor_fixture') is None and
        plan.get('generic_movement_not_exercised') is True and
        type(plan.get('surrender_frame')) is int and plan['surrender_frame'] == 700 and
        plan.get('native_cohort_spec') == '1:1:280:420:8' and
        close._exact(plan.get('queued_orders_fixture'),metadata()) and plan.get('queued_orders_scope') == SCOPE and
        all(type(plan.get(k,False)) is bool and not plan.get(k,False) for k in EXCLUSIONS),'exclusive ordinary650/two130475/slot0/Concede700 fixture differs')


def option(args,frames,position_trace):
    selected = args.scenario == 'queued-orders'
    surrender = getattr(args,'surrender_frame',None)
    plan = dict(queued_orders=selected,scenario=args.scenario,lifecycle=args.lifecycle,frames=frames,
        expected_matches=2 if args.lifecycle == 'natural' else 1,move_slot=args.move_slot,rtt_ms=list(args.rtt_ms),
        native_position_trace=position_trace,actor_fixture=None,generic_movement_not_exercised=True,
        surrender_frame=700 if surrender is None else surrender,native_cohort_spec='1:1:280:420:8',
        queued_orders_fixture=metadata(),queued_orders_scope=SCOPE,**{k:getattr(args,k,False) for k in EXCLUSIONS})
    validate_plan(plan); return selected


def native_observation(state,parsed_sha):
    require(type(state) is dict and shared.integer(state.get('frame'),0,2**31-1),'actual native frame missing')
    if not 130 <= state['frame'] <= 440: return None
    require(state.get('viewer') == 31 and type(state.get('entities')) is list and type(state.get('game_state')) is dict and
        shared._hex(parsed_sha) and parsed_sha == hashlib.sha256(json.dumps({k:v for k,v in state.items() if k != 'raw_sha256'},
        sort_keys=True,separators=(',',':')).encode()).hexdigest(),'actual full Spectator31/hash differs')
    people = []
    for identity in [10]+IDS:
        found = [r for r in state['entities'] if type(r) is dict and r.get('id') == identity]
        require(len(found) == 1,'actual native participant missing/duplicate')
        row = found[0]
        require(all(k in row for k in ('id','type','army','max_health','current_damage','position')) and
            type(row['id']) is int and type(row['type']) is int and row['type'] == 1 and type(row['army']) is int and
            row['army'] == (0 if identity == 10 else 1) and shared.point(row['position']),'actual native identity/position differs')
        position = list(struct.unpack('<fff',struct.pack('<fff',*row['position'])))
        require(position == row['position'],'decoded native position is not Single')
        people.append({k:row[k] for k in ('id','type','army','max_health','current_damage')} | dict(position=position))
    return dict(frame=state['frame'],parsed_state_sha256=parsed_sha,participants=people,game_state=dict(state['game_state']))


def records(log,slot,matches):
    require(type(log) is str and len(log.encode()) <= 64*1024*1024,'closed log bound')
    result=[]; us=tick=-1
    for number,line in enumerate(log.splitlines(),1):
        if PREFIX not in line: continue
        raw=line.split(PREFIX,1)[1]; require(0 < len(raw) <= 16384,'row bound')
        row=shared._decode(raw)
        require(type(row) is dict and close.COMMON <= set(row) and type(row['schema']) is int and row['schema'] == 1 and
            row['event'] in EVENTS and row['match'] in matches and type(row['slot']) is int and row['slot'] == slot and
            shared.integer(row['world'],1) and shared.integer(row['frame'],-1,2**31-1) and
            shared.integer(row['completed_frame'],row['frame'],2**31-1) and shared.integer(row['sampled_us']) and
            shared.integer(row['tick_ms']) and row['sampled_us'] >= us and row['tick_ms'] >= tick and row['physicalUI'] is False,
            'row owner/source clocks differ')
        command=row['event'] in ('move_queued','serialized','batch_registered')
        require((slot == 1 and row['order_tag'] in ('approach','first','queued')) if command else row['order_tag'] is None,'tag/seat differs')
        us,tick=row['sampled_us'],row['tick_ms']; result.append(dict(row=row,line=number))
        require(len(result) <= 20000,'row budget')
    return result


def snapshot(row,slot):
    extra=TARGETS if row['event'] == 'targets_frozen' else set()
    require(set(row) == close.COMMON | close.SNAPSHOT | extra and type(row['members']) is list and
        [r.get('id') for r in row['members']] == (IDS if slot else [10]),'snapshot fields/roster differs')
    require(all(shared.ptr(row[k]) for k in ('selector','manager','simulation','current_frame_owner')) and
        shared.integer(row['group_generation']) and all(shared.ids(row[k]) for k in
        ('current_ids','preview_ids','casting_ids','current_all_ids','current_typed_ids')) and
        row['current_ids'] == row['current_all_ids'] and shared.integer(row['current_count'],0,8) and
        row['active_caster'] is None and row['primary'] is row['context'] is row['drag'] is False and not row['casting_ids'] and
        shared.integer(row['pending_commands'],0,1) and shared.integer(row['last_click_id'],0,2**32-1) and
        type(row['click_mode']) is int and row['click_mode'] == 0 and type(row['history_writes']) is int and row['history_writes'] == 0,
        'snapshot roots/input/queue differs')
    for member in row['members']:
        require(set(member) == close.MEMBER and type(member['unit_type']) is int and member['unit_type'] == 1 and
            type(member['army']) is int and member['army'] == slot and shared.integer(member['original_token'],1) and
            type(member['incarnation']) is type(member['canonical_token']) is int and
            member['incarnation'] == member['canonical_token'] == member['original_token'] and
            shared.ptr(member['original_actor']) and member['actor'] == member['original_actor'] and
            member['native_present'] is member['admitted'] is member['initialized'] is member['jobs_joined'] is True and
            shared.integer(member['native_state'],0,2**32-2) and member['native_state'] != 6 and
            shared.integer(member['position_sampled_us']) and member['position_sampled_us'] <= row['sampled_us'],
            'member original live initialized confirmed lease differs')
        shared.bits_point(member['position'],member['position_bits'])
    require(len({m['actor'] for m in row['members']}) == len(row['members']),'duplicate actor')
    if slot:
        single=row['frame'] >= 290; expected={11} if single else set(IDS)
        require(type(row['selection_calls']) is type(row['group_assign_calls']) is int and
            row['selection_calls'] == (2 if single else 1) and row['group_assign_calls'] == 1 and
            row['selection_scope_player_initiated'] is False and row['current_count'] == len(expected) and
            all(set(row[k]) == expected for k in ('current_ids','current_all_ids','current_typed_ids')) and
            all(shared.ptr(row[k]) for k in ('group','helper','group_frame_owner')) and
            row['group_frame_owner'] == row['current_frame_owner'] and type(row['group_count']) is int and row['group_count'] == 4 and
            all(shared.ids(row[k]) and set(row[k]) == set(IDS) for k in ('group_ids','group_all_ids','group_typed_ids')) and
            row['tracked_released_ids'] == [] and row['auto_type1'] is False,'intentional current4-to1/manualgroup4 contract differs')
    else:
        require(row['selection_calls'] == row['group_assign_calls'] == 0 and row['selection_scope_player_initiated'] is None and
            all(row[k] is None for k in ('group','helper','group_ids','group_count','group_all_ids','group_typed_ids','group_frame_owner','tracked_released_ids','auto_type1')),
            'host selection/group changed')


def _one(rows,event,tag=None):
    return close._one(rows,event,tag)


def _queue_intervals(rows):
    pending=None
    for item in rows:
        row=item['row']
        if row['event'] in SNAPSHOTS:
            require(row['pending_commands'] == int(pending is not None),'unexplained pending ICommand count')
        elif row['event'] == 'move_queued':
            require(pending is None,'overlapping pending ICommands'); pending=row['order_tag']
        elif row['event'] == 'serialized':
            require(pending == row['order_tag'],'serializer has no matching pending command'); pending=None
    require(pending is None,'command never drained')


def _command(log,rows,tag,context):
    queued,serial,registered=(_one(rows,name,tag) for name in ('move_queued','serialized','batch_registered'))
    q,s,r=(item['row'] for item in (queued,serial,registered))
    at,ability,is_queued,sources={'approach':(180,12,False,IDS),'first':(300,88,False,[11]),'queued':(302,12,True,[11])}[tag]
    require(set(q) == close.COMMON | shared.ORDER and set(s) == close.COMMON | shared.SERIAL and
        set(r) == close.COMMON | shared.REGISTERED,'command field set differs')
    require(q['frame'] == at and q['source_ids'] == sources and type(q['ability']) is int and q['ability'] == ability and
        q['queued'] is is_queued and q['originalCtor'] is True and q['command_class'] == 'Uncapped.ExecuteTargetGroundCommand' and
        q['original_callback'] == 'Uncapped.ExecuteTargetGroundCommand..ctor' and shared.ptr(q['command']) and
        type(q['queue_before']) is type(q['queue_after']) is int and (q['queue_before'],q['queue_after']) == (0,1) and
        len(q['incarnations']) == len(q['origins']) == len(q['origins_sampled_us']) == len(sources) and
        all(shared.integer(v,1) for v in q['incarnations']) and all(shared.point(p) for p in q['origins']) and
        all(shared.integer(t) and t <= q['sampled_us'] for t in q['origins_sampled_us']) and
        shared.integer(q['enqueue_sampled_us']) and q['enqueue_sampled_us'] >= q['sampled_us'],'original command source/queue/frame differs')
    mobile._perspective(q)
    require(q['map_perspective'] == 1 and queued['line'] < serial['line'] < registered['line'] and
        q['enqueue_sampled_us'] <= s['sampled_us'] <= r['sampled_us'] and q['command'] == s['command'] == r['command'] and
        shared.ptr(s['action']) and s['action'] == r['action'] and shared.integer(s['sequence'],1) and s['sequence'] == r['sequence'] and
        type(s['action_index']) is type(r['action_index']) is int and s['action_index'] == r['action_index'] == 0 and
        shared.integer(s['source_next_frame'],0,2**31-1),'original ToProto/67 pointer/ordinal/order differs')
    sequence=r['sequence']; body=context['raw_bodies'].get((context['match'],1,sequence))
    require(type(body) is bytes,'normal raw67/72 player body missing')
    decoded=decode_player_input(body); identity=decoded['identity']; actions=decoded['actions']
    require(len(actions) == 1 and identity['player_id'] == 2 and identity['is_aliased'] and not identity['ai_profile_id'],'original one-action human identity differs')
    action=actions[0]; require([f.number for f in parse_fields(action)] == [1],'original action is not Execute')
    execute=get_bytes(action,1,required=True); groups=get_repeated_bytes(execute,1)
    require(len(groups) == 1 and get_uint(groups[0],1) == 1 and get_uint(groups[0],2) == ability and
        sorted(get_repeated_uint(groups[0],3)) == sorted(sources) and len(get_repeated_uint(groups[0],3)) == len(sources) and
        get_uint(execute,2) == int(is_queued),'original body ability/queued/source IDs differ')
    command=get_bytes(execute,3,required=True)
    require([f.number for f in parse_fields(command)] == [3],'original target is not Ground')
    position=get_bytes(get_bytes(command,3,required=True),1,required=True)
    target=shared.bits_point(q['target'],q['target_bits']); mapped=[-v if axis in (0,2) else v for axis,v in enumerate(target)]
    for axis,value in enumerate(mapped,1):
        wire=get_uint(position,axis); require(wire < 2**64,'Q32 overflow')
        signed=wire-2**64 if wire >= 2**63 else wire
        require(math.floor(value*2**32) <= signed <= math.ceil(value*2**32),'original mapped target/Q32 differs')
    regs=[tuple(map(int,v)) for v in re.findall(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) tick=(\d+) match='+re.escape(context['match'])+r'(?:\s|$)',log) if int(v[0]) == sequence]
    sends=[v for v in re.findall(r'Original command batch submitted: match='+re.escape(context['match'])+r' sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)',log) if int(v[0]) == sequence]
    sha=shared.digest(action); body_sha=shared.digest(body)
    commits=[v for v in context['commits'] if (v.get('event'),v.get('match'),v.get('slot'),v.get('sequence')) == ('command_batch_committed',context['match'],1,sequence)]
    require(len(regs) == len(sends) == len(commits) == 1 and regs[0][2] >= q['tick_ms'] and int(sends[0][1]) == 1 and
        int(sends[0][2]) == len(body) and sends[0][3] == body_sha and int(sends[0][4]) >= regs[0][2] and
        int(sends[0][5]) == s['source_next_frame'] and
        [(v['frame'],slot) for v in context['journal'] for slot,values in v['players'].items() for a in values if shared.digest(a) == sha] == [(commits[0]['frame'],1)] and
        abs(regs[0][1]-commits[0]['frame']) <= 1 and abs(commits[0]['frame']-(at+1)) <= 1 and
        r['speculative_frame'] == regs[0][1] and r['action_sha256'] == sha and r['body_sha256'] == body_sha,'normal67/72/canonical bytes, uniqueness or phase differs')
    return dict(q,sequence=sequence),dict(sequence=sequence,action_sha256=sha,body_sha256=body_sha,assigned_frame=regs[0][1],
        canonical_frame=commits[0]['frame'],assigned_minus_canonical=regs[0][1]-commits[0]['frame'],native67_tick_ms=regs[0][2],
        native72_tick_ms=int(sends[0][4]),registered_sampled_us=r['sampled_us'],protocol_target=mapped,ability=ability,queued=is_queued)


def _turn(rows,origin,first_target,second_target):
    """Find actual sustained direction change, never progress from old origin."""
    by={r['frame']:r for r in rows}; frames=sorted(by)
    for f in frames:
        if not all(k in by for k in range(f-1,f+3)): continue
        prior=[r for r in rows if r['frame'] < f]
        if not prior or max(shared._progress(r['position'],origin,first_target) for r in prior) < 12.: continue
        if all(shared._progress(by[k]['position'],by[k-1]['position'],second_target) > .025 for k in range(f,f+3)):
            return dict(frame=f,last_frame=f+2,first=by[f],last=by[f+2])
    require(False,'actual B turn lacks three consecutive frame displacements after A travel')


def _joined(check,rows,receipt,context,*,replay=False,required=None,allowed=(),latest_tick=None):
    result=check(rows,world=receipt['world'],authority=receipt,canonical_states=context['canonical_states'],require_replay=replay)
    indices=result.get('promotion_group_row_indices'); tail=result.get('continuation_row_indices')
    require(type(indices) is list and indices and len(indices) == len(set(indices)) and all(shared.integer(i,0,len(rows)-1) for i in indices) and
        type(tail) is list and len(tail) == 20 and all(shared.integer(i,0,len(rows)-1) for i in tail),'confirmed group/20 row indices invalid')
    group=[rows[i] for i in indices]; numbers=[r['frame'] for r in group]
    require(numbers == list(range(min(numbers),max(numbers)+1)) and receipt['frame'] in numbers and
        all(r['world'] == receipt['world'] and r['parsed_state_sha256'] == context['canonical_states'].get(r['frame']) and
            r['tick_ms'] >= receipt['tick_ms'] and (latest_tick is None or r['tick_ms'] <= latest_tick) for r in group) and
        (not replay or sum(r['replayed_frames_delta'] for r in group) > 0),'own receipt/hash/real replay group differs')
    actual=[(r['frame'],slot,shared.digest(a)) for r in context['journal'] if r['frame'] in numbers for slot,aa in r['players'].items() for a in aa]
    require(all(item in allowed for item in actual) and (required is None or actual.count(required) == 1),'replay is not bound to exact own A action/prefix')
    continuations=[rows[i] for i in tail]
    require([r['frame'] for r in continuations] == list(range(max(numbers)+1,max(numbers)+21)) and
        all(r['world'] == receipt['world'] and r['parsed_state_sha256'] == context['canonical_states'].get(r['frame']) and
            r['tick_ms'] >= group[-1]['tick_ms'] and (latest_tick is None or r['tick_ms'] <= latest_tick) for r in continuations),
        '20 native continuations after the actual episode missing/mismatched')
    return dict(result,group=group,input_actions=actual)


def _authority(rows,states):
    require(type(rows) is list and [r.get('frame') for r in rows] == list(range(130,441)),'actual native authority window incomplete')
    for row in rows:
        require(set(row) == {'frame','parsed_state_sha256','participants','game_state'} and row['parsed_state_sha256'] == states.get(row['frame']) and
            row['game_state'].get('complete') is False and [p.get('id') for p in row['participants']] == [10]+IDS,'actual authority full hash/roster/terminal differs')
        for p in row['participants']:
            require(set(p) == {'id','type','army','max_health','current_damage','position'} and p['type'] == 1 and p['army'] == (0 if p['id'] == 10 else 1) and
                type(p['max_health']) in (int,float) and p['max_health'] == 600 and type(p['current_damage']) in (int,float) and p['current_damage'] == 0 and shared.point(p['position']),
                'ordinary participant native identity/health/position differs')
    return {r['frame']:r for r in rows}


def evaluate(*,contexts,cohort_trace,worker_states,native_receipts,peer_bridge_frames,authority_rows,join_check):
    require(type(contexts) is list and len(contexts) == 2,'two closed actual contexts required')
    matches=[c['match'] for c in contexts]
    require(len(set(matches)) == 2 and all(type(m) is str and re.fullmatch('[a-f0-9]{32}',m) for m in matches),'match identities differ')
    logs={1:contexts[0]['log'],0:contexts[0]['attacker_log']}
    require(all(c['log'] == logs[1] and c['attacker_log'] == logs[0] for c in contexts) and
        all('Queued orders smoke failed:' not in log for log in logs.values()),'closed logs differ or producer failed')
    parsed={slot:records(logs[slot],slot,matches) for slot in (0,1)}
    worlds,native_count=close._closed_states(contexts,worker_states,logs)
    native=shared.validate_native_trace(cohort_trace,spec=SPEC)
    require(list(dict.fromkeys(r['world'] for r in native)) == [worlds[1][m] for m in matches],'cohort worlds differ from actual BEGIN')
    episodes=[]; wire_count=0
    for context in contexts:
        match=context['match']; world=worlds[1][match]; seat={slot:[r for r in parsed[slot] if r['row']['match'] == match] for slot in (0,1)}
        samples={}; starts={}
        for slot in (0,1):
            require(seat[slot] and {r['row']['world'] for r in seat[slot]} == {worlds[slot][match]},'C++ world differs from BEGIN')
            for item in seat[slot]:
                row=item['row']
                if row['event'] in SNAPSHOTS: snapshot(row,slot)
                elif row['event'] == 'authority':
                    require(set(row) == close.COMMON | shared.AUTHORITY and shared.integer(row['canonical_frame'],130,440) and
                        shared._hex(row['wire_sha256']) and shared._hex(row['canonical_sha256']),'actual successful65 fields differ')
            begin=_one(seat[slot],'selected' if slot else 'setup'); end=_one(seat[slot],'complete')
            require(begin['row']['frame'] == 130 and end['row']['frame'] == 420 and begin['line'] < end['line'],'initial/completion frame/order differs')
            snapshots=[r['row'] for r in seat[slot] if r['row']['event'] in SNAPSHOTS]
            require(set(r['frame'] for r in snapshots) == set(range(130,421)),'actor/cache observations miss a frame')
            roots=('selector','manager','simulation','group_generation','current_frame_owner','preview_ids','last_click_id','click_mode')
            if slot: roots += ('group','helper','group_frame_owner')
            first=begin['row']; identity=[(m['id'],m['original_actor'],m['original_token']) for m in first['members']]
            require(all(all(r[k] == first[k] for k in roots) and [(m['id'],m['original_actor'],m['original_token']) for m in r['members']] == identity for r in snapshots),
                'original actor/token/group ownership was rebound or repaired')
            require([r['row']['canonical_frame'] for r in seat[slot] if r['row']['event'] == 'authority'] == list(range(130,441)),
                    'dense actual successful65 receipt window differs')
            _queue_intervals(seat[slot]); starts[slot]=first; samples[slot]=snapshots
        single=_one(seat[1],'single_selected'); frozen=_one(seat[1],'targets_frozen'); f=frozen['row']
        require(single['row']['frame'] == 290 and f['frame'] == 300 and single['line'] < frozen['line'],'intentional selection/freeze order differs')
        orders={tag:_command(logs[1],seat[1],tag,context) for tag in ('approach','first','queued')}
        qa,a=orders['first']; qb,b=orders['queued']; approach,ap=orders['approach']
        require(ap['sequence'] < a['sequence'] < b['sequence'] and len({q['command'] for q,_ in orders.values()}) == 3 and
            _one(seat[1],'move_queued','approach')['line'] < single['line'] < frozen['line'] < _one(seat[1],'move_queued','first')['line'] < _one(seat[1],'move_queued','queued')['line'],
            'original command ordinal/selection/freeze ordering differs')
        require(approach['incarnations'] == [m['original_token'] for m in starts[1]['members']] and
            qa['incarnations'] == qb['incarnations'] == [starts[1]['members'][0]['original_token']] and
            approach['target'] == [70.,0.,50.],'original source incarnation/approach target differs')
        for name in ('target_a','target_b'): shared.bits_point(f[name],f[name+'_bits'])
        expected_a=close.fresh_target([m['position'] for m in f['members']]); p=f['members'][0]['position']
        expected_b=[close._f32(p[0]),close._f32(p[1]),close._f32(close._f32(p[2])-16.)]
        require(all(struct.pack('<f',x) == struct.pack('<f',y) for actual,expected in ((f['target_a'],expected_a),(f['target_b'],expected_b)) for x,y in zip(actual,expected)) and
            qa['target_bits'] == f['target_a_bits'] and qb['target_bits'] == f['target_b_bits'] and
            qa['origins'] == [f['members'][0]['position']] and qa['origins_sampled_us'] == [f['members'][0]['position_sampled_us']],
            'exact frozen Single targets/first origin differ')
        require(all(m['native_state'] == 0 for m in f['members']),'first order did not start ready/idle')
        authority=_authority(context['native_states'],context['canonical_states'])
        own=[r for r in native if r['world'] == world]
        require(all(r['status'] == 'present' and [p['id'] for p in r['entities']] == IDS for r in own if r['event'] != 'before_restore_cached_head'),
            'actual native query census lost a cohort member')
        ordinary=[r for r in own if r['event'] == 'native_cohort_positions' and r['stage'] == 'ordinary']
        require([r['frame'] for r in ordinary] == list(range(280,421)),'ordinary native observation window incomplete')
        quiet=close._native_quiet(ordinary,qa,a)
        receipt,bridge,_=close._receipt(seat[1],context,a['canonical_frame'],1,native_receipts)
        queued_receipt,_,_=close._receipt(seat[1],context,b['canonical_frame'],1,native_receipts)
        end_tick=min(receipt['tick_ms'],bridge['received_tick_ms'])
        before_native=[r for r in ordinary if r['frame'] >= b['assigned_frame'] and r['query_begin_us'] >= b['registered_sampled_us'] and
            r['query_begin_tick_ms'] >= b['native67_tick_ms'] and r['query_end_tick_ms'] < end_tick]
        before_render=[r for r in samples[1] if r['frame'] >= b['assigned_frame'] and r['members'][0]['position_sampled_us'] >= b['registered_sampled_us'] and
            r['tick_ms'] >= b['native67_tick_ms'] and r['tick_ms'] < end_tick]
        require(before_native and before_render,'no measured post-B67/assigned-frame interval before BOTH A receipts')
        origin_native=next(p['position'] for p in ordinary[0]['entities'] if p['id'] == 11)
        require(all(shared._norm(shared._delta(next(p['position'] for p in r['entities'] if p['id'] == 11),origin_native)) <= .025 for r in before_native) and
            all(shared._norm(shared._delta(r['members'][0]['position'],qa['origins'][0])) <= .025 for r in before_render),
            'queued B moved before its omitted A predecessor was received')
        allowed=[(x['canonical_frame'],1,x['action_sha256']) for _,x in orders.values()]
        completion=_one(seat[1],'complete')['row']
        repair=_joined(join_check,worker_states[1],receipt,context,replay=True,required=(a['canonical_frame'],1,a['action_sha256']),
            allowed=allowed[1:],latest_tick=completion['tick_ms'])
        same_head=close._same_head(native,world,a['canonical_frame'])
        replay_queries=[r for r in own if r['event'] != 'before_restore_cached_head' and r['stage'] == 'replay' and
            r['revision'] == native[same_head['after_record']]['revision']]
        require(replay_queries[0]['query_begin_tick_ms'] >= receipt['tick_ms'] and replay_queries[-1]['query_end_tick_ms'] <= repair['group'][-1]['tick_ms'],
            'A actual replay clocks differ from deferred receipt/group provenance')
        canonical_positions=[dict(frame=frame,position=next(p['position'] for p in row['participants'] if p['id'] == 11)) for frame,row in authority.items() if frame >= 300]
        native_positions=[dict(frame=r['frame'],position=r['entities'][0]['position'],sampled_us=r['query_end_us'],record=r['record']) for r in ordinary if r['frame'] >= 300]
        rendered={r['frame']:dict(frame=r['frame'],position=r['members'][0]['position'],sampled_us=r['members'][0]['position_sampled_us']) for r in samples[1] if r['frame'] >= 300}
        canonical_turn=_turn(canonical_positions,origin_native,a['protocol_target'],b['protocol_target'])
        native_turn=_turn(native_positions,origin_native,a['protocol_target'],b['protocol_target'])
        render_turn=_turn(list(rendered.values()),qa['origins'][0],qa['target'],qb['target'])
        require(native_turn['frame'] == canonical_turn['frame'] and native_turn['first']['sampled_us'] <= render_turn['last']['sampled_us'],
            'actual native/render B turn lacks canonical correspondence')
        by_native={r['frame']:r for r in ordinary}
        for frame in range(native_turn['frame'],max(native_turn['frame'],render_turn['last_frame'])+21):
            require(frame in by_native and frame in authority and all(p['position'] == next(q['position'] for q in authority[frame]['participants'] if q['id'] == p['id']) for p in by_native[frame]['entities']),
                'native queued execution/20 continuation poses differ from original authority')
        confirmation_frame=max(canonical_turn['frame'],native_turn['frame'],render_turn['last_frame'])
        require(confirmation_frame+20 <= 420,'actual B turn is too late for20 observed continuations')
        turn65,_,_=close._receipt(seat[1],context,confirmation_frame,1,native_receipts)
        turn_proof=_joined(join_check,worker_states[1],turn65,context,allowed=allowed,latest_tick=completion['tick_ms'])
        _joined(join_check,worker_states[1],queued_receipt,context,allowed=allowed)
        # Both clients' ordinary full streams and every wire frame are also
        # checked, including receipts after the bounded observation window.
        expected=[(1,x['action_sha256']) for _,x in orders.values()]
        actual=[(slot,shared.digest(action)) for row in context['journal'] if 130 <= row['frame'] <= 440 for slot,aa in row['players'].items() for action in aa]
        require(actual == expected,'exclusive approach/A/B action conservation differs')
        require(all(len([r for r in raw if r['match'] == match]) == len(context['canonical_states']) for raw in (context['bridge_frames'],peer_bridge_frames)),
                'closed rawbridge duplicate/extra frames')
        wire_count += shared.all_wire(context=context,peer_bridge_frames=peer_bridge_frames,native_receipts=native_receipts)
        episodes.append(dict(passed=True,match=match,world=world,worlds_by_slot=[worlds[s][match] for s in (0,1)],
            selected_ids=IDS[:],subject=11,selection_calls=2,group_assign_calls=1,manual_group_ids=IDS[:],current_ids=[11],
            cache_observed_frames=291,continuity_verified=True,orders={tag:x[1] for tag,x in orders.items()},
            native_quiet_baseline=quiet,no_premature_B=dict(passed=True,native_records=[r['record'] for r in before_native],render_samples=len(before_render),
                boundary_tick_ms=end_tick,after_actual67_sampled_us=b['registered_sampled_us']),
            A_replay=repair,same_head=same_head,B_canonical_turn=canonical_turn,B_native_turn=native_turn,B_render_turn=render_turn,
            B_confirmation_frame=confirmation_frame,B_after_turn_20=turn_proof,closed_native_frames=len(context['canonical_states']),
            closed_native_rows_by_slot=[len(context['canonical_states'])]*2,physicalUI=False))
    return dict(passed=True,episodes=episodes,all_closed_native_hashes_checked=native_count,all_retained_wire_triples_checked=wire_count,
        physicalUI=False,full_feature_accepted=False,collision_solver_qualified=False,scope=SCOPE)


def _episode_complete(e):
    """Persistence completeness; raw data must still be evaluated separately."""
    try:
        required={'orders','A_replay','same_head','B_canonical_turn','B_native_turn','B_render_turn','B_after_turn_20','no_premature_B'}
        if not required <= set(e): return False
        orders=e['orders']; a=orders['first']; b=orders['queued']; pending=e['no_premature_B']; repair=e['A_replay']; tail=e['B_after_turn_20']
        if (type(orders) is not dict or set(orders) != {'approach','first','queued'} or
            not (orders['approach']['ability'] == 12 and a['ability'] == 88 and b['ability'] == 12 and
                orders['approach']['queued'] is a['queued'] is False and b['queued'] is True) or
            not all(shared._hex(o['action_sha256']) and shared._hex(o['body_sha256']) for o in orders.values()) or
            not orders['approach']['sequence'] < a['sequence'] < b['sequence']): return False
        if (pending.get('passed') is not True or type(pending.get('native_records')) is not list or not pending['native_records'] or
            len(pending['native_records']) != len(set(pending['native_records'])) or
            not all(shared.integer(n) for n in pending['native_records']) or not shared.integer(pending.get('render_samples'),1)): return False
        for name in ('B_canonical_turn','B_native_turn','B_render_turn'):
            turn=e[name]
            if (not shared.integer(turn['frame'],300,400) or turn['last_frame'] != turn['frame']+2 or
                turn['first']['frame'] != turn['frame'] or turn['last']['frame'] != turn['last_frame'] or
                not shared.point(turn['first']['position']) or not shared.point(turn['last']['position'])): return False
        if (e['B_native_turn']['frame'] != e['B_canonical_turn']['frame'] or
            e['B_confirmation_frame'] != max(e['B_native_turn']['frame'],e['B_canonical_turn']['frame'],e['B_render_turn']['last_frame']) or
            e['same_head']['first_divergent_frame'] != a['canonical_frame'] or
            not shared.integer(e['same_head']['physical_head'],a['canonical_frame'],420) or
            [r['entity'] for r in e['same_head']['entities']] != IDS): return False
        for value,frame in ((repair,a['canonical_frame']),(tail,e['B_confirmation_frame'])):
            group=value['group']
            if (type(group) is not list or not group or sum(row['frame'] == frame for row in group) != 1 or
                not all(row['world'] == e['world'] and shared._hex(row['parsed_state_sha256']) for row in group) or
                len(value['promotion_group_row_indices']) != len(group) or len(value['continuation_row_indices']) != 20): return False
        return bool(sum(row['replayed_frames_delta'] for row in repair['group']) > 0 and
            (a['canonical_frame'],1,a['action_sha256']) in [tuple(v) for v in repair['input_actions']])
    except (KeyError,TypeError,AttributeError,ValueError): return False


def _proof(proof,matches):
    if type(proof) is not dict: return False
    eps=proof.get('episodes',[])
    return bool(proof.get('passed') is True and proof.get('scope') == SCOPE and proof.get('physicalUI') is False and
        proof.get('full_feature_accepted') is proof.get('collision_solver_qualified') is False and type(eps) is list and len(eps) == 2 and
        [e.get('match') for e in eps] == matches and len({e.get('world') for e in eps}) == 2 and
        all(_episode_complete(e) and e.get('passed') is e.get('continuity_verified') is True and e.get('selected_ids') == e.get('manual_group_ids') == IDS and
            e.get('subject') == 11 and e.get('current_ids') == [11] and e.get('selection_calls') == 2 and e.get('group_assign_calls') == 1 and
            e.get('cache_observed_frames') == 291 and e.get('no_premature_B',{}).get('passed') is True and
            shared.integer(e.get('B_confirmation_frame'),300,400) and type(e.get('worlds_by_slot')) is list and len(e['worlds_by_slot']) == 2 and
            all(shared.integer(v,1) for v in e['worlds_by_slot']) and e['worlds_by_slot'][1] == e['world'] and
            shared.integer(e.get('closed_native_frames'),650) and e.get('closed_native_rows_by_slot') == [e['closed_native_frames']]*2 and
            e.get('physicalUI') is False for e in eps) and proof.get('all_closed_native_hashes_checked') == proof.get('all_retained_wire_triples_checked') ==
        sum(e['closed_native_frames']*2 for e in eps))


def finalize(report,plan):
    validate_plan(plan); require(plan.get('queued_orders') is True,'explicit scenario required')
    report['queued_orders_witness_passed']=report['scoped_observation_passed']=False
    matches=close._report_envelope(report)
    require(_proof(report.get('queued_orders',{}),matches),'complete two-world queued proof missing')
    report.update(queued_orders_witness_passed=True,scoped_observation_passed=True,generic_movement_not_exercised=True,movement_feel_witness_passed=False)


def gate(plan,report):
    if not plan.get('queued_orders'): return plan.get('scenario') != 'queued-orders'
    try:
        validate_plan(plan); matches=close._report_envelope(report)
        return bool(report.get('queued_orders_witness_passed') is report.get('scoped_observation_passed') is True and
            report.get('generic_movement_not_exercised') is True and report.get('movement_feel_witness_passed') is False and _proof(report.get('queued_orders',{}),matches))
    except (AssertionError,KeyError,TypeError,AttributeError): return False
