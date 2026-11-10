"""Pure joins for the explicit original-Gunbot mobile correction experiment.

This module consumes retained observations.  It starts no processes, queries no
native state, and treats Unity addresses as observed leases, not entity IDs.
The injected command/replay checkers retain the controller's existing wire and
canonical-state contracts without importing that controller here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct

from server.game_data import decode_player_input
from server.protobuf_wire import get_bytes, get_repeated_bytes, get_repeated_uint, get_uint, parse_fields
from tools.prediction_actor_fixture import mobile_metadata


EVENTS = (
    'original_mobile_selection_established', 'native_dead_observed',
    'original_mobile_release_observed', 'original_mobile_restored_and_admitted',
    'before_fresh_reselection', 'original_fresh_reselection_established',
    'mobile_observation_complete',
)
UI_EVENTS = (*EVENTS[:4], 'before_ui_cast', 'original_ui_cast_queued', 'mobile_observation_complete')
HEX64 = re.compile('[a-f0-9]{64}')
UINT32 = 2**32 - 1
UINT64 = 2**64 - 1


def require(ok, reason):
    if not ok:
        raise AssertionError('mobile evidence: ' + reason)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def _bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def _reported_bits_match(value, bits):
    # ostream prints negative float zero as "-0". JSON's integer decoder loses
    # its sign; preserve the separate raw bit field as the source of that sign.
    return _bits(value) == bits or (value == 0 and bits in (0, 0x80000000))


def _perspective(order):
    require(_integer(order.get('local_alliance'), 0, UINT32) and
            type(order.get('map_perspective')) is int and order['map_perspective'] in (0, 1) and
            order.get('map_perspective_source') == 'Uncapped.Map.GetAlliancePerspective' and
            order.get('map_perspective_enum') == 'Uncapped.Map.Perspective' and
            order.get('map_perspective_enum_matches_ctor') is True and
            type(order.get('map_perspective_normal')) is int and order['map_perspective_normal'] == 0 and
            type(order.get('map_perspective_flipped')) is int and order['map_perspective_flipped'] == 1 and
            order.get('map_perspective_value_name') == ('Normal' if order['map_perspective'] == 0 else 'Flipped'),
            'fresh original runtime map getter/constructor Perspective proof differs')
    return {key: order[key] for key in ('local_alliance', 'map_perspective', 'map_perspective_source',
        'map_perspective_enum', 'map_perspective_enum_matches_ctor', 'map_perspective_normal',
        'map_perspective_flipped', 'map_perspective_value_name')}


def _integer(value, low=0, high=UINT64):
    return type(value) is int and low <= value <= high


def _pointer(value):
    require(type(value) is str and re.fullmatch('[a-fA-F0-9]{1,16}', value), 'invalid observed actor pointer')
    return int(value, 16)


def _vector(value):
    require(type(value) is list and len(value) == 3 and all(type(v) in (int, float) and
            math.isfinite(v) and abs(v) <= 1e6 for v in value), 'nonfinite/out-of-range native vector')
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate diagnostic JSON key')
        result[key] = value
    return result


def _rows(log, prefix, match, limit):
    require(type(log) is str and len(log) <= 32 * 1024 * 1024, 'diagnostic log exceeds bound')
    result = []
    for line in log.splitlines():
        if prefix not in line:
            continue
        raw = line.split(prefix, 1)[1]
        require(0 < len(raw) <= 8192, 'diagnostic row exceeds bound')
        row = json.loads(raw, object_pairs_hook=_unique_object)
        require(type(row) is dict and type(row.get('schema')) is int and row['schema'] == 1 and
                type(row.get('match')) is str and re.fullmatch('[a-f0-9]{32}', row['match']),
                'invalid diagnostic schema/match')
        if row['match'] == match:
            result.append(row)
            require(len(result) <= limit, 'diagnostic row count exceeds bound')
    return result


def _common(row, *, world=None):
    require(all(_integer(row.get(k)) for k in ('world', 'tick_ms', 'sampled_us')) and
            row['world'] > 0 and (world is None or row['world'] == world) and
            all(_integer(row.get(k), 0, UINT32) for k in ('entity', 'unit_type', 'army')) and
            _integer(row.get('frame'), 0, 2**31-1) and row.get('physicalUI') is False,
            'invalid native identity/clock/scope')


def _focus_observation(row, *, transient):
    """Classify the original cached branch, never a camera-call observation."""
    booleans = ('focus_is_unit', 'focus_dead_to_sim', 'focus_component_present', 'focus_in_active',
        'focus_in_retained', 'focus_current_admitted', 'focus_unity_truth', 'focus_is_active_and_enabled',
        'focus_lookup_id_present')
    for key in booleans:
        require(key in row and (row[key] is None or type(row[key]) is bool),
                'missing/invalid nullable focus boolean')
    for key in ('focus_actual_entity', 'focus_actual_type', 'focus_actual_army'):
        require(key in row and (row[key] is None or _integer(row[key], 0, UINT32)),
                'missing/invalid nullable focus identity')
    for key in ('focus_observed_incarnation', 'focus_confirmed_incarnation', 'focus_cached_ptr'):
        require(key in row and (row[key] is None or _integer(row[key])),
                'missing/invalid nullable focus token/pointer')
    for key in ('focus_class_name', 'focus_class_namespace', 'focus_unity_proof_error', 'focus_lookup_proof_error'):
        require(key in row and (row[key] is None or type(row[key]) is str and len(row[key]) <= 2048),
                'missing/invalid nullable focus class/error')
    require(row.get('focus_lookup_source') == 'manager-active-UnitSet-id-enumeration' and
            'focus_lookup_actor' in row and (row['focus_lookup_actor'] is None or
                _pointer(row['focus_lookup_actor']) > 0), 'missing/invalid original manager lookup provenance')
    if row['focus_lookup_id_present'] is False:
        require(row['focus_lookup_actor'] is None, 'explicit manager lookup miss has an actor')
    if row['focus_lookup_id_present'] is True:
        require(row['focus_lookup_actor'] is not None, 'positive manager lookup has no actor')
    predicates = {key: row[key] for key in
                  ('focus_unity_truth', 'focus_lookup_id_present', 'focus_is_active_and_enabled')}
    facts = {key: row[key] for key in (*booleans, 'focus_actual_entity', 'focus_actual_type', 'focus_actual_army',
        'focus_observed_incarnation', 'focus_confirmed_incarnation', 'focus_cached_ptr', 'focus_class_name',
        'focus_class_namespace', 'focus_unity_proof_error', 'focus_lookup_proof_error',
        'focus_lookup_source', 'focus_lookup_actor')}
    if not _pointer(row['focus_actor']):
        classification, would_focus = 'null_cached_object', False
        # No getter was queried for null; do not invent observed false values.
    elif any(value is False for value in predicates.values()):
        classification, would_focus = 'would_not_focus_known_false', False
    elif all(value is True for value in predicates.values()):
        would_focus = True
        if transient:
            classification = 'would_focus_predicates_true_transient_lease_unqualified'
        else:
            require(row['focus_is_unit'] is True and row['focus_class_namespace'] == 'Uncapped' and
                    row['focus_class_name'] == 'Unit' and
                    _integer(row['focus_actual_entity'], 0, UINT32) and
                    _integer(row['focus_actual_type'], 1, UINT32) and
                    _integer(row['focus_actual_army'], 0, UINT32) and
                    row['focus_dead_to_sim'] is False and row['focus_component_present'] is True and
                    row['focus_in_active'] is True and row['focus_in_retained'] is False and
                    row['focus_cached_ptr'] is not None and row['focus_cached_ptr'] > 0 and
                    row['focus_unity_proof_error'] is None and
                    row['focus_lookup_proof_error'] is None and
                    _pointer(row['focus_actor']) == _pointer(row['focus_lookup_actor']) and
                    row['focus_observed_incarnation'] is not None and
                    row['focus_observed_incarnation'] == row['focus_confirmed_incarnation'] > 0,
                    'stable original focus predicates select an invalid/uninitialized/unconfirmed camera lease')
            # Original camera following is not player input. Context.admitted
            # additionally requires our army, so its False observation is not
            # a stale-lease proof for a live enemy/allied camera target.
            classification = 'would_focus_valid_camera_lease'
    else:
        classification, would_focus = 'focus_proof_missing', None
        require(transient, 'stable original focus predicates missing')
    return dict(event=row['event'], frame=row['frame'], tick_ms=row['tick_ms'], focus_actor=row['focus_actor'],
        focus_group=row['focus_group'], predicates=predicates, facts=facts, classification=classification,
        would_focus_per_original_predicates=would_focus, transient_front_update=transient,
        target_identity=dict(entity=row['focus_actual_entity'], unit_type=row['focus_actual_type'], army=row['focus_actual_army']),
        target_differs_from_input_mobile=(row['focus_actual_entity'], row['focus_actual_type'], row['focus_actual_army']) != (11, 1, 1),
        own_input_admission_required=False,
        whole_unity_frame_claim=False, actual_camera_call_observed=False,
        scope='Would focus per original cached-branch predicates; not an actual camera-call observation')


def _caster_lifetime_records(log, match):
    """Validate fixture invocations and observed100, not engine callback causes."""
    rows = _rows(log, 'MOBILE ACTIVE CASTER ', match, 2048)
    require(rows, 'missing active-caster lifetime receipt')
    indices=[]
    for index,line in enumerate(log.splitlines()):
        if 'MOBILE ACTIVE CASTER ' in line:
            row=json.loads(line.split('MOBILE ACTIVE CASTER ',1)[1],object_pairs_hook=_unique_object)
            if row['match']==match:indices.append(index)
    fields={'schema','event','world','match','slot','entity','unit_type','army','frame','tick_ms','sampled_us',
        'button_slot','config_id','ui_cast_type','ui_group_kind','smart_casting','activated_caster',
        'activated_caster_class','active_caster','active_caster_class','active_relation','is_unit_selection_related',
        'source_ids','source_count','casting_ids','casting_count','pending_commands','left_held','right_held',
        'click_reference','activation_calls','explicit_pop_calls','pop_reason','natural_clear_observed',
        'first_natural_clear_frame','first_natural_clear_us','activation_info_type','activation_info_count',
        'activation_info_from_hotkey','activation_info_held','native_identity_present','native_state',
        'current_actor','current_admitted','original_incarnation','current_incarnation','direct_factory_calls','cast_calls','physicalUI'}
    events={'before_activation','after_activation','snapshot','native_dead','release_observed','restored_before_cleanup',
        'before_explicit_pop','after_explicit_pop','cleanup_skipped','before_fresh','complete'}
    world=rows[0].get('world');require(world in (1,2) and type(world) is int,'active-caster world is not sequential1/2')
    natural=None;last_active=0
    for i,row in enumerate(rows):
        _common(row,world=world)
        require(set(row)==fields and row['event'] in events and type(row['slot']) is int and row['slot']==1 and
                (row['entity'],row['unit_type'],row['army'])==(11,1,1), 'active-caster schema/event/identity differs')
        require(all(type(row[k]) is int and row[k]==v for k,v in
            (('button_slot',4),('config_id',88),('ui_cast_type',5),('ui_group_kind',2),
             ('activation_info_type',1),('activation_info_count',1),('direct_factory_calls',0),('cast_calls',0))) and
                row['smart_casting'] is False and row['activation_info_from_hotkey'] is True and row['activation_info_held'] is False,
                'active-caster original mapping/activation-info/fixture-call scope differs')
        require(all(type(row[k]) is bool for k in ('native_identity_present','current_admitted','natural_clear_observed',
                'left_held','right_held')) and not row['left_held'] and not row['right_held'] and
                type(row['pending_commands']) is int and row['pending_commands']==0 and
                _integer(row['click_reference'],0,UINT32) and row['click_reference']!=11 and
                _integer(row['activation_calls'],0,1) and _integer(row['explicit_pop_calls'],0,1) and
                _integer(row['original_incarnation'],1) and _integer(row['current_incarnation']) and
                (row['native_state'] is None or _integer(row['native_state'],0,UINT32-1)),
                'active-caster queue/gesture/counter/native observation differs')
        for stem in ('source','casting'):
            ids=row[stem+'_ids'];count=row[stem+'_count']
            require(type(ids) is list and len(ids)<=8192 and all(_integer(v,0,UINT32) for v in ids) and
                    len(ids)==len(set(ids)) and _integer(count,0,len(ids)), 'active-caster actual selector IDs/count invalid')
        current=_pointer(row['active_caster']);activated=_pointer(row['activated_caster']);actor=_pointer(row['current_actor'])
        require((actor>0 or not row['current_admitted'] and row['current_incarnation']==0) and
                (not row['current_admitted'] or row['current_incarnation']>0),'active-caster current actor/token differs')
        for key in ('activated_caster_class','active_caster_class'):
            require(row[key] is None or type(row[key]) is str and 0<len(row[key].encode('utf-8'))<=511,
                    'active-caster managed class invalid')
        require((row['activated_caster_class'] is not None)==bool(activated) and
                (row['active_caster_class'] is not None)==bool(current) and
                (type(row['is_unit_selection_related']) is bool if current else row['is_unit_selection_related'] is None) and
                row['active_relation']==('none' if not current else 'same' if current==activated else 'replaced') and
                (not current or current!=activated or row['active_caster_class']==row['activated_caster_class']),
                'active-caster null/class/Related/relation observation differs')
        require(row['pop_reason'] in (None,'explicit_cancel','post_restore_cleanup'), 'active-caster pop reason invalid')
        if row['activation_calls'] and not row['explicit_pop_calls'] and last_active and not current and natural is None:
            natural=(row['frame'],row['sampled_us'])
        require(row['natural_clear_observed']==(natural is not None) and
                (row['first_natural_clear_frame'],row['first_natural_clear_us'])==(natural if natural is not None else (None,None)),
                'active-caster first observed clear is not the actual pre-fixture-Pop transition')
        last_active=current
        if i:
            previous=rows[i-1]
            require(row['frame']>=previous['frame'] and row['tick_ms']>=previous['tick_ms'] and
                    row['sampled_us']>=previous['sampled_us'], 'active-caster clocks/frames regressed')
    names=[r['event'] for r in rows if r['event']!='snapshot']
    wanted=['before_activation','after_activation']
    if world==1:wanted+=['before_explicit_pop','after_explicit_pop']
    wanted+=['native_dead','release_observed','restored_before_cleanup']
    if world==2:wanted+=(['cleanup_skipped'] if any(r['event']=='cleanup_skipped' for r in rows) else ['before_explicit_pop','after_explicit_pop'])
    wanted+=['before_fresh','complete']
    require(names==wanted,'active-caster activation/death/restoration/cleanup event chain incomplete or duplicated')
    by_event={row['event']:row for row in rows if row['event']!='snapshot'}
    start,active=by_event['before_activation'],by_event['after_activation']
    require(start['frame']==active['frame']==145 and start['activation_calls']==0 and not _pointer(start['active_caster']) and
            not _pointer(start['activated_caster']) and start['source_ids']==[11] and start['source_count']==1 and
            not start['casting_ids'] and start['casting_count']==0 and
            active['active_relation']=='same' and _pointer(active['active_caster'])>0 and
            active['is_unit_selection_related'] is True and start['current_admitted'] and active['current_admitted'] and
            start['native_identity_present'] and active['native_identity_present'] and
            start['native_state'] not in (None,6) and active['native_state'] not in (None,6) and
            start['current_incarnation']==active['current_incarnation']==start['original_incarnation'],
            'original Perform did not activate one actual current unit-related managed caster at145')
    cleanup=by_event.get('after_explicit_pop',by_event.get('cleanup_skipped'))
    cleanup_index=rows.index(cleanup)
    for i,row in enumerate(rows):
        require(row['activation_calls']==(0 if i==0 else 1) and
                row['explicit_pop_calls']==(1 if 'after_explicit_pop' in by_event and i>=cleanup_index else 0) and
                (i==0 or (row['activated_caster'],row['activated_caster_class'],row['original_incarnation'])==
                 (active['activated_caster'],active['activated_caster_class'],active['original_incarnation'])) and
                (i<cleanup_index or not _pointer(row['active_caster'])) and
                (row['pop_reason'] is None or row['event']=='after_explicit_pop'),
                'active-caster fixture counters/root/cleanup scope changed')
        require((row['event'] in ('before_fresh','complete') or 145<=row['frame']<180),
                'active-caster observation escaped145..179')
    restored=by_event['restored_before_cleanup'];dead=by_event['native_dead'];released=by_event['release_observed']
    require(dead['native_identity_present'] and dead['native_state']==6 and
            not released['native_identity_present'] and not _pointer(released['current_actor']) and
            restored['native_identity_present'] and restored['native_state'] not in (None,6) and restored['current_admitted'] and
            restored['current_incarnation']>0 and dead['frame']<released['frame']<=restored['frame'],
            'active-caster actual native death/release/re-admission differs')
    if 'after_explicit_pop' in by_event:
        before=by_event['before_explicit_pop']
        require(_pointer(before['active_caster'])>0 and before['sampled_us']<=cleanup['sampled_us'] and
                before['frame']==cleanup['frame'] and cleanup['pop_reason']==('explicit_cancel' if world==1 else 'post_restore_cleanup') and
                (cleanup['frame']==145 if world==1 else before['active_caster']==restored['active_caster'] and
                 before['sampled_us']>=restored['sampled_us']), 'original Pop did not consume the observed current caster exactly once')
    else:
        require(world==2 and not _pointer(restored['active_caster']) and cleanup['frame']==restored['frame'] and
                cleanup['sampled_us']>=restored['sampled_us'] and cleanup['pop_reason'] is None,
                'cleanup skipped without an actual prior null100 observation')
    fresh,complete=by_event['before_fresh'],by_event['complete']
    require(fresh['frame']==180 and complete['frame']>=260 and all(not _pointer(r['active_caster']) and not r['casting_ids'] and
            r['casting_count']==0 and r['current_admitted'] for r in (fresh,complete)),
            'active-caster before-fresh/completion strict100/98 idle boundary missing')
    return dict(rows=rows,indices=indices,world=world,match=match,events=by_event,
        activation_index=indices[1],cleanup_index=indices[cleanup_index],
        restored_relation=restored['active_relation'],natural_clear_observed=natural is not None)


def _ui_residue(log, match, world):
    rows=_rows(log,'MOBILE UI RESIDUE ',match,1)
    require(len(rows)==1,'UI preactivation scratch proof missing or duplicated')
    row=rows[0]
    fields={'schema','event','world','match','slot','entity','frame','tick_ms','sampled_us','casting_set','casting_ids','casting_count',
        'casting_references_victim','typed_member11','typed_proof_error','casting_frame_collection','current_frame_collection',
        'frame_owner_matches','active_caster','pending_commands','left_held','right_held','click_reference','prior_completed_world',
        'prior_match','prior_normal_drain_complete','prior_next_sequence_before','prior_next_sequence_after','prior_complete_frame',
        'policy_result','physicalUI','scope'}
    require(set(row)==fields and type(row['schema'])is int and row['schema']==1 and row['event']=='preactivation' and
        _integer(row['world'],1,2) and row['world']==world and type(row['slot'])is int and row['slot']==1 and
        type(row['entity'])is int and row['entity']==11 and type(row['frame'])is int and row['frame']==130 and
        _integer(row['tick_ms']) and _integer(row['sampled_us']) and row['physicalUI']is False and
        row['scope']=='inactive_scratch_only_not_admission','UI preactivation scratch event/owner scope differs')
    require(all(type(row[k])is bool for k in('casting_references_victim','frame_owner_matches','left_held','right_held','prior_normal_drain_complete')) and
        (row['typed_member11']is None or type(row['typed_member11'])is bool) and
        (row['typed_proof_error']is None or type(row['typed_proof_error'])is str and len(row['typed_proof_error'])<=4096),
        'UI preactivation scratch nullable proof differs')
    require(_pointer(row['casting_set'])>0 and _pointer(row['casting_frame_collection'])>0 and
        _pointer(row['casting_frame_collection'])==_pointer(row['current_frame_collection']) and row['frame_owner_matches'] and
        not _pointer(row['active_caster']) and type(row['pending_commands'])is int and row['pending_commands']==0 and
        not row['left_held'] and not row['right_held'] and _integer(row['click_reference'],0,UINT32) and row['click_reference']!=11,
        'UI preactivation scratch is not inactive/current-frame-owned/input-idle')
    ids=row['casting_ids'];require(type(ids)is list and len(ids)<=4096 and all(_integer(v,0,UINT32)for v in ids) and
        len(set(ids))==len(ids) and (row['casting_count']is None or _integer(row['casting_count'],0,len(ids))) and
        type(row['prior_completed_world'])is int and row['prior_completed_world']in(0,1),
        'UI preactivation scratch IDs/prior world invalid')
    proof=None
    if row['prior_completed_world']==0:
        require(row['prior_normal_drain_complete']is False and all(row[k]is None for k in
            ('prior_match','prior_next_sequence_before','prior_next_sequence_after','prior_complete_frame')),
            'UI preactivation invented an absent prior-drain certificate')
    else:
        require(world==2 and type(row['prior_match'])is str and re.fullmatch('[a-f0-9]{32}',row['prior_match']) and
            row['prior_match']!=match and row['prior_normal_drain_complete']is True and
            _integer(row['prior_next_sequence_before'],1) and type(row['prior_next_sequence_after'])is int and
            row['prior_next_sequence_after']==row['prior_next_sequence_before']+1 and _integer(row['prior_complete_frame'],260,279),
            'UI preactivation prior completed/drained world certificate invalid')
        previous=_ui_cast_records(log,row['prior_match']);events=previous['events']
        require(previous['world']==1 and events['complete']['frame']==row['prior_complete_frame'] and
            events['complete']['sampled_us']<row['sampled_us'] and
            events['before_cast']['next_sequence_before_cast']==row['prior_next_sequence_before'] and
            events['normal_drain_observed']['next_sequence_after_drain']==row['prior_next_sequence_after'] and
            events['complete']['drain_observed']is True and events['complete']['pending_commands']==0 and
            events['complete']['casting_ids']==[11],
            'UI preactivation prior certificate does not bind real first-world normal drain/completion/residue')
        proof=dict(world=1,match=row['prior_match'],normal_drain_sampled_us=events['normal_drain_observed']['sampled_us'],
            complete_sampled_us=events['complete']['sampled_us'],next_before=row['prior_next_sequence_before'],next_after=row['prior_next_sequence_after'])
    require(row['typed_proof_error']is None and row['casting_count']is not None,'UI preactivation original typed scratch proof failed')
    if row['policy_result']=='strict_empty':
        require(not ids and row['casting_references_victim']is False and row['typed_member11']is False,
            'UI strict-empty preactivation scratch still references11')
    else:
        require(row['policy_result']=='prior_drained_residue' and world==2 and proof is not None and ids==[11] and
            row['typed_member11']is True,
            'UI residue is not exact11 from a qualified prior completed/drained world')
    indices=[i for i,line in enumerate(log.splitlines())if 'MOBILE UI RESIDUE 'in line and
        json.loads(line.split('MOBILE UI RESIDUE ',1)[1],object_pairs_hook=_unique_object).get('match')==match]
    return dict(row=row,index=indices[0],prior_drain=proof,
        scope='Current inactive numeric/typed scratch and frame owner only; no cross-world same-storage/actor/incarnation or admission claim')


def _ui_cast_records(log, match):
    rows=_rows(log,'MOBILE UI CAST ',match,2048);require(rows,'missing original UI cast receipts')
    indices=[i for i,line in enumerate(log.splitlines())if 'MOBILE UI CAST ' in line and
        json.loads(line.split('MOBILE UI CAST ',1)[1],object_pairs_hook=_unique_object).get('match')==match]
    events={'before_activation','after_activation','snapshot','native_dead','release_observed','restored','before_cast',
        'after_cast_queued','normal_drain_observed','complete'}
    names=['before_activation','after_activation','native_dead','release_observed','restored','before_cast',
        'after_cast_queued','normal_drain_observed','complete']
    require([r.get('event')for r in rows if r.get('event')!='snapshot']==names,'UI original activation/cast/drain lifecycle incomplete or duplicated')
    by_event={r['event']:r for r in rows if r['event']!='snapshot'};world=rows[0].get('world')
    require(_integer(world,1,2),'UI world is not sequential1/2')
    residue=_ui_residue(log,match,world)
    fields={'schema','event','world','match','slot','entity','unit_type','army','frame','tick_ms','sampled_us','button_slot','config_id',
        'ui_cast_type','ui_group_kind','smart_casting','retained_caster','retained_caster_class','active_caster','active_caster_class',
        'same_retained','is_unit_selection_related','source_set','casting_set','command_queue','alias_storage_unchanged','source_ids',
        'source_count','casting_ids','casting_count','pending_commands','activation_calls','cast_calls','drain_observed',
        'next_sequence_before_cast','next_sequence_after_drain','cast_result','origin','origin_bits','target','target_bits','origin_sampled_us',
        'minimap_call_begin_us','minimap_call_end_us','local_alliance','map_perspective','composite_map_perspective',
        'composite_queue_cast_before','perspective_observed_frame','map_perspective_source','composite_map_perspective_source',
        'map_perspective_enum','map_perspective_enum_matches_composite','map_perspective_normal','map_perspective_flipped',
        'map_perspective_value_name','selector_append','left_held','right_held','click_reference','native_identity_present','native_state',
        'current_actor','current_admitted','original_incarnation','current_incarnation','route','original_callback','original_callback_token',
        'originalCtor','extra_pop_calls','extra_to_proto_calls','manual_caster_set_calls','direct_factory_calls','physicalUI'}
    active=by_event['after_activation'];before=by_event['before_cast'];queued=by_event['after_cast_queued'];drain=by_event['normal_drain_observed']
    active_i=rows.index(active);before_i=rows.index(before);queued_i=rows.index(queued);drain_i=rows.index(drain)
    for i,row in enumerate(rows):
        _common(row,world=world)
        require(set(row)==fields and row['event'] in events and type(row['slot'])is int and row['slot']==1 and
            (row['entity'],row['unit_type'],row['army'])==(11,1,1) and 145<=row['frame']<280,'UI schema/event/identity/frame differs')
        require(all(type(row[k])is int and row[k]==v for k,v in(('button_slot',4),('config_id',88),('ui_cast_type',5),('ui_group_kind',2),
            ('extra_pop_calls',0),('extra_to_proto_calls',0),('manual_caster_set_calls',0),('direct_factory_calls',0),('original_callback_token',0x0600222a))) and
            row['route']=='original_ui_minimap' and row['original_callback']=='Uncapped.UnitSelector.ProcessActiveAbilityCaster_Minimap' and
            row['originalCtor'] is False and row['smart_casting'] is False,'UI original mapping/callback/fixture-only scope differs')
        require(all(type(row[k])is bool for k in('same_retained','alias_storage_unchanged','selector_append','left_held','right_held',
            'native_identity_present','current_admitted','drain_observed')) and row['alias_storage_unchanged'] and
            not row['left_held'] and not row['right_held'] and _integer(row['click_reference'],0,UINT32) and row['click_reference']!=11 and
            _integer(row['original_incarnation'],1) and _integer(row['current_incarnation']) and
            (row['native_state']is None or _integer(row['native_state'],0,UINT32-1)),'UI owner/gesture/native scalar differs')
        for stem in('source','casting'):
            ids=row[stem+'_ids'];count=row[stem+'_count']
            require(type(ids)is list and len(ids)<=8192 and all(_integer(v,0,UINT32)for v in ids) and
                len(set(ids))==len(ids) and _integer(count,0,len(ids)),'UI original IDs/resolvable count invalid')
        pointers=tuple(_pointer(row[k])for k in('source_set','casting_set','command_queue'))
        require(all(pointers) and pointers[0]!=pointers[1] and all(row[k]==rows[0][k] for k in
            ('source_set','casting_set','command_queue','original_incarnation')),'UI lazy storage roots were replaced or aliased incorrectly')
        require(_pointer(row['casting_set'])==_pointer(residue['row']['casting_set']) and
            row['sampled_us']>=residue['row']['sampled_us'],'UI preactivation scratch does not bind current-world casting storage')
        current=_pointer(row['active_caster']);retained=_pointer(row['retained_caster']);actor=_pointer(row['current_actor'])
        require((actor>0 or not row['current_admitted'] and row['current_incarnation']==0) and
            (not row['current_admitted'] or row['current_incarnation']>0),'UI current actor/admission token differs')
        for key in('retained_caster_class','active_caster_class'):
            require(row[key]is None or type(row[key])is str and 0<len(row[key].encode('utf-8'))<=511,'UI managed caster class invalid')
        require((row['retained_caster_class']is not None)==bool(retained) and (row['active_caster_class']is not None)==bool(current) and
            (type(row['is_unit_selection_related'])is bool if current else row['is_unit_selection_related']is None) and
            row['same_retained']==bool(current and current==retained),'UI actual caster/null/Related observation differs')
        require(type(row['activation_calls'])is int and row['activation_calls']==(0 if i<active_i else 1) and
            type(row['cast_calls'])is int and row['cast_calls']==(0 if i<queued_i else 1) and
            row['drain_observed']==(i>=drain_i),'UI fixture invocation/drain counters changed')
        if i<active_i:
            initial_scratch_ok=(not row['casting_ids'] and row['casting_count']==0) or (
                residue['row']['policy_result']=='prior_drained_residue' and row['casting_ids']==[11])
            require(not current and not retained and row['source_ids']==[11] and row['source_count']==1 and
                initial_scratch_ok,'UI activation was not originally inactive/prior-drained scratch/source11Count1')
        else:
            require(row['retained_caster']==active['retained_caster'] and row['retained_caster_class']==
                active['retained_caster_class']=='Uncapped.TargetGroundOrUnitAbilityCaster' and retained>0 and
                (row['same_retained'] and row['active_caster_class']==row['retained_caster_class'] if i<queued_i else not current),
                'UI original retained100 was cleared/replaced before cast or reappeared after auto-Pop')
        require(_integer(row['pending_commands'],0,1) and (queued_i<=i<drain_i or row['pending_commands']==0),
            'UI pending queue escaped its queued→normal-drain phase')
        require(row['next_sequence_before_cast']is None if i<before_i else _integer(row['next_sequence_before_cast'],1) and
                row['next_sequence_before_cast']==before['next_sequence_before_cast'],'UI captured NEXT sequence changed')
        require(row['next_sequence_after_drain']is None if i<drain_i else row['next_sequence_after_drain']==before['next_sequence_before_cast']+1 and
                type(row['next_sequence_after_drain'])is int,'UI normal-drain NEXT sequence missing/changed')
        require(row['cast_result']is None if i<queued_i else row['cast_result']is True,'UI original Minimap did not return actualtrue')
        if i>=queued_i and i<=drain_i:
            require(row['source_ids']==queued['source_ids']==[11] and row['casting_ids']==queued['casting_ids']==[11],
                'UI lazy source/casting IDs changed before normal serialize')
        if i:
            previous=rows[i-1];require(row['frame']>=previous['frame'] and row['tick_ms']>=previous['tick_ms'] and
                row['sampled_us']>=previous['sampled_us'],'UI observation clocks/physical frames regressed')
        perspective_keys=('local_alliance','map_perspective','composite_map_perspective','composite_queue_cast_before',
            'perspective_observed_frame','map_perspective_enum_matches_composite','map_perspective_value_name')
        require(row['map_perspective_source']=='Uncapped.Map.GetAlliancePerspective' and
            row['composite_map_perspective_source']=='Uncapped.CompositeAbilityCaster.get_MapPerspective' and
            row['map_perspective_enum']=='Uncapped.Map.Perspective' and type(row['map_perspective_normal'])is int and row['map_perspective_normal']==0 and
            type(row['map_perspective_flipped'])is int and row['map_perspective_flipped']==1,'UI original map/Composite source/literals differ')
        if i<active_i:require(all(row[k]is None for k in perspective_keys),'UI invented a perspective before original caster activation')
        else:
            require(_integer(row['local_alliance'],0,UINT32) and type(row['map_perspective'])is int and row['map_perspective']in(0,1) and
                type(row['composite_map_perspective'])is int and row['composite_map_perspective']in(0,1) and
                type(row['composite_queue_cast_before'])is bool and row['map_perspective_enum_matches_composite']is True and
                type(row['perspective_observed_frame'])is int and row['perspective_observed_frame']==(145 if i<before_i else 180) and
                row['map_perspective_value_name']==('Normal'if row['map_perspective']==0 else'Flipped'),'UI actual Composite/runtime map enum proof differs')
            # These are actual independent pre-command values. The getter
            # return enum CLASS matches; original Minimap owns initialization.
            # Cached145/180 observations are not post-call property samples.
            # The normal serialized target is bound to actual Map below.
            reference=active if i<before_i else before
            require(all(row[k]==reference[k]for k in perspective_keys),'UI stored perspective proof changed without original getter observation')
        target_keys=('origin','origin_bits','target','target_bits','origin_sampled_us')
        if i<before_i:require(all(row[k]is None for k in target_keys),'UI invented an origin/target before original sample')
        else:
            for key in('origin','target'):
                _vector(row[key]);bits=row[key+'_bits']
                require(type(bits)is list and len(bits)==3 and all(_integer(b,0,UINT32)for b in bits) and
                    all(_reported_bits_match(v,b)for v,b in zip(row[key],bits)),'UI captured target/origin float32 bits differ')
            require(_integer(row['origin_sampled_us']) and all(row[k]==before[k]for k in target_keys),
                'UI retained actual origin/target sample changed')
        require(all(row[k]is None for k in('minimap_call_begin_us','minimap_call_end_us'))if i<queued_i else
            all(_integer(row[k]) and row[k]==queued[k]for k in('minimap_call_begin_us','minimap_call_end_us')),
            'UI original call QPC bracket missing or altered')
    start=by_event['before_activation'];dead=by_event['native_dead'];released=by_event['release_observed'];restored=by_event['restored']
    require(start['frame']==active['frame']==145 and active['is_unit_selection_related']is True and
        all(r['current_admitted'] and r['native_identity_present'] and r['native_state']not in(None,6) and
            r['source_ids']==[11] and r['source_count']==1 and r['current_incarnation']==r['original_incarnation'] for r in(start,active,restored,before)) and
        dead['native_identity_present'] and dead['native_state']==6 and not released['native_identity_present'] and
        not _pointer(released['current_actor']) and dead['frame']<released['frame']<=restored['frame']<before['frame']==queued['frame']==180,
        'UI activation/correction/current original source11 lifecycle differs')
    require(not before['selector_append'] and not queued['selector_append'] and before['composite_queue_cast_before']is False and
        before['pending_commands']==0 and queued['pending_commands']==1 and queued['casting_count']==1 and
        before['origin_sampled_us']<=before['sampled_us']<=queued['minimap_call_begin_us']<queued['minimap_call_end_us']<=queued['sampled_us'] and
        before['current_actor']==queued['current_actor'] and before['current_incarnation']==queued['current_incarnation'],
        'UI original call/queue0→1/auto-Pop/current lease bracket differs')
    expected=[_f32(_f32(before['origin'][0])+16),_f32(before['origin'][1]),_f32(before['origin'][2])]
    require(all(_reported_bits_match(v,b)for v,b in zip(expected,before['target_bits'])),'UI target is not actual sampled origin plus bounded16X')
    require(by_event['complete']['frame']>=260 and drain['pending_commands']==0 and
        all(r['pending_commands']==0 and not _pointer(r['active_caster'])for r in rows[drain_i:]),'UI normal drain/complete did not remain inactive')
    return dict(rows=rows,indices=indices,events=by_event,world=world,match=match,
        activation_index=indices[active_i],queued_index=indices[queued_i],drain_index=indices[drain_i],preactivation_residue=residue)


def _snapshots(log, match, *, caster_lifetime=False, _ui=None):
    require(type(caster_lifetime) is bool,'invalid active-caster observation option')
    lifetime=_caster_lifetime_records(log,match) if caster_lifetime else None
    mobile_indices=[]
    if lifetime or _ui:
        for index,line in enumerate(log.splitlines()):
            if 'MOBILE CORRECTION ' in line and json.loads(line.split('MOBILE CORRECTION ',1)[1],object_pairs_hook=_unique_object).get('match')==match:
                mobile_indices.append(index)
    rows = _rows(log, 'MOBILE CORRECTION ', match, 2048)
    require(rows, 'missing original mobile episode')
    world = rows[0].get('world')
    require(lifetime is None or lifetime['world']==world,'active-caster/mobile world binding differs')
    require(_ui is None or _ui['world']==world and not caster_lifetime,'UI-cast/mobile world/mode differs')
    events=UI_EVENTS if _ui else EVENTS
    bool_fields = ('old_dead_to_sim', 'old_component_present', 'old_in_active', 'old_in_retained',
        'current_in_active', 'current_admitted', 'native_identity_present', 'native_state_present',
        'casting_references_victim', 'auto_type1', 'left_held', 'right_held', 'pool_callback_observed')
    for row_index,row in enumerate(rows):
        _common(row, world=world)
        require(row.get('event') in (*events, 'snapshot') and
                (row['entity'], row['unit_type'], row['army']) == (11, 1, 1) and
                _integer(row.get('completed_frame'), -1, 2**31-1), 'mobile episode event/identity differs')
        require('selection_scope_player_initiated' in row and
                (row['selection_scope_player_initiated'] is None or type(row['selection_scope_player_initiated']) is bool),
                'original selection scope provenance missing')
        require(all(type(row.get(k)) is bool for k in bool_fields), 'missing mobile observed boolean')
        for key in ('original_actor', 'current_actor', 'active_caster', 'focus_actor'):
            _pointer(row.get(key))
        require(_pointer(row['original_actor']) > 0 and
                _integer(row.get('original_incarnation'), 1) and _integer(row.get('current_incarnation')) and
                _integer(row.get('original_actual_entity'), 0, UINT32), 'missing original lease/token')
        for key in ('selected_ids', 'preview_ids', 'casting_ids', 'group_ids', 'tracked_released_ids'):
            values = row.get(key)
            require(type(values) is list and len(values) <= 4096 and len(values) == len(set(values)) and
                    all(_integer(v, 0, UINT32) for v in values), 'invalid original selection/group ID set')
        require(_integer(row.get('focus_group'), -1, 15) and
                _integer(row.get('pending_commands'), 0, 256) and _integer(row.get('live_click_id'), 0, UINT32),
                'invalid observed selector scalar')
        active_window=bool(lifetime and lifetime['activation_index']<mobile_indices[row_index]<lifetime['cleanup_index'] and
            lifetime['events']['after_activation']['sampled_us']<=row['sampled_us']<=lifetime['events'].get('after_explicit_pop',lifetime['events'].get('cleanup_skipped'))['sampled_us'] and 145<=row['frame']<180)
        scratch_window=bool(lifetime and lifetime['activation_index']<mobile_indices[row_index] and
            row['sampled_us']>=lifetime['events']['after_activation']['sampled_us'] and 145<=row['frame']<180)
        if _ui:
            active_window=bool(_ui['activation_index']<mobile_indices[row_index]<_ui['queued_index'] and
                _ui['events']['after_activation']['sampled_us']<=row['sampled_us']<=_ui['events']['after_cast_queued']['sampled_us'] and 145<=row['frame']<=180)
            scratch_window=bool(_ui['activation_index']<mobile_indices[row_index] and
                row['sampled_us']>=_ui['events']['after_activation']['sampled_us'] and 145<=row['frame']<=_ui['events']['complete']['frame'])
            residue=_ui['preactivation_residue']
            if residue['row']['policy_result']=='prior_drained_residue' and 130<=row['frame']<=145 and mobile_indices[row_index]<_ui['activation_index']:
                require(residue['index']<mobile_indices[row_index] and residue['row']['sampled_us']<=row['sampled_us'] and
                    row['casting_ids'] in ([],[11]),'UI preactivation scratch escaped its actual prior-drain proof')
                scratch_window=True
            queue_window=bool(_ui['events']['before_cast']['sampled_us']<=row['sampled_us']<=_ui['events']['normal_drain_observed']['sampled_us'] and
                180<=row['frame']<=_ui['events']['normal_drain_observed']['frame'])
            require(row['pending_commands'] in ((0,1) if queue_window else (0,)), 'UI queue1 escaped the validated normal-drain interval')
            if _pointer(row['active_caster']):
                require(_pointer(row['active_caster'])==_pointer(_ui['events']['after_activation']['retained_caster']),
                        'UI snapshot replaced the retained actual caster')
        if active_window and _pointer(row['active_caster']):
            witness=lifetime or _ui
            require(any(index>mobile_indices[row_index] and receipt['frame']==row['frame'] and
                receipt['sampled_us']>=row['sampled_us'] and _pointer(receipt['active_caster'])==_pointer(row['active_caster'])
                for index,receipt in zip(witness['indices'],witness['rows'])),
                'mobile active100 lacks its actual same-frame lifetime observation')
        require(row['pool_callback_observed'] is False and not row['left_held'] and not row['right_held'] and
                row['live_click_id'] != 11 and (active_window or not _pointer(row['active_caster'])) and
                (scratch_window or not row['casting_ids'] and not row['casting_references_victim']),
                'unexercised caster/gesture/pool-callback scope was crossed')
        require(row['native_state_present'] == (row.get('native_state') is not None) and
                (row['native_state'] is None or _integer(row['native_state'], 0, UINT32-1)),
                'invalid actual native state presence')
        actual = tuple(row.get('current_actual_' + key) for key in ('entity', 'type', 'army'))
        if row['current_in_active']:
            require(_pointer(row['current_actor']) > 0 and actual == (11, 1, 1), 'current actor identity differs')
        else:
            require(not _pointer(row['current_actor']) and actual == (None, None, None) and
                    not row['current_admitted'] and row['current_incarnation'] == 0,
                    'inactive actor masquerades as a current lease')
        if row['current_admitted']:
            require(row['current_in_active'] and row['current_incarnation'] > 0,
                    'admission lacks current actor/token')
        native = row.get('native_identity_type'), row.get('native_identity_army')
        require(native == ((1, 1) if row['native_identity_present'] else (None, None)),
                'observed native identity differs')
    require(all(b['frame'] >= a['frame'] and b['tick_ms'] >= a['tick_ms'] and
                b['sampled_us'] > a['sampled_us'] for a, b in zip(rows, rows[1:])),
            'mobile observation clocks/physical frames regressed')
    require(len({(_pointer(r['original_actor']), r['original_incarnation']) for r in rows}) == 1,
            'original mobile root/token changed')
    episode = [r for r in rows if r['event'] != 'snapshot']
    require([r['event'] for r in episode] == list(events), 'incomplete/duplicate original mobile episode')
    setup, dead, released, restored, before, reselected, complete = episode
    if _ui:
        residue=_ui['preactivation_residue']
        require(residue['row']['sampled_us']<=setup['sampled_us'] and residue['index']<mobile_indices[0],
            'UI preactivation proof did not precede original setup')
    require(setup['frame'] == 130 and dead['frame'] >= 153 and released['frame'] > dead['frame'] and
            restored['frame'] >= released['frame'] and 180 <= before['frame'] < 200 and
            before['frame'] == reselected['frame'] and complete['frame'] >= 260,
            'mobile episode physical boundaries differ')
    require(setup['original_actual_entity'] == 11 and setup['selected_ids'] == [11] and
            11 in setup['group_ids'] and setup['focus_group'] == 4 and
            _pointer(setup['focus_actor']) == _pointer(setup['original_actor']) == _pointer(setup['current_actor']) and
            setup['current_admitted'] and setup['current_incarnation'] == setup['original_incarnation'],
            'original mobile selection/group/repeat focus was not established')
    require(setup['selection_scope_player_initiated'] is True and
            (reselected['selection_scope_player_initiated'] is None if _ui else reselected['selection_scope_player_initiated'] is False) and
            all(r['selection_scope_player_initiated'] is None for r in rows
                if r['event'] not in (('original_mobile_selection_established',) if _ui else
                    ('original_mobile_selection_established', 'original_fresh_reselection_established'))),
            'fresh original programmatic selection scope differs from explicit initial player-initiated scope')
    require(dead['native_state_present'] and dead['native_state'] == 6 and
            not released['native_identity_present'] and not released['old_in_active'] and
            not released['old_in_retained'] and not released['old_component_present'],
            'original mobile death/release did not occur')
    require(restored['native_identity_present'] and restored['native_state_present'] and restored['native_state'] != 6 and
            restored['current_in_active'] and restored['current_admitted'], 'mobile was not reinitialized/admitted')
    lease = _pointer(restored['current_actor']), restored['current_incarnation']
    require(all((_pointer(r['current_actor']), r['current_incarnation']) == lease and r['current_admitted'] and
                r['current_in_active'] for r in (before, reselected, complete)) and reselected['selected_ids'] == [11],
            'fresh selection uses a stale/unadmitted mobile lease')
    require(all(r['pending_commands'] == (1 if _ui and r['event']=='original_ui_cast_queued' else 0) for r in episode[:-1]),
            'unrelated queued input crossed setup/reselection')
    focus_observations = []
    for row in rows:
        # FrontUpdate precedes later original selector work. The actual cache
        # in a death/release/first-restored frame is an observation, not a
        # whole-Unity-frame safety assertion. Do not clear it to fit the test.
        transient = dead['frame'] <= row['frame'] <= restored['frame'] and row['event'] not in (
            'before_fresh_reselection', 'original_fresh_reselection_established', 'mobile_observation_complete')
        focus_observations.append(_focus_observation(row, transient=transient))
    require(focus_observations[0]['classification'] == 'would_focus_valid_camera_lease' and
            (setup['focus_actual_entity'], setup['focus_actual_type'], setup['focus_actual_army']) == (11, 1, 1) and
            setup['focus_observed_incarnation'] == setup['current_incarnation'],
            'initial repeat-focus setup lacks original predicates/current-lease proof')
    return rows, episode, focus_observations


def _receipt(frame, world, match, rows, bridges, payloads):
    own = [r for r in rows if (r.get('match'), r.get('world'), r.get('frame')) == (match, world, frame)]
    wire = [r for r in bridges if (r.get('match'), r.get('frame')) == (match, frame)]
    require(len(own) == len(wire) == 1 and _integer(own[0].get('tick_ms')) and
            _integer(wire[0].get('received_tick_ms')) and type(payloads.get(frame)) is str and
            HEX64.fullmatch(payloads[frame]) and own[0].get('wire_sha256') == wire[0].get('payload_sha256') == payloads[frame],
            'actual victim65/raw bridge/authoritative wire differs')
    return own[0], wire[0]


def _joined(check, rows, *, world, receipt, states, journal, action_hash, slot, replay, latest_tick=None):
    result = check(rows, world=world, authority=receipt, canonical_states=states, require_replay=replay)
    indices = result.get('promotion_group_row_indices')
    require(type(indices) is list and indices and len(indices) == len(set(indices)) and
            all(_integer(i, 0, len(rows)-1) for i in indices), 'invalid confirmed replay group indices')
    group = [rows[i] for i in indices]
    frame = receipt['frame']
    require(sum(r['frame'] == frame for r in group) == 1 and
            all(r['world'] == world and r['parsed_state_sha256'] == states.get(r['frame']) and
                r['tick_ms'] >= receipt['tick_ms'] and (latest_tick is None or r['tick_ms'] <= latest_tick) for r in group),
            'correction group lacks its own canonical command/hash/time')
    require(not replay or sum(r['replayed_frames_delta'] for r in group) > 0,
            'canonical correction has no actual replay')
    numbers = {r['frame'] for r in group}
    require(len(numbers) == len(group) and numbers == set(range(min(numbers), max(numbers)+1)),
            'canonical promotion group is not contiguous')
    actions = [(r['frame'], s, digest(a)) for r in journal if r['frame'] in numbers
               for s, values in r['players'].items() for a in values]
    require(actions == [(frame, slot, action_hash)], 'replay group has unrelated/missing canonical actions')
    tail = result.get('continuation_row_indices')
    frontier = max(numbers)
    require(type(tail) is list and len(tail) == 20 and all(_integer(i, 0, len(rows)-1) for i in tail) and
            [rows[i]['frame'] for i in tail] == list(range(frontier+1, frontier+21)) and
            all(rows[i]['world'] == world and rows[i]['parsed_state_sha256'] == states.get(rows[i]['frame']) and
                rows[i]['tick_ms'] >= group[-1]['tick_ms'] for i in tail),
            '20 actual canonical native continuations missing/mismatched')
    return dict(result, group=group, input_actions=[dict(frame=f, slot=s, action_sha256=h) for f, s, h in actions])


def _fresh_binding(log, order, *, match, commits, raw_bodies, journal):
    perspective = _perspective(order)
    sha = order['action_sha256']
    candidates = []
    for (m, slot, sequence), body in raw_bodies.items():
        if (m, slot) != (match, 1):
            continue
        decoded = decode_player_input(body)
        if any(digest(a) == sha for a in decoded['actions']):
            require(len(decoded['actions']) == 1 and decoded['identity']['player_id'] == 2 and
                    decoded['identity']['is_aliased'] and not decoded['identity']['ai_profile_id'],
                    'fresh72 must be one exact original action for the victim human')
            candidates.append((sequence, body, decoded['actions'][0]))
    require(len(candidates) == 1, 'fresh original command missing/duplicated in72')
    sequence, body, action = candidates[0]
    require([f.number for f in parse_fields(action)] == [1], 'fresh command is not original Execute')
    execute = get_bytes(action, 1, required=True)
    groups = get_repeated_bytes(execute, 1)
    require(len(groups) == 1 and get_uint(groups[0], 1) == 1 and get_uint(groups[0], 2) == 12 and
            get_repeated_uint(groups[0], 3) == (11,) and get_uint(execute, 2) == 0,
            'fresh source/type/ability/queued differs')
    command = get_bytes(execute, 3, required=True)
    require([f.number for f in parse_fields(command)] == [3], 'fresh target is not ground')
    position = get_bytes(get_bytes(command, 3, required=True), 1, required=True)
    target = []; target_raw = []
    for n in (1, 2, 3):
        value = get_uint(position, n)
        require(value < 2**64, 'fresh target exceeds signed Q32.32')
        signed = value-2**64 if value >= 2**63 else value
        target_raw.append(signed); target.append(signed/2**32)
    require(all(_reported_bits_match(v, bits) for v, bits in zip(order['target'], order['target_bits'])),
            'fresh captured original float32 target bits differ')
    # pointJson's nine decimal digits round-trip float32, not Python's exact
    # binary64 comparison. Fixed-point cannot retain sub-Q32 float components:
    # require exact raw integers on representable axes and a bracketing single
    # Q32 quantum otherwise. Do not claim float-bit equality after quantization.
    unity_target = [struct.unpack('<f', struct.pack('<I', bits))[0] for bits in order['target_bits']]
    # Original ExecuteTargetGroundCommand.ToProto -> ProtocolUtil.ToProto:
    # Flipped negates X/Z, preserves Y. Use the actual runtime getter enum;
    # neither army numbering nor the observed camera target selects this map.
    mapped_target = [(-v if perspective['map_perspective'] == 1 and axis in (0, 2) else v)
                     for axis, v in enumerate(unity_target)]
    quantization = [dict(float32=v, fixed_raw=raw, difference_raw=raw-v*2**32)
                    for v, raw in zip(mapped_target, target_raw)]
    require(all(math.floor(r['float32']*2**32) <= r['fixed_raw'] <= math.ceil(r['float32']*2**32)
                for r in quantization), 'fresh original ToProto fixed-point target differs')
    registrations = re.findall(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) '
        r'tick=(\d+) match=' + re.escape(match) + r'(?:\s|$)', log)
    registered = [tuple(map(int, r)) for r in registrations if int(r[0]) == sequence]
    sent = re.findall(r'Original command batch submitted: match=' + re.escape(match) +
        r' sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)', log)
    sent = [r for r in sent if int(r[0]) == sequence]
    require(len(registered) == len(sent) == 1 and registered[0][2] >= order['tick_ms'] and
            int(sent[0][1]) == 1 and int(sent[0][2]) == len(body) and sent[0][3] == digest(body) and
            int(sent[0][4]) >= registered[0][2], 'fresh actual67/native72 sender/body differs')
    accepted = [r for r in commits if (r.get('event'), r.get('match'), r.get('slot'), r.get('sequence')) ==
                ('command_batch_committed', match, 1, sequence)]
    require(len(accepted) == 1 and _integer(accepted[0].get('frame'), 0, 2**31-1), 'fresh canonical commit missing/duplicated')
    frame = accepted[0]['frame']
    require(abs(registered[0][1]-frame) <= 1, 'fresh steady actual67/canonical phase exceeds one frame')
    occurrences = [(r['frame'], slot) for r in journal for slot, values in r['players'].items()
                   for a in values if digest(a) == sha]
    require(occurrences == [(frame, 1)], 'fresh canonical journal is duplicated/rebound/missing')
    return dict(order=order, sequence=sequence, action_sha256=sha, body_sha256=digest(body),
        speculative_frame=registered[0][1], canonical_commit_frame=frame,
        speculative_minus_canonical_frames=registered[0][1]-frame, native67_tick_ms=registered[0][2],
        native72_send_tick_ms=int(sent[0][4]), target=target, unity_target=unity_target,
        protocol_target_expected=mapped_target, perspective_proof=perspective, target_quantization=quantization,
        json_zero_sign_loss_axes=[i for i, (v, bits) in enumerate(zip(order['target'], order['target_bits']))
                                  if v == 0 and bits == 0x80000000 and _bits(v) != bits],
        target_scope='Captured Unity float32 bits authoritative; JSON cannot prove zero sign. Original runtime Perspective maps X/Z for ToProto; signed Q32.32 exact when representable, otherwise adjacent quantization bracket')


def _fresh_motion(log, match, world, token, order, restored, receipt, bridge):
    poses = _rows(log, 'MOBILE FEEL ', match, 1024)
    for row in poses:
        _common(row, world=world)
        require(row.get('event') == 'transform' and (row['entity'], row['unit_type'], row['army']) == (11, 1, 1) and
                row.get('incarnation') == token and type(row.get('incarnation')) is int and row.get('move_id') == 1 and
                type(row.get('baseline')) is bool and row.get('source') == 'UnityEngine.Transform.get_position' and
                row.get('jobsJoined') is True and _integer(row.get('presented_frame'), -1, 2**31-1) and
                _integer(row.get('completed_frame'), -1, 2**31-1) and row['presented_frame'] == row['frame'],
                'fresh actual Transform owner/token/clock/source differs')
        _vector(row.get('position'))
    require(all(b['sampled_us'] > a['sampled_us'] and b['tick_ms'] >= a['tick_ms'] and
                b['presented_frame'] >= a['presented_frame'] for a, b in zip(poses, poses[1:])),
            'actual Transform clocks/frames regressed')
    baseline = [r for r in poses if r['baseline'] and restored['sampled_us'] <= r['sampled_us'] <= order['sampled_us']]
    require(baseline and baseline[-1]['sampled_us'] >= order['sampled_us']-50_000 and
            baseline[0]['sampled_us'] <= order['sampled_us']-200_000, 'fresh Move has no actual 200ms pre-enqueue baseline')
    quiet = [r for r in baseline if r['sampled_us'] >= order['sampled_us']-200_000]
    require(len(quiet) >= 3 and quiet[-1]['sampled_us']-quiet[0]['sampled_us'] >= 150_000,
            'fresh quiet baseline is sparse/incomplete')
    drift = max(math.dist(r['position'], order['origin']) for r in quiet)
    require(drift <= .025, 'fresh response could be ongoing pre-command auto-chase motion')
    cutoff = min(receipt['tick_ms'], bridge['received_tick_ms'])
    after = [r for r in poses if not r['baseline'] and r['sampled_us'] > order['enqueue_sampled_us'] and r['tick_ms'] < cutoff]
    direction = [b-a for a, b in zip(order['origin'], order['target'])]
    distance = math.sqrt(sum(v*v for v in direction))
    require(distance > .25, 'fresh Move target was already reached')
    response = [r for r in after if sum((v-o)*d for v, o, d in zip(r['position'], order['origin'], direction))/distance > .025]
    require(response, 'fresh current actor has no NEW targetward motion before both65 and raw bridge')
    first = response[0]
    return dict(passed=True, baseline_rows=quiet, baseline_max_drift=drift, first_new_motion=first,
        enqueue_return_us=order['enqueue_sampled_us'], response_after_enqueue_ms=(first['sampled_us']-order['enqueue_sampled_us'])/1000,
        before_native65_ms=receipt['tick_ms']-first['tick_ms'], before_raw_bridge_ms=bridge['received_tick_ms']-first['tick_ms'],
        pose_count=len(poses), clock_scope='Actual same-process checked QPC Transform samples;65/bridge ordering uses strict recorded tick_ms')


def _ui_binding(log, witness, *, match, commits, raw_bodies, journal):
    """One normal serialized original UI action;67's frame is not prediction."""
    before=witness['events']['before_cast'];after=witness['events']['after_cast_queued'];drain=witness['events']['normal_drain_observed']
    sequence=before['next_sequence_before_cast']
    require(_integer(sequence,1) and drain['next_sequence_after_drain']==sequence+1,
            'UI normal input drain did not advance exactly the captured NEXT sequence')
    body=raw_bodies.get((match,1,sequence));require(type(body) is bytes,'UI original72 body is missing')
    decoded=decode_player_input(body)
    require(len(decoded['actions'])==1 and decoded['identity']['player_id']==2 and decoded['identity']['is_aliased'] and
            not decoded['identity']['ai_profile_id'],'UI72 is not one exact original victim-human action')
    action=decoded['actions'][0];action_hash=digest(action)
    require([f.number for f in parse_fields(action)]==[1],'UI original command is not Execute')
    execute=get_bytes(action,1,required=True);groups=get_repeated_bytes(execute,1)
    require(len(groups)==1 and get_uint(groups[0],1)==1 and get_uint(groups[0],2)==88 and
            get_repeated_uint(groups[0],3)==(11,) and get_uint(execute,2)==0,
            'UI source/type/ability88/unqueued original body differs')
    from client_patch.prediction_worker.commands import _action
    normalized,predictive,join=_action(action,1)
    require(normalized==action and predictive is False and join is False,'UI88 body changed or became prediction eligible')
    command=get_bytes(execute,3,required=True)
    require([f.number for f in parse_fields(command)]==[3],'UI minimap original target is not ground')
    position=get_bytes(get_bytes(command,3,required=True),1,required=True)
    raw=[]
    for axis in(1,2,3):
        value=get_uint(position,axis);require(value<2**64,'UI target exceeds signedQ32')
        raw.append(value-2**64 if value>=2**63 else value)
    target=[struct.unpack('<f',struct.pack('<I',bits))[0]for bits in before['target_bits']]
    mapped=[-value if before['map_perspective']==1 and axis in(0,2)else value for axis,value in enumerate(target)]
    require(all(math.floor(value*2**32)<=fixed<=math.ceil(value*2**32)for value,fixed in zip(mapped,raw)),
            'UI actual normal ToProto target differs from mapped original float32 target')
    registered=[];sent=[]
    for index,line in enumerate(log.splitlines()):
        found=re.search(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) tick=(\d+) match='+re.escape(match)+r'(?:\s|$)',line)
        if found and int(found[1])==sequence:registered.append((index,tuple(map(int,found.groups()))))
        found=re.search(r'Original command batch submitted: match='+re.escape(match)+r' sequence=(\d+) actions=(\d+) bytes=(\d+) body_sha256=([a-f0-9]{64}) sendTick=(\d+) sourceNextFrame=(\d+)',line)
        if found and int(found[1])==sequence:sent.append((index,found.groups()))
    require(len(registered)==len(sent)==1,'UI actual67/native72 receipt missing or duplicated')
    registration_index,registration=registered[0];send_index,send=sent[0]
    require(witness['queued_index']<registration_index<send_index<witness['drain_index'] and
            before['tick_ms']<=registration[2]<=int(send[4])<=drain['tick_ms'] and
            int(send[1])==1 and int(send[2])==len(body) and send[3]==digest(body),
            'UI normal drain/body is not source-ordered after queued input and before actual drain observation')
    accepted=[r for r in commits if(r.get('event'),r.get('match'),r.get('slot'),r.get('sequence'))==
        ('command_batch_committed',match,1,sequence)]
    require(len(accepted)==1 and _integer(accepted[0].get('frame'),0,2**31-1),'UI canonical commit missing or duplicated')
    frame=accepted[0]['frame'];occurrences=[(r['frame'],slot)for r in journal for slot,actions in r['players'].items()for a in actions if digest(a)==action_hash]
    require(occurrences==[(frame,1)],'UI exact original action absent/rebound/duplicated in canonical journal')
    return dict(passed=True,sequence=sequence,incarnation=before['current_incarnation'],action_sha256=action_hash,body_sha256=digest(body),
        canonical_commit_frame=frame,registration_frame_hint=registration[1],registration_minus_canonical_frames=registration[1]-frame,
        registration_tick_ms=registration[2],native72_send_tick_ms=int(send[4]),
        normal_serialize_source_lines=dict(queued=witness['queued_index'],registered67=registration_index,submitted72=send_index,drain=witness['drain_index']),
        protocol_target_raw=raw,protocol_target=[value/2**32 for value in raw],unity_target=target,protocol_target_expected=mapped,
        prediction_exercised=False,movement_feel_exercised=False,constructor_callback_claim=False,
        target_scope='Actual original normal ToProto bytes; original runtime map perspective maps X/Z, adjacentQ32 quantization bound only. No extra ToProto/hash or constructor call inferred.')


