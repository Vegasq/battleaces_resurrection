"""Verifier controls using authored bytes and mocked processes, never Cargo/timing."""
import contextlib
import copy
import io
import json
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import verify_rust_snapshot_decoder as v


def process_result(value=None, *, returncode=0, stderr=b''):
    return SimpleNamespace(returncode=returncode, stdout=v.json_bytes(value) if value is not None else b'',
                           stderr=stderr)


class ParityTests(unittest.TestCase):
    def test_exact_nested_values_and_key_order_are_accepted(self):
        expected = {'integer': 2**64-1, 'values': [-0.0, math.ulp(0.0), 1.5], 'complete': True}
        actual = dict(reversed(list(expected.items())))
        v.assert_equivalent(actual, expected)

    def test_float_bits_negative_zero_types_keys_and_lengths_are_checked(self):
        cases = [
            (1.0, math.nextafter(1.0, 2.0), 'floating-point bits'),
            (-0.0, 0.0, 'floating-point bits'),
            (0.0, -0.0, 'floating-point bits'),
            (True, 1, 'type differs'),
            (1, True, 'type differs'),
            (1.0, 1, 'type differs'),
            (1, 1.0, 'type differs'),
            ({'x': 1}, {'x': 1, 'y': 2}, 'keys differ'),
            ({'x': 1, 'y': 2}, {'x': 1}, 'keys differ'),
            ([1], [1, 2], 'lengths differ'),
            (2**64-2, 2**64-1, 'value differs'),
        ]
        for actual, expected, reason in cases:
            with self.subTest(actual=actual, expected=expected):
                with self.assertRaisesRegex(ValueError, r'\$\.state\[0\]: '+reason):
                    v.assert_equivalent({'state': [actual]}, {'state': [expected]})

    def test_nonfinite_values_never_pass_parity_or_strict_json(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'floating-point bits'):
                    v.assert_equivalent(value, value)
                with self.assertRaises(ValueError):
                    v.json_bytes({'position': value})


class VerifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.local = self.root / 'local'
        self.local.mkdir()
        self.crate = self.root / 'rust' / 'snapshot-decoder'
        self.binary = self.crate / 'target' / 'release' / ('ba-snapshot-decode.exe' if os.name == 'nt' else 'ba-snapshot-decode')
        self.output = self.local / 'verification'
        self.sources = {'server/native_simulation.py': 'authored-decoder-digest'}
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(v, 'ROOT', self.root))
        stack.enter_context(mock.patch.object(v, 'CRATE', self.crate))
        stack.enter_context(mock.patch.object(v, 'source_hashes', return_value=self.sources))
        self.process = stack.enter_context(mock.patch.object(v, 'run_process',
            side_effect=AssertionError('unit controls must not launch processes')))
        self.python_batch = stack.enter_context(mock.patch.object(v, 'python_batch',
            side_effect=AssertionError('unit controls must not run timing workloads')))

    def args(self, *, output=None, corpus=()):
        result = ['--binary', str(self.binary), '--output', str(output or self.output)]
        for directory in corpus:
            result += ['--corpus', str(directory)]
        return result

    def write_corpus(self):
        directory = self.local / 'corpus'
        directory.mkdir()
        raw = v.fixtures.make_snapshot(2)
        full = v.json_reference(raw, 31, True)
        summary = v.json_reference(raw, 31, False)
        entry = dict(id='authored-movement', phase='movement', viewer=31, frame=full['frame'],
                     bytes=len(raw), snapshot_file='sample.snapshot', snapshot_sha256=v.sha(raw),
                     expected_file='full.json', expected_sha256=v.sha(v.json_bytes(full)),
                     expected_summary_file='summary.json', expected_summary_sha256=v.sha(v.json_bytes(summary)))
        manifest = dict(schema=1, passed=True, native_qualified=True, source_unchanged=True,
                        source_at_start=dict(self.sources), source_at_finish=dict(self.sources),
                        reference={'simulation_sha256': v.SUPPORTED_DLL_SHA256}, verified_frames=4,
                        snapshots=[entry])
        (directory / entry['snapshot_file']).write_bytes(raw)
        (directory / entry['expected_file']).write_bytes(v.json_bytes(full))
        (directory / entry['expected_summary_file']).write_bytes(v.json_bytes(summary))
        self.write_manifest(directory, manifest)
        return directory, manifest, raw

    def write_manifest(self, directory, manifest):
        (directory / 'manifest.json').write_bytes(v.json_bytes(manifest))

    def fake_decode(self, binary, path, viewer, entities):
        self.assertEqual(binary, self.binary)
        return process_result(v.json_reference(path.read_bytes(), viewer, entities))

    def test_authored_corpus_checks_full_summary_and_selects_dense_input(self):
        directory, manifest, raw = self.write_corpus()
        with mock.patch.object(v, 'invoke', side_effect=self.fake_decode) as invoke:
            report, selected = v.verify_corpus(self.binary, directory)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual([call.args[3] for call in invoke.call_args_list], [False, True])
        self.assertTrue(all(row['equivalent'] for row in report['snapshots']))
        self.assertEqual(report['manifest_sha256'], v.sha((directory / 'manifest.json').read_bytes()))
        self.assertEqual(selected, [(manifest['snapshots'][0], directory / 'sample.snapshot', raw)])
        self.process.assert_not_called()

    def test_snapshot_and_expected_digest_tampering_are_refused_before_execution(self):
        directory, _, _ = self.write_corpus()
        for name in ('sample.snapshot', 'summary.json'):
            path = directory / name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b' ')
                with mock.patch.object(v, 'invoke') as invoke:
                    with self.assertRaisesRegex(ValueError, 'digest differs'):
                        v.verify_corpus(self.binary, directory)
                    invoke.assert_not_called()
                path.write_bytes(original)

    def test_rehashed_expected_value_tampering_still_fails_python_parity(self):
        directory, manifest, _ = self.write_corpus()
        expected = json.loads((directory / 'summary.json').read_bytes())
        expected['frame'] += 1
        encoded = v.json_bytes(expected)
        (directory / 'summary.json').write_bytes(encoded)
        manifest['snapshots'][0]['expected_summary_sha256'] = v.sha(encoded)
        self.write_manifest(directory, manifest)
        with mock.patch.object(v, 'invoke') as invoke:
            with self.assertRaisesRegex(ValueError, r'\$\.frame: value differs'):
                v.verify_corpus(self.binary, directory)
            invoke.assert_not_called()

    def test_corpus_path_tampering_is_refused_before_execution(self):
        directory, manifest, _ = self.write_corpus()
        for name in ('../outside.snapshot', str(self.root / 'outside.snapshot'), '', '.', '..'):
            with self.subTest(name=name):
                manifest['snapshots'][0]['snapshot_file'] = name
                self.write_manifest(directory, manifest)
                with mock.patch.object(v, 'invoke') as invoke:
                    with self.assertRaisesRegex(ValueError, 'unsafe corpus filename'):
                        v.verify_corpus(self.binary, directory)
                    invoke.assert_not_called()

    def test_corpus_qualification_and_source_identity_are_required(self):
        directory, original, _ = self.write_corpus()
        variants = []
        for field in ('passed', 'native_qualified', 'source_unchanged'):
            manifest = copy.deepcopy(original)
            manifest[field] = False
            variants.append(manifest)
        manifest = copy.deepcopy(original)
        manifest['source_at_finish']['server/native_simulation.py'] = 'changed'
        variants.append(manifest)
        manifest = copy.deepcopy(original)
        manifest['reference']['simulation_sha256'] = 'wrong-dll'
        variants.append(manifest)
        manifest = copy.deepcopy(original)
        for field in ('source_at_start', 'source_at_finish'):
            manifest[field]['server/native_simulation.py'] = 'different-decoder'
        variants.append(manifest)
        for index, manifest in enumerate(variants):
            with self.subTest(index=index):
                self.write_manifest(directory, manifest)
                with mock.patch.object(v, 'invoke') as invoke:
                    with self.assertRaises(ValueError):
                        v.verify_corpus(self.binary, directory)
                    invoke.assert_not_called()

    def test_missing_and_redirected_corpus_files_are_refused(self):
        directory, _, raw = self.write_corpus()
        with self.assertRaisesRegex(ValueError, 'missing/redirected'):
            v.corpus_file(directory, 'missing.snapshot', v.sha(raw))
        with mock.patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'missing/redirected'):
                v.corpus_file(directory, 'sample.snapshot', v.sha(raw))

    def test_wrong_binary_path_is_refused_before_any_process_launch(self):
        self.output.mkdir()
        wrong = self.root / self.binary.name
        with self.assertRaisesRegex(ValueError, 'source-owned Cargo release output'):
            v.build(wrong, self.output)
        self.process.assert_not_called()

    def prepare_build(self):
        self.output.mkdir()
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes((b'MZ' if os.name == 'nt' else b'\x7fELF') + b'authored executable header')
        return dict(reason='compiler-artifact', target={'name': 'ba-snapshot-decode'}, executable=str(self.binary))

    def test_build_receipt_binds_expected_binary_compiler_and_bytes(self):
        artifact = self.prepare_build()
        self.process.side_effect = [process_result(artifact),
                                    SimpleNamespace(returncode=0, stdout=b'authored compiler identity\n', stderr=b'')]
        with mock.patch.dict(os.environ, {'CARGO_TARGET_DIR': 'redirected-output'}):
            receipt = v.build(self.binary, self.output)
        self.assertEqual(receipt['executable_sha256'], v.sha(self.binary.read_bytes()))
        self.assertEqual(receipt['compiler_artifact'], artifact)
        self.assertEqual(receipt['rustc'], 'authored compiler identity')
        calls = self.process.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0][:4], ['cargo', '+'+v.TOOLCHAIN, 'build', '--release'])
        self.assertIn('--locked', calls[0].args[0])
        self.assertNotIn('CARGO_TARGET_DIR', calls[0].kwargs['env'])
        self.assertEqual(calls[1].args[0], ['rustc', '+'+v.TOOLCHAIN, '-Vv'])

    def test_forged_missing_or_duplicated_cargo_receipt_cannot_launch_decoder(self):
        artifact = self.prepare_build()
        wrong = dict(artifact, executable=str(self.root / self.binary.name))
        outputs = [b'', v.json_bytes(wrong), v.json_bytes(artifact)+b'\n'+v.json_bytes(artifact)]
        for output in outputs:
            with self.subTest(output=output):
                self.process.reset_mock()
                self.process.side_effect = None
                self.process.return_value = SimpleNamespace(returncode=0, stdout=output, stderr=b'')
                with self.assertRaisesRegex(ValueError, 'Cargo executable receipt differs'):
                    v.build(self.binary, self.output)
                self.assertEqual(self.process.call_count, 1)
                self.assertEqual(self.process.call_args.args[0][0], 'cargo')

    def test_non_native_or_redirected_binary_is_refused_before_identity_launch(self):
        artifact = self.prepare_build()
        self.process.side_effect = None
        self.process.return_value = process_result(artifact)
        self.binary.write_bytes(b'not a native executable')
        with self.assertRaisesRegex(ValueError, 'wrong native executable format'):
            v.build(self.binary, self.output)
        self.assertEqual(self.process.call_count, 1)
        self.process.reset_mock()
        with mock.patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'compiled executable missing or redirected'):
                v.build(self.binary, self.output)
        self.assertEqual(self.process.call_count, 1)

    def test_main_records_wrong_binary_refusal_without_launching_or_overwriting(self):
        argv = self.args()
        argv[1] = str(self.root / 'untrusted-decoder')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(v.main(argv), 1)
        report = json.loads((self.output / 'verification.json').read_bytes())
        self.assertFalse(report['passed'])
        self.assertIn('source-owned Cargo release output', report['error'])
        self.process.assert_not_called()
        original = (self.output / 'verification.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'preserve existing'):
            v.parse_args(argv)
        self.assertEqual((self.output / 'verification.json').read_bytes(), original)

    def test_only_fresh_private_output_separate_from_corpora_is_accepted(self):
        corpus, _, _ = self.write_corpus()
        args = v.parse_args(self.args(corpus=[corpus]))
        self.assertEqual(args.output, self.output)
        self.assertEqual(args.corpus, [corpus])
        for output in (self.root / 'public-output', self.local, corpus, corpus / 'nested-output'):
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    v.parse_args(self.args(output=output, corpus=[corpus]))
        outside = self.root / 'outside-corpus'
        outside.mkdir()
        with self.assertRaisesRegex(ValueError, 'separate local/'):
            v.parse_args(self.args(corpus=[outside]))
        with self.assertRaisesRegex(ValueError, 'duplicate/excessive'):
            v.parse_args(self.args(corpus=[corpus, corpus]))
        self.process.assert_not_called()

    def benchmark_values(self, raw, iterations=3):
        return dict(raw_sha256=v.sha(raw), canonical_fnv1a64=v.json_reference(raw, 31, True)['canonical_fnv1a64'],
                    iterations=iterations, samples=1, include_entities=True, release_build=True,
                    decode_ms=[1.0], decode_serialize_ms=[2.0])

    def test_mocked_benchmark_alternates_backends_and_preserves_full_work(self):
        raw = v.fixtures.make_snapshot(2)
        value = self.benchmark_values(raw)
        order = []
        self.python_batch.side_effect = lambda *args: order.append('python') or copy.deepcopy(value)
        with mock.patch.object(v, 'invoke', side_effect=lambda *a, **k: order.append('rust') or process_result(value)) as invoke:
            report = v.benchmark_pair(self.binary, self.local / 'sample.snapshot', raw, 31, 'authored', iterations=3, pairs=2)
        self.assertEqual(order, ['python', 'rust', 'rust', 'python'])
        self.assertEqual(report['entities'], 2)
        self.assertEqual(report['summary']['rust']['decode_ms']['count'], 2)
        for call in invoke.call_args_list:
            self.assertEqual(call.args[2:], (31, True))
            self.assertEqual(call.kwargs, {'benchmark': True, 'iterations': 3})
        self.process.assert_not_called()

    def test_wrong_benchmark_hash_or_work_contract_is_refused_for_either_backend(self):
        raw = v.fixtures.make_snapshot(2)
        correct = self.benchmark_values(raw)
        mutations = {'raw_sha256': 'wrong-raw', 'canonical_fnv1a64': 'wrong-state',
                     'iterations': 2, 'samples': 2, 'include_entities': False}
        for backend in ('python', 'rust'):
            for field, replacement in mutations.items():
                with self.subTest(backend=backend, field=field):
                    bad = dict(correct, **{field: replacement})
                    self.python_batch.side_effect = None
                    self.python_batch.return_value = bad if backend == 'python' else correct
                    with mock.patch.object(v, 'invoke', return_value=process_result(bad if backend == 'rust' else correct)) as invoke:
                        with self.assertRaisesRegex(ValueError, 'input/output/work contract differs'):
                            v.benchmark_pair(self.binary, self.local / 'sample.snapshot', raw, 31, 'authored', iterations=3, pairs=1)
                        if backend == 'python':
                            invoke.assert_not_called()

    def test_debug_failed_and_nonfinite_benchmarks_cannot_qualify(self):
        raw = v.fixtures.make_snapshot(2)
        correct = self.benchmark_values(raw)
        self.python_batch.side_effect = None
        self.python_batch.return_value = correct
        for result, reason in ((process_result(dict(correct, release_build=False)), 'not optimized'),
                               (process_result(returncode=2, stderr=b'refused'), 'benchmark failed')):
            with self.subTest(reason=reason):
                with mock.patch.object(v, 'invoke', return_value=result):
                    with self.assertRaisesRegex(ValueError, reason):
                        v.benchmark_pair(self.binary, self.local / 'sample.snapshot', raw, 31, 'authored', iterations=3, pairs=1)
        for value in (0.0, -1.0, float('nan'), float('inf')):
            with self.subTest(timing=value):
                with self.assertRaisesRegex(ValueError, 'invalid timing'):
                    v.timing_summary([value])


if __name__ == '__main__':
    unittest.main()
