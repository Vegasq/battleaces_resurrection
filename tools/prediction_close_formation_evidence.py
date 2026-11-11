"""Pure evidence for an explicit ordinary-stat four-unit prediction fixture.

Native/query, original input and process ownership remain with the producer.
Geometric proximity is reported separately from collision-solver correctness.
"""
from __future__ import annotations

import itertools
import hashlib
import json
import math
import re
import struct

from tools import prediction_multi_unit_evidence as shared
from tools import prediction_mobile_evidence as mobile
from tools.prediction_close_formation_fixture import metadata


PREFIX = 'CLOSE FORMATION '
IDS = [11, 12, 13, 14]
SPEC = dict(type=1, army=1, first_frame=130, last_frame=360, max_entities=8)
RADIUS = 3435973888 / 2**32
EDGE = 3 * RADIUS
COMMON = shared.COMMON | {'order_tag', 'physicalUI'}
SNAPSHOT = {'members', 'selector', 'manager', 'simulation', 'group_generation',
    'current_ids', 'preview_ids', 'casting_ids', 'active_caster', 'primary', 'context', 'drag',
    'last_click_id', 'click_mode', 'pending_commands', 'selection_calls', 'group_assign_calls',
    'selection_scope_player_initiated', 'history_writes', 'current_count', 'current_all_ids',
    'current_typed_ids', 'current_frame_owner', 'group', 'helper', 'group_ids', 'group_count',
    'group_all_ids', 'group_typed_ids', 'group_frame_owner', 'tracked_released_ids', 'auto_type1'}
MEMBER = shared.MEMBER | {'original_token', 'original_actor', 'native_present'}
EVENTS = {'setup', 'selected', 'sample', 'move_queued', 'serialized', 'batch_registered', 'authority', 'complete'}
EXCLUSIONS = tuple(sorted(set(shared.EXCLUSIONS) | {
    'multi_unit_move', 'mobile_correction', 'cohort_canonical_death'}))
SCOPE = ('Original scripted four-unit selection/manual group and shared Moves using ordinary definitions; '
    'each original render/native response, close-cohort continuity, real remote replay+20, full wire/state parity '
    'and natural lifecycle; no physical-input or collision-solver acceptance')


def require(ok, why):
    if not ok:
        raise AssertionError('close-formation evidence: ' + why)


def _exact(value, expected):
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(_exact(value[k], v) for k, v in expected.items())
    if type(expected) is list:
        return len(value) == len(expected) and all(_exact(a, b) for a, b in zip(value, expected))
    return value == expected


def scope(plan):
    return SCOPE if plan.get('close_formation') else None


def validate_plan(plan):
    require(type(plan.get('close_formation', False)) is bool, 'option must be Boolean')
    require(plan.get('scenario') != 'close-formation' or plan.get('close_formation') is True,
            'scenario requires its explicit option')
    if not plan.get('close_formation'):
        return
    require(plan.get('scenario') == 'close-formation' and plan.get('lifecycle') == 'natural' and
        type(plan.get('frames')) is int and plan['frames'] == 650 and
        type(plan.get('expected_matches')) is int and plan['expected_matches'] == 2 and
        type(plan.get('move_slot')) is int and plan['move_slot'] == 0 and
        type(plan.get('rtt_ms')) is list and len(plan['rtt_ms']) == 2 and
        all(type(value) in (int, float) and math.isfinite(value) and value == expected
            for value, expected in zip(plan['rtt_ms'], (130, 475))) and plan.get('native_position_trace') is None and
        plan.get('actor_fixture') is None and plan.get('generic_movement_not_exercised') is True and
        type(plan.get('surrender_frame')) is int and plan['surrender_frame'] == 700 and
        plan.get('native_cohort_spec') == '1:1:130:360:8' and
        _exact(plan.get('close_formation_fixture'), metadata()) and
        plan.get('close_formation_scope') == SCOPE and
        all(type(plan.get(k, False)) is bool and not plan.get(k, False) for k in EXCLUSIONS),
        'requires exclusive ordinary natural650/two worlds/130475/slot0/Concede700 and exact fixture/spec')


def option(args, frames, position_trace):
    selected = args.scenario == 'close-formation'
    surrender = getattr(args, 'surrender_frame', None)
    plan = dict(close_formation=selected, scenario=args.scenario, lifecycle=args.lifecycle, frames=frames,
        expected_matches=2 if args.lifecycle == 'natural' else 1, move_slot=args.move_slot,
        rtt_ms=list(args.rtt_ms), native_position_trace=position_trace,
        actor_fixture=None, generic_movement_not_exercised=True,
        surrender_frame=700 if surrender is None else surrender,
        native_cohort_spec='1:1:130:360:8', close_formation_fixture=metadata(),
        close_formation_scope=SCOPE, **{key: getattr(args, key, False) for key in EXCLUSIONS})
    validate_plan(plan)
    return selected