def _assignment_span(rows, *, world, assigned, canonical, states):
    first, last = min(assigned, canonical), canonical+20
    selected = [(i, row) for i, row in enumerate(rows)
                if row['world'] == world and first <= row['frame'] <= last]
    require([r['frame'] for _, r in selected] == list(range(first, last+1)) and
            all(r['parsed_state_sha256'] == states.get(r['frame']) for _, r in selected),
            'fresh assigned-to-canonical+20 native state span is missing/mismatched')
    return dict(first_frame=first, last_frame=last, frames_checked=len(selected),
        worker_row_indices=[i for i, _ in selected], speculative_frame=assigned,
        canonical_commit_frame=canonical, speculative_minus_canonical_frames=assigned-canonical,
        hashes_match=True, fresh_repair_attribution_claim=False,
        scope='Actual closed confirmed worker states across min(assignment,canonical)..canonical+20; no claim that fresh repair occurs after canonical receipt')


def evaluate(log, *, attacker_log, match, commits, raw_bodies, journal, bridge_frames,
             canonical_payloads, canonical_states, native_states, worker_states,
             escape_check, join_check, authority_rows, caster_lifetime=False):
    """Require one source-bound mobile release/reinit/fresh-command episode.

    ``authority_rows`` is the victim's parsed actual65 list (or the existing
    controller parser).  Exceptions are explicit missing/invalid evidence, never
    a manufactured zero position or a synthetic successful observation.
    """
    require(type(match) is str and re.fullmatch('[a-f0-9]{32}', match), 'invalid selected match')
    metadata = mobile_metadata()
    escape = escape_check(attacker_log, match=match, commits=commits, raw_bodies=raw_bodies,
                          journal=journal, fixture=metadata, prefix='MOBILE ORDER ')
    cause = decode_player_input(raw_bodies[match, 0, escape['sequence']])['actions']
    require(len(cause) == 1 and digest(cause[0]) == escape['action_sha256'],
            'escape cause must be one exact original Move, not a multi-action batch')
    snapshots, episode, focus_observations = _snapshots(log, match, caster_lifetime=caster_lifetime)
    setup, dead, released, restored, before, reselected, complete = episode
    world = setup['world']
    actual65 = authority_rows(log) if callable(authority_rows) else authority_rows
    frame = escape['canonical_commit_frame']
    require(frame in metadata['safe_canonical_frames'] and frame < 153, 'escape canonical frame does not precede native death')
    receipt, bridge = _receipt(frame, world, match, actual65, bridge_frames, canonical_payloads)
    require(dead['tick_ms'] < min(receipt['tick_ms'], bridge['received_tick_ms']) and
            dead['sampled_us'] < released['sampled_us'] < restored['sampled_us'] and
            dead['frame'] < released['frame'] <= restored['frame'] and
            released['tick_ms'] <= restored['tick_ms'] and
            restored['tick_ms'] >= receipt['tick_ms'], 'speculative death/release or corrected restoration lacks real receipt ordering')
    replay = _joined(join_check, worker_states, world=world, receipt=receipt, states=canonical_states,
                     journal=journal, action_hash=escape['action_sha256'], slot=0, replay=True,
                     latest_tick=restored['tick_ms'])
    require([r.get('frame') for r in native_states] == list(range(130, 221)), 'actual native mobile authority timeline incomplete')
    for row in native_states:
        number = row['frame']; victim, attacker = row.get('victim'), row.get('attacker')
        damage = victim.get('current_damage') if type(victim) is dict else None
        require(row.get('parsed_state_sha256') == canonical_states.get(number) and type(victim) is dict and
                (victim.get('id'), victim.get('army'), victim.get('type')) == (11, 1, 1) and
                victim.get('max_health') == 100 and type(damage) in (int, float) and math.isfinite(damage) and
                0 <= damage < 100 and (number > 173 or damage == (0 if number < 142 else 50)) and
                type(row.get('game_state')) is dict and row['game_state'].get('complete') is False,
                'actual authoritative victim is not continuously alive with qualified native damage')
        if number <= 153:
            require(type(attacker) is dict and (attacker.get('id'), attacker.get('army'), attacker.get('type')) == (10, 0, 1) and
                    attacker.get('max_health') == 100 and attacker.get('current_damage') ==
                    (0 if number < 142 else 50 if number < 153 else 100), 'actual attacker native death timeline differs')
        else:
            require(attacker is None, 'actual attacker remains after qualified native release')
    orders = _rows(log, 'MOBILE ORDER ', match, 1)
    require(len(orders) == 1, 'one fresh original mobile command required')
    order = orders[0]; _common(order, world=world)
    require(order.get('event') == 'original_fresh_move' and (order['entity'], order['unit_type'], order['army']) == (11, 1, 1) and
            order.get('incarnation') == restored['current_incarnation'] and type(order.get('incarnation')) is int and
            order.get('ability') == 12 and 180 <= order['frame'] < 200 and
            order['frame'] == reselected['frame'] and order.get('originalCtor') is True and
            type(order.get('queueDelta')) is int and order['queueDelta'] == 1 and
            order.get('reselected_current') is True and order.get('original_callback') == 'Uncapped.ExecuteTargetGroundCommand..ctor' and
            type(order.get('action_sha256')) is str and HEX64.fullmatch(order['action_sha256']), 'fresh constructor/source/admission differs')
    for key in ('origin', 'target'):
        _vector(order.get(key))
    require(all(_integer(order.get(k)) for k in ('origin_sampled_us', 'enqueue_sampled_us')) and
            reselected['sampled_us'] < order['origin_sampled_us'] <= order['sampled_us'] <= order['enqueue_sampled_us'] and
            before['sampled_us'] < reselected['sampled_us'] and
            type(order.get('target_bits')) is list and len(order['target_bits']) == 3 and
            all(_integer(v, 0, UINT32) for v in order['target_bits']), 'fresh origin/constructor/enqueue clocks or float bits differ')
    expected = [_f32(_f32(order['origin'][0])+16), _f32(order['origin'][1]), _f32(order['origin'][2])]
    require(all(_reported_bits_match(v, bits) for v, bits in zip(expected, order['target_bits'])),
            'fresh original target is not the actual restored origin plus bounded16mX')
    fresh = _fresh_binding(log, order, match=match, commits=commits, raw_bodies=raw_bodies, journal=journal)
    # No extra original command in this isolated window may stand in for the
    # scripted escape or fresh response. Normal build automation starts at300.
    window_actions = [(r['frame'], slot, digest(a)) for r in journal if 130 <= r['frame'] <= 220
                      for slot, actions in r['players'].items() for a in actions]
    require(window_actions == [(frame, 0, escape['action_sha256']),
                               (fresh['canonical_commit_frame'], 1, fresh['action_sha256'])],
            'mobile observation window contains an unintended/duplicate canonical command')
    fresh65, fresh_bridge = _receipt(fresh['canonical_commit_frame'], world, match, actual65, bridge_frames, canonical_payloads)
    fresh_replay = _joined(join_check, worker_states, world=world, receipt=fresh65, states=canonical_states,
        journal=journal, action_hash=fresh['action_sha256'], slot=1, replay=False)
    assignment_span = _assignment_span(worker_states, world=world, assigned=fresh['speculative_frame'],
        canonical=fresh['canonical_commit_frame'], states=canonical_states)
    motion = _fresh_motion(log, match, world, restored['current_incarnation'], order, restored, fresh65, fresh_bridge)
    same_token = setup['original_incarnation'] == restored['current_incarnation']
    stable_groups = [dict(event=r['event'], frame=r['frame'], group_ids=r['group_ids'],
                         tracked_released_ids=r['tracked_released_ids']) for r in (before, reselected, complete)]
    group_status = 'not_same_confirmed_token' if not same_token else (
        'preserved' if all(11 in r['group_ids'] for r in (before, reselected, complete)) else 'lost')
    return dict(passed=True, world=world, match=match, rows=snapshots, escape=escape,
        escape_actual_victim65=receipt, escape_raw_bridge=bridge, escape_native_replay=replay,
        release_receipt_observation=dict(release_tick_ms=released['tick_ms'],
            actual_victim65_tick_ms=receipt['tick_ms'], raw_bridge_tick_ms=bridge['received_tick_ms'],
            release_minus_victim65_ms=released['tick_ms']-receipt['tick_ms'],
            same_quantized_tick=released['tick_ms'] == receipt['tick_ms'],
            release_sampled_us=released['sampled_us'], restoration_sampled_us=restored['sampled_us'],
            scope='Death precedes both receipts; release follows death and precedes restored native view. Bridge/65 may queue before PROCESS repair; no release-before-arrival or submillisecond receipt-order claim'),
        native_authority_timeline=native_states, fresh=fresh, fresh_actual_victim65=fresh65,
        fresh_raw_bridge=fresh_bridge, fresh_native_confirmation=fresh_replay, fresh_motion=motion,
        fresh_assignment_span=assignment_span, fresh_repair_attribution_claim=False,
        original_mobile_release_observed=True, current_mobile_reinitialized_and_admitted=True,
        original_selection_group_focus_established=True,
        same_observed_pointer=_pointer(setup['original_actor']) == _pointer(restored['current_actor']),
        same_confirmed_token=same_token,
        observed_group_timeline=[dict(event=r['event'], group_ids=r['group_ids'], tracked_released_ids=r['tracked_released_ids'],
            focus_actor=r['focus_actor'], focus_group=r['focus_group'], auto_type1=r['auto_type1']) for r in episode],
        focus_observations=focus_observations, whole_unity_frame_focus_safety_claim=False,
        camera_retarget_observations=[r for r in focus_observations
            if r['classification'] == 'would_focus_valid_camera_lease' and r['target_differs_from_input_mobile']],
        group_intent_observation=dict(status=group_status, same_confirmed_token=same_token,
            stable_observations=stable_groups, followup_open=group_status != 'preserved',
            full_mobile_controls_accepted=False,
            scope='Observed original group4 ID11 membership for the retained confirmed token; raw tracked IDs preserved, no all-controls restoration claim'),
        inactive_casting_scratch_exercised=False, active_caster_exercised=caster_lifetime, pool_callback_observed=False,
        physicalUI=False, full_feature_accepted=False,
        scope=('Scripted original Move12; original mobile membership/component release, corrected current admission, real group/focus setup and fresh command response; no physical UI/casting/VFX claim' if caster_lifetime else
               'Scripted original Move12; original mobile membership/component release, corrected current admission, real group/focus setup and fresh command response; no physical UI/caster/VFX claim'))


