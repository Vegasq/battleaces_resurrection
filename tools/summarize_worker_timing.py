"""Validate and summarize an owned large-army worker profile, without native calls.

Requires the completed benchmark, exact input journal, frame trace and profiler
sidecar. An optional unprofiled control must reproduce every input/observable
state. This is diagnostic attribution, not a network/playability acceptance test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct

PHASES = ('setup', 'movement', 'combat')
PROFILE_SOURCES = ('tools/profile_worker_timing.py', 'server/worker_client.py', 'server/simulation_worker.py',
                   'server/native_simulation.py', 'server/native_ai.py', 'server/worker_ai.py')
MAX_FRAMES = 32000
MAX_FRAME_BYTES = 4 * 65536 + 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def valid_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def read_json(path, limit=128 * 1024 * 1024):
    require(path.stat().st_size <= limit, f'JSON evidence exceeds bound: {path.name}')
    raw = path.read_bytes()
    def reject(value):
        raise ValueError('nonfinite JSON evidence')
    return json.loads(raw, parse_constant=reject), sha(raw)


def stats(values):
    ordered = sorted(values)
    if not ordered:
        return {'count': 0}
    require(all(finite(v) for v in ordered), 'nonfinite metric')
    pick = lambda p: ordered[max(0, math.ceil(len(ordered)*p)-1)]
    return dict(count=len(ordered), minimum=ordered[0], mean=statistics.fmean(ordered),
                p50=pick(.5), p95=pick(.95), p99=pick(.99), maximum=ordered[-1])


def load_benchmark(directory):
    directory = Path(directory)
    report, report_sha = read_json(directory/'benchmark.json')
    require(report.get('passed') is True and report.get('native_qualified') is True,
            'benchmark did not qualify a native run')
    require(report.get('source_unchanged') is True and report.get('source_at_start') == report.get('source_at_finish'),
            'benchmark source changed during run')
    require(isinstance(report.get('source_at_start'), dict) and all(valid_sha(v) for v in report['source_at_start'].values()),
            'benchmark source hashes missing/invalid')
    cleanup = report.get('cleanup', {})
    require(type(cleanup.get('exit_code')) is int and cleanup['exit_code'] == 0 and cleanup.get('failure') is None
            and cleanup.get('stderr_thread_closed') is True and cleanup.get('io_threads_closed') is True,
            'benchmark worker cleanup incomplete')
    require(type(report.get('frames')) is int and 1 <= report['frames'] <= MAX_FRAMES, 'benchmark frame count invalid')
    for field in ('bootstrap_sha256', 'simulation_sha256', 'asset_manifest_sha256', 'input_journal_sha256'):
        require(valid_sha(report.get(field)), f'benchmark {field} missing/invalid')
    trace = directory/'frames.jsonl'
    require(trace.stat().st_size <= 128 * 1024 * 1024, 'frame trace exceeds bound')
    raw = trace.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    require(len(rows) == report['frames'], 'frame trace truncated or has extra rows')
    payload_lengths = []
    journal_digest = hashlib.sha256()
    with (directory/'frames.bin').open('rb') as stream:
        for number, row in enumerate(rows):
            require(type(row.get('frame')) is int and row['frame'] == number and row.get('phase') in PHASES,
                    'frame trace order/phase invalid')
            require(valid_sha(row.get('input_sha256')) and valid_sha(row.get('state_sha256')), 'frame digest invalid')
            require(finite(row.get('step_rpc_ms')) and row['step_rpc_ms'] >= 0, 'frame RPC timing invalid')
            header = stream.read(4)
            require(len(header) == 4, 'input journal truncated')
            length = struct.unpack('<I', header)[0]
            require(1 <= length <= MAX_FRAME_BYTES, 'journal frame exceeds bound')
            payload = stream.read(length)
            require(len(payload) == length and sha(payload) == row['input_sha256'], 'journal/frame digest differs')
            journal_digest.update(header); journal_digest.update(payload)
            payload_lengths.append(length)
        require(not stream.read(1), 'input journal has extra frames')
    require(journal_digest.hexdigest() == report['input_journal_sha256'], 'input journal SHA differs')
    require(set(row['phase'] for row in rows) == set(PHASES), 'workload phases missing')
    transitions = [rows[0]['phase']] + [row['phase'] for previous, row in zip(rows, rows[1:])
                                       if row['phase'] != previous['phase']]
    require(transitions == list(PHASES), 'workload phases reordered or interleaved')
    require(all(report.get('phases', {}).get(phase, {}).get('frames') == sum(row['phase'] == phase for row in rows)
                for phase in PHASES), 'phase frame totals differ from benchmark')
    return dict(report=report, rows=rows, payload_lengths=payload_lengths,
                evidence_sha256={'benchmark.json': report_sha, 'frames.jsonl': sha(raw),
                                 'frames.bin': journal_digest.hexdigest()})


def validate_profile(profile, benchmark, profile_sha):
    report, frames = benchmark['report'], benchmark['rows']
    require(profile.get('schema') == 1 and profile.get('completed') is True
            and type(profile.get('exit_code')) is int and profile['exit_code'] == 0
            and profile.get('failure') is None and profile.get('dropped_records') == 0
            and profile.get('synthetic_test_backend') is False, 'worker profile incomplete/failed/synthetic')
    require(report.get('profiled') is True and report.get('worker_profile_sha256') == profile_sha,
            'profile sidecar is not bound to this benchmark')
    require(type(profile.get('pid')) is int and profile['pid'] > 0 and profile['pid'] == report.get('worker_pid'),
            'profile worker PID differs')
    sources = profile.get('source_sha256', {})
    require(isinstance(sources, dict) and set(sources) == set(PROFILE_SOURCES)
            and all(valid_sha(sources[name]) and sources[name] == report['source_at_start'].get(name)
                    for name in PROFILE_SOURCES), 'profile source binding differs')
    records = profile.get('records')
    require(isinstance(records, list) and 3 <= len(records) <= 20000, 'profile records absent/outside bound')
    require(records[0].get('operation') == 'CREATE' and records[0].get('frame') == -1
            and records[-1].get('operation') == 'CLOSE' and records[-1].get('frame') == len(frames)-1,
            'profile lacks exact CREATE/CLOSE boundaries')
    seen_steps, seen_bots = [], []
    for request_id, row in enumerate(records, 1):
        require(type(row.get('request_id')) is int and row['request_id'] == request_id
                and row.get('replied') is True and row.get('response_error') is False,
                'profile request coverage is discontinuous or failed')
        operation = row.get('operation')
        require(operation in ('CREATE', 'STEP', 'BOT_INPUT', 'CLOSE'), 'unexpected benchmark operation')
        if operation in ('CREATE', 'CLOSE'):
            require(request_id == (1 if operation == 'CREATE' else len(records)), 'duplicate profile lifecycle operation')
        else:
            number = row.get('frame')
            require(type(number) is int and 0 <= number < len(frames), 'profile frame outside benchmark')
            if operation == 'STEP':
                seen_steps.append(number)
                require(row.get('request_payload_bytes') == benchmark['payload_lengths'][number],
                        'profile input size differs from replay journal')
            else:
                seen_bots.append(number)
                require(row.get('request_payload_bytes') == 0 and number == len(seen_steps), 'bot input coverage/order differs')
        for name in ('active_wall_ns', 'active_thread_cpu_ns', 'active_process_cpu_ns', 'receive_wall_ns',
                     'observer_thread_sample_wall_ns', 'response_bytes'):
            require(type(row.get(name)) is int and row[name] >= 0, f'profile {name} missing/invalid')
        metrics = row.get('metrics')
        require(isinstance(metrics, dict) and len(metrics) <= 128, 'profile metrics missing/unbounded')
        for label, value in metrics.items():
            require(isinstance(label, str) and isinstance(value, dict), 'invalid metric object')
            require(type(value.get('calls')) is int and value['calls'] > 0, 'invalid metric call count')
            for field in ('wall_ns', 'thread_cpu_ns', 'process_cpu_ns', 'max_wall_ns'):
                require(type(value.get(field)) is int and value[field] >= 0, f'invalid {label} metric')
            require(value['max_wall_ns'] <= value['wall_ns'], 'metric maximum exceeds total')
        require({'ipc.encode', 'ipc.write', 'ipc.decode_metadata'} <= metrics.keys(), 'IPC instrumentation incomplete')
        if operation == 'STEP':
            require({'sim.SimProcessMsg', 'sim.SimStep', 'sim.SimMakeSimFrame', 'sim.SimGetSimFrameBuffer',
                     'decode_snapshot', 'simulation.state', 'simulation.process_frame'} <= metrics.keys(),
                    'native STEP instrumentation incomplete')
            require(metrics['sim.SimStep']['calls'] == 1 and metrics['sim.SimProcessMsg']['calls'] == 1,
                    'native frame has unexpected step/message count')
    require(seen_steps == list(range(len(frames))), 'profile STEP frames truncated/duplicated/reordered')
    if report.get('ai') is not None:
        require(seen_bots == list(range(len(frames))), 'profile AI request coverage incomplete')
    else:
        require(not seen_bots, 'unexpected AI requests in replay-only/scripted worker')
    return records


def leaf_categories(metrics):
    categories = dict(native_simulation=0, native_snapshot=0, snapshot_decode=0, native_ai=0,
                      native_other=0, ai_action_decode=0, response_json=0, response_pipe_write=0)
    exact = {'sim.SimProcessMsg': 'native_simulation', 'sim.SimStep': 'native_simulation',
             'sim.SimMakeSimFrame': 'native_snapshot', 'sim.SimGetSimFrameBuffer': 'native_snapshot',
             'decode_snapshot': 'snapshot_decode', 'decode_ai_actions': 'ai_action_decode',
             'ipc.encode': 'response_json', 'ipc.write': 'response_pipe_write'}
    for name, metric in metrics.items():
        category = exact.get(name)
        if category is None and name.startswith('sim.'):
            category = 'native_other'
        elif category is None and name.startswith('ai.') and name != 'ai.commands':
            category = 'native_ai'
        if category is not None:
            categories[category] += metric['wall_ns']
    return categories


def summarize_phases(records, frames):
    result = {}
    for phase in PHASES:
        selected = [row for row in records if row['operation'] in ('STEP', 'BOT_INPUT') and frames[row['frame']]['phase'] == phase]
        steps = [row for row in selected if row['operation'] == 'STEP']
        active = sum(row['active_wall_ns'] for row in selected)
        leaves = [leaf_categories(row['metrics']) for row in selected]
        for row, leaf in zip(selected, leaves):
            require(sum(leaf.values()) <= row['active_wall_ns'], 'leaf timings exceed active request time; overlapping metrics')
            leaf['other_active_and_observer'] = row['active_wall_ns'] - sum(leaf.values())
        categories = {name: dict(timings_ms=stats([leaf[name]/1e6 for leaf in leaves]),
                                 mean_ms_per_frame=sum(leaf[name] for leaf in leaves)/len(steps)/1e6,
                                 fraction_of_active=sum(leaf[name] for leaf in leaves)/active if active else 0)
                      for name in leaves[0]}
        labels = sorted({name for row in selected for name in row['metrics']})
        result[phase] = dict(frames=len(steps), requests=len(selected),
            mean_active_ms_per_frame=active/len(steps)/1e6,
            active_ms=stats([row['active_wall_ns']/1e6 for row in selected]),
            active_thread_cpu_ms=stats([row['active_thread_cpu_ns']/1e6 for row in selected]),
            active_process_cpu_ms=stats([row['active_process_cpu_ns']/1e6 for row in selected]),
            step_rpc_ms=stats([frames[row['frame']]['step_rpc_ms'] for row in steps]),
            step_rpc_minus_active_ms=stats([frames[row['frame']]['step_rpc_ms']-row['active_wall_ns']/1e6 for row in steps]),
            thread_sample_overhead_ms=stats([row['observer_thread_sample_wall_ns']/1e6 for row in selected]),
            step_rpc_on_thread_sample_ms=stats([frames[row['frame']]['step_rpc_ms'] for row in steps
                                               if row['observer_thread_sample_wall_ns'] > 0]),
            step_rpc_without_thread_sample_ms=stats([frames[row['frame']]['step_rpc_ms'] for row in steps
                                                    if row['observer_thread_sample_wall_ns'] == 0]),
            step_rpc_minus_active_and_thread_sample_ms=stats([frames[row['frame']]['step_rpc_ms']
                -(row['active_wall_ns']+row['observer_thread_sample_wall_ns'])/1e6 for row in steps]),
            categories=categories,
            largest_active_category=max(categories, key=lambda name: categories[name]['fraction_of_active']),
            operations={operation: dict(requests=len(group),
                active_ms=stats([row['active_wall_ns']/1e6 for row in group]),
                thread_sample_overhead_ms=stats([row['observer_thread_sample_wall_ns']/1e6 for row in group]),
                inclusive_metrics_ms={label: stats([row['metrics'].get(label, {}).get('wall_ns', 0)/1e6 for row in group])
                                      for label in labels})
                for operation in ('STEP', 'BOT_INPUT')
                if (group := [row for row in selected if row['operation'] == operation])},
            inclusive_metrics_ms={label: stats([row['metrics'].get(label, {}).get('wall_ns', 0)/1e6 for row in selected])
                                  for label in labels})
    return result


def summarize_threads(samples, records, frames):
    require(isinstance(samples, list) and len(samples) <= 20000, 'thread samples missing/unbounded')
    totals, intervals, skipped = {}, [], 0
    previous = None
    for sample in samples:
        require(isinstance(sample, dict), 'invalid thread sample')
        if sample.get('available') is not True:
            skipped += 1; previous = None
            continue
        request = sample.get('request_id')
        require(type(request) is int and 1 <= request <= len(records), 'thread sample request not covered')
        stamp = sample.get('perf_counter_ns')
        require(type(stamp) is int and stamp > 0, 'thread sample timestamp invalid')
        current = {}
        for thread in sample.get('threads', []):
            for name in ('tid', 'creation', 'kernel_cpu_ns', 'user_cpu_ns'):
                require(type(thread.get(name)) is int and thread[name] >= 0, 'thread CPU identity/counter invalid')
            key = (thread['tid'], thread['creation'])
            require(key not in current, 'duplicate sampled thread identity')
            current[key] = thread['kernel_cpu_ns'] + thread['user_cpu_ns']
        if previous is not None:
            old_sample, old = previous
            require(stamp > old_sample['perf_counter_ns'] and request >= old_sample['request_id'], 'thread samples reordered')
            deltas = {}
            for key in current.keys() & old.keys():
                require(current[key] >= old[key], 'thread CPU counter decreased within same identity')
                deltas[key] = current[key]-old[key]
                totals[key] = totals.get(key, 0) + deltas[key]
            phases = []
            for number in (old_sample['request_id'], request):
                row = records[number-1]
                phases.append(frames[row['frame']]['phase'] if row['operation'] in ('STEP', 'BOT_INPUT') else 'lifecycle')
            intervals.append(dict(start_request_id=old_sample['request_id'], end_request_id=request,
                phase=phases[0] if phases[0] == phases[1] else 'boundary',
                elapsed_ms=(stamp-old_sample['perf_counter_ns'])/1e6,
                matched_thread_cpu_ms=sum(deltas.values())/1e6,
                threads_with_positive_cpu=sum(value > 0 for value in deltas.values()),
                newly_seen_threads=len(current.keys()-old.keys()), missing_threads=len(old.keys()-current.keys())))
        previous = sample, current
    total = sum(totals.values())
    top = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    return dict(qualified=bool(intervals and total > 0 and not skipped), skipped_samples=skipped,
        sampled_cpu_ms=total/1e6, busiest_thread_fraction=top[0][1]/total if total else None,
        threads=[dict(tid=key[0], creation=key[1], sampled_cpu_ms=value/1e6,
                      fraction=value/total if total else 0) for key, value in top], intervals=intervals,
        scope='live worker thread CPU distribution; not DLL attribution or proof of multicore scaling')


def summarize(directory, control=None):
    benchmark = load_benchmark(directory)
    profile, profile_sha = read_json(Path(directory)/'worker-profile.json')
    records = validate_profile(profile, benchmark, profile_sha)
    result = dict(schema=1, passed=True, frames=len(benchmark['rows']),
        evidence_sha256={**benchmark['evidence_sha256'], 'worker-profile.json': profile_sha},
        source_sha256=profile['source_sha256'], phases=summarize_phases(records, benchmark['rows']),
        thread_cpu=summarize_threads(profile.get('thread_samples'), records, benchmark['rows']),
        limitations=['nested metrics are inclusive; only named disjoint leaf categories form the active-time partition',
                     'RPC minus worker active time includes coordinator scheduling/serialization/transport and observer tail; it is not pure IPC',
                     'receive time includes parent pacing/idle and is excluded from active compute',
                     'thread CPU samples omit exited threads and do not identify which DLL created or used a thread',
                     'thread CPU totals include profiler/sampler overhead; thread enumeration can dominate sampled RPC tails',
                     'profile frame binding uses owned worker PID/source/output digest and exact frame/size coverage; profiler stores no raw command data',
                     'single profiled run does not establish performance improvement or network playability'])
    if control is not None:
        baseline = load_benchmark(control)
        require(baseline['report'].get('profiled') is False, 'control must be unprofiled')
        for field in ('bootstrap_sha256', 'simulation_sha256', 'asset_manifest_sha256', 'frames', 'input_journal_sha256'):
            require(benchmark['report'][field] == baseline['report'][field], f'control {field} differs')
        for actual, expected in zip(benchmark['rows'], baseline['rows']):
            require(all(actual[key] == expected[key] for key in ('frame', 'phase', 'input_sha256', 'state_sha256')),
                    'control input/state/phase differs')
        comparisons = {}
        for phase in PHASES:
            pairs = [(row['step_rpc_ms'], base['step_rpc_ms']) for row, base in zip(benchmark['rows'], baseline['rows'])
                     if row['phase'] == phase]
            observed, ordinary = stats([pair[0] for pair in pairs]), stats([pair[1] for pair in pairs])
            comparisons[phase] = dict(profiled_rpc_ms=observed, control_rpc_ms=ordinary,
                paired_rpc_delta_ms=stats([a-b for a, b in pairs]),
                mean_ratio=observed['mean']/ordinary['mean'] if ordinary['mean'] else None,
                p95_ratio=observed['p95']/ordinary['p95'] if ordinary['p95'] else None)
        result['control'] = dict(evidence_sha256=baseline['evidence_sha256'], exact_input_and_observable_state_match=True,
                                 phases=comparisons,
                                 scope='paired instrumentation/environment difference; not a causal estimate from one pair')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path, required=True)
    parser.add_argument('--control', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = summarize(args.benchmark, args.control)
    with args.output.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write('\n')
    print(json.dumps({'passed': True, 'frames': result['frames'],
                      'dominant_by_phase': {p: v['largest_active_category'] for p, v in result['phases'].items()},
                      'thread_cpu_qualified': result['thread_cpu']['qualified']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
