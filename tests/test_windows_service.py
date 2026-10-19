"""SCM lifecycle and real child-process containment without installing a service."""
import asyncio
from contextlib import redirect_stderr
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from server import host
from server import windows_service as s
from tests.test_credentials import private_test_folder, remove_test_folder

ROOT = Path(__file__).resolve().parents[1]


class ControllerTests(unittest.TestCase):
    def test_stop_and_shutdown_from_control_thread_wait_for_cleanup_once(self):
        for control in (s.STOP, s.SHUTDOWN):
            reports, sequence = [], []
            ready_event = threading.Event()
            controller = s.ServiceController(lambda status: (reports.append(status), sequence.append(status.state)))
            async def run(ready, progress):
                progress('package_checked'); progress('configuration_loaded')
                ready(('127.0.0.1', 12345)); ready_event.set()
                try: await asyncio.Event().wait()
                finally:
                    # A second STOP arriving during cleanup must not cancel it.
                    await asyncio.sleep(.04)
                    sequence.append('cleaned')
            def stop():
                if ready_event.wait(2):
                    controller.control(control)
                    time.sleep(.01)
                    controller.control(control)
                    controller.control(s.INTERROGATE)
            thread = threading.Thread(target=stop, daemon=True); thread.start()
            with self.subTest(control=control):
                self.assertEqual(controller.execute(run), 0)
                thread.join(2); self.assertFalse(thread.is_alive())
                self.assertEqual(sequence[-3:], [s.STOP_PENDING, 'cleaned', s.STOPPED])
                self.assertEqual(sum(row.state == s.STOP_PENDING for row in reports), 1)
                self.assertEqual(sum(row.state == s.STOPPED for row in reports), 1)
                self.assertTrue(all(row.controls == (s.ACCEPT_STOP_SHUTDOWN if row.state == s.RUNNING else 0) for row in reports))
                self.assertEqual(reports[-1].win32_exit, 0)
                count = len(reports)
                controller.control(s.STOP); controller.control(s.INTERROGATE)
                self.assertEqual(len(reports), count)
                self.assertEqual(controller.control(123), s.ERROR_CALL_NOT_IMPLEMENTED)
                with self.assertRaises(s.ServiceError): controller.execute(run)

    def test_early_stop_cannot_be_undone_by_late_readiness(self):
        reports = []
        controller = s.ServiceController(reports.append)
        async def run(ready, progress):
            controller.control(s.STOP)
            ready(('127.0.0.1', 12345))
            progress('native_checked')
            await asyncio.Event().wait()
        self.assertEqual(controller.execute(run), 0)
        self.assertEqual([row.state for row in reports], [s.START_PENDING, s.STOP_PENDING, s.STOPPED])
        self.assertIsNone(controller.loop)
        self.assertIsNone(controller.task)

    def test_failure_and_unrequested_exit_report_failure_without_private_text(self):
        for mode in ('startup', 'runtime', 'returned', 'cancelled'):
            reports = []
            controller = s.ServiceController(reports.append)
            async def run(ready, progress):
                if mode == 'startup': raise OSError('private test value')
                ready(('127.0.0.1', 12345))
                if mode == 'runtime': raise RuntimeError('private test value')
                if mode == 'cancelled': raise asyncio.CancelledError()
            with self.subTest(mode=mode):
                self.assertEqual(controller.execute(run), 1)
                self.assertEqual(reports[-1], s.Status(s.STOPPED, win32_exit=1066, specific_exit=1))
                if mode == 'startup': self.assertNotIn(s.RUNNING, [row.state for row in reports])
                self.assertNotIn('private test value', repr(reports))

    def test_progress_cannot_extend_deadline_or_report_repeated_milestones(self):
        reports = []
        controller = s.ServiceController(reports.append)
        async def run(ready, progress):
            deadline, timer = controller.deadline, controller.timer
            progress('package_checked'); progress('package_checked')
            progress('configuration_loaded'); progress('package_checked')
            self.assertEqual(controller.deadline, deadline)
            self.assertIs(controller.timer, timer)
            controller.control(s.STOP)
            await asyncio.Event().wait()
        self.assertEqual(controller.execute(run), 0)
        self.assertEqual([row.checkpoint for row in reports if row.state == s.START_PENDING], [1, 2, 3])
        self.assertIsNone(controller.timer)

    def test_runtime_failure_starts_deadline_and_late_stop_does_not_cancel_cleanup(self):
        reports, sequence = [], []
        controller = s.ServiceController(reports.append)
        async def run(ready, progress):
            ready(('127.0.0.1', 12345))
            try: raise RuntimeError('authored runtime failure')
            finally:
                progress('stopping')
                deadline, timer = controller.deadline, controller.timer
                controller.control(s.STOP)
                progress('stopping')
                self.assertEqual(controller.deadline, deadline)
                self.assertIs(controller.timer, timer)
                await asyncio.sleep(.01)
                sequence.append('cleaned')
        self.assertEqual(controller.execute(run), 1)
        self.assertEqual(sequence, ['cleaned'])
        self.assertEqual([row.state for row in reports], [s.START_PENDING, s.RUNNING, s.STOP_PENDING, s.STOPPED])
        self.assertEqual(reports[-1].specific_exit, 1)


class HostReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_readiness_requires_native_health_and_listener_and_cleanup_closes_audit(self):
        native_entered, native_release, ready_event = asyncio.Event(), asyncio.Event(), asyncio.Event()
        listener_wait = asyncio.Event()
        server = mock.Mock()
        server.start = mock.AsyncMock(return_value=('127.0.0.1', 12345))
        server.close = mock.AsyncMock()
        server.listener.serve_forever = listener_wait.wait
        audit = mock.Mock()
        config = mock.Mock(data_directory=Path('data'), assets_directory=Path('assets'))
        template = mock.Mock()
        async def check(*args):
            native_entered.set(); await native_release.wait(); return {'reaped': True}
        def ready(address):
            server.start.assert_awaited_once()
            self.assertTrue(native_release.is_set())
            ready_event.set()
        with (mock.patch.object(host, 'prepare', return_value=(template, None, None, {'game_build':37822, 'asset_format':1, 'files':{}})),
              mock.patch.object(host, 'check_native', side_effect=check),
              mock.patch.object(host, 'HostAudit', return_value=audit),
              mock.patch.object(host, 'DedicatedServer', return_value=server),
              mock.patch.object(host, 'ProfileStore'), mock.patch('builtins.print')):
            stages = []
            task = asyncio.create_task(host._run_owned(config, on_ready=ready, on_progress=stages.append))
            try:
                await asyncio.wait_for(native_entered.wait(), 2)
                self.assertFalse(ready_event.is_set()); server.start.assert_not_called()
                native_release.set()
                await asyncio.wait_for(ready_event.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                server.close.assert_awaited_once(); audit.close.assert_called_once()
                self.assertEqual(stages, ['assets_and_storage_checked', 'native_checked', 'stopping'])
            finally:
                if not task.done(): task.cancel(); await asyncio.gather(task, return_exceptions=True)

    async def test_startup_error_never_claims_readiness(self):
        ready = mock.Mock()
        config = mock.Mock()
        with mock.patch.object(host, 'prepare', side_effect=ValueError('invalid assets')):
            with self.assertRaises(ValueError): await host._run_owned(config, on_ready=ready)
        ready.assert_not_called()


class ServicePackagingTests(unittest.TestCase):
    def test_registration_quotes_paths_and_uses_only_bundled_runtime(self):
        folder = private_test_folder('service paths-')
        try:
            runtime = folder/'program/runtime/python.exe'
            runtime.parent.mkdir(parents=True); runtime.write_bytes(b'authored non-executable placeholder')
            with mock.patch('server.configuration.load_config'):
                plan = s.registration(folder, folder/'config/host & friends.json', 'AuthoredTest')
            self.assertEqual(plan['argv'][0], str(runtime))
            self.assertEqual(plan['argv'][1:6], ['-I', '-B', '-m', 'server.windows_service', '--name'])
            self.assertEqual(plan['binary_path'], subprocess.list2cmdline(plan['argv']))
            self.assertEqual(plan['startup'], 'Manual')
            self.assertNotIn('cmd.exe', plan['binary_path'])
            for name in ('', 'bad/name', 'two names', 'x'*65, 'a\nprivate', '1bad'):
                with self.subTest(name=name), self.assertRaises(s.ServiceError): s.registration(folder, folder/'host.json', name)
        finally: remove_test_folder(folder)

    @unittest.skipUnless(os.name == 'nt', 'Windows SCM API')
    def test_actual_dispatcher_rejects_console_without_running_factory(self):
        factory = mock.Mock()
        with self.assertRaisesRegex(s.ServiceError, 'Windows Services'):
            s.WindowsSCM().dispatch('BattleAcesAuthoredConsoleProbe', factory)
        factory.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows native callback types')
    def test_native_callbacks_marshal_status_and_keep_handler_alive_through_stop(self):
        scm = s.WindowsSCM()
        records, threads = [], []
        class AuthoredSCM:
            def RegisterServiceCtrlHandlerExW(self, name, handler, context):
                self.handler = handler
                return 0x123456789  # Exercise a pointer-sized status handle.
            def SetServiceStatus(self, handle, pointer):
                row = ctypes.cast(pointer, ctypes.POINTER(scm.NativeStatus)).contents
                records.append((handle, row.type, row.state, row.controls, row.exit, row.specific))
                if row.state == s.RUNNING:
                    worker = threading.Thread(target=lambda: (self.handler(s.SHUTDOWN, 0, None, None),
                                                             self.handler(s.STOP, 0, None, None)))
                    threads.append(worker); worker.start()
                return 1
            def StartServiceCtrlDispatcherW(self, table):
                self.null_terminated = table[1].name is None and not table[1].main
                table[0].main(0, None)  # Actual WINFUNCTYPE callback invocation.
                return 1
        scm.api = AuthoredSCM()
        async def run(ready, progress):
            ready(('127.0.0.1', 12345))
            await asyncio.Event().wait()
        with mock.patch.object(s.os, '_exit', side_effect=AssertionError('unexpected fatal callback')) as fatal:
            result = scm.dispatch('AuthoredCallbackProbe', run)
        for thread in threads: thread.join(2)
        fatal.assert_not_called()
        self.assertEqual(result, 0)
        self.assertTrue(scm.api.null_terminated)
        self.assertEqual(ctypes.sizeof(scm.NativeStatus), 28)
        self.assertEqual([row[2] for row in records], [s.START_PENDING, s.RUNNING, s.STOP_PENDING, s.STOPPED])
        self.assertTrue(all(row[0:2] == (0x123456789, 0x10) for row in records))
        self.assertEqual(records[-1][3:], (0, 0, 0))

    def test_cli_rejects_relative_config_without_connecting_to_scm(self):
        with mock.patch.object(s, 'WindowsSCM') as scm, redirect_stderr(io.StringIO()):
            self.assertEqual(s.main(['--config', 'relative.json']), 1)
        scm.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'Windows process and job containment')
