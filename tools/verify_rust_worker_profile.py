"""Run one exact-journal Rust worker control/profile pair in private output.

The control runs first; both arms use the same hash-bound Rust library, runtime,
assets and recorded inputs. This attributes existing worker costs and measures
instrumentation overhead; it does not compare Rust with Python or qualify game
latency. Recorded AI inputs are replayed without running the AI producer.
Retain the source-bound build receipt for the supplied library separately.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace

from tools import benchmark_large_armies as b
from tools import capture_snapshot_corpus as c
from tools import summarize_worker_timing as s
from tools import verify_rust_worker as w

ROOT = b.ROOT
MAX_FRAMES = 10_000
MAX_JSON = 8 * 1024 * 1024
WINE_OPTIONS = ('wine_executable', 'windows_python', 'wine_prefix_template', 'wine_cgroup_parent')


def sources():
    name = 'tools/verify_rust_worker_profile.py'
    return {**w.sources(), name: b.digest((ROOT/name).read_bytes())}


def validate_args(args):
    hybrid = b.wine_requested(args)
    b.require(sys.platform.startswith('linux') if hybrid else sys.platform == 'win32',
              'use native Windows or the explicit native-Linux Wine worker backend')
    b.require(not os.path.lexists(args.output), 'fresh private output required')
    b.require(args.library.is_absolute() and not args.library.is_symlink(), 'explicit unredirected absolute library required')
    args.assets, args.journal, args.library, args.output = (
        value.resolve() for value in (args.assets, args.journal, args.library, args.output))
    local = (ROOT/'local').resolve()
    b.require(args.output != local and args.output.is_relative_to(local), 'fresh ignored local output required')
    for directory in (args.assets, args.journal):
        b.require(directory.is_dir() and not args.output.is_relative_to(directory)
                  and not directory.is_relative_to(args.output), 'input/output directories must be separate')
    b.require(not args.library.is_relative_to(args.output), 'library cannot be inside new output')
    b.require(s.valid_sha(args.library_sha256), 'expected lowercase library SHA256 required')
    b.require(type(args.timeout_seconds) in (int, float) and math.isfinite(args.timeout_seconds)
              and 30 <= args.timeout_seconds <= 1800, 'per-arm timeout must be30..1800seconds')
    b.require(type(args.thread_sample_interval) is int and 0 <= args.thread_sample_interval <= 20000,
              'thread sampling interval outside0..20000')
    return hybrid


def arm_options(args, profiled):
    return SimpleNamespace(assets=args.assets, output=args.output/('profile' if profiled else 'control'),
        replay=args.journal, profile_worker=profiled,
        profile_thread_interval=args.thread_sample_interval if profiled else 0, paced=False,
        setup_frames=4000, measure_frames=600, timeout_seconds=args.timeout_seconds,
        seed=20261117, resource_multiplier=1, profile=58,
        snapshot_decoder_library=args.library, snapshot_decoder_sha256=args.library_sha256,
        **{name: getattr(args, name, None) for name in WINE_OPTIONS})


def expected_decoder(args, hybrid):
    path = ('Z:'+args.library.as_posix()).replace('/', '\\') if hybrid else str(args.library)
    return dict(implementation='rust', abi_version=1, library_sha256=args.library_sha256, library_path=path)


def verify_arm(loaded, reference, expected_rows, args, profiled, hybrid, source):
    report, rows = loaded['report'], loaded['rows']
    b.require(report['source_at_start'] == source and report['source_at_finish'] == source,
              'candidate benchmark is not bound to current source')
    b.require(report.get('profiled') is profiled and report.get('paced') is False
              and type(report.get('timestep_ms')) is int and report['timestep_ms'] == 50,
              'candidate profiling/pacing/timestep contract differs')
    b.require(report.get('profile_thread_interval') == (args.thread_sample_interval if profiled else None),
              'candidate thread sampling contract differs')
    decoder = report.get('snapshot_decoder')
    b.require(decoder == expected_decoder(args, hybrid) and type(decoder.get('abi_version')) is int,
              'candidate Rust decoder identity differs')
    b.require(report.get('ai') is None and report.get('replay') == str(args.journal),
              'candidate must replay recorded inputs without regenerating AI')
    for field in ('simulation_sha256', 'asset_manifest_sha256', 'bootstrap_sha256'):
        b.require(report.get(field) == reference[field], 'candidate '+field+' differs')
    b.require(report.get('input_journal_sha256') == reference['journal_files']['frames.bin']
              and report.get('workload') == reference['workload']
              and report.get('replayed_source_hashes') == reference['journal_source_hashes'],
              'candidate replay provenance differs')
    b.require(len(rows) == len(expected_rows), 'candidate frame count differs')
    for actual, expected in zip(rows, expected_rows):
        b.require(all(actual[key] == expected[key] for key in ('frame', 'phase', 'input_sha256', 'state_sha256')),
                  'candidate frame input/state/phase differs')
    runtime = report.get('worker_runtime', {})
    b.require(runtime.get('os_name') == 'nt' and runtime.get('platform') == 'win32'
              and type(runtime.get('pointer_bits')) is int and runtime['pointer_bits'] == 64
              and runtime.get('implementation') == 'cpython'
              and all(isinstance(runtime.get(key), str) and runtime[key] for key in ('python_version', 'executable')),
              'candidate native Windows worker identity missing')
    backend = report.get('backend', {})
    b.require(backend.get('kind') == ('native-linux-wine-worker' if hybrid else 'windows-worker'),
              'candidate backend differs')
    if hybrid:
        b.require(b.backend_cleanup_complete(report.get('backend_statistics')),
                  'candidate Wine prefix/cgroup cleanup incomplete')
    b.require(w.clean_exit(report), 'candidate cleanup incomplete')
    return dict(evidence_sha256=loaded['evidence_sha256'], frames=len(rows),
                decoder=decoder, runtime=runtime, cleanup=report['cleanup'], profiled=profiled,
                exact_input_and_observable_state_match=True)


async def run(args):
    hybrid = validate_args(args)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, passed=False, scope=__doc__, order=['control', 'profile'], arms=[],
                  performance_acceptance_evaluated=False, ai_producer_profiled=False,
                  thread_sample_interval=args.thread_sample_interval, hybrid=hybrid)
    bindings, reference = {}, None
    try:
        report['source_at_start'] = sources()
        current_benchmark_sources = b.source_hashes()
        b.require(all(report['source_at_start'].get(name) == value for name, value in current_benchmark_sources.items()),
                  'benchmark source inventory is not covered')
        w.remember(args.library, w.MAX_LIBRARY, bindings, args.library_sha256)
        _, _, expected_rows, _, _, reference = c.load_reference(args)
        b.require(1 <= len(expected_rows) <= MAX_FRAMES
                  and all(s.valid_sha(row.get('state_sha256')) for row in expected_rows),
                  'bounded complete reference states required')
        report['reference'] = reference
        for name, digest in reference['journal_files'].items():
            w.remember(args.journal/name, c.JOURNAL_LIMITS[name], bindings, digest)
        for name, limit in (('asset-manifest.json', 4*1024*1024), ('Simulation.dll', 128*1024*1024)):
            w.remember(args.assets/name, limit, bindings)
        if hybrid:
            for name in ('wine_executable', 'windows_python'):
                path = Path(getattr(args, name)).resolve()
                w.remember(path, 128*1024*1024, bindings)
        else:
            w.remember(Path(sys.executable).resolve(), 128*1024*1024, bindings)
        runtime = None
        for profiled in (False, True):
            options = arm_options(args, profiled)
            b.validate_args(options)
            code = await b.run(options)
            b.require(code == 0, 'worker arm failed; preserve its benchmark and profile report')
            loaded = s.load_benchmark(options.output)
            checked = verify_arm(loaded, reference, expected_rows, args, profiled, hybrid, current_benchmark_sources)
            if runtime is None:
                runtime = checked['runtime']
            b.require(checked['runtime'] == runtime, 'control/profile worker runtimes differ')
            for name, digest in loaded['evidence_sha256'].items():
                limit = c.JOURNAL_LIMITS.get(name, MAX_JSON)
                w.remember(options.output/name, limit, bindings, digest)
            if profiled:
                w.remember(options.output/'worker-profile.json', 128*1024*1024, bindings,
                           loaded['report']['worker_profile_sha256'])
            report['arms'].append(checked)
            (args.output/'progress.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        summary = s.summarize(args.output/'profile', args.output/'control')
        b.require(summary.get('passed') is True
                  and summary.get('control', {}).get('exact_input_and_observable_state_match') is True,
                  'profile summary/control did not qualify')
        report['summary'] = summary
        report['passed'] = True
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        errors = []
        try:
            report['source_at_finish'] = sources()
            report['source_unchanged'] = report.get('source_at_start') == report['source_at_finish']
            if not report['source_unchanged']:
                errors.append('source changed during verification')
        except BaseException as error:
            report['source_unchanged'] = False
            errors.append('source stability: '+repr(error))
        for path, identity in bindings.items():
            try:
                b.require(b.digest(w.read_file(Path(path), identity['limit'])) == identity['sha256'], 'digest differs')
            except BaseException as error:
                errors.append('bound file changed: '+path+': '+repr(error))
        if reference is not None:
            try:
                c.check_stability(args, reference)
            except BaseException as error:
                errors.append('reference/assets stability: '+repr(error))
        report['inputs_and_evidence_unchanged'] = not errors
        report['stability_errors'] = errors
        report['passed'] = report['passed'] and not errors
        with (args.output/'verification.json').open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'passed': report['passed'], 'completed_arms': len(report['arms']),
                      'error': report.get('error'), 'performance_acceptance_evaluated': False}), flush=True)
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'journal', 'library', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--library-sha256', required=True)
    parser.add_argument('--timeout-seconds', type=float, default=600)
    parser.add_argument('--thread-sample-interval', type=int, default=0)
    for name in WINE_OPTIONS:
        parser.add_argument('--'+name.replace('_', '-'), type=Path)
    return parser.parse_args(argv)


if __name__ == '__main__':
    raise SystemExit(asyncio.run(run(arguments())))
