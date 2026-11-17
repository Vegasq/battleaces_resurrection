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
from pathlib import Path, PureWindowsPath
import statistics
import struct

from server.native_simulation import SUPPORTED_DLL_SHA256

PHASES = ('setup', 'movement', 'combat')
PROFILE_SOURCES = ('tools/profile_worker_timing.py', 'server/worker_client.py', 'server/simulation_worker.py',
                   'server/native_simulation.py', 'server/native_ai.py', 'server/worker_ai.py')
HYBRID_PROFILE_SOURCES = ('server/wine_worker.py', 'server/wine_worker_guardian.py', 'server/wine_worker_cgroup.py')
RUST_PROFILE_SOURCES = ('server/rust_snapshot_decoder.py', 'rust/snapshot-decoder/Cargo.toml',
                        'rust/snapshot-decoder/Cargo.lock', 'rust/snapshot-decoder/src/lib.rs',
                        'rust/snapshot-decoder/src/ffi.rs')
RUST_CHILDREN = ('rust.ffi.decode', 'rust.copy_output', 'rust.json.loads', 'rust.validate', 'rust.ffi.free')
RUST_METRIC_PARENTS = {'rust.decode': None, **{name: 'rust.decode' for name in RUST_CHILDREN}}
MAX_DURATION_NS = (1 << 63) - 1
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
    try:
        return type(value) in (float, int) and math.isfinite(value)
    except OverflowError:
        return False


def duration(value):
    return type(value) is int and 0 <= value <= MAX_DURATION_NS


def decoder_identity(value):
    # Historical Python sidecars predate the explicit identity field.
    if value is None:
        return {'implementation': 'python'}
    require(isinstance(value, dict), 'decoder identity missing/invalid')
    if value.get('implementation') == 'python':
        require(value == {'implementation': 'python'}, 'Python decoder identity differs')
    else:
        require(set(value) == {'implementation', 'abi_version', 'library_sha256', 'library_path'}
                and value['implementation'] == 'rust' and type(value['abi_version']) is int and value['abi_version'] == 1
                and valid_sha(value['library_sha256']) and isinstance(value['library_path'], str)
                and PureWindowsPath(value['library_path']).is_absolute()
                and not any(char in value['library_path'] for char in ('\x00', '\r', '\n')),
                'Rust decoder identity missing/invalid')
    return value


def read_json(path, limit=128 * 1024 * 1024):
    require(path.is_file() and not path.is_symlink(), f'JSON evidence missing/redirected: {path.name}')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, f'JSON evidence exceeds bound: {path.name}')
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
    require(isinstance(report.get('source_at_start'), dict) and report['source_at_start']
            and all(valid_sha(v) for v in report['source_at_start'].values()),
            'benchmark source hashes missing/invalid')
    cleanup = report.get('cleanup', {})
    require(type(cleanup.get('exit_code')) is int and cleanup['exit_code'] == 0 and cleanup.get('failure') is None
            and cleanup.get('stderr_thread_closed') is True and cleanup.get('io_threads_closed') is True
            and 'cleanup_error' not in report,
            'benchmark worker cleanup incomplete')
    require(type(report.get('frames')) is int and 1 <= report['frames'] <= MAX_FRAMES, 'benchmark frame count invalid')
    for field in ('bootstrap_sha256', 'simulation_sha256', 'asset_manifest_sha256', 'input_journal_sha256'):
        require(valid_sha(report.get(field)), f'benchmark {field} missing/invalid')
    require(report['simulation_sha256'] == SUPPORTED_DLL_SHA256, 'benchmark did not use the original native simulation')
    decoder_identity(report.get('snapshot_decoder'))
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
            if report.get('ai') is not None:
                require(finite(row.get('ai_rpc_ms')) and row['ai_rpc_ms'] >= 0, 'frame AI RPC timing invalid')
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


