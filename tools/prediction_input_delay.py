"""Explicit diagnostic input-delay plan and payload-free delivery evidence."""
from __future__ import annotations

import json
import math


SETTINGS = dict(direction='client_to_server', extra_ms=100, duration_ms=250)
TRACE = '74:1:0:400:650'


def require(value, why):
    if not value:
        raise AssertionError('prediction input delay: ' + why)


def validate_settings(value):
    require(type(value) is dict and set(value) == set(SETTINGS) and
            all(type(value[k]) is type(v) and value[k] == v for k, v in SETTINGS.items()),
            'requires the explicit 100ms/250ms client-to-server window')


def validate_plan(plan):
    if 'transition_input_delay' not in plan:
        return
    validate_settings(plan['transition_input_delay'])
    require(plan.get('scenario') == 'movement' and plan.get('lifecycle') == 'natural' and
            type(plan.get('frames')) is int and plan['frames'] == 650 and
            type(plan.get('expected_matches')) is int and plan['expected_matches'] == 2 and
            type(plan.get('move_slot')) is int and plan['move_slot'] == 0 and
            plan.get('changing_rtt') is plan.get('transition_orders') is True and
            plan.get('native_position_trace') == TRACE and
            plan.get('transition_phase_source') == 'decision' and
            plan.get('changing_pose_clock') == 'sampled_us' and
            plan.get('publication_source') == 'post-original-qpc' and
            type(plan.get('rtt_ms')) is list and len(plan['rtt_ms']) == 2 and
            all(finite(v) and v == expected
                for v, expected in zip(plan['rtt_ms'], (130, 475))) and
            all(type(plan.get(k, False)) is bool and not plan.get(k, False) for k in
                ('actor_correction', 'mobile_correction', 'close_formation', 'queued_orders',
                 'multi_unit_move', 'cohort_survivor')),
            'requires the traced natural two-world changing-RTT movement fixture')


def option(args, frames, position_trace):
    value = getattr(args, 'transition_input_delay_ms', None)
    if value is None:
        return None
    require(type(value) is int and value == 100, 'only the explicit 100ms diagnostic is supported')
    validate_plan(dict(scenario=args.scenario, lifecycle=args.lifecycle, frames=frames,
        expected_matches=2 if args.lifecycle == 'natural' else 1, move_slot=args.move_slot,
        rtt_ms=list(args.rtt_ms), native_position_trace=position_trace,
        changing_rtt=getattr(args, 'changing_rtt', False),
        transition_orders=getattr(args, 'transition_orders', False),
        actor_correction=getattr(args, 'actor_correction', False),
        mobile_correction=getattr(args, 'mobile_correction', False),
        transition_phase_source='decision', changing_pose_clock='sampled_us',
        publication_source='post-original-qpc', transition_input_delay=dict(SETTINGS)))
    return dict(SETTINGS)


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def integer(value, minimum=0):
    return type(value) is int and minimum <= value < 2**64


def validate_window(window):
    require(window['direction'] == SETTINGS['direction'] and
            all(finite(window[k]) and window[k] == SETTINGS[k] for k in ('extra_ms', 'duration_ms')) and
            all(integer(window[k]) for k in ('requested_tick_ms', 'effective_tick_ms',
                'requested_perf_counter_ns', 'effective_perf_counter_ns')) and
            window['requested_tick_ms'] <= window['effective_tick_ms'] and
            window['requested_perf_counter_ns'] <= window['effective_perf_counter_ns'] and
            finite(window['start_loop']) and finite(window['end_loop']) and
            abs(window['end_loop'] - window['start_loop'] - .250) < 1e-9 and
            window['requested_perf_counter_ns'] - 2000 <= window['start_loop'] * 1e9 <=
                window['effective_perf_counter_ns'] + 2000,
            'actual window settings/clocks differ')


