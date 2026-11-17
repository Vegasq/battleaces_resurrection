"""Authored evidence fixtures exercise rejection, never claim native execution."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tools import summarize_worker_timing as summary


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)/'profile'; self.directory.mkdir()
        self.control = Path(self.temporary.name)/'control'; self.control.mkdir()
        self.profile, self.report, self.rows = self.fixture()
        self.save(self.directory, self.profile, self.report, self.rows)
        control = copy.deepcopy(self.report); control['profiled'] = False
        self.save(self.control, self.profile, control, self.rows)

    def fixture(self):
        sources = {name: 'a'*64 for name in summary.PROFILE_SOURCES}
        rows = [dict(frame=i, phase=phase, input_sha256=summary.sha(f'f{i}'.encode()),
                     state_sha256=summary.sha(f'state{i}'.encode()), step_rpc_ms=1)
                for i, phase in enumerate(summary.PHASES)]
        metric = dict(calls=1, wall_ns=100, thread_cpu_ns=20, process_cpu_ns=40, max_wall_ns=100)
        records = []
        for index, (operation, frame) in enumerate([('CREATE', -1), ('STEP', 0), ('STEP', 1), ('STEP', 2), ('CLOSE', 2)], 1):
            metrics = {name: dict(metric) for name in ('ipc.encode', 'ipc.write', 'ipc.decode_metadata')}
            if operation == 'STEP':
                metrics.update({name: dict(metric) for name in ('sim.SimProcessMsg', 'sim.SimStep', 'sim.SimMakeSimFrame',
                    'sim.SimGetSimFrameBuffer', 'decode_snapshot', 'simulation.state', 'simulation.process_frame')})
                metrics['simulation.state']['wall_ns'] = 9000  # Inclusive parent is deliberately much larger.
                metrics['simulation.state']['max_wall_ns'] = 9000
            records.append(dict(request_id=index, operation=operation, frame=frame, replied=True, response_error=False,
                request_payload_bytes=2, active_wall_ns=10000, active_thread_cpu_ns=2000, active_process_cpu_ns=3000,
                receive_wall_ns=500, observer_thread_sample_wall_ns=0, response_bytes=200, metrics=metrics))
        thread = lambda cpu: dict(tid=71, creation=1, kernel_cpu_ns=cpu, user_cpu_ns=cpu)
        profile = dict(schema=1, completed=True, exit_code=0, failure=None, pid=1234, dropped_records=0,
            synthetic_test_backend=False, source_sha256=sources, records=records,
            thread_samples=[dict(available=True, request_id=1, perf_counter_ns=1, threads=[thread(10)]),
                            dict(available=True, request_id=5, perf_counter_ns=1000001, threads=[thread(100)])])
        journal = b''.join(struct.pack('<I', 2)+f'f{i}'.encode() for i in range(3))
        report = dict(passed=True, native_qualified=True, source_unchanged=True, source_at_start=sources,
            source_at_finish=sources, frames=3, bootstrap_sha256='b'*64, simulation_sha256='c'*64,
            asset_manifest_sha256='d'*64, input_journal_sha256=summary.sha(journal), profiled=True,
            worker_pid=1234, ai=None,
            phases={phase: {'frames': 1} for phase in summary.PHASES},
            cleanup=dict(exit_code=0, failure=None, stderr_thread_closed=True, io_threads_closed=True))
        return profile, report, rows

    def save(self, directory, profile, report, rows):
        raw = json.dumps(profile).encode()
        report = dict(report, worker_profile_sha256=summary.sha(raw))
        (directory/'worker-profile.json').write_bytes(raw)
        (directory/'benchmark.json').write_text(json.dumps(report))
        (directory/'frames.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (directory/'frames.bin').write_bytes(b''.join(struct.pack('<I', 2)+f'f{i}'.encode() for i in range(3)))

    def test_exact_control_passes_and_inclusive_parents_are_not_double_counted(self):
        result = summary.summarize(self.directory, self.control)
        self.assertTrue(result['passed'])
        self.assertTrue(result['control']['exact_input_and_observable_state_match'])
        self.assertTrue(result['thread_cpu']['qualified'])
        categories = result['phases']['combat']['categories']
        self.assertAlmostEqual(categories['native_simulation']['fraction_of_active'], .02)
        self.assertAlmostEqual(sum(category['fraction_of_active'] for category in categories.values()), 1)
        self.assertEqual(result['thread_cpu']['busiest_thread_fraction'], 1)

    def test_rebound_profile_still_rejects_missing_coverage_sources_or_cleanup(self):
        mutations = ('truncated', 'duplicate', 'request_gap', 'missing_native', 'source', 'pid', 'dropped',
                     'error', 'synthetic', 'missing_create', 'ai_missing')
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                profile, report, rows = copy.deepcopy((self.profile, self.report, self.rows))
                if mutation == 'truncated': profile['records'].pop(2)
                elif mutation == 'duplicate': profile['records'][2]['frame'] = 0
                elif mutation == 'request_gap': profile['records'][2]['request_id'] = 91
                elif mutation == 'missing_native': del profile['records'][2]['metrics']['sim.SimStep']
                elif mutation == 'source': profile['source_sha256'] = dict(profile['source_sha256'], **{'server/native_ai.py': 'f'*64})
                elif mutation == 'pid': profile['pid'] = 1235
                elif mutation == 'dropped': profile['dropped_records'] = 1
                elif mutation == 'error': profile['records'][2]['response_error'] = True
                elif mutation == 'synthetic': profile['synthetic_test_backend'] = True
                elif mutation == 'missing_create': profile['records'][0]['operation'] = 'STEP'
                else: report['ai'] = {'bots': {'1': 58}}
                self.save(self.directory, profile, report, rows)
                with self.assertRaises(ValueError): summary.summarize(self.directory)

    def test_unbound_profile_hash_truncated_journal_and_phase_changes_refused(self):
        for mutation in ('profile_sha', 'journal', 'phase', 'trace', 'cleanup', 'source_finish'):
            with self.subTest(mutation=mutation):
                profile, report, rows = copy.deepcopy((self.profile, self.report, self.rows))
                if mutation == 'phase': rows[1]['phase'], rows[2]['phase'] = rows[2]['phase'], rows[1]['phase']
                elif mutation == 'trace': rows.pop()
                elif mutation == 'cleanup': report['cleanup']['exit_code'] = 1
                elif mutation == 'source_finish': report['source_at_finish'] = {}
                self.save(self.directory, profile, report, rows)
                if mutation == 'profile_sha':
                    (self.directory/'worker-profile.json').write_text(json.dumps({**profile, 'pid': 9999}))
                elif mutation == 'journal':
                    (self.directory/'frames.bin').write_bytes(b'\x02\x00\x00\x00f')
                with self.assertRaises(ValueError): summary.summarize(self.directory)

    def test_control_state_mismatch_cannot_be_called_observer_overhead(self):
        rows = copy.deepcopy(self.rows); rows[1]['state_sha256'] = 'f'*64
        report = {**self.report, 'profiled': False}
        self.save(self.control, self.profile, report, rows)
        with self.assertRaisesRegex(ValueError, 'control input/state/phase differs'):
            summary.summarize(self.directory, self.control)

    def test_thread_counter_identity_and_sample_order_are_checked(self):
        for mutation in ('decrease', 'timestamp', 'request', 'duplicate'):
            with self.subTest(mutation=mutation):
                profile = copy.deepcopy(self.profile)
                sample = profile['thread_samples'][1]
                if mutation == 'decrease': sample['threads'][0]['kernel_cpu_ns'] = sample['threads'][0]['user_cpu_ns'] = 0
                elif mutation == 'timestamp': sample['perf_counter_ns'] = 1
                elif mutation == 'request': sample['request_id'] = 99
                else: sample['threads'].append(dict(sample['threads'][0]))
                self.save(self.directory, profile, self.report, self.rows)
                with self.assertRaises(ValueError): summary.summarize(self.directory)

    def test_absent_thread_cpu_is_explicitly_unqualified(self):
        profile = copy.deepcopy(self.profile)
        profile['thread_samples'] = [{'available': False, 'reason': 'unavailable', 'threads': []}]
        self.save(self.directory, profile, self.report, self.rows)
        result = summary.summarize(self.directory)
        self.assertFalse(result['thread_cpu']['qualified'])
        self.assertIsNone(result['thread_cpu']['busiest_thread_fraction'])


    def hybrid_fixture(self):
        profile, report, rows = copy.deepcopy((self.profile, self.report, self.rows))
        sources = dict(profile['source_sha256'], **{name: 'a'*64 for name in summary.HYBRID_PROFILE_SOURCES})
        profile.update(pid=32, launch_kind='native-linux-wine-worker', source_sha256=sources)
        report.update(backend=dict(kind='native-linux-wine-worker'), native_worker_pid=32,
            source_at_start=sources, source_at_finish=sources,
            worker_runtime=dict(platform='win32', os_name='nt', pointer_bits=64, implementation='cpython',
                                python_version='authored Windows Python', executable='Z:\\python.exe'),
            backend_statistics=dict(guardian_pid=1234, cleanup_complete=True, prefix_removed=True,
                                    cgroup_removed=True, exit_code=0, native_exit_code=0))
        return profile, report, rows

    def test_hybrid_profile_binds_native_pid_and_retained_guardian_cleanup(self):
        profile, report, rows = self.hybrid_fixture()
        self.save(self.directory, profile, report, rows)
        self.assertTrue(summary.summarize(self.directory)['passed'])

    def test_hybrid_guardian_profile_cannot_masquerade_as_native_worker(self):
        for mutation in ('guardian_pid', 'no_native', 'bool_native', 'wrong_launch', 'no_launch', 'runtime',
                         'cleanup', 'native_exit', 'wrong_guardian', 'source', 'missing_backend', 'unknown_backend'):
            with self.subTest(mutation=mutation):
                profile, report, rows = self.hybrid_fixture()
                if mutation == 'guardian_pid': profile['pid'] = report['worker_pid']
                elif mutation == 'no_native': del report['native_worker_pid']
                elif mutation == 'bool_native': report['native_worker_pid'] = True
                elif mutation == 'wrong_launch': profile['launch_kind'] = 'direct-worker'
                elif mutation == 'no_launch': del profile['launch_kind']
                elif mutation == 'runtime': report['worker_runtime']['platform'] = 'linux'
                elif mutation == 'cleanup': report['backend_statistics']['cgroup_removed'] = False
                elif mutation == 'native_exit': report['backend_statistics']['native_exit_code'] = -9
                elif mutation == 'wrong_guardian': report['backend_statistics']['guardian_pid'] += 1
                elif mutation == 'source': del profile['source_sha256'][summary.HYBRID_PROFILE_SOURCES[0]]
                elif mutation == 'missing_backend': del report['backend']
                else: report['backend']['kind'] = 'unrecognized'
                self.save(self.directory, profile, report, rows)
                with self.assertRaises(ValueError): summary.summarize(self.directory)

    def test_direct_legacy_report_does_not_switch_binding_from_native_pid_field(self):
        profile, report, rows = copy.deepcopy((self.profile, self.report, self.rows))
        report['native_worker_pid'] = 32
        self.save(self.directory, profile, report, rows)
        self.assertTrue(summary.summarize(self.directory)['passed'])
        profile['pid'] = 32
        self.save(self.directory, profile, report, rows)
        with self.assertRaisesRegex(ValueError, 'PID differs'): summary.summarize(self.directory)


if __name__ == '__main__':
    unittest.main()
