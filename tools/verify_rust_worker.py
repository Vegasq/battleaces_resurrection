"""Private Windows worker integration proof using retained recorded workloads.

No listeners, user profiles, live hosts or game UI. A pass verifies observable
state parity, exact backend identity, stable inputs and normal worker cleanup.
Accelerated whole-worker RPC timings are exploratory measurements, not Internet
publication cadence, perceived gameplay smoothness or performance acceptance.
The caller must retain the source-bound Cargo build receipt for the selected DLL.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import statistics
import sys
from types import SimpleNamespace

from tools import benchmark_large_armies as b
from tools import capture_snapshot_corpus as c
from tools import verify_rust_snapshot_decoder as v

ROOT = b.ROOT
MAX_LIBRARY = 64 * 1024 * 1024
MAX_JSON = 8 * 1024 * 1024


def sources():
    names = ['tools/verify_rust_worker.py', 'tools/capture_snapshot_corpus.py']
    return {**b.source_hashes(), **v.source_hashes(),
            **{p.relative_to(ROOT).as_posix(): b.digest(p.read_bytes())
               for p in (ROOT / 'rust/snapshot-decoder/src').rglob('*.rs')},
            **{name: b.digest((ROOT / name).read_bytes()) for name in names}}


def read_file(path, limit):
    b.require(path.is_file() and not path.is_symlink(), f'missing/redirected input: {path}')
    return c.bounded_read(path, limit)


def remember(path, limit, bindings, expected=None):
    raw = read_file(path, limit)
    actual = b.digest(raw)
    b.require(expected is None or actual == expected, f'input digest differs: {path}')
    identity = dict(sha256=actual, limit=limit)
    b.require(str(path) not in bindings or bindings[str(path)] == identity, f'input changed: {path}')
    bindings[str(path)] = identity
    return raw


def corpus_file(directory, name, expected, bindings, limit=64 * 1024 * 1024):
    b.require(isinstance(name, str) and Path(name).name == name and name not in ('', '.', '..'),
              'unsafe corpus filename')
    return remember(directory / name, limit, bindings, expected)


def clean_exit(receipt):
    cleanup = receipt.get('cleanup', {})
    return (type(cleanup.get('exit_code')) is int and cleanup['exit_code'] == 0
            and cleanup.get('failure', 'missing') is None
            and cleanup.get('stderr_thread_closed') is True and cleanup.get('io_threads_closed') is True
            and 'cleanup_error' not in receipt)


def verify_corpus(corpus, decoder, source, bindings):
    raw_manifest = remember(corpus / 'manifest.json', MAX_JSON, bindings)
    manifest = json.loads(raw_manifest)
    b.require(manifest.get('schema') == 1 and manifest.get('passed') is True
              and manifest.get('native_qualified') is True and manifest.get('source_unchanged') is True
              and manifest.get('reference_unchanged') is True and clean_exit(manifest)
              and manifest.get('source_at_start') and manifest['source_at_start'] == manifest.get('source_at_finish'),
              'unqualified native corpus')
    b.require(manifest['source_at_start']['server/native_simulation.py'] == source['server/native_simulation.py'],
              'captured Python decoder differs')
    reference = manifest['reference']
    journal, assets = Path(reference['journal']), Path(reference['assets'])
    options = SimpleNamespace(journal=journal, assets=assets)
    _, _, rows, selected, viewers, verified_reference = c.load_reference(options)
    b.require(reference == verified_reference, 'captured reference differs from retained journal/assets')
    b.require(type(manifest['verified_frames']) is int and manifest['verified_frames'] == len(rows),
              'captured frame count differs')
    b.require(manifest['selection'] == selected and manifest['viewer_frames'] == sorted(viewers),
              'captured sample selection differs')
    for name, sha in reference['journal_files'].items():
        corpus_file(journal, name, sha, bindings, c.JOURNAL_LIMITS[name])
    b.require(1 <= len(manifest['snapshots']) <= 64, 'corpus snapshot count outside bounds')
    observed = set()
    for entry in manifest['snapshots']:
        frame, viewer = entry['frame'], entry['viewer']
        b.require(type(frame) is int and 0 <= frame < len(rows)
                  and type(viewer) is int and 0 <= viewer <= 31 and entry['include_entities'] is True,
                  'invalid captured frame/viewer')
        b.require((frame, viewer) not in observed and entry['phase'] == rows[frame]['phase'],
                  'duplicate or mislabeled corpus sample')
        observed.add((frame, viewer))
        raw = corpus_file(corpus, entry['snapshot_file'], entry['snapshot_sha256'], bindings, v.MAX_SNAPSHOT)
        b.require(len(raw) == entry['bytes'], 'snapshot byte count differs')
        for entities in (False, True):
            prefix = 'expected' if entities else 'expected_summary'
            expected = json.loads(corpus_file(corpus, entry[prefix + '_file'], entry[prefix + '_sha256'], bindings))
            python = v.json_reference(raw, viewer, entities)
            v.assert_equivalent(python, expected)
            b.require(python['frame'] == frame, 'snapshot native frame differs')
            # Production resources use integer keys; JSON references use strings.
            actual = json.loads(v.json_bytes(decoder.decode(raw, viewer, include_entities=entities)))
            v.assert_equivalent(actual, expected)
            if entities:
                state_sha = b.state_digest(python)
                b.require(state_sha == entry['observable_state_sha256'], 'snapshot observable digest differs')
                if viewer == 31:
                    b.require(state_sha == rows[frame]['state_sha256'], 'snapshot differs from journal state')
    b.require(observed == {(frame, 31) for frame in selected}
              | {(frame, viewer) for frame in viewers for viewer in (0, 1)}, 'corpus samples incomplete')
    return dict(name=corpus.name, manifest_sha256=b.digest(raw_manifest), snapshots=len(observed),
                verified_frames=len(rows), reference=reference)


def verify_receipt(receipt, backend, reference, frames, args, library_sha, source, benchmark_sources):
    b.require(receipt.get('passed') is True and receipt.get('native_qualified') is True
              and receipt.get('source_unchanged') is True and clean_exit(receipt), 'worker replay or cleanup failed')
    b.require(receipt.get('source_at_start') == receipt.get('source_at_finish')
              and set(receipt['source_at_start']) == benchmark_sources
              and all(source.get(name) == sha for name, sha in receipt['source_at_start'].items()),
              'worker source identity differs')
    b.require(receipt['simulation_sha256'] == reference['simulation_sha256']
              and receipt['input_journal_sha256'] == reference['journal_files']['frames.bin']
              and receipt['bootstrap_sha256'] == reference['bootstrap_sha256']
              and receipt['asset_manifest_sha256'] == reference['asset_manifest_sha256']
              and type(receipt['frames']) is int and receipt['frames'] == frames,
              'worker input/DLL/frame identity differs')
    b.require(receipt.get('paced') is False and receipt.get('profiled') is False and receipt.get('timestep_ms') == 50,
              'worker measurement conditions differ')
    expected_decoder = (dict(implementation='rust', abi_version=1, library_sha256=library_sha,
                             library_path=str(args.library)) if backend == 'rust' else dict(implementation='python'))
    b.require(receipt.get('snapshot_decoder') == expected_decoder, 'worker decoder identity differs')
    runtime = receipt['worker_runtime']
    b.require(isinstance(runtime, dict) and runtime.get('os_name') == 'nt' and runtime.get('platform') == 'win32'
              and runtime.get('pointer_bits') == 64 and runtime.get('implementation') == 'cpython'
              and all(isinstance(runtime.get(key), str) and runtime[key] for key in ('python_version', 'executable')),
              'native worker runtime identity missing')
    b.require(isinstance(receipt['startup_ms'], (int, float)) and math.isfinite(receipt['startup_ms'])
              and receipt['startup_ms'] >= 0, 'invalid worker startup timing')
    phases = receipt['phases']
    b.require(set(phases) == set(c.PHASES) and sum(phases[p]['frames'] for p in c.PHASES) == frames,
              'worker phase/frame counts differ')
    for phase in phases.values():
        timing = phase['timings_ms']['step_rpc_ms']
        b.require(type(phase['frames']) is int and phase['frames'] > 0 and timing['count'] == phase['frames'],
                  'worker timing count differs')
        b.require(all(type(timing[key]) in (int, float) and math.isfinite(timing[key]) and timing[key] >= 0
                      for key in ('mean', 'p50', 'p95', 'p99'))
                  and all(type(timing[key]) is int and 0 <= timing[key] <= phase['frames']
                          for key in ('above_50ms', 'above_100ms')), 'invalid worker timing summary')


def validate_args(args):
    b.require(sys.platform == 'win32', 'native Windows qualification required')
    b.require(not os.path.lexists(args.output), 'fresh private output required')
    args.library, args.output = args.library.resolve(), args.output.resolve()
    args.corpus = [p.resolve() for p in args.corpus]
    local = (ROOT / 'local').resolve()
    b.require(args.library == (ROOT / 'rust/snapshot-decoder/target/release/ba_snapshot_decoder.dll').resolve(),
              'source-owned release library required')
    b.require(type(args.pairs) is int and 1 <= args.pairs <= 3 and 1 <= len(args.corpus) <= 2,
              'bounded one-to-three pairs and one-to-two corpora required')
    b.require(len({p.name for p in args.corpus}) == len(args.corpus), 'duplicate corpus names')
    b.require(args.output.is_relative_to(local) and args.output != local, 'fresh private output required')
    b.require(all(p.is_relative_to(local) and p.is_dir() and not args.output.is_relative_to(p)
                  and not p.is_relative_to(args.output) for p in args.corpus), 'separate private corpus required')


async def run(args):
    validate_args(args)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, passed=False, pairs=[], corpora=[], scope=__doc__, requested_pairs=args.pairs,
                  performance_acceptance_evaluated=False)
    bindings, references = {}, []
    try:
        from server.rust_snapshot_decoder import RustSnapshotDecoder, RustDecoderError
        report['source_at_start'] = sources()
        benchmark_sources = set(b.source_hashes())
        report['library_sha256'] = b.digest(remember(args.library, MAX_LIBRARY, bindings))
        decoder = RustSnapshotDecoder(args.library, report['library_sha256'])
        valid = v.fixtures.valid_cases()
        refused = v.fixtures.invalid_cases() + v.fixtures.json_refusal_cases()
        for case in valid:
            v.assert_equivalent(decoder.decode(case['raw'], case['viewer'], include_entities=case['include_entities']),
                                v.decode_snapshot(case['raw'], case['viewer'], include_entities=case['include_entities']))
        for case in refused:
            try:
                decoder.decode(case['raw'], case['viewer'], include_entities=case['include_entities'])
            except RustDecoderError:
                pass
            else:
                raise ValueError('FFI failed to refuse ' + case['name'])
        report['authored'] = dict(valid=len(valid), refused=len(refused))
        # Qualify every input before timing any corpus. No decoding is added to the measured loop.
        for corpus in args.corpus:
            checked = verify_corpus(corpus, decoder, report['source_at_start'], bindings)
            report['corpora'].append(checked)
            references.append(checked['reference'])
        runtime_reference = None
        for corpus, checked in zip(args.corpus, report['corpora']):
            reference = checked['reference']
            journal, assets = Path(reference['journal']), Path(reference['assets'])
            for pair in range(args.pairs):
                order = ('python', 'rust') if pair % 2 == 0 else ('rust', 'python')
                result = dict(corpus=corpus.name, pair=pair + 1, order=order)
                for backend in order:
                    output = args.output / f'{corpus.name}-pair{pair + 1}-{backend}'
                    options = SimpleNamespace(assets=assets, output=output, replay=journal,
                        profile_worker=False, profile_thread_interval=0, paced=False,
                        setup_frames=4000, measure_frames=600, timeout_seconds=600,
                        seed=20261117, resource_multiplier=1, profile=58,
                        wine_executable=None, windows_python=None, wine_prefix_template=None, wine_cgroup_parent=None,
                        snapshot_decoder_library=args.library if backend == 'rust' else None,
                        snapshot_decoder_sha256=report['library_sha256'] if backend == 'rust' else None)
                    b.validate_args(options)
                    code = await b.run(options)
                    raw_receipt = remember(output / 'benchmark.json', MAX_JSON, bindings)
                    receipt = json.loads(raw_receipt)
                    b.require(code == 0, 'worker replay failed; retain individual benchmark report')
                    verify_receipt(receipt, backend, reference, checked['verified_frames'], args,
                                   report['library_sha256'], report['source_at_start'], benchmark_sources)
                    if runtime_reference is None:
                        runtime_reference = receipt['worker_runtime']
                    b.require(runtime_reference == receipt['worker_runtime'], 'worker runtimes differ between arms')
                    result[backend] = dict(frames=receipt['frames'], startup_ms=receipt['startup_ms'],
                        phases=receipt['phases'], cleanup=receipt['cleanup'], runtime=receipt['worker_runtime'],
                        decoder=receipt['snapshot_decoder'], report_sha256=b.digest(raw_receipt))
                report['pairs'].append(result)
                (args.output / 'progress.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
                print(json.dumps(dict(corpus=corpus.name, pair=pair + 1,
                    combat_step_mean_ms={key: result[key]['phases']['combat']['timings_ms']['step_rpc_ms']['mean']
                                         for key in ('python', 'rust')})), flush=True)
        report['summary'] = {}
        for corpus in args.corpus:
            rows = [row for row in report['pairs'] if row['corpus'] == corpus.name]
            report['summary'][corpus.name] = {phase: {backend: {metric: statistics.median([
                row[backend]['phases'][phase]['timings_ms']['step_rpc_ms'][metric] for row in rows])
                for metric in ('mean', 'p50', 'p95', 'p99', 'above_50ms', 'above_100ms')}
                for backend in ('python', 'rust')} for phase in ('movement', 'combat')}
        report['passed'] = True
    except BaseException as error:
        import traceback
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        errors = []
        try:
            report['source_at_finish'] = sources()
            report['source_unchanged'] = report.get('source_at_start') == report['source_at_finish']
            b.require(report['source_unchanged'], 'qualification source changed')
        except BaseException as error:
            report['source_unchanged'] = False
            errors.append(f'source: {type(error).__name__}: {error}')
        try:
            for path, identity in bindings.items():
                b.require(b.digest(read_file(Path(path), identity['limit'])) == identity['sha256'], f'input changed: {path}')
            for reference in references:
                c.check_stability(SimpleNamespace(assets=Path(reference['assets']), journal=Path(reference['journal'])), reference)
            report['inputs_unchanged'] = True
        except BaseException as error:
            report['inputs_unchanged'] = False
            errors.append(f'input: {type(error).__name__}: {error}')
        report['library_unchanged'] = False
        try:
            report['library_unchanged'] = report.get('library_sha256') == b.digest(read_file(args.library, MAX_LIBRARY))
        except BaseException as error:
            errors.append(f'library: {type(error).__name__}: {error}')
        report['passed'] &= report['source_unchanged'] and report['inputs_unchanged'] and report['library_unchanged']
        if errors:
            report['stability_errors'] = errors
            report.setdefault('error', 'qualification inputs/source changed; see stability_errors')
        with (args.output / 'verification.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'summary', 'error') if key in report}), flush=True)
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--corpus', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pairs', type=int, default=3)
    return asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    raise SystemExit(main())
