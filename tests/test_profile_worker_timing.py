"""Diagnostic-only profiling preserves real worker IPC and process isolation."""
import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server import simulation_worker as ipc, worker_client
from server.protobuf_wire import field_uint
from server.worker_client import SimulationWorker, WorkerTimeout
from tools import profile_worker_timing as profile


def frame(number):
    return field_uint(1, number) + field_uint(2, 20) + field_uint(3, 50)


class LaunchProxyTests(unittest.TestCase):
    def make(self):
        calls = []
        original = SimpleNamespace(PIPE=-1)
        module = SimpleNamespace(subprocess=original)
        def popen(args, **kwargs):
            self.assertIs(module.subprocess, original, 'proxy must restore before spawning or awaiting')
            calls.append((args, kwargs))
            return 'owned child'
        original.Popen = popen
        proxy = profile._OneLaunch(module, Path.cwd() / 'profile.json', 100, 20)
        module.subprocess = proxy
        args = [sys.executable, '-I', '-S', '-B', '-u', '-c', profile.WORKER_BOOTSTRAP,
                str(profile.ROOT), '--stdio']
        kwargs = dict(stdin=-1, stdout=-1, stderr=-1, close_fds=True, bufsize=0,
                      env={'marker': 'unchanged'}, cwd=Path.cwd(), creationflags=0)
        return module, original, proxy, args, kwargs, calls

    def test_only_bootstrap_and_explicit_diagnostic_arguments_change(self):
        module, original, proxy, args, kwargs, calls = self.make()
        self.assertEqual(proxy.Popen(args, **kwargs), 'owned child')
        command, options = calls[0]
        self.assertEqual(command[:6], args[:6])
        self.assertEqual(command[6], profile.PROFILE_BOOTSTRAP)
        self.assertEqual(command[7:9], args[7:9])
        self.assertEqual(options, kwargs)
        self.assertEqual(args[6], profile.WORKER_BOOTSTRAP)
        self.assertIs(module.subprocess, original)
        with self.assertRaisesRegex(RuntimeError, 'ownership changed'):
            proxy.Popen(args, **kwargs)

    def test_wrong_command_pipe_or_thread_is_refused_without_spawn(self):
        for mutation in ('root', 'command', 'shell', 'pipe', 'thread', 'extra'):
            with self.subTest(mutation=mutation):
                module, original, proxy, args, kwargs, calls = self.make()
                if mutation == 'root': args[7] = 'unrelated checkout'
                elif mutation == 'command': args[6] = 'untrusted code'
                elif mutation == 'shell': kwargs['shell'] = True
                elif mutation == 'pipe': kwargs['stdout'] = None
                elif mutation == 'thread': proxy.owner_thread = -1
                else: args.append('--unexpected')
                with self.assertRaises(RuntimeError): proxy.Popen(args, **kwargs)
                self.assertEqual(calls, [])
                self.assertIs(module.subprocess, original)


