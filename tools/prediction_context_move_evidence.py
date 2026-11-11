"""Pure joins for real bound-Mouse ContextDown Move and balanced ContextUp.

Raw rows remain unchanged. The fresh action hash is derived only from the normal
serialized batch body, joined to the observed callback ICommand pointer/serial.
"""
from __future__ import annotations

import json
import math
import re

from server.game_data import decode_player_input
from server.protobuf_wire import get_bytes, get_repeated_bytes, get_repeated_uint, get_uint, parse_fields

UINT32, UINT64 = 2**32-1, 2**64-1
EVENTS = ('setup','native_dead','natural_release','restored','primary_position_queued',
    'primary_position_observed','primary_down_queued','primary_down_observed','primary_up_queued',
    'primary_up_observed','primary_closed','context_position_queued','context_position_observed',
    'context_down_queued','context_down_observed','context_up_queued','context_up_observed','context_closed','complete')
INPUT_FIELDS = set(('schema,event,sequence,world,match,frame,ordinal,tick_ms,sampled_us,slot,entity,unit_type,army,'
    'original_token,session,input_sequence,input_closed,selector,action,control,device,primary,context,drag,'
    'owned_primary,owned_context,current_ids,preview_ids,casting_ids,active_caster,current_token,canonical_token,'
    'native_present,native_state,current_admitted,last_click_id,click_mode,primary_return_serial,primary_return_down,'
    'primary_return_up,context_return_serial,context_return_down,context_return_up,pending_commands,selection_writes,'
    'history_writes,physicalUI,screen_position,queued_screen_position').split(','))
CALLBACK_FIELDS = set(('schema,event,sequence,world,match,generation,selector,manager,server,simulation,thread,kind,'
    'ticket_serial,frame,tick_ms,sampled_us,ledger_completed,ledger_serial,primary,context,drag,owned_primary,'
    'owned_context,pending_commands,captured_command,captured_class,target,target_bits,queued,map_perspective,physicalUI').split(','))
PERSPECTIVE_FIELDS = set(('local_alliance,map_perspective,map_perspective_source,map_perspective_enum,'
    'map_perspective_enum_matches_ctor,map_perspective_normal,map_perspective_flipped,map_perspective_value_name').split(','))
ORDER_FIELDS = set(('schema,event,world,match,slot,entity,unit_type,army,incarnation,frame,tick_ms,sampled_us,'
    'origin_sampled_us,enqueue_sampled_us,origin,target,target_bits,requested_target,command,command_class,queued,'
    'originalCtor,original_callback,queue_before,queue_after,queueDelta,physicalUI').split(',')) | PERSPECTIVE_FIELDS
SERIALIZED_FIELDS = set(('schema,world,match,generation,selector,manager,thread,callback_serial,frame,source_next_frame,'
    'sequence,command,action,tick_ms,sampled_us,physicalUI').split(','))
PREFIXES = ('CONTEXT INPUT ', 'CONTEXT CALLBACK ', 'CONTEXT ORDER ', 'CONTEXT SERIALIZED ')


def require(ok, why):
    if not ok:
        raise AssertionError('context Move evidence: ' + why)


def integer(value, low=0, high=UINT64):
    return type(value) is int and low <= value <= high


def pointer(value, *, optional=False):
    if value is None:
        require(optional, 'missing original pointer')
        return 0
    require(type(value) is str and re.fullmatch(r'(?:0x)?[a-fA-F0-9]{1,16}', value) is not None,
            'invalid original pointer')
    result = int(value, 16)
    require(optional or result > 0, 'zero original owner pointer')
    return result


def vector(value, size):
    return type(value) is list and len(value) == size and all(type(v) in (int,float) and
        math.isfinite(v) and abs(v) <= 1e6 for v in value)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _rows(log, prefix, fields, limit):
    result = []
    for index, line in enumerate(log.splitlines()):
        if prefix not in line:
            continue
        raw = line.split(prefix, 1)[1]
        require(0 < len(raw) <= 16384, 'diagnostic row exceeds bound')
        try:
            row = json.loads(raw, object_pairs_hook=_unique)
        except (ValueError,TypeError) as error:
            raise AssertionError('context Move evidence: invalid JSON') from error
        require(type(row) is dict and set(row) == fields and integer(row['schema'],1,1) and
            integer(row['world'],1,2) and type(row['match']) is str and re.fullmatch('[a-f0-9]{32}',row['match']) and
            integer(row['frame'],0,1000) and integer(row['tick_ms']) and integer(row['sampled_us'],1) and
            row['physicalUI'] is False, 'strict schema1/owner/clock differs')
        result.append((index,row))
        require(len(result) <= limit, 'extra diagnostic rows')
    return result


