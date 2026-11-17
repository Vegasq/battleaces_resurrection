"""Authored profile orchestration controls; no native library or worker launch."""
import asyncio
import contextlib
import copy
import gzip
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import verify_rust_worker_profile as v


class ProfileVerifierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(v, 'ROOT', self.root))
        stack.enter_context(mock.patch.object(v.sys, 'platform', 'win32'))
        self.source = {'server/native_simulation.py': 'a'*64, 'tools/benchmark_large_armies.py': 'b'*64}
        self.sources = stack.enter_context(mock.patch.object(v, 'sources', return_value=self.source))
        stack.enter_context(mock.patch.object(v.b, 'source_hashes', return_value=self.source))
        stack.enter_context(mock.patch.object(v.c, 'verify_assets'))
        stack.enter_context(mock.patch.object(v.b, 'validate_args'))
        stack.enter_context(mock.patch.object(v.s, 'SUPPORTED_DLL_SHA256', v.b.digest(b'authored simulation identity')))
        # Windows-path syntax belongs to the summarizer's identity controls;
        # these authored orchestration tests also run on Linux CI temp paths.
        stack.enter_context(mock.patch.object(v.s, 'decoder_identity', side_effect=lambda value: value))
        self.assets, self.journal = self.root/'assets', self.root/'journal'
        self.assets.mkdir()
        self.journal.mkdir()
        self.library = self.root/'decoder.dll'
        self.library.write_bytes(b'authored library identity, never loaded')
        (self.assets/'Simulation.dll').write_bytes(b'authored simulation identity')
        (self.assets/'asset-manifest.json').write_bytes(b'{}')
        data = b'authored bootstrap'
        self.payloads = [bytes([index+1]) for index in range(9)]
        self.input_bytes = b''.join(struct.pack('<I', len(payload))+payload for payload in self.payloads)
        self.rows = [dict(frame=index, phase=v.c.PHASES[index//3], input_sha256=v.b.digest(payload),
                          state_sha256=v.b.digest(b'state'+payload), step_rpc_ms=1.0)
                     for index, payload in enumerate(self.payloads)]
        self.reference = dict(passed=True, native_qualified=True, source_unchanged=True,
            source_at_start={'historical-reference': 'c'*64}, source_at_finish={'historical-reference': 'c'*64},
            frames=9, asset_manifest_sha256=v.b.digest(b'{}'), simulation_sha256=v.b.digest(b'authored simulation identity'),
            bootstrap_sha256=v.b.digest(data), input_journal_sha256=v.b.digest(self.input_bytes),
            workload={'opponent': 'ai', 'seed': 20261117})
        (self.journal/'benchmark.json').write_text(json.dumps(self.reference), encoding='utf-8')
        (self.journal/'bootstrap.pb.gz').write_bytes(gzip.compress(data))
        (self.journal/'frames.bin').write_bytes(self.input_bytes)
        (self.journal/'frames.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in self.rows), encoding='utf-8')
        self.args = SimpleNamespace(assets=self.assets, journal=self.journal, library=self.library,
            library_sha256=v.b.digest(self.library.read_bytes()), output=self.root/'local'/'profile-check',
            timeout_seconds=60, thread_sample_interval=0,
            wine_executable=None, windows_python=None, wine_prefix_template=None, wine_cgroup_parent=None)
        self.calls, self.receipt_hook, self.after_write_hook = [], None, None
        self.runner = stack.enter_context(mock.patch.object(v.b, 'run', side_effect=self.fake_arm))
        # Detailed profile metric validation has its own authored controls. This
        # boundary proves the orchestrator requires that validation to pass.
        self.summary = stack.enter_context(mock.patch.object(v.s, 'summarize', return_value={
            'passed': True, 'control': {'exact_input_and_observable_state_match': True,
                                      'phases': {'movement': {'mean_ratio': 1.2}}}}))

    async def fake_arm(self, options):
        profiled = options.profile_worker
        self.calls.append(options)
        options.output.mkdir(parents=True)
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row['step_rpc_ms'] = 2.0 if profiled else 1.0
        receipt = dict(self.reference, source_at_start=dict(self.source), source_at_finish=dict(self.source),
            profiled=profiled, paced=False, timestep_ms=50, ai=None, replay=str(self.journal),
            replayed_source_hashes=self.reference['source_at_start'],
            profile_thread_interval=options.profile_thread_interval if profiled else None,
            snapshot_decoder=dict(implementation='rust', abi_version=1, library_sha256=self.args.library_sha256,
                                  library_path=str(self.library)),
            worker_runtime=dict(os_name='nt', platform='win32', pointer_bits=64, implementation='cpython',
                                python_version='authored interpreter', executable='authored-python.exe'),
            backend={'kind': 'windows-worker'},
            cleanup=dict(exit_code=0, failure=None, stderr_thread_closed=True, io_threads_closed=True),
            phases={phase: {'frames': 3} for phase in v.c.PHASES})
        if profiled:
            profile = b'{"authored sidecar":"validated by mocked summary boundary"}'
            (options.output/'worker-profile.json').write_bytes(profile)
            receipt['worker_profile_sha256'] = v.b.digest(profile)
        if self.receipt_hook:
            self.receipt_hook(receipt, rows, profiled)
        (options.output/'benchmark.json').write_text(json.dumps(receipt), encoding='utf-8')
        (options.output/'frames.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
        (options.output/'frames.bin').write_bytes(self.input_bytes)
        if self.after_write_hook:
            self.after_write_hook(options, receipt)
        return 0

    def execute(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = asyncio.run(v.run(self.args))
        report = json.loads((self.args.output/'verification.json').read_text())
        return code, report

    def test_current_rust_control_then_profile_exactly_replays_historical_reference(self):
        code, report = self.execute()
        self.assertEqual(code, 0)
        self.assertTrue(report['passed'] and report['source_unchanged'] and report['inputs_and_evidence_unchanged'])
        self.assertEqual([options.profile_worker for options in self.calls], [False, True])
        for options in self.calls:
            self.assertEqual(options.snapshot_decoder_library, self.library)
            self.assertEqual(options.snapshot_decoder_sha256, self.args.library_sha256)
            self.assertEqual(options.replay, self.journal)
            self.assertFalse(options.paced)
            self.assertEqual(options.profile_thread_interval, 0)
        self.assertFalse(report['performance_acceptance_evaluated'] or report['ai_producer_profiled'])
        self.assertTrue(all(arm['exact_input_and_observable_state_match'] for arm in report['arms']))
        self.summary.assert_called_once_with(self.args.output/'profile', self.args.output/'control')
        self.assertEqual(report['summary']['control']['phases']['movement']['mean_ratio'], 1.2)

    def test_wrong_library_hash_is_refused_before_any_worker(self):
        self.args.library_sha256 = '0'*64
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn('input digest differs', report['error'])
        self.runner.assert_not_called()

    def test_changed_reference_input_is_refused_before_any_worker(self):
        (self.journal/'frames.bin').write_bytes(self.input_bytes+b'extra')
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn('input journal digest differs', report['error'])
        self.runner.assert_not_called()

    def test_old_candidate_source_does_not_qualify_as_current(self):
        self.receipt_hook = lambda receipt, rows, profiled: receipt.update(
            source_at_start=self.reference['source_at_start'], source_at_finish=self.reference['source_at_start'])
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn('not bound to current source', report['error'])
        self.assertEqual(len(self.calls), 1)

    def test_every_candidate_frame_state_and_phase_are_checked(self):
        for key, value in (('state_sha256', 'f'*64), ('input_sha256', 'e'*64), ('phase', 'combat')):
            with self.subTest(key=key):
                self.args.output = self.root/'local'/('frame-'+key)
                self.receipt_hook = lambda receipt, rows, profiled: rows[1].update({key: value})
                code, report = self.execute()
                self.assertEqual(code, 1)
                self.assertFalse(report['passed'])

    def test_decoder_profile_and_replay_contract_mismatches_are_refused(self):
        changes = [('snapshot_decoder', {'implementation': 'python'}), ('profiled', False),
                   ('profile_thread_interval', 10), ('ai', {}), ('replay', 'old-other-journal'),
                   ('replayed_source_hashes', {'other': 'd'*64})]
        for index, (key, value) in enumerate(changes):
            with self.subTest(key=key):
                self.args.output = self.root/'local'/f'contract-{index}'
                self.receipt_hook = lambda receipt, rows, profiled: receipt.update({key: value}) if profiled else None
                code, report = self.execute()
                self.assertEqual(code, 1)
                self.assertFalse(report['passed'])

    def test_normal_cleanup_and_same_runtime_are_required(self):
        def cleanup(receipt, rows, profiled):
            if profiled:
                receipt['cleanup']['io_threads_closed'] = False

        def runtime(receipt, rows, profiled):
            if profiled:
                receipt['worker_runtime']['python_version'] = 'another interpreter'

        for index, hook in enumerate((cleanup, runtime)):
            with self.subTest(index=index):
                self.args.output = self.root/'local'/f'lifetime-{index}'
                self.receipt_hook = hook
                code, report = self.execute()
                self.assertEqual(code, 1)
                self.assertFalse(report['passed'])

    def test_failed_profile_keeps_completed_control_and_failure_report(self):
        ordinary = self.fake_arm

        async def fail_profile(options):
            if options.profile_worker:
                raise RuntimeError('authored profile launch failure')
            return await ordinary(options)

        self.runner.side_effect = fail_profile
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertEqual(len(report['arms']), 1)
        self.assertIn('authored profile launch failure', report['error'])
        self.assertTrue((self.args.output/'control'/'benchmark.json').is_file())
        self.assertTrue((self.args.output/'progress.json').is_file())

    def test_missing_profile_validation_cannot_be_promoted(self):
        self.summary.return_value = {'passed': True, 'control': {'exact_input_and_observable_state_match': False}}
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertIn('summary/control did not qualify', report['error'])

    def test_source_library_journal_and_evidence_drift_invalidate_success(self):
        targets = [self.library, self.journal/'frames.jsonl', self.args.output/'control'/'frames.jsonl']
        for index, target in enumerate(targets):
            with self.subTest(target=target):
                # Restore the authored input after each retained failed attempt.
                original = target.read_bytes() if target.exists() else None
                self.args.output = self.root/'local'/f'drift-{index}'
                if index == 2:
                    target = self.args.output/'control'/'frames.jsonl'

                def change_after_profile(options, receipt):
                    if options.profile_worker:
                        target.write_bytes(target.read_bytes()+b' ')

                self.after_write_hook = change_after_profile
                code, report = self.execute()
                self.assertEqual(code, 1)
                self.assertFalse(report['inputs_and_evidence_unchanged'])
                self.assertTrue(report['stability_errors'])
                if original is not None:
                    target.write_bytes(original)
        self.after_write_hook = None
        self.args.output = self.root/'local'/'source-drift'
        self.sources.side_effect = [self.source, {**self.source, 'changed': 'f'*64}]
        code, report = self.execute()
        self.assertEqual(code, 1)
        self.assertFalse(report['source_unchanged'])

    def test_private_fresh_output_and_complete_wine_options_are_required(self):
        for output in (self.root/'public', self.assets/'nested', self.journal/'nested', self.root/'local'):
            with self.subTest(output=output):
                self.args.output = output
                with self.assertRaises(ValueError):
                    v.validate_args(self.args)
        self.args.output = self.root/'local'/'fresh'
        self.args.wine_executable = Path('/usr/bin/wine')
        with self.assertRaisesRegex(ValueError, 'supplied together'):
            v.validate_args(self.args)
        self.runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