def evaluate_ui_cast(log, *, attacker_log, match, commits, raw_bodies, journal, bridge_frames,
                     canonical_payloads, canonical_states, native_states, worker_states,
                     escape_check, join_check, authority_rows):
    """Original minimap88 queue/serialization ownership; no predictive feel gate."""
    require(type(match) is str and re.fullmatch('[a-f0-9]{32}',match),'invalid UI selected match')
    ui=_ui_cast_records(log,match)
    snapshots,episode,focus=_snapshots(log,match,_ui=ui)
    setup,dead,released,restored,before,queued,complete=episode;world=setup['world']
    metadata=mobile_metadata()
    escape=escape_check(attacker_log,match=match,commits=commits,raw_bodies=raw_bodies,journal=journal,fixture=metadata,prefix='MOBILE ORDER ')
    cause=decode_player_input(raw_bodies[match,0,escape['sequence']])['actions']
    require(len(cause)==1 and digest(cause[0])==escape['action_sha256'],'UI episode escape cause is not one original Move12')
    frame=escape['canonical_commit_frame'];actual65=authority_rows(log)if callable(authority_rows)else authority_rows
    require(frame in metadata['safe_canonical_frames'] and frame<153,'UI episode canonical escape misses actual native death')
    receipt,bridge=_receipt(frame,world,match,actual65,bridge_frames,canonical_payloads)
    require(dead['tick_ms']<min(receipt['tick_ms'],bridge['received_tick_ms']) and
            dead['sampled_us']<released['sampled_us']<restored['sampled_us'] and
            restored['tick_ms']>=receipt['tick_ms'],'UI episode real death/release/restoration lacks receipt chronology')
    replay=_joined(join_check,worker_states,world=world,receipt=receipt,states=canonical_states,journal=journal,
        action_hash=escape['action_sha256'],slot=0,replay=True,latest_tick=restored['tick_ms'])
    require([r.get('frame')for r in native_states]==list(range(130,221)),'UI actual native authority timeline incomplete')
    for row in native_states:
        number=row['frame'];victim,attacker=row.get('victim'),row.get('attacker')
        damage=victim.get('current_damage')if type(victim)is dict else None
        require(row.get('parsed_state_sha256')==canonical_states.get(number) and type(victim)is dict and
            (victim.get('id'),victim.get('army'),victim.get('type'))==(11,1,1) and victim.get('max_health')==100 and
            type(damage)in(int,float) and math.isfinite(damage) and 0<=damage<100 and
            (number>173 or damage==(0 if number<142 else 50)) and type(row.get('game_state'))is dict and
            row['game_state'].get('complete')is False,'UI actual authority victim health/state/hash differs')
        require((type(attacker)is dict and (attacker.get('id'),attacker.get('army'),attacker.get('type'))==(10,0,1) and
            attacker.get('max_health')==100 and attacker.get('current_damage')==(0 if number<142 else 50 if number<153 else 100))
            if number<=153 else attacker is None,'UI actual authority attacker death/purge differs')
    command=_ui_binding(log,ui,match=match,commits=commits,raw_bodies=raw_bodies,journal=journal)
    canonical=command['canonical_commit_frame']
    window=[(r['frame'],slot,digest(a))for r in journal if 130<=r['frame']<=220 for slot,actions in r['players'].items()for a in actions]
    require(window==[(frame,0,escape['action_sha256']),(canonical,1,command['action_sha256'])],
            'UI observation canonical window contains unintended/missing commands')
    cast65,cast_bridge=_receipt(canonical,world,match,actual65,bridge_frames,canonical_payloads)
    confirmed=_joined(join_check,worker_states,world=world,receipt=cast65,states=canonical_states,journal=journal,
        action_hash=command['action_sha256'],slot=1,replay=False)
    command.update(native_confirmation=confirmed,actual_victim65=cast65,raw_bridge=cast_bridge,
        original_ui_rows=ui['rows'],preactivation_residue=ui['preactivation_residue'],active_caster_exercised=True,physicalUI=False)
    critical=ui['events']
    require(all(row['original_incarnation']==setup['original_incarnation'] for row in ui['rows']) and
            setup['sampled_us']<critical['before_activation']['sampled_us']<=critical['after_activation']['sampled_us']<dead['sampled_us'] and
            all(critical[name]['frame']==source['frame'] and critical[name]['sampled_us']>=source['sampled_us'] for name,source in
                (('native_dead',dead),('release_observed',released),('restored',restored))) and
            critical['before_cast']['frame']==before['frame']==queued['frame']==180 and
            before['sampled_us']<=critical['before_cast']['sampled_us']<critical['after_cast_queued']['sampled_us']<=queued['sampled_us'] and
            critical['complete']['frame']==complete['frame'] and critical['complete']['sampled_us']<=complete['sampled_us'] and
            critical['before_cast']['current_incarnation']==restored['current_incarnation']==command['incarnation'],
            'UI phase rows do not join actual lifecycle/current identity/cast queue boundary')
    require(not _rows(log,'MOBILE ORDER ',match,1) and not _rows(log,'MOBILE FEEL ',match,1024),
            'UI-only variant emitted a fake fresh constructor or predicted feel witness')
    return dict(passed=True,world=world,match=match,rows=snapshots,escape=escape,escape_actual_victim65=receipt,escape_raw_bridge=bridge,
        escape_native_replay=replay,native_authority_timeline=native_states,ui_command=command,focus_observations=focus,
        same_confirmed_token=setup['original_incarnation']==restored['current_incarnation'],
        original_mobile_release_observed=True,current_mobile_reinitialized_and_admitted=True,
        original_selection_group_focus_established=True,active_caster_exercised=True,physicalUI=False,
        full_feature_accepted=False,full_mobile_controls_accepted=False,prediction_exercised=False,movement_feel_exercised=False,
        scope='Original UI88 activation retained across correction, original minimap queue0→1, normal serialize67/72 and one canonical88/nativeC+20; no fresh Move12, constructor-call, preauthority movement or phase acceptance claim')