def validate_profile_identity(profile, report):
    """Bind Windows-worker timing separately from the Linux guardian's PID."""
    backend = report.get('backend')
    kind = backend.get('kind') if isinstance(backend, dict) else None
    hybrid = kind == 'native-linux-wine-worker'
    required_sources = PROFILE_SOURCES
    expected_decoder = decoder_identity(report.get('snapshot_decoder'))
    require(decoder_identity(profile.get('snapshot_decoder')) == expected_decoder, 'profile decoder identity differs')
    rust = expected_decoder['implementation'] == 'rust'
    if 'source_unchanged' in profile:
        require(profile['source_unchanged'] is True, 'profile source changed')
    if rust:
        require(profile.get('snapshot_decoder_requested') == expected_decoder
                and profile.get('source_unchanged') is True and profile.get('snapshot_decoder_library_unchanged') is True,
                'Rust profile requested/loaded library or source stability differs')
        require(profile.get('metric_parents') == RUST_METRIC_PARENTS, 'Rust metric parent schema differs')
        required_sources += RUST_PROFILE_SOURCES
    else:
        require(profile.get('metric_parents', {}) == {}, 'Python profile contains Rust metric parents')
        if 'snapshot_decoder_requested' in profile:
            require(profile['snapshot_decoder_requested'] == expected_decoder and profile.get('source_unchanged') is True
                    and profile.get('snapshot_decoder_library_unchanged') is None, 'Python profile identity/stability differs')
    expected_pid = report.get('worker_pid')
    if hybrid:
        runtime, cleanup = report.get('worker_runtime', {}), report.get('backend_statistics', {})
        require(isinstance(runtime, dict) and runtime.get('platform') == 'win32'
                and runtime.get('os_name') == 'nt' and runtime.get('pointer_bits') == 64
                and runtime.get('implementation') == 'cpython'
                and isinstance(runtime.get('python_version'), str) and bool(runtime['python_version'])
                and isinstance(runtime.get('executable'), str) and bool(runtime['executable']),
                'hybrid worker runtime identity missing/invalid')
        require(isinstance(cleanup, dict) and cleanup.get('cleanup_complete') is True
                and cleanup.get('prefix_removed') is True and cleanup.get('cgroup_removed') is True
                and all(type(cleanup.get(key)) is int and cleanup[key] == 0 for key in ('exit_code', 'native_exit_code'))
                and type(report.get('worker_pid')) is int and report['worker_pid'] > 0
                and type(cleanup.get('guardian_pid')) is int and cleanup['guardian_pid'] == report['worker_pid'],
                'hybrid guardian identity/cleanup missing/invalid')
        require(profile.get('launch_kind') == kind, 'hybrid profile did not identify a Windows worker launch')
        expected_pid = report.get('native_worker_pid')
        require(type(expected_pid) is int and 0 < expected_pid <= 0xffffffff, 'hybrid native PID missing/invalid')
        required_sources += HYBRID_PROFILE_SOURCES
    else:
        require(kind in (None, 'windows-worker') and profile.get('launch_kind') in (None, 'direct-worker'),
                'unknown/mismatched profile launch kind')
        if rust:
            runtime = report.get('worker_runtime', {})
            require(isinstance(runtime, dict) and runtime.get('platform') == 'win32' and runtime.get('os_name') == 'nt'
                    and runtime.get('pointer_bits') == 64 and runtime.get('implementation') == 'cpython'
                    and all(isinstance(runtime.get(key), str) and runtime[key] for key in ('python_version', 'executable')),
                    'Rust worker runtime identity missing/invalid')
    require(type(profile.get('pid')) is int and profile['pid'] > 0 and profile['pid'] == expected_pid,
            'profile worker PID differs')
    sources = profile.get('source_sha256', {})
    require(isinstance(sources, dict) and set(sources) == set(required_sources)
            and all(valid_sha(sources[name]) and sources[name] == report['source_at_start'].get(name)
                    for name in required_sources), 'profile source binding differs')
    return expected_decoder


