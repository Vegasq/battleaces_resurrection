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
                    'sim.SimGetSimFrameBuffer', 'decode_snapshot', 'simulation.state', 'simulation.process_frame', 'simulation.snapshot_bytes')})
                metrics['simulation.state']['wall_ns'] = 9000  # Inclusive parent is deliberately much larger.
                metrics['simulation.state']['max_wall_ns'] = 9000
                for label, ns in (('simulation.process_frame', 700), ('simulation.snapshot_bytes', 500)):
                    metrics[label].update(wall_ns=ns, max_wall_ns=ns)
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
            source_at_finish=sources, frames=3, bootstrap_sha256='b'*64, simulation_sha256=summary.SUPPORTED_DLL_SHA256,
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

    def rust_fixture(self, hybrid=False):
        profile, report, rows = (self.hybrid_fixture() if hybrid else copy.deepcopy((self.profile, self.report, self.rows)))
        sources = {**profile['source_sha256'], **{name: 'a'*64 for name in summary.RUST_PROFILE_SOURCES}}
        identity = dict(implementation='rust', abi_version=1, library_sha256='e'*64,
                        library_path='Z:\\owned\\decoder.dll' if hybrid else 'C:\\owned\\decoder.dll')
        profile.update(snapshot_decoder=identity, snapshot_decoder_requested=dict(identity), source_unchanged=True,
            snapshot_decoder_library_unchanged=True, metric_parents=dict(summary.RUST_METRIC_PARENTS), source_sha256=sources)
        report.update(snapshot_decoder=dict(identity), source_at_start=sources, source_at_finish=sources)
        if not hybrid:
            report['worker_runtime'] = dict(platform='win32', os_name='nt', pointer_bits=64, implementation='cpython',
                                           python_version='authored Windows Python', executable='C:\\python.exe')
        for row in profile['records']:
            if row['operation'] != 'STEP':
                continue
            metrics = row['metrics']
            del metrics['decode_snapshot']
            del metrics['simulation.state']
            for name in summary.RUST_METRIC_PARENTS:
                wall = 800 if name == 'rust.decode' else 100
                metrics[name] = dict(calls=1, wall_ns=wall, thread_cpu_ns=20, process_cpu_ns=40, max_wall_ns=wall)
        return profile, report, rows

    def test_rust_direct_and_wine_children_partition_without_double_counting(self):
        for hybrid in (False, True):
            with self.subTest(hybrid=hybrid):
                profile, report, rows = self.rust_fixture(hybrid)
                self.save(self.directory, profile, report, rows)
                control = dict(report, profiled=False)
                self.save(self.control, profile, control, rows)
                result = summary.summarize(self.directory, self.control)
                self.assertTrue(result['passed'])
                self.assertTrue(result['control']['exact_runtime_and_decoder_identity_match'])
                categories = result['phases']['combat']['categories']
                self.assertAlmostEqual(sum(value['fraction_of_active'] for key, value in categories.items()
                                           if key.startswith('rust_')), .08)
                self.assertAlmostEqual(categories['rust_adapter_overhead']['mean_ms_per_frame'], .0003)
                self.assertEqual(categories['snapshot_decode']['mean_ms_per_frame'], 0)
                self.assertAlmostEqual(sum(value['fraction_of_active'] for value in categories.values()), 1)
                self.assertEqual(result['metric_parents'], summary.RUST_METRIC_PARENTS)

    def test_rust_requires_exact_loaded_requested_library_source_and_parent_schema(self):
        mutations = ('missing_identity', 'requested', 'hash', 'path', 'relative_path', 'abi', 'bool_abi',
                     'source_changed', 'library_changed', 'missing_source', 'wrong_source', 'parent_map', 'runtime')
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                profile, report, rows = self.rust_fixture()
                if mutation == 'missing_identity': del profile['snapshot_decoder']
                elif mutation == 'requested': profile['snapshot_decoder_requested']['library_sha256'] = 'f'*64
                elif mutation == 'hash': report['snapshot_decoder']['library_sha256'] = 'f'*64
                elif mutation == 'path': report['snapshot_decoder']['library_path'] = 'C:\\other.dll'
                elif mutation == 'relative_path': profile['snapshot_decoder']['library_path'] = 'relative.dll'
                elif mutation == 'abi': report['snapshot_decoder']['abi_version'] = 2
                elif mutation == 'bool_abi': report['snapshot_decoder']['abi_version'] = True
                elif mutation == 'source_changed': profile['source_unchanged'] = False
                elif mutation == 'library_changed': profile['snapshot_decoder_library_unchanged'] = False
                elif mutation == 'missing_source': del profile['source_sha256'][summary.RUST_PROFILE_SOURCES[0]]
                elif mutation == 'wrong_source': profile['source_sha256'] = {**profile['source_sha256'], summary.RUST_PROFILE_SOURCES[0]: 'f'*64}
                elif mutation == 'parent_map': profile['metric_parents']['rust.json.loads'] = None
                else: report['worker_runtime']['platform'] = 'linux'
                self.save(self.directory, profile, report, rows)
                with self.assertRaises(ValueError): summary.summarize(self.directory)

    def test_rust_missing_child_or_mixed_python_path_is_not_partial_success(self):
        for name in (*summary.RUST_METRIC_PARENTS, 'simulation.snapshot_bytes', 'mixed_python'):
            with self.subTest(name=name):
                profile, report, rows = self.rust_fixture()
                metrics = profile['records'][2]['metrics']
                if name == 'mixed_python':
                    metrics['decode_snapshot'] = dict(metrics['rust.ffi.decode'])
                else:
                    del metrics[name]
                self.save(self.directory, profile, report, rows)
                with self.assertRaises(ValueError): summary.summarize(self.directory)

    def test_negative_overhead_duration_overflow_and_bad_calls_are_refused(self):
        for mutation in ('negative', 'overflow', 'parent_overflow', 'parent_smaller', 'bad_max', 'call_count',
                         'negative_observer', 'rpc_negative', 'rpc_overflow', 'receive_too_short'):
            with self.subTest(mutation=mutation):
                profile, report, rows = self.rust_fixture()
                record = profile['records'][2]
                metrics = record['metrics']
                if mutation == 'negative': metrics['rust.ffi.decode']['wall_ns'] = -1
                elif mutation == 'overflow': metrics['rust.ffi.decode']['wall_ns'] = 1 << 64
                elif mutation == 'parent_overflow': record['active_wall_ns'] = 1 << 64
                elif mutation == 'parent_smaller': metrics['rust.decode'].update(wall_ns=400, max_wall_ns=400)
                elif mutation == 'bad_max': metrics['rust.ffi.decode']['max_wall_ns'] = 99
                elif mutation == 'call_count': metrics['rust.ffi.decode']['calls'] = 2
                elif mutation == 'negative_observer': record['observer_thread_sample_wall_ns'] = -1
                elif mutation == 'rpc_negative': rows[1]['step_rpc_ms'] = -.001
                elif mutation == 'rpc_overflow': rows[1]['step_rpc_ms'] = 10**400
                else: record['receive_wall_ns'] = 1
                self.save(self.directory, profile, report, rows)
                with self.assertRaises(ValueError): summary.summarize(self.directory)

    def test_post_reply_worker_tail_keeps_signed_residual_and_explicit_scope(self):
        profile, report, rows = self.rust_fixture(hybrid=True)
        # A parent may finish at9us while the child records10us active plus1us
        # pre-active observer time: the child endpoint follows its reply write.
        # Native/decoder leaf costs remain inside the worker's active interval.
        rows[1]['step_rpc_ms'] = .009
        profile['records'][2]['observer_thread_sample_wall_ns'] = 1000
        self.save(self.directory, profile, report, rows)
        result = summary.summarize(self.directory)
        phase = result['phases']['movement']
        self.assertTrue(result['passed'])
        self.assertAlmostEqual(phase['step_rpc_minus_active_ms']['mean'], -.001)
        self.assertAlmostEqual(phase['step_rpc_minus_active_and_thread_sample_ms']['mean'], -.002)
        self.assertEqual(phase['rpc_residual_diagnostics']['step_negative_count'], 1)
        self.assertFalse(phase['rpc_residual_diagnostics']['negative_residual_is_qualification_failure'])
        self.assertTrue(result['rpc_residual_scope']['worker_endpoint_after_reply_write'])
        self.assertFalse(result['rpc_residual_scope']['causal_transport_cost'])
        self.assertAlmostEqual(sum(v['fraction_of_active'] for v in phase['categories'].values()), 1)

    def test_signed_rpc_difference_keeps_bounded_nonnegative_raw_inputs(self):
        row = dict(operation='STEP', active_wall_ns=10000, observer_thread_sample_wall_ns=1000)
        for field, value in (('active_wall_ns', -1), ('active_wall_ns', summary.MAX_DURATION_NS + 1),
                             ('observer_thread_sample_wall_ns', -1), ('observer_thread_sample_wall_ns', True)):
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, 'outside bound'):
                    summary.rpc_residual({**row, field: value}, {'step_rpc_ms': .009})
        bot_row = {**row, 'operation': 'BOT_INPUT'}
        self.assertAlmostEqual(summary.rpc_residual(bot_row, {'ai_rpc_ms': .009}), -.002)

    def test_validation_alone_refuses_overlapping_children(self):
        profile, report, rows = self.rust_fixture()
        profile['records'][2]['metrics']['rust.decode'].update(wall_ns=400, max_wall_ns=400)
        self.save(self.directory, profile, report, rows)
        benchmark = summary.load_benchmark(self.directory)
        loaded, digest = summary.read_json(self.directory/'worker-profile.json')
        with self.assertRaisesRegex(ValueError, 'negative overhead'):
            summary.validate_profile(loaded, benchmark, digest)

    def test_control_decoder_runtime_source_backend_and_workload_must_match(self):
        for mutation in ('decoder', 'runtime', 'source', 'backend', 'workload', 'paced', 'timestep', 'ai'):
            with self.subTest(mutation=mutation):
                profile, report, rows = self.rust_fixture()
                control = copy.deepcopy(report); control['profiled'] = False
                if mutation == 'decoder': control['snapshot_decoder'] = {'implementation': 'python'}
                elif mutation == 'runtime': control['worker_runtime']['python_version'] = 'another runtime'
                elif mutation == 'source':
                    control['source_at_start'] = control['source_at_finish'] = {**control['source_at_start'], 'extra.py': 'f'*64}
                elif mutation == 'backend': control['backend'] = {'kind': 'windows-worker', 'worker_interpreter_sha256': 'f'*64}
                elif mutation == 'workload': control['workload'] = {'opponent': 'ai'}
                elif mutation == 'paced': control['paced'] = True
                elif mutation == 'timestep': control['timestep_ms'] = 60
                else: control['ai'] = {'bots': {'1': 58}}
                self.save(self.directory, profile, report, rows)
                self.save(self.control, profile, control, rows)
                with self.assertRaises(ValueError): summary.summarize(self.directory, self.control)

    def test_nonoriginal_native_hash_and_false_successful_cleanup_are_rejected(self):
        for mutation in ('native', 'cleanup_error'):
            with self.subTest(mutation=mutation):
                profile, report, rows = self.rust_fixture()
                if mutation == 'native': report['simulation_sha256'] = 'f'*64
                else: report['cleanup_error'] = 'forced exit'
                self.save(self.directory, profile, report, rows)
                with self.assertRaises(ValueError): summary.summarize(self.directory)

    def test_profiled_control_delta_can_be_negative_without_negative_accounting(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row['step_rpc_ms'] = 2
        self.save(self.control, self.profile, {**self.report, 'profiled': False}, rows)
        result = summary.summarize(self.directory, self.control)
        self.assertEqual(result['control']['phases']['combat']['paired_rpc_delta_ms']['mean'], -1)


if __name__ == '__main__':
    unittest.main()
