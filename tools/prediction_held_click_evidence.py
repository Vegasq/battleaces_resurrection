"""Pure retained-evidence checks for the explicit held HQ click diagnostic.

No launch, input, native call, or expected-failure-to-pass conversion lives here.
A stopped unchanged retirement guard leaves an incomplete, failing witness.
"""
from __future__ import annotations

import json
import math
import re
import struct

PREFIX = 'HELD CLICK '
PHASES = ('setup', 'focused', 'position_queued', 'position_observed', 'press_queued',
          'pressed', 'held_checkpoint', 'dead_hq_retained', 'hq_restored', 'preview_ready',
          'release_queued', 'released', 'input_closed', 'complete')
ACTOR_EVENTS = ('original_hq_selection_established', 'original_dead_hq_retained',
                'original_hq_restored_and_admitted', 'hq_selection_correction_passed')
PRESERVED = 'preserved_numeric_sets'
NATURAL_REMOVED = 'tracked_natural_removal'
FIELDS = set(('schema', 'event', 'sequence', 'world', 'match', 'slot', 'entity', 'unit_type',
    'frame', 'update', 'update_scope', 'input_sequence', 'selector', 'action', 'control', 'device',
    'input_source', 'ownership_scope', 'owned_button', 'input_closed', 'click_id', 'mode',
    'primary', 'context', 'drag', 'now_bits', 'last_up_bits', 'window_bits', 'target_position_bits',
    'current_position_bits', 'down_position_bits', 'reference_position_bits', 'current_ids', 'preview_ids',
    'current_exact5', 'current_empty', 'preview_exact5', 'preview_empty', 'original_actor', 'current_actor',
    'original_token', 'current_token', 'original_dead', 'original_component', 'focus_group',
    'focus_actor', 'active_caster', 'input_serial', 'accepted_down_serial', 'provenance_phase',
    'originalClockSingle', 'selectionWritesAfterPress', 'physicalUI'))
UINT32, UINT64 = 2**32 - 1, 2**64 - 1


def require(ok, reason):
    if not ok:
        raise AssertionError('held click evidence: ' + reason)


def integer(value, low=0, high=UINT64):
    return type(value) is int and low <= value <= high


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def single(bits, *, signed=False):
    require(integer(bits, 0, UINT32), 'invalid Single bits')
    value = struct.unpack('<f', struct.pack('<I', bits))[0]
    require(math.isfinite(value) and (signed or value >= 0), 'invalid original Single value')
    return value


def pointer(value, *, optional=False):
    require(type(value) is str and re.fullmatch('[0-9a-fA-F]{1,16}', value), 'invalid observed pointer')
    result = int(value, 16)
    require(optional or result, 'required observed pointer missing')
    return result


def records(log):
    require(type(log) is str and len(log) <= 64 * 1024 * 1024, 'log exceeds bound')
    require(not any(reason in log for reason in ('Held click smoke failed:',
        'retiring identity remains in live or unresolved click intent',
        'retiring identity remains in held gesture selection or cached type subset')),
        'retained failure remains RED; a refusal is not a completed repair')
    clicks, actors = [], []
    for line_number, line in enumerate(log.splitlines()):
        prefix = PREFIX if PREFIX in line else 'ACTOR CORRECTION ' if 'ACTOR CORRECTION ' in line else None
        if prefix is None:
            continue
        require(len(line) <= 16384, 'diagnostic line exceeds bound')
        try:
            row = json.loads(line.split(prefix, 1)[1], object_pairs_hook=unique_object)
        except (ValueError, TypeError) as error:
            raise AssertionError('held click evidence: invalid diagnostic JSON') from error
        require(type(row) is dict, 'diagnostic is not an object')
        target = clicks if prefix == PREFIX else actors
        target.append((line_number, row))
        require(len(target) <= (28 if target is clicks else 8), 'unexpected diagnostic count')
    return clicks, actors


