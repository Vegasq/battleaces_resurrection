"""Pure evidence joins for the explicit owned-process bound-mouse/HQ experiment.

The update counter belongs to original frontend callbacks. It is not an
InputSystem serial, a hardware-input witness, or an Internet-feel measurement.
"""
from __future__ import annotations

import json
import math
import re
import struct


PREFIX = 'EXPIRED CLICK '
PHASES = ('focused', 'position_queued', 'pressed', 'released', 'expired_before_setup',
          'input_closed', 'after_setup', 'dead_hq_retained', 'hq_restored', 'complete')
FIELDS = set(('schema', 'event', 'sequence', 'world', 'match', 'slot', 'entity', 'frame',
    'update', 'update_scope', 'input_sequence', 'selector', 'action', 'control', 'device',
    'input_source', 'ownership_scope', 'owned_button', 'input_closed', 'click_id', 'mode', 'primary',
    'context', 'drag', 'now_bits', 'last_up_bits', 'window_bits', 'originalClockSingle', 'physicalUI'))
ACTOR_EVENTS = ('original_hq_selection_established', 'original_dead_hq_retained',
                'original_hq_restored_and_admitted', 'hq_selection_correction_passed')
UINT32, UINT64 = 2**32 - 1, 2**64 - 1


def require(ok, reason):
    if not ok:
        raise AssertionError('expired click evidence: ' + reason)


def integer(value, low=0, high=UINT64):
    return type(value) is int and low <= value <= high


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def single(bits):
    require(integer(bits, 0, UINT32), 'invalid Single bits')
    value = struct.unpack('<f', struct.pack('<I', bits))[0]
    require(math.isfinite(value) and value >= 0, 'invalid original Single value')
    return value


def elapsed(row):
    now, last, window = (single(row[key]) for key in ('now_bits', 'last_up_bits', 'window_bits'))
    require(now >= last, 'original Single clock moved backwards')
    delta = struct.unpack('<f', struct.pack('<f', now - last))[0]
    require(math.isfinite(delta), 'invalid original Single elapsed time')
    return delta, window


def read_records(log):
    require(type(log) is str and len(log) <= 64 * 1024 * 1024, 'log exceeds bound')
    clicks, actors = [], []
    for line_number, line in enumerate(log.splitlines()):
        prefix = PREFIX if PREFIX in line else 'ACTOR CORRECTION ' if 'ACTOR CORRECTION ' in line else None
        if prefix is None:
            continue
        require(len(line) <= 8192, 'diagnostic line exceeds bound')
        try:
            row = json.loads(line.split(prefix, 1)[1], object_pairs_hook=unique_object)
        except (ValueError, TypeError) as error:
            raise AssertionError('expired click evidence: invalid diagnostic JSON') from error
        require(type(row) is dict, 'diagnostic is not an object')
        target = clicks if prefix == PREFIX else actors
        target.append((line_number, row))
        require(len(target) <= (20 if target is clicks else 8), 'unexpected extra diagnostic records')
    return clicks, actors


