"""Closed-file correction/renderer decomposition; never loads a native engine.

The native and publication clocks are joined only under the caller's retained
same-interpreter QPC witness. Segment projection describes sampled endpoints,
not Unity's unsampled interpolation clock, display latency, or visual comfort.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import struct


class EvidenceError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise EvidenceError('correction motion: ' + reason)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integer(value, low=0):
    return type(value) is int and low <= value < 2**64


def vec(values):
    require(type(values) is list and len(values) == 3 and
            all(type(x) in (int, float) and math.isfinite(x) for x in values), 'finite Vec3 required')
    try:
        result = list(struct.unpack('<fff', struct.pack('<fff', *values)))
    except (OverflowError, struct.error) as error:
        raise EvidenceError('correction motion: Vec3 is outside Single') from error
    require(all(math.isfinite(x) for x in result), 'nonfinite Single position')
    return result


def sub(a, b):
    return [x-y for x, y in zip(a, b)]


def add(a, b):
    return [x+y for x, y in zip(a, b)]


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def precision_bound(points):
    """Eight actual float32 ULPs per coordinate; report this numerical envelope."""
    ulps = []
    for point in points:
        for value in point:
            bits, = struct.unpack('<I', struct.pack('<f', abs(value)))
            require(bits < 0x7f7fffff, 'no finite adjacent Single for precision bound')
            following, = struct.unpack('<f', struct.pack('<I', bits+1))
            ulps.append(following-abs(value))
    return 8 * math.sqrt(3) * max(ulps)


def _timestamp_function(text):
    text = text.replace('\r\n', '\n')
    start = text.index('static bool timestampMicros(uint64_t& output) {')
    depth = 0
    for end in range(text.index('{', start), len(text)):
        depth += (text[end] == '{') - (text[end] == '}')
        if depth == 0:
            return text[start:end+1]
    raise EvidenceError('correction motion: incomplete timestampMicros source')


def validate_clock(receipt, samples, *, samples_sha256, python_sha256,
                   reference_source, consumed_source):
    """Validate retained real samples and the exact consumed conversion function."""
    require(receipt.get('passed') is True and receipt.get('samples') == 32 and
            receipt.get('natural_exit') == 0 and receipt.get('forced') is False and
            receipt.get('job', {}).get('active') == receipt.get('job', {}).get('terminated') == 0,
            'retained clock process did not close naturally')
    require(receipt.get('python_sha256') == python_sha256 and
            receipt.get('stdout_sha256') == samples_sha256 and
            hashlib.sha256(reference_source).hexdigest() == receipt.get('cpp_source_sha256'),
            'clock interpreter/samples/reference source pin differs')
    require(_timestamp_function(reference_source.decode()) == _timestamp_function(consumed_source.decode()),
            'consumed QPC conversion function differs from retained witness')
    frequency = samples.get('frequency'); rows = samples.get('rows')
    require(integer(frequency, 1) and type(rows) is list and len(rows) == 32,
            'clock frequency/sample count differs')
    previous = -1
    for row in rows:
        require(all(integer(row.get(k)) for k in ('raw_qpc', 'cpp_us', 'begin_ns', 'end_ns')) and
                row['begin_ns'] <= row['end_ns'], 'clock sample is malformed')
        converted = (row['raw_qpc']//frequency)*1_000_000 + (row['raw_qpc']%frequency)*1_000_000//frequency
        require(converted == row['cpp_us'] and previous <= row['begin_ns'] and
                row['begin_ns']//1000-1 <= converted <= row['end_ns']//1000+1,
                'retained QPC/perf-counter bracket differs')
        previous = row['end_ns']
    return dict(passed=True, samples=32, tolerance_us=1,
                reference_source_sha256=receipt['cpp_source_sha256'],
                consumed_source_sha256=hashlib.sha256(consumed_source).hexdigest(),
                conversion_function_identical=True,
                scope='Same-host retained interpreter perf_counter/QPC conversion; not Unity cachedTime or pure-native latency')


def _promotion(pair, native, workers, canonical, journal, command):
    """Join pre-accounting same-H counters to the completed confirmed group."""
    before, after = native[pair['before_record']], native[pair['after_record']]
    D, H = pair['first_divergent_frame'], pair['physical_head']
    S, C = command['assigned_frame'], command['canonical_frame']
    require(min(S, C) <= D <= max(S, C), 'same-head divergence is outside this command retime')
    groups = {}
    for index, row in enumerate(workers):
        if row['world'] == after['world']:
            groups.setdefault(row['confirmed_frontier'], []).append((index, row))
    candidates = []
    for frontier, group in groups.items():
        last = group[-1][1]
        replay = sum(r['replayed_frames_delta'] for _, r in group)
        if (replay > 0 and last['corrections'] == after['corrections']+1 and
                last['replayed_frames_total'] == after['replayed_frames']+1 and
                D in [r['frame'] for _, r in group]):
            candidates.append((frontier, group, replay))
    require(len(candidates) == 1, 'same-H replay lacks one exact pre-accounting promotion group')
    frontier, group, replay = candidates[0]
    frames = [r['frame'] for _, r in group]
    require(frames == list(range(frames[0], frontier+1)) and replay >= H-D+1 and
            sum(r['corrections_delta'] for _, r in group) > 0 and
            all(canonical.get(str(r['frame'])) == r['parsed_state_sha256'] for _, r in group),
            'promotion group native parity/contiguity/replay differs')
    actions = [(r['frame'], slot, hashlib.sha256(a).hexdigest()) for r in journal if r['frame'] in frames
               for slot, values in r['players'].items() for a in values]
    expected = [(C, 0, command['action_sha256'])] if C in frames else []
    require(actions == expected, 'another command could cause selected replay')
    require(after['query_begin_us'] >= command['original_order']['enqueue_sampled_us'] and
            before['query_end_us'] <= after['query_begin_us'], 'replay/cache query chronology differs')
    return dict(first_divergent_frame=D, physical_head=H, confirmed_frontier=frontier,
                row_indices=[i for i, _ in group], frames=frames, replayed_delta=replay,
                corrections=group[-1][1]['corrections'],
                replayed_frames_total=group[-1][1]['replayed_frames_total'], canonical_actions=actions,
                native65_timestamp_for_empty_frame=None,
                timing_scope='Source-ordered actual authority enqueue before before_next_frame replay; empty-frame TSV has no timestamp')


def decompose_world(*, binding, native, episodes, publications, poses, workers,
                    canonical, journal, command, next_enqueue_us, minimum_backtrack):
    """Pure actual-record core. It does not synthesize missing native endpoints."""
    world, match = binding['world'], binding['match']
    original = command['original_order']
    require(command['ordinal'] == original['ordinal'] == 2 and command['assigned_frame'] != command['canonical_frame'] and
            (original['world'], original['match'], original['entity'], original['unit_type'], original['incarnation']) ==
            (world, match, binding['entity'], binding['unit_type'], binding['incarnation']) and
            original['originalCtor'] is True and original['physicalUI'] is False and original['queueDelta'] == 1,
            'turn2 constructor/actor/retime binding differs')
    require(type(minimum_backtrack) in (int, float) and math.isfinite(minimum_backtrack) and minimum_backtrack > 0,
            'invalid minimum backtrack')
    relevant = [e for e in episodes if min(command['assigned_frame'], command['canonical_frame']) <=
                e['first_divergent_frame'] <= max(command['assigned_frame'], command['canonical_frame'])]
    require(relevant and all(e['qualified'] for e in relevant), 'command same-H episode is missing/incomplete')
    require(any(e['changed'] for e in relevant), 'command has no changed speculative head')
    actual = [n for n in native if n['world'] == world and n['event'] != 'before_restore_cached_head' and n['status'] == 'present']
    endpoints = {}
    for publication in publications:
        candidates = [n for n in actual if n['frame'] == publication['frame'] and n['query_end_us'] <= publication['qpc_us']]
        if candidates:
            chosen = max(candidates, key=lambda n: n['query_end_us'])
            endpoints[publication['frame']] = dict(position=vec(chosen['position']), native_record=chosen['record'],
                revision=chosen['revision'], query_begin_us=chosen['query_begin_us'], query_end_us=chosen['query_end_us'],
                publication_qpc_us=publication['qpc_us'])
    corrections = []
    for pair in relevant:
        H = pair['physical_head']; before, after = native[pair['before_record']], native[pair['after_record']]
        require(H in endpoints and H+1 in endpoints, 'corrected head lacks published native endpoints')
        old, following = endpoints[H], endpoints[H+1]
        require(old['native_record'] == before['cached_from_record'] and following['revision'] == pair['revision'] and
                after['query_end_us'] <= following['publication_qpc_us'], 'published endpoints are not this cached/replayed head')
        delta = sub(vec(after['position']), vec(before['position']))
        ordinary = sub(following['position'], vec(after['position']))
        change = sub(following['position'], old['position'])
        require(norm(sub(change, add(delta, ordinary))) < 1e-12, 'endpoint correction+ordinary-step equation fails')
        corrections.append(dict(before_cached=before, after_same_head=after,
            promotion=_promotion(pair, native, workers, canonical, journal, command),
            native_correction_delta=delta, native_correction_magnitude=norm(delta),
            ordinary_next_motion=ordinary, ordinary_next_motion_magnitude=norm(ordinary),
            published_endpoint_delta=change, published_endpoint_magnitude=norm(change),
            equation='new(H+1)-old(H)=[corrected(H)-old(H)]+[new(H+1)-corrected(H)]'))
    lower, upper = min(e['physical_head'] for e in relevant)-2, max(e['physical_head'] for e in relevant)+4
    selected = [p for p in poses if p.get('event') == 'transform' and p.get('match') == match and
                lower <= p['presented_frame'] <= upper and
                original['enqueue_sampled_us'] <= p['sampled_us'] < next_enqueue_us]
    require(len(selected) >= 3 and any(p['presented_frame'] <= lower+2 for p in selected) and
            any(p['presented_frame'] >= upper-2 for p in selected), 'near-correction Transform coverage incomplete')
    previous_time = -1; envelope = []; points = []
    for p in selected:
        require((p['world'], p['entity'], p['unit_type'], p['incarnation']) ==
                (world, binding['entity'], binding['unit_type'], binding['incarnation']) and
                p['source'] == 'UnityEngine.Transform.get_position' and p['jobsJoined'] is True and
                integer(p['sampled_us'], 1) and p['sampled_us'] > previous_time and
                p['completed_frame'] in (p['presented_frame'], p['presented_frame']+1),
                'Transform lease/frame/clock/source differs')
        P = p['presented_frame']
        require(P-1 in endpoints and P in endpoints, 'Transform lacks exact adjacent native frame endpoints')
        a, b = endpoints[P-1], endpoints[P]
        require(a['publication_qpc_us'] < b['publication_qpc_us'] <= p['sampled_us'] and
                (P+1 not in endpoints or p['sampled_us'] <= endpoints[P+1]['publication_qpc_us']),
                'Transform presented-frame/publication QPC ordering differs')
        point = vec(p['position']); vector = sub(b['position'], a['position']); length2 = dot(vector, vector)
        alpha = dot(sub(point, a['position']), vector)/length2 if length2 else 0
        projection = add(a['position'], [alpha*x for x in vector])
        clamped = add(a['position'], [max(0, min(1, alpha))*x for x in vector])
        envelope.append(dict(sampled_us=p['sampled_us'], presented_frame=P, completed_frame=p['completed_frame'],
            position=point, alpha=alpha, perpendicular_residual=norm(sub(point, projection)),
            outside_segment_distance=norm(sub(point, clamped)), endpoint_records=[a['native_record'], b['native_record']],
            publication_qpc_us=b['publication_qpc_us']))
        points += [point, a['position'], b['position']]; previous_time = p['sampled_us']
    direction = sub(vec(original['target']), vec(original['origin']))
    require(norm(direction) > 1, 'turn2 new direction is degenerate')
    direction = [x/norm(direction) for x in direction]
    peak = None; best = (-1, None, None)
    for p in selected:
        coordinate = dot(vec(p['position']), direction)
        if peak is None or coordinate > peak[0]:
            peak = coordinate, p
        if peak[0]-coordinate > best[0]:
            best = peak[0]-coordinate, peak[1], p
    bound = precision_bound(points)
    require(bound < minimum_backtrack/100, 'Single precision is too coarse for amplitude classification')
    outside = max(e['outside_segment_distance'] for e in envelope)
    contained = outside <= bound
    return dict(binding=binding, command={k: command[k] for k in ('sequence', 'action_sha256', 'assigned_frame',
        'canonical_frame', 'native67_tick_ms', 'native72_send_tick_ms')}, corrections=corrections,
        selected_published_endpoints={str(f): endpoints[f] for f in range(lower-1, upper+1) if f in endpoints},
        envelope=dict(points=len(envelope), precision_bound=bound, maximum_outside_segment_distance=outside,
            maximum_perpendicular_residual=max(e['perpendicular_residual'] for e in envelope), rows=envelope),
        render_backtrack=dict(amount=best[0], from_sample=best[1], to_sample=best[2],
            duration_ms=(best[2]['sampled_us']-best[1]['sampled_us'])/1000,
            direction=direction, threshold=minimum_backtrack, exceeds_threshold=best[0] > minimum_backtrack),
        decomposition_complete=True, renderer_amplification_observed=not contained,
        renderer_classification='contained_in_published_native_segments' if contained else 'outside_published_native_segments',
        attribution_passed=contained)


def summarize(worlds, *, minimum_backtrack):
    require(len(worlds) == 2 and len({w['binding']['world'] for w in worlds}) == 2 and
            len({w['binding']['match'] for w in worlds}) == 2, 'two distinct bound worlds required')
    large = any(w['render_backtrack']['amount'] > minimum_backtrack for w in worlds)
    complete = all(w['decomposition_complete'] for w in worlds)
    return dict(schema=1, passed=large and complete and all(w['attribution_passed'] for w in worlds),
        file_only=True, native_executed=False, full_feature_accepted=False,
        minimum_backtrack=minimum_backtrack, large_event_reproduced=large, decomposition_complete=complete,
        worlds=worlds, scope='Sampled render peak-to-trough backtrack and corrected native published-endpoint decomposition; no smoothing or physical comfort acceptance',
        limitations=['Native brackets include existing Make/Get plus decode; cached-before times are original queries.',
            'Post-original publication timestamps are after return/bookkeeping, not the internal counter write.',
            'Unity interpolation alpha/time is not sampled; segment projection is descriptive.',
            'Outside-segment residual requires further interpolation evidence; it alone does not identify an engine defect.',
            'No retrospective attribution of Portable16 and no decrypted TLS chunk-to-command mapping.'])


def bind_replay_authority(correction, *, receipt, bridge, arrival, payload_sha256):
    """Real65 has no TSV time; use its exact payload and the arrival QPC separately."""
    D = correction['promotion']['first_divergent_frame']
    after = correction['after_same_head']
    require(receipt['frame'] == bridge['frame'] == arrival['frame'] == D and
            receipt['sha256'] == bridge['payload_sha256'] == payload_sha256 and
            receipt['sim'] >= D and arrival['event'] == 'arrival' and
            integer(arrival.get('qpc_us'), 1) and arrival['qpc_us'] <= after['query_begin_us'],
            'actual divergent-frame65/bridge/arrival-QPC does not precede replay')
    return dict(native65=receipt, native65_tick_ms=None, raw_bridge=bridge,
                arrival_qpc_us=arrival['qpc_us'], query_begin_us=after['query_begin_us'],
                scope='Actual65 TSV payload plus separate original arrival QPC; no fabricated65 TSV timestamp')


def read_submitted_bodies(folder, *, read=None):
    """Read exact retained raw72 payloads, before canonical identity normalization."""
    from server.game_data import decode_player_input
    read = read or (lambda path: path.read_bytes())
    paths = sorted(Path(folder).glob('*.pb'))
    require(0 < len(paths) <= 4096, 'retained submitted-body count differs')
    result = {}
    for path in paths:
        match = re.fullmatch(r'([a-f0-9]{32})-([01])-([1-9][0-9]*)\.pb', path.name)
        require(match is not None and path.is_file(), 'retained submitted-body filename differs')
        match_id, slot, sequence = match.groups(); slot, sequence = int(slot), int(sequence)
        require(integer(sequence, 1), 'retained submitted-body sequence overflow')
        body = read(path); decoded = decode_player_input(body); identity = decoded['identity']
        require(identity['player_id'] == slot+1 and identity['is_aliased'] is True and
                identity['ai_profile_id'] == 0 and decoded['actions'], 'raw sender body owner/action differs')
        key = match_id, slot, sequence
        require(key not in result, 'duplicate retained raw sender-body key')
        result[key] = body
    return result


def analyze_run(output: Path, *, minimum_backtrack=0.75, clock_receipt: Path,
                clock_samples: Path, clock_reference_source: Path, delay_proof: dict) -> dict:
    """Read a naturally closed new controlled run, returning evidence without writes."""
    # Import only inside the closed-file entry point; no controller import cycle.
    from tools import frame_timing, prediction_position_trace as position
    from tools import prediction_input_delay as input_delay
    from tools import verify_prediction_multiplayer as controller
    from tools import verify_original_command_scheduling as scheduling
    from tools.verify_original_command_scheduling import read_journal
    from server.game_data import decode_player_input

    output = Path(output); run = output/'run'; inputs = {}
    def read(path):
        path = Path(path); raw = path.read_bytes()
        require(len(raw) <= 64*1024*1024, 'input exceeds closed-file bound')
        inputs[str(path)] = hashlib.sha256(raw).hexdigest()
        return raw
    def load(path):
        return json.loads(read(path))
    plan = load(output/'invocation.json'); report = load(run/'verification.json')
    require(report['passed'] is True and report['source_unchanged'] is report['files_unchanged'] is True and
            report['forced_cleanup'] is False and not report['cleanup_errors'] and
            report['source_sha256_at_start'] == report['source_sha256_at_finish'] == plan['source_sha256'] and
            report['invocation_sha256'] == inputs[str(output/'invocation.json')], 'parent command/state/lifetime run did not pass unchanged')
    require(delay_proof == report.get('transition_input_delay') and input_delay.gate(plan, report),
            'actual controlled-input-delay proof is absent/incomplete')
    consumed = {}
    names = ('client_patch/src/frame_timing_audit.cpp', 'client_patch/src/prediction_movement_smoke.cpp',
        'client_patch/src/prediction_worker.cpp', 'client_patch/prediction_worker/native.py',
        'client_patch/src/online_presentation.cpp', 'client_patch/prediction_worker/checkpoint.py',
        'client_patch/prediction_worker/commands.py', 'client_patch/prediction_worker/prediction.py',
        'client_patch/prediction_worker/observation.py')
    for name in names:
        consumed[name] = read(output/'source-at-prepare'/name)
        require(hashlib.sha256(consumed[name]).hexdigest() == plan['source_sha256'][name], 'consumed producer source pin differs')
    # This entry point is for the NEW frozen capture. Older captures can use
    # the pure core, without pretending today's changed parser was consumed.
    for module in (frame_timing, position, input_delay, controller, scheduling):
        path = Path(module.__file__); name = 'tools/'+path.name
        require(sha(path) == plan['source_sha256'][name], 'current file-only parser differs from prepared source')
        read(path)
    clock = validate_clock(load(clock_receipt), load(clock_samples), samples_sha256=inputs[str(Path(clock_samples))],
        python_sha256=plan['files']['python']['sha256'], reference_source=read(clock_reference_source),
        consumed_source=consumed['client_patch/src/frame_timing_audit.cpp'])
    raw_native = read(run/'native-positions-0.jsonl'); native = position.read_trace(run/'native-positions-0.jsonl')
    require(hashlib.sha256(raw_native).hexdigest() == sha(run/'native-positions-0.jsonl'), 'native trace changed during read')
    bindings = [w['binding'] for w in report['native_position_trace']['worlds']]
    require(len(bindings) == 2, 'native trace external bindings missing')
    analysis = position.analyze(native, identity=dict(id=bindings[0]['entity'], type=bindings[0]['unit_type'], army=bindings[0]['army']), worlds=bindings)
    require(analysis['passed'], 'native trace lacks changed qualified heads in both worlds')
    events = [json.loads(line) for line in read(run/'events.jsonl').splitlines()]
    matches = [e['match'] for e in events if e['event'] == 'match_created']
    log = read(run/'native-0.log').decode('utf-8'); poses = controller.feel_rows(log)
    require(poses == load(run/'movement-feel-0.json'), 'saved FEEL rows differ from actual log')
    pid = load(run/'client-0-process.json')['pid']; timing = run/f'frame-timing-{pid}.tsv'
    read(timing); timing_rows = frame_timing.read_trace(timing)
    pubs = controller.publication_segments(timing_rows, matches)
    worker_path = run/'canonical-state-0.jsonl'; read(worker_path); workers = controller.read_worker_states(worker_path)
    canonical = load(run/'server-states.json'); transitions = report['transition_orders']['episodes']
    bridges = load(run/'bridge-wire-0.json'); authority_rows = controller.authority_rows(log)
    bodies = read_submitted_bodies(run/'submitted-batches', read=read)
    require([b['match'] for b in bindings] == matches == [e['match'] for e in transitions] ==
            [e['match'] for e in delay_proof['worlds']], 'world/match/controlled-turn ordering differs')
    worlds = []
    for traced, transition, delayed in zip(analysis['worlds'], transitions, delay_proof['worlds']):
        binding = traced['binding']; match = binding['match']; command = transition['orders'][0]
        require(all(command[k] == delayed[k] for k in ('sequence', 'action_sha256', 'assigned_frame', 'canonical_frame')) and
                binding['world'] == delayed['world'], 'controlled delay does not bind this actual turn2')
        count = sum(e['event'] == 'frame_queued' and e.get('match') == match for e in events)
        path = run/'matches'/match/'frames.bin'; raw = read(path); journal = read_journal(run, match, count)
        cursor = 0
        for frame in journal:
            require(cursor+4 <= len(raw), 'journal header truncated')
            length, = struct.unpack_from('<I', raw, cursor); cursor += 4
            payload = raw[cursor:cursor+length]; cursor += length
            require(len(payload) == length, 'journal payload truncated')
        require(cursor == len(raw), 'journal has extra unbound frames')
        actual_binding = controller.transition_order_binding(log, command['original_order'], slot=0,
            raw_bodies=bodies, journal=journal, commits=events)
        require(all(command[k] == value for k, value in actual_binding.items()), 'original ctor/67/72/journal turn2 differs')
        require(len(decode_player_input(bodies[match, 0, command['sequence']])['actions']) == 1,
                'turn2 immutable body includes another action')
        C = command['canonical_frame']
        authority = [r for r in authority_rows if r['match'] == match and r['world'] == binding['world'] and r['frame'] == C]
        bridge = [r for r in bridges if r['match'] == match and r['frame'] == C]
        payloads = {e['frame']: e['frame_payload_sha256'] for e in events if e.get('event') == 'frame_queued' and e.get('match') == match}
        require(len(authority) == len(bridge) == 1 and authority[0] == command['native65'] and
                bridge[0] == command['raw_bridge'] and
                authority[0]['wire_sha256'] == bridge[0]['payload_sha256'] == payloads[C] and
                bridge[0]['received_tick_ms'] <= authority[0]['tick_ms'], 'final own command native65/bridge differs')
        # Final canonical group and every+20 continuation still match actual full native hashes.
        for index in command['promotion_group_row_indices'] + command['continuation_row_indices']:
            row = workers[index]
            require(row['world'] == binding['world'] and row['parsed_state_sha256'] == canonical[match][str(row['frame'])],
                    'turn2 final group/continuation full-state parity differs')
        require(len(command['continuation_row_indices']) == 20 and
                [workers[i]['frame'] for i in command['continuation_row_indices']] ==
                list(range(command['confirmed_state_frame']+1, command['confirmed_state_frame']+21)),
                'turn2 twenty canonical continuations missing')
        next_order = transition['orders'][1]['original_order']
        require(next_order['ordinal'] == 3, 'turn3 capture boundary missing')
        result = decompose_world(binding=binding, native=native, episodes=traced['episodes'],
            publications=pubs[match], poses=poses, workers=workers, canonical=canonical[match], journal=journal,
            command=command, next_enqueue_us=next_order['enqueue_sampled_us'], minimum_backtrack=minimum_backtrack)
        receipt_path = run/f'dedicated-receipts-{pid}-{match}.tsv'; read(receipt_path)
        receipts = controller.read_native_receipts(receipt_path, pid=pid, match=match)
        # Frame0 arrivals delimit the two original worlds in the shared trace.
        starts = [i for i, r in enumerate(timing_rows) if r['event'] == 'arrival' and r['frame'] == 0]
        index = matches.index(match); segment = timing_rows[starts[index]: starts[index+1] if index+1 < len(starts) else len(timing_rows)]
        for correction in result['corrections']:
            D = correction['promotion']['first_divergent_frame']
            received = [r for r in receipts if r['frame'] == D]
            wire = [r for r in bridges if r['match'] == match and r['frame'] == D]
            arrival = [r for r in segment if r['event'] == 'arrival' and r['frame'] == D]
            require(len(received) == len(wire) == len(arrival) == 1, 'divergent-frame actual65/bridge/arrival missing')
            correction['authority'] = bind_replay_authority(correction, receipt=received[0], bridge=wire[0],
                arrival=arrival[0], payload_sha256=payloads[D])
            if D < C:
                require(received[0]['actions'] == 0, 'early divergent authority is not empty')
            at = max(workers[i]['tick_ms'] for i in correction['promotion']['row_indices'])
            registrations = re.findall(r'Movement local batch registered: sequence=(\d+) speculativeFrame=(\d+) '
                r'tick=(\d+) match='+re.escape(match)+r'(?:\s|$)', log)
            pending = []
            for sequence, _, tick in registrations:
                if int(tick) > at:
                    continue
                commits = [e for e in events if e.get('event') == 'command_batch_committed' and
                           e.get('match') == match and e.get('slot') == 0 and e.get('sequence') == int(sequence)]
                require(len(commits) == 1, 'registered command lacks exact canonical disposition')
                if commits[0]['frame'] > correction['promotion']['confirmed_frontier']:
                    pending.append(int(sequence))
            require(pending == ([command['sequence']] if C > correction['promotion']['confirmed_frontier'] else []),
                    'another pending local command could cause selected replay')
        result['final_canonical_authority'] = authority[0]
        worlds.append(result)
    result = summarize(worlds, minimum_backtrack=minimum_backtrack)
    result.update(clock_witness=clock, original_report_sha256=inputs[str(run/'verification.json')],
                  controlled_input_delay=delay_proof, input_sha256=inputs,
                  analyzer_sha256=sha(__file__))
    require(all(sha(path) == digest for path, digest in inputs.items()), 'a consumed input changed during analysis')
    return result