def _group_intent_rows(log, *, match, slot):
    rows = _rows(log, 'MOBILE GROUP INTENT ', match, 5)
    fields = {'schema','event','world','match','slot','frame','tick_ms','sampled_us','entity','unit_type','army',
        'incarnation','confirmed_incarnation','native_identity_present','current_admitted','retained_group',
        'retained_ids','retained_tracked_ids','operation','original_scope_player_initiated','clear_callback',
        'replace_callback','replace_source_count','replace_existing','physicalUI'}
    for row in rows:
        _common(row)
        require(set(row) == fields and type(row['slot']) is int and row['slot'] == slot and
                (row['entity'],row['unit_type'],row['army']) == ((10,1,0) if slot == 0 else (11,1,1)) and
                _integer(row['incarnation'],1) and _integer(row['confirmed_incarnation']) and
                row['retained_group'] == 4 and type(row['retained_group']) is int,
                'group identity/schema/manual group differs')
        require(type(row['native_identity_present']) is bool and type(row['current_admitted']) is bool,
                'group native/current admission flags differ')
        for key in ('retained_ids','retained_tracked_ids'):
            ids=row[key]
            require(type(ids) is list and len(ids) <= 4096 and all(_integer(v,0,UINT32) for v in ids) and
                    len(set(ids)) == len(ids) and set(ids) <= {row['entity']}, 'group contains duplicate/unrelated IDs')
        operation=row['operation']
        if row['event'] == 'after_user_edits':
            require(slot == 1 and operation in ('clear','replace') and row['original_scope_player_initiated'] is True,
                    'original group edit scope/operation missing')
            if operation == 'clear':
                require(row['clear_callback'] == 'Uncapped.ControlGroup.Clear' and row['replace_callback'] is None and
                        row['replace_source_count'] is None and row['replace_existing'] is None,
                        'original Clear callback differs from observed edit')
            else:
                require(row['clear_callback'] is None and row['replace_callback'] == 'Uncapped.ControlGroupPanel.AssignToControlGroup' and
                        type(row['replace_source_count']) is int and row['replace_source_count'] == 0 and
                        row['replace_existing'] is True, 'original empty replacement callback/source differs')
        else:
            require(all(row[key] is None for key in ('operation','original_scope_player_initiated','clear_callback',
                    'replace_callback','replace_source_count','replace_existing')), 'unobserved original edit was fabricated')
    require(rows and all(b['frame'] >= a['frame'] and b['tick_ms'] >= a['tick_ms'] and
            b['sampled_us'] > a['sampled_us'] for a,b in zip(rows,rows[1:])), 'group observation clock/frame regressed')
    require(len({(r['world'],r['incarnation']) for r in rows}) == 1, 'group original world/incarnation changed')
    return rows


def evaluate_group_intent(log, *, attacker_log, mobile_episodes, user_edits=False, ui_cast=False):
    """Opt-in group4 retention OR two original cancellation operations.

    Both modes separately require the attacker's group4 provisional hold and
    canonical death purge in its independently owned client. The already-qualified mobile body/replay/motion evidence is required;
    the controller additionally gates on all closed native hashes and shutdown.
    """
    require(type(user_edits) is bool and type(ui_cast) is bool and not(ui_cast and user_edits) and
            type(mobile_episodes) is list and len(mobile_episodes) == 2,
            'group intent requires both actual mobile episodes')
    matches=[ep.get('match') for ep in mobile_episodes]
    require(len(set(matches)) == 2 and all(type(m) is str and re.fullmatch('[a-f0-9]{32}',m) for m in matches) and
            len({ep.get('world') for ep in mobile_episodes}) == 2, 'group match/world episodes repeat')
    require(len({ep.get('escape',{}).get('order',{}).get('world') for ep in mobile_episodes}) == 2,
            'group attacker escape world reused across rematch')
    for text in (log,attacker_log):
        count=0
        for line in text.splitlines():
            if 'MOBILE GROUP INTENT ' not in line:continue
            raw=line.split('MOBILE GROUP INTENT ',1)[1]
            require(len(raw) <= 8192, 'group diagnostic line exceeds bound')
            row=json.loads(raw,object_pairs_hook=_unique_object)
            require(type(row) is dict and row.get('match') in matches, 'group event belongs to an unqualified extra match')
            count+=1;require(count <= 10, 'group diagnostic count exceeds two-round bound')
    result=[]
    for ep in mobile_episodes:
        input_ok=(ep.get('ui_command',{}).get('passed') is True and
                  ep['ui_command'].get('prediction_exercised') is False and
                  ep['ui_command'].get('native_confirmation',{}).get('continuation_frames')==20) if ui_cast else (
                  ep.get('fresh_motion',{}).get('passed') is True and ep.get('fresh_assignment_span',{}).get('hashes_match') is True)
        require(ep.get('passed') is True and input_ok and
                ep.get('escape_native_replay',{}).get('promotion_group_replayed_delta',0) > 0 and
                ep.get('escape_native_replay',{}).get('continuation_frames') == 20,
                'group intent lacks positive mobile motion/replay+20/native confirmation')
        match=ep['match'];world=ep['world']
        correction=[r for r in ep['rows'] if r['event'] != 'snapshot']
        require([r['event'] for r in correction] == list(UI_EVENTS if ui_cast else EVENTS), 'group mobile lifecycle binding incomplete')
        setup,dead,released,restored,before,reselected,complete=correction
        token=setup['original_incarnation']
        input_token=ep['ui_command']['incarnation'] if ui_cast else ep['fresh']['order']['incarnation']
        require(token == restored['current_incarnation'] == input_token > 0,
                'group victim is not the same authoritative mobile incarnation')
        victim=_group_intent_rows(log,match=match,slot=1)
        names=['setup','before_user_edits','after_user_edits','restored','complete'] if user_edits else [
            'setup','before_provisional_hold','restored','complete']
        require([r['event'] for r in victim] == names and all(r['world'] == world and
                r['incarnation'] == r['confirmed_incarnation'] == token for r in victim),
                'victim group event/token/world chain differs')
        first,hold=victim[:2];last_restored,last=victim[-2:]
        require(first['frame'] == setup['frame'] == 130 and first['sampled_us'] >= setup['sampled_us'] and
                first['native_identity_present'] and first['current_admitted'] and first['retained_ids'] == setup['group_ids'] == [11] and
                not hold['native_identity_present'] and not hold['current_admitted'] and hold['retained_ids'] == [11] and
                released['frame'] <= hold['frame'] <= restored['frame'] and
                released['sampled_us'] <= hold['sampled_us'] < restored['sampled_us'],
                'victim group lacks original setup and same-token provisional hold')
        expected=[] if user_edits else [11]
        require(all(r['native_identity_present'] and r['current_admitted'] and r['retained_ids'] == expected
                    for r in (last_restored,last)) and last_restored['frame'] == restored['frame'] and
                last_restored['sampled_us'] >= restored['sampled_us'] and
                last['frame'] == complete['frame'] >= 260 and last['sampled_us'] <= complete['sampled_us'] and
                last_restored['retained_ids'] == restored['group_ids'] and last['retained_ids'] == complete['group_ids'],
                'victim group preservation/cancellation did not survive restored view and completion')
        operation=None
        if user_edits:
            edited=victim[2];operation='clear' if world == 1 else 'replace'
            require(world in (1,2) and edited['operation'] == operation and edited['frame'] == hold['frame'] and
                    not edited['native_identity_present'] and not edited['current_admitted'] and
                    edited['retained_ids'] == [] and hold['sampled_us'] < edited['sampled_us'] < restored['sampled_us'],
                    'original user edit was not the distinct round-specific cancellation during absence')
        attacker=_group_intent_rows(attacker_log,match=match,slot=0)
        require([r['event'] for r in attacker] == ['attacker_setup','attacker_speculative_absence',
                'attacker_confirmed_purge','attacker_complete'], 'attacker group chain incomplete')
        attack_world=ep['escape']['order']['world'];attack_token=ep['escape']['order']['incarnation']
        require(all(r['world'] == attack_world and r['incarnation'] == attack_token for r in attacker),
                'attacker group does not bind the exact original escape actor/world')
        a_setup,absence,purge,a_complete=attacker
        require(a_setup['frame'] == 130 and a_setup['native_identity_present'] and a_setup['current_admitted'] and
                a_setup['confirmed_incarnation'] == attack_token and a_setup['retained_ids'] == [10] and
                absence['frame'] >= 154 and not absence['native_identity_present'] and not absence['current_admitted'] and
                absence['confirmed_incarnation'] == attack_token and absence['retained_ids'] == [10],
                'attacker provisional absence did not retain unchanged confirmed group intent')
        require(all(not r['native_identity_present'] and not r['current_admitted'] and
                r['confirmed_incarnation'] == 0 and r['retained_ids'] == [] for r in (purge,a_complete)) and
                a_complete['frame'] >= 220, 'confirmed attacker death did not purge group membership permanently')
        native=ep['native_authority_timeline']
        require([r['frame'] for r in native] == list(range(130,221)) and
                all(type(r['victim']) is dict and r['victim']['id'] == 11 and r['victim']['current_damage'] < 100 for r in native) and
                next(r['attacker'] for r in native if r['frame'] == 153)['current_damage'] == 100 and
                all(r['attacker'] is None for r in native if r['frame'] >= 154),
                'group canonical attacker death/victim survival does not match actual native authority')
        require(input_ok, 'group test lost its actual original input witness')
        result.append(dict(passed=True,match=match,world=world,victim_rows=victim,attacker_rows=attacker,
            victim_same_confirmed_token=True,retained_group4_preserved=not user_edits,
            original_user_operation=operation,user_cancellation_respected=user_edits,
            attacker_provisional_membership_preserved=True,attacker_confirmed_numeric_membership_purged=True,
            attacker_tracked_ids_after_purge=[r['retained_tracked_ids'] for r in (purge,a_complete)],
            confirmation_scope='Actual confirmed_incarnation becomes0 plus canonical native death153/absence154; no invented per-frame65 timestamp',
            physicalUI=False,full_mobile_controls_accepted=False))
    require(not user_edits or [r['original_user_operation'] for r in result] == ['clear','replace'],
            'two actual rounds must separately exercise original Clear and empty replacement')
    return dict(passed=True,user_edits=user_edits,episodes=result,requires_controller_full_closed_native_parity=True,
        physicalUI=False,active_casting_exercised=ui_cast,full_mobile_controls_accepted=False,
        scope=('Retained original group4 plus attacker canonical purge and actual nonpredicted UI88 ownership/native continuation; no predicted response/full-controls acceptance' if ui_cast else
            'Single original manual group4 retention OR separate Clear/empty-replace captures, plus attacker group4 provisional hold and confirmed-death numeric purge in its separate client; no physical UI/casting/all-controls acceptance'))