def native_observation(state, parsed_sha):
    """Copy actual room.last_state only; never query or fabricate a participant."""
    require(type(state) is dict and shared.integer(state.get('frame'), 0, 2**31-1),
            'native observation frame missing')
    frame = state['frame']
    if not 130 <= frame <= 380:
        return None
    require(state.get('viewer') == 31 and type(state.get('entities')) is list and
            type(state.get('game_state')) is dict and shared._hex(parsed_sha) and
            parsed_sha == hashlib.sha256(json.dumps(
                {k: v for k, v in state.items() if k != 'raw_sha256'},
                sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'native observation is not the actual full Spectator31 state/hash')
    participants = []
    for identity in [10] + IDS:
        found = [e for e in state['entities'] if type(e) is dict and e.get('id') == identity]
        require(len(found) == 1, 'native participant missing/duplicate')
        e = found[0]
        require(all(k in e for k in ('id', 'type', 'army', 'max_health', 'current_damage', 'position')),
                'native participant component missing')
        require(type(e['id']) is int and type(e['type']) is int and e['type'] == 1 and
                type(e['army']) is int and e['army'] == (0 if identity == 10 else 1) and
                shared.point(e['position']), 'native participant identity/position differs')
        position = list(struct.unpack('<fff', struct.pack('<fff', *e['position'])))
        require(position == e['position'], 'native participant position is not decoded float32')
        participants.append({k: e[k] for k in ('id', 'type', 'army', 'max_health', 'current_damage')} |
                            dict(position=position))
    return dict(frame=frame, parsed_state_sha256=parsed_sha,
                participants=participants, game_state=dict(state['game_state']))


def records(log, *, slot, matches):
    require(type(log) is str and len(log.encode('utf8')) <= 64*1024*1024, 'log bound')
    result = []
    last_us = last_tick = -1
    for number, line in enumerate(log.splitlines(), 1):
        if PREFIX not in line:
            continue
        raw = line.split(PREFIX, 1)[1]
        require(0 < len(raw) <= 16384, 'row bound')
        row = shared._decode(raw)
        require(type(row) is dict and COMMON <= set(row) and type(row['schema']) is int and row['schema'] == 1 and
            row['event'] in EVENTS and row['match'] in matches and type(row['slot']) is int and row['slot'] == slot and
            shared.integer(row['world'], 1) and shared.integer(row['frame'], -1, 2**31-1) and
            shared.integer(row['completed_frame'], row['frame'], 2**31-1) and
            shared.integer(row['sampled_us']) and shared.integer(row['tick_ms']) and
            row['sampled_us'] >= last_us and row['tick_ms'] >= last_tick and row['physicalUI'] is False,
            'common event/world/owner/clock differs')
        command = row['event'] in ('move_queued', 'serialized', 'batch_registered')
        require(row['order_tag'] in (('approach', 'fresh') if slot == 1 else ('remote',)) if command else
                row['order_tag'] is None, 'order tag/event/seat differs')
        last_us, last_tick = row['sampled_us'], row['tick_ms']
        result.append(dict(row=row, line=number))
        require(len(result) <= 20000, 'observation row budget')
    return result


def snapshot(row, slot):
    expected = IDS if slot == 1 else [10]
    require(set(row) == COMMON | SNAPSHOT and type(row['members']) is list and
            [m.get('id') for m in row['members']] == expected, 'snapshot exact fields/roster differs')
    require(all(shared.ptr(row[k]) for k in ('selector', 'manager', 'simulation', 'current_frame_owner')) and
        shared.integer(row['group_generation']) and all(shared.ids(row[k]) for k in
        ('current_ids', 'preview_ids', 'casting_ids', 'current_all_ids', 'current_typed_ids')) and
        row['current_ids'] == row['current_all_ids'] and shared.integer(row['current_count'], 0, 8) and
        row['active_caster'] is None and row['primary'] is row['context'] is row['drag'] is False and
        not row['casting_ids'] and shared.integer(row['pending_commands'], 0, 1) and
        shared.integer(row['last_click_id'], 0, 2**32-1) and type(row['click_mode']) is int and row['click_mode'] == 0 and
        row['history_writes'] == 0 and type(row['history_writes']) is int, 'snapshot roots/input/raw current cache differs')
    for member in row['members']:
        require(set(member) == MEMBER and member['unit_type'] == 1 and type(member['unit_type']) is int and
            member['army'] == slot and type(member['army']) is int and
            shared.integer(member['original_token'], 1) and member['incarnation'] == member['canonical_token'] == member['original_token'] and
            type(member['incarnation']) is type(member['canonical_token']) is int and
            shared.ptr(member['original_actor']) and member['actor'] == member['original_actor'] and
            member['native_present'] is member['admitted'] is member['initialized'] is member['jobs_joined'] is True and
            shared.integer(member['native_state'], 0, 2**32-2) and member['native_state'] != 6,
            'member lost original current initialized confirmed lease')
        shared.bits_point(member['position'], member['position_bits'])
        require(shared.integer(member['position_sampled_us']) and member['position_sampled_us'] <= row['sampled_us'],
                'joined Transform query clock differs')
    require(len({m['actor'] for m in row['members']}) == len(expected), 'members share an actor')
    group_fields = ('group', 'helper', 'group_ids', 'group_count', 'group_all_ids', 'group_typed_ids',
                    'group_frame_owner', 'tracked_released_ids', 'auto_type1')
    if slot == 0:
        require(row['selection_calls'] == row['group_assign_calls'] == 0 and
                type(row['selection_calls']) is type(row['group_assign_calls']) is int and
                row['selection_scope_player_initiated'] is None and all(row[k] is None for k in group_fields),
                'host invented selection/group changes')
    else:
        require(row['selection_calls'] == row['group_assign_calls'] == 1 and
            type(row['selection_calls']) is type(row['group_assign_calls']) is int and
            row['selection_scope_player_initiated'] is False and
            all(shared.ptr(row[k]) for k in ('group', 'helper', 'group_frame_owner')) and
            row['current_frame_owner'] == row['group_frame_owner'] and row['auto_type1'] is False and
            row['tracked_released_ids'] == [] and row['current_count'] == row['group_count'] == 4 and
            type(row['group_count']) is int and all(shared.ids(row[k]) and set(row[k]) == set(IDS) for k in
            ('current_ids', 'current_all_ids', 'current_typed_ids', 'group_ids', 'group_all_ids', 'group_typed_ids')),
            'four-member raw/type/Count/manual group ownership differs')
    return row


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def fresh_target(origins):
    require(type(origins) is list and len(origins) == 4 and all(shared.point(p) for p in origins), 'fresh centroid inputs differ')
    center = []
    for axis in range(3):
        total = _f32(0)
        for position in origins:
            # Nine-digit JSON round-trips a Single, but Python parses its
            # decimal text as double. Reconstruct BOTH C++ float operands.
            total = _f32(total + _f32(position[axis]))
        center.append(_f32(total * .25))
    center[2] = _f32(center[2] + 16.)
    return center


def geometry(positions):
    require(set(positions) == set(IDS), 'geometry lacks actual labeled members')
    pairs = {f'{a}-{b}': math.hypot(positions[a][0]-positions[b][0], positions[a][2]-positions[b][2])
             for a, b in itertools.combinations(IDS, 2)}
    seen = {IDS[0]}
    while True:
        following = seen | {b for a in seen for b in IDS
            if math.hypot(positions[a][0]-positions[b][0], positions[a][2]-positions[b][2]) <= EDGE}
        if following == seen:
            break
        seen = following
    return dict(connected=len(seen) == 4, min_pair=min(pairs.values()), diameter=max(pairs.values()), pairs=pairs)


def _one(rows, event, tag=None):
    found = [item for item in rows if item['row']['event'] == event and item['row']['order_tag'] == tag]
    require(len(found) == 1, 'missing/duplicate ' + event + '/' + str(tag))
    return found[0]


def _command(log, rows, tag, slot, context):
    queued, serial, registered = (_one(rows, name, tag) for name in ('move_queued', 'serialized', 'batch_registered'))
    q, s, r = queued['row'], serial['row'], registered['row']
    require(set(q) == COMMON | shared.ORDER and set(s) == COMMON | shared.SERIAL and
            set(r) == COMMON | shared.REGISTERED, 'command exact fields differ')
    expected = IDS if slot == 1 else [10]
    at = {'approach': 180, 'fresh': 300, 'remote': 320}[tag]
    require(q['frame'] == at and q['source_ids'] == expected and
        len(q['incarnations']) == len(q['origins']) == len(q['origins_sampled_us']) == len(expected) and
        all(shared.integer(value, 1) for value in q['incarnations']) and all(shared.point(p) for p in q['origins']) and
        all(shared.integer(t) and t <= q['sampled_us'] for t in q['origins_sampled_us']) and
        q['ability'] == 12 and type(q['ability']) is int and q['queue_before'] == 0 and q['queue_after'] == 1 and
        type(q['queue_before']) is type(q['queue_after']) is int and q['queued'] is False and q['originalCtor'] is True and
        q['command_class'] == 'Uncapped.ExecuteTargetGroundCommand' and shared.ptr(q['command']) and
        q['original_callback'] == 'Uncapped.ExecuteTargetGroundCommand..ctor' and
        shared.integer(q['enqueue_sampled_us']) and q['enqueue_sampled_us'] >= q['sampled_us'],
        'original command frame/source/constructor/queue differs')
    mobile._perspective(q)
    require(queued['line'] < serial['line'] < registered['line'] and
        q['enqueue_sampled_us'] <= s['sampled_us'] <= r['sampled_us'] and
        q['command'] == s['command'] == r['command'] and shared.ptr(s['action']) and s['action'] == r['action'] and
        shared.integer(s['sequence'], 1) and s['sequence'] == r['sequence'] and
        s['action_index'] == r['action_index'] == 0 and type(s['action_index']) is type(r['action_index']) is int and
        shared.integer(s['source_next_frame'], 0, 2**31-1), 'normal constructor/ToProto/67 order or identity differs')
    order = dict(q, sequence=r['sequence'])
    binding = shared.bind_move(log, order, slot=slot, match=context['match'], raw_bodies=context['raw_bodies'],
                              commits=context['commits'], journal=context['journal'])
    require(r['speculative_frame'] == binding['assigned_frame'] and r['action_sha256'] == binding['action_sha256'] and
            r['body_sha256'] == binding['body_sha256'] and abs(binding['canonical_frame']-(at+1)) <= 1,
            'actual67 bytes or planned steady command frame differs')
    sends = re.findall(r'Original command batch submitted: match=' + re.escape(context['match']) +
        r' sequence=' + str(s['sequence']) + r' actions=1 bytes=\d+ body_sha256=[a-f0-9]{64} sendTick=\d+ sourceNextFrame=(\d+)', log)
    require(len(sends) == 1 and int(sends[0]) == s['source_next_frame'], 'normal72 source cursor differs from ToProto receipt')
    if tag == 'approach':
        require(q['target'] == [70., 0., 50.] and binding['protocol_target'] == [-70., 0., -50.], 'approach map target differs')
    elif tag == 'remote':
        require(q['target'] == binding['protocol_target'] == [60., 0., 44.], 'remote target differs')
    else:
        expected_target = fresh_target(q['origins'])
        require(q['map_perspective'] == 1 and all(struct.pack('<f', a) == struct.pack('<f', b)
            for a, b in zip(q['target'], expected_target)), 'fresh target is not the ordered Single centroid+16 UnityZ')
    return order, binding


def _queue_intervals(rows):
    pending = None
    for item in rows:
        row = item['row']
        if row['event'] in ('setup', 'selected', 'sample', 'complete'):
            require(row['pending_commands'] == (0 if pending is None else 1),
                    'pending ICommand count lacks the exact queued-before-serializer interval')
        elif row['event'] == 'move_queued':
            require(pending is None, 'two scripted ICommands overlap before normal drain')
            pending = row['order_tag']
        elif row['event'] == 'serialized':
            require(pending == row['order_tag'], 'serializer lacks its still-pending command')
            pending = None
    require(pending is None, 'final pending command never serialized')


def _receipt(rows, context, frame, slot, native_receipts):
    # This scenario has its own actual successful-65 observer. A generic sparse
    # MOVEMENT AUTHORITY line or a timestamp-free TSV cannot substitute for it.
    found = [item for item in rows if item['row']['event'] == 'authority' and item['row']['canonical_frame'] == frame]
    require(len(found) == 1, 'actual CLOSE FORMATION accepted65 receipt missing/duplicate')
    observed = found[0]['row']
    bridge = [r for r in context['bridge_frames'] if (r.get('match'), r.get('frame')) == (context['match'], frame)]
    native = [r for r in native_receipts[slot, context['match']] if r['frame'] == frame]
    require(len(bridge) == len(native) == 1 and observed['wire_sha256'] == bridge[0]['payload_sha256'] ==
        native[0]['sha256'] == context['canonical_payloads'].get(frame), 'accepted65/native TSV/rawbridge/server wire differs')
    receipt = dict(schema=1, world=observed['world'], match=observed['match'], frame=frame,
        tick_ms=observed['tick_ms'], canonical_sha256=observed['canonical_sha256'], wire_sha256=observed['wire_sha256'])
    return receipt, bridge[0], found[0]


def _native_authority(rows, states, orders):
    require(type(rows) is list and [r.get('frame') for r in rows] == list(range(130, 381)), 'full actual native authority window missing')
    square = dict(zip(IDS, metadata()['initial_guests']))
    for row in rows:
        frame = row['frame']
        require(set(row) == {'frame', 'parsed_state_sha256', 'participants', 'game_state'} and
            row['parsed_state_sha256'] == states.get(frame) and type(row['game_state']) is dict and
            row['game_state'].get('complete') is False and type(row['participants']) is list and
            [p.get('id') for p in row['participants']] == [10] + IDS, 'native full hash/game state/roster differs')
        for participant in row['participants']:
            identity = participant['id']
            require(set(participant) == {'id', 'type', 'army', 'max_health', 'current_damage', 'position'} and
                type(identity) is int and type(participant['type']) is int and participant['type'] == 1 and
                type(participant['army']) is int and participant['army'] == (0 if identity == 10 else 1) and
                type(participant['max_health']) in (int, float) and participant['max_health'] == 600 and
                type(participant['current_damage']) in (int, float) and participant['current_damage'] == 0 and
                shared.point(participant['position']), 'ordinary native health/identity/position differs')
            if frame < orders['approach'][1]['canonical_frame']:
                require(participant['position'] == ([60., 0., 60.] if identity == 10 else square[identity]),
                        'original initial participant drifted before approach')
    by_frame = {r['frame']: r for r in rows}
    for tag, ids in (('approach', IDS), ('fresh', IDS), ('remote', [10])):
        binding = orders[tag][1]; frame = binding['canonical_frame']; target = binding['protocol_target']
        initial = {p['id']: p['position'] for p in by_frame[frame-1]['participants']}
        for identity in ids:
            require(any(shared._progress(next(p['position'] for p in by_frame[f]['participants'] if p['id'] == identity),
                        initial[identity], target) > .025 for f in range(frame, frame+5)),
                    'one actual canonical native participant did not respond targetward')
    return by_frame


def _geometry_report(positions):
    shapes = [(frame, geometry(points)) for frame, points in positions]
    require(shapes, 'geometry observations missing')
    initial = shapes[0][1]['pairs']; convergence = 0.; near = {key: 0 for key in initial}; longest = 0
    previous = None
    for frame, shape in shapes:
        for key, distance in shape['pairs'].items():
            convergence = max(convergence, initial[key]-distance)
            near[key] = (near[key]+1 if previous is not None and frame == previous+1 else 1) if distance <= 2*RADIUS+1e-4 else 0
            longest = max(longest, near[key])
        previous = frame
    return dict(minimum_pair_distance=min(s['min_pair'] for _, s in shapes), maximum_diameter=max(s['diameter'] for _, s in shapes),
        maximum_labeled_pair_convergence=convergence, geometric_convergence=convergence >= .25,
        geometric_near_contact=longest >= 3, near_contact_consecutive_max=longest,
        radius=RADIUS, edge_bound=EDGE, contact_is_report_only=True, collision_solver_qualified=False)


def _same_head(native, world, canonical):
    before = [r for r in native if r['world'] == world and r['event'] == 'before_restore_cached_head' and
              r['first_divergent_frame'] == canonical and r['status'] == 'present']
    require(len(before) == 1, 'remote correction has no unique cached physical head')
    before = before[0]
    after = [r for r in native if r['world'] == world and r['event'] == 'after_replay_same_head' and
             r['revision'] == before['revision']]
    require(len(after) == 1, 'remote correction lacks actual replayed same head')
    after = after[0]
    require(after['frame'] == after['head'] == before['frame'] and after['checkpoint_base'] == before['checkpoint_base'] and
        after['stage'] == 'replay' and before['query_end_us'] <= after['query_begin_us'] and
        before['query_end_tick_ms'] <= after['query_begin_tick_ms'], 'remote same-head provenance differs')
    replay = [r for r in native if r['world'] == world and r['event'] != 'before_restore_cached_head' and
              r['stage'] == 'replay' and r['revision'] == before['revision']]
    require([r['frame'] for r in replay] == list(range(canonical, after['frame']+1)), 'remote native replay query prefix has a gap')
    deltas = []
    for old, new in zip(before['entities'], after['entities']):
        require(old['id'] == new['id'], 'same-head native census changed')
        delta = shared._delta(new['position'], old['position'])
        deltas.append(dict(entity=old['id'], delta=delta, magnitude=shared._norm(delta)))
    return dict(before_record=before['record'], after_record=after['record'], physical_head=after['frame'],
        first_divergent_frame=canonical, entities=deltas, nonzero_local_delta_required=False)


def _native_quiet(ordinary, order, binding):
    before = [row for row in ordinary if row['frame'] < binding['assigned_frame'] and
              row['query_end_us'] <= order['enqueue_sampled_us']]
    require(before, 'native quiet baseline is missing')
    last = before[-1]
    start = next((index for index in range(len(before)-1, -1, -1)
                  if last['query_end_us']-before[index]['query_end_us'] >= 200000), None)
    quiet = before[start:] if start is not None else []
    require(len(quiet) >= 3, 'native quiet baseline is shorter than200ms')
    origins = {entity['id']: entity['position'] for entity in last['entities']}
    require(all(shared._norm(shared._delta(entity['position'], origins[entity['id']])) <= .025
                for row in quiet for entity in row['entities']), 'one native member was already moving before fresh command')
    return dict(first_record=quiet[0]['record'], last_record=last['record'], samples=len(quiet),
                span_us=last['query_end_us']-quiet[0]['query_end_us'])


def _closed_states(contexts, workers, logs):
    require(set(workers) == {0, 1}, 'both closed native clients required')
    matches = [c['match'] for c in contexts]; bindings = {}; count = 0
    for slot in (0, 1):
        ready = re.findall(r'Movement prediction ready: generation=(\d+) match=([a-f0-9]{32}) world=(\d+) slot=(\d+) ', logs[slot])
        require([r[1] for r in ready] == matches and all(int(r[3]) == slot and int(r[0]) > 0 for r in ready) and
            len({r[2] for r in ready}) == 2 and all(0 < int(r[2]) < 2**64 for r in ready), 'actual native BEGIN/world/seat differs')
        bindings[slot] = {match: int(row[2]) for match, row in zip(matches, ready)}
        rows = workers[slot]
        require(type(rows) is list and list(dict.fromkeys(r['world'] for r in rows)) == [int(r[2]) for r in ready],
                'closed native stream world order differs from BEGIN')
        for context in contexts:
            expected = context['canonical_states']; world = bindings[slot][context['match']]
            require(len(expected) >= 650 and sorted(expected) == list(range(len(expected))), 'full canonical native timeline missing')
            selected = [r for r in rows if r['world'] == world]
            require([r['frame'] for r in selected] == list(range(len(expected))) and
                all(r['parsed_state_sha256'] == expected[r['frame']] for r in selected), 'a closed full native hash differs')
            count += len(selected)
    return bindings, count


def evaluate(*, contexts, cohort_trace, worker_states, native_receipts, peer_bridge_frames, authority_rows, join_check):
    require(type(contexts) is list and len(contexts) == 2, 'two actual match contexts required')
    matches = [c['match'] for c in contexts]
    require(len(set(matches)) == 2 and all(type(m) is str and re.fullmatch('[a-f0-9]{32}', m) for m in matches), 'two unique match identities required')
    logs = {1: contexts[0]['log'], 0: contexts[0]['attacker_log']}
    require(all(c['log'] == logs[1] and c['attacker_log'] == logs[0] for c in contexts), 'contexts do not share the closed original logs')
    parsed = {slot: records(logs[slot], slot=slot, matches=matches) for slot in (0, 1)}
    worlds, native_count = _closed_states(contexts, worker_states, logs)
    native = shared.validate_native_trace(cohort_trace, spec=SPEC)
    require(list(dict.fromkeys(r['world'] for r in native)) == [worlds[1][m] for m in matches], 'cohort native worlds differ from actual BEGIN')
    episodes = []; wire_count = 0
    for context in contexts:
        match = context['match']; world = worlds[1][match]
        seat_rows = {slot: [x for x in parsed[slot] if x['row']['match'] == match] for slot in (0, 1)}
        samples = {}; starts = {}; orders = {}
        for slot in (0, 1):
            selected = seat_rows[slot]
            require(selected and {x['row']['world'] for x in selected} == {worlds[slot][match]}, 'C++ stream belongs to another actual BEGIN world')
            for item in selected:
                row = item['row']
                if row['event'] in ('setup', 'selected', 'sample', 'complete'):
                    snapshot(row, slot)
                elif row['event'] == 'authority':
                    require(set(row) == COMMON | shared.AUTHORITY and shared.integer(row['canonical_frame'], 130, 380) and
                            shared._hex(row['wire_sha256']) and shared._hex(row['canonical_sha256']), 'actual accepted65 fields differ')
            start = _one(selected, 'selected' if slot else 'setup'); end = _one(selected, 'complete')
            require(start['row']['frame'] == 130 and end['row']['frame'] == 360 and start['line'] < end['line'], 'setup/completion frame/order differs')
            snapshots = [x['row'] for x in selected if x['row']['event'] in ('setup', 'selected', 'sample', 'complete')]
            require(set(r['frame'] for r in snapshots) == set(range(130, 361)), 'current actor/cache observations miss a frame')
            starts[slot] = start['row']; samples[slot] = snapshots
            roots = ('selector', 'manager', 'simulation', 'group_generation', 'current_frame_owner', 'preview_ids', 'last_click_id', 'click_mode')
            if slot: roots += ('group', 'helper', 'group_frame_owner')
            identities = [(m['id'], m['original_actor'], m['original_token']) for m in start['row']['members']]
            require(all(all(row[k] == start['row'][k] for k in roots) and
                [(m['id'], m['original_actor'], m['original_token']) for m in row['members']] == identities for row in snapshots),
                'same actor/token/owner/cache was rebound or repaired')
            receipts = [x['row'] for x in selected if x['row']['event'] == 'authority']
            require([r['canonical_frame'] for r in receipts] == list(range(130, 381)), 'dense actual successful65 observation missing/duplicate')
            for tag in (('approach', 'fresh') if slot else ('remote',)):
                order, binding = _command(logs[slot], selected, tag, slot, context)
                require(order['incarnations'] == [m['original_token'] for m in start['row']['members']], 'command source token differs from original selection')
                queued = _one(selected, 'move_queued', tag)
                prior = [x['row'] for x in selected if x['line'] < queued['line'] and
                         x['row']['event'] in ('sample', 'selected', 'setup') and x['row']['frame'] == order['frame']]
                require(prior and all(m['native_state'] == 0 and m['position'] == origin and
                    m['position_sampled_us'] <= stamp for m, origin, stamp in
                    zip(prior[-1]['members'], order['origins'], order['origins_sampled_us'])),
                    'original command lacks its actual ready same-frame source poses')
                orders[tag] = (order, binding)
            _queue_intervals(selected)
        require(orders['approach'][0]['sequence'] < orders['fresh'][0]['sequence'] and
            orders['approach'][0]['command'] != orders['fresh'][0]['command'], 'fresh command reused the old pending command/ordinal')
        authority = _native_authority(context['native_states'], context['canonical_states'], orders)
        own = [r for r in native if r['world'] == world]
        require(all(r['status'] == 'present' and r['count'] == 4 and [e['id'] for e in r['entities']] == IDS
            for r in own if r['event'] != 'before_restore_cached_head'), 'native actual query census lacks one current member')
        require(all([e['id'] for e in r['entities']] == IDS for r in own if r['status'] == 'present'), 'native cache census lacks one member')
        ordinary = [r for r in own if r['event'] == 'native_cohort_positions' and r['stage'] == 'ordinary']
        require([r['frame'] for r in ordinary] == list(range(130, 361)), 'native ordinary pose window missing/duplicate')
        by_frame = {r['frame']: r for r in ordinary}
        fresh, binding = orders['fresh']; remote, remote_binding = orders['remote']
        quiet_native = _native_quiet(ordinary, fresh, binding)
        own65, bridge, _ = _receipt(seat_rows[1], context, binding['canonical_frame'], 1, native_receipts)
        late65, late_bridge, late_item = _receipt(seat_rows[1], context, remote_binding['canonical_frame'], 1, native_receipts)
        require(remote_binding['canonical_frame'] > binding['canonical_frame'] and
            min(late65['tick_ms'], late_bridge['received_tick_ms']) > remote['tick_ms'], 'independent late remote delivery missing/early')
        replay = mobile._joined(join_check, worker_states[1], world=world, receipt=late65,
            states=context['canonical_states'], journal=context['journal'], action_hash=remote_binding['action_sha256'],
            slot=0, replay=True, latest_tick=_one(seat_rows[1], 'complete')['row']['tick_ms'])
        tail = [worker_states[1][i] for i in replay['continuation_row_indices']]
        require(tail[-1]['frame'] <= 360 and tail[-1]['tick_ms'] <= _one(seat_rows[1], 'complete')['row']['tick_ms'],
                'replay+20 extends beyond observed continuous actor/group caches')
        confirmation = mobile._joined(join_check, worker_states[1], world=world, receipt=own65,
            states=context['canonical_states'], journal=context['journal'], action_hash=binding['action_sha256'], slot=1, replay=False)
        # Also validate the host's full native stream through the supplied shared
        # validator, without claiming a separate preauthority host response.
        host_context = dict(context, bridge_frames=peer_bridge_frames)
        host65, _, _ = _receipt(seat_rows[0], host_context, remote_binding['canonical_frame'], 0, native_receipts)
        mobile._joined(join_check, worker_states[0], world=worlds[0][match], receipt=host65,
            states=context['canonical_states'], journal=context['journal'], action_hash=remote_binding['action_sha256'], slot=0, replay=False)
        same_head = _same_head(native, world, remote_binding['canonical_frame'])
        replay_queries = [r for r in own if r['event'] != 'before_restore_cached_head' and r['stage'] == 'replay' and
                          r['revision'] == native[same_head['after_record']]['revision']]
        require(replay_queries[0]['query_begin_tick_ms'] >= late65['tick_ms'] and
                replay_queries[-1]['query_end_tick_ms'] <= replay['group'][-1]['tick_ms'],
                'actual native replay query clocks do not join late65 and the confirmed group')
        end_frame = max(335, same_head['physical_head']+1)
        require(end_frame <= 360, 'late correction exceeded the observed moving window')
        render_frames = {}
        for row in samples[1]: render_frames[row['frame']] = row
        for frame in range(280, end_frame+1):
            nr = by_frame[frame]; rr = render_frames[frame]
            require(geometry({e['id']: e['position'] for e in nr['entities']})['connected'] and
                geometry({m['id']: m['position'] for m in rr['members']})['connected'], 'close cohort graph disconnects around baseline/correction')
        for frame in range(remote_binding['canonical_frame'], end_frame+1):
            previous = {e['id']: e['position'] for e in by_frame[frame-1]['entities']}
            for e in by_frame[frame]['entities']:
                require(shared._norm(shared._delta(e['position'], previous[e['id']])) > .025 and
                    shared._progress(e['position'], previous[e['id']], binding['protocol_target']) > .025,
                    'one native member stopped/not targetward through actual remote correction')
        after_samples = [x for x in seat_rows[1] if x['row']['event'] in ('sample', 'complete') and x['line'] > late_item['line']]
        before_samples = [x['row'] for x in seat_rows[1] if x['row']['event'] in ('sample', 'selected') and
            x['line'] < late_item['line'] and x['row']['sampled_us'] <= late_item['row']['sampled_us']]
        require(before_samples and after_samples, 'render observations do not bracket actual late65')
        before = before_samples[-1]
        for index, identity in enumerate(IDS):
            require(any(shared._progress(x['row']['members'][index]['position'], before['members'][index]['position'], fresh['target']) > .025
                for x in after_samples if x['row']['frame'] <= end_frame), 'one rendered member stopped across the real correction')
        members = []
        for index, identity in enumerate(IDS):
            poses = [dict(position=r['members'][index]['position'], sampled_us=r['members'][index]['position_sampled_us'], tick_ms=r['tick_ms'])
                     for r in samples[1] if r['frame'] >= 280]
            rendered = shared.rendered_response(poses, fresh, member=dict(position=fresh['origins'][index]), receipt=own65, bridge=bridge)
            response = shared.native_response(own, fresh, binding, entity=identity, receipt=own65, bridge=bridge)
            members.append(dict(entity=identity, unit_type=1, army=1, incarnation=fresh['incarnations'][index], render=rendered, native=response))
        expected = [(1, orders['approach'][1]['action_sha256']), (1, binding['action_sha256']), (0, remote_binding['action_sha256'])]
        actual = [(slot, shared.digest(a)) for row in context['journal'] if 130 <= row['frame'] <= 380
                  for slot, actions in row['players'].items() for a in actions]
        require(actual == expected, 'exclusive fixture has extra/missing/reordered commands')
        require(all(len([r for r in raw if r['match'] == match]) == len(context['canonical_states'])
                    for raw in (context['bridge_frames'], peer_bridge_frames)), 'closed rawbridge has duplicate/extra frames')
        wire_count += shared.all_wire(context=context, peer_bridge_frames=peer_bridge_frames, native_receipts=native_receipts)
        native_geometry = _geometry_report([(r['frame'], {e['id']: e['position'] for e in r['entities']}) for r in ordinary])
        canonical_geometry = _geometry_report([(f, {p['id']: p['position'] for p in authority[f]['participants'] if p['id'] in IDS}) for f in range(130, 381)])
        episodes.append(dict(passed=True, match=match, world=world, worlds_by_slot=[worlds[s][match] for s in (0, 1)], selected_ids=IDS[:],
            orders={tag: value[1] for tag, value in orders.items()}, members=members, rendered_members_verified=4, native_members_verified=4,
            late_remote_replay_verified=True, late_native_replay=replay, fresh_native_confirmation=confirmation,
            remote_same_head=same_head, continuity_verified=True, close_graph_verified=True, close_graph_window=[280, end_frame],
            native_quiet_baseline=quiet_native,
            moving_native_window=[remote_binding['canonical_frame'], end_frame], selection_calls=1, group_assign_calls=1, reselection_calls=0,
            cache_observed_frames=231, closed_native_frames=len(context['canonical_states']),
            closed_native_rows_by_slot=[len(context['canonical_states'])]*2,
            geometry=dict(speculative_native=native_geometry, canonical_native=canonical_geometry, collision_solver_qualified=False), physicalUI=False))
    return dict(passed=True, episodes=episodes, all_retained_wire_triples_checked=wire_count,
        all_closed_native_hashes_checked=native_count, physicalUI=False, collision_solver_qualified=False, full_feature_accepted=False, scope=SCOPE)


def _proof_contract(proof, matches):
    if type(proof) is not dict or type(matches) is not list:
        return False
    episodes = proof.get('episodes', [])
    if type(episodes) is not list or len(episodes) != 2 or not all(type(e) is dict for e in episodes):
        return False
    return bool(proof.get('passed') is True and proof.get('physicalUI') is False and
        proof.get('collision_solver_qualified') is False and proof.get('full_feature_accepted') is False and proof.get('scope') == SCOPE and
        len(episodes) == 2 and [e.get('match') for e in episodes] == matches and len({e.get('world') for e in episodes}) == 2 and
        all(e.get('passed') is True and e.get('selected_ids') == IDS and e.get('rendered_members_verified') == e.get('native_members_verified') == 4 and
            e.get('late_remote_replay_verified') is e.get('continuity_verified') is e.get('close_graph_verified') is True and
            e.get('selection_calls') == e.get('group_assign_calls') == 1 and e.get('reselection_calls') == 0 and
            e.get('cache_observed_frames') == 231 and len(e.get('members', [])) == 4 and
            [m.get('entity') for m in e['members']] == IDS and e.get('physicalUI') is False and
            shared.integer(e.get('closed_native_frames'), 650) and
            e.get('closed_native_rows_by_slot') == [e['closed_native_frames']]*2 and
            type(e.get('worlds_by_slot')) is list and len(e['worlds_by_slot']) == 2 and
            all(shared.integer(w, 1) for w in e['worlds_by_slot']) and e['worlds_by_slot'][1] == e.get('world') for e in episodes) and
        proof.get('all_closed_native_hashes_checked') == proof.get('all_retained_wire_triples_checked') ==
            sum(e['closed_native_frames']*2 for e in episodes))


def _report_envelope(report):
    require(type(report) is dict and not report.get('error') and not report.get('forced_cleanup') and
            not report.get('cleanup_errors'), 'scenario already failed/forced')
    rows = report.get('matches', [])
    require(type(rows) is list and len(rows) == 2 and all(type(r) is dict and type(r.get('canonical_frames')) is int and r['canonical_frames'] == 650 and
        r.get('exact_bridge_and_native_authority_receipts') is True for r in rows), 'both exact650 receipt prefixes missing')
    matches = [r['match'] for r in rows]
    require(len(set(matches)) == 2 and all(type(m) is str and re.fullmatch('[a-f0-9]{32}', m) for m in matches), 'match identities differ')
    clients = report.get('clients', [])
    require(type(clients) is list and len(clients) == 2 and all(type(c) is dict for c in clients) and {c.get('index') for c in clients} == {0, 1} and
        all(c.get('natural_worker_shutdown') is True and c.get('matches') == matches and c.get('movement_route') is True for c in clients),
        'actual clients lack matching natural worker/BEGIN evidence')
    return matches


def finalize(report, plan):
    validate_plan(plan)
    require(plan.get('close_formation') is True, 'finalize requires explicit scenario')
    report['close_formation_witness_passed'] = report['scoped_observation_passed'] = False
    matches = _report_envelope(report)
    require(_proof_contract(report.get('close_formation', {}), matches), 'complete two-world proof missing/failed')
    report['close_formation_witness_passed'] = report['scoped_observation_passed'] = True
    report['generic_movement_not_exercised'] = True
    report['movement_feel_witness_passed'] = False


def gate(plan, report):
    if not plan.get('close_formation'):
        return plan.get('scenario') != 'close-formation'
    try:
        validate_plan(plan)
        matches = _report_envelope(report)
        return bool(report.get('close_formation_witness_passed') is report.get('scoped_observation_passed') is True and
            report.get('generic_movement_not_exercised') is True and report.get('movement_feel_witness_passed') is False and
            _proof_contract(report.get('close_formation', {}), matches))
    except (AssertionError, KeyError, TypeError, AttributeError):
        return False
