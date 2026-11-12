"""Opt-in Actual74 visual correction capture and closed-file evidence gate.

The independent oracle reconstructs finite cubic pulses from native same-head
evidence and actual publication/sample clocks. It never loads the game or native
engine, simulates a missing pose, or turns a visual-only result into acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from tools import prediction_correction_motion as motion
from tools import prediction_input_delay as input_delay
from tools import prediction_visual_lifetime as lifetime


PREFIX = 'PREDICTION VISUAL '
DURATION_US = 900_000
TAIL_US = 150_000
RAW_MINIMUM = .75
DISPLAY_MAXIMUM = .35
COMMON = {'schema', 'event', 'world', 'match', 'frame', 'entity', 'unit_type', 'army',
          'incarnation', 'lease', 'publication_us', 'flipped'}
CORRECTION = COMMON | {'head', 'revision', 'duration_us', 'admission', 'native_delta', 'mapped_delta'}
POSE = COMMON | {'sampled_us', 'alpha', 'elapsed', 'step', 'pulses', 'wrote',
                 'from', 'to', 'raw', 'displayed', 'output', 'transform'}


def require(value, why):
    if not value:
        raise AssertionError('prediction visual correction: ' + why)


def validate_plan(plan):
    require('visual_correction' not in plan or type(plan['visual_correction']) is bool,
            'option must be Boolean')
    if not plan.get('visual_correction'):
        return
    require('transition_input_delay' in plan, 'requires the explicit Actual74 input delay')
    input_delay.validate_plan(plan)
    from tools.prediction_mobile_plan import EXPIRED_CLICK_MOBILE_FLAGS
    require(all(type(plan.get(k, False)) is bool and not plan.get(k, False) for k in
                (*EXPIRED_CLICK_MOBILE_FLAGS, 'expired_click', 'held_click', 'actor_mirror',
                 'terminal_timeline', 'cohort_canonical_death')),
            'requires only the bounded Actual74 movement fixture')


def option(args, frames, trace, delay):
    enabled = getattr(args, 'visual_correction', False)
    plan = dict(vars(args), frames=frames, expected_matches=2 if args.lifecycle == 'natural' else 1,
        rtt_ms=list(args.rtt_ms), native_position_trace=trace, visual_correction=enabled,
        transition_phase_source='decision', changing_pose_clock='sampled_us',
        publication_source='post-original-qpc')
    if delay is not None:
        plan['transition_input_delay'] = delay
    validate_plan(plan)
    return enabled


def helper(enabled, data):
    if enabled:
        require(b'OfflinePredictionVisualJoin\0' in data and all(flag.encode('utf-16-le') in data
            for flag in ('-prediction-visual-correction', '-prediction-visual-observe', '-prediction-presentation-stages')),
            'helper lacks the visual join export or explicit UTF16 flags')


def rows(log):
    require(type(log) is str and len(log.encode('utf-8')) <= 64*1024*1024, 'bounded UTF8 log required')
    require('Prediction visual correction failed:' not in log, 'renderer reported a consumer failure')
    result = []
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate JSON field')
            value[key] = item
        return value
    for line in log.splitlines():
        if PREFIX not in line:
            continue
        raw = line.split(PREFIX, 1)[1]
        if raw.startswith('INPUT '):
            continue  # Separately bounded/validated frontend-query records.
        require(len(raw.encode('utf-8')) <= 4096, 'diagnostic line exceeds bound')
        row = json.loads(raw, object_pairs_hook=unique)
        require(type(row) is dict and row.get('event') in ('correction', 'visual_pose') and
                set(row) == (CORRECTION if row['event'] == 'correction' else POSE) and
                type(row['schema']) is int and row['schema'] == 1, 'diagnostic schema differs')
        require(all(motion.integer(row[k]) for k in ('world', 'frame', 'entity', 'unit_type', 'army',
                    'incarnation', 'lease', 'publication_us')) and
                row['world'] > 0 and row['incarnation'] > 0 and row['lease'] > 0 and
                type(row['match']) is str and re.fullmatch('[a-f0-9]{32}', row['match']) and
                400 <= row['frame'] <= 650 and type(row['flipped']) is bool,
                'diagnostic identity/clock/window differs')
        if row['event'] == 'correction':
            require(all(motion.integer(row[k]) for k in ('head', 'revision', 'duration_us', 'admission')) and
                    row['head']+1 == row['frame'] and row['revision'] > 0 and
                    row['duration_us'] == DURATION_US and row['admission'] == 0,
                    'target correction refused, zero, or not admitted for900ms')
            vectors = ('native_delta', 'mapped_delta')
        else:
            require(motion.integer(row['sampled_us'], 1) and motion.integer(row['pulses']) and
                    type(row['wrote']) is bool and all(input_delay.finite(row[k]) for k in
                    ('alpha', 'elapsed', 'step')) and 0 <= row['alpha'] <= 1 and
                    row['elapsed'] >= 0 and row['step'] >= 0, 'pose clock/alpha/schema differs')
            vectors = ('from', 'to', 'raw', 'displayed', 'output', 'transform')
        for name in vectors:
            row[name] = motion.vec(row[name])  # emitted nine-digit decimal -> exact Single
        result.append(row)
        require(len(result) <= 200_000, 'two-world diagnostic row bound exceeded')
    require(result, 'actual joined visual observations missing')
    return result


def close(actual, expected, why):
    tolerance = motion.precision_bound([actual, expected])
    require(tolerance < .001 and math.dist(actual, expected) <= max(tolerance, 1e-12), why)
    return math.dist(actual, expected)


def mapped(vector, flipped):
    return [-vector[0], vector[1], -vector[2]] if flipped else list(vector)


def backtrack(poses, field, direction):
    peak = None
    best = dict(amount=0., from_sampled_us=None, to_sampled_us=None)
    for row in poses:
        coordinate = motion.dot(row[field], direction)
        if peak is None or coordinate > peak[0]:
            peak = coordinate, row['sampled_us']
        if peak[0]-coordinate > best['amount']:
            best = dict(amount=peak[0]-coordinate, from_sampled_us=peak[1], to_sampled_us=row['sampled_us'])
    return best


def evaluate_world(*, binding, records, native, episodes, publications, command, next_order):
    """Validate a real bound actor's entire window, plus the original turn2 interval."""
    require(records and all(all(r[k] == binding[k] for k in binding) for r in records),
            'visual actor/native binding differs')
    require(len({r['lease'] for r in records}) == len({r['flipped'] for r in records}) == 1,
            'selected actor lease/perspective changed inside the bounded capture')
    poses = [r for r in records if r['event'] == 'visual_pose']
    corrections = [r for r in records if r['event'] == 'correction']
    require(len(poses) >= 20 and corrections and poses[0]['frame'] == 400 and poses[-1]['frame'] == 650,
            'full400..650 observed window with corrections required')
    require(all(b['sampled_us'] > a['sampled_us'] and b['frame'] >= a['frame']
                for a, b in zip(poses, poses[1:])) and
            all(b['revision'] > a['revision'] and b['frame'] > a['frame'] and
                b['publication_us'] > a['publication_us'] for a, b in zip(corrections, corrections[1:])),
            'sample/publication/revision order differs')
    by_frame = {}
    for pose in poses:
        by_frame.setdefault(pose['frame'], []).append(pose)
    require(list(by_frame) == list(range(400, 651)), 'a traced publication lacks an actual joined pose')
    timing = {r['frame']: r['qpc_us'] for r in publications}
    actual = [r for r in native if r['world'] == binding['world'] and
              r['event'] != 'before_restore_cached_head' and r['status'] == 'present']
    endpoints = {}
    translation = None
    for frame, group in by_frame.items():
        first = group[0]
        require(all(r['publication_us'] == first['publication_us'] and r['from'] == first['from'] and
                    r['to'] == first['to'] for r in group), 'one publication changed immutable endpoints/clock')
        require(first['publication_us'] <= timing[frame] <= first['sampled_us'] and
                all(r['publication_us'] <= r['sampled_us'] < timing.get(frame+1, 2**64) for r in group),
                'visual clock is outside its original publication interval')
        candidates = [r for r in actual if r['frame'] == frame and r['query_end_us'] <= first['publication_us']]
        require(candidates, 'published endpoint lacks the subject native query')
        endpoint = max(candidates, key=lambda r: r['query_end_us'])
        endpoints[frame] = endpoint
        position = mapped(endpoint['position'], first['flipped'])
        if translation is None:
            translation = motion.sub(first['to'], position)
        close(first['to'], motion.add(position, translation), 'To differs from actual mapped native publication')
        if frame > 400:
            close(first['from'], by_frame[frame-1][0]['to'], 'From differs from preceding immutable native To')
    # Multiple repairs at the same H coalesce before the next publication. Bind
    # FIRST cached H -> LAST repaired H; never include ordinary H->H+1 movement.
    pairs = {}
    for episode in episodes:
        if episode['physical_head'] is not None and 400 <= episode['physical_head']+1 <= 650:
            require(episode['qualified'], 'unqualified native same-head pair inside visual window')
            pairs.setdefault(episode['physical_head'], []).append(episode)
    expected = {}
    for head, group in pairs.items():
        before, after = native[group[0]['before_record']], native[group[-1]['after_record']]
        delta = motion.vec(motion.sub(after['position'], before['position']))
        if any(delta):
            expected[head+1] = (group, before, after, delta)
    require(set(expected) == {r['frame'] for r in corrections} and len(expected) == len(corrections),
            'missing, extra, or duplicate native-backed correction')
    joined = []
    for correction in corrections:
        frame = correction['frame']; group, before, after, delta = expected[frame]
        require(correction['publication_us'] == by_frame[frame][0]['publication_us'] and
                before['cached_from_record'] == endpoints[frame-1]['record'] and
                after['query_end_us'] <= endpoints[frame]['query_begin_us'] <= correction['publication_us'],
                'correction is not cached old-H/repaired same-H before this publication')
        close(correction['native_delta'], delta, 'metadata delta includes ordinary motion or differs from native repair')
        close(correction['mapped_delta'], mapped(delta, correction['flipped']), 'actual perspective delta differs')
        require(motion.norm(delta) <= 8, 'unbounded accepted correction')
        joined.append(dict(frame=frame, revision=correction['revision'], native_revisions=[r['revision'] for r in group],
            before_record=before['record'], after_record=after['record'], native_delta=delta,
            publication_us=correction['publication_us']))
    consumed = []
    sampled_frames = set()
    previous_write = False
    maximum_interpolation = maximum_policy = 0.
    untouched = 0
    for record in records:
        if record['event'] == 'correction':
            require(record['frame'] not in sampled_frames and
                    record['publication_us'] <= by_frame[record['frame']][0]['sampled_us'],
                    'correction arrives after its first pose')
            consumed.append(record)
            continue
        row = record
        sampled_frames.add(row['frame'])
        require(all(c['frame'] <= row['frame'] for c in consumed), 'future correction observed before publication')
        active = [c for c in consumed if 0 <= row['sampled_us']-c['publication_us'] < DURATION_US]
        require(len(active) == row['pulses'] and len(active) <= 16 and
                sum(motion.norm(c['mapped_delta']) for c in active) <= 8+1e-6,
                'active pulse count/capacity/distance differs')
        alpha = 0. if row['elapsed'] == 0 or row['step'] == 0 else min(1., row['elapsed']/row['step'])
        require(abs(alpha-row['alpha']) <= 2**-22, 'actual alpha differs from original elapsed/step')
        interpolated = [a+(b-a)*row['alpha'] for a, b in zip(row['from'], row['to'])]
        maximum_interpolation = max(maximum_interpolation,
            close(row['raw'], interpolated, 'raw differs from original From/To/alpha interpolation'))
        offset = [0., 0., 0.]
        for pulse in active:
            age = (row['sampled_us']-pulse['publication_us'])/DURATION_US
            # Expanded cubic is independent of the runtime's factored formula.
            decay = 1-3*age*age+2*age*age*age
            weight = row['alpha'] if row['frame'] == pulse['frame'] else 1.
            offset = motion.sub(offset, [d*decay*weight for d in pulse['mapped_delta']])
        expected_pose = motion.vec(motion.add(row['raw'], offset))
        maximum_policy = max(maximum_policy,
            close(row['displayed'], expected_pose, 'displayed differs from independent cubic pulses'))
        close(row['output'], row['displayed'], 'shared output differs from displayed result')
        close(row['transform'], row['displayed'], 'actual Transform differs after joined write')
        nonzero = any(offset)
        require(row['wrote'] is (nonzero or previous_write), 'write/restore decision differs')
        previous_write = nonzero
        if not active:
            require(row['displayed'] == row['raw'] == row['output'] == row['transform'],
                    'ordinary/fully expired raw output changed')
            untouched += 1
    last_expiry = max(r['publication_us'] for r in corrections)+DURATION_US
    tail = [r for r in poses if r['sampled_us'] >= last_expiry]
    require(len(tail) >= 3 and tail[-1]['sampled_us']-tail[0]['sampled_us'] >= TAIL_US and
            tail[0]['sampled_us']-last_expiry <= 100_000 and
            all(b['sampled_us']-a['sampled_us'] <= 100_000 for a, b in zip(tail, tail[1:])) and
            all(r['pulses'] == 0 and r['displayed'] == r['raw'] for r in tail),
            'actual complete expiry plus150ms raw-equal tail missing')
    original = command['original_order']
    require(command['ordinal'] == original['ordinal'] == 2 and next_order['ordinal'] == 3 and
            all(original[k] == binding[k] for k in ('world', 'match', 'entity', 'unit_type', 'incarnation')) and
            original['originalCtor'] is True and original['physicalUI'] is False and
            command['assigned_frame'] != command['canonical_frame'], 'original turn2 command/retime differs')
    window = [r for r in poses if original['enqueue_sampled_us'] <= r['sampled_us'] < next_order['enqueue_sampled_us']]
    require(len(window) >= 5 and any(c['publication_us'] >= original['enqueue_sampled_us'] and
            c['publication_us'] < next_order['enqueue_sampled_us'] for c in corrections),
            'original turn2-before-turn3 correction window missing')
    direction = motion.sub(motion.vec(original['target']), motion.vec(original['origin']))
    require(motion.norm(direction) > 1, 'original turn direction is degenerate')
    direction = [x/motion.norm(direction) for x in direction]
    raw, displayed = backtrack(window, 'raw', direction), backtrack(window, 'displayed', direction)
    require(raw['amount'] > RAW_MINIMUM and displayed['amount'] < DISPLAY_MAXIMUM and
            displayed['amount'] < raw['amount'], 'actual large raw backtrack was not reduced below0.35units')
    require(untouched > len(tail), 'pre-correction unchanged ordinary samples missing')
    return dict(passed=True, binding=binding, lease=records[0]['lease'], flipped=records[0]['flipped'],
        poses=len(poses), corrections=joined, original_turn2={k: command[k] for k in
            ('sequence', 'action_sha256', 'assigned_frame', 'canonical_frame')},
        window=dict(begin_us=original['enqueue_sampled_us'], end_us=next_order['enqueue_sampled_us'],
                    samples=len(window), direction=direction), raw_backtrack=raw, displayed_backtrack=displayed,
        maximum_interpolation_residual=maximum_interpolation, maximum_policy_residual=maximum_policy,
        unchanged_samples=untouched, last_expiry_us=last_expiry,
        tail=dict(first_us=tail[0]['sampled_us'], last_us=tail[-1]['sampled_us'], samples=len(tail),
                  raw_equal=True, duration_us=tail[-1]['sampled_us']-tail[0]['sampled_us']))