def evaluate(plan, report, metadata):
    """Bind owner-clock command production and actual opaque-byte scheduling.

    This does not identify which encrypted chunk contains a command. Native
    command/canonical and state checks remain the parent's independent gates.
    """
    validate_plan(plan)
    require('transition_input_delay' in plan, 'explicit scenario missing')
    control = report['changing_rtt_control']
    validate_settings(control['transition_input_delay'])
    worlds = control['worlds']
    turns = report['transition_orders']['episodes']
    require(report['transition_orders']['passed'] is True and
            report['native_position_trace']['passed'] is True and
            report['changing_rtt_smoothness_passed'] is True and
            len(worlds) == len(turns) == 2 and
            [w['match'] for w in worlds] == [t['match'] for t in turns] and
            len({w['match'] for w in worlds}) == len({w['world'] for w in worlds}) == 2,
            'two complete traced transition worlds required')
    windows = metadata['directional_delays']
    require(type(windows) is list and len(windows) == 2 and
            [w['window_id'] for w in windows] == [1, 2] and
            [w['input_delay'] for w in worlds] == windows,
            'actual shaper windows differ from controller receipts')
    for window in windows:
        validate_window(window)
    require(windows[0]['end_loop'] < windows[1]['start_loop'], 'delay windows overlap')
    held = {w['window_id']: [] for w in windows}
    held_rows = {w['window_id']: [] for w in windows}
    recovered = {w['window_id']: [] for w in windows}
    fields = {'base_due_loop', 'directional_extra_ms', 'directional_window_id', 'final_due_loop'}
    for direction, bucket in metadata['directions'].items():
        require(direction in ('client_to_server', 'server_to_client') and
                integer(bucket['dropped']) and bucket['dropped'] == 0 and
                integer(bucket['seen'], 1) and bucket['seen'] == len(bucket['rows']) and bucket['rows'],
                'complete payload-free direction metadata required')
        rows = bucket['rows']
        require({r['connection'] for r in rows} == {1} and
                [r['chunk'] for r in rows] == list(range(1, len(rows) + 1)),
                'one owned connection with complete chunk order required')
        previous_base = previous_final = previous_read = 0.
        for row in rows:
            require(all(finite(row[k]) for k in ('received_loop', 'due_loop', 'configured_rtt_ms')) and
                    row['received_loop'] >= previous_read and integer(row['byte_count'], 1),
                    'chunk clocks/byte count differ')
            # The selected controller creates this relay with jitter=0. Its
            # ordinary source schedule is independently reconstructed per read.
            base = max(previous_base, row['received_loop'] + row['configured_rtt_ms'] / 2000)
            active = [w for w in windows if direction == w['direction'] and
                      w['start_loop'] <= row['received_loop'] < w['end_loop']]
            require(len(active) <= 1, 'ambiguous active delay')
            extra = .100 if active else 0.
            final = max(previous_final, base + extra)
            require(abs(row['due_loop'] - final) < 1e-9, 'byte schedule accumulated/masked delay or changed order')
            if direction == 'client_to_server' and row['received_loop'] >= windows[0]['start_loop']:
                require(fields <= set(row) and finite(row['base_due_loop']) and finite(row['final_due_loop']) and
                        abs(row['base_due_loop'] - base) < 1e-9 and abs(row['final_due_loop'] - final) < 1e-9 and
                        row['directional_extra_ms'] == extra * 1000 and
                        row['directional_window_id'] == (active[0]['window_id'] if active else None),
                        'counterfactual base/final/window metadata differs')
            else:
                require(not fields.intersection(row), 'pending chunk or other direction was changed')
            if row['forwarded_loop'] is not None:
                require(finite(row['forwarded_loop']) and row['forwarded_loop'] + 1e-9 >= final and
                        finite(row['held_ms']) and
                        abs(row['held_ms'] - (row['forwarded_loop'] - row['received_loop']) * 1000) < 1e-6,
                        'chunk forwarded before its actual due time')
            if row['drained_loop'] is not None:
                require(finite(row['drained_loop']) and row['forwarded_loop'] is not None and
                        row['drained_loop'] >= row['forwarded_loop'], 'chunk drain precedes forwarding')
            if active:
                require(row['forwarded_loop'] is not None and row['drained_loop'] is not None and
                        abs(final - base - .100) < 1e-9, 'selected delayed chunk did not complete its100ms extension')
                held[active[0]['window_id']].append(row['chunk'])
                held_rows[active[0]['window_id']].append(row)
            if (direction == 'client_to_server' and not active and abs(final - base) < 1e-9 and
                    row['forwarded_loop'] is not None and row['drained_loop'] is not None):
                for window in windows:
                    if row['received_loop'] >= window['end_loop'] and (window['window_id'] == 2 or
                            row['received_loop'] < windows[1]['start_loop']):
                        recovered[window['window_id']].append(row['chunk'])
            previous_base, previous_final, previous_read = base, final, row['received_loop']
    require(set(metadata['directions']) == {'client_to_server', 'server_to_client'}, 'both stream directions required')
    episodes = []
    for state, transition, window in zip(worlds, turns, windows):
        order = transition['orders'][0]
        original = order['original_order']
        gate = state['turn2_gate']
        post_enqueue = [r['chunk'] for r in held_rows[window['window_id']]
                        if r['received_loop'] * 1e6 >= original['enqueue_sampled_us']]
        require(state['stage'] == 'complete' and original['ordinal'] == 2 and
                original['world'] == state['world'] and original['match'] == state['match'] and
                state['fall']['effective_perf_counter_ns'] <= window['requested_perf_counter_ns'] <=
                    window['effective_perf_counter_ns'] <= gate['requested_perf_counter_ns'] <=
                    gate['published_perf_counter_ns'] <= original['enqueue_sampled_us'] * 1000 <=
                    window['requested_perf_counter_ns'] + 250_000_000 and
                window['effective_tick_ms'] <= order['native67_tick_ms'] <= order['native72_send_tick_ms'] <=
                    window['requested_tick_ms'] + 250 and post_enqueue and recovered[window['window_id']],
                'actual turn2 enqueue/67/72 is outside the controlled delay episode or recovery is missing')
        episodes.append(dict(match=state['match'], world=state['world'], window=dict(window),
            sequence=order['sequence'], action_sha256=order['action_sha256'],
            assigned_frame=order['assigned_frame'], canonical_frame=order['canonical_frame'],
            enqueue_sampled_us=original['enqueue_sampled_us'], native67_tick_ms=order['native67_tick_ms'],
            native72_send_tick_ms=order['native72_send_tick_ms'],
            affected_chunks=held[window['window_id']], post_enqueue_affected_chunks=post_enqueue,
            recovered_chunk=recovered[window['window_id']][0]))
    return dict(passed=True, settings=dict(SETTINGS), worlds=episodes,
        tcp_order_preserved=True, default_other_direction_preserved=True, per_chunk_delay_does_not_accumulate=True,
        tls_chunk_to_command_mapping_claimed=False,
        scope='Actual100ms extra C2S scheduling during250ms read windows; exact original command creation and receipt clocks, without decrypted TLS chunk attribution')