def _group_focus_fixture_rows(log, *, match, world, token):
    """Original fixture callbacks/snapshots, separate from product call proof."""
    require(world in (1,2) and _integer(world,1,2) and _integer(token,1), 'focus fixture world/token differs')
    rows=_rows(log,'MOBILE GROUP FOCUS ',match,5)
    names=['setup','restored','complete'] if world == 1 else ['setup','before_cancel','after_cancel','restored','complete']
    fields={'schema','event','world','match','slot','entity','unit_type','army','frame','completed_frame','tick_ms','sampled_us',
        'selector','incarnation','confirmed_incarnation','current_incarnation','retained_group','group_ids','selected_ids',
        'preview_ids','casting_ids','native_identity_present','current_admitted','current_actor','current_actual_entity',
        'current_actual_type','current_actual_army','source_resolvable_count','focus_group','focus_actor','pending_iteration',
        'pending_epoch','pending_iterator','release_pending_baseline','pending_commands','cancel_callback','cancel_token','physicalUI'}
    require([r.get('event') for r in rows] == names, 'focus fixture original event chain is incomplete')
    for row in rows:
        _common(row,world=world)
        require(set(row) == fields and type(row['slot']) is int and row['slot'] == 1 and
                (row['entity'],row['unit_type'],row['army']) == (11,1,1) and
                _integer(row['completed_frame'],-1,2**31-1) and _integer(row['incarnation'],1) and
                _integer(row['confirmed_incarnation'],1) and row['incarnation'] == row['confirmed_incarnation'] == token and
                _integer(row['current_incarnation']) and type(row['retained_group']) is int and row['retained_group'] == 4 and
                type(row['native_identity_present']) is bool and type(row['current_admitted']) is bool and
                _integer(row['source_resolvable_count'],0,1) and _integer(row['focus_group'],-1,2**31-1) and
                type(row['pending_commands']) is int and row['pending_commands'] == 0 and
                _integer(row['pending_iteration']) and _integer(row['pending_epoch']) and _integer(row['release_pending_baseline']) and
                _pointer(row['selector']) > 0, 'focus fixture identity/owner/schema differs')
        for key in ('current_actor','focus_actor','pending_iterator'):_pointer(row[key])
        require(bool(row['pending_iteration']) == bool(row['pending_epoch']) == bool(_pointer(row['pending_iterator'])),
                'focus fixture pending witness is only partial')
        for key in ('group_ids','selected_ids','preview_ids','casting_ids'):
            ids=row[key]
            require(type(ids) is list and len(ids) <= 4096 and all(_integer(v,0,UINT32) for v in ids) and
                    len(set(ids)) == len(ids), 'focus fixture observed ID set is invalid')
        require(row['group_ids'] == [11], 'focus fixture lost original group4 intent')
        for key in ('current_actual_entity','current_actual_type','current_actual_army'):
            require(row[key] is None or _integer(row[key],0,UINT32), 'focus fixture nullable current identity differs')
        if row['event'] == 'after_cancel':
            require(row['cancel_callback'] == 'Uncapped.UnitSelector.FocusControlGroupCancel' and row['cancel_token'] == '06002220',
                    'focus fixture original Cancel callback differs')
        else:
            require(row['cancel_callback'] is None and row['cancel_token'] is None, 'unobserved focus cancellation fabricated')
    require(len({_pointer(r['selector']) for r in rows}) == 1 and all(b['frame'] >= a['frame'] and
            b['tick_ms'] >= a['tick_ms'] and b['sampled_us'] >= a['sampled_us'] for a,b in zip(rows,rows[1:])),
            'focus fixture owner or actual clocks/frame changed')
    setup=rows[0];restored,last=rows[-2:]
    require(setup['frame'] == 130 and setup['focus_group'] == 4 and setup['selected_ids'] == [11] and
            _pointer(setup['focus_actor']) == _pointer(setup['current_actor']) > 0 and not setup['release_pending_baseline'] and
            restored['release_pending_baseline'] == last['release_pending_baseline'] and last['frame'] >= 260,
            'focus fixture lacks original positive setup/complete')
    for row in (setup,restored,last):
        require(row['native_identity_present'] and row['current_admitted'] and _pointer(row['current_actor']) > 0 and
                row['current_incarnation'] == token and row['source_resolvable_count'] == 1 and
                (row['current_actual_entity'],row['current_actual_type'],row['current_actual_army']) == (11,1,1),
                'focus fixture current mobile is not the admitted canonical lease')
    if world == 1:
        require(all(not r['pending_iteration'] and r['focus_group'] == 4 for r in rows) and
                _pointer(last['focus_actor']) == _pointer(last['current_actor']), 'positive focus fixture lost held intent/current cache')
    else:
        before,after=rows[1:3]
        require(not setup['pending_iteration'] and before['pending_iteration'] > before['release_pending_baseline'] and
                len({r['release_pending_baseline'] for r in rows[1:]}) == 1 and
                len({(r['pending_iteration'],r['pending_epoch'],_pointer(r['pending_iterator'])) for r in rows[1:]}) == 1 and
                before['frame'] == after['frame'] and before['focus_group'] == 4 and
                all(not r['native_identity_present'] and not r['current_admitted'] and
                    _pointer(r['current_actor']) == 0 and r['current_incarnation'] == 0 and
                    all(r[k] is None for k in ('current_actual_entity','current_actual_type','current_actual_army'))
                    for r in (before,after)) and
                all(r['focus_group'] == -1 and not _pointer(r['focus_actor']) for r in (after,restored,last)),
                'focus fixture original pending cancellation did not remain cancelled')
    return rows


def _group_focus_product_rows(log, *, matches, no_start=False):
    require(type(no_start)is bool,'focus no-start schema option is not typed')
    require(type(log) is str and len(log) <= 32*1024*1024, 'focus product log exceeds bound')
    fields={'schema','event_sequence','event','stage','route','world','match','selector','iterator','request_epoch','iteration',
        'group','held_group','tick_ms','sampled_us','original_state','yield_bits','original_result','source_ids','logical_ids',
        'actor','entity','unit_type','army','incarnation','member','initialized','current_lease'}
    if no_start:fields|={'requested_group','active_epoch','active_iterator','active_handle'}
    stages={'request':{'accepted_repeat'},'start':{'scheduling'},'scheduled':{'returned'},
        'iteration':{'waiting_absent','refind','delegate','cancel_delegate','ending_delegate'},'camera':{'requested','returned'},
        'cancel_observed':{'cancel_delegate'},'ending_observed':{'ending_delegate'},
        'terminal':{'original_false','world_retired','superseded','failed'}}
    if no_start:stages['request']|={'accepted_once'}
    rows=[];previous=None
    for line_index,line in enumerate(log.splitlines()):
        if 'MOVEMENT FOCUS ' not in line:continue
        raw=line.split('MOVEMENT FOCUS ',1)[1]
        require(0 < len(raw) <= 8192 and len(rows) < 65536, 'focus product diagnostic exceeds bound')
        row=json.loads(raw,object_pairs_hook=_unique_object)
        require(type(row) is dict and set(row) == fields and type(row['schema']) is int and row['schema'] == 1 and
                row['match'] in matches and _integer(row['world'],1,2) and row['match'] == matches[row['world']-1] and
                _integer(row['event_sequence'],1) and _integer(row['request_epoch'],1) and _integer(row['iteration']) and
                row['event'] in stages and row['stage'] in stages[row['event']] and row['route'] in ('initial','repeat') and
                _pointer(row['selector']) > 0 and _integer(row['group'],0,UINT32) and _integer(row['held_group'],-1,2**31-1) and
                _integer(row['tick_ms']) and _integer(row['sampled_us']), 'focus product schema/owner/event differs')
        require(row['route'] == 'repeat' or row['event'] == 'camera' or no_start and row['event']=='request',
                'focus initial route is not a camera/request callback')
        if no_start:
            require(_integer(row['requested_group'],0,UINT32) and _integer(row['active_epoch']) and
                (row['active_handle']is None or _integer(row['active_handle'],0,UINT32)), 'focus actual active/request scalar differs')
            if row['active_iterator']is None:
                require(row['active_epoch']==0 and row['active_handle']is None,'focus invented an absent active iterator scope')
            else:
                require(_pointer(row['active_iterator'])>0 and row['active_epoch']>0,'focus active iterator lacks its installed epoch')
            if row['route']=='initial':
                require(row['iterator']is None and row['iteration']==0,'initial request adopted the active iterator')
            else:
                require(row['request_epoch']==row['active_epoch'] and row['iterator']==row['active_iterator'],
                    'repeat callback adopted pending request metadata')
            require(row['event']!='request' or row['route']=='initial','extended accepted request is not scoped as initial')
        if row['iterator'] is None:
            require(row['iteration'] == 0 and row['original_state'] is None and row['yield_bits'] is None,
                    'focus product fabricated iterator state')
        else:
            require(_pointer(row['iterator']) > 0 and _integer(row['original_state'],-2**31,2**31-1) and
                    _integer(row['yield_bits'],0,UINT32), 'focus product iterator/state differs')
        require(row['original_result'] is None or type(row['original_result']) is bool, 'focus original result is not observed bool/null')
        for key in ('source_ids','logical_ids'):
            ids=row[key]
            require(type(ids) is list and len(ids) <= 4096 and all(_integer(v,0,UINT32) for v in ids) and
                    len(set(ids)) == len(ids), 'focus numeric membership is invalid')
        if row['actor'] is None:
            require(all(row[k] is None for k in ('entity','unit_type','army','incarnation')) and
                    all(row[k] is False for k in ('member','initialized','current_lease')), 'focus null candidate has invented lease facts')
        else:
            require(_pointer(row['actor']) > 0 and _integer(row['entity'],0,UINT32) and _integer(row['unit_type'],1,UINT32) and
                    _integer(row['army'],0,UINT32) and _integer(row['incarnation'],1) and
                    all(row[k] is True for k in ('member','initialized','current_lease')) and
                    row['entity'] in row['source_ids'] and row['entity'] in row['logical_ids'],
                    'focus candidate lacks independent source/group membership and current initialized lease')
        if row['event'] == 'camera':
            require(row['actor'] is not None and row['original_result'] is None and
                    ((row['route'] == 'initial' and row['iterator'] is None) or
                     (row['route'] == 'repeat' and row['iterator'] is not None and row['iteration'] > 0)),
                    'focus camera does not bind its actual initial/repeat route')
        elif row['event'] == 'iteration':
            require(row['iterator'] is not None and row['iteration'] > 0,
                    'focus outer iteration has no actual iterator/ordinal')
            if row['stage'] == 'waiting_absent':
                require(row['actor'] is None and row['original_result'] is None and row['original_state'] in (1,2) and
                        row['yield_bits'] == 0xff800000, 'focus pending did not preserve original MEC yield/state')
            else:
                require(type(row['original_result']) is bool, 'focus delegate lacks original bool receipt')
        elif row['event'] == 'terminal':
            require(row['actor'] is None and (row['original_result'] is False if row['stage'] == 'original_false' else
                    row['original_result'] is None), 'focus terminal fabricated an original false result')
        else:
            require(row['actor'] is None and row['original_result'] is None, 'focus bookkeeping fabricated an original result/actor')
        old=previous
        require(row['event_sequence'] == (old['event_sequence']+1 if old else 1) and
                (old is None or row['sampled_us'] >= old['sampled_us'] and row['tick_ms'] >= old['tick_ms']),
                'focus event sequence or checked clock has a gap/regression')
        previous=row;rows.append(dict(row=row,line=line_index))
    return rows


def _caster_survey_json(raw):
    # This opt-in atomic receipt can hold twelve detailed buttons. Legacy
    # diagnostic prefixes retain their separate 8KiB limit in _rows().
    require(type(raw) is str and 0 < len(raw.encode('utf-8')) <= 65536, 'caster survey row exceeds64KiB bound')
    depth=0;quoted=False;escaped=False
    for char in raw:
        if quoted:
            if escaped:escaped=False
            elif char == '\\':escaped=True
            elif char == '"':quoted=False
        elif char == '"':quoted=True
        elif char in '{[':
            depth+=1;require(depth <= 4, 'caster survey JSON exceeds declared depth4')
        elif char in '}]':
            depth-=1;require(depth >= 0, 'caster survey JSON has an invalid container')
    require(not quoted and depth == 0, 'caster survey JSON container is incomplete')
    return json.loads(raw,object_pairs_hook=_unique_object)


def _caster_survey_text(value):
    if type(value) is not str:return False
    try:return 0 < len(value.encode('utf-8')) <= 511
    except UnicodeError:return False


def _caster_survey_button(row, index):
    fields={'index','present','button_class','slot','valid_button','mapped_ids','mapped_count','has_mapped_casters',
        'group_present','group_class','group_unity_truth','panel_group_matches','group_kind','cast_type','cast_type_method_token',
        'smart_casting','config_lookup_performed','config_present','config_id','config_key_observation','candidate','candidate_reason'}
    require(type(row) is dict and set(row) == fields and _integer(row['index'],0,11) and row['index'] == index and
            type(row['present']) is bool and type(row['config_lookup_performed']) is bool and type(row['candidate']) is bool,
            'caster survey button schema/actual array position differs')
    optional=fields-{'index','present','config_lookup_performed','candidate','candidate_reason'}
    if not row['present']:
        require(all(row[k] is None for k in optional) and row['config_lookup_performed'] is False and
                row['candidate'] is False and row['candidate_reason'] == 'null_button', 'null UI button has invented getter values')
        return False
    require(_caster_survey_text(row['button_class']) and _integer(row['slot'],-2**31,2**31-1) and
            type(row['group_present']) is bool, 'caster survey button class/actual slot/group presence differs')
    supported=0 <= row['slot'] < 12
    if supported:
        require(type(row['valid_button']) is bool and
                (type(row['panel_group_matches']) is bool if row['valid_button'] else row['panel_group_matches'] is None),
                'caster survey original panel getter route differs')
    else:
        require(row['valid_button'] is None and row['panel_group_matches'] is None,
                'unsupported actual slot fabricated a panel lookup')
    if row['mapped_ids'] is None:
        require(row['mapped_count'] is None and row['has_mapped_casters'] is None,
                'null mapped casters fabricated Count/HasMappedCasters')
    else:
        ids=row['mapped_ids']
        require(type(ids) is list and len(ids) <= 8192 and all(_integer(v,0,UINT32) for v in ids) and
                len(set(ids)) == len(ids) and _integer(row['mapped_count'],0,len(ids)) and
                type(row['has_mapped_casters']) is bool and row['has_mapped_casters'] == (row['mapped_count'] > 0),
                'caster survey mapped numeric IDs/resolvable Count/Has differ')
    if row['group_present']:
        require(_caster_survey_text(row['group_class']) and type(row['group_unity_truth']) is bool and
                _integer(row['group_kind'],-2**31,2**31-1) and type(row['smart_casting']) is bool,
                'caster survey group field/Unity observations differ')
        if row['group_unity_truth']:
            require(_integer(row['cast_type'],2,10) and _integer(row['cast_type_method_token']) and
                    row['cast_type_method_token'] in (0x06000177,0x06000193), 'caster survey actual virtual CastType getter differs')
        else:
            require(row['cast_type'] is None and row['cast_type_method_token'] is None,
                    'destroyed Unity group fabricated an effective CastType getter')
    else:
        require(all(row[k] is None for k in ('group_class','group_unity_truth','group_kind','smart_casting','cast_type','cast_type_method_token')),
                'null mapped group fabricated group getter/field values')
    lookup=row['has_mapped_casters'] is True and row['group_present'] and row['group_unity_truth'] is True
    require(row['config_lookup_performed'] == lookup, 'caster survey original config lookup preconditions differ')
    if lookup:
        require(type(row['config_present']) is bool, 'caster survey config result presence is unobserved')
    else:
        require(row['config_present'] is None, 'skipped config getter fabricated a null result')
    if lookup and row['config_present']:
        require(_integer(row['config_id'],0,UINT32), 'caster survey actual config Key ID differs')
        expected=dict(declaring_class='Uncapped.AbilityConfig',field_name='Key',field_offset=52,
            declared_class='Uncapped.IntKey`1',boxed_class='Uncapped.IntKey`1',declared_boxed_class_equal=True,
            value_size=4,getter_token=0x0600151a,getter_rva_guarded=False,field_token_source='static_original_metadata',
            closed_argument_source='original_AbilityConfig.Key_metadata')
        observed=row['config_key_observation']
        require(type(observed) is dict and set(observed) == set(expected) and
                all(type(observed[k]) is type(value) and observed[k] == value for k,value in expected.items()),
                'caster survey boxed closed Key/get_ID provenance differs')
    else:
        require(row['config_id'] is None and row['config_key_observation'] is None, 'missing config fabricated a Key ID/provenance')
    candidate=(supported and row['valid_button'] is True and row['panel_group_matches'] is True and
        row['group_unity_truth'] is True and row['has_mapped_casters'] is True and row['mapped_count'] == 1 and
        row['mapped_ids'] == [11] and row['config_id'] in (12,14) and row['cast_type'] is not None and
        row['cast_type'] != 2 and row['smart_casting'] is False)
    reason='noninstant_ui_mapping_only' if candidate else 'unsupported_slot' if not supported else 'ineligible_mapping'
    require(row['candidate'] == candidate and row['candidate_reason'] == reason,
            'caster survey candidate classification does not match actual getter values')
    return candidate