def rpc_residual(row, frame, *, include_observer=True):
    """Signed difference, not a subtraction of causally nested intervals.

    Recorder.write sends the response before recording its metrics/header and
    finishing active time. The parent can finish its RPC while that bookkeeping
    or a post-reply descheduling interval is still inside worker active time.
    The parent may even consume the packet before the write call returns.
    Therefore a negative difference does not invalidate either measured span.
    """
    key = 'step_rpc_ms' if row['operation'] == 'STEP' else 'ai_rpc_ms'
    rpc = frame[key]
    require(finite(rpc) and 0 <= rpc <= MAX_DURATION_NS / 1e6, 'RPC duration outside bound')
    require(duration(row['active_wall_ns']) and duration(row['observer_thread_sample_wall_ns']),
            'worker/observer duration outside bound')
    accounted = row['active_wall_ns'] + (row['observer_thread_sample_wall_ns'] if include_observer else 0)
    return rpc - accounted / 1e6


def validate_profile(profile, benchmark, profile_sha):
    report, frames = benchmark['report'], benchmark['rows']
    require(profile.get('schema') == 1 and profile.get('completed') is True
            and type(profile.get('exit_code')) is int and profile['exit_code'] == 0
            and profile.get('failure') is None and type(profile.get('dropped_records')) is int and profile['dropped_records'] == 0
            and profile.get('synthetic_test_backend') is False, 'worker profile incomplete/failed/synthetic')
    require(report.get('profiled') is True and report.get('worker_profile_sha256') == profile_sha,
            'profile sidecar is not bound to this benchmark')
    require(report.get('simulation_sha256') == SUPPORTED_DLL_SHA256, 'profile did not use the original native simulation')
    decoder = validate_profile_identity(profile, report)
    rust = decoder['implementation'] == 'rust'
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
            require(duration(row.get(name)), f'profile {name} missing/invalid')
        metrics = row.get('metrics')
        require(isinstance(metrics, dict) and len(metrics) <= 128, 'profile metrics missing/unbounded')
        for label, value in metrics.items():
            require(isinstance(label, str) and isinstance(value, dict), 'invalid metric object')
            require(type(value.get('calls')) is int and 0 < value['calls'] <= 0x7fffffff, 'invalid metric call count')
            for field in ('wall_ns', 'thread_cpu_ns', 'process_cpu_ns', 'max_wall_ns'):
                require(duration(value.get(field)), f'invalid {label} metric')
            require(value['max_wall_ns'] <= value['wall_ns'] <= value['max_wall_ns'] * value['calls'],
                    'metric maximum/total/call count differs')
            limit = row['receive_wall_ns'] if label == 'ipc.decode_metadata' else row['active_wall_ns']
            require(value['wall_ns'] <= limit, 'metric exceeds its containing request interval')
        require(rust or not any(name.startswith('rust.') for name in metrics), 'Python profile has Rust decoder metrics')
        require({'ipc.encode', 'ipc.write', 'ipc.decode_metadata'} <= metrics.keys(), 'IPC instrumentation incomplete')
        if operation == 'STEP':
            required = {'sim.SimProcessMsg', 'sim.SimStep', 'sim.SimMakeSimFrame', 'sim.SimGetSimFrameBuffer',
                        'simulation.process_frame'}
            required |= ({'simulation.snapshot_bytes', *RUST_METRIC_PARENTS} if rust else {'decode_snapshot', 'simulation.state'})
            require(required <= metrics.keys(),
                    'native STEP instrumentation incomplete')
            require(all(metrics[name]['calls'] == 1 for name in required),
                    'native frame has unexpected step/message count')
            require(not rust or not {'decode_snapshot', 'simulation.state'}.intersection(metrics),
                    'Rust STEP includes a Python decoder/state path')
        if operation in ('STEP', 'BOT_INPUT'):
            rpc_residual(row, frames[row['frame']])
        # Validate disjoint accounting even when a caller only asks for validation.
        require(sum(leaf_categories(metrics).values()) <= row['active_wall_ns'],
                'leaf timings exceed active request time; overlapping metrics')
    require(seen_steps == list(range(len(frames))), 'profile STEP frames truncated/duplicated/reordered')
    if report.get('ai') is not None:
        require(seen_bots == list(range(len(frames))), 'profile AI request coverage incomplete')
    else:
        require(not seen_bots, 'unexpected AI requests in replay-only/scripted worker')
    return records