def records(log, match):
    require(type(log) is str and len(log) <= 32*1024*1024 and type(match) is str and
        re.fullmatch('[a-f0-9]{32}',match), 'invalid log/match')
    groups = [_rows(log,prefix,fields,limit) for prefix,fields,limit in zip(PREFIXES,
        (INPUT_FIELDS,CALLBACK_FIELDS,ORDER_FIELDS,SERIALIZED_FIELDS),(38,8,2,2))]
    own = [[(i,r) for i,r in rows if r['match'] == match] for rows in groups]
    require([len(rows) for rows in own] == [19,4,1,1], 'complete input/callback/order/normal serialization episode required')
    inputs = [r for _,r in own[0]]
    callbacks = [r for _,r in own[1]]
    order, serialized = own[2][0][1], own[3][0][1]
    world, token = inputs[0]['world'], inputs[0]['original_token']
    require([r['event'] for r in inputs] == list(EVENTS) and [r['sequence'] for r in inputs] == list(range(1,20)) and
        integer(token,1), 'missing/reordered input event or original token')
    events = dict(zip(EVENTS,inputs))
    require(all(r['world'] == world for rows in own for _,r in rows), 'world was rebound')
    for i,row in enumerate(inputs):
        event = row['event']
        session = 0 if i < 4 else 1 if i < 11 else 2
        seq = 0 if not session else (1 if event.endswith(('position_queued','position_observed')) else
            2 if event.endswith(('down_queued','down_observed')) else 3)
        closed = not session or event in ('primary_closed','context_closed','complete')
        require((row['slot'],row['entity'],row['unit_type'],row['army']) == (1,11,1,1) and
            all(type(row[k]) is int for k in ('slot','entity','unit_type','army')) and
            row['original_token'] == token and type(row['original_token']) is int and
            integer(row['session'],session,session) and integer(row['input_sequence'],seq,seq) and
            row['input_closed'] is closed and integer(row['ordinal'],1) and
            all(type(row[k]) is bool for k in ('primary','context','drag','native_present','current_admitted',
                'primary_return_down','primary_return_up','context_return_down','context_return_up')) and
            not row['drag'] and integer(row['pending_commands'],0,1) and
            integer(row['selection_writes'],0,0) and integer(row['history_writes'],0,0),
            'input scope/session/scalar differs')
        pointer(row['selector'])
        for key in ('current_ids','preview_ids','casting_ids'):
            require(type(row[key]) is list and len(set(row[key])) == len(row[key]) and
                all(integer(v,11,11) for v in row[key]), 'invalid original ID set')
        pointer(row['active_caster'],optional=True)
        require((i >= 14 or row['active_caster'] is None and not row['casting_ids']) and
            integer(row['current_token']) and row['canonical_token'] == token and
            type(row['canonical_token']) is int and integer(row['last_click_id'],0,UINT32) and
            integer(row['click_mode'],0,2) and
            (row['native_state'] is None or integer(row['native_state'],0,UINT32-1)), 'input identity/history differs')
        require(all(integer(row[k]) for k in ('primary_return_serial','context_return_serial')) and
            not(row['primary_return_down'] and row['primary_return_up']) and
            not(row['context_return_down'] and row['context_return_up']), 'returned button witness is ambiguous')
        for name in ('screen_position','queued_screen_position'):
            require(row[name] is None or vector(row[name],2), 'invalid observed screen position')
        require((row['queued_screen_position'] is None) == (session == 0), 'queued position has no actual session')
        if not session:
            require(all(row[k] is None for k in ('action','control','device','owned_primary','owned_context')) and
                not row['primary'] and not row['context'] and row['pending_commands'] == 0, 'pre-input row has a live input lease')
        else:
            for key in ('action','control','device'):
                pointer(row[key])
            require(all(row[k] is None if closed else type(row[k]) is bool for k in ('owned_primary','owned_context')),
                'closed/live actual device observation differs')
            primary = event in ('primary_down_observed','primary_up_queued')
            context = event in ('context_down_observed','context_up_queued')
            require(row['primary'] is primary and row['context'] is context and
                (closed or row['owned_primary'] is primary and row['owned_context'] is context),
                'actual selector/device button phase differs')
            if event not in ('primary_position_queued','context_position_queued'):
                require(row['screen_position'] == row['queued_screen_position'], 'queued position was not actually observed')
        if i >= 3:
            require(row['native_present'] and row['native_state'] != 6 and row['current_admitted'] and
                row['current_token'] == token, 'restored input source is not current admitted mobile')
        if i >= 9:
            require(row['current_ids'] == [11] and row['last_click_id'] == 11 and row['click_mode'] == 0,
                'real primary release did not establish current selection/history')
    require(all(b['frame'] >= a['frame'] and b['ordinal'] >= a['ordinal'] and b['tick_ms'] >= a['tick_ms'] and
        b['sampled_us'] >= a['sampled_us'] for a,b in zip(inputs,inputs[1:])), 'input ordering regressed')
    require([events[k]['frame'] for k in EVENTS[:3]] == [130,153,154] and
        154 <= events['restored']['frame'] <= 164 and inputs[-1]['frame'] in (260,261), 'lifecycle frames differ')
    require(events['native_dead']['native_state'] == 6 and not events['natural_release']['native_present'] and
        events['natural_release']['native_state'] is None and not events['natural_release']['current_admitted'],
        'original dead/removal evidence is absent')
    for prefix,frames in (('primary',(178,180,180,(180,181),182,(182,183))),
                          ('context',(184,186,186,(186,187),None,None))):
        queued,pos,down,pressed,up,released = [events[prefix+'_'+suffix] for suffix in
            ('position_queued','position_observed','down_queued','down_observed','up_queued','up_observed')]
        require(queued['frame'] == frames[0] and pos['frame'] == frames[1] and down['frame'] == frames[2] and
            pressed['frame'] in frames[3] and pos['ordinal'] > queued['ordinal'] and
            pressed['ordinal'] > down['ordinal'] and released['ordinal'] > up['ordinal'] and
            events[prefix+'_closed']['frame'] == released['frame'], 'original input consumption/close boundary differs')
        if prefix == 'primary':
            require(up['frame'] == frames[4] and released['frame'] in frames[5], 'primary release frame differs')
        else:
            require(up['ordinal'] == pressed['ordinal']+1 and up['frame'] <= 189 and released['frame'] <= 190,
                'ContextUp did not queue on first later ordinal or finish by190')
        leased = [r for r in inputs if r['session'] == (1 if prefix == 'primary' else 2)]
        require(len({tuple(r[k] for k in ('selector','action','control','device')) for r in leased}) == 1,
            'bound input lease changed within session')
    require(inputs[4]['selector'] == inputs[11]['selector'] == inputs[0]['selector'] and
        inputs[4]['device'] == inputs[11]['device'] and inputs[4]['action'] != inputs[11]['action'] and
        inputs[4]['control'] != inputs[11]['control'], 'primary/context receipts reused a different owner or the same button')
    pdown,pup = events['primary_down_observed'],events['primary_up_observed']
    require(pdown['primary_return_down'] and not pdown['primary_return_up'] and pdown['primary_return_serial'] > 0 and
        pup['primary_return_up'] and pup['primary_return_serial'] > pdown['primary_return_serial'], 'fresh primary Down/Up return is stale')
    require(all(r['primary_return_serial'] == pdown['primary_return_serial'] and r['primary_return_down'] and
        not r['primary_return_up'] for r in inputs[7:9]), 'held primary provenance changed before actual Up')
    require(all(r['primary_return_serial'] == pup['primary_return_serial'] and r['primary_return_up'] and
        not r['primary_return_down'] for r in inputs[9:]), 'post-primary-Up provenance was overwritten')
    require(all(r['primary_return_serial'] == 0 and not r['primary_return_down'] and not r['primary_return_up']
        for r in inputs[:7]) and all(r['context_return_serial'] == 0 and not r['context_return_down'] and
        not r['context_return_up'] for r in inputs[:14]), 'button witness preceded an actual current-world callback')
    singles = re.findall(r'Prediction input Single observed: world=(\d+) generation=(\d+) serial=(\d+) entity=(\d+) '
        r'originalDown=1 originalProcess=1 completedCallback=1 dispatchVerified=1 repairAuthorized=0',log)
    require(sum(int(w)==world and int(g)==callbacks[0]['generation'] and
        int(s)==pdown['primary_return_serial'] and int(e)==11 for w,g,s,e in singles) == 1,
        'fresh primary Down lacks one actual Single observation')
    require([(r['kind'],r['event'],r['sequence']) for r in callbacks] ==
        [('ContextDown','before',1),('ContextDown','returned',2),('ContextUp','before',3),('ContextUp','returned',4)],
        'missing/reordered actual context callbacks')
    owner_keys = ('generation','selector','manager','server','simulation','thread')
    require(len({tuple(r[k] for k in owner_keys) for r in callbacks}) == 1, 'callback owner changed')
    for r in callbacks:
        require(integer(r['generation'],1) and integer(r['thread'],1,UINT32) and integer(r['ticket_serial'],1) and
            integer(r['ledger_serial'],r['ticket_serial']) and (r['ledger_completed'] is None if r['event']=='before'
            else type(r['ledger_completed']) is bool) and all(type(r[k]) is bool for k in
            ('primary','context','drag','owned_primary','owned_context')) and not r['primary'] and not r['owned_primary'] and
            not r['drag'] and integer(r['pending_commands'],0,1), 'callback type/ledger/button differs')
        for k in ('selector','manager','server','simulation'):
            pointer(r[k])
    before,returned,up_before,up_returned = callbacks
    require(before['selector'] == inputs[0]['selector'] and
        before['ticket_serial'] == returned['ticket_serial'] > pup['primary_return_serial'] and
        up_before['ticket_serial'] == up_returned['ticket_serial'] > returned['ticket_serial'] and
        before['frame'] == returned['frame'] and returned['frame'] in (186,187) and
        0 <= events['context_down_observed']['frame']-returned['frame'] <= 1 and
        up_before['frame'] == up_returned['frame'] and
        0 <= events['context_up_observed']['frame']-up_returned['frame'] <= 1 and
        returned['sampled_us'] <= events['context_down_observed']['sampled_us'] and
        up_returned['sampled_us'] <= events['context_up_observed']['sampled_us'] and
        all(b['sampled_us'] >= a['sampled_us'] and b['tick_ms'] >= a['tick_ms'] for a,b in zip(callbacks,callbacks[1:])),
        'callback return serial/frame/clock differs')
    require([(r['context'],r['owned_context']) for r in callbacks] == [(False,True),(True,True),(True,False),(False,False)] and
        before['pending_commands'] == 0 and returned['pending_commands'] == 1 and
        up_before['pending_commands'] == up_returned['pending_commands'], 'context callback did not produce one command on Down only')
    captured = ('captured_command','captured_class','target','target_bits','queued','map_perspective')
    require(all(before[k] is None for k in captured), 'command capture preceded original ContextDown')
    pointer(returned['captured_command'])
    require(returned['captured_class'] == 'Uncapped.ExecuteTargetGroundCommand' and returned['queued'] is False and
        vector(returned['target'],3) and type(returned['target_bits']) is list and len(returned['target_bits']) == 3 and
        all(integer(v,0,UINT32) for v in returned['target_bits']) and type(returned['map_perspective']) is int and
        returned['map_perspective'] in (0,1) and all(all(r[k] == returned[k] for k in captured) for r in callbacks[2:]),
        'actual ground command capture changed/failed')
    cdown,cup = events['context_down_observed'],events['context_up_observed']
    require(cdown['context_return_down'] and cdown['context_return_serial'] == returned['ticket_serial'] and
        cup['context_return_up'] and cup['context_return_serial'] == up_returned['ticket_serial'] and
        all(r['context_return_serial'] == returned['ticket_serial'] and r['context_return_down'] and
            not r['context_return_up'] for r in inputs[14:16]) and
        all(r['context_return_serial'] == cup['context_return_serial'] and r['context_return_up'] and
            not r['context_return_down'] for r in inputs[16:]), 'context returned button witness is stale')
    require(order['event'] == 'original_context_move' and
        (order['slot'],order['entity'],order['unit_type'],order['army'],order['incarnation']) == (1,11,1,1,token) and
        order['frame'] == before['frame'] and order['sampled_us'] == before['sampled_us'] and
        order['enqueue_sampled_us'] == returned['sampled_us'] and integer(order['origin_sampled_us'],1) and
        pup['sampled_us'] < order['origin_sampled_us'] <= order['sampled_us'] and
        order['originalCtor'] is False and order['original_callback'] == 'Uncapped.UnitSelector.OnPlayerPointerContextDown' and
        all(integer(order[k],v,v) for k,v in (('queue_before',0),('queue_after',1),('queueDelta',1))) and order['queued'] is False and
        order['command'] == returned['captured_command'] and order['command_class'] == returned['captured_class'] and
        order['target'] == returned['target'] and order['target_bits'] == returned['target_bits'] and
        order['map_perspective'] == returned['map_perspective'] and
        all(vector(order[k],3) for k in ('origin','target','requested_target')),
        'original context order does not belong to the captured callback command')
    for k in ('selector','manager','generation','thread'):
        require(serialized[k] == returned[k], 'normal serialization owner was rebound')
    require(integer(serialized['sequence'],1) and integer(serialized['callback_serial'],1) and
        serialized['callback_serial'] == returned['ticket_serial'] and serialized['command'] == order['command'] and
        integer(serialized['source_next_frame'],0,1000) and serialized['sampled_us'] >= returned['sampled_us'],
        'normal ToProto did not bind the captured Down command/serial')
    pointer(serialized['action'])
    carried = inputs[0]['last_click_id'] == 11
    if carried:
        previous = [r for _,r in groups[0] if r['world'] == 1 and r['event'] == 'complete' and
            r['sampled_us'] < inputs[0]['sampled_us']]
        require(world == 2 and len(previous) == 1, 'initial reference11 lacks the prior completed input world')
        prior = records(log,previous[0]['match'])['events']['complete']
        require(prior['selector'] == inputs[0]['selector'] and prior['primary_return_up'] and prior['context_return_up'] and
            prior['input_closed'] and not prior['primary'] and not prior['context'], 'prior input history was not genuinely released')
    return dict(rows=inputs,indices=[i for i,_ in own[0]],events=events,world=world,match=match,token=token,
        callbacks=callbacks,callback_indices=[i for i,_ in own[1]],order=order,order_index=own[2][0][0],
        serialized=serialized,serialized_index=own[3][0][0],carried_idle_history=carried)