class RecorderTests(unittest.TestCase):
    def test_real_protocol_roundtrip_is_byte_identical_and_hooks_restore(self):
        request = b''.join((ipc.encode_message(ipc.CREATE, 1, -1, payload=b'private synthetic bytes'),
                            ipc.encode_message(ipc.STEP, 2, 0, {'dt_ms': 50}, frame(0)),
                            ipc.encode_message(ipc.CLOSE, 3, 0)))
        control, instrumented = io.BytesIO(), io.BytesIO()
        self.assertEqual(ipc.serve(io.BytesIO(request), control, test_backend=True), 0)
        original = ipc.read_message, ipc.write_packet, ipc.encode_message
        recorder = profile.Recorder(thread_sample_interval=0)
        with profile.instrumentation(recorder):
            self.assertEqual(ipc.serve(io.BytesIO(request), instrumented, test_backend=True), 0)
        self.assertEqual(instrumented.getvalue(), control.getvalue())
        self.assertEqual((ipc.read_message, ipc.write_packet, ipc.encode_message), original)
        self.assertEqual([row['operation'] for row in recorder.records], ['CREATE', 'STEP', 'CLOSE'])
        for row in recorder.records:
            self.assertTrue(row['replied'])
            self.assertFalse(row['response_error'])
            self.assertGreater(row['active_wall_ns'], 0)
            self.assertGreater(row['metrics']['ipc.encode']['wall_ns'], 0)
            self.assertIn('ipc.decode_metadata', row['metrics'])
        self.assertNotIn('private synthetic bytes', json.dumps(recorder.records))

    def test_error_reply_retained_and_hooks_restore_after_exception(self):
        request = ipc.encode_message(ipc.CREATE, 1, -1, payload=b'test')
        request += ipc.encode_message(ipc.STEP, 2, 5, {'dt_ms': 50}, frame(5))
        recorder = profile.Recorder(thread_sample_interval=0)
        original = ipc.read_message
        with profile.instrumentation(recorder):
            self.assertEqual(ipc.serve(io.BytesIO(request), io.BytesIO(), test_backend=True), 2)
        self.assertTrue(recorder.records[-1]['response_error'])
        self.assertIs(ipc.read_message, original)
        with self.assertRaisesRegex(ValueError, 'test exception'):
            with profile.instrumentation(recorder):
                raise ValueError('test exception')
        self.assertIs(ipc.read_message, original)

    def test_record_and_thread_sample_caps_are_hard_bounds(self):
        request = ipc.encode_message(ipc.CREATE, 1, -1, payload=b'test')
        request += b''.join(ipc.encode_message(ipc.STEP, n + 2, n, {'dt_ms': 50}, frame(n)) for n in range(5))
        request += ipc.encode_message(ipc.CLOSE, 7, 4)
        recorder = profile.Recorder(2, 1)
        with patch.object(profile, 'thread_cpu_snapshot', return_value={'available': True, 'threads': []}):
            with profile.instrumentation(recorder):
                self.assertEqual(ipc.serve(io.BytesIO(request), io.BytesIO(), test_backend=True), 0)
        self.assertEqual(len(recorder.records), 2)
        self.assertEqual(recorder.dropped_records, 5)
        self.assertEqual(len(recorder.thread_samples), 2)

    def test_live_thread_sample_has_current_thread_and_nonnegative_cpu(self):
        sample = profile.thread_cpu_snapshot()
        if not sample['available']:
            self.skipTest(sample['reason'])
        own = [item for item in sample['threads'] if item['tid'] == threading.get_native_id()]
        self.assertEqual(len(own), 1)
        self.assertGreater(own[0]['creation'], 0)
        self.assertGreaterEqual(own[0]['kernel_cpu_ns'], 0)
        self.assertGreaterEqual(own[0]['user_cpu_ns'], 0)


class ProfiledWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.workers = []

    async def asyncTearDown(self):
        await asyncio.gather(*(worker.close() for worker in self.workers))
        for worker in self.workers:
            self.assertIsNotNone(worker.process.poll())
            self.assertFalse(worker._stderr_thread.is_alive())
        self.temporary.cleanup()

    async def make(self, name, **kwargs):
        worker = await profile.create_profiled_worker(b'owned synthetic world', profile_path=self.directory / name,
            working_directory=self.directory, _test_backend=True, **kwargs)
        self.workers.append(worker)
        return worker

    async def test_concurrent_profiled_and_normal_workers_are_isolated(self):
        original = worker_client.subprocess
        first, normal, second = await asyncio.gather(self.make('one.json'),
            SimulationWorker.create(b'owned synthetic world', _test_backend=True, working_directory=self.directory),
            self.make('two.json'))
        self.workers.append(normal)
        self.assertIs(worker_client.subprocess, original)
        states = await asyncio.gather(*(worker.process_frame(frame(0)) for worker in (first, normal, second)))
        self.assertEqual(states[0].state, states[1].state)
        self.assertEqual(states[1].state, states[2].state)
        snapshots = await asyncio.gather(*(worker.snapshot() for worker in (first, normal, second)))
        self.assertEqual(snapshots[0], snapshots[1]); self.assertEqual(snapshots[1], snapshots[2])
        await asyncio.gather(*(worker.close() for worker in (first, normal, second)))
        for name, worker in (('one.json', first), ('two.json', second)):
            report = json.loads((self.directory / name).read_text())
            self.assertTrue(report['completed'])
            self.assertEqual(report['exit_code'], 0)
            self.assertEqual(report['pid'], worker.pid)
            self.assertEqual(report['dropped_records'], 0)
            self.assertEqual([row['operation'] for row in report['records']], ['CREATE', 'STEP', 'SNAPSHOT', 'CLOSE'])
            self.assertIn('server/native_simulation.py', report['source_sha256'])
        self.assertEqual(sorted(path.name for path in self.directory.iterdir()), ['one.json', 'two.json'])

    async def test_failure_before_spawn_restores_parent_and_existing_output_is_preserved(self):
        original = worker_client.subprocess
        with self.assertRaises(ValueError):
            await profile.create_profiled_worker(b'', profile_path=self.directory / 'bad.json', _test_backend=True)
        self.assertIs(worker_client.subprocess, original)
        existing = self.directory / 'existing.json'; existing.write_text('keep this evidence')
        with self.assertRaises(FileExistsError):
            await self.make(existing.name)
        self.assertEqual(existing.read_text(), 'keep this evidence')
        self.assertIs(worker_client.subprocess, original)

    async def test_indirect_backend_is_refused_before_installing_launch_proxy(self):
        original = worker_client.subprocess
        with self.assertRaisesRegex(ValueError, 'explicit WineWorkerBackend'):
            await profile.create_profiled_worker(b'test', profile_path=self.directory/'hybrid.json', backend=object())
        self.assertIs(worker_client.subprocess, original)
        self.assertFalse((self.directory/'hybrid.json').exists())

    async def test_forced_timeout_retains_incomplete_evidence_not_false_success(self):
        worker = await self.make('incomplete.json', request_timeout=0.15)
        await worker._test_control('hang_next_step')
        with self.assertRaises(WorkerTimeout):
            await worker.process_frame(frame(0))
        self.assertIsNotNone(worker.process.poll())
        self.assertEqual((self.directory / 'incomplete.json').read_bytes(), b'')
        self.assertIs(worker_client.subprocess, subprocess)

    async def test_synthetic_gate_cannot_be_enabled_by_profile_alone(self):
        output = self.directory / 'not-run.json'
        environment = dict(os.environ); environment.pop('BA_ENABLE_SYNTHETIC_WORKER_TESTS', None)
        args = [sys.executable, '-I', '-B', '-c', profile.PROFILE_BOOTSTRAP, str(profile.ROOT),
                '--stdio', '--test-backend', '--profile-output', str(output)]
        result = await asyncio.to_thread(subprocess.run, args, input=b'', capture_output=True, env=environment,
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'explicit test environment gate', result.stderr)
        self.assertFalse(output.exists())


class HybridLaunchProxyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.backend = SimpleNamespace(wine_executable=self.directory/'wine', windows_python=self.directory/'python.exe',
                                       prefix_template=self.directory/'template', cgroup_parent=self.directory/'group')
        self.runtime = self.directory/'ba-wine-worker-authored'
        self.argv = [value for pair in zip(profile.GUARDIAN_FIELDS,
            (str(self.backend.wine_executable), str(self.backend.windows_python), str(self.backend.prefix_template),
             str(self.directory), str(self.runtime), str(self.backend.cgroup_parent/self.runtime.name),
             str(os.getpid()), '10', '11')) for value in pair]
        self.calls = []
        self.original = SimpleNamespace(PIPE=-1)
        self.module = SimpleNamespace(subprocess=self.original)
        def popen(args, **kwargs):
            self.assertIs(self.module.subprocess, self.original)
            self.calls.append((args, kwargs))
            return 'owned child'
        self.original.Popen = popen

    def parent(self):
        from server.wine_worker import GUARDIAN_BOOTSTRAP
        proxy = profile._OneGuardianLaunch(self.module, self.directory/'profile.json', 100, 0,
                                           self.backend, self.directory)
        self.module.subprocess = proxy
        args = [sys.executable, '-I', '-S', '-B', '-u', '-c', GUARDIAN_BOOTSTRAP, str(profile.ROOT)]+self.argv
        kwargs = dict(cwd=self.directory, stdin=-1, stdout=-1, stderr=-1, close_fds=True,
                      pass_fds=(10, 11), start_new_session=True, env={'unchanged': 'yes'}, bufsize=0)
        return proxy, args, kwargs

    def child(self):
        proxy = profile._OneWineChildLaunch(self.module, self.directory/'profile.json', 100, 0, self.argv)
        self.module.subprocess = proxy
        args = [str(self.backend.wine_executable), 'wine:'+str(self.backend.windows_python),
                '-I', '-S', '-B', '-u', '-c', profile.WORKER_BOOTSTRAP, 'wine:'+str(profile.ROOT), '--stdio']
        kwargs = dict(cwd=self.runtime/'work', stdin=sys.stdin.buffer, stdout=sys.stdout.buffer,
                      stderr=sys.stderr.buffer, close_fds=True, pass_fds=(17,), preexec_fn=lambda: None,
                      env=dict(WINEPREFIX=str(self.runtime/'prefix'), WINEARCH='win64', WINEDLLOVERRIDES='mscoree,mshtml='))
        return proxy, args, kwargs

    def test_guardian_substitution_preserves_exact_ownership_and_restores_before_spawn(self):
        proxy, args, kwargs = self.parent()
        self.assertEqual(proxy.Popen(args, **kwargs), 'owned child')
        command, options = self.calls[0]
        self.assertEqual(command[:6], args[:6])
        self.assertEqual(command[6], profile.GUARDIAN_PROFILE_BOOTSTRAP)
        self.assertEqual(command[7:-6], args[7:])
        self.assertEqual(options, kwargs)
        self.assertIs(self.module.subprocess, self.original)

    def test_guardian_invalid_command_and_ownership_refuse_before_launch(self):
        for mutation in ('root', 'cgroup', 'runtime', 'prefix', 'fds', 'session', 'thread', 'shell', 'extra'):
            with self.subTest(mutation=mutation):
                proxy, args, kwargs = self.parent()
                if mutation == 'root': args[7] = 'unrelated-root'
                elif mutation in ('cgroup', 'runtime', 'prefix'):
                    field = {'cgroup': '--cgroup', 'runtime': '--runtime-directory', 'prefix': '--prefix-template'}[mutation]
                    args[args.index(field)+1] = str(self.directory/'unowned')
                elif mutation == 'fds': kwargs['pass_fds'] = (10, 18)
                elif mutation == 'session': kwargs['start_new_session'] = False
                elif mutation == 'thread': proxy.owner_thread = -1
                elif mutation == 'shell': kwargs['shell'] = True
                else: args += ['--extra', 'x']
                with self.assertRaises(RuntimeError): proxy.Popen(args, **kwargs)
                self.assertIs(self.module.subprocess, self.original)
                self.assertFalse(self.calls)

    def test_wine_substitution_keeps_cgroup_preexec_private_prefix_and_stdio(self):
        proxy, args, kwargs = self.child()
        with patch('server.wine_worker.windows_path', side_effect=lambda p: 'wine:'+str(p)):
            self.assertEqual(proxy.Popen(args, **kwargs), 'owned child')
        command, options = self.calls[0]
        self.assertEqual(command[:7], args[:7])
        self.assertEqual(command[7], profile.PROFILE_BOOTSTRAP)
        self.assertEqual(command[8:10], args[8:10])
        self.assertEqual(command[command.index('--profile-output')+1], 'wine:'+str(self.directory)+'\\profile.json')
        self.assertIn('--profile-hybrid-worker', command)
        self.assertEqual(options, kwargs)
        self.assertIs(options['preexec_fn'], kwargs['preexec_fn'])
        self.assertIs(self.module.subprocess, self.original)

    def test_wine_child_malformed_or_synthetic_launch_refuses_and_restores(self):
        for mutation in ('root', 'synthetic', 'stdio', 'preexec', 'fds', 'prefix', 'shell'):
            with self.subTest(mutation=mutation):
                proxy, args, kwargs = self.child()
                if mutation == 'root': args[8] = 'other-root'
                elif mutation == 'synthetic': args.append('--test-backend')
                elif mutation == 'stdio': kwargs['stdout'] = -1
                elif mutation == 'preexec': kwargs['preexec_fn'] = None
                elif mutation == 'fds': kwargs['pass_fds'] = ()
                elif mutation == 'prefix': kwargs['env']['WINEPREFIX'] = 'shared-prefix'
                else: kwargs['shell'] = True
                with patch('server.wine_worker.windows_path', side_effect=lambda p: 'wine:'+str(p)):
                    with self.assertRaises(RuntimeError): proxy.Popen(args, **kwargs)
                self.assertIs(self.module.subprocess, self.original)
                self.assertFalse(self.calls)

    def test_diagnostic_guardian_reuses_original_main_and_restores_on_failure(self):
        from server import wine_worker_guardian as guardian
        original = guardian.subprocess
        def fail(argv):
            self.assertEqual(argv, self.argv)
            self.assertIsInstance(guardian.subprocess, profile._OneWineChildLaunch)
            raise ValueError('authored prelaunch refusal')
        with patch.object(guardian, 'main', side_effect=fail), patch.object(profile, '_wine_output', return_value='Z:\\profile.json'):
            with self.assertRaisesRegex(ValueError, 'authored prelaunch'):
                profile.guardian_main(self.argv+['--profile-output', str(self.directory/'profile.json'),
                                                '--max-records', '100', '--thread-sample-interval', '0'])
        self.assertIs(guardian.subprocess, original)

    def test_output_translation_never_creates_file_and_rejects_invalid_name_or_existing(self):
        with patch('server.wine_worker.windows_path', return_value='Z:\\owned') as translate:
            self.assertEqual(profile._wine_output(self.directory/'new.json'), 'Z:\\owned\\new.json')
            translate.assert_called_once_with(self.directory)
            self.assertFalse((self.directory/'new.json').exists())
            with self.assertRaises(ValueError): profile._wine_output(self.directory/'bad:name.json')
            (self.directory/'existing').write_bytes(b'keep')
            with self.assertRaises(ValueError): profile._wine_output(self.directory/'existing')
            self.assertEqual((self.directory/'existing').read_bytes(), b'keep')

    def test_thread_enumeration_is_disabled_by_default(self):
        recorder = profile.Recorder()
        with patch.object(profile, 'thread_cpu_snapshot', side_effect=AssertionError('must not enumerate')):
            self.assertEqual(recorder.sample_threads(1), 0)
        self.assertEqual(recorder.thread_samples, [])


class HybridProfileConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_profiled_hybrid_restores_before_await_and_leaves_normal_hybrid_and_direct_alone(self):
        from server import wine_worker
        helper = HybridLaunchProxyTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        backend = object.__new__(wine_worker.WineWorkerBackend)
        for name, value in vars(helper.backend).items(): object.__setattr__(backend, name, value)
        _, hybrid_args, hybrid_kwargs = helper.parent()
        helper.module.subprocess = helper.original
        normal = SimpleNamespace(PIPE=-1)
        calls = []
        def popen(args, **kwargs):
            self.assertIs(wine_worker.subprocess, normal)
            self.assertIs(worker_client.subprocess, normal)
            calls.append(args)
            return args[6]
        normal.Popen = popen
        async def create(data, dll=None, **kwargs):
            if kwargs.get('backend') is backend:
                result = wine_worker.subprocess.Popen(list(hybrid_args), **hybrid_kwargs)
            else:
                args = [sys.executable, '-I', '-S', '-B', '-u', '-c', profile.WORKER_BOOTSTRAP, str(profile.ROOT), '--stdio']
                result = worker_client.subprocess.Popen(args, stdin=-1, stdout=-1, stderr=-1, close_fds=True)
            await asyncio.sleep(0)
            return result
        with patch.object(wine_worker, 'subprocess', normal), patch.object(worker_client, 'subprocess', normal), \
                patch.object(profile, '_wine_output', return_value='Z:\\profile.json'), \
                patch.object(SimulationWorker, 'create', side_effect=create):
            results = await asyncio.gather(
                profile.create_profiled_worker(b'test', profile_path=helper.directory/'hybrid.json',
                    backend=backend, working_directory=helper.directory),
                SimulationWorker.create(b'test', backend=backend),
                profile.create_profiled_worker(b'test', profile_path=helper.directory/'direct.json'))
        self.assertEqual(results, [profile.GUARDIAN_PROFILE_BOOTSTRAP, wine_worker.GUARDIAN_BOOTSTRAP, profile.PROFILE_BOOTSTRAP])
        self.assertEqual(len(calls), 3)

    async def test_hybrid_prelaunch_failure_restores_both_modules(self):
        from server import wine_worker
        backend = object.__new__(wine_worker.WineWorkerBackend)
        original, direct = wine_worker.subprocess, worker_client.subprocess
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(profile, '_wine_output', return_value='Z:\\profile.json'), \
                patch.object(SimulationWorker, 'create', side_effect=ValueError('authored validation failure')):
            with self.assertRaisesRegex(ValueError, 'authored validation'):
                await profile.create_profiled_worker(b'test', profile_path=Path(temporary)/'profile.json',
                    backend=backend, working_directory=temporary)
        self.assertIs(wine_worker.subprocess, original)
        self.assertIs(worker_client.subprocess, direct)


if __name__ == '__main__':
    unittest.main()
