"""Capture private original snapshots from a verified benchmark input journal.

Run with ``python -m tools.capture_snapshot_corpus`` on Windows. This replays
recorded inputs, including recorded AI decisions, without regenerating AI. Every
observable state must match the retained reference; hidden DLL state is outside
that comparison. Outputs contain original game data: keep them in ignored local/
storage, never Git or public CI. Capture elapsed time is not benchmark evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import io
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import traceback

from server.assets import verify_assets
from server.native_simulation import decode_snapshot
from server.worker_client import SimulationWorker
from tools import benchmark_large_armies as benchmark

ROOT = Path(__file__).resolve().parents[1]
PHASES = ('setup', 'movement', 'combat')
MAX_BOOTSTRAP = 32 * 1024 * 1024
JOURNAL_LIMITS = {'benchmark.json': 4 * 1024 * 1024,
                  'bootstrap.pb.gz': MAX_BOOTSTRAP,
                  'frames.jsonl': 128 * 1024 * 1024,
                  'frames.bin': 256 * 1024 * 1024}
require, digest = benchmark.require, benchmark.digest


def bounded_read(path, limit):
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, f'{path.name} exceeds capture size limit')
    return data


def source_hashes():
    result = benchmark.source_hashes()
    result['tools/capture_snapshot_corpus.py'] = digest(Path(__file__).read_bytes())
    return result


def validate_args(args):
    require(sys.platform == 'win32', 'capture requires an owned native Windows worker; no backend fallback')
    require(math.isfinite(args.timeout_seconds) and 10 <= args.timeout_seconds <= 900,
            'capture timeout must be between 10 and 900 seconds')
    require(not os.path.lexists(args.output), 'output already exists; preserve previous captures')
    args.assets, args.journal, args.output = (p.resolve() for p in (args.assets, args.journal, args.output))
    local = (ROOT / 'local').resolve()
    require(args.output != local and args.output.is_relative_to(local), 'fresh ignored local/ output required')
    for source in (args.assets, args.journal):
        require(source.is_dir(), f'input directory does not exist: {source}')
        require(not args.output.is_relative_to(source) and not source.is_relative_to(args.output),
                'output and input directories must be separate')


def select_frames(rows):
    require(1 <= len(rows) <= benchmark.MAX_FRAMES, 'reference frame count outside bounds')
    indices = {phase: [] for phase in PHASES}
    previous = 0
    for frame, row in enumerate(rows):
        require(type(row['frame']) is int and row['frame'] == frame, 'nonsequential reference frame')
        require(row['phase'] in PHASES, 'unknown reference phase')
        phase = PHASES.index(row['phase'])
        require(phase >= previous, 'reference phases moved backwards')
        previous = phase
        indices[row['phase']].append(frame)
    require(all(indices.values()), 'reference workload phases missing')
    selected = {frames[index] for frames in indices.values() for index in (0, len(frames) // 2, -1)}
    return sorted(selected), {frames[-1] for frames in indices.values()}


def load_reference(args):
    verify_assets(args.assets)
    files = {name: bounded_read(args.journal / name, limit) for name, limit in JOURNAL_LIMITS.items()}
    report = json.loads(files['benchmark.json'])
    require(report.get('passed') is True and report.get('native_qualified') is True,
            'reference must be a successful native benchmark')
    require(report.get('source_unchanged') is True and report.get('source_at_start')
            and report['source_at_start'] == report.get('source_at_finish'), 'reference source was not stable')
    manifest_sha = digest(bounded_read(args.assets / 'asset-manifest.json', 4 * 1024 * 1024))
    dll_sha = digest(bounded_read(args.assets / 'Simulation.dll', 128 * 1024 * 1024))
    require(manifest_sha == report['asset_manifest_sha256'], 'reference asset manifest differs')
    require(dll_sha == report['simulation_sha256'], 'reference simulation DLL differs')
    require(digest(files['frames.bin']) == report['input_journal_sha256'], 'input journal digest differs')
    rows = [json.loads(line) for line in files['frames.jsonl'].splitlines()]
    require(len(rows) == report['frames'], 'reference frame count differs')
    selected, viewer_frames = select_frames(rows)
    with gzip.GzipFile(fileobj=io.BytesIO(files['bootstrap.pb.gz'])) as stream:
        data = stream.read(MAX_BOOTSTRAP + 1)
    require(len(data) <= MAX_BOOTSTRAP and digest(data) == report['bootstrap_sha256'], 'reference bootstrap differs')
    with io.BytesIO(files['frames.bin']) as stream:
        for row in rows:
            require(digest(benchmark.read_frame(stream)) == row['input_sha256'], 'recorded input digest differs')
        require(not stream.read(1), 'extra input journal bytes')
    reference = dict(journal=str(args.journal), assets=str(args.assets),
                     journal_files={name: digest(raw) for name, raw in files.items()},
                     asset_manifest_sha256=manifest_sha, bootstrap_sha256=digest(data),
                     simulation_sha256=dll_sha, workload=report['workload'],
                     journal_source_hashes=report['source_at_start'])
    return data, files['frames.bin'], rows, selected, viewer_frames, reference


def write_json(path, value):
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    with path.open('xb') as stream:
        stream.write(data)
    return digest(data)


async def save_snapshot(worker, output, frame, phase, viewer, expected):
    raw = await worker.snapshot(viewer=viewer)
    require(0 < len(raw) <= 16 * 1024 * 1024, 'snapshot size outside worker protocol bounds')
    stem = f'f{frame:06d}-v{viewer:02d}'
    filename, full_name, summary_name = stem + '.snapshot', stem + '.expected.json', stem + '.summary.json'
    # Retain original returned bytes even if decoding or reference comparison fails.
    with (output / filename).open('xb') as stream:
        stream.write(raw)
    full = decode_snapshot(raw, viewer=viewer, include_entities=True)
    summary = decode_snapshot(raw, viewer=viewer, include_entities=False)
    require(full['frame'] == frame and summary['frame'] == frame, 'snapshot frame differs')
    require(benchmark.state_digest(full) == benchmark.state_digest(expected), 'snapshot observable state differs')
    require({key: value for key, value in full.items() if key != 'entities'} == summary,
            'full and summary decoders disagree')
    full_sha = write_json(output / full_name, full)
    summary_sha = write_json(output / summary_name, summary)
    return dict(id=stem, frame=frame, phase=phase, viewer=viewer, include_entities=True,
                snapshot_file=filename, snapshot_sha256=digest(raw), bytes=len(raw),
                expected_file=full_name, expected_sha256=full_sha,
                expected_summary_file=summary_name, expected_summary_sha256=summary_sha,
                observable_state_sha256=benchmark.state_digest(full))


def check_stability(args, reference):
    verify_assets(args.assets)
    require(digest(bounded_read(args.assets / 'asset-manifest.json', 4 * 1024 * 1024))
            == reference['asset_manifest_sha256'], 'asset manifest changed during capture')
    require(digest(bounded_read(args.assets / 'Simulation.dll', 128 * 1024 * 1024))
            == reference['simulation_sha256'], 'simulation DLL changed during capture')
    require({name: digest(bounded_read(args.journal / name, limit)) for name, limit in JOURNAL_LIMITS.items()}
            == reference['journal_files'], 'reference journal changed during capture')


async def run(args):
    validate_args(args)
    args.output.mkdir(parents=True, exist_ok=False)
    workdir = args.output / 'worker'
    workdir.mkdir()
    report = dict(schema=1, passed=False, native_qualified=False, scope=__doc__, snapshots=[],
                  source_at_start=source_hashes(), verified_frames=0, platform=platform.platform(),
                  python=sys.version, timestep_ms=50, timeout_seconds=args.timeout_seconds)
    worker, started = None, time.perf_counter()
    try:
        data, inputs, rows, selected, viewer_frames, reference = load_reference(args)
        report.update(reference=reference, selection=selected, viewer_frames=sorted(viewer_frames))
        async with asyncio.timeout(args.timeout_seconds):
            # Recorded AI bytes are replayed as-is; never create a second AI producer.
            worker = await SimulationWorker.create(data, args.assets / 'Simulation.dll', working_directory=workdir,
                                                   startup_timeout=min(120, args.timeout_seconds),
                                                   request_timeout=10, close_timeout=3)
            report.update(worker_pid=worker.pid, backend='native-windows')
            report['worker_identity'] = dict(game_data_sha256=worker.game_data_sha256,
                                            dll_sha256=worker.dll_sha256, synthetic=worker._test_backend)
            require(not worker._test_backend and worker.game_data_sha256 == reference['bootstrap_sha256']
                    and worker.dll_sha256 == reference['simulation_sha256'], 'worker identity differs')
            with io.BytesIO(inputs) as stream:
                for frame, row in enumerate(rows):
                    payload = benchmark.read_frame(stream)
                    result = await worker.process_frame(payload, dt_ms=50)
                    require(result.frame == frame, 'native frame differs')
                    benchmark.check_record(frame, payload, result.state, row)
                    report['verified_frames'] += 1
                    if frame in selected:
                        report['snapshots'].append(await save_snapshot(worker, args.output, frame, row['phase'],
                                                                      31, result.state))
                    if frame in viewer_frames:
                        for viewer in (0, 1):
                            state = await worker.state(viewer=viewer, include_entities=True)
                            report['snapshots'].append(await save_snapshot(worker, args.output, frame, row['phase'],
                                                                          viewer, state))
                require(not stream.read(1), 'extra replay journal frames')
        report.update(passed=True, native_qualified=True)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        clean = False
        if worker is not None:
            try:
                await worker.close()
            except BaseException as error:
                report['cleanup_error'] = repr(error)
            cleanup = dict(exit_code=worker.process.poll(), failure=worker.failure,
                           stderr_thread_closed=not worker._stderr_thread.is_alive(),
                           io_threads_closed=all(not t.is_alive() for t in worker._io._threads))
            report['cleanup'] = cleanup
            clean = (cleanup['exit_code'] == 0 and cleanup['failure'] is None and cleanup['stderr_thread_closed']
                     and cleanup['io_threads_closed'] and 'cleanup_error' not in report)
        try:
            report['source_at_finish'] = source_hashes()
            report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
            require(report['source_unchanged'], 'capture source changed during replay')
            if 'reference' in report:
                check_stability(args, report['reference'])
                report['reference_unchanged'] = True
        except BaseException as error:
            report['stability_error'] = f'{type(error).__name__}: {error}'
        report['passed'] &= clean and 'stability_error' not in report
        report['native_qualified'] &= report['passed']
        if not report['passed'] and 'error' not in report:
            report['error'] = 'worker cleanup or input/source stability failed'
        report['elapsed_seconds'] = time.perf_counter() - started
        write_json(args.output / 'manifest.json', report)
    print(json.dumps(dict(passed=report['passed'], verified_frames=report['verified_frames'],
                          snapshots=len(report['snapshots']), output=str(args.output), error=report.get('error'))))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', required=True, type=Path)
    parser.add_argument('--journal', required=True, type=Path, help='successful benchmark directory')
    parser.add_argument('--output', required=True, type=Path, help='fresh directory inside ignored local/')
    parser.add_argument('--timeout-seconds', type=float, default=600)
    return asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    raise SystemExit(main())