def evaluate(log, *, actor_episodes, expected_matches):
    """Join two actual value histories to independently passed full HQ proofs."""
    require(type(expected_matches) is list and len(expected_matches) == 2 and
            all(type(match) is str and re.fullmatch('[a-f0-9]{32}', match) for match in expected_matches) and
            len(set(expected_matches)) == 2,
            'two ordered actual matches required')
    require(type(actor_episodes) is list and len(actor_episodes) == 2 and all(type(episode) is dict for episode in actor_episodes) and
            [episode.get('match') for episode in actor_episodes] == expected_matches and
            all(episode.get('passed') is True for episode in actor_episodes),
            'both full original HQ correction proofs are required')
    clicks, actor_rows = read_records(log)
    require(len(clicks) == 20 and len(actor_rows) == 8 and
            [row.get('match') for _, row in clicks] == [match for match in expected_matches for _ in PHASES],
            'both complete source-ordered click histories required')
    require(all(integer(row.get('update'), 1) and integer(row.get('now_bits'), 0, UINT32) for _, row in clicks) and
            all(b['update'] >= a['update'] and single(b['now_bits']) >= single(a['now_bits'])
                for (_, a), (_, b) in zip(clicks, clicks[1:])),
            'original callback ordinal/Single clock regressed across matches')
    result = []
    for episode in actor_episodes:
        match = episode['match']
        own = [(line, row) for line, row in clicks if row.get('match') == match]
        actor = [(line, row) for line, row in actor_rows if row.get('match') == match]
        rows = [row for _, row in own]
        require([row.get('event') for row in rows] == list(PHASES) and
                [row.get('sequence') for row in rows] == list(range(1, 11)),
                'missing, duplicate or reordered click phase')
        require([row.get('event') for _, row in actor] == list(ACTOR_EVENTS) and
                [row for _, row in actor] == episode.get('rows'),
                'HQ proof is not the same retained source episode')
        world = actor[0][1].get('world')
        require(integer(world, 1) and all(row.get('world') == world and row.get('match') == match for _, row in actor),
                'HQ world binding differs')
        for row in rows:
            require(set(row) == FIELDS and row.get('schema') == 1 and type(row['schema']) is int and
                    row.get('world') == world and type(row['world']) is int and row.get('slot') == 1 and
                    type(row['slot']) is int and row.get('entity') == 5 and type(row['entity']) is int and
                    integer(row.get('frame'), 120, 649) and integer(row.get('update'), 1) and
                    integer(row.get('sequence'), 1, 10) and integer(row.get('input_sequence'), 0, 3) and
                    row.get('update_scope') == 'original_frontend_callback' and
                    row.get('originalClockSingle') is True and row.get('physicalUI') is False and
                    row.get('input_source') == 'bound_existing_mouse',
                    'typed original callback/value receipt differs')
            require(integer(row.get('click_id'), 0, UINT32) and type(row.get('mode')) is int and row['mode'] in (0, 1, 2) and
                    all(type(row.get(key)) is bool for key in ('primary', 'context', 'drag', 'input_closed')),
                    'invalid original click scalar types')
            require(all(type(row.get(key)) is str and re.fullmatch('[0-9a-fA-F]{1,16}', row[key]) and int(row[key], 16)
                        for key in ('selector', 'action', 'control', 'device')), 'invalid owned input identity tuple')
            elapsed(row)
        require(len({tuple(int(row[key], 16) for key in ('selector', 'action', 'control', 'device')) for row in rows}) == 1,
                'owned selector/action/control/device identity changed')
        require(all(b['frame'] >= a['frame'] and b['update'] >= a['update'] and single(b['now_bits']) >= single(a['now_bits'])
                    for a, b in zip(rows, rows[1:])), 'callback/frame/Single observations regressed')
        require([row['input_sequence'] for row in rows] == [0, 1, 2, 3, 3, 3, 3, 3, 3, 3],
                'actual queued input sequence differs')
        require(rows[2]['update'] > rows[1]['update'] and rows[3]['update'] > rows[2]['update'] and
                rows[4]['update'] > rows[3]['update'], 'press/release/expiry lack separate original frontend callbacks')
        require([row['owned_button'] for row in rows[:5]] == [False, False, True, False, False] and
                all(type(row['owned_button']) is bool and row['ownership_scope'] == 'borrowed_current' and not row['input_closed']
                    for row in rows[:5]) and
                all(row['owned_button'] is None and row['ownership_scope'] == 'retained_scalar' and row['input_closed']
                    for row in rows[5:]), 'borrowed-device button observations/session-close scope differ')
        require(rows[2]['primary'] and not rows[2]['context'] and not rows[2]['drag'],
                'owned press did not reach the original selector callback')
        require(all(not row['primary'] and not row['context'] and not row['drag'] for row in rows[:2] + rows[3:]),
                'before-press or released history still has a held or drag owner')
        history = tuple(rows[3][key] for key in ('click_id', 'mode', 'last_up_bits', 'window_bits'))
        require(history[:2] == (5, 0) and all(tuple(row[key] for key in
                ('click_id', 'mode', 'last_up_bits', 'window_bits')) == history for row in rows[3:]),
                'released affected click history was cleared, refreshed or replaced')
        require(all(elapsed(row)[0] > elapsed(row)[1] for row in rows[4:]),
                'history is not strictly expired under original Single arithmetic')
        require(own[4][0] < actor[0][0] < own[6][0] and
                all(actor[index][0] < own[index + 6][0] for index in (1, 2)) and
                actor[3][0] < own[9][0] and
                all(rows[index + 6]['frame'] == actor[index][1]['frame'] for index in range(3)) and
                rows[9]['frame'] >= actor[3][1]['frame'],
                'expired history is not source/frame-bound through original HQ setup/death/restoration/completion')
        result.append(dict(passed=True, match=match, world=world, rows=rows,
            source_line_indices=[line for line, _ in own], original_actor_rows=episode['rows'],
            expired_elapsed_seconds=elapsed(rows[4])[0], original_window_seconds=elapsed(rows[4])[1],
            history_unchanged=True, owned_virtual_device_exercised=False,
            bound_existing_process_device_exercised=True, native_device_removed=False, physical_input_exercised=False))
    return dict(passed=True, episodes=result, original_actor_gate_passed=True,
        physical_input_exercised=False, inputsystem_update_serial_observed=False,
        scope='Queued input to the unique already-bound Mouse inside the owned process through separate original frontend callbacks; exact Single expiry and '
              'unchanged click history through both independently qualified HQ correction episodes. No physical/Internet acceptance.')