def leaf_categories(metrics):
    categories = dict(native_simulation=0, native_snapshot=0, snapshot_decode=0, native_ai=0,
                      native_other=0, ai_action_decode=0, response_json=0, response_pipe_write=0,
                      native_process_wrapper=0, snapshot_export_wrapper=0, python_state_wrapper=0,
                      rust_ffi_decode=0, rust_output_copy=0, rust_json_parse=0, rust_validation=0,
                      rust_ffi_free=0, rust_adapter_overhead=0)
    exact = {'sim.SimProcessMsg': 'native_simulation', 'sim.SimStep': 'native_simulation',
             'sim.SimMakeSimFrame': 'native_snapshot', 'sim.SimGetSimFrameBuffer': 'native_snapshot',
             'decode_snapshot': 'snapshot_decode', 'decode_ai_actions': 'ai_action_decode',
             'ipc.encode': 'response_json', 'ipc.write': 'response_pipe_write',
             'rust.ffi.decode': 'rust_ffi_decode', 'rust.copy_output': 'rust_output_copy',
             'rust.json.loads': 'rust_json_parse', 'rust.validate': 'rust_validation', 'rust.ffi.free': 'rust_ffi_free'}
    for name, metric in metrics.items():
        category = exact.get(name)
        if category is None and name.startswith('sim.'):
            category = 'native_other'
        elif category is None and name.startswith('ai.') and name != 'ai.commands':
            category = 'native_ai'
        if category is not None:
            categories[category] += metric['wall_ns']
    def remainder(parent, children):
        require(all(name in metrics for name in children), f'{parent} child instrumentation incomplete')
        value = metrics[parent]['wall_ns'] - sum(metrics[name]['wall_ns'] for name in children)
        require(value >= 0, f'{parent} children exceed inclusive parent; negative overhead')
        return value
    if 'simulation.process_frame' in metrics:
        categories['native_process_wrapper'] = remainder('simulation.process_frame', ('sim.SimProcessMsg', 'sim.SimStep'))
    if 'simulation.snapshot_bytes' in metrics:
        categories['snapshot_export_wrapper'] = remainder('simulation.snapshot_bytes', ('sim.SimMakeSimFrame', 'sim.SimGetSimFrameBuffer'))
    if 'simulation.state' in metrics:
        children = (('simulation.snapshot_bytes',) if 'simulation.snapshot_bytes' in metrics
                    else ('sim.SimMakeSimFrame', 'sim.SimGetSimFrameBuffer')) + ('decode_snapshot',)
        categories['python_state_wrapper'] = remainder('simulation.state', children)
    if any(name.startswith('rust.') for name in metrics):
        require(set(RUST_METRIC_PARENTS) <= metrics.keys()
                and {name for name in metrics if name.startswith('rust.')} == set(RUST_METRIC_PARENTS),
                'Rust decoder instrumentation incomplete/unknown')
        categories['rust_adapter_overhead'] = remainder('rust.decode', RUST_CHILDREN)
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
        step_residuals = [rpc_residual(row, frames[row['frame']]) for row in steps]
        bots = [row for row in selected if row['operation'] == 'BOT_INPUT']
        bot_residuals = [rpc_residual(row, frames[row['frame']]) for row in bots]
        result[phase] = dict(frames=len(steps), requests=len(selected),
            mean_active_ms_per_frame=active/len(steps)/1e6,
            active_ms=stats([row['active_wall_ns']/1e6 for row in selected]),
            active_thread_cpu_ms=stats([row['active_thread_cpu_ns']/1e6 for row in selected]),
            active_process_cpu_ms=stats([row['active_process_cpu_ns']/1e6 for row in selected]),
            step_rpc_ms=stats([frames[row['frame']]['step_rpc_ms'] for row in steps]),
            step_rpc_minus_active_ms=stats([rpc_residual(row, frames[row['frame']], include_observer=False) for row in steps]),
            thread_sample_overhead_ms=stats([row['observer_thread_sample_wall_ns']/1e6 for row in selected]),
            step_rpc_on_thread_sample_ms=stats([frames[row['frame']]['step_rpc_ms'] for row in steps
                                               if row['observer_thread_sample_wall_ns'] > 0]),
            step_rpc_without_thread_sample_ms=stats([frames[row['frame']]['step_rpc_ms'] for row in steps
                                                    if row['observer_thread_sample_wall_ns'] == 0]),
            step_rpc_minus_active_and_thread_sample_ms=stats(step_residuals),
            bot_rpc_ms=stats([frames[row['frame']]['ai_rpc_ms'] for row in bots]),
            bot_rpc_minus_active_and_thread_sample_ms=stats(bot_residuals),
            rpc_residual_diagnostics=dict(step_negative_count=sum(value < 0 for value in step_residuals),
                bot_negative_count=sum(value < 0 for value in bot_residuals),
                negative_residual_is_qualification_failure=False),
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
        snapshot_decoder=decoder_identity(benchmark['report'].get('snapshot_decoder')),
        metric_parents=profile.get('metric_parents', {}),
        rpc_residual_scope=dict(signed_duration_difference=True, causal_transport_cost=False,
            worker_endpoint_after_reply_write=True, parent_may_finish_before_worker_write_returns=True,
            post_reply_bookkeeping_and_scheduling_may_overlap_parent=True),
        evidence_sha256={**benchmark['evidence_sha256'], 'worker-profile.json': profile_sha},
        source_sha256=profile['source_sha256'], phases=summarize_phases(records, benchmark['rows']),
        thread_cpu=summarize_threads(profile.get('thread_samples'), records, benchmark['rows']),
        limitations=['nested metrics are inclusive; only named disjoint leaf categories form the active-time partition',
                     'Rust FFI decode includes native Rust decoding and Rust JSON serialization; they are not separately timed',
                     'Rust JSON parse includes duplicate-key hooks; validation includes raw SHA/schema checks; parent residual includes instrumentation overhead',
                     'RPC residuals are signed differences between non-nested intervals, not transport or coordinator cost estimates',
                     'parent RPC can finish before worker reply-write returns or its bookkeeping ends; post-reply scheduling can produce negative residuals',
                     'receive time includes parent pacing/idle and is excluded from active compute',
                     'thread CPU samples omit exited threads and do not identify which DLL created or used a thread',
                     'thread CPU totals include profiler/sampler overhead; thread enumeration can dominate sampled RPC tails',
                     'profile frame binding uses validated native worker PID/source/output digest and exact frame/size coverage; profiler stores no raw command data',
                     'negative RPC residuals remain visible and do not relax bounded raw-duration or within-worker parent/child conservation checks',
                     'single profiled run does not establish performance improvement or network playability'])
    if control is not None:
        baseline = load_benchmark(control)
        require(baseline['report'].get('profiled') is False, 'control must be unprofiled')
        for field in ('bootstrap_sha256', 'simulation_sha256', 'asset_manifest_sha256', 'frames', 'input_journal_sha256'):
            require(benchmark['report'][field] == baseline['report'][field], f'control {field} differs')
        require(decoder_identity(benchmark['report'].get('snapshot_decoder'))
                == decoder_identity(baseline['report'].get('snapshot_decoder')), 'control decoder identity differs')
        for field in ('source_at_start', 'worker_runtime', 'ai', 'workload', 'paced', 'timestep_ms'):
            require(benchmark['report'].get(field) == baseline['report'].get(field), f'control {field} differs')
        actual_backend = dict(benchmark['report'].get('backend') or {})
        control_backend = dict(baseline['report'].get('backend') or {})
        # Version-probe duration is an observation, not an executable/config identity.
        actual_backend.pop('wine_version_probe_ms', None)
        control_backend.pop('wine_version_probe_ms', None)
        require(actual_backend == control_backend, 'control backend identity differs')
        if actual_backend.get('kind') == 'native-linux-wine-worker':
            cleanup = baseline['report'].get('backend_statistics', {})
            require(cleanup.get('cleanup_complete') is True and cleanup.get('prefix_removed') is True
                    and cleanup.get('cgroup_removed') is True
                    and all(type(cleanup.get(key)) is int and cleanup[key] == 0 for key in ('exit_code', 'native_exit_code')),
                    'control hybrid cleanup incomplete')
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
                                 exact_runtime_and_decoder_identity_match=True,
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