def fresh_order(witness, raw_bodies):
    """Derive the action hash from the one normal batch, never before ToProto."""
    from tools.prediction_mobile_evidence import digest
    sequence = witness['serialized']['sequence']
    body = raw_bodies.get((witness['match'],1,sequence))
    require(type(body) is bytes, 'normal serialized native67 body is missing')
    decoded = decode_player_input(body)
    require(len(decoded['actions']) == 1 and decoded['identity']['player_id'] == 2 and decoded['identity']['is_aliased'] and
        not decoded['identity']['ai_profile_id'], 'normal native67 body is not one victim human action')
    action = decoded['actions'][0]
    require([f.number for f in parse_fields(action)] == [1], 'normal action is not Execute')
    command = get_bytes(action,1,required=True)
    groups = get_repeated_bytes(command,1)
    require(len(groups) == 1 and (get_uint(groups[0],1),get_uint(groups[0],2),get_repeated_uint(groups[0],3)) ==
        (1,12,(11,)) and get_uint(command,2) == 0 and
        [f.number for f in parse_fields(get_bytes(command,3,required=True))] == [3],
        'captured normal command is not original Move12/type1/ID11/ground')
    return dict(witness['order'],ability=12,action_sha256=digest(action),normal_sequence=sequence,
        normal_serialization=witness['serialized'])


