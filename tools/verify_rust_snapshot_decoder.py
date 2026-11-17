"""Build the portable Rust decoder and compare it with the Python reference.

Default inputs are authored fixtures suitable for public CI. --corpus consumes
an explicitly supplied private capture; its snapshots and results stay local.
Measurements concern warmed decoding/serialization only, never game tick rate.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.native_simulation import decode_snapshot, SnapshotFormatError, SUPPORTED_DLL_SHA256
from tests import snapshot_decoder_fixtures as fixtures

CRATE = ROOT / 'rust/snapshot-decoder'
TOOLCHAIN = '1.98.1'
MAX_SNAPSHOT = 16 * 1024 * 1024


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes():
    names = ['server/native_simulation.py', 'tools/verify_rust_snapshot_decoder.py',
             'tests/snapshot_decoder_fixtures.py', 'rust/snapshot-decoder/Cargo.toml',
             'rust/snapshot-decoder/Cargo.lock', 'rust/snapshot-decoder/src/lib.rs',
             'rust/snapshot-decoder/src/main.rs']
    names.extend(p.relative_to(ROOT).as_posix() for p in sorted((CRATE/'src').glob('*.rs'))
                 if p.relative_to(ROOT).as_posix() not in names)
    return {name: sha((ROOT / name).read_bytes()) for name in names}


def run_process(command, *, timeout=20, env=None):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    return subprocess.run([str(a) for a in command], cwd=ROOT, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=timeout, env=env, creationflags=flags)


def json_bytes(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode('utf-8')


def json_reference(raw, viewer, entities):
    return json.loads(json_bytes(decode_snapshot(raw, viewer, include_entities=entities)))


def assert_equivalent(actual, expected, path='$'):
    """JSON value parity includes integer types, exact f64 values and negative zero."""
    require(type(actual) is type(expected), f'{path}: type differs')
    if isinstance(expected, dict):
        require(actual.keys() == expected.keys(), f'{path}: keys differ')
        for key in expected:
            assert_equivalent(actual[key], expected[key], path+'.'+str(key))
    elif isinstance(expected, list):
        require(len(actual) == len(expected), f'{path}: lengths differ')
        for index, (a, e) in enumerate(zip(actual, expected)):
            assert_equivalent(a, e, f'{path}[{index}]')
    elif isinstance(expected, float):
        require(math.isfinite(actual) and math.isfinite(expected) and actual.hex() == expected.hex(),
                f'{path}: floating-point bits differ')
    else:
        require(actual == expected, f'{path}: value differs')


def build(binary, output):
    require(sys.platform in ('win32', 'linux'), 'verification supports native Windows and Linux only')
    expected = (CRATE / 'target/release' / ('ba-snapshot-decode.exe' if os.name == 'nt' else 'ba-snapshot-decode')).resolve()
    require(binary == expected, 'binary must be the source-owned Cargo release output')
    command = ['cargo', '+'+TOOLCHAIN, 'build', '--release', '--locked', '--manifest-path',
               CRATE / 'Cargo.toml', '--message-format=json']
    env = dict(os.environ)
    env.pop('CARGO_TARGET_DIR', None)
    result = run_process(command, timeout=300, env=env)
    (output / 'cargo-build.stdout').write_bytes(result.stdout)
    (output / 'cargo-build.stderr').write_bytes(result.stderr)
    require(result.returncode == 0, 'Rust release build failed; see retained build stderr')
    artifacts = [json.loads(line) for line in result.stdout.splitlines() if line.startswith(b'{')]
    matches = [row for row in artifacts if row.get('reason') == 'compiler-artifact'
               and row.get('target', {}).get('name') == 'ba-snapshot-decode' and row.get('executable')]
    require(len(matches) == 1 and Path(matches[0]['executable']).resolve() == binary, 'Cargo executable receipt differs')
    require(binary.is_file() and not binary.is_symlink(), 'compiled executable missing or redirected')
    raw = binary.read_bytes()
    require(raw.startswith(b'MZ' if os.name == 'nt' else b'\x7fELF'), 'wrong native executable format')
    compiler = run_process(['rustc', '+'+TOOLCHAIN, '-Vv'])
    require(compiler.returncode == 0, 'pinned compiler identity unavailable')
    return dict(command=[str(v) for v in command], executable_sha256=sha(raw),
                native_format='PE' if os.name == 'nt' else 'ELF', rustc=compiler.stdout.decode().strip(),
                compiler_artifact=matches[0], stdout_sha256=sha(result.stdout), stderr_sha256=sha(result.stderr),
                build_environment={key: env.get(key) for key in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTC_WRAPPER')})


def invoke(binary, path, viewer, entities, *, benchmark=False, iterations=100):
    command = [binary, 'bench' if benchmark else 'decode', path, '--viewer', str(viewer)]
    if entities:
        command.append('--entities')
    if benchmark:
        command += ['--iterations', str(iterations), '--samples', '1']
    return run_process(command, timeout=60 if benchmark else 15)


def check_case(binary, path, case):
    reference = json_reference(case['raw'], case['viewer'], case['include_entities'])
    result = invoke(binary, path, case['viewer'], case['include_entities'])
    require(result.returncode == 0 and not result.stderr, 'Rust valid input failed: '+case['name'])
    require(len(result.stdout) <= 64 * 1024 * 1024, 'decoded output exceeds comparison bound')
    assert_equivalent(json.loads(result.stdout), reference)
    return dict(name=case['name'], snapshot_sha256=sha(case['raw']), bytes=len(case['raw']),
                viewer=case['viewer'], include_entities=case['include_entities'],
                canonical_fnv1a64=reference['canonical_fnv1a64'], equivalent=True)


def verify_authored(binary, output):
    folder = output / 'authored'
    folder.mkdir()
    report = dict(valid=[], invalid=[], json_refusals=[])
    groups = [('valid', fixtures.valid_cases()), ('invalid', fixtures.invalid_cases()),
              ('json_refusals', fixtures.json_refusal_cases())]
    for kind, cases in groups:
        for index, case in enumerate(cases):
            path = folder / f'{kind}-{index:04d}.snapshot'
            path.write_bytes(case['raw'])
            if kind == 'valid':
                report[kind].append(check_case(binary, path, case))
                continue
            try:
                if kind == 'invalid':
                    decode_snapshot(case['raw'], case['viewer'], include_entities=case['include_entities'])
                else:
                    json_reference(case['raw'], case['viewer'], case['include_entities'])
            except (ValueError, SnapshotFormatError, OverflowError, struct.error):
                pass
            else:
                raise ValueError('fixture expected Python refusal: '+case['name'])
            result = invoke(binary, path, case['viewer'], case['include_entities'])
            require(result.returncode == 2 and not result.stdout and result.stderr.startswith(b'snapshot decoder: ')
                    and len(result.stderr) < 4096 and b'panicked' not in result.stderr,
                    'Rust refusal missing or process crashed: '+case['name'])
            report[kind].append(dict(name=case['name'], snapshot_sha256=sha(case['raw']), refused=True))
    # Native retrieval already caps size; this is an explicit stricter boundary
    # than the standalone Python helper, not an asserted Python parity case.
    oversized = folder / 'oversized.snapshot'
    oversized.write_bytes(bytes(MAX_SNAPSHOT+1))
    result = invoke(binary, oversized, 31, True)
    require(result.returncode == 2 and not result.stdout and b'16MiB' in result.stderr, 'size boundary missing')
    report['size_limit'] = dict(bytes=MAX_SNAPSHOT+1, refused=True, standalone_python_parity=False)
    result = invoke(binary, folder, 31, True)
    require(result.returncode == 2 and not result.stdout, 'directory input was not refused')
    report['directory_refused'] = True
    if sys.platform == 'linux':
        fifo = folder / 'not-a-snapshot.fifo'
        os.mkfifo(fifo)
        try:
            result = invoke(binary, fifo, 31, True)
            require(result.returncode == 2 and not result.stdout and b'regular file' in result.stderr,
                    'FIFO input was not refused before opening')
            report['fifo_refused'] = True
        finally:
            fifo.unlink()
    # A refusal must leave no process-global dependency or changed source state.
    case = fixtures.valid_cases()[0]
    report['after_invalid'] = check_case(binary, folder/'valid-0000.snapshot', case)
    return report


def corpus_file(directory, name, expected_sha):
    require(isinstance(name, str) and Path(name).name == name and name not in ('', '.', '..'), 'unsafe corpus filename')
    path = directory / name
    require(path.is_file() and not path.is_symlink(), 'missing/redirected corpus file')
    require(path.stat().st_size <= 64*1024*1024, 'corpus file exceeds bound')
    data = path.read_bytes()
    require(sha(data) == expected_sha, 'corpus file digest differs')
    return path, data


def verify_corpus(binary, directory):
    manifest_path = directory / 'manifest.json'
    require(manifest_path.stat().st_size <= 8*1024*1024, 'corpus manifest exceeds bound')
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    require(manifest.get('schema') == 1 and manifest.get('passed') is True
            and manifest.get('native_qualified') is True and manifest.get('source_unchanged') is True
            and manifest.get('source_at_start') and manifest['source_at_start'] == manifest.get('source_at_finish'),
            'corpus is not a completed source-bound native capture')
    require(manifest['reference']['simulation_sha256'] == SUPPORTED_DLL_SHA256, 'corpus DLL differs')
    require(manifest['source_at_start']['server/native_simulation.py'] == source_hashes()['server/native_simulation.py'],
            'corpus Python decoder differs')
    require(1 <= len(manifest['snapshots']) <= 64, 'corpus snapshot count outside bound')
    rows, benchmarks = [], []
    for entry in manifest['snapshots']:
        path, raw = corpus_file(directory, entry['snapshot_file'], entry['snapshot_sha256'])
        require(len(raw) == entry['bytes'] and len(raw) <= MAX_SNAPSHOT, 'corpus snapshot size differs')
        for entities in (False, True):
            prefix = 'expected' if entities else 'expected_summary'
            _, expected_bytes = corpus_file(directory, entry[prefix+'_file'], entry[prefix+'_sha256'])
            reference = json_reference(raw, entry['viewer'], entities)
            assert_equivalent(reference, json.loads(expected_bytes))
            require(reference['frame'] == entry['frame'], 'corpus native frame differs')
            case = dict(name=entry['id']+('-full' if entities else '-summary'), raw=raw,
                        viewer=entry['viewer'], include_entities=entities)
            rows.append(check_case(binary, path, case))
        if entry['viewer'] == 31 and entry['phase'] in ('movement', 'combat'):
            benchmarks.append((entry, path, raw))
    # Pick one dense snapshot from each phase; do not cherry-pick measured timings.
    selected = []
    for phase in ('movement', 'combat'):
        candidates = [r for r in benchmarks if r[0]['phase'] == phase]
        if candidates:
            selected.append(max(candidates, key=lambda r: (len(r[2]), -r[0]['frame'])))
    return dict(manifest_sha256=sha(raw_manifest), verified_frames=manifest['verified_frames'],
                source_at_capture=manifest['source_at_start'], reference=manifest['reference'], snapshots=rows), selected


def timing_summary(values):
    require(values and all(math.isfinite(v) and v > 0 for v in values), 'invalid timing sample')
    ordered = sorted(values)
    return dict(count=len(values), minimum=ordered[0], median=statistics.median(values),
                mean=statistics.mean(values), maximum=ordered[-1])


def python_batch(raw, viewer, iterations):
    for _ in range(10):
        decode_snapshot(raw, viewer, include_entities=True)
    values = {}
    last_hash = None
    for serialize in (False, True):
        began = time.perf_counter_ns()
        for _ in range(iterations):
            result = decode_snapshot(raw, viewer, include_entities=True)
            last_hash = result['canonical_fnv1a64']
            if serialize:
                encoded = json_bytes(result)
                require(encoded, 'empty serialized result')
                del encoded
            del result
        values['decode_serialize_ms' if serialize else 'decode_ms'] = [(time.perf_counter_ns()-began)/1e6/iterations]
    return dict(iterations=iterations, samples=1, include_entities=True, canonical_fnv1a64=last_hash,
                raw_sha256=sha(raw), **values)


def benchmark_pair(binary, path, raw, viewer, name, iterations=100, pairs=7):
    expected = json_reference(raw, viewer, True)
    runs = []
    for index in range(pairs):
        order = ('python', 'rust') if index % 2 == 0 else ('rust', 'python')
        row = dict(pair=index+1, order=order)
        for backend in order:
            if backend == 'python':
                value = python_batch(raw, viewer, iterations)
            else:
                result = invoke(binary, path, viewer, True, benchmark=True, iterations=iterations)
                require(result.returncode == 0 and not result.stderr, 'Rust benchmark failed')
                value = json.loads(result.stdout)
                require(value.get('release_build') is True, 'Rust benchmark is not optimized')
            require(value['raw_sha256'] == sha(raw) and value['canonical_fnv1a64'] == expected['canonical_fnv1a64']
                    and value['iterations'] == iterations and value['samples'] == 1 and value['include_entities'] is True,
                    'benchmark input/output/work contract differs')
            row[backend] = value
        runs.append(row)
    summary = {backend: {metric: timing_summary([row[backend][metric][0] for row in runs])
                          for metric in ('decode_ms', 'decode_serialize_ms')} for backend in ('python', 'rust')}
    return dict(name=name, snapshot_sha256=sha(raw), bytes=len(raw), viewer=viewer,
                entities=len(expected['entities']), iterations_per_sample=iterations, paired_runs=runs,
                summary=summary, gc_enabled=gc.isenabled(),
                scope='warmed decode and decode+JSON per-operation averages from alternating batches; includes result destruction; excludes subprocess startup/file IO; no DLL, IPC, server cadence, or perceived-lag claim')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--corpus', type=Path, action='append', default=[])
    parser.add_argument('--benchmark', action='store_true')
    args = parser.parse_args(argv)
    require(not os.path.lexists(args.output), 'preserve existing verification output')
    args.output = args.output.resolve()
    require(args.output.is_relative_to((ROOT/'local').resolve()) and args.output != (ROOT/'local').resolve(),
            'fresh ignored local/ output required')
    args.binary = args.binary.resolve()
    args.corpus = [p.resolve() for p in args.corpus]
    require(len(args.corpus) <= 4 and len(set(args.corpus)) == len(args.corpus), 'duplicate/excessive corpora')
    for directory in args.corpus:
        require(directory.is_relative_to((ROOT/'local').resolve()) and directory.is_dir()
                and not args.output.is_relative_to(directory) and not directory.is_relative_to(args.output),
                'private corpus and fresh output must be separate local/ directories')
    return args


def main(argv=None):
    args = parse_args(argv)
    args.output.mkdir(parents=True)
    report = dict(schema=1, passed=False, python=sys.version, platform=platform.platform(),
                  machine=platform.machine(), logical_cpus=os.cpu_count(), source_at_start=source_hashes(),
                  corpora=[], benchmarks=[], native_game_runtime_in_this_verifier=False)
    try:
        report['build'] = build(args.binary, args.output)
        report['authored'] = verify_authored(args.binary, args.output)
        selected = []
        for directory in args.corpus:
            result, dense = verify_corpus(args.binary, directory)
            report['corpora'].append(result)
            selected.extend((str(directory.name)+'-'+entry['id'], path, raw, entry['viewer']) for entry, path, raw in dense)
        if args.benchmark:
            raw = fixtures.make_snapshot(800)
            path = args.output/'authored-800.snapshot'
            path.write_bytes(raw)
            selected.insert(0, ('authored-800', path, raw, 31))
            for name, path, raw, viewer in selected:
                result = benchmark_pair(args.binary, path, raw, viewer, name)
                report['benchmarks'].append(result)
                print(json.dumps(dict(benchmark=name, platform=sys.platform, entities=result['entities'],
                                      snapshot_sha256=result['snapshot_sha256'], summary=result['summary'])), flush=True)
        report['passed'] = True
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        report['source_at_finish'] = source_hashes()
        report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
        report['passed'] &= report['source_unchanged']
        if 'build' in report:
            report['binary_unchanged'] = sha(args.binary.read_bytes()) == report['build']['executable_sha256']
            report['passed'] &= report['binary_unchanged']
        (args.output/'verification.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'], source_unchanged=report['source_unchanged'],
                          authored_valid=len(report.get('authored', {}).get('valid', [])),
                          authored_invalid=len(report.get('authored', {}).get('invalid', [])),
                          native_corpora=len(report['corpora']), benchmarks=len(report['benchmarks']),
                          error=report.get('error'))), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