def evaluate_caster_lifetime(log, *, attacker_log, mobile_episodes, group_intent):
    """Observed real original UI activation/current100 cleanup, never a cast."""
    require(type(mobile_episodes) is list and len(mobile_episodes)==2 and [e.get('world') for e in mobile_episodes]==[1,2] and
            type(group_intent) is dict and group_intent.get('passed') is True and group_intent.get('user_edits') is False and
            len(group_intent.get('episodes',[]))==2,'active-caster lifetime requires both mobile/preserved-group episodes')
    matches=[e.get('match') for e in mobile_episodes]
    require(len(set(matches))==2 and all(type(v) is str and re.fullmatch('[a-f0-9]{32}',v) for v in matches) and
            [e.get('match') for e in group_intent['episodes']]==matches and type(attacker_log) is str and
            len(attacker_log)<=32*1024*1024 and 'MOBILE ACTIVE CASTER ' not in attacker_log,
            'active-caster match/rematch/guest-only scope differs')
    require(type(log) is str and len(log)<=32*1024*1024,'active-caster log exceeds bound')
    actual=[]
    for line in log.splitlines():
        if 'MOBILE ACTIVE CASTER ' in line:
            raw=line.split('MOBILE ACTIVE CASTER ',1)[1]
            require(0<len(raw)<=8192,'active-caster receipt exceeds bound')
            row=json.loads(raw,object_pairs_hook=_unique_object)
            require(type(row) is dict and row.get('match') in matches,'active-caster extra/unknown match')
            actual.append(row)
            require(len(actual)<=4096,'active-caster total receipt count exceeds bound')
    require(actual and all(b['sampled_us']>=a['sampled_us'] and b['tick_ms']>=a['tick_ms'] for a,b in zip(actual,actual[1:])),
            'active-caster global rematch clocks regressed')
    require(list(dict.fromkeys(row['match'] for row in actual))==matches,'active-caster rematch ordering differs')
    episodes=[]
    for ep,group in zip(mobile_episodes,group_intent['episodes']):
        require(ep.get('passed') is True and ep.get('active_caster_exercised') is True and
                ep.get('fresh_motion',{}).get('passed') is True and ep.get('fresh_assignment_span',{}).get('hashes_match') is True and
                ep.get('fresh_native_confirmation',{}).get('continuation_frames')==20 and
                ep.get('escape_native_replay',{}).get('promotion_group_replayed_delta',0)>0 and
                ep.get('escape_native_replay',{}).get('continuation_frames')==20 and group.get('passed') is True and
                group.get('world')==ep['world'] and group.get('retained_group4_preserved') is True,
                'active-caster lifetime lacks unchanged body/phase/replay+20/native/group gates')
        witness=_caster_lifetime_records(log,ep['match']);events=witness['events'];rows=witness['rows']
        require(witness['world']==ep['world'],'active-caster actual world differs')
        lifecycle={r['event']:r for r in ep['rows'] if r['event']!='snapshot'}
        require(list(lifecycle)==list(EVENTS),'active-caster mobile lifecycle incomplete')
        setup=lifecycle[EVENTS[0]];dead=lifecycle[EVENTS[1]];released=lifecycle[EVENTS[2]]
        restored=lifecycle[EVENTS[3]];before=lifecycle[EVENTS[4]];complete=lifecycle[EVENTS[-1]]
        require(all(row['original_incarnation']==setup['original_incarnation'] for row in rows) and
                setup['sampled_us']<events['before_activation']['sampled_us']<=events['after_activation']['sampled_us']<dead['sampled_us'] and
                all(events[name]['frame']==source['frame'] and events[name]['sampled_us']>=source['sampled_us'] for name,source in
                    (('native_dead',dead),('release_observed',released),('restored_before_cleanup',restored))) and
                events['native_dead']['sampled_us']<events['release_observed']['sampled_us']<events['restored_before_cleanup']['sampled_us'] and
                events['before_fresh']['frame']==before['frame']==180 and events['before_fresh']['sampled_us']<=before['sampled_us'] and
                events['complete']['frame']==complete['frame'] and events['complete']['sampled_us']<=complete['sampled_us'],
                'active-caster phase observations lack their actual mobile lifecycle/QPC join')
        require(events['restored_before_cleanup']['current_actor']==restored['current_actor'] and
                events['restored_before_cleanup']['current_incarnation']==restored['current_incarnation']==ep['fresh']['order']['incarnation'] and
                events['before_fresh']['sampled_us']<ep['fresh']['order']['sampled_us'],
                'active-caster cleanup/fresh boundary does not use the actual restored current lease')
        cleanup=events.get('after_explicit_pop',events.get('cleanup_skipped'))
        episodes.append(dict(passed=True,match=ep['match'],world=ep['world'],rows=rows,
            activated_caster=events['after_activation']['activated_caster'],
            activated_caster_class=events['after_activation']['activated_caster_class'],
            restored_relation=witness['restored_relation'],active_at_native_dead=bool(_pointer(events['native_dead']['active_caster'])),
            active_at_release=bool(_pointer(events['release_observed']['active_caster'])),
            fixture_activation_calls=1,fixture_explicit_pop_calls=cleanup['explicit_pop_calls'],
            cleanup_event=cleanup['event'],cleanup_reason=cleanup['pop_reason'],
            observed_pre_fixture_pop_clear=witness['natural_clear_observed'],
            first_observed_clear_frame=cleanup['first_natural_clear_frame'],first_observed_clear_us=cleanup['first_natural_clear_us'],
            clear_callback_or_cause_observed=False,strict_idle_before_fresh=True,
            casting98_observation_scope='Actual IDs/count through145..179, including after Pop; strict empty98 required at180',
            fixture_direct_factory_calls=0,fixture_cast_calls=0,activation_exercised=True,cast_command_exercised=False,physicalUI=False))
    return dict(passed=True,episodes=episodes,activation_exercised=True,cast_command_exercised=False,
        requires_controller_full_closed_native_parity=True,physicalUI=False,full_mobile_controls_accepted=False,
        scope='One original UI88 Perform per world; observed managed IAbilityCaster100/Related/class and current100 original Pop0/1. Fixture call counts are not intercepted engine totals. Null-before-fixture-Pop is an observed transition, not callback/cause proof. No cast, attack,88 prediction or hidden-caster-state claim.')


def evaluate_caster_survey(log, *, attacker_log, mobile_episodes, group_intent):
    """Bounded readonly UI values, never a caster-instance/activation proof."""
    require(type(mobile_episodes) is list and len(mobile_episodes) == 2 and [ep.get('world') for ep in mobile_episodes] == [1,2] and
            type(group_intent) is dict and group_intent.get('passed') is True and group_intent.get('user_edits') is False and
            len(group_intent.get('episodes',[])) == 2, 'caster survey requires both original mobile/preserved-group episodes')
    matches=[ep.get('match') for ep in mobile_episodes]
    require(len(set(matches)) == 2 and all(type(match) is str and re.fullmatch('[a-f0-9]{32}',match) for match in matches) and
            [r.get('match') for r in group_intent['episodes']] == matches, 'caster survey match/rematch binding differs')
    prefix='MOBILE CASTER SURVEY '
    require(type(log) is str and len(log) <= 32*1024*1024 and type(attacker_log) is str and
            len(attacker_log) <= 32*1024*1024 and prefix not in attacker_log, 'caster survey log exceeds bound or attacker emitted survey')
    observed=[]
    for line in log.splitlines():
        if prefix not in line:continue
        require(len(observed) < 2, 'caster survey duplicate/extra atomic receipt')
        observed.append(_caster_survey_json(line.split(prefix,1)[1]))
    require(len(observed) == 2 and [r.get('match') if type(r) is dict else None for r in observed] == matches,
            'caster survey requires exactly one actual receipt per matched world')
    fields={'schema','event','route','world','match','slot','entity','unit_type','army','frame','tick_ms','sample_begin_us','sample_end_us',
        'incarnation','confirmed_incarnation','current_actual_entity','current_actual_type','current_actual_army','current_admitted',
        'current_initialized','current_native_state','source_ids_before','source_ids_after','preview_ids_before','preview_ids_after',
        'casting_ids_before','casting_ids_after','source_count_before','source_count_after','pending_before','pending_after',
        'active_caster_before','active_caster_after','active_array_present','active_array_count','buttons','eligible_slots',
        'settings_scope','activation_performed','caster_class_observed'}
    episodes=[]
    for ep,group,row in zip(mobile_episodes,group_intent['episodes'],observed):
        require(ep.get('passed') is True and ep.get('fresh_motion',{}).get('passed') is True and
                ep.get('fresh_assignment_span',{}).get('hashes_match') is True and
                ep.get('escape_native_replay',{}).get('promotion_group_replayed_delta',0) > 0 and
                ep.get('escape_native_replay',{}).get('continuation_frames') == 20 and group.get('passed') is True and
                group.get('world') == ep['world'] and group.get('retained_group4_preserved') is True,
                'caster survey lacks unchanged mobile input/replay+20/native confirmation/group gates')
        lifecycle=[r for r in ep['rows'] if r['event'] != 'snapshot']
        require([r['event'] for r in lifecycle] == list(EVENTS), 'caster survey mobile lifecycle is incomplete')
        setup,dead,released,restored,before,reselected,complete=lifecycle;token=setup['original_incarnation']
        require(type(row) is dict and set(row) == fields and type(row['schema']) is int and row['schema'] == 1 and
                row['event'] == 'mapped_buttons' and row['route'] == 'owned_active_buttons_original_getters' and
                all(_integer(row[k],0,UINT32) for k in ('slot','entity','unit_type','army','frame','current_actual_entity','current_actual_type','current_actual_army')) and
                _integer(row['world'],1,2) and row['world'] == ep['world'] and
                (row['slot'],row['entity'],row['unit_type'],row['army'],row['frame']) == (1,11,1,1,145) and
                (row['current_actual_entity'],row['current_actual_type'],row['current_actual_army']) == (11,1,1) and
                row['current_admitted'] is True and row['current_initialized'] is True and
                _integer(row['current_native_state'],0,UINT32-1) and row['current_native_state'] != 6 and
                _integer(row['incarnation'],1) and _integer(row['confirmed_incarnation'],1) and
                row['incarnation'] == row['confirmed_incarnation'] == token == restored['current_incarnation'] == ep['fresh']['order']['incarnation'],
                'caster survey actual current mobile/route/schema differs')
        require(_integer(row['tick_ms']) and _integer(row['sample_begin_us']) and _integer(row['sample_end_us']) and
                setup['sampled_us'] <= row['sample_begin_us'] < row['sample_end_us'] < dead['sampled_us'],
                'caster survey QPC bracket is not after setup and before actual speculative death')
        require(not episodes or (row['sample_begin_us'] > episodes[-1]['row']['sample_end_us'] and
                row['tick_ms'] >= episodes[-1]['row']['tick_ms']), 'caster survey rematch clocks regressed/reused')
        for stem in ('source_ids','preview_ids','casting_ids'):
            a,b=row[stem+'_before'],row[stem+'_after']
            require(type(a) is list and type(b) is list and len(a) <= 8192 and len(b) <= 8192 and
                    all(_integer(v,0,UINT32) for v in a+b) and len(set(a)) == len(a) and len(set(b)) == len(b) and a == b,
                    'caster survey changed original selector sets')
        require(row['source_ids_before'] == [11] and all(type(row[k]) is int and row[k] == 1 for k in ('source_count_before','source_count_after')) and
                all(type(row[k]) is int and row[k] == 0 for k in ('pending_before','pending_after')) and
                row['active_caster_before'] is None and row['active_caster_after'] is None and
                row['settings_scope'] == 'AbilityGroup.SmartCasting' and row['activation_performed'] is False and row['caster_class_observed'] is None,
                'caster survey crossed readonly source/queue/settings/active-caster scope')
        require(type(row['active_array_present']) is bool and _integer(row['active_array_count'],0,12) and
                type(row['buttons']) is list and len(row['buttons']) == row['active_array_count'] and
                (row['active_array_present'] or row['active_array_count'] == 0), 'caster survey actual array is incomplete/truncated/unsupported')
        candidates=[button for index,button in enumerate(row['buttons']) if _caster_survey_button(button,index)]
        require(type(row['eligible_slots']) is list and row['eligible_slots'] == [button['slot'] for button in candidates] and
                all(_integer(slot,0,11) for slot in row['eligible_slots']), 'caster survey eligible actual slots/order/duplicates differ')
        episodes.append(dict(passed=True,match=ep['match'],world=ep['world'],row=row,eligible_candidate_count=len(candidates),
            eligible_slots=row['eligible_slots'],eligible_config_ids=[button['config_id'] for button in candidates],
            complete_active_array_recorded=True,readonly_bracket_us=row['sample_end_us']-row['sample_begin_us'],
            ownership_provenance='Frozen helper validates actual selector/panel/button/simulation/frame owners; no invented pointer JSON',
            value_only=True,activation_exercised=False,caster_instance_type_qualified=False,physicalUI=False))
    return dict(passed=True,episodes=episodes,requires_controller_full_closed_native_parity=True,activation_exercised=False,
        active_casting_exercised=False,physicalUI=False,full_mobile_controls_accepted=False,
        scope='Readonly owned active-button array and original getter/field values at145. Zero eligible mappings is complete evidence; no factory lookup, caster instance, activation or target semantics accepted.')


def _focus_request_rows(log, *, match, world, token, restart=False):
    require(type(restart)is bool,'focus restart schema option is not typed')
    rows=_rows(log,'MOBILE FOCUS REQUEST ',match,6 if restart else 5)
    names=['before_repeat','after_repeat']+((['before_cancel','after_cancel','after_restart']if restart else['before_cancel','after_cancel'])if world==2 else[])+['complete']
    require([r.get('event')for r in rows]==names,'accepted no-start fixture event chain incomplete/duplicated')
    fields={'schema','event','world','match','slot','entity','frame','tick_ms','sampled_us','observer_active','observer_world',
        'active_epoch','request_epoch','requested_group','effective_group','active_group','iterator','handle','selector_handle',
        'handle_ready','scheduling','ending','iteration','pending_iteration','pending_count','pending_identities','original_state','yield_bits',
        'held_group','source_ids','logical_ids','selected_ids','current_actor','current_admitted','original_incarnation','current_incarnation',
        'native_identity_present','repeat_calls','cancel_calls','original_callback','original_token','physicalUI'}
    if restart:fields|={'restart_calls','retired_iterator','old_iterator_weak_registered','restart_eligible'}
    for i,row in enumerate(rows):
        require(set(row)==fields and _integer(row['world'],1,2) and row['world']==world and
            type(row['slot'])is int and row['slot']==1 and type(row['entity'])is int and row['entity']==11 and
            _integer(row['frame'],130,279) and _integer(row['tick_ms']) and _integer(row['sampled_us']) and row['physicalUI']is False,
            'focus request fixture schema/owner/clock differs')
        require(all(type(row[k])is bool for k in('observer_active','handle_ready','scheduling','ending','current_admitted','native_identity_present')) and
            _integer(row['observer_world'],0,2) and _integer(row['active_epoch']) and _integer(row['request_epoch']) and
            _integer(row['handle'],0,UINT32) and _integer(row['selector_handle'],0,UINT32) and _integer(row['iteration']) and
            _integer(row['pending_iteration'],0,row['iteration']) and _integer(row['pending_count'],0,1) and
            type(row['pending_identities'])is list and len(row['pending_identities'])==row['pending_count'] and
            (row['pending_iteration']>0)==bool(row['pending_count']), 'focus request active/pending scalar differs')
        for pending in row['pending_identities']:
            require(type(pending)is dict and set(pending)=={'entity','unit_type','army','incarnation'} and
                all(type(pending[k])is int for k in pending) and
                (pending['entity'],pending['unit_type'],pending['army'],pending['incarnation'])==(11,1,1,token),
                'focus request pending identity is not the unchanged canonical member11')
        for key in('source_ids','logical_ids','selected_ids'):
            require(type(row[key])is list and len(row[key])<=4096 and all(_integer(v,0,UINT32)for v in row[key]) and
                len(set(row[key]))==len(row[key]),'focus request original ID set invalid')
        require(_pointer(row['current_actor'])>0 and row['current_admitted'] and row['native_identity_present'] and
            _integer(row['original_incarnation'],1) and _integer(row['current_incarnation'],1) and
            row['original_incarnation']==row['current_incarnation']==token and row['selected_ids']==[11],
            'focus request lost its actual current admitted mobile')
        if row['observer_active']:
            require(row['observer_world']==world and row['active_epoch']>0 and _pointer(row['iterator'])>0 and
                type(row['active_group'])is int and row['active_group']==4 and row['handle_ready'] and not row['scheduling'] and
                not row['ending'] and row['handle']==row['selector_handle'] and row['iteration']>0 and
                _integer(row['original_state'],-2**31,2**31-1) and _integer(row['yield_bits'],0,UINT32) and
                row['source_ids']==row['logical_ids']==[11], 'focus request active iterator/handle/state is not the original owned scope')
        else:
            require(not restart and world==2 and row['event']=='complete' and row['observer_world']==row['active_epoch']==row['request_epoch']==
                row['handle']==row['iteration']==row['pending_iteration']==row['pending_count']==0 and
                not _pointer(row['iterator']) and row['active_group']is None and not row['handle_ready'] and not row['scheduling'] and
                not row['ending'] and row['original_state']is None and row['yield_bits']is None and
                row['source_ids']==row['logical_ids']==[],'focus request fabricated an absent/completed active iterator')
        require(row['request_epoch']==0 and row['requested_group']is None and row['effective_group']is None or
            row['request_epoch']>0 and type(row['requested_group'])is int and row['requested_group']==4 and
            type(row['effective_group'])is int and row['effective_group']==4,'focus request pending epoch/group null semantics differ')
        cancelled=world==2 and (row['event']=='after_cancel' or not restart and row['event']=='complete')
        cancel_called=world==2 and row['event']in('after_cancel','after_restart','complete')
        require(type(row['held_group'])is int and row['held_group']==(-1 if cancelled else 4) and
            type(row['repeat_calls'])is int and row['repeat_calls']==(0 if i==0 else 1) and
            type(row['cancel_calls'])is int and row['cancel_calls']==int(cancel_called),'focus request original call counter/held intent differs')
        if restart:
            restarted=world==2 and row['event']in('after_restart','complete')
            eligible=world==2 and row['event']in('before_cancel','after_cancel','after_restart','complete')
            require(type(row['restart_calls'])is int and row['restart_calls']==int(restarted) and
                type(row['old_iterator_weak_registered'])is bool and row['old_iterator_weak_registered']==restarted and
                type(row['restart_eligible'])is bool and row['restart_eligible']==eligible and
                (_pointer(row['retired_iterator'])>0 if restarted else row['retired_iterator']is None),
                'restart fixture eligibility/call/old weak lifetime proof differs')
        callback='Uncapped.UnitSelector.FocusControlGroupCancel'if'cancel'in row['event']else'Uncapped.UnitSelector.FocusControlGroup'
        expected_token=0x06002220 if'cancel'in row['event']else 0x06002221
        require((row['original_callback']is None and row['original_token']is None)if row['event']=='complete'else
            row['original_callback']==callback and type(row['original_token'])is int and row['original_token']==expected_token,
            'focus request original Void callback provenance differs')
    require(all(b['frame']>=a['frame'] and b['sampled_us']>a['sampled_us'] and b['tick_ms']>=a['tick_ms']for a,b in zip(rows,rows[1:])),
        'focus request observation clock/frame regressed')
    before,after=rows[:2]
    same=('observer_active','observer_world','active_epoch','active_group','iterator','handle','selector_handle','handle_ready','scheduling',
        'ending','iteration','pending_iteration','pending_count','pending_identities','original_state','yield_bits','held_group','source_ids','logical_ids','selected_ids')
    require(before['observer_active'] and after['observer_active'] and all(before[k]==after[k]for k in same) and
        before['frame']==after['frame'] and after['request_epoch']>max(before['active_epoch'],before['request_epoch']),
        'accepted request without Start changed the old active iterator/pending/state or did not advance its independent request nonce')
    require(rows[-1]['frame']>=260 and (rows[-1]['observer_active'] if world==1 or restart else not rows[-1]['observer_active']),
        'focus request completed without expected live/retired scope')
    return rows


def _focus_restart_proof(records, fixture, camera, requests, starts, scheduled, marker, *, epoch, iterator, handle, fresh_us):
    before,cancelled,restarted=fixture[2:5];complete=fixture[-1]
    request=requests[2];start=starts[1];returned=scheduled[1]
    new_epoch=request['row']['request_epoch'];new_iterator=start['row']['iterator'];new_handle=returned['row']['active_handle']
    require(170<=before['frame']==cancelled['frame']==restarted['frame']<180 and
        before['sampled_us']<cancelled['sampled_us']<restarted['sampled_us']<fresh_us and before['restart_eligible']is True and
        before['active_epoch']==cancelled['active_epoch']==epoch and before['iterator']==cancelled['iterator']==iterator and
        before['handle']==cancelled['handle']==handle and before['iteration']==cancelled['iteration'] and
        before['source_ids']==cancelled['source_ids']==before['logical_ids']==cancelled['logical_ids']==[11],
        'same-callback original cancel/restart lacks old live scope/eligibility/boundary proof')
    require(marker('after_cancel')<request['line']<start['line']<returned['line']<marker('after_restart') and
        new_epoch>max(epoch,before['request_epoch']) and new_iterator is not None and new_iterator!=iterator and
        start['row']['original_state']==0 and start['row']['iteration']==0 and start['row']['active_handle']is None and
        start['row']['request_epoch']==returned['row']['request_epoch']==new_epoch and
        restarted['active_epoch']==complete['active_epoch']==new_epoch and restarted['request_epoch']==complete['request_epoch']==0 and
        restarted['iterator']==complete['iterator']==new_iterator and restarted['handle']==complete['handle']==new_handle and
        restarted['retired_iterator']==complete['retired_iterator']==iterator and restarted['old_iterator_weak_registered']is True,
        'original restart did not install a genuine new iterator/consume its request/register the old identity')
    superseded=[x for x in records if x['row']['event']=='terminal'and x['row']['stage']=='superseded']
    require(len(superseded)==1 and request['line']<superseded[0]['line']<start['line'] and
        superseded[0]['row']['request_epoch']==superseded[0]['row']['active_epoch']==epoch and superseded[0]['row']['iterator']==iterator and
        superseded[0]['row']['active_iterator']==iterator and superseded[0]['row']['active_handle']==handle and
        superseded[0]['row']['source_ids']==superseded[0]['row']['logical_ids']==[11],
        'superseded terminal was emitted after installation or relabeled with new request metadata')
    new_iterations=[x for x in records if x['row']['event']=='iteration'and x['row']['request_epoch']==new_epoch]
    require(new_iterations and [x['row']['iteration']for x in new_iterations]==list(range(1,len(new_iterations)+1)) and
        start['line']<new_iterations[0]['line']<returned['line'] and new_iterations[0]['row']['original_result']is True and
        max(x['row']['iteration']for x in new_iterations if x['line']<marker('after_restart'))==restarted['iteration'],
        'restart lacks actual synchronous new MoveNext inside original Start before scheduled return')
    require(all(x['row']['request_epoch']==x['row']['active_epoch']==new_epoch and x['row']['iterator']==x['row']['active_iterator']==new_iterator
                for x in records if x['row']['route']=='repeat'and x['line']>=start['line']) and
        all(x['row']['active_handle']==new_handle for x in records if x['line']>=returned['line']),
        'restarted repeat callbacks reused the old installed scope')
    pair=camera.get((new_epoch,'initial',0),[])
    require(len(pair)==2 and request['line']<pair[0]['line']<pair[-1]['line']<superseded[0]['line'] and
        all(x['row']['active_epoch']==epoch and x['row']['active_iterator']==iterator for x in pair),
        'restart initial camera is not separately scoped while the old session remains installed')
    late_old=[x for x in records if x['row']['event']=='camera'and x['row']['route']=='repeat'and
        (x['row']['request_epoch']==epoch or x['row']['iterator']==iterator)and x['line']>superseded[0]['line']]
    require(not late_old and not any(x['row']['event']=='cancel_observed'and x['line']>start['line']for x in records) and
        not any(x['row']['event']=='terminal'and x['row']['sampled_us']<=complete['sampled_us']and x is not superseded[0]for x in records) and
        any(x['row']['request_epoch']==new_epoch and x['row']['route']=='repeat'and x['row']['stage']=='returned'and
            x['row']['sampled_us']>=complete['sampled_us']for x in records if x['row']['event']=='camera'),
        'old camera forwarded after retirement or new active repeat failed continuity through completion')
    return dict(restart_epoch=new_epoch,restart_iterator=new_iterator,restart_handle=new_handle,
        original_restart_frame=restarted['frame'],new_outer_iterations=len(new_iterations),old_iterator_weak_registration_observed=True,
        old_registration_is_cached_certificate_at_complete=True,retired_old_camera_calls=0,late_old_next_attempt_observed=False,
        handle_inequality_required=False,superseded_old_scope=superseded[0],synchronous_first_new_iteration=new_iterations[0])