def mobile_row_scope(witness, row):
    events = witness['events']
    require(row['world'] == witness['world'] and row['match'] == witness['match'] and
        row['original_incarnation'] == witness['token'], 'mobile/context identity differs')
    if row['event'] != 'original_mobile_selection_established':
        require(row['focus_group'] == -1, 'cancelled repeat focus restarted')
    if row['live_click_id'] == 11:
        require(witness['carried_idle_history'] or
            events['primary_down_observed']['frame'] <= row['frame'] <= events['complete']['frame'],
            'reference11 preceded its actual primary input')
    for key,prefix in (('left_held','primary'),('right_held','context')):
        first,last = events[prefix+'_down_observed'],events[prefix+'_up_observed']
        require(not row[key] or first['frame'] <= row['frame'] <= last['frame'], 'held button escaped actual input interval')
        require(not(first['frame'] < row['frame'] < last['frame']) or row[key], 'button released without actual Up')
    if row['pending_commands']:
        require(row['pending_commands'] == 1 and witness['callbacks'][1]['sampled_us'] <= row['sampled_us'] <=
            witness['serialized']['sampled_us'], 'queue1 escaped original callback/normal drain interval')
    return True


def post_down_scope(witness, row):
    return (witness['callbacks'][1]['sampled_us'] <= row['sampled_us'] <= witness['events']['complete']['sampled_us'] and
        witness['callbacks'][1]['frame'] <= row['frame'] <= witness['events']['complete']['frame'])


