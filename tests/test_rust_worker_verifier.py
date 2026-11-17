"""Authored orchestration controls; no DLL loads, native workers or timings."""
import asyncio
import contextlib
import gzip
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from server import rust_snapshot_decoder as adapter
from tests.synthetic import snapshot
from tests.test_snapshot_corpus import FakeWorker
from tools import verify_rust_worker as w


class FakeDecoder:
    def decode(self, raw, viewer=31, *, include_entities=False):
        if raw.startswith(b'invalid'):
            raise adapter.RustDecoderError('authored malformed input')
        return w.v.decode_snapshot(raw, viewer, include_entities=include_entities)


class RustWorkerVerifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.source = {'server/native_simulation.py': 'authored-decoder',
                       'tools/benchmark_large_armies.py': 'authored-benchmark'}
        for module in (w, w.b, w.c):
            self.stack.enter_context(mock.patch.object(module, 'ROOT', self.root))
        self.stack.enter_context(mock.patch.object(w.sys, 'platform', 'win32'))
        self.stack.enter_context(mock.patch.object(w.c, 'verify_assets'))
        self.stack.enter_context(mock.patch.object(w.c, 'source_hashes', return_value=self.source))
        self.stack.enter_context(mock.patch.object(w.b, 'source_hashes', return_value=self.source))
        self.sources_mock = self.stack.enter_context(mock.patch.object(w, 'sources', return_value=self.source))
        self.assets, self.journal = self.root / 'assets', self.root / 'journal'
        self.assets.mkdir()
        self.journal.mkdir()
        data, dll, manifest = b'authored bootstrap', b'authored DLL', b'{}'
        (self.assets / 'Simulation.dll').write_bytes(dll)
        (self.assets / 'asset-manifest.json').write_bytes(manifest)
        payloads = [bytes([i + 1]) for i in range(9)]
        inputs = b''.join(struct.pack('<I', len(payload)) + payload for payload in payloads)
        rows = [dict(frame=i, phase=w.c.PHASES[i // 3], input_sha256=w.b.digest(payload),
                     state_sha256=w.b.state_digest(w.v.decode_snapshot(snapshot(i), include_entities=True)))
                for i, payload in enumerate(payloads)]
        reference = dict(passed=True, native_qualified=True, source_unchanged=True, source_at_start=self.source,
                         source_at_finish=self.source, frames=9, asset_manifest_sha256=w.b.digest(manifest),
                         simulation_sha256=w.b.digest(dll), bootstrap_sha256=w.b.digest(data),
                         input_journal_sha256=w.b.digest(inputs), workload={'opponent': 'scripted'})
        (self.journal / 'benchmark.json').write_text(json.dumps(reference), encoding='utf-8')
        (self.journal / 'bootstrap.pb.gz').write_bytes(gzip.compress(data))
        (self.journal / 'frames.bin').write_bytes(inputs)
        (self.journal / 'frames.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        self.corpus = self.root / 'local' / 'corpus'
        capture = SimpleNamespace(assets=self.assets, journal=self.journal, output=self.corpus, timeout_seconds=10)
        with mock.patch.object(w.c.SimulationWorker, 'create', new_callable=mock.AsyncMock,
                               return_value=FakeWorker(data, dll)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(asyncio.run(w.c.run(capture)), 0)
        self.captured = json.loads((self.corpus / 'manifest.json').read_text(encoding='utf-8'))
        self.reference = self.captured['reference']
        library = self.root / 'rust/snapshot-decoder/target/release/ba_snapshot_decoder.dll'
        library.parent.mkdir(parents=True)
        library.write_bytes(b'authored library identity; never loaded')
        self.args = SimpleNamespace(library=library, corpus=[self.corpus], output=self.root / 'local' / 'verify', pairs=3)
        self.stack.enter_context(mock.patch.object(adapter, 'RustSnapshotDecoder', return_value=FakeDecoder()))
        self.stack.enter_context(mock.patch.object(w.v.fixtures, 'valid_cases', return_value=[
            dict(name='authored', raw=snapshot(), viewer=31, include_entities=True)]))
        self.stack.enter_context(mock.patch.object(w.v.fixtures, 'invalid_cases', return_value=[
            dict(name='bad1', raw=b'invalid1', viewer=31, include_entities=True),
            dict(name='bad2', raw=b'invalid2', viewer=31, include_entities=False)]))
        self.stack.enter_context(mock.patch.object(w.v.fixtures, 'json_refusal_cases', return_value=[
            dict(name='bad-json', raw=b'invalid3', viewer=31, include_entities=True)]))
        self.calls, self.receipt_hook, self.after_write_hook = [], None, None
        self.stack.enter_context(mock.patch.object(w.b, 'run', side_effect=self.fake_benchmark))

    async def fake_benchmark(self, options):
        backend = 'rust' if options.snapshot_decoder_library else 'python'
        self.calls.append(backend)
        options.output.mkdir(parents=True, exist_ok=False)
        decoder = (dict(implementation='rust', abi_version=1, library_sha256=options.snapshot_decoder_sha256,
                        library_path=str(options.snapshot_decoder_library)) if backend == 'rust'
                   else dict(implementation='python'))
        receipt = dict(passed=True, native_qualified=True, source_unchanged=True,
            source_at_start=self.source, source_at_finish=self.source, frames=9,
            simulation_sha256=self.reference['simulation_sha256'],
            input_journal_sha256=self.reference['journal_files']['frames.bin'],
            bootstrap_sha256=self.reference['bootstrap_sha256'],
            asset_manifest_sha256=self.reference['asset_manifest_sha256'],
            paced=False, profiled=False, timestep_ms=50, snapshot_decoder=decoder,
            startup_ms=1, worker_runtime=dict(os_name='nt', platform='win32', pointer_bits=64,
                implementation='cpython', executable='authored-python.exe', python_version='authored Python'),
            cleanup=dict(exit_code=0, failure=None, stderr_thread_closed=True, io_threads_closed=True),
            phases={phase: dict(frames=3, timings_ms=dict(step_rpc_ms=w.b.summary([1, 2, 3])))
                    for phase in w.c.PHASES})
        if self.receipt_hook:
            self.receipt_hook(receipt, backend)
        (options.output / 'benchmark.json').write_text(json.dumps(receipt), encoding='utf-8')
        if self.after_write_hook:
            self.after_write_hook(receipt, backend)
        return 0

    def run_verifier(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = asyncio.run(w.run(self.args))
        report = json.loads((self.args.output / 'verification.json').read_text(encoding='utf-8'))
        return code, report

    def test_success_has_three_alternating_pairs_without_claiming_performance_acceptance(self):
        code, report = self.run_verifier()
        self.assertEqual(code, 0)
        self.assertTrue(report['passed'] and report['source_unchanged'] and report['inputs_unchanged'])
        self.assertEqual(self.calls, ['python', 'rust', 'rust', 'python', 'python', 'rust'])
        self.assertEqual(len(report['pairs']), 3)
        self.assertEqual(report['authored'], {'valid': 1, 'refused': 3})
        self.assertFalse(report['performance_acceptance_evaluated'])

    def test_missing_or_wrong_backend_identity_is_rejected(self):
        values = [None, {'implementation': 'python'},
                  dict(implementation='rust', abi_version=2, library_sha256='wrong', library_path='wrong')]
        for index, identity in enumerate(values):
            with self.subTest(identity=identity):
                self.args.output = self.root / 'local' / f'identity-{index}'
                self.receipt_hook = lambda receipt, backend: receipt.update(snapshot_decoder=identity) if backend == 'rust' else None
                code, report = self.run_verifier()
                self.assertEqual(code, 1)
                self.assertIn('decoder identity differs', report['error'])

    def test_cleanup_and_runtime_failures_cannot_qualify(self):
        def cleanup(receipt, backend):
            if backend == 'rust':
                receipt['cleanup']['io_threads_closed'] = False

        def runtime(receipt, backend):
            if backend == 'rust':
                receipt['worker_runtime']['python_version'] = 'another Python'

        for index, hook in enumerate((cleanup, runtime)):
            with self.subTest(index=index):
                self.args.output = self.root / 'local' / f'worker-failure-{index}'
                self.receipt_hook = hook
                code, report = self.run_verifier()
                self.assertEqual(code, 1)
                self.assertFalse(report['passed'])

    def test_captured_expected_reference_corruption_is_rejected_before_benchmark(self):
        path = self.corpus / self.captured['snapshots'][0]['expected_summary_file']
        path.write_text('{}', encoding='utf-8')
        code, report = self.run_verifier()
        self.assertEqual(code, 1)
        self.assertIn('input digest differs', report['error'])
        self.assertFalse(self.calls)

    def test_incomplete_or_unqualified_capture_is_rejected(self):
        self.captured['reference_unchanged'] = False
        (self.corpus / 'manifest.json').write_text(json.dumps(self.captured), encoding='utf-8')
        code, report = self.run_verifier()
        self.assertEqual(code, 1)
        self.assertIn('unqualified native corpus', report['error'])
        self.assertFalse(self.calls)

    def test_journal_drift_after_last_arm_invalidates_comparison(self):
        def drift(receipt, backend):
            if len(self.calls) == 6:
                path = self.journal / 'frames.jsonl'
                path.write_bytes(path.read_bytes() + b'\n')

        self.after_write_hook = drift
        code, report = self.run_verifier()
        self.assertEqual(code, 1)
        self.assertFalse(report['inputs_unchanged'])
        self.assertTrue(report['stability_errors'])

    def test_source_drift_and_missing_source_retain_failed_report(self):
        for index, final in enumerate(({**self.source, 'new-source': 'changed'}, FileNotFoundError('removed source'))):
            with self.subTest(index=index):
                self.args.output = self.root / 'local' / f'source-failure-{index}'
                self.sources_mock.side_effect = [self.source, final]
                code, report = self.run_verifier()
                self.assertEqual(code, 1)
                self.assertFalse(report['source_unchanged'])
                self.assertTrue(report['stability_errors'])

    def test_missing_library_retains_failure_report(self):
        def remove_owned_fixture(receipt, backend):
            if len(self.calls) == 6:
                self.args.library.unlink()

        self.after_write_hook = remove_owned_fixture
        code, report = self.run_verifier()
        self.assertEqual(code, 1)
        self.assertFalse(report['library_unchanged'])
        self.assertTrue(report['stability_errors'])

    def test_unrelated_runtime_error_does_not_count_as_malformed_refusal(self):
        decoder = FakeDecoder()
        ordinary = decoder.decode

        def decode(raw, viewer=31, *, include_entities=False):
            if raw.startswith(b'invalid'):
                raise RuntimeError('unrelated adapter defect')
            return ordinary(raw, viewer, include_entities=include_entities)

        decoder.decode = decode
        with mock.patch.object(adapter, 'RustSnapshotDecoder', return_value=decoder):
            code, report = self.run_verifier()
        self.assertEqual(code, 1)
        self.assertIn('unrelated adapter defect', report['error'])
        self.assertFalse(self.calls)

    def test_bounded_read_and_fresh_private_output_controls(self):
        path = self.root / 'oversized'
        path.write_bytes(b'12345')
        with self.assertRaisesRegex(ValueError, 'size limit'):
            w.read_file(path, 4)
        with self.assertRaisesRegex(ValueError, 'unsafe corpus filename'):
            w.corpus_file(self.corpus, '../manifest.json', 'unused', {})
        self.args.output = self.corpus
        with self.assertRaisesRegex(ValueError, 'fresh private output'):
            w.validate_args(self.args)


if __name__ == '__main__':
    unittest.main()