def _evaluate_focus_no_start(log, *, attacker_log, mobile_episodes, group_intent, restart=False):
    require(type(mobile_episodes)is list and len(mobile_episodes)==2 and [e.get('world')for e in mobile_episodes]==[1,2] and
        group_intent.get('passed')is True and group_intent.get('user_edits')is False and len(group_intent.get('episodes',[]))==2,
        'no-start focus needs both mobile/preserved-group episodes')
    matches=[e.get('match')for e in mobile_episodes]
    require(len(set(matches))==2 and [e.get('match')for e in group_intent['episodes']]==matches and
        type(attacker_log)is str and len(attacker_log)<=32*1024*1024 and
        'MOVEMENT FOCUS 'not in attacker_log and 'MOBILE FOCUS REQUEST 'not in attacker_log,'no-start focus match/guest-only scope differs')
    product=_group_focus_product_rows(log,matches=matches,no_start=True)
    require(not any(x['row']['stage']=='failed'for x in product),'focus product recorded failure')
    index={}
    for i,line in enumerate(log.splitlines()):
        for prefix in('MOBILE FOCUS REQUEST ','MOBILE CORRECTION '):
            if prefix not in line:continue
            row=json.loads(line.split(prefix,1)[1],object_pairs_hook=_unique_object)
            require(row.get('match')in matches,'focus request extra unmatched fixture event')
            if row.get('event')!='snapshot':
                key=(prefix,row['match'],row['event']);require(key not in index,'duplicate focus request/lifecycle event');index[key]=i
    result=[]
    for ep,group in zip(mobile_episodes,group_intent['episodes']):
        require(ep.get('passed')is True and ep.get('fresh_motion',{}).get('passed')is True and ep.get('fresh_assignment_span',{}).get('hashes_match')is True and
            ep.get('escape_native_replay',{}).get('promotion_group_replayed_delta',0)>0 and ep['escape_native_replay'].get('continuation_frames')==20 and
            ep.get('fresh_native_confirmation',{}).get('continuation_frames')==20 and group.get('passed')is True and group.get('world')==ep['world'] and
            group.get('retained_group4_preserved')is True,'no-start focus lost original mobile motion/phase/replay/native/group gates')
        lifecycle=[r for r in ep['rows']if r['event']!='snapshot'];require([r['event']for r in lifecycle]==list(EVENTS),'focus mobile lifecycle incomplete')
        setup,dead,released,restored,_,_,complete=lifecycle;world=ep['world'];match=ep['match'];token=setup['original_incarnation']
        require(token==restored['current_incarnation']==ep['fresh']['order']['incarnation'],'focus current mobile incarnation differs')
        fixture=_focus_request_rows(log,match=match,world=world,token=token,restart=restart);before,after=fixture[:2]
        marker=lambda event:index['MOBILE FOCUS REQUEST ',match,event]
        require(restored['sampled_us']<=before['sampled_us']<after['sampled_us']<ep['fresh']['order']['sampled_us'] and
            restored['frame']<=before['frame']<180 and fixture[-1]['frame']==complete['frame'] and
            fixture[-1]['sampled_us']<=complete['sampled_us'],'focus repeated request does not bind restored/current/fresh boundaries')
        records=[x for x in product if x['row']['world']==world];rows=[x['row']for x in records]
        require(rows and all(r['group']==r['requested_group']==4 for r in rows) and len({r['selector']for r in rows})==1,
            'focus requested/active group or selector changed')
        requests=[x for x in records if x['row']['event']=='request'];starts=[x for x in records if x['row']['event']=='start'];scheduled=[x for x in records if x['row']['event']=='scheduled']
        restarting=restart and world==2
        require(len(requests)==(3 if restarting else 2) and all(x['row']['stage']=='accepted_repeat'for x in requests) and
            len(starts)==len(scheduled)==(2 if restarting else 1), 'focus accepted request/real Start count differs')
        first,second=[x['row']for x in requests[:2]];epoch=first['request_epoch'];new_epoch=second['request_epoch'];iterator=starts[0]['row']['iterator'];handle=scheduled[0]['row']['active_handle']
        require(epoch>0 and new_epoch>epoch and before['active_epoch']==after['active_epoch']==epoch and after['request_epoch']==new_epoch and
            iterator==before['iterator'] and handle==before['handle'] and first['active_epoch']==0 and first['active_iterator']is None and
            starts[0]['row']['request_epoch']==scheduled[0]['row']['request_epoch']==epoch and
            requests[0]['line']<starts[0]['line']<scheduled[0]['line']<index['MOBILE CORRECTION ',match,EVENTS[0]] and
            marker('before_repeat')<requests[1]['line']<marker('after_repeat'),
            'focus accepted request/new nonce became the old active scope or Start provenance differs')
        old_records=[x for x in records if not restarting or x['line']<starts[1]['line']]
        require(second['active_epoch']==epoch and second['active_iterator']==iterator and second['active_handle']==handle and
            all(r['request_epoch']==epoch and r['active_epoch']==epoch and r['active_iterator']==iterator for x in old_records for r in(x['row'],)if r['route']=='repeat') and
            all(r['active_handle']==handle for x in old_records if x['line']>=scheduled[0]['line']for r in(x['row'],)),
            'no-start accepted request changed active epoch/iterator/handle')
        all_iterations=[x for x in records if x['row']['event']=='iteration']
        iterations=[x for x in all_iterations if x['row']['request_epoch']==epoch]
        by_iteration={(x['row']['request_epoch'],x['row']['iteration']):x for x in all_iterations}
        require([x['row']['iteration']for x in iterations]==list(range(1,len(iterations)+1)) and
            max(x['row']['iteration']for x in iterations if x['line']<marker('before_repeat'))==before['iteration'] and
            not any(marker('before_repeat')<x['line']<marker('after_repeat')for x in iterations),
            'focus active iteration count changed during accepted no-start request or has gaps')
        camera={}
        for x in records:
            r=x['row']
            if r['actor']is not None:require((r['entity'],r['unit_type'],r['army'],r['incarnation'])==(11,1,1,token),'focus forwarded a wrong current member')
            if r['event']=='camera':camera.setdefault((r['request_epoch'],r['route'],r['iteration']),[]).append(x)
        returned=[]
        for key,pair in camera.items():
            require(len(pair)==2 and [x['row']['stage']for x in pair]==['requested','returned'],'focus camera request/return missing or duplicated')
            require(all(pair[0]['row'][k]==pair[1]['row'][k]for k in('request_epoch','route','iterator','iteration','active_epoch','active_iterator','active_handle','actor','entity','unit_type','army','incarnation')),
                'focus camera receipt changed its request/active lease')
            if key[1]=='repeat':
                decision=by_iteration.get((key[0],key[2]));require(decision is not None and decision['row']['stage']in('delegate','refind') and
                    decision['row']['original_result']is True and pair[-1]['line']<decision['line'],'focus camera has no same-iteration original result')
            returned.append(pair[-1])
        initial_epochs={epoch,new_epoch}|({requests[2]['row']['request_epoch']}if restarting else set())
        require({key for key in camera if key[1]=='initial'}=={(value,'initial',0)for value in initial_epochs} and
            requests[0]['line']<camera[epoch,'initial',0][0]['line']<camera[epoch,'initial',0][-1]['line']<starts[0]['line'] and
            requests[1]['line']<camera[new_epoch,'initial',0][0]['line']<camera[new_epoch,'initial',0][-1]['line']<marker('after_repeat'),
            'focus no-start request lacks its distinct actual initial-camera callback pair')
        pending=[x for x in iterations if x['row']['stage']=='waiting_absent']
        require(pending and all((epoch,'repeat',x['row']['iteration'])not in camera for x in pending) and any(
            x['line']>index['MOBILE CORRECTION ',match,EVENTS[2]] and released['sampled_us']<=x['row']['sampled_us']<restored['sampled_us'] and
            x['row']['source_ids']==x['row']['logical_ids']==[11]for x in pending),'focus lacks actual post-release no-camera waiting')
        require(any(x['row']['route']=='repeat'and x['row']['sampled_us']<dead['sampled_us']for x in returned) and
            not any(x['row']['stage']=='ending_delegate'and x['row']['sampled_us']<=fixture[-1]['sampled_us']for x in records),
            'focus initial positive continuity/canonical identity ended before completion')
        resumed=[x for x in iterations if x['line']>marker('after_repeat')]
        require(resumed and resumed[0]['row']['iteration']==before['iteration']+1 and
            (epoch,'repeat',resumed[0]['row']['iteration'])in camera,'old active iterator did not resume its real member after no-start request')
        if world==1:
            require(not any(x['row']['event']in('cancel_observed','terminal')and x['row']['sampled_us']<=fixture[-1]['sampled_us']for x in records) and
                any(x['row']['route']=='repeat'and x['row']['sampled_us']>=fixture[-1]['sampled_us']for x in returned),
                'accepted no-start request did not preserve held repeat through completion')
            branch='accepted_no_start_held_continuity'
        elif not restarting:
            cancel_before,cancel_after=fixture[2:4]
            require(170<=cancel_before['frame']==cancel_after['frame']<180 and after['sampled_us']<cancel_before['sampled_us'] and
                cancel_before['active_epoch']==cancel_after['active_epoch']==epoch and cancel_before['iterator']==cancel_after['iterator']==iterator and
                cancel_before['handle']==cancel_after['handle']==handle and cancel_before['iteration']==cancel_after['iteration'] and
                max(x['row']['iteration']for x in iterations if x['line']<marker('before_cancel'))==cancel_before['iteration'],
                'focus original post-repeat cancellation lacks its still-owned active scope')
            cancelled=[x for x in records if x['row']['event']=='cancel_observed'];tail=[x for x in iterations if x['line']>marker('after_cancel')]
            terminals=[x for x in records if x['row']['event']=='terminal'and x['row']['stage']=='original_false']
            require(tail and cancelled and tail[0]['row']['iteration']==cancel_before['iteration']+1 and
                [x['row']['iteration']for x in cancelled]==[x['row']['iteration']for x in tail] and
                all(a['line']<b['line'] and a['row']['held_group']==b['row']['held_group']==-1 and b['row']['stage']=='cancel_delegate' and
                    b['row']['actor']is None for a,b in zip(cancelled,tail)) and
                all(x['row']['original_result']is True for x in tail[:-1]) and tail[-1]['row']['original_result']is False and
                len(terminals)==1 and terminals[0]['row']['iteration']==tail[-1]['row']['iteration'] and
                tail[-1]['line']<terminals[0]['line'] and terminals[0]['row']['sampled_us']<ep['fresh']['order']['sampled_us'] and
                not any(x['line']>marker('after_cancel')for x in returned),'original cancel did not terminate the old iterator without restarting/forwarding')
            branch='accepted_no_start_then_original_cancel'
        else:
            restart_proof=_focus_restart_proof(records,fixture,camera,requests,starts,scheduled,marker,
                epoch=epoch,iterator=iterator,handle=handle,fresh_us=ep['fresh']['order']['sampled_us'])
            branch='accepted_no_start_then_same_world_restart'
        result.append(dict(passed=True,match=match,world=world,path=branch,fixture_rows=fixture,active_epoch=epoch,accepted_no_start_request_epoch=new_epoch,
            iterator=iterator,handle=handle,outer_iterations=len(iterations),camera_callbacks_returned=len(returned),waiting_absent_iterations=len(pending),
            pending_count_before=before['pending_count'],pending_count_after=after['pending_count'],nonzero_pending_preservation_exercised=before['pending_count']>0,
            no_new_start=True,request_active_scope_verified=True,physicalUI=False,full_mobile_controls_accepted=False))
        if restarting:result[-1].update(restart_proof,no_new_start_during_first_repeat=True,no_new_start=False)
    answer=dict(passed=True,episodes=result,no_start_variant=True,accepted_no_start_exercised=True,request_active_scope_verified=True,
        accepted_group_switch_exercised=False,requires_controller_full_closed_native_parity=True,physicalUI=False,full_mobile_controls_accepted=False,
        scope='Actual same-group accepted original Void Focus request/initial camera without Start; old active iterator/epoch/handle/pending preserved and real repeat continues or originalCancel terminates it. No physicalUI/group-switch/casting claim.')
    if restart:answer.update(restart_variant=True,accepted_restart_exercised=True,old_iterator_retirement_verified=True,
        late_old_next_attempt_observed=False,scope='First accepted no-start preserves old scope; actual same-callback originalCancel/Focus then supersedes it and installs a genuine new active iterator. No manual/observed late oldNext, handle inequality, physicalUI or group-switch claim.')
    return answer


def evaluate_group_focus(log, *, attacker_log, mobile_episodes, group_intent, no_start=False, restart=False):
    """Complete owned repeat-focus trace, distinct from cached-focus snapshots."""
    require(type(no_start)is bool,'focus no-start variant option is not typed')
    require(type(restart)is bool and (not restart or no_start),'focus restart requires typed no-start variant')
    if no_start:
        return _evaluate_focus_no_start(log,attacker_log=attacker_log,mobile_episodes=mobile_episodes,group_intent=group_intent,restart=restart)
    require(type(mobile_episodes) is list and len(mobile_episodes) == 2 and
            [ep.get('world') for ep in mobile_episodes] == [1,2] and
            type(group_intent) is dict and group_intent.get('passed') is True and group_intent.get('user_edits') is False and
            len(group_intent.get('episodes',[])) == 2, 'focus requires both passed mobile/preserved-group episodes')
    matches=[ep.get('match') for ep in mobile_episodes]
    require(len(set(matches)) == 2 and all(type(match) is str and re.fullmatch('[a-f0-9]{32}',match) for match in matches) and
            [r.get('match') for r in group_intent['episodes']] == matches,
            'focus actual match/rematch binding differs')
    require(type(attacker_log) is str and len(attacker_log) <= 32*1024*1024 and
            'MOVEMENT FOCUS ' not in attacker_log and 'MOBILE GROUP FOCUS ' not in attacker_log,
            'attacker emitted the victim-only focus witness')
    product=_group_focus_product_rows(log,matches=matches)
    require(not any(item['row']['event'] == 'terminal' and item['row']['stage'] == 'failed' for item in product),
            'focus product recorded a runtime failure')
    fixture_index={};release_index={}
    for i,line in enumerate(log.splitlines()):
        for prefix in ('MOBILE GROUP FOCUS ','MOBILE CORRECTION '):
            if prefix not in line:continue
            raw=line.split(prefix,1)[1];require(0 < len(raw) <= 8192, 'focus fixture diagnostic exceeds bound')
            row=json.loads(raw,object_pairs_hook=_unique_object)
            if prefix == 'MOBILE GROUP FOCUS ':
                require(type(row) is dict and row.get('match') in matches, 'focus fixture extra match')
                key=(row['match'],row.get('event'));require(key not in fixture_index,'duplicate focus fixture event')
                fixture_index[key]=i
            elif row.get('event') == 'original_mobile_release_observed':
                require(row['match'] not in release_index,'duplicate focus physical release')
                release_index[row['match']]=i
    result=[]
    for ep,group in zip(mobile_episodes,group_intent['episodes']):
        require(ep.get('passed') is True and ep.get('fresh_motion',{}).get('passed') is True and
                ep.get('fresh_assignment_span',{}).get('hashes_match') is True and
                ep.get('escape_native_replay',{}).get('promotion_group_replayed_delta',0) > 0 and
                ep.get('escape_native_replay',{}).get('continuation_frames') == 20 and
                group.get('passed') is True and group.get('world') == ep['world'] and group.get('retained_group4_preserved') is True,
                'focus lacks unchanged mobile input/replay+20/native confirmation/group gates')
        lifecycle=[r for r in ep['rows'] if r['event'] != 'snapshot']
        require([r['event'] for r in lifecycle] == list(EVENTS), 'focus mobile lifecycle is incomplete')
        setup,dead,released,restored,before_fresh,reselected,complete=lifecycle
        token=setup['original_incarnation'];world=ep['world'];match=ep['match']
        require(token == restored['current_incarnation'] == ep['fresh']['order']['incarnation'] > 0,
                'focus canonical mobile incarnation changed')
        fixture=_group_focus_fixture_rows(log,match=match,world=world,token=token)
        require(fixture[0]['sampled_us'] >= setup['sampled_us'] and fixture[-2]['sampled_us'] >= restored['sampled_us'] and
                fixture[-2]['frame'] == restored['frame'] and fixture[-1]['sampled_us'] <= complete['sampled_us'] and
                fixture[-1]['frame'] == complete['frame'], 'focus fixture does not bind actual mobile lifecycle')
        records=[item for item in product if item['row']['world'] == world];rows=[item['row'] for item in records]
        require(rows and all(r['selector'] == fixture[0]['selector'] and r['group'] == 4 for r in rows), 'focus product selector/requested group differs')
        require(not any(r['stage'] == 'ending_delegate' and r['sampled_us'] <= fixture[-1]['sampled_us'] for r in rows),
                'held focus ended its canonical/member identity before completion')
        require(all(r['held_group'] == 4 for r in rows if r['sampled_us'] <= fixture[-1]['sampled_us'] and
                    (r['event'] == 'iteration' and r['stage'] != 'cancel_delegate' or
                     r['event'] == 'camera' and r['route'] == 'repeat')), 'focus held intent silently switched groups')
        require(len({r['request_epoch'] for r in rows}) == 1, 'focus silently restarted/superseded its accepted request epoch')
        request=[item for item in records if item['row']['event'] == 'request']
        start=[item for item in records if item['row']['event'] == 'start']
        scheduled=[item for item in records if item['row']['event'] == 'scheduled']
        require(len(request) == len(start) == len(scheduled) == 1 and request[0]['line'] < start[0]['line'] < scheduled[0]['line'] <
                fixture_index[match,'setup'] and scheduled[0]['row']['sampled_us'] <= fixture[0]['sampled_us'],
                'focus lacks one actual accepted/scheduled original iterator before setup')
        iterator=start[0]['row']['iterator'];epoch=start[0]['row']['request_epoch']
        require(iterator is not None and start[0]['row']['iteration'] == 0 and start[0]['row']['original_state'] == 0 and
                all(r['iterator'] == iterator for r in rows if r['iterator'] is not None), 'focus iterator was replaced/reused inside the owned epoch')
        iterations=[item for item in records if item['row']['event'] == 'iteration']
        require([item['row']['iteration'] for item in iterations] == list(range(1,len(iterations)+1)),
                'focus outer MoveNext iteration coverage has a gap/duplicate')
        by_iteration={item['row']['iteration']:item for item in iterations}
        false_iterations=[item for item in iterations if item['row']['original_result'] is False]
        false_terminals=[item for item in records if item['row']['event'] == 'terminal' and item['row']['stage'] == 'original_false']
        require(len(false_iterations) == len(false_terminals) and len(false_iterations) <= 1 and
                all(exit_['row']['iteration'] == call['row']['iteration'] and call['line'] < exit_['line']
                    for call,exit_ in zip(false_iterations,false_terminals)) and
                (not false_iterations or false_iterations[-1]['row']['iteration'] == len(iterations)),
                'focus original false terminal lacks its actual last delegated receipt')
        camera={}
        for item in records:
            row=item['row']
            if row['actor'] is not None:
                require((row['entity'],row['unit_type'],row['army'],row['incarnation']) == (11,1,1,token),
                        'owned held focus forwarded a different member/incarnation')
            if row['event'] != 'camera':continue
            key=(row['route'],row['iteration']);camera.setdefault(key,[]).append(item)
        returned=[]
        for key,pair in camera.items():
            require(len(pair) == 2 and [item['row']['stage'] for item in pair] == ['requested','returned'],
                    'focus camera callback requested/returned proof incomplete/duplicated')
            a,b=[item['row'] for item in pair]
            require(all(a[k] == b[k] for k in ('selector','iterator','request_epoch','iteration','group','actor','entity','unit_type','army','incarnation')),
                    'focus camera returned under another lease/iterator')
            if key[0] == 'repeat':
                decision=by_iteration.get(key[1])
                require(decision is not None and decision['row']['stage'] in ('delegate','refind') and
                        decision['row']['original_result'] is True and start[0]['line'] < pair[0]['line'] and
                        pair[-1]['line'] < decision['line'],
                        'focus camera has no same-iteration successful original MoveNext receipt')
            returned.append(pair[-1])
        require(('initial',0) in camera and len(camera['initial',0]) == 2,
                'original group focus has no positive initial camera-call receipt')
        pending=[item for item in iterations if item['row']['stage'] == 'waiting_absent']
        require(pending and all(('repeat',item['row']['iteration']) not in camera for item in pending),
                'focus pending path forwarded a camera or was never exercised')
        actual_absence=[item for item in pending if item['line'] > release_index.get(match,2**63) and
            released['sampled_us'] <= item['row']['sampled_us'] < restored['sampled_us'] and
            item['row']['source_ids'] == item['row']['logical_ids'] == [11]]
        require(actual_absence, 'focus has no waiting decision after complete physical release')
        require(any(item['row']['route'] == 'repeat' and item['row']['sampled_us'] < dead['sampled_us'] for item in returned),
                'focus never positively forwarded intended member before speculative death')
        if world == 1:
            after=[item for item in returned if item['row']['route'] == 'repeat' and
                item['row']['sampled_us'] > actual_absence[-1]['row']['sampled_us'] and
                restored['sampled_us'] <= item['row']['sampled_us'] < ep['fresh']['order']['sampled_us']]
            require(after and any(item['row']['route'] == 'repeat' and item['row']['sampled_us'] >= fixture[-1]['sampled_us']
                        for item in returned) and
                    not any(item['row']['event'] in ('terminal','cancel_observed') and
                        item['row']['sampled_us'] <= fixture[-1]['sampled_us'] for item in records),
                    'held focus did not resume the same current member and persist through completion')
            branch='held_focus_continuity';witness=actual_absence[-1];resume=after[0]
        else:
            before,after_cancel=fixture[1:3]
            require(released['sampled_us'] <= before['sampled_us'] <= after_cancel['sampled_us'] < restored['sampled_us'] and
                    released['frame'] <= before['frame'] <= restored['frame'], 'original focus Cancel was not during actual physical absence')
            saved=[item for item in actual_absence if item['row']['iteration'] == before['pending_iteration'] and
                item['row']['request_epoch'] == before['pending_epoch'] and item['row']['iterator'] == before['pending_iterator'] and
                item['line'] < fixture_index[match,'before_cancel'] and item['row']['sampled_us'] <= before['sampled_us']]
            require(len(saved) == 1 and epoch == before['pending_epoch'] and iterator == before['pending_iterator'] and
                    max(item['row']['iteration'] for item in iterations if item['line'] < fixture_index[match,'before_cancel']) == before['pending_iteration'],
                    'original focus Cancel does not bind the latest post-release pending iterator')
            cancelled=[item for item in records if item['row']['event'] == 'cancel_observed']
            require(cancelled and cancelled[0]['line'] > fixture_index[match,'after_cancel'] and
                    cancelled[0]['row']['sampled_us'] >= after_cancel['sampled_us'] and
                    cancelled[0]['row']['iteration'] == before['pending_iteration']+1 and cancelled[0]['row']['held_group'] == -1,
                    'original Cancel was not consumed by the next same owned iterator')
            cancel_iterations=[item for item in iterations if item['row']['iteration'] > before['pending_iteration']]
            require([item['row']['iteration'] for item in cancelled] == [item['row']['iteration'] for item in cancel_iterations] and
                    all(item['row']['stage'] == 'cancel_delegate' and item['row']['held_group'] == -1 and
                        item['row']['actor'] is None and observation['row']['held_group'] == -1 and
                        observation['line'] < item['line'] for observation,item in zip(cancelled,cancel_iterations)),
                    'original pending cancel did not remain a consecutive cancelled delegation chain')
            final=cancel_iterations[-1] if cancel_iterations else None
            terminals=[item for item in records if item['row']['event'] == 'terminal' and item['row']['stage'] == 'original_false']
            require(final is not None and final['row']['stage'] == 'cancel_delegate' and final['row']['original_result'] is False and
                    all(item['row']['original_result'] is True for item in cancel_iterations[:-1]) and
                    len(terminals) == 1 and terminals[0]['row']['iteration'] == final['row']['iteration'] and
                    final['line'] < terminals[0]['line'] and terminals[0]['row']['sampled_us'] < ep['fresh']['order']['sampled_us'] and
                    not any(item['line'] > fixture_index[match,'after_cancel'] for item in returned) and
                    not any(item['row']['iteration'] > final['row']['iteration'] for item in iterations),
                    'cancelled held focus forwarded/restarted or did not naturally terminate')
            branch='original_pending_cancel_honored';witness=saved[0];resume=None
        result.append(dict(passed=True,match=match,world=world,path=branch,fixture_rows=fixture,
            request_epoch=epoch,iterator=iterator,product_events=len(records),outer_iterations=len(iterations),
            camera_callbacks_returned=len(returned),waiting_absent_iterations=len(pending),post_release_pending=witness,
            restored_camera_return=resume,all_camera_targets_current_member11=True,pending_camera_calls=0,
            no_silent_restart=True,source_event_sequence_complete=True,physicalUI=False,full_mobile_controls_accepted=False))
    return dict(passed=True,episodes=result,requires_controller_full_closed_native_parity=True,
        physicalUI=False,active_casting_exercised=False,accepted_group_switch_exercised=False,full_mobile_controls_accepted=False,
        scope='Complete owned original iterator/camera callback trace: same-member continuity OR original pending cancel. Snapshot cached predicates alone, physical camera pixels, group switching and active casting are not accepted.')