def bind_mobile(witness, rows, indices):
    names = ('setup','native_dead','natural_release','restored','primary_down_queued','primary_up_observed','complete')
    events = witness['events']
    named = [(i,r) for i,r in zip(indices,rows) if r['event'] != 'snapshot']
    require(len(named) == 7, 'mobile lifecycle is incomplete')
    positions = dict(zip(EVENTS,witness['indices']))
    for (index,row),name in zip(named,names):
        actual = events[name]
        require(row['frame'] == actual['frame'] and row['sampled_us'] <= actual['sampled_us'] and
            index < positions[name] and not any(index < other < positions[name] for other in indices),
            'named mobile snapshot lacks its immediate same-callback input observation')
        require(row['selected_ids'] == actual['current_ids'] and row['preview_ids'] == actual['preview_ids'] and
            row['casting_ids'] == actual['casting_ids'] and row['current_incarnation'] == actual['current_token'] and
            row['current_admitted'] is actual['current_admitted'] and row['left_held'] is actual['primary'] and
            row['right_held'] is actual['context'] and row['live_click_id'] == actual['last_click_id'] and
            pointer(row['active_caster'],optional=True) == pointer(actual['active_caster'],optional=True) and
            row['native_identity_present'] is actual['native_present'] and row['native_state'] == actual['native_state'],
            'unmodified mobile snapshot differs from original input observation')
    require(named[5][1]['selection_scope_player_initiated'] is None, 'fresh selection used a programmatic scope')
    return dict(passed=True,evidence_schema=1,world=witness['world'],match=witness['match'],rows=witness['rows'],
        callbacks=witness['callbacks'],order=witness['order'],serialized=witness['serialized'],
        balanced_original_input=True,context_callback_created_move=True,normal_serialization_only=True,
        selection_writes=0,history_writes=0,originalCtor=False,physicalUI=False)


