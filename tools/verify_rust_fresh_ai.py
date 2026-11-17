"""Private fresh original-AI parity proof for Python and Rust snapshot decoders.

Each arm owns a new simulation/AI worker. Original AI decisions are regenerated,
compared byte-for-byte with the retained journal, then the identical recorded
frame is stepped and every observable state is checked. No listeners, gameplay
UI or live hosts are used. This accelerated correctness check is not a timing or
Internet gameplay qualification. Original assets and output remain private.
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
import re
import sys
import traceback
from types import SimpleNamespace

from server.game_data import decode_frame, encode_frame, encode_player_input
from server.protobuf_wire import get_bytes, get_repeated_bytes
from server.worker_ai import AISetup, BotRoster, pack_inputs
from server.worker_client import SimulationWorker
from tools import benchmark_large_armies as b
from tools import capture_snapshot_corpus as c
from tools import verify_rust_worker as binding

ROOT = b.ROOT


def source_hashes():
    return {**binding.sources(), **{name: b.digest((ROOT / name).read_bytes()) for name in
            ('tools/verify_rust_fresh_ai.py', 'tests/test_rust_fresh_ai.py')}}


def validate_args(args):
    hybrid = b.wine_requested(args)
    b.require(sys.platform.startswith('linux') if hybrid else sys.platform == 'win32',
              'explicit Wine backend requires Linux; default workers require Windows; no fallback')
    b.require(math.isfinite(args.timeout_seconds) and 10 <= args.timeout_seconds <= 900, 'timeout outside 10..900 seconds')
    b.require(isinstance(args.library_sha256, str) and re.fullmatch('[0-9a-f]{64}', args.library_sha256),
              'explicit lowercase library SHA256 required')
    b.require(not os.path.lexists(args.output), 'fresh private output required')
    args.corpus, args.library, args.output = (path.resolve() for path in (args.corpus, args.library, args.output))
    local = (ROOT / 'local').resolve()
    b.require(args.output != local and args.output.is_relative_to(local), 'output must be inside ignored local/')
    b.require(args.corpus.is_dir() and args.corpus.is_relative_to(local), 'private local corpus required')
    for path in (args.corpus, args.library):
        b.require(not path.is_relative_to(args.output) and not args.output.is_relative_to(path), 'input/output paths overlap')
    for name in ('assets', 'journal'):
        value = getattr(args, name, None)
        if value is not None:
            setattr(args, name, value.resolve())


def recorded_bodies(payload, roster, frame):
    decoded = decode_frame(payload)
    b.require(decoded['frame'] == frame and decoded['timestep_ms'] == 50 and decoded['frames_per_second'] == 20
              and decoded['speed'] == 1.0 and decoded['spectator_count'] == 0, 'recorded frame header differs')
    identities = {identity: army for army, identity in roster.identities.items()}
    bodies = {army: encode_player_input(identity) for army, identity in roster.identities.items()}
    seen = set()
    for body in decoded['players']:
        army = identities.get(get_bytes(body, 1, required=True))
        b.require(army is not None and army not in seen, 'unknown/duplicate recorded player identity')
        bodies[army] = body
        seen.add(army)
    b.require(encode_frame(frame, bodies) == payload, 'recorded frame is not canonical')
    return {army: bodies[army] for army in roster.bots}


def load_inputs(args, identities):
    raw = binding.remember(args.corpus / 'manifest.json', binding.MAX_JSON, identities)
    manifest = json.loads(raw)
    b.require(manifest.get('schema') == 1 and manifest.get('passed') is True
              and manifest.get('native_qualified') is True and manifest.get('source_unchanged') is True
              and manifest.get('reference_unchanged') is True and binding.clean_exit(manifest)
              and manifest.get('source_at_start') and manifest['source_at_start'] == manifest.get('source_at_finish'),
              'qualified stable native corpus required')
    captured = manifest['reference']
    assets = args.assets or Path(captured['assets'])
    journal = args.journal or Path(captured['journal'])
    b.require(assets.is_dir() and journal.is_dir(), 'retained inputs missing; use explicit --assets/--journal when relocated')
    for path in (assets.resolve(), journal.resolve()):
        b.require(not path.is_relative_to(args.output) and not args.output.is_relative_to(path), 'retained input/output paths overlap')
    selected = SimpleNamespace(assets=assets.resolve(), journal=journal.resolve())
    data, inputs, rows, _, _, reference = c.load_reference(selected)
    b.require({key: value for key, value in reference.items() if key not in ('assets', 'journal')}
              == {key: value for key, value in captured.items() if key not in ('assets', 'journal')}, 'capture/reference binding differs')
    b.require(type(manifest['verified_frames']) is int and manifest['verified_frames'] == len(rows), 'capture frame count differs')
    report = json.loads(binding.read_file(selected.journal / 'benchmark.json', c.JOURNAL_LIMITS['benchmark.json']))
    ai = report['ai']
    b.require(isinstance(ai, dict) and isinstance(ai.get('bots'), dict)
              and all(key in ('0', '1', '2', '3') for key in ai['bots']), 'reference AI assignment missing')
    bots = {int(army): profile for army, profile in ai['bots'].items()}
    setup = AISetup(selected.assets, bots)
    roster = BotRoster(data, bots)
    spec = reference['workload']
    b.require(spec.get('opponent') == 'ai', 'fresh-AI proof requires an original AI workload')
    if spec.get('ai_profiles') is not None:
        b.require(spec['ai_profiles'] == setup.wire()['bots'], 'workload AI profiles differ')
    else:
        b.require(len(roster.armies) == 2 and bots == {1: spec.get('ai_profile')}, 'legacy workload AI profile differs')
    expected_ai = dict(bots=setup.wire()['bots'],
        dll_sha256=b.digest(binding.remember(selected.assets / 'aiprogram.dll', 128 * 1024 * 1024, identities)),
        manifest_sha256=b.digest(binding.remember(selected.assets / 'ai-rules.json', binding.MAX_JSON, identities)))
    b.require(ai == expected_ai, 'reference AI DLL/rule manifest differs')
    payloads, expected_bots = [], []
    with io.BytesIO(inputs) as stream:
        for frame, row in enumerate(rows):
            payload = b.read_frame(stream)
            payloads.append(payload)
            expected_bots.append(recorded_bodies(payload, roster, frame))
        b.require(not stream.read(1), 'extra recorded frames')
    return dict(data=data, rows=rows, payloads=payloads, bots=expected_bots, setup=setup, roster=roster,
                reference=reference, captured_paths=dict(assets=captured['assets'], journal=captured['journal']), ai=expected_ai)


def decoder_identity(args, kind, backend):
    if kind == 'python':
        return {'implementation': 'python'}
    path = str(args.library) if backend is None else backend.translate_path(args.library)
    return dict(implementation='rust', abi_version=1, library_sha256=args.library_sha256, library_path=path)


async def run_arm(args, kind, source, backend):
    output = args.output / kind
    output.mkdir()
    worker_dir = output / 'worker'
    worker_dir.mkdir()
    report = dict(passed=False, native_qualified=False, decoder=kind, verified_frames=0, prepared_frames=0,
                  post_join_actions={str(army): 0 for army in source['roster'].bots})
    worker = None
    expected_digest, actual_digest = hashlib.sha256(), hashlib.sha256()
    try:
        async with asyncio.timeout(args.timeout_seconds):
            kwargs = dict(working_directory=worker_dir, ai=source['setup'], backend=backend,
                          startup_timeout=min(120, args.timeout_seconds), request_timeout=15, close_timeout=3)
            if kind == 'rust':
                kwargs.update(snapshot_decoder_library=args.library, snapshot_decoder_sha256=args.library_sha256)
            worker = await SimulationWorker.create(source['data'], source['setup'].directory / 'Simulation.dll', **kwargs)
            report.update(worker_pid=worker.pid, native_worker_pid=getattr(worker, 'native_pid', worker.pid),
                          worker_runtime=worker.runtime_info, snapshot_decoder=worker.decoder_info, ai=worker.ai_info,
                          game_data_sha256=worker.game_data_sha256, simulation_sha256=worker.dll_sha256)
            b.require(not worker._test_backend and worker.game_data_sha256 == source['reference']['bootstrap_sha256']
                      and worker.dll_sha256 == source['reference']['simulation_sha256'], 'native worker identity differs')
            b.require(worker.decoder_info == decoder_identity(args, kind, backend), 'worker decoder identity differs')
            b.require(worker.ai_info == source['ai'], 'worker AI identity differs')
            runtime = worker.runtime_info
            b.require(isinstance(runtime, dict) and runtime.get('os_name') == 'nt' and runtime.get('platform') == 'win32'
                      and runtime.get('pointer_bits') == 64 and runtime.get('implementation') == 'cpython'
                      and all(isinstance(runtime.get(key), str) and runtime[key] for key in ('python_version', 'executable')),
                      'worker runtime identity missing')
            with (output / 'frames.jsonl').open('x', encoding='utf-8') as trace:
                for frame, (payload, expected, row) in enumerate(zip(source['payloads'], source['bots'], source['rows'])):
                    report['current_frame'] = frame
                    actual = await worker.bot_inputs(frame)
                    report['prepared_frames'] += 1
                    source['roster'].check_inputs(actual)
                    expected_bytes, actual_bytes = pack_inputs(expected), pack_inputs(actual)
                    report['current_expected_bot_sha256'] = b.digest(expected_bytes)
                    report['current_actual_bot_sha256'] = b.digest(actual_bytes)
                    b.require(actual == expected, f'fresh AI decisions differ at frame {frame}')
                    source['roster'].check_frame(payload, actual)
                    result = await worker.process_frame(payload, dt_ms=50)
                    b.require(result.frame == frame, 'completed worker frame differs')
                    b.check_record(frame, payload, result.state, row)
                    expected_digest.update(expected_bytes)
                    actual_digest.update(actual_bytes)
                    for army, body in actual.items():
                        if frame:
                            report['post_join_actions'][str(army)] += len(get_repeated_bytes(body, 2))
                    report['verified_frames'] += 1
                    trace.write(json.dumps(dict(frame=frame, phase=row['phase'], input_sha256=b.digest(payload),
                        bot_inputs_sha256=b.digest(actual_bytes), state_sha256=b.state_digest(result.state)), sort_keys=True) + '\n')
            b.require(report['verified_frames'] == len(source['rows']) and all(report['post_join_actions'].values()),
                      'fresh AI proof did not cover every frame and post-join bot decisions')
        report.update(passed=True, native_qualified=True)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if worker is not None:
            try:
                await worker.close()
            except BaseException as error:
                report['cleanup_error'] = repr(error)
            report['cleanup'] = dict(exit_code=worker.process.poll(), failure=worker.failure,
                stderr_thread_closed=not worker._stderr_thread.is_alive(),
                io_threads_closed=all(not thread.is_alive() for thread in worker._io._threads))
            report['backend_statistics'] = worker.backend_statistics
        clean = binding.clean_exit(report)
        if backend is not None:
            clean &= b.backend_cleanup_complete(report.get('backend_statistics'))
        report['passed'] &= clean
        report['native_qualified'] &= report['passed']
        if not report['passed'] and 'error' not in report:
            report['error'] = 'worker cleanup failed'
        report.update(expected_bot_journal_sha256=expected_digest.hexdigest(), actual_bot_journal_sha256=actual_digest.hexdigest())
        trace = output / 'frames.jsonl'
        if trace.exists():
            report['frames_sha256'] = b.digest(binding.read_file(trace, 64 * 1024 * 1024))
        c.write_json(output / 'verification.json', report)
    return report


async def run(args):
    validate_args(args)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, passed=False, scope=__doc__, arms=[], timeout_per_arm_seconds=args.timeout_seconds,
                  performance_acceptance_evaluated=False)
    identities, source = {}, None
    try:
        report['source_at_start'] = source_hashes()
        raw_library = binding.remember(args.library, binding.MAX_LIBRARY, identities, args.library_sha256)
        b.require(raw_library.startswith(b'MZ'), 'Windows worker requires a PE decoder library')
        source = load_inputs(args, identities)
        report.update(reference=source['reference'], captured_paths=source['captured_paths'],
                      library_sha256=args.library_sha256, expected_frames=len(source['rows']), ai=source['ai'])
        backend = b.select_backend(args)
        report['backend'] = b.backend_identity(backend)
        runtime = None
        for kind in ('python', 'rust'):
            reference = source['reference']
            c.check_stability(SimpleNamespace(assets=Path(reference['assets']), journal=Path(reference['journal'])), reference)
            binding.remember(args.library, binding.MAX_LIBRARY, identities, args.library_sha256)
            arm = await run_arm(args, kind, source, backend)
            report['arms'].append(arm)
            b.require(arm['passed'] and arm['native_qualified'], f'{kind} fresh-AI verification failed; see arm report')
            if runtime is None:
                runtime = arm['worker_runtime']
            b.require(runtime == arm['worker_runtime'], 'worker runtimes differ between decoder arms')
        b.require(report['arms'][0]['actual_bot_journal_sha256'] == report['arms'][1]['actual_bot_journal_sha256'],
                  'decoder arms produced different AI journals')
        report['passed'] = True
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        errors = []
        try:
            report['source_at_finish'] = source_hashes()
            report['source_unchanged'] = report.get('source_at_start') == report['source_at_finish']
            b.require(report['source_unchanged'], 'verification source changed')
        except BaseException as error:
            report['source_unchanged'] = False
            errors.append(f'source: {type(error).__name__}: {error}')
        try:
            for path, identity in identities.items():
                b.require(b.digest(binding.read_file(Path(path), identity['limit'])) == identity['sha256'], f'input changed: {path}')
            if source is not None:
                reference = source['reference']
                c.check_stability(SimpleNamespace(assets=Path(reference['assets']), journal=Path(reference['journal'])), reference)
            report['inputs_unchanged'] = True
        except BaseException as error:
            report['inputs_unchanged'] = False
            errors.append(f'input: {type(error).__name__}: {error}')
        report['passed'] &= report['source_unchanged'] and report['inputs_unchanged']
        if errors:
            report['stability_errors'] = errors
            report.setdefault('error', 'verification inputs/source changed')
        c.write_json(args.output / 'verification.json', report)
    print(json.dumps(dict(passed=report['passed'], arms=len(report['arms']), error=report.get('error'))), flush=True)
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--assets', type=Path, help='explicit relocated assets; exact captured hashes required')
    parser.add_argument('--journal', type=Path, help='explicit relocated journal; exact captured hashes required')
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--library-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=float, default=600)
    parser.add_argument('--wine-executable', type=Path)
    parser.add_argument('--windows-python', type=Path)
    parser.add_argument('--wine-prefix-template', type=Path)
    parser.add_argument('--wine-cgroup-parent', type=Path)
    return asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    raise SystemExit(main())