def evaluate_group_recall(log, *, attacker_log, mobile_episodes, group_intent):
    """Join original group recall observations to the passed mobile slice.

    Retained numeric membership is not a selectable native actor. The actual
    callback and selection snapshots establish that distinction; this parser
    does not invent a filter invocation, physical keypress or camera call.
    """
    require(type(mobile_episodes) is list and len(mobile_episodes) == 2 and
            type(group_intent) is dict and group_intent.get('passed') is True and
            group_intent.get('user_edits') is False and len(group_intent.get('episodes',[])) == 2,
            'recall requires both passed mobile and retained-group episodes')
    matches=[ep.get('match') for ep in mobile_episodes]
    require(len(set(matches)) == 2 and all(type(m) is str and re.fullmatch('[a-f0-9]{32}',m) for m in matches) and
            len({ep.get('world') for ep in mobile_episodes}) == 2 and
            [ep.get('match') for ep in group_intent['episodes']] == matches,
            'recall match/world rematch binding differs')
    prefix='MOBILE GROUP RECALL '
    require(type(log) is str and type(attacker_log) is str and len(log) <= 32*1024*1024 and
            len(attacker_log) <= 32*1024*1024 and prefix not in attacker_log,
            'recall log scope exceeds bound or attacker emitted victim recall')
    count=0
    for line in log.splitlines():
        if prefix not in line:continue
        raw=line.split(prefix,1)[1];require(0 < len(raw) <= 8192, 'recall diagnostic exceeds bound')
        row=json.loads(raw,object_pairs_hook=_unique_object)
        require(type(row) is dict and row.get('match') in matches, 'recall belongs to an extra unqualified match')
        count+=1;require(count <= 12, 'recall exceeds two-round event bound')
    names=['before_absent_recall','focus_cancelled','after_absent_recall',
           'before_restored_recall','after_restored_recall','complete']
    fields={'schema','event','world','match','slot','entity','unit_type','army','frame','completed_frame',
        'tick_ms','sampled_us','incarnation','confirmed_incarnation','current_incarnation','retained_group',
        'group_ids','selected_ids','preview_ids','casting_ids','native_identity_present','current_admitted','source_resolvable_count',
        'current_actor','current_actual_entity','current_actual_type','current_actual_army','focus_group',
        'pending_commands','cancel_callback','cancel_token','actuate_callback','actuate_token','actuate_result','physicalUI'}
    result=[]
    for ep,group in zip(mobile_episodes,group_intent['episodes']):
        require(ep.get('passed') is True and ep.get('fresh_motion',{}).get('passed') is True and
                ep.get('fresh_assignment_span',{}).get('hashes_match') is True and
                ep.get('escape_native_replay',{}).get('promotion_group_replayed_delta',0) > 0 and
                ep.get('escape_native_replay',{}).get('continuation_frames') == 20 and
                group.get('passed') is True and group.get('world') == ep['world'] and
                group.get('retained_group4_preserved') is True,
                'recall lacks passed original input/replay+20/native confirmation/group preservation')
        lifecycle=[r for r in ep['rows'] if r['event'] != 'snapshot']
        require([r['event'] for r in lifecycle] == list(EVENTS), 'recall mobile lifecycle is incomplete')
        setup,dead,released,restored,before_fresh,reselected,complete=lifecycle
        token=setup['original_incarnation'];world=ep['world'];match=ep['match']
        require(token == restored['current_incarnation'] == ep['fresh']['order']['incarnation'] > 0,
                'recall canonical mobile incarnation changed')
        rows=_rows(log,prefix,match,6)
        require([r.get('event') for r in rows] == names, 'recall original callback/event chain is incomplete')
        for row in rows:
            _common(row,world=world)
            require(set(row) == fields and type(row['slot']) is int and row['slot'] == 1 and
                    (row['entity'],row['unit_type'],row['army']) == (11,1,1) and
                    _integer(row['completed_frame'],-1,2**31-1) and
                    _integer(row['incarnation'],1) and _integer(row['confirmed_incarnation'],1) and
                    row['incarnation'] == row['confirmed_incarnation'] == token and
                    _integer(row['current_incarnation']) and type(row['retained_group']) is int and
                    row['retained_group'] == 4 and type(row['native_identity_present']) is bool and
                    type(row['current_admitted']) is bool and _integer(row['focus_group'],-1,2**31-1) and
                    type(row['pending_commands']) is int and row['pending_commands'] == 0 and
                    _integer(row['source_resolvable_count'],0,1), 'recall observed identity/schema/group differs')
            _pointer(row['current_actor'])
            for key in ('current_actual_entity','current_actual_type','current_actual_army'):
                require(row[key] is None or _integer(row[key],0,UINT32), 'recall actual identity nullable field differs')
            for key in ('group_ids','selected_ids','preview_ids','casting_ids'):
                ids=row[key]
                require(type(ids) is list and len(ids) <= 4096 and all(_integer(v,0,UINT32) for v in ids) and
                        len(set(ids)) == len(ids), 'recall observed ID set is invalid')
            require(row['group_ids'] == [11], 'recall lost retained original group4 intent')
            if row['event'] == 'focus_cancelled':
                require(row['cancel_callback'] == 'Uncapped.UnitSelector.FocusControlGroupCancel' and
                        row['cancel_token'] == '06002220' and all(row[k] is None for k in
                        ('actuate_callback','actuate_token','actuate_result')), 'recall original Cancel callback differs')
            elif row['event'] in ('after_absent_recall','after_restored_recall'):
                require(row['actuate_callback'] == 'Uncapped.UnitSelector.ActuateControlGroup' and
                        row['actuate_token'] == '0600220f' and type(row['actuate_result']) is bool and
                        row['cancel_callback'] is None and row['cancel_token'] is None,
                        'recall original Actuate callback/result differs')
            else:
                require(all(row[k] is None for k in ('cancel_callback','cancel_token',
                        'actuate_callback','actuate_token','actuate_result')), 'unobserved recall callback was fabricated')
        require(all(b['frame'] >= a['frame'] and b['tick_ms'] >= a['tick_ms'] and b['sampled_us'] >= a['sampled_us']
                    for a,b in zip(rows,rows[1:])), 'recall actual event clocks/frame regressed')
        absent,cancel,after_absent,before_restored,after_restored,last=rows
        require(all(not r['native_identity_present'] and not r['current_admitted'] and
                    _pointer(r['current_actor']) == 0 and r['current_incarnation'] == 0 and
                    all(r[k] is None for k in ('current_actual_entity','current_actual_type','current_actual_army')) and
                    released['frame'] <= r['frame'] <= restored['frame'] and
                    released['sampled_us'] <= r['sampled_us'] < restored['sampled_us'] for r in rows[:3]) and
                absent['frame'] == cancel['frame'] == after_absent['frame'] and cancel['focus_group'] == -1,
                'original recall did not exclude unavailable mobile during actual absence')
        # The original Count counts physically type-resolvable IDs, not the
        # retained numeric group. A legal Count0 refusal returns before opening
        # the selection scope; it must not be reported as an exercised filter.
        require(after_absent['source_resolvable_count'] == cancel['source_resolvable_count'],
                'absent recall original source count changed inside its callback')
        if cancel['source_resolvable_count'] == 0:
            require(after_absent['actuate_result'] is False and all(after_absent[k] == cancel[k]
                    for k in ('selected_ids','preview_ids','casting_ids')),
                    'absent recall Count0 refusal did not leave original selector sets unchanged')
            classification='legal_absent_refusal'
        else:
            require(after_absent['actuate_result'] is True and after_absent['selected_ids'] == [] and
                    after_absent['preview_ids'] == [], 'absent recall Count1 did not complete original empty-selection branch')
            classification='excluded_on_recall'
        require(all(r['native_identity_present'] and r['current_admitted'] and _pointer(r['current_actor']) > 0 and
                    r['current_incarnation'] == token and
                    r['source_resolvable_count'] == 1 and
                    (r['current_actual_entity'],r['current_actual_type'],r['current_actual_army']) == (11,1,1)
                    for r in rows[3:]) and
                restored['sampled_us'] <= before_restored['sampled_us'] <= after_restored['sampled_us'] < before_fresh['sampled_us'] and
                before_restored['frame'] == after_restored['frame'] and after_restored['actuate_result'] is True and
                after_restored['selected_ids'] == [11] and
                last['frame'] == complete['frame'] >= 260 and last['sampled_us'] <= complete['sampled_us'],
                'original restored recall lacks admitted current lease/selection or completed observation')
        result.append(dict(passed=True,match=match,world=world,rows=rows,
            absent_recall_classification=classification,
            unavailable_original_recall_selection_empty=after_absent['selected_ids'] == [],
            absent_empty_selection_branch_exercised=classification == 'excluded_on_recall',
            legal_refusal_selection_unchanged=True if classification == 'legal_absent_refusal' else None,
            restored_original_recall_selected_current=True,
            retained_group4_preserved=True,same_confirmed_incarnation=token,
            absent_actuate_result=after_absent['actuate_result'],restored_actuate_result=after_restored['actuate_result'],
            absent_selected_before=absent['selected_ids'],absent_selected_after=after_absent['selected_ids'],
            restored_selected_before=before_restored['selected_ids'],restored_selected_after=after_restored['selected_ids'],
            physicalUI=False,full_mobile_controls_accepted=False))
    return dict(passed=True,episodes=result,requires_controller_full_closed_native_parity=True,
        physicalUI=False,active_casting_exercised=False,full_mobile_controls_accepted=False,
        scope='Original Cancel/Actuate during unavailable native view (legal Count0 refusal OR actual Count1 empty-selection branch) and original Actuate on restored admitted mobile; no invented filter, physical UI, camera-call or active-casting acceptance')


def evaluate_recovery_stall(log, *, attacker_log, matches):
    """Observe the opt-in hold and actual successful recovery queues.

    Actual BEGIN plus raw normal snapshots keep this diagnostic independent of
    a later failed command-phase gate. That gate remains mandatory in the
    controller; an observed stall is never a replacement for it.
    """
    require(type(matches) is list and len(matches) == 2 and len(set(matches)) == 2 and
            all(type(match) is str and re.fullmatch('[a-f0-9]{32}',match) for match in matches),
            'recovery stall requires two exact actual matches')
    require(type(log) is str and type(attacker_log) is str and len(log) <= 32*1024*1024 and
            len(attacker_log) <= 32*1024*1024, 'recovery log exceeds bound')
    ready=re.findall(r'Movement prediction ready: generation=(\d+) match=([a-f0-9]{32}) world=(\d+) slot=(\d+) ',log)
    require([row[1] for row in ready] == matches and [int(row[2]) for row in ready] == [1,2] and
            all(int(row[3]) == 1 for row in ready), 'recovery victim BEGIN/world/match/slot binding differs')
    prefix='MOBILE RECOVERY STALL '
    require(not any(prefix in line for line in attacker_log.splitlines()), 'recovery hold was emitted by the attacker')
    raw=[line.split(prefix,1)[1] for line in log.splitlines() if prefix in line]
    require(len(raw) == 1 and len(raw[0]) <= 2048, 'exactly one bounded world2 recovery hold required')
    row=json.loads(raw[0],object_pairs_hook=_unique_object)
    fields={'schema','event','world','match','slot','frame','requested_ms','begin_us','end_us',
            'presented_before','presented_after','completed_before','completed_after','qpc_scope','physicalUI'}
    require(type(row) is dict and set(row) == fields and type(row['schema']) is int and row['schema'] == 1 and
            row['event'] == 'main_thread_stall' and row['physicalUI'] is False and
            all(type(row[key]) is int for key in ('world','slot','frame','requested_ms')) and
            (row['world'],row['match'],row['slot'],row['frame'],row['requested_ms']) == (2,matches[1],1,152,250) and
            row['qpc_scope'] == 'Sleep(250) only', 'recovery hold schema/scope/world differs')
    require(_integer(row['begin_us']) and _integer(row['end_us']) and
            row['end_us']-row['begin_us'] >= 250_000, 'recovery QPC hold was shorter than250ms or invalid')
    require(type(row['presented_before']) is int and row['presented_before'] == 152 and
            type(row['presented_after']) is int and 152 <= row['presented_after'] <= 153 and
            all(_integer(row[key],-1,2**31-1) for key in ('completed_before','completed_after')) and
            row['completed_after'] >= row['completed_before'], 'recovery actual counter observations regressed/skipped')
    corrections=_rows(log,'MOBILE CORRECTION ',matches[1],2048)
    bracket=[]
    for frame in (152,153):
        found=[r for r in corrections if r.get('event') == 'snapshot' and r.get('frame') == frame]
        require(len(found) == 1 and all(type(found[0].get(k)) is int for k in ('world','frame','army','entity','unit_type')) and
                (found[0]['world'],found[0]['army'],found[0]['entity'],found[0]['unit_type']) == (2,1,11,1) and
                found[0].get('physicalUI') is False and _integer(found[0].get('sampled_us')),
                'recovery normal snapshot bracket missing/mismatched')
        bracket.append(found[0])
    require(bracket[0]['sampled_us'] < row['begin_us'] < row['end_us'] < bracket[1]['sampled_us'],
            'recovery hold is not after normal152 snapshot and before normal153 snapshot')

    def mode_changes(text, slot):
        # The actual C++ emitter follows ORIGINAL PushSimMessage + queued().
        # Policy starts inactive, and queued() is its only recovery-mode writer.
        # Other worlds/clients may have their own natural recovery episodes.
        changes={1:[],2:[]}; current=None; count=0
        fields={'schema','event','world','match','frame','active','decision_us','queue_return_us',
                'target_assigned','native_dt_us'}
        for line in text.splitlines():
            begin=re.search(r'Movement prediction ready: generation=(\d+) match=([a-f0-9]{32}) world=(\d+) slot=(\d+) ',line)
            if begin:
                current=(begin[2],int(begin[3]),int(begin[4]))
            prefix='MOVEMENT RECOVERY '
            if prefix not in line:
                continue
            count+=1; raw=line.split(prefix,1)[1]
            require(count <= 4096 and 0 < len(raw) <= 2048, 'recovery mode changes exceed bound')
            change=json.loads(raw,object_pairs_hook=_unique_object)
            require(type(change) is dict and set(change) == fields and
                    type(change['schema']) is int and change['schema'] == 1 and change['event'] == 'queued_mode' and
                    _integer(change['world'],1,2) and change['match'] == matches[change['world']-1] and
                    current == (change['match'],change['world'],slot) and
                    _integer(change['frame'],1,2**31-1) and type(change['active']) is bool and
                    _integer(change['decision_us']) and _integer(change['queue_return_us']) and
                    change['queue_return_us'] >= change['decision_us'] and
                    _integer(change['target_assigned'],1,2**63-1) and
                    type(change['native_dt_us']) is int and change['native_dt_us'] == 50000,
                    'recovery queued-mode schema/BEGIN/clock differs')
            previous=changes[change['world']]
            require(change['active'] != (previous[-1]['active'] if previous else False) and
                    (not previous or (change['frame'] > previous[-1]['frame'] and
                     change['decision_us'] >= previous[-1]['queue_return_us'])),
                    'recovery mode chain did not alternate in actual queue order')
            previous.append(change)
        return changes

    victim_modes=mode_changes(log,1)
    attacker_modes=mode_changes(attacker_log,0)
    fresh=_rows(log,'MOBILE ORDER ',matches[1],1)
    require(len(fresh) == 1 and fresh[0].get('event') == 'original_fresh_move',
            'recovery exit requires the actual fresh original Move')
    fresh=fresh[0]
    require(all(type(fresh.get(k)) is int for k in ('world','entity','unit_type','army','frame','queueDelta')) and
            (fresh['world'],fresh['entity'],fresh['unit_type'],fresh['army'],fresh['frame'],fresh['queueDelta']) == (2,11,1,1,180,1) and
            fresh.get('originalCtor') is True and fresh.get('reselected_current') is True and
            fresh.get('physicalUI') is False and
            all(_integer(fresh.get(k)) for k in ('origin_sampled_us','sampled_us','enqueue_sampled_us')) and
            row['end_us'] < fresh['origin_sampled_us'] <= fresh['sampled_us'] <= fresh['enqueue_sampled_us'],
            'recovery fresh original Move identity/clock differs')
    modes=victim_modes[2]
    require(not any(change['decision_us'] < row['end_us'] and change['queue_return_us'] >= row['begin_us'] for change in modes),
            'recovery queue mode overlaps the owned Sleep bracket')
    before=[change for change in modes if change['queue_return_us'] < row['begin_us']]
    require(not before or before[-1]['active'] is False, 'recovery mode was already active before the hold')
    episode=[change for change in modes if row['end_us'] < change['queue_return_us'] < fresh['sampled_us']]
    require(len(episode) == 2 and [change['active'] for change in episode] == [True,False] and
            all(change['decision_us'] >= row['end_us'] and 153 <= change['frame'] <= fresh['frame']+1 for change in episode),
            'recovery requires one actual entered/exited queue chain after Sleep and before fresh Move')
    return dict(passed=True,world=2,match=matches[1],slot=1,event=row,
        actual_elapsed_us=row['end_us']-row['begin_us'],actual_elapsed_ms=(row['end_us']-row['begin_us'])/1000,
        snapshot_before=bracket[0],snapshot_after=bracket[1],physicalUI=False,
        recovery_entry=episode[0],recovery_exit=episode[1],fresh_original_order=fresh,
        victim_mode_changes=victim_modes,attacker_mode_changes=attacker_modes,
        recovered_before_fresh_original_input=True,native_dt_us=50000,
        body_phase_qualified_by_this_gate=False,full_feature_accepted=False,
        scope='Owned Sleep between actual normal152/153 snapshots, then successful original native queues enter/exit recovery before fresh original input; movement phase/body/hash/group/lifecycle remain independent mandatory gates')
