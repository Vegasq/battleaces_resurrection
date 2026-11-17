"""Wine boundary tests use an explicitly authored executable, never game DLLs.

Linux lifecycle cases exercise real fork/session/subreaper/pidfd cleanup with a
fake protocol peer. Actual Wine/native equivalence is a separate owned gate.
"""
import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import Mock, patch

from server import simulation_worker as ipc
from server.native_simulation import SUPPORTED_DLL_SHA256
from server.protobuf_wire import field_uint
from server.wine_worker import ROOT, TEMPLATE_MARKER, TEMPLATE_PURPOSE, WineWorkerBackend
from server.worker_client import SimulationWorker, WorkerError, WorkerTimeout


def authored_decoder_pe(*, machine=0x8664, dll=True):
    binary = bytearray(88); binary[:2] = b'MZ'; struct.pack_into('<I', binary, 60, 64)
    binary[64:68] = b'PE\0\0'; struct.pack_into('<H', binary, 68, machine)
    struct.pack_into('<H', binary, 86, 0x2000 if dll else 0)
    return bytes(binary)


def frame(number):
    return field_uint(1, number) + field_uint(2, 20) + field_uint(3, 50)


class NonceProtocolTests(unittest.TestCase):
    def test_valid_native_nonce_echoes_without_changing_default_protocol(self):
        class FakeNative:
            def __init__(self, data, path):
                self.frame = -1
                self.game_data_sha256 = hashlib.sha256(data).hexdigest()
                self.dll_sha256 = SUPPORTED_DLL_SHA256
            def close(self): pass
        for nonce in (None, 'a'*64):
            metadata = {} if nonce is None else {'worker_nonce': nonce}
            wire = ipc.encode_message(ipc.CREATE, 1, -1, metadata, b'authored fixture')
            wire += ipc.encode_message(ipc.CLOSE, 2, -1)
            output = io.BytesIO()
            with patch('server.native_simulation.NativeSimulation', FakeNative):
                self.assertEqual(ipc.serve(io.BytesIO(wire), output), 0)
            output.seek(0); response = ipc.read_message(output)[4]
            if nonce is None: self.assertNotIn('worker_nonce', response)
            else: self.assertEqual(response['worker_nonce'], nonce)

    def test_bad_nonce_or_synthetic_nonce_refused_before_native_creation(self):
        for nonce, synthetic in (('short', False), ('A'*64, False), (True, False), ('a'*64, True)):
            with self.subTest(nonce=nonce, synthetic=synthetic):
                wire = ipc.encode_message(ipc.CREATE, 1, -1, {'worker_nonce': nonce}, b'fixture')
                output = io.BytesIO()
                with patch('server.native_simulation.NativeSimulation') as native:
                    self.assertEqual(ipc.serve(io.BytesIO(wire), output, test_backend=synthetic), 2)
                    native.assert_not_called()
                output.seek(0)
                self.assertIn('nonce', ipc.read_message(output)[4]['message'])