def evaluate(log, *, attacker_log, mobile_episodes, expected_matches):
    require(not any(prefix in attacker_log for prefix in PREFIXES) and type(expected_matches) is list and
        len(expected_matches) == len(set(expected_matches)) == len(mobile_episodes) == 2 and
        [ep.get('match') for ep in mobile_episodes] == expected_matches, 'two ordered victim-only episodes required')
    result = []
    for world,(match,ep) in enumerate(zip(expected_matches,mobile_episodes),1):
        witness = records(log,match)
        bound = ep.get('mobile_context_move',{})
        require(ep.get('passed') is True and ep.get('world') == witness['world'] == world and
            bound.get('passed') is True and bound.get('rows') == witness['rows'] and
            all(bound.get(k) == witness[k] for k in ('callbacks','order','serialized')) and
            ep.get('same_confirmed_token') is True and ep.get('original_mobile_release_observed') is True and
            ep.get('current_mobile_reinitialized_and_admitted') is True and
            ep.get('escape_native_replay',{}).get('continuation_frames') == 20 and
            ep.get('fresh_native_confirmation',{}).get('continuation_frames') == 20 and
            ep.get('fresh_motion',{}).get('passed') is True and ep.get('fresh',{}).get('order',{}).get('originalCtor') is False and
            ep['fresh']['sequence'] == witness['serialized']['sequence'], 'context input lacks existing mobile/native/replay/feel proof')
        result.append(bound)
    require(result[0]['rows'][-1]['sampled_us'] < result[1]['rows'][0]['sampled_us'], 'rematch clocks overlap')
    require([sum(prefix in line for line in log.splitlines()) for prefix in PREFIXES] == [38,8,2,2],
        'extra/unjoined context evidence')
    return dict(passed=True,evidence_schema=1,episodes=result,selection_writes=0,history_writes=0,originalCtor=False,
        context_callback_created_move=True,normal_serialization_only=True,physicalUI=False,full_mobile_controls_accepted=False,
        scope='Actual bound-Mouse fresh primary click, original ContextDown Move12 normal serialization and balanced ContextUp; existing mobile/native/replay/pre-authority gates remain required')
