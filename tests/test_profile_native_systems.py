"""Authored gate/ownership controls; no native DLL, process or instrumentation."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest import mock

from tools import profile_native_systems as n


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.config = dict(schema=1, nonce='a'*64, parent_pid=os.getppid(),
                           image=str(Path(sys.executable).resolve()), output=str(self.directory),
                           dll=str(self.directory/'Simulation.dll'), dll_sha256='b'*64,
                           library=str(self.directory/'decoder.dll'), library_sha256='c'*64,
                           source_sha256={'test': 'd'*64}, gate_seconds=1, drain_seconds=0)
        self.simulation = NS(dll_sha256='b'*64, _runtime=NS(path=Path(self.config['dll'])),
                             _world=NS(value=12345), frame=-1)
        self.verify = mock.patch.object(n, 'verify_config')
        self.verify.start()
        self.addCleanup(self.verify.stop)

    def publish(self, action='release', mutate=None):
        ready = n.read_json(self.directory/'ready.json')
        identity = dict(nonce=self.config['nonce'], pid=ready['pid'], ready_sha256=n.sha(self.directory/'ready.json'),
                        job_member=True, retained_handle=True, actual_image=self.config['image'],
                        source_sha256=self.config['source_sha256'])
        n.write_new(self.directory/'identity.json', identity)
        release = dict(schema=1, action=action, nonce=self.config['nonce'], pid=ready['pid'],
                       parent_pid=ready['parent_pid'])
        if action == 'release':
            release.update(ready_sha256=n.sha(self.directory/'ready.json'),
                           identity_sha256=n.sha(self.directory/'identity.json'),
                           source_sha256=self.config['source_sha256'], attached=True)
        if mutate:
            mutate(release)
        n.write_new(self.directory/'release.json', release)

    def test_full_identity_release(self):
        n.await_release(self.config, self.directory, self.simulation, sleep=lambda _: self.publish())
        self.assertEqual(n.read_json(self.directory/'released.json'), n.read_json(self.directory/'release.json'))
        self.assertEqual(n.read_json(self.directory/'ready.json')['world_hex'], '0x3039')

    def test_timeout_and_no_accepted_release(self):
        ticks = iter([0, 0.1, 2])
        with self.assertRaisesRegex(ValueError, 'deadline'):
            n.await_release(self.config, self.directory, self.simulation,
                            monotonic=lambda: next(ticks), sleep=lambda _: None)
        self.assertFalse((self.directory/'released.json').exists())

    def test_wrong_nonce_cannot_release(self):
        with self.assertRaisesRegex(ValueError, 'release differs'):
            n.await_release(self.config, self.directory, self.simulation,
                            sleep=lambda _: self.publish(mutate=lambda r: r.update(nonce='e'*64)))

    def test_explicit_failed_attach_abort(self):
        with self.assertRaisesRegex(ValueError, 'explicitly aborted'):
            n.await_release(self.config, self.directory, self.simulation, sleep=lambda _: self.publish('abort'))
        self.assertFalse((self.directory/'released.json').exists())

    def test_old_release_refused_before_ready(self):
        n.write_new(self.directory/'release.json', {'nonce': 'e'*64})
        with self.assertRaisesRegex(ValueError, 'reused gate'):
            n.await_release(self.config, self.directory, self.simulation)
        self.assertFalse((self.directory/'ready.json').exists())

    def test_gate_failure_closes_initialized_world_and_restores_constructor(self):
        for error in (TimeoutError('no release'), ValueError('failed attach'), ValueError('bad nonce')):
            with self.subTest(error=error):
                closed = []
                class Native:
                    def __init__(self):
                        self.initialized = True
                    def close(self):
                        closed.append(self.initialized)
                original = Native.__init__
                with mock.patch.object(n, 'await_release', side_effect=error):
                    with self.assertRaises(type(error)):
                        with n.gate_constructor(Native, self.config, self.directory):
                            Native()
                self.assertEqual(closed, [True])
                self.assertIs(Native.__init__, original)

    def test_exact_image_parent_and_initial_frame(self):
        self.simulation.frame = 0
        with self.assertRaisesRegex(ValueError, 'first native STEP'):
            n.await_release(self.config, self.directory, self.simulation)

    def test_receipts_never_overwrite(self):
        path = self.directory/'receipt.json'
        n.write_new(path, {'first': True})
        with self.assertRaises(FileExistsError):
            n.write_new(path, {'second': True})
        self.assertEqual(n.read_json(path), {'first': True})
        self.assertEqual(list(self.directory.glob('*.tmp')), [])


class LaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=n.ROOT/'local')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        (self.directory/'decoder.dll').write_bytes(b'authored nonexecutable library bytes')
        self.decoder = ['--snapshot-decoder-library', str(self.directory/'decoder.dll'),
                        '--snapshot-decoder-sha256', n.sha(self.directory/'decoder.dll')]
        self.original = NS(PIPE=-1, Popen=mock.Mock(return_value=NS(pid=123)))
        class Job:
            def __init__(self, pid):
                self.pid = pid
        self.module = NS(subprocess=self.original, _WindowsJob=Job)
        self.original_job = Job
        self.command = [sys.executable, '-I', '-S', '-B', '-u', '-c', n.p.WORKER_BOOTSTRAP,
                        str(n.ROOT), '--stdio']+self.decoder
        self.kwargs = dict(stdin=-1, stdout=-1, stderr=-1, close_fds=True,
                           cwd=self.directory/'arm'/'worker')

    def test_one_launch_then_exact_job_and_restore(self):
        with n.owned_launch(self.module, self.directory, self.decoder) as (launch, captured):
            self.module.subprocess.Popen(self.command, **self.kwargs)
            self.assertIs(self.module.subprocess, self.original)
            job = self.module._WindowsJob(123)
            self.assertIs(captured['job'], job)
            self.assertIs(self.module._WindowsJob, self.original_job)
            actual = self.original.Popen.call_args.args[0]
            self.assertEqual(actual[6], n.BOOTSTRAP)
            self.assertEqual(actual[-2:], ['--native-gate', str(self.directory)])
        with self.assertRaises(RuntimeError):
            launch.Popen(self.command, **self.kwargs)

    def test_wrong_argv_pipe_or_directory_never_launches_and_restores(self):
        cases = [(self.command+['--test-backend'], self.kwargs),
                 (self.command, {**self.kwargs, 'stdin': None}),
                 (self.command, {**self.kwargs, 'cwd': n.ROOT}),
                 (self.command, {**self.kwargs, 'shell': True})]
        for command, kwargs in cases:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    with n.owned_launch(self.module, self.directory, self.decoder):
                        self.module.subprocess.Popen(command, **kwargs)
                self.assertIs(self.module.subprocess, self.original)
                self.assertIs(self.module._WindowsJob, self.original_job)
        self.original.Popen.assert_not_called()

    def test_unused_and_failed_launch_leave_no_global_proxy(self):
        with self.assertRaisesRegex(RuntimeError, 'cancel'):
            with n.owned_launch(self.module, self.directory, self.decoder):
                raise RuntimeError('cancel')
        self.assertIs(self.module.subprocess, self.original)
        self.assertIs(self.module._WindowsJob, self.original_job)
        self.original.Popen.side_effect = OSError('launch refused')
        with self.assertRaises(OSError):
            with n.owned_launch(self.module, self.directory, self.decoder):
                self.module.subprocess.Popen(self.command, **self.kwargs)
        self.assertIs(self.module.subprocess, self.original)
        self.assertIs(self.module._WindowsJob, self.original_job)

    def test_wrong_job_pid_refused(self):
        with self.assertRaisesRegex(ValueError, 'Job assignment'):
            with n.owned_launch(self.module, self.directory, self.decoder):
                self.module.subprocess.Popen(self.command, **self.kwargs)
                self.module._WindowsJob(124)
        self.assertIs(self.module._WindowsJob, self.original_job)

    def test_output_fresh_local_and_nonce(self):
        with tempfile.TemporaryDirectory(dir=n.ROOT/'local') as temporary:
            path = Path(temporary).resolve()
            self.assertEqual(n.fresh_output(path/'new'), path/'new')
            for invalid in (path, n.ROOT/'local', n.ROOT/'elsewhere', Path('relative')):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    n.fresh_output(invalid)
        self.assertTrue(n.nonce_ok('a'*64))
        for invalid in ('a'*63, 'A'*64, 'x'*64, None):
            self.assertFalse(n.nonce_ok(invalid))


if __name__ == '__main__':
    unittest.main()