class DeadlineProcessTests(unittest.TestCase):
    def test_absolute_startup_deadline_ends_a_blocked_process(self):
        code = ('import sys,time;sys.path.insert(0,sys.argv[1]);from server.windows_service import ServiceController\n'
                'async def host(ready,progress): time.sleep(30)\n'
                'ServiceController(lambda status:None,start_timeout=.2).execute(host)\n')
        started = time.monotonic()
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(ROOT)], capture_output=True,
                                timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 1)
        self.assertLess(time.monotonic()-started, 5)

    def test_runtime_failure_cleanup_has_a_deadline_without_external_stop(self):
        code = ('import sys,time;sys.path.insert(0,sys.argv[1]);from server.windows_service import ServiceController\n'
                'async def host(ready,progress):\n'
                ' ready(("127.0.0.1",12345))\n'
                ' try: raise RuntimeError("authored failure")\n'
                ' finally: progress("stopping");time.sleep(30)\n'
                'ServiceController(lambda status:print(status.state,flush=True),stop_timeout=.2).execute(host)\n')
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(ROOT)], capture_output=True,
                                timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.split(), [b'2', b'4', b'3'])

    def test_stop_deadline_kills_stuck_host_and_its_owned_worker(self):
        folder = private_test_folder('service-deadline-')
        process = handle = None
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        code = r'''
import asyncio,json,sys,threading,time
sys.path.insert(0,sys.argv[1])
from server.windows_service import ServiceController, STOP
from server.worker_client import SimulationWorker
async def host(ready,progress):
    worker=await SimulationWorker.create(b'authored synthetic match', working_directory=sys.argv[2], _test_backend=True)
    print(json.dumps({'worker':worker.pid}),flush=True)
    ready(('127.0.0.1',12345))
    timer=threading.Timer(.1,lambda:controller.control(STOP)); timer.daemon=True; timer.start()
    try: await asyncio.Event().wait()
    finally: time.sleep(30)
controller=ServiceController(lambda status:print(json.dumps({'state':status.state}),flush=True),start_timeout=5,stop_timeout=1)
controller.execute(host)
'''
        try:
            process = subprocess.Popen([sys.executable, '-I', '-B', '-c', code, str(ROOT), str(folder)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            rows = []
            while not handle:
                raw = process.stdout.readline()
                self.assertTrue(raw, 'Service probe ended before creating its test worker')
                row = json.loads(raw); rows.append(row)
                if 'worker' in row:
                    handle = kernel.OpenProcess(0x100000, False, row['worker'])
                    self.assertTrue(handle, 'Cannot observe owned worker')
            output, errors = process.communicate(timeout=5)
            rows.extend(json.loads(row) for row in output.splitlines())
            self.assertEqual(process.returncode, 1, errors.decode(errors='replace'))
            self.assertIn({'state':s.STOP_PENDING}, rows)
            self.assertNotIn({'state':s.STOPPED}, rows)
            self.assertEqual(kernel.WaitForSingleObject(handle, 3000), 0, 'Worker survived host deadline')
        finally:
            if process:
                if process.poll() is None: process.kill(); process.wait(timeout=5)
                for stream in (process.stdout, process.stderr): stream.close()
            if handle: kernel.CloseHandle(handle)
            remove_test_folder(folder)


if __name__ == '__main__': unittest.main()