def parent_gate(plan, report):
    """The controller's complete result is a prerequisite, never a visual substitute."""
    require(report.get('passed') is True and report.get('source_unchanged') is True and
            report.get('files_unchanged') is True and report.get('forced_cleanup') is False and
            report.get('cleanup_errors') == [] and
            type(plan.get('source_sha256')) is dict and plan['source_sha256'] and
            report.get('source_sha256_at_start') == report.get('source_sha256_at_finish') == plan.get('source_sha256') and
            input_delay.gate(plan, report),
            'full original native/wire/command/lifecycle gates did not pass unchanged')


def analyze(plan, report, run):
    from tools import prediction_position_trace as position, frame_timing
    from tools import verify_prediction_multiplayer as controller
    validate_plan(plan)
    require(plan.get('visual_correction') is True, 'explicit capture option missing')
    parent_gate(plan, report)
    run = Path(run); root = Path(plan['module_root']); inputs = {}
    def read(path):
        path = Path(path); require(path.stat().st_size <= 64*1024*1024, 'closed input exceeds bound')
        raw = path.read_bytes(); inputs[str(path)] = hashlib.sha256(raw).hexdigest()
        return raw
    def load(path):
        return json.loads(read(path))
    prepared = load(run.parent/'invocation.json')
    require(prepared == plan and inputs[str(run.parent/'invocation.json')] == report['invocation_sha256'],
            'actual invocation differs')
    for module in (motion, input_delay, position, frame_timing, controller, lifetime):
        name = 'tools/'+Path(module.__file__).name
        require(motion.sha(module.__file__) == plan['source_sha256'][name], 'consumed analyzer source differs')
    require(motion.sha(__file__) == plan['source_sha256']['tools/prediction_visual_correction.py'],
            'consumed visual analyzer source differs')
    witness = root/'local/prediction-checkpoint-20261110/position-capture17-clock01'
    reference = root/'local/prediction-runtime/movement74-input-delay/source-at-prepare/client_patch/src/frame_timing_audit.cpp'
    clock_samples = witness/'stdout.json'
    clock = motion.validate_clock(load(witness/'verification.json'), load(clock_samples),
        samples_sha256=inputs[str(clock_samples)], python_sha256=plan['files']['python']['sha256'],
        reference_source=read(reference),
        consumed_source=read(run.parent/'source-at-prepare/client_patch/src/frame_timing_audit.cpp'))
    native_path = run/'native-positions-0.jsonl'; read(native_path)
    native = position.read_trace(native_path)
    bindings = [w['binding'] for w in report['native_position_trace']['worlds']]
    native_analysis = position.analyze(native, identity=dict(id=74, type=1, army=0), worlds=bindings)
    require(native_analysis['passed'], 'subject native trace did not qualify both worlds')
    subject_log = read(run/'native-0.log').decode('utf-8')
    observed = rows(subject_log)
    peer = read(run/'native-1.log').decode('utf-8')
    require(PREFIX not in peer and 'Prediction visual correction failed:' not in peer,
            'unrequested peer observation or peer visual failure')
    require({(r['world'], r['match']) for r in observed} == {(b['world'], b['match']) for b in bindings},
            'observations contain missing/extra worlds')
    matches = [b['match'] for b in bindings]
    pid = load(run/'client-0-process.json')['pid']; timing_path = run/f'frame-timing-{pid}.tsv'; read(timing_path)
    publications = controller.publication_segments(frame_timing.read_trace(timing_path), matches)
    transitions = report['transition_orders']['episodes']
    require([e['match'] for e in transitions] == matches, 'turn/native world ordering differs')
    worlds = []
    for traced, turn in zip(native_analysis['worlds'], transitions):
        binding = traced['binding']
        records = [r for r in observed if r['world'] == binding['world']]
        worlds.append(evaluate_world(binding=binding, records=records, native=native,
            episodes=traced['episodes'], publications=publications[binding['match']],
            command=turn['orders'][0], next_order=turn['orders'][1]['original_order']))
    retirement = lifetime.evaluate([subject_log,peer],matches,visual_records=observed,
        pids=[pid,load(run/'client-1-process.json')['pid']])
    retirement['source_sha256'] = {}
    for name in ('client_patch/src/prediction_visual_correction.cpp',
                 'client_patch/src/prediction_visual_lifetime.hpp','client_patch/src/prediction_movement.cpp'):
        raw = read(run.parent/'source-at-prepare'/name)
        digest = hashlib.sha256(raw).hexdigest()
        require(digest == plan['source_sha256'][name], 'consumed visual retirement producer differs')
        retirement['source_sha256'][name] = digest
    require(len(worlds) == 2 and all(motion.sha(path) == digest for path, digest in inputs.items()),
            'two unchanged closed worlds required')
    return dict(schema=1, passed=True, parent_gates_passed=True, file_only=True,
        full_feature_accepted=False, duration_us=DURATION_US, required_tail_us=TAIL_US,
        raw_minimum=RAW_MINIMUM, displayed_maximum=DISPLAY_MAXIMUM, worlds=worlds,
        clock_witness=clock, input_sha256=inputs, lifetime=retirement,
        scope='Actual joined raw/alpha/shared-output/Transform and native-backed independent900ms pulses; full parent gates required',
        limitations=['Scripted selected own actor only; no physical/Internet comfort acceptance.',
            'No forced retirement/type change, camera/input-reader or performance acceptance.'])


def finalize(plan, report, run):
    if not plan.get('visual_correction'):
        return
    parent_passed = report.get('passed') is True
    try:
        report['visual_correction'] = analyze(plan, report, run)
    except (AssertionError, KeyError, TypeError, ValueError, AttributeError, IndexError, OSError, OverflowError) as error:
        report['visual_correction'] = dict(passed=False, error=repr(error), parent_gates_passed=parent_passed,
            full_feature_accepted=False, scope='Actual Unity visual correction remains unqualified')
    report['passed'] = parent_passed and report['visual_correction'].get('passed') is True