class WineDecoderOptionTests(unittest.TestCase):
    """Portable argument/identity controls without launching Wine or a guardian."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.decoder = self.directory/'authored decoder.dll'
        self.decoder.write_bytes(authored_decoder_pe())
        self.sha = hashlib.sha256(self.decoder.read_bytes()).hexdigest()
        self.backend = object.__new__(WineWorkerBackend)
        for name, value in (('wine_executable', self.directory/'wine'),
                            ('windows_python', self.directory/'python.exe'),
                            ('prefix_template', self.directory/'template'),
                            ('cgroup_parent', self.directory/'groups')):
            object.__setattr__(self.backend, name, value)

    def test_guardian_command_defaults_and_explicit_translated_decoder(self):
        from server.wine_worker_guardian import worker_command, WORKER_BOOTSTRAP
        def translate(value): return 'Z:\\authored\\'+Path(value).name
        with patch.object(WineWorkerBackend, 'translate_path', side_effect=translate):
            baseline = worker_command(self.backend)
            self.assertEqual(baseline, [str(self.backend.wine_executable), translate(self.backend.windows_python),
                             '-I', '-S', '-B', '-u', '-c', WORKER_BOOTSTRAP, translate(ROOT), '--stdio'])
            command = worker_command(self.backend, snapshot_decoder_library=self.decoder,
                                     snapshot_decoder_sha256=self.sha)
            self.assertEqual(command, baseline+['--snapshot-decoder-library', translate(self.decoder),
                                               '--snapshot-decoder-sha256', self.sha])
            self.decoder.write_bytes(b'changed after coordinator validation')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                worker_command(self.backend, snapshot_decoder_library=self.decoder, snapshot_decoder_sha256=self.sha)

    def test_wrong_native_format_or_malformed_options_refused_before_owned_resources(self):
        from server.wine_worker_guardian import worker_command
        invalid = [(self.decoder, None), (None, self.sha), (self.decoder, '0'*64), ('relative.dll', self.sha)]
        for data in (b'\x7fELF'+bytes(100), authored_decoder_pe(machine=0x14c), authored_decoder_pe(dll=False)):
            path = self.directory/('bad-'+hashlib.sha256(data).hexdigest()+'.dll'); path.write_bytes(data)
            invalid.append((path, hashlib.sha256(data).hexdigest()))
        with patch('server.wine_worker_cgroup.OwnedCgroup') as group, \
             patch('server.wine_worker.subprocess.Popen') as spawn, \
             patch.object(WineWorkerBackend, 'translate_path', return_value=r'Z:\fixture'):
            for library, sha in invalid:
                with self.subTest(library=library, sha=sha):
                    with self.assertRaises(ValueError):
                        self.backend.launch(source_root=ROOT, working_directory=self.directory,
                                            snapshot_decoder_library=library, snapshot_decoder_sha256=sha)
                    with self.assertRaises(ValueError):
                        worker_command(self.backend, snapshot_decoder_library=library, snapshot_decoder_sha256=sha)
            group.assert_not_called(); spawn.assert_not_called()
            self.assertEqual(list(self.directory.glob('ba-wine-worker-*')), [])

    def test_backend_argv_carries_host_path_to_guardian_without_environment_override(self):
        def owner(process, watch, status, *args):
            os.close(watch); os.close(status)
            return Mock()
        with patch('server.wine_worker.validate_template'), \
             patch.object(WineWorkerBackend, 'translate_path', return_value=r'Z:\translated\decoder.dll'), \
             patch('server.wine_worker_cgroup.OwnedCgroup') as group, \
             patch('server.wine_worker.WineWorkerOwner', side_effect=owner), \
             patch('server.wine_worker.subprocess.Popen', return_value=Mock()) as spawn:
            group.return_value.path = self.directory/'authored-group'
            self.backend.launch(source_root=ROOT, working_directory=self.directory,
                                snapshot_decoder_library=self.decoder, snapshot_decoder_sha256=self.sha)
            command = spawn.call_args.args[0]
            self.assertEqual(command[-4:], ['--snapshot-decoder-library', str(self.decoder),
                                           '--snapshot-decoder-sha256', self.sha])
            self.assertFalse(spawn.call_args.kwargs.get('shell', False))
            self.assertNotIn('BA_ENABLE_SYNTHETIC_WORKER_TESTS', spawn.call_args.kwargs['env'])


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux private Wine guardian tests')
class WineWorkerLinuxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from server.wine_worker_cgroup import current_cgroup
        group = current_cgroup()
        if not os.access(group, os.W_OK):
            self.skipTest('a writable delegated cgroup-v2 parent is required for ownership tests')
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.cgroup_parent = group/('ba-wine-worker-test-'+self.directory.name)
        self.cgroup_parent.mkdir(mode=0o700)
        self.template = self.directory/'template'; self.template.mkdir(mode=0o700)
        (self.template/'drive_c').mkdir()
        (self.template/'dosdevices').mkdir()
        (self.template/'dosdevices/z:').symlink_to('/')
        (self.template/'dosdevices/c:').symlink_to('../drive_c')
        for name in ('system.reg', 'user.reg'):
            (self.template/name).write_text('WINE REGISTRY Version 2\n')
        marker = self.template/TEMPLATE_MARKER
        marker.write_text(json.dumps({'format': 1, 'purpose': TEMPLATE_PURPOSE, 'uid': os.getuid()}))
        marker.chmod(0o600)
        self.python = self.directory/'windows-python.exe'
        binary = bytearray(88); binary[:2] = b'MZ'; struct.pack_into('<I', binary, 60, 64)
        binary[64:68] = b'PE\0\0'; struct.pack_into('<H', binary, 68, 0x8664)
        self.python.write_bytes(binary)
        self.work = self.directory/'workers'; self.work.mkdir()
        self.dll = self.directory/'Simulation.dll'; self.dll.write_bytes(b'authored fake asset')
        self.decoder = self.directory/'authored decoder.dll'; self.decoder.write_bytes(authored_decoder_pe())
        self.decoder_sha = hashlib.sha256(self.decoder.read_bytes()).hexdigest()
        self.wine = self.directory/'authored-wine'
        self.pid_files = self.directory/'pids'; self.pid_files.mkdir()
        body = '''
import hashlib,json,os,pathlib,signal,sys,time
sys.path.insert(0, ROOT)
from server import simulation_worker as p
from server.native_simulation import _protobuf_header,SUPPORTED_DLL_SHA256
prefix=pathlib.Path(os.environ['WINEPREFIX'])
decoder={'implementation':'python'}
if '--snapshot-decoder-library' in sys.argv:
    decoder_path=sys.argv[sys.argv.index('--snapshot-decoder-library')+1]
    decoder_sha=sys.argv[sys.argv.index('--snapshot-decoder-sha256')+1]
    assert decoder_path.startswith('Z:')
    actual=pathlib.Path(decoder_path[2:].replace(chr(92),'/'))
    assert hashlib.sha256(actual.read_bytes()).hexdigest()==decoder_sha
    decoder={'implementation':'rust','abi_version':1,'library_path':decoder_path,'library_sha256':decoder_sha}
receipt=pathlib.Path(PID_DIRECTORY)/str(os.getpid())
child=os.fork()
if child==0:
    os.setsid()
    grandchild=os.fork()
    if grandchild: os._exit(0)
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    birth=int(pathlib.Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19])
    receipt.write_text(json.dumps({'service':os.getpid(),'creation':birth,'launcher':os.getppid(),'prefix':str(prefix)}))
    for fd in (0,1,2):
        try: os.close(fd)
        except OSError: pass
    while True: time.sleep(1)
os.waitpid(child,0)
while not receipt.exists(): time.sleep(.005)
number=-1; mode=None
while True:
    item=p.read_message(sys.stdin.buffer)
    if item is None: break
    op,flags,rid,f,metadata,payload=item
    if op==p.CREATE:
        mode=payload.decode()
        if mode=='hang_create':
            signal.signal(signal.SIGTERM,signal.SIG_IGN)
            while True: time.sleep(1)
        result={'pid':77,'worker_nonce':metadata['worker_nonce'],'game_data_sha256':hashlib.sha256(payload).hexdigest(),
                'dll_sha256':SUPPORTED_DLL_SHA256,'synthetic_test_backend':False,'ai':None,
                'snapshot_decoder':dict(decoder),
                'runtime':{'python_version':sys.version,'implementation':'cpython','executable':'authored-peer',
                           'platform':'win32','os_name':'nt','pointer_bits':64}}
        if mode=='wrong_nonce': result['worker_nonce']='0'*64
        if mode=='wrong_pid': result['pid']=True
        if mode=='wrong_dll': result['dll_sha256']='0'*64
        if mode=='wrong_digest': result['game_data_sha256']='0'*64
        if mode=='synthetic': result['synthetic_test_backend']=True
        if mode=='wrong_decoder_path': result['snapshot_decoder']['library_path']='Z:'+chr(92)+'wrong.dll'
        if mode=='wrong_decoder_sha': result['snapshot_decoder']['library_sha256']='0'*64
        if mode=='wrong_decoder_abi': result['snapshot_decoder']['abi_version']=2
    elif op==p.STEP:
        if mode=='hang':
            signal.signal(signal.SIGTERM,signal.SIG_IGN)
            while True: time.sleep(1)
        number,dt=_protobuf_header(payload)
        result={'input_sha256':hashlib.sha256(payload).hexdigest(),'game_time_seconds':0,
                'state':{'frame':number,'resources':{'0':{'primary':number+1}}}}
    elif op==p.CLOSE:
        if mode=='late_ack_stalled_guardian':
            time.sleep(1.8)
            data=json.loads(receipt.read_text());data['late_close_ack']=True;receipt.write_text(json.dumps(data))
            p.write_packet(sys.stdout.buffer,p.encode_message(op|p.RESPONSE,rid,f,{'closed':True}))
            os.kill(os.getppid(),signal.SIGSTOP)
            signal.signal(signal.SIGTERM,signal.SIG_IGN)
            while True: time.sleep(1)
        if mode=='hang_close':
            signal.signal(signal.SIGTERM,signal.SIG_IGN)
            while True: time.sleep(1)
        p.write_packet(sys.stdout.buffer,p.encode_message(op|p.RESPONSE,rid,f,{'closed':True}))
        if mode=='exit_19': os._exit(19)
        break
    else: raise RuntimeError('unexpected authored-peer operation')
    p.write_packet(sys.stdout.buffer,p.encode_message(op|p.RESPONSE,rid,f,result))
'''
        self.wine.write_text(f'#!{sys.executable}\nROOT={str(ROOT)!r}\nPID_DIRECTORY={str(self.pid_files)!r}\n'+textwrap.dedent(body))
        self.wine.chmod(0o700)
        self.backend = WineWorkerBackend(self.wine, self.python, self.template, self.cgroup_parent)
        self.workers = []

    async def asyncTearDown(self):
        results = await asyncio.gather(*(worker.close() for worker in self.workers), return_exceptions=True)
        for worker, result in zip(self.workers, results):
            if isinstance(result, Exception): self.assertIsNotNone(worker.failure)
            self.assertIsNotNone(worker.process.poll())
            self.assertTrue(worker.backend_statistics['cleanup_complete'])
        # Only identities emitted by our authored fake executable are eligible.
        # This is fallback fixture cleanup, never a user/global wineserver kill.
        from server.wine_worker_guardian import process_identity
        for receipt in self.pid_files.iterdir():
            record = json.loads(receipt.read_text()); pid = record['service']
            identity = process_identity(pid)
            if identity is not None and identity[1] == record['creation'] and identity[2] != 'Z':
                descriptor = os.pidfd_open(pid)
                try:
                    current = process_identity(pid)
                    if current is not None and current[1] == record['creation']:
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                finally: os.close(descriptor)
        self.temp.cleanup()
        self.cgroup_parent.rmdir()

    async def make(self, mode='ordinary', **kwargs):
        worker = await SimulationWorker.create(mode.encode(), self.dll, backend=self.backend,
            working_directory=self.work, **kwargs)
        self.workers.append(worker)
        return worker

    def no_scratch(self):
        self.assertEqual(list(self.work.glob('ba-wine-worker-*')), [])

    async def test_two_workers_have_private_prefixes_exact_nonce_and_independent_cleanup(self):
        first, second = await asyncio.gather(self.make(), self.make())
        self.assertNotEqual(first.pid, second.pid)
        self.assertEqual(first.native_pid, 77)
        self.assertEqual(second.native_pid, 77)  # Windows PIDs need not be globally unique across prefixes.
        receipts = [json.loads(path.read_text()) for path in self.pid_files.iterdir()]
        self.assertEqual(len({row['prefix'] for row in receipts}), 2)
        self.assertEqual((await first.process_frame(frame(0))).frame, 0)
        await first.close()
        self.assertEqual((await second.process_frame(frame(0))).frame, 0)
        await second.close()
        for worker in (first, second):
            self.assertEqual(worker.process.poll(), 0)
            self.assertTrue(worker.backend_statistics['cleanup_complete'])
            self.assertTrue(worker.backend_statistics['prefix_removed'])
            self.assertGreaterEqual(worker.backend_statistics['prefix_clone_ms'], 0)
            self.assertGreaterEqual(worker.backend_statistics['process_cleanup']['descendants_seen'], 1)
        self.no_scratch()

    async def test_timeout_and_cancel_reap_owned_daemon_children_but_leave_other_worker(self):
        first, second = await asyncio.gather(self.make('hang', request_timeout=.15), self.make())
        with self.assertRaises(WorkerTimeout): await first.process_frame(frame(0))
        self.assertTrue(first.backend_statistics['cleanup_complete'])
        third = await self.make('hang', request_timeout=30)
        pending = asyncio.create_task(third.process_frame(frame(0)))
        await asyncio.sleep(.05); pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        self.assertTrue(third.backend_statistics['cleanup_complete'])
        self.assertEqual((await second.process_frame(frame(0))).frame, 0)
        await second.close(); self.no_scratch()

    async def test_corrupt_identity_digest_and_synthetic_reply_are_terminal_and_clean(self):
        for mode in ('wrong_nonce', 'wrong_pid', 'wrong_dll', 'wrong_digest', 'synthetic'):
            with self.subTest(mode=mode):
                with self.assertRaises(WorkerError): await self.make(mode)
                self.no_scratch()

    async def test_decoder_options_cross_guardian_and_bad_identity_cleans_owned_worker(self):
        options = {'snapshot_decoder_library': self.decoder, 'snapshot_decoder_sha256': self.decoder_sha}
        worker = await self.make(**options)
        self.assertEqual(worker.decoder_info, {'implementation': 'rust', 'abi_version': 1,
                         'library_path': self.backend.translate_path(self.decoder), 'library_sha256': self.decoder_sha})
        self.assertEqual((await worker.process_frame(frame(0))).frame, 0)
        await worker.close(); self.no_scratch()
        for mode in ('wrong_decoder_path', 'wrong_decoder_sha', 'wrong_decoder_abi'):
            with self.subTest(mode=mode), self.assertRaisesRegex(WorkerError, 'decoder identity'):
                await self.make(mode, **options)
            self.no_scratch()

    async def test_backend_refuses_synthetic_gate_and_unprepared_or_public_template(self):
        with self.assertRaisesRegex(ValueError, 'synthetic'):
            await SimulationWorker.create(b'test', self.dll, backend=self.backend, _test_backend=True, working_directory=self.work)
        self.template.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'private'):
            WineWorkerBackend(self.wine, self.python, self.template, self.cgroup_parent)
        self.template.chmod(0o700)
        (self.template/TEMPLATE_MARKER).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'marker'):
            WineWorkerBackend(self.wine, self.python, self.template, self.cgroup_parent)
        self.no_scratch()

    async def test_source_root_paths_and_clone_never_follow_host_root_symlink(self):
        from server.wine_worker_guardian import clone_template
        target = self.directory/'clone'
        clone_template(self.template, target, lambda: None)
        self.assertTrue((target/'dosdevices/z:').is_symlink())
        self.assertEqual(os.readlink(target/'dosdevices/z:'), '/')
        self.assertEqual(self.backend.translate_path(self.dll), 'Z:'+str(self.dll).replace('/', '\\'))
        with self.assertRaisesRegex(ValueError, 'coordinator checkout'):
            self.backend.launch(source_root=self.directory, working_directory=self.work)
        bad = self.directory/'bad:name'; bad.write_bytes(b'test')
        with self.assertRaisesRegex(ValueError, 'represented'):
            self.backend.translate_path(bad)

    async def test_external_c_drive_and_fifo_template_are_refused_without_blocking(self):
        drive = self.template/'dosdevices/c:'; drive.unlink()
        drive.symlink_to(self.template/'drive_c')
        with self.assertRaisesRegex(ValueError, 'clone-relative'):
            WineWorkerBackend(self.wine, self.python, self.template, self.cgroup_parent)
        drive.unlink(); drive.symlink_to('../drive_c')
        os.mkfifo(self.template/'unsafe-fifo')
        started = time.monotonic()
        with self.assertRaises(WorkerError): await self.make(startup_timeout=2)
        self.assertLess(time.monotonic()-started, 10)
        self.no_scratch()

    async def test_cgroup_parent_cannot_escape_coordinator_supervisor(self):
        from server.wine_worker_cgroup import current_cgroup
        group = current_cgroup()
        if group.parent == group or not (group.parent/'cgroup.controllers').is_file():
            self.skipTest('coordinator already occupies the cgroup mount root')
        with self.assertRaisesRegex(ValueError, 'supervisor hierarchy'):
            WineWorkerBackend(self.wine, self.python, self.template, group.parent)

    async def test_create_and_destructor_hangs_are_owned_and_native_exit_is_not_lost(self):
        started = time.monotonic()
        with self.assertRaises(WorkerTimeout): await self.make('hang_create', startup_timeout=1)
        self.assertLess(time.monotonic()-started, 10)
        self.no_scratch()
        worker = await self.make('hang_close', close_timeout=.15)
        started = time.monotonic(); await worker.close()
        self.assertLess(time.monotonic()-started, 10)
        self.assertTrue(worker.backend_statistics['cleanup_complete'])
        self.assertNotEqual(worker.backend_statistics['native_exit_code'], 0)
        ordinary_error = await self.make('exit_19')
        await ordinary_error.close()
        self.assertEqual(ordinary_error.process.returncode, 19)
        self.assertEqual(ordinary_error.backend_statistics['native_exit_code'], 19)

    async def test_killed_guardian_is_cleaned_without_another_rpc_or_close(self):
        worker, other = await asyncio.gather(self.make(), self.make())
        started = time.monotonic()
        signal.pidfd_send_signal(worker._backend_owner._pidfd, signal.SIGKILL)
        while time.monotonic()-started < 9:
            if (worker._cleanup_task is not None and worker._cleanup_task.done()
                    and not worker._stderr_thread.is_alive() and all(not t.is_alive() for t in worker._io._threads)):
                break
            await asyncio.sleep(.02)
        else: self.fail('guardian death did not automatically finish worker cleanup')
        self.assertTrue(worker.backend_statistics['parent_recovery'])
        self.assertTrue(worker.backend_statistics['cleanup_complete'])
        self.assertIsNotNone(worker.failure)
        self.assertEqual((await other.process_frame(frame(0))).frame, 0)
        await other.close()
        self.no_scratch()

    async def test_default_close_uses_one_deadline_across_lock_ack_and_guardian_stall(self):
        worker = await self.make('late_ack_stalled_guardian')  # Deliberately use default2s close_timeout.
        await worker._lock.acquire()
        started = time.monotonic()
        closing = asyncio.create_task(worker.close())
        await asyncio.sleep(1.8)
        worker._lock.release()
        with self.assertRaisesRegex(RuntimeError, 'guardian exited'):
            await asyncio.wait_for(closing, 10)
        self.assertLess(time.monotonic()-started, 10)
        self.assertTrue(any(json.loads(path.read_text()).get('late_close_ack') for path in self.pid_files.iterdir()),
                        'the late ACK path was not exercised')
        self.assertTrue(worker.backend_statistics['cleanup_complete'])
        self.assertFalse(worker._stderr_thread.is_alive())
        self.no_scratch()

    async def test_worker_constructor_failure_after_backend_launch_releases_ownership(self):
        original = threading.Thread.start
        def start(thread):
            if thread.name.startswith('ba-stderr-'):
                raise RuntimeError('injected stderr thread allocation failure')
            return original(thread)
        started = time.monotonic()
        with patch.object(threading.Thread, 'start', start):
            with self.assertRaisesRegex(RuntimeError, 'injected stderr'):
                await self.make()
        self.assertLess(time.monotonic()-started, 10)
        self.no_scratch()
        self.assertEqual([path for path in self.cgroup_parent.iterdir() if path.is_dir()], [])

    async def test_guardian_owner_close_before_spawn_cleans_partial_prefix(self):
        process, owner = self.backend.launch(source_root=ROOT, working_directory=self.work)
        await asyncio.to_thread(owner.close)
        self.assertTrue(owner.statistics['cleanup_complete'])
        self.assertEqual(process.returncode, 125)
        for stream in (process.stdin, process.stdout, process.stderr): stream.close()
        self.no_scratch()

    async def test_abrupt_coordinator_death_reaps_daemon_descendants_and_prefix(self):
        code = '''
import asyncio,json,sys
sys.path.insert(0,sys.argv.pop(1))
from server.wine_worker import WineWorkerBackend
from server.worker_client import SimulationWorker
async def main():
    backend=WineWorkerBackend(*sys.argv[1:4],cgroup_parent=sys.argv[6])
    worker=await SimulationWorker.create(b'hang',sys.argv[4],working_directory=sys.argv[5],backend=backend)
    print(json.dumps({'guardian':worker.pid}),flush=True)
    await asyncio.sleep(120)
asyncio.run(main())
'''
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', textwrap.dedent(code), str(ROOT),
            str(self.wine), str(self.python), str(self.template), str(self.dll), str(self.work), str(self.cgroup_parent)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, close_fds=True)
        try:
            line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 10)
            self.assertTrue(line, 'authored coordinator did not start')
            guardian = json.loads(line)['guardian']
            process.kill(); await asyncio.to_thread(process.wait, timeout=3)
            from server.wine_worker_guardian import process_identity
            deadline = time.monotonic()+10
            while time.monotonic() < deadline:
                identity = process_identity(guardian)
                if (identity is None or identity[2] == 'Z') and not list(self.work.glob('ba-wine-worker-*')):
                    break
                await asyncio.sleep(.05)
            else: self.fail('guardian/prefix survived coordinator death')
            for receipt in self.pid_files.iterdir():
                identity = process_identity(json.loads(receipt.read_text())['service'])
                self.assertIsNone(identity, 'guardian failed to reap adopted service')
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=3)
            process.stdout.close(); process.stderr.close()

    async def test_constructor_recovery_survives_cleanup_executor_refusal(self):
        launched = []
        original_launch = WineWorkerBackend.launch
        original_start = threading.Thread.start
        def launch(backend, **kwargs):
            result = original_launch(backend, **kwargs)
            launched.append(result)
            return result
        def start(thread):
            if thread.name.startswith('ba-stderr-'):
                raise RuntimeError('injected stderr thread allocation failure')
            return original_start(thread)
        async def refused(*args, **kwargs):
            raise RuntimeError('cleanup executor unavailable')
        started = time.monotonic()
        with patch.object(WineWorkerBackend, 'launch', launch), patch.object(threading.Thread, 'start', start):
            with patch.object(asyncio, 'to_thread', refused):
                with self.assertRaisesRegex(RuntimeError, 'cleanup executor unavailable'):
                    await self.make()
        self.assertEqual(len(launched), 1)
        process, owner = launched[0]
        while not owner._done.is_set() and time.monotonic()-started < 9:
            await asyncio.sleep(.01)
        self.assertTrue(owner._done.is_set())
        self.assertTrue(owner.statistics['cleanup_complete'])
        self.assertIsNotNone(process.poll())
        self.assertTrue(all(stream.closed for stream in (process.stdin, process.stdout, process.stderr)))
        self.assertLess(time.monotonic()-started, 10)
        self.no_scratch()
        self.assertEqual([path for path in self.cgroup_parent.iterdir() if path.is_dir()], [])

    async def test_existing_worker_cleanup_survives_executor_refusal(self):
        worker = await self.make('hang', request_timeout=30, close_timeout=.15)
        pending = asyncio.create_task(worker.process_frame(frame(0)))
        await asyncio.sleep(.05)
        async def refused(*args, **kwargs):
            raise RuntimeError('cleanup executor unavailable')
        started = time.monotonic()
        with patch.object(asyncio, 'to_thread', refused):
            with self.assertRaisesRegex(RuntimeError, 'cleanup executor unavailable'):
                await worker.close()
        while time.monotonic()-started < 9:
            if (worker._backend_owner._done.is_set() and not worker._stderr_thread.is_alive()
                    and all(not thread.is_alive() for thread in worker._io._threads)):
                break
            await asyncio.sleep(.01)
        else:
            self.fail('cleanup required a new executor thread to release the owned worker')
        await asyncio.gather(pending, return_exceptions=True)
        self.assertTrue(worker.backend_statistics['cleanup_complete'])
        self.assertTrue(all(stream.closed for stream in (worker.process.stdin, worker.process.stdout, worker.process.stderr)))
        self.assertLess(time.monotonic()-started, 10)
        self.no_scratch()

    async def test_whole_supervisor_kill_contains_children_and_preserves_sibling(self):
        from server.wine_worker_cgroup import OwnedCgroup
        from server.wine_worker_guardian import remove_runtime
        supervisor = OwnedCgroup(self.cgroup_parent/'ba-wine-worker-supervisor', create=True)
        other = await self.make()
        code = '''
import asyncio,json,sys
sys.path.insert(0,sys.argv.pop(1))
from server.wine_worker import WineWorkerBackend
from server.wine_worker_cgroup import OwnedCgroup
from server.worker_client import SimulationWorker
group=OwnedCgroup(sys.argv[6]);group.join_current();group.close()
async def main():
    backend=WineWorkerBackend(*sys.argv[1:4])
    worker=await SimulationWorker.create(b'hang',sys.argv[4],working_directory=sys.argv[5],backend=backend)
    print(json.dumps({'guardian':worker.pid,'scratch':str(worker._backend_owner.runtime),
                      'cgroup':str(worker._backend_owner.cgroup.path)}),flush=True)
    await asyncio.sleep(120)
asyncio.run(main())
'''
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', textwrap.dedent(code), str(ROOT),
            str(self.wine), str(self.python), str(self.template), str(self.dll), str(self.work), str(supervisor.path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, close_fds=True)
        receipt = None
        try:
            line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 10)
            self.assertTrue(line, 'owned nested supervisor failed to start')
            receipt = json.loads(line)
            self.assertTrue(Path(receipt['cgroup']).is_relative_to(supervisor.path))
            started = time.monotonic()
            self.assertTrue(await asyncio.to_thread(supervisor.kill_and_wait, 3))
            await asyncio.to_thread(process.communicate, timeout=3)
            self.assertLess(time.monotonic()-started, 10)
            self.assertFalse(supervisor.populated())
            self.assertEqual((await other.process_frame(frame(0))).frame, 0)
            print('SUPERVISOR_KILL_SCOPE '+json.dumps(dict(zero_live_descendants=True, pipes_closed=True,
                unrelated_sibling_survived=True, graceful_cleanup_receipt='unavailable: both actors SIGKILL',
                scratch_remained=Path(receipt['scratch']).exists())))
        finally:
            empty = await asyncio.to_thread(supervisor.kill_and_wait, 3)
            if process.poll() is None:
                process.wait(timeout=3)
            process.stdout.close(); process.stderr.close()
            # This is external fixture cleanup AFTER kernel containment proof.
            # It is not claimed as graceful worker/supervisor disk cleanup.
            if empty:
                for directory in supervisor.path.iterdir():
                    if directory.is_dir():
                        child = OwnedCgroup(directory)
                        try: self.assertTrue(child.cleanup())
                        finally: child.close()
                self.assertTrue(supervisor.cleanup())
                if receipt is not None: remove_runtime(Path(receipt['scratch']), self.work.resolve())
            supervisor.close()
        await other.close(); self.no_scratch()


if __name__ == '__main__':
    unittest.main()
