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
        with self.assertRaisesRegex(ValueError, 'direct worker backend'):
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


if __name__ == '__main__':
    unittest.main()