def evaluate(log, *, actor_episodes, expected_matches):
    """Require both full HQ replay proofs and a balanced real-callback held input."""
    require(type(expected_matches) is list and len(expected_matches) == 2 and
        all(type(match) is str and re.fullmatch('[a-f0-9]{32}', match) for match in expected_matches) and
        len(set(expected_matches)) == 2, 'two ordered actual matches required')
    require(type(actor_episodes) is list and len(actor_episodes) == 2 and
        all(type(episode) is dict and episode.get('passed') is True for episode in actor_episodes) and
        [episode.get('match') for episode in actor_episodes] == expected_matches,
        'both independently passed full original HQ correction proofs required')
    clicks, actors = records(log)
    require(len(clicks) == 28 and len(actors) == 8 and
        [row.get('match') for _, row in clicks] == [match for match in expected_matches for _ in PHASES],
        'both complete held-click episodes required')
    result = []
    previous_update, previous_time = 0, 0.0
    for world, episode in enumerate(actor_episodes, 1):
        match = episode['match']
        own = [(line, row) for line, row in clicks if row.get('match') == match]
        actor = [(line, row) for line, row in actors if row.get('match') == match]
        rows = [row for _, row in own]
        require([row.get('event') for row in rows] == list(PHASES) and
            [row.get('sequence') for row in rows] == list(range(1, 15)),
            'missing, duplicate or reordered held-click phase')
        require([row.get('event') for _, row in actor] == list(ACTOR_EVENTS) and
            [row for _, row in actor] == episode.get('rows') and
            all(row.get('world') == world and row.get('match') == match for _, row in actor),
            'full HQ proof differs from retained source/world')
        for row in rows:
            require(set(row) == FIELDS and integer(row['schema'], 1, 1) and
                integer(row['world'], world, world) and row['match'] == match and
                integer(row['slot'], 1, 1) and integer(row['entity'], 5, 5) and integer(row['unit_type'], 3, 3) and
                integer(row['frame'], 130, 167) and integer(row['update'], 1) and
                integer(row['input_sequence'], 0, 3) and row['update_scope'] == 'original_frontend_callback' and
                row['input_source'] == 'bound_existing_mouse' and row['physicalUI'] is False and
                row['originalClockSingle'] is True and integer(row['selectionWritesAfterPress'], 0, 0),
                'typed source/schema or no-reselection receipt differs')
            require(integer(row['click_id'], 0, UINT32) and integer(row['mode'], 0, 2) and
                all(type(row[key]) is bool for key in ('primary', 'context', 'drag', 'input_closed',
                    'current_exact5', 'current_empty', 'preview_exact5', 'preview_empty',
                    'original_dead', 'original_component')),
                'typed original state differs')
            require(integer(row['original_token'], 1) and integer(row['current_token']) and
                integer(row['input_serial']) and integer(row['accepted_down_serial']) and
                integer(row['provenance_phase'], 0, 3) and type(row['focus_group']) is int and
                row['focus_group'] == -1 and pointer(row['focus_actor'], optional=True) == 0 and
                pointer(row['active_caster'], optional=True) == 0, 'identity/provenance/focus scope differs')
            for key in ('selector', 'action', 'control', 'device', 'original_actor'):
                pointer(row[key])
            pointer(row['current_actor'], optional=True)
            for key in ('target_position_bits', 'current_position_bits', 'down_position_bits', 'reference_position_bits'):
                require(type(row[key]) is list and len(row[key]) == 2, 'original Vector2 bits differ')
                for value in row[key]:
                    single(value, signed=True)
            for key in ('current_ids', 'preview_ids'):
                require(type(row[key]) is list and len(row[key]) <= 1 and
                    all(integer(value, 0, UINT32) for value in row[key]), 'raw membership ID shape differs')
                stem = key[:-4]
                require((row[key] == [5] and row[stem + '_exact5'] is True and row[stem + '_empty'] is False) or
                    (row[key] == [] and row[stem + '_exact5'] is False and row[stem + '_empty'] is True),
                    'raw membership lacks exact all+typed cache proof')
            now, last, _ = (single(row[key]) for key in ('now_bits', 'last_up_bits', 'window_bits'))
            require(now >= last and row['update'] >= previous_update and now >= previous_time,
                'original frontend ordinal/Single clock regressed')
            previous_update, previous_time = row['update'], now
        require(all(b['frame'] >= a['frame'] for a, b in zip(rows, rows[1:])), 'native frame regressed')
        require(rows[0]['frame'] == rows[1]['frame'] == 130 and rows[2]['frame'] in (148,149) and
            rows[3]['frame'] == rows[4]['frame'] in (150,151) and rows[4]['frame'] <= rows[5]['frame'] <= 154 and
            rows[6]['frame'] == 154 and rows[7]['frame'] in (155,156) and 158 <= rows[8]['frame'] <= 164 and
            rows[8]['frame'] <= rows[9]['frame'] <= 164 and rows[10]['frame'] in (165,166) and
            rows[10]['frame'] >= rows[8]['frame'] + 2 and
            rows[10]['frame'] <= rows[11]['frame'] <= 167 and
            rows[11]['frame'] == rows[12]['frame'] == rows[13]['frame'] and
            rows[13]['frame'] >= rows[8]['frame'] + 2, 'finite setup/press/death/restore/real-Up frame contract differs')
        require([row['input_sequence'] for row in rows] == [0,0,1,1,2,2,2,2,2,2,3,3,3,3] and
            rows[3]['update'] > rows[2]['update'] and rows[5]['update'] > rows[4]['update'] and
            rows[11]['update'] > rows[10]['update'] and rows[11]['update'] == rows[12]['update'] == rows[13]['update'],
            'queued events were not consumed on separate original frontend callbacks')
        require(len({tuple(pointer(row[key]) for key in ('selector','action','control','device')) for row in rows}) == 1,
            'borrowed selector/action/control/device changed')
        require([row['owned_button'] for row in rows[:12]] == [False]*5 + [True]*6 + [False] and
            all(type(row['owned_button']) is bool and row['ownership_scope'] == 'borrowed_current' and
                row['input_closed'] is False for row in rows[:12]) and
            all(row['owned_button'] is None and row['ownership_scope'] == 'retained_scalar' and
                row['input_closed'] is True for row in rows[12:]), 'actual borrowed-button/close boundary differs')
        require(all(row['primary'] is False and row['mode'] == 0 for row in rows[:5] + rows[11:]) and
            all(row['primary'] is True and row['mode'] == 1 and row['click_id'] == 5 for row in rows[5:11]) and
            all(row['context'] is False and row['drag'] is False for row in rows) and
            all(row['click_id'] == 5 for row in rows[11:]), 'original held Single/id5 or final Up differs')
        history = tuple(rows[5][key] for key in ('click_id','mode','last_up_bits','window_bits'))
        require(all(tuple(row[key] for key in ('click_id','mode','last_up_bits','window_bits')) == history
            for row in rows[5:11]), 'held history was cleared/refreshed before real Up')
        target = rows[2]['target_position_bits']
        require(all(row['target_position_bits'] == target for row in rows[2:]) and
            all(row['current_position_bits'] == target for row in rows[3:]) and
            all(row['down_position_bits'] == row['reference_position_bits'] == target for row in rows[5:]),
            'queued/current/press/reference position changed')
        # Borrowed Mouse position survives rematch, so original hover may
        # already preview this HQ before the new position event is delivered.
        # Every raw preview still needs exact all+typed empty-or-HQ proof above;
        # the observed new position and every press require HQ, never empty.
        require(all(row['current_ids'] == [5] for row in rows[:3]) and
            all(row['current_ids'] == row['preview_ids'] == [5] for row in rows[3:5]) and
            all(row['current_ids'] == row['preview_ids'] == [5] for row in rows[5:7]) and
            all(row['current_ids'] == [5] and row['preview_ids'] == [] for row in rows[11:]),
            'raw hover/press/real-Up selection stages differ')
        death = rows[7]
        if death['current_ids'] == death['preview_ids'] == [5] and death['provenance_phase'] == 1:
            variant = PRESERVED
            require(all(row['current_ids'] == row['preview_ids'] == [5] and row['provenance_phase'] == 1
                for row in rows[7:11]), 'preserved-set variant changed numeric sets or held provenance')
        elif death['current_ids'] == death['preview_ids'] == [] and death['provenance_phase'] == 3:
            variant = NATURAL_REMOVED
            require(all(row['current_ids'] == [] and row['provenance_phase'] == 3 for row in rows[7:11]) and
                all(row['preview_ids'] == [5] for row in rows[9:11]),
                'tracked-removal variant reselected current before real Up or lost removal provenance')
        else:
            require(False, 'death needs both preserved typed sets/Held or both empty sets/tracked natural removal')
        original_actor, original_token = pointer(rows[0]['original_actor']), rows[0]['original_token']
        require(all(pointer(row['original_actor']) == original_actor and row['original_token'] == original_token for row in rows) and
            all(pointer(row['current_actor']) == original_actor and row['current_token'] == original_token for row in rows[:7]) and
            pointer(rows[7]['current_actor'], optional=True) == 0 and rows[7]['current_token'] == 0 and
            rows[7]['original_dead'] is True and rows[7]['original_component'] is False,
            'immutable original actor/death lease differs')
        restored_actor, restored_token = pointer(rows[8]['current_actor']), rows[8]['current_token']
        require(restored_token > 0 and restored_token == original_token and
            all(pointer(row['current_actor']) == restored_actor and row['current_token'] == restored_token for row in rows[8:]),
            'restored canonical logical identity changed; physical allocation is proved separately')
        serial = rows[5]['accepted_down_serial']
        require(serial > 0 and all(row['input_serial'] == row['accepted_down_serial'] == serial for row in rows[5:11]) and
            rows[5]['provenance_phase'] == rows[6]['provenance_phase'] == 1 and
            all(row['input_serial'] > serial and row['accepted_down_serial'] == 0 and row['provenance_phase'] == 0 for row in rows[11:]),
            'exact accepted Down/natural removal/real-Up provenance differs')
        for actor_index, click_index in enumerate((0,7,8,13)):
            require(actor[actor_index][0] < own[click_index][0] and
                actor[actor_index][1]['frame'] == rows[click_index]['frame'] and
                pointer(actor[actor_index][1].get('original_actor')) == original_actor and
                pointer(actor[actor_index][1].get('current_actor')) ==
                    (original_actor if actor_index == 1 else pointer(rows[click_index]['current_actor'])),
                'HQ source/frame/physical actor join differs')
        result.append(dict(passed=True, world=world, match=match, rows=rows, proof_variant=variant,
            source_line_indices=[line for line, _ in own], original_actor_rows=episode['rows'],
            held_history_preserved=True, raw_typed_selection_verified=True,
            genuine_original_up_confirmed=True, roots_closed_after_release=True,
            canonical_identity_preserved=True,
            original_token=original_token, restored_token=restored_token))
    return dict(passed=True, episodes=result, original_actor_gate_passed=True,
        physical_input_exercised=False, inputsystem_update_serial_observed=False,
        expected_refusal_is_pass=False,
        scope='Bound existing process Mouse held through original HQ death/recreation and real Up in both independently qualified HQ correction episodes. Each world retains either intact numeric sets with Held provenance or exact tracked natural removal followed by preview recovery; this evaluator grants no permission for unqualified input and does not accept physical/Internet feel.')
