"""Private explicit full/ownership worker parity and alternating STEP measurements.

Replays retained inputs by default. --fresh-ai regenerates original bot bytes;
neither mode exercises Room lifecycle or Internet publication cadence. Full
states retain the original observable digest. Ownership is independently
projected from the first full arm. All nine common fields match on identical
raw corpus inputs. Across separately acquired native buffers, eight semantic
fields match and every raw hash/difference is retained explicitly, following
the existing original full-digest scope. No arbitrary fields are normalized.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

from server.worker_client import SimulationWorker
from server.protobuf_wire import get_repeated_bytes
from tools import benchmark_large_armies as b
from tools import capture_snapshot_corpus as c
from tools import verify_rust_worker as w
from tools import verify_rust_fresh_ai as ai
from tools import verify_rust_snapshot_decoder as decoder_verifier

ROOT = b.ROOT
COMMON = frozenset(('frame', 'viewer', 'local_alliance', 'canonical_fnv1a64',
                    'raw_sha256', 'byte_count', 'counts', 'resources', 'game_state'))
WINE_OPTIONS = ('wine_executable', 'windows_python', 'wine_prefix_template', 'wine_cgroup_parent')
MAX_REFERENCE = 128 * 1024 * 1024


def sources():
    names = ('tools/verify_compact_worker.py', 'tests/test_compact_worker_verifier.py',
             'tools/verify_rust_fresh_ai.py')
    return {**w.sources(), **{name: b.digest((ROOT/name).read_bytes()) for name in names}}


def projection(full):
    b.require(set(full) == COMMON | {'entities'}, 'full reference schema differs')
    records = []
    previous = -1
    for entity in full['entities']:
        ident = entity['id']
        b.require(type(ident) is int and previous < ident <= 0xffffffff,
                  'full reference IDs are not strictly ordered uint32')
        previous = ident
        if 'army' in entity and 'type' in entity:
            records.append({key: entity[key] for key in ('id', 'army', 'type')})
    return {**{key: full[key] for key in COMMON}, 'ownership': records}


def compare_projection(actual, expected, *, same_raw=True):
    b.require(set(actual) == COMMON | {'ownership'}, 'ownership schema differs')
    keys = COMMON | {'ownership'} if same_raw else (COMMON - {'raw_sha256'}) | {'ownership'}
    decoder_verifier.assert_equivalent({key: actual[key] for key in keys}, {key: expected[key] for key in keys})


def validate_corpora(args, bindings, *, decoder=None):
    """Decode the retained raw input itself, never re-acquire native storage."""
    from server.native_simulation import decode_snapshot
    from server.rust_snapshot_decoder import RustSnapshotDecoder
    if decoder is None:
        b.require(sys.platform == 'win32', 'same-raw PE corpus checks require Windows; supply bound Windows evidence for Wine')
        decoder = RustSnapshotDecoder(args.library, args.library_sha256)
    b.require(decoder.projection_version == 1, 'explicit Rust projection export required')
    report = dict(schema=1, passed=False, library_sha256=args.library_sha256, source_sha256=sources(),
                  execution_platform=sys.platform,
                  scope='same raw bytes; all nine common fields, full diagnostics and independent ownership', corpora=[])
    b.require(decoder.info['library_sha256'] == args.library_sha256, 'same-raw decoder library differs')
    w.remember(args.library, w.MAX_LIBRARY, bindings, args.library_sha256)
    for directory in args.corpus:
        manifest_raw = w.remember(directory/'manifest.json', w.MAX_JSON, bindings)
        manifest = json.loads(manifest_raw)
        b.require(manifest.get('schema') == 1 and manifest.get('passed') is True
                  and manifest.get('native_qualified') is True and manifest.get('source_unchanged') is True
                  and manifest.get('reference_unchanged') is True and w.clean_exit(manifest)
                  and manifest.get('source_at_start') and manifest['source_at_start'] == manifest.get('source_at_finish'),
                  'qualified unchanged retained native corpus required')
        captured = manifest['reference']
        selected = argparse.Namespace(assets=args.assets, journal=Path(captured['journal']))
        _, _, rows, samples, viewers, reference = c.load_reference(selected)
        b.require({key: value for key, value in reference.items() if key not in ('assets', 'journal')}
                  == {key: value for key, value in captured.items() if key not in ('assets', 'journal')},
                  'retained corpus/reference binding differs')
        b.require(manifest['verified_frames'] == len(rows) and manifest['selection'] == samples
                  and manifest['viewer_frames'] == sorted(viewers), 'retained corpus coverage differs')
        for name, digest in reference['journal_files'].items():
            w.remember(selected.journal/name, c.JOURNAL_LIMITS[name], bindings, digest)
        observed = set()
        b.require(1 <= len(manifest['snapshots']) <= 64, 'bounded retained corpus required')
        for entry in manifest['snapshots']:
            frame, viewer = entry['frame'], entry['viewer']
            b.require(type(frame) is int and 0 <= frame < len(rows) and type(viewer) is int and 0 <= viewer <= 31
                      and entry['include_entities'] is True and (frame, viewer) not in observed
                      and entry['phase'] == rows[frame]['phase'], 'invalid retained corpus entry')
            observed.add((frame, viewer))
            raw = w.corpus_file(directory, entry['snapshot_file'], entry['snapshot_sha256'], bindings, 16*1024*1024)
            b.require(len(raw) == entry['bytes'], 'retained raw byte count differs')
            full = decode_snapshot(raw, viewer, mode='full')
            b.require(full['frame'] == frame and full['viewer'] == viewer
                      and full['raw_sha256'] == b.digest(raw) and full['byte_count'] == len(raw), 'independent raw binding differs')
            b.require(b.state_digest(full) == entry['observable_state_sha256'], 'retained corpus full digest differs')
            if viewer == 31:
                b.require(b.state_digest(full) == rows[frame]['state_sha256'], 'retained viewer31 state differs')
            expected_full = json.loads(w.corpus_file(directory, entry['expected_file'], entry['expected_sha256'], bindings))
            decoder_verifier.assert_equivalent(json.loads(decoder_verifier.json_bytes(full)), expected_full)
            summary = {key: full[key] for key in COMMON}
            projected = projection(full)
            for mode, expected in (('full', full), ('summary', summary), ('ownership', projected)):
                decoder_verifier.assert_equivalent(decoder.decode(raw, viewer, mode=mode), expected)
                decoder_verifier.assert_equivalent(decode_snapshot(raw, viewer, mode=mode), expected)
            expected_summary = json.loads(w.corpus_file(directory, entry['expected_summary_file'],
                                                         entry['expected_summary_sha256'], bindings))
            decoder_verifier.assert_equivalent(json.loads(decoder_verifier.json_bytes(summary)), expected_summary)
        b.require(observed == {(frame, 31) for frame in samples}
                  | {(frame, viewer) for frame in viewers for viewer in (0, 1)}, 'retained corpus incomplete')
        report['corpora'].append(dict(directory=str(directory), manifest_sha256=b.digest(manifest_raw),
                                     snapshots=len(observed), reference=reference))
    b.require(report['corpora'], '--corpus or a hash-bound same-raw report required')
    for path, identity in bindings.items():
        b.require(b.digest(w.read_file(Path(path), identity['limit'])) == identity['sha256'], 'same-raw input changed: '+path)
    b.require(sources() == report['source_sha256'], 'same-raw source changed')
    report.update(passed=True, inputs_unchanged=True, evidence_sha256={path: identity['sha256'] for path, identity in bindings.items()})
    return report


def update_history(history, state, mode):
    records = state['entities' if mode == 'full' else 'ownership']
    for record in records:
        if 'army' in record and 'type' in record:
            history[record['id']] = (record['army'], record['type'])


def history_digest(history):
    return b.digest(json.dumps(sorted(history.items()), separators=(',', ':')).encode())


def memory_sample(worker, backend):
    """Query only the retained owned Windows handle, outside timed STEP calls."""
    if backend is not None or os.name != 'nt':
        return dict(available=False, reason='no retained Wine cgroup memory sampler; Linux memory gate open')
    import ctypes as ct
    from ctypes import wintypes as wt
    class Counters(ct.Structure):
        _fields_ = [('cb', wt.DWORD), ('PageFaultCount', wt.DWORD)] + [
            (name, ct.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
            'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
    counters = Counters()
    counters.cb = ct.sizeof(counters)
    psapi = ct.WinDLL('psapi', use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ct.POINTER(Counters), wt.DWORD]
    psapi.GetProcessMemoryInfo.restype = wt.BOOL
    b.require(psapi.GetProcessMemoryInfo(wt.HANDLE(int(worker.process._handle)), ct.byref(counters), counters.cb),
              f'owned process memory query failed:{ct.get_last_error()}')
    return dict(available=True, scope='retained worker process handle; peak includes startup',
                working_set_bytes=counters.WorkingSetSize, peak_working_set_bytes=counters.PeakWorkingSetSize,
                private_usage_bytes=counters.PrivateUsage)


def validate_args(args):
    hybrid = b.wine_requested(args)
    b.require(sys.platform.startswith('linux') if hybrid else sys.platform == 'win32',
              'use native Windows or explicit Linux Wine; no fallback')
    b.require(not os.path.lexists(args.output), 'fresh private output required')
    b.require(args.library.is_absolute() and not args.library.is_symlink(),
              'explicit unredirected absolute library required')
    for name in ('assets', 'journal', 'library', 'output'):
        setattr(args, name, getattr(args, name).resolve())
    local = (ROOT/'local').resolve()
    b.require(args.output != local and args.output.is_relative_to(local), 'ignored local output required')
    for path in (args.assets, args.journal, args.library):
        b.require(not args.output.is_relative_to(path) and not path.is_relative_to(args.output),
                  'input/output paths overlap')
    b.require(all(path.is_dir() for path in (args.assets, args.journal)), 'input directory missing')
    b.require(type(args.pairs) is int and args.pairs == 3, 'exactly three alternating pairs required')
    b.require(isinstance(args.library_sha256, str) and len(args.library_sha256) == 64
              and all(ch in '0123456789abcdef' for ch in args.library_sha256), 'lowercase library SHA256 required')
    b.require(type(args.timeout_seconds) in (int, float) and math.isfinite(args.timeout_seconds)
              and 30 <= args.timeout_seconds <= 1800, 'timeout outside30..1800seconds')
    if args.build_receipt:
        args.build_receipt = args.build_receipt.resolve()
        b.require(not args.build_receipt.is_relative_to(args.output), 'build receipt overlaps output')
    b.require(bool(args.corpus) != bool(args.same_raw_report), 'select retained --corpus or --same-raw-report')
    b.require(bool(args.same_raw_report) == bool(args.same_raw_report_sha256), 'same-raw evidence requires expected SHA256')
    if args.same_raw_report:
        b.require(not args.same_raw_report.resolve().is_relative_to(args.output), 'same-raw evidence overlaps output')
    for directory in args.corpus:
        b.require(directory.is_dir() and not args.output.is_relative_to(directory.resolve())
                  and not directory.resolve().is_relative_to(args.output), 'corpus/output paths overlap')
    return hybrid


def load_inputs(args, bindings):
    data, inputs, rows, _, _, reference = c.load_reference(args)
    b.require(1 <= len(rows) <= 10000, 'bounded retained journal required')
    baseline = json.loads(w.remember(args.baseline_inputs.resolve(), w.MAX_JSON, bindings))
    b.require(any(entry.get('journal_files') == reference['journal_files']
                  for entry in baseline.get('references', {}).values()), 'journal is not a pinned N47 baseline input')
    payloads = []
    with io.BytesIO(inputs) as stream:
        for row in rows:
            payloads.append(b.read_frame(stream))
            b.require(type(row.get('state_sha256')) is str and len(row['state_sha256']) == 64,
                      'complete retained full-state digests required')
        b.require(not stream.read(1), 'extra input bytes')
    for name, sha in reference['journal_files'].items():
        w.remember(args.journal/name, c.JOURNAL_LIMITS[name], bindings, sha)
    for name, limit in (('Simulation.dll', 128*1024*1024), ('asset-manifest.json', 4*1024*1024)):
        w.remember(args.assets/name, limit, bindings)
    source = dict(data=data, inputs=inputs, payloads=payloads, rows=rows, reference=reference,
                  baseline_inputs_sha256=bindings[str(args.baseline_inputs.resolve())]['sha256'], setup=None)
    if args.fresh_ai:
        from server.worker_ai import AISetup, BotRoster
        old = json.loads(w.read_file(args.journal/'benchmark.json', c.JOURNAL_LIMITS['benchmark.json']))
        identity = old.get('ai')
        b.require(isinstance(identity, dict) and isinstance(identity.get('bots'), dict)
                  and reference['workload'].get('opponent') == 'ai', 'retained original AI workload required')
        bots = {int(key): value for key, value in identity['bots'].items()}
        setup, roster = AISetup(args.assets, bots), BotRoster(data, bots)
        expected = dict(bots=setup.wire()['bots'],
            dll_sha256=b.digest(w.remember(args.assets/'aiprogram.dll', 128*1024*1024, bindings)),
            manifest_sha256=b.digest(w.remember(args.assets/'ai-rules.json', w.MAX_JSON, bindings)))
        b.require(identity == expected, 'retained AI identity differs')
        source.update(setup=setup, roster=roster, ai=expected,
                      bots=[ai.recorded_bodies(payload, roster, frame) for frame, payload in enumerate(payloads)])
    return source


async def run_arm(args, source, backend, mode, output, reference_path, *, profiled=False,
                  thread_sample_interval=0):
    """Reusable arm for a separate SAME-mode control/profile pair; never mixed in primary pairs."""
    output.mkdir()
    workdir = output/'worker'
    workdir.mkdir()
    frozen = sources()
    ref = source['reference']
    report = dict(passed=False, native_qualified=False, frames=0, state_mode=mode,
        state_projection_version=1, profiled=profiled, paced=False, timestep_ms=50,
        state_projection={'version': 1, 'step_mode': mode},
        state_projection_modes=['summary', 'full', 'ownership'],
        profile_thread_interval=thread_sample_interval if profiled else None,
        source_at_start=frozen, ai=source.get('ai'), replay=str(args.journal),
        workload=ref['workload'], replayed_source_hashes=ref['journal_source_hashes'],
        simulation_sha256=ref['simulation_sha256'], bootstrap_sha256=ref['bootstrap_sha256'],
        asset_manifest_sha256=ref['asset_manifest_sha256'], input_journal_sha256=ref['journal_files']['frames.bin'],
        memory={'available': False, 'reason': 'no retained native-handle memory sampler installed'},
        response_bytes_scope='actual IPC header+metadata+payload lengths recorded by worker transport')
    worker, rows = None, []
    bot_hash = hashlib.sha256()
    post_join_actions = {str(army): 0 for army in source['roster'].bots} if source['setup'] is not None else {}
    history, reference_history = {}, {}
    writing = mode == 'full' and not reference_path.exists()
    reference_stream = None
    try:
        if writing:
            reference_stream = reference_path.open('x', encoding='utf-8')
        else:
            reference_stream = reference_path.open('r', encoding='utf-8')
        def check(state, frame):
            if mode == 'full':
                expected = projection(state)
                digest = b.state_digest(state)
            else:
                expected, digest = None, None
            if writing:
                entry = dict(frame=frame, full_state_sha256=digest, projected=expected)
                reference_stream.write(json.dumps(entry, separators=(',', ':'), allow_nan=False)+'\n')
            else:
                line = reference_stream.readline(MAX_REFERENCE+1)
                b.require(line and len(line) <= MAX_REFERENCE, 'truncated/oversized full projection reference')
                entry = json.loads(line)
                b.require(entry['frame'] == frame, 'full projection reference frame differs')
                resources = entry['projected']['resources']
                b.require(all(type(key) is str and key.isascii() and key.isdecimal()
                              and str(int(key)) == key and int(key) <= 0xffffffff for key in resources),
                          'noncanonical reference resource keys')
                entry['projected']['resources'] = {int(key): value for key, value in resources.items()}
                if mode == 'full':
                    b.require(digest == entry['full_state_sha256'], 'full diagnostic state differs across arms')
                compare_projection(projection(state) if mode == 'full' else state, entry['projected'], same_raw=False)
            update_history(history, state, mode)
            update_history(reference_history, entry['projected'], 'ownership')
            b.require(history == reference_history, 'cumulative command-owner history differs')
            return entry
        async with asyncio.timeout(args.timeout_seconds):
            kwargs = dict(working_directory=workdir, backend=backend, ai=source['setup'], state_mode=mode,
                startup_timeout=min(120, args.timeout_seconds), request_timeout=15, close_timeout=3,
                snapshot_decoder_library=args.library, snapshot_decoder_sha256=args.library_sha256)
            began = time.perf_counter()
            if profiled:
                from tools.profile_worker_timing import create_profiled_worker
                worker = await create_profiled_worker(source['data'], args.assets/'Simulation.dll',
                    profile_path=output/'worker-profile.json', max_records=20000,
                    thread_sample_interval=thread_sample_interval, **kwargs)
            else:
                worker = await SimulationWorker.create(source['data'], args.assets/'Simulation.dll', **kwargs)
            report.update(startup_ms=(time.perf_counter()-began)*1000, worker_pid=worker.pid,
                          native_worker_pid=worker.native_pid, worker_runtime=worker.runtime_info,
                          snapshot_decoder=worker.decoder_info, backend=b.backend_identity(backend))
            b.require(not worker._test_backend and worker.game_data_sha256 == ref['bootstrap_sha256']
                      and worker.dll_sha256 == ref['simulation_sha256'], 'native worker identity differs')
            b.require(worker.decoder_info == ai.decoder_identity(args, 'rust', backend), 'decoder identity differs')
            b.require(worker.state_mode == mode and worker.projection_version == 1, 'projection negotiation differs')
            b.require(worker.state_projection_info == {'version': 1, 'step_mode': mode}
                      and worker.state_projection_modes == ['summary', 'full', 'ownership'], 'actual CREATE projection claims differ')
            report.update(state_projection=worker.state_projection_info, state_projection_modes=worker.state_projection_modes)
            runtime = worker.runtime_info
            b.require(runtime.get('os_name') == 'nt' and runtime.get('platform') == 'win32'
                      and runtime.get('pointer_bits') == 64 and runtime.get('implementation') == 'cpython'
                      and all(isinstance(runtime.get(key), str) and runtime[key] for key in ('python_version', 'executable')),
                      'worker Windows x64 runtime differs')
            b.require(worker.ai_info == source.get('ai'), 'worker AI identity differs')
            initial = await worker.state(31, mode=mode)
            b.require(initial['frame'] == 0xffffffff, 'initial native frame differs')
            initial_entry = check(initial, -1)
            report['initial_full_state_sha256'] = initial_entry['full_state_sha256']
            report['initial_raw_sha256'] = initial['raw_sha256']
            report['initial_reference_raw_sha256'] = initial_entry['projected']['raw_sha256']
            # Full diagnostic availability outside STEP timing, in every session.
            diagnostic = await worker.state(31, mode='full')
            b.require(b.state_digest(diagnostic) == report['initial_full_state_sha256'], 'initial full diagnostic differs')
            report['memory_before_replay'] = memory_sample(worker, backend)
            with (output/'frames.jsonl').open('x', encoding='utf-8') as trace:
                for frame, (payload, retained) in enumerate(zip(source['payloads'], source['rows'])):
                    ai_ms = 0.0
                    if source['setup'] is not None:
                        began = time.perf_counter()
                        actual = await worker.bot_inputs(frame)
                        ai_ms = (time.perf_counter()-began)*1000
                        source['roster'].check_inputs(actual)
                        b.require(actual == source['bots'][frame], f'fresh original AI bytes differ at frame{frame}')
                        source['roster'].check_frame(payload, actual)
                        bot_hash.update(ai.pack_inputs(actual))
                        if frame:
                            for army, body in actual.items():
                                post_join_actions[str(army)] += len(get_repeated_bytes(body, 2))
                    began = time.perf_counter()
                    result = await worker.process_frame(payload, dt_ms=50)
                    elapsed = (time.perf_counter()-began)*1000
                    reply_bytes = worker.last_response_bytes
                    b.require(type(reply_bytes) is int and reply_bytes > 0, 'actual STEP response bytes unavailable')
                    b.require(result.frame == frame and result.state['frame'] == frame, 'STEP frame differs')
                    b.require(b.digest(payload) == retained['input_sha256'], 'input digest differs')
                    if mode == 'full':
                        b.check_record(frame, payload, result.state, retained)
                    reference_entry = check(result.state, frame)
                    full_digest = reference_entry['full_state_sha256']
                    b.require(full_digest == retained['state_sha256'], 'full reference differs from retained original state')
                    row = dict(frame=frame, phase=retained['phase'], input_sha256=b.digest(payload),
                        state_sha256=b.state_digest(result.state), full_reference_state_sha256=full_digest,
                        history_sha256=history_digest(history), step_rpc_ms=elapsed, reply_bytes=reply_bytes,
                        raw_sha256=result.state['raw_sha256'], reference_raw_sha256=reference_entry['projected']['raw_sha256'],
                        raw_hash_equal=result.state['raw_sha256'] == reference_entry['projected']['raw_sha256'],
                        ai_rpc_ms=ai_ms, work_ms=ai_ms+elapsed, pacing_late_ms=0.0)
                    rows.append(row)
                    trace.write(json.dumps(row, separators=(',', ':'), allow_nan=False)+'\n')
                    report['frames'] += 1
            if not writing:
                b.require(not reference_stream.read(1), 'extra full projection reference frames')
            report['memory'] = memory_sample(worker, backend)
            b.require(source['setup'] is None or (post_join_actions and all(post_join_actions.values())),
                      'fresh AI proof requires post-join decisions for every bot')
            report.update(passed=True, native_qualified=True, actual_bot_journal_sha256=bot_hash.hexdigest(),
                          post_join_actions=post_join_actions)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if reference_stream:
            reference_stream.close()
        if worker is not None:
            try:
                await worker.close()
            except BaseException as error:
                report['cleanup_error'] = repr(error)
            report['cleanup'] = dict(exit_code=worker.process.poll(), failure=worker.failure,
                stderr_thread_closed=not worker._stderr_thread.is_alive(),
                io_threads_closed=all(not thread.is_alive() for thread in worker._io._threads))
            report['backend_statistics'] = worker.backend_statistics
        report['source_at_finish'] = sources()
        report['source_unchanged'] = report['source_at_finish'] == frozen
        report['passed'] &= (w.clean_exit(report) and report['source_unchanged']
            and (backend is None or b.backend_cleanup_complete(report.get('backend_statistics'))))
        report['native_qualified'] = report['passed']
        if not report['passed'] and 'error' not in report:
            report['error'] = 'worker cleanup or source stability failed'
        report['phases'] = {phase: dict(frames=sum(row['phase'] == phase for row in rows),
            timings_ms={metric: b.summary([row[metric] for row in rows if row['phase'] == phase])
                        for metric in ('step_rpc_ms', 'ai_rpc_ms', 'work_ms', 'pacing_late_ms')},
            reply_bytes={key: value for key, value in b.summary(
                [row['reply_bytes'] for row in rows if row['phase'] == phase]).items()
                if key not in ('above_50ms', 'above_100ms')}) for phase in c.PHASES}
        (output/'frames.bin').write_bytes(source['inputs'])
        if profiled and (output/'worker-profile.json').exists():
            report['worker_profile_sha256'] = b.digest((output/'worker-profile.json').read_bytes())
        c.write_json(output/'benchmark.json', report)
    return report


async def run(args):
    validate_args(args)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, passed=False, scope=__doc__, pairs=[], requested_pairs=3,
                  fresh_ai=args.fresh_ai, room_lifecycle_exercised=False, performance_acceptance_evaluated=False)
    report['initial_state_scope'] = 'initial0xffffffff compared across explicit modes and full diagnostic query; N47 journal starts at STEP0'
    report['raw_hash_scope'] = 'all9 common fields on SAME raw corpus; separately acquired replay buffers compare8 semantic fields and retain actual/reference raw hashes'
    bindings, source = {}, None
    try:
        report['source_at_start'] = sources()
        raw = w.remember(args.library, w.MAX_LIBRARY, bindings, args.library_sha256)
        b.require(raw.startswith(b'MZ'), 'Windows worker requires explicit PE library')
        if args.build_receipt:
            report['build_receipt_sha256'] = b.digest(w.remember(args.build_receipt, w.MAX_JSON, bindings))
        report['build_provenance_scope'] = 'receipt bytes bound if supplied; T7 must independently review source/build correspondence'
        source = load_inputs(args, bindings)
        report['reference'] = source['reference']
        report['baseline_inputs_sha256'] = source['baseline_inputs_sha256']
        if args.same_raw_report:
            same_raw = json.loads(w.remember(args.same_raw_report.resolve(), MAX_REFERENCE, bindings, args.same_raw_report_sha256))
            b.require(same_raw.get('schema') == 1 and same_raw.get('passed') is True
                      and same_raw.get('inputs_unchanged') is True and same_raw.get('source_sha256') == sources()
                      and same_raw.get('execution_platform') == 'win32'
                      and same_raw.get('library_sha256') == args.library_sha256
                      and isinstance(same_raw.get('evidence_sha256'), dict) and same_raw['evidence_sha256'],
                      'same-raw Windows evidence provenance differs')
        else:
            same_raw = validate_corpora(args, bindings)
        b.require(any(entry['reference']['journal_files'] == source['reference']['journal_files']
                      and entry['reference']['simulation_sha256'] == source['reference']['simulation_sha256']
                      and entry['reference']['asset_manifest_sha256'] == source['reference']['asset_manifest_sha256']
                      for entry in same_raw['corpora']), 'same-raw corpus does not cover this replay journal')
        report['same_raw'] = same_raw
        c.write_json(args.output/'same-raw.json', same_raw)
        w.remember(args.output/'same-raw.json', MAX_REFERENCE, bindings)
        for path in ([Path(sys.executable)] if not b.wine_requested(args) else
                     [args.wine_executable, args.windows_python]):
            w.remember(path.resolve(), 128*1024*1024, bindings)
        backend = b.select_backend(args)
        runtime = None
        reference_path = args.output/'full-projection-reference.jsonl'
        for pair in range(3):
            order = ('full', 'ownership') if pair % 2 == 0 else ('ownership', 'full')
            result = dict(pair=pair+1, order=order)
            for mode in order:
                output = args.output/f'pair{pair+1}-{mode}'
                arm = await run_arm(args, source, backend, mode, output, reference_path)
                result[mode] = arm
                for name in ('benchmark.json', 'frames.jsonl', 'frames.bin'):
                    if (output/name).exists():
                        w.remember(output/name, c.JOURNAL_LIMITS.get(name, w.MAX_JSON), bindings)
                b.require(arm['passed'], 'arm failed; preserve its benchmark report')
                if runtime is None:
                    runtime = arm['worker_runtime']
                b.require(runtime == arm['worker_runtime'], 'arm worker runtimes differ')
                if not any(str(reference_path) == name for name in bindings):
                    w.remember(reference_path, MAX_REFERENCE, bindings)
            b.require(result['full']['actual_bot_journal_sha256'] == result['ownership']['actual_bot_journal_sha256'],
                      'fresh AI journals differ across modes')
            report['pairs'].append(result)
            c.write_json(args.output/f'pair{pair+1}.json', result)
            w.remember(args.output/f'pair{pair+1}.json', w.MAX_JSON, bindings)
        report['performance'] = performance_summary(report['pairs'])
        report['step_performance_acceptance_evaluated'] = True
        report['passed'] = True
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        errors = []
        try:
            report['source_at_finish'] = sources()
            b.require(report.get('source_at_start') == report['source_at_finish'], 'source changed')
            for path, identity in bindings.items():
                b.require(b.digest(w.read_file(Path(path), identity['limit'])) == identity['sha256'], 'bound file changed: '+path)
            if source is not None:
                c.check_stability(args, source['reference'])
        except BaseException as error:
            errors.append(repr(error))
        report['source_unchanged'] = report.get('source_at_start') == report.get('source_at_finish')
        report['inputs_library_and_evidence_unchanged'] = not errors
        report['stability_errors'] = errors
        report['passed'] &= not errors
        if errors:
            report.setdefault('error', 'verification stability failed; see stability_errors')
        c.write_json(args.output/'verification.json', report)
    print(json.dumps(dict(passed=report['passed'], pairs=len(report['pairs']), error=report.get('error'))), flush=True)
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'journal', 'library', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--library-sha256', required=True)
    parser.add_argument('--build-receipt', type=Path)
    parser.add_argument('--baseline-inputs', type=Path,
                        default=ROOT/'local/compact-state-20261117/baseline-inputs.json')
    parser.add_argument('--corpus', type=Path, action='append', default=[])
    parser.add_argument('--same-raw-report', type=Path)
    parser.add_argument('--same-raw-report-sha256')
    parser.add_argument('--pairs', type=int, default=3)
    parser.add_argument('--timeout-seconds', type=float, default=600)
    parser.add_argument('--fresh-ai', action='store_true')
    for name in WINE_OPTIONS:
        parser.add_argument('--'+name.replace('_', '-'), type=Path)
    return parser.parse_args(argv)


def performance_summary(pairs):
    result = {}
    for phase in ('movement', 'combat'):
        comparisons = []
        for pair in pairs:
            full = pair['full']['phases'][phase]['timings_ms']['step_rpc_ms']
            compact = pair['ownership']['phases'][phase]['timings_ms']['step_rpc_ms']
            comparisons.append(dict(pair=pair['pair'], full_mean_ms=full['mean'], ownership_mean_ms=compact['mean'],
                full_p95_ms=full['p95'], ownership_p95_ms=compact['p95'],
                mean_improved=compact['mean'] < full['mean'],
                p95_within_tolerance=compact['p95'] <= full['p95'] + max(1., .05*full['p95'])))
        result[phase] = dict(pairs=comparisons, repeated_step_improvement=all(row['mean_improved'] for row in comparisons),
            p95_gate_passed=all(row['p95_within_tolerance'] for row in comparisons))
    return dict(scope='unpaced owned worker STEP only; no cadence or player acceptance',
                three_pairs_required=True, pair_count=len(pairs), phases=result,
                passed=len(pairs) == 3 and all(row['repeated_step_improvement'] and row['p95_gate_passed']
                                               for row in result.values()))


if __name__ == '__main__':
    raise SystemExit(asyncio.run(run(arguments())))