def finalize(plan, report, run):
    if 'transition_input_delay' not in plan:
        return
    try:
        metadata = json.loads((run / 'shaper-delay-0.json').read_text())
        report['transition_input_delay'] = evaluate(plan, report, metadata)
    except (AssertionError, KeyError, TypeError, ValueError, AttributeError, IndexError, OSError, OverflowError) as error:
        report['transition_input_delay'] = dict(passed=False, error=repr(error))
        report.setdefault('error', repr(error))


def gate(plan, report):
    if 'transition_input_delay' not in plan:
        return True
    try:
        validate_plan(plan)
        proof = report['transition_input_delay']
        validate_settings(proof['settings'])
        worlds = proof['worlds']
        controls = report['changing_rtt_control']['worlds']
        turns = report['transition_orders']['episodes']
        require(len(worlds) == len(controls) == len(turns) == 2 and
                report['transition_orders']['passed'] is report['native_position_trace']['passed'] is
                    report['changing_rtt_smoothness_passed'] is True,
                'complete traced transition proof required')
        for world, control, turn in zip(worlds, controls, turns):
            validate_window(world['window'])
            order = turn['orders'][0]
            original = order['original_order']
            require(world['window'] == control['input_delay'] and
                    integer(world['world'], 1) and world['world'] == control['world'] == original['world'] and
                    world['match'] == control['match'] == turn['match'] == original['match'] and
                    all(integer(world[k], 1) and world[k] == order[k] for k in
                        ('sequence', 'assigned_frame', 'canonical_frame', 'native67_tick_ms', 'native72_send_tick_ms')) and
                    world['action_sha256'] == order['action_sha256'] and
                    world['enqueue_sampled_us'] == original['enqueue_sampled_us'] and
                    all(type(world[k]) is list and world[k] == sorted(set(world[k])) and
                        all(integer(chunk, 1) for chunk in world[k]) for k in
                        ('affected_chunks', 'post_enqueue_affected_chunks')) and
                    world['affected_chunks'] and world['recovered_chunk'] > max(world['affected_chunks']),
                    'persisted delay world/command binding differs')
        return bool(proof['passed'] is proof['tcp_order_preserved'] is
            proof['default_other_direction_preserved'] is proof['per_chunk_delay_does_not_accumulate'] is True and
            proof['tls_chunk_to_command_mapping_claimed'] is False and len(worlds) == 2 and
            [w['match'] for w in worlds] == [w['match'] for w in report['changing_rtt_control']['worlds']] and
            [w['window']['window_id'] for w in worlds] == [1, 2] and
            all(w['affected_chunks'] and w['post_enqueue_affected_chunks'] and
                set(w['post_enqueue_affected_chunks']) <= set(w['affected_chunks']) and integer(w['recovered_chunk'], 1) and
                integer(w['sequence'], 1) and type(w['action_sha256']) is str and len(w['action_sha256']) == 64 and
                integer(w['enqueue_sampled_us']) and integer(w['native67_tick_ms']) and
                integer(w['native72_send_tick_ms']) for w in worlds))
    except (AssertionError, KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError):
        return False
