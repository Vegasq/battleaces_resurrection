"""Authored ctypes/worker boundary controls; no original assets or Cargo required."""
import asyncio
import copy
import ctypes as C
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from server import rust_snapshot_decoder as rust
from server import simulation_worker as ipc
from server import worker_client as client
from server.native_simulation import decode_snapshot
from server.wine_worker import WineWorkerBackend
from server.protobuf_wire import field_uint
from tests.snapshot_decoder_fixtures import make_snapshot


class Export:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class AuthoredLibrary:
    def __init__(self):
        self.version = 1
        self.status = 0
        self.free_status = 0
        self.output = None
        self.exception = None
        self.length = None
        self.allocations = []
        self.freed = []
        self.calls = 0
        self.ba_snapshot_decoder_abi_version = Export(lambda: self.version)
        self.ba_decode_snapshot = Export(self.decode)
        self.ba_free_buffer = Export(self.free)

    def decode(self, data, size, viewer, include_entities, result):
        self.calls += 1
        raw = C.string_at(data, size)
        encoded = self.output
        if encoded is None:
            encoded = json.dumps(decode_snapshot(raw, viewer, include_entities=bool(include_entities))).encode()
        if encoded:
            allocation = C.create_string_buffer(encoded)
            self.allocations.append(allocation)
            output = C.cast(result, C.POINTER(rust._Buffer)).contents
            output.data = C.cast(allocation, C.POINTER(C.c_uint8))
            output.len = len(encoded) if self.length is None else self.length
        if self.exception:
            raise self.exception
        return self.status

    def free(self, data, size):
        self.freed.append((C.cast(data, C.c_void_p).value, size))
        return self.free_status


class AdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name).resolve() / 'authored-decoder.dll'
        self.path.write_bytes(b'authored nonexecutable fixture')
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.library = AuthoredLibrary()
        self.loader = patch.object(rust.C, 'CDLL', return_value=self.library).start()
        self.addCleanup(patch.stopall)
        self.raw = make_snapshot(3)

    def make(self):
        return rust.RustSnapshotDecoder(self.path, self.sha)

    def test_hash_missing_library_and_relative_path_refuse_before_load(self):
        cases = [(self.path, None), (self.path, '0'*64), (None, self.sha),
                 ('relative.dll', self.sha), (self.path.parent, self.sha),
                 (self.path.with_name('missing.dll'), self.sha)]
        for path, sha in cases:
            with self.subTest(path=path, sha=sha), self.assertRaises((ValueError, OSError)):
                rust.RustSnapshotDecoder(path, sha)
        self.loader.assert_not_called()

    def test_version_and_missing_exports_have_no_fallback(self):
        self.library.version = 2
        with self.assertRaisesRegex(rust.RustDecoderError, 'ABI version'):
            self.make()
        del self.library.ba_free_buffer
        with self.assertRaisesRegex(rust.RustDecoderError, 'exports'):
            self.make()

    def test_typed_state_parity_and_output_released_once(self):
        decoder = self.make()
        for viewer in (0, 31, 32, 0xffffffff):
            for full in (False, True):
                self.assertEqual(decoder.decode(self.raw, viewer, include_entities=full),
                                 decode_snapshot(self.raw, viewer, include_entities=full))
        self.assertEqual(len(self.library.freed), 8)
        self.assertEqual(decoder.info, {'implementation': 'rust', 'abi_version': 1,
                         'library_path': str(self.path), 'library_sha256': self.sha})

    def test_arguments_refused_before_ffi(self):
        decoder = self.make()
        for raw, viewer, full in [(bytearray(self.raw), 31, False), (self.raw, True, False),
                                  (self.raw, -1, False), (self.raw, 1 << 32, False),
                                  (self.raw, 31, 1), (b'x'*(rust.MAX_INPUT+1), 31, False)]:
            with self.subTest(viewer=viewer, full=full), self.assertRaises(rust.RustDecoderError):
                decoder.decode(raw, viewer, include_entities=full)
        self.assertEqual(self.library.calls, 0)

    def test_bad_json_schema_and_duplicate_fields_release_exact_buffer(self):
        state = json.loads(json.dumps(decode_snapshot(self.raw, include_entities=True)))
        invalid = [b'{', b'\xff', b'[]', b'{"x":NaN}', b'{"x":1,"x":2}']
        for key, value in [('viewer', 0), ('raw_sha256', '0'*64), ('byte_count', True),
                           ('frame', True), ('counts', {}), ('resources', {'00': {}}),
                           ('entities', [{'id': 1, 'army': True}]), ('game_state', {})]:
            changed = copy.deepcopy(state); changed[key] = value
            invalid.append(json.dumps(changed).encode())
        decoder = self.make()
        for encoded in invalid:
            self.library.output = encoded
            previous = len(self.library.freed)
            with self.subTest(encoded=encoded[:60]), self.assertRaises(rust.RustDecoderError):
                decoder.decode(self.raw, include_entities=True)
            self.assertEqual(len(self.library.freed), previous+1)
            self.assertEqual(self.library.freed[-1][1], len(encoded))

    def test_ffi_failures_release_any_returned_allocation_without_fallback(self):
        decoder = self.make()
        self.library.status = 2
        with self.assertRaisesRegex(rust.RustDecoderError, 'status2'):
            decoder.decode(self.raw)
        self.assertEqual(len(self.library.freed), 1)
        self.library.status = 0
        self.library.exception = OSError('authored FFI fault')
        with self.assertRaisesRegex(OSError, 'FFI fault'):
            decoder.decode(self.raw)
        self.assertEqual(len(self.library.freed), 2)
        self.library.exception = None
        self.library.free_status = 1
        with self.assertRaisesRegex(rust.RustDecoderError, 'free failed'):
            decoder.decode(self.raw)
        self.assertEqual(len(self.library.freed), 3)

    def test_invalid_output_bounds_rejected_before_read_and_still_freed(self):
        decoder = self.make()
        for length in (0, rust.MAX_OUTPUT+1):
            self.library.length = length
            with patch.object(rust.C, 'string_at', wraps=C.string_at) as read:
                with self.assertRaisesRegex(rust.RustDecoderError, 'pointer/length'):
                    decoder.decode(self.raw)
                # Only the authored DLL's input read happened; no output read.
                self.assertEqual(read.call_count, 1)
            self.assertEqual(self.library.freed[-1][1], length)
        self.library.output = b''
        with self.assertRaisesRegex(rust.RustDecoderError, 'pointer/length'):
            decoder.decode(self.raw)
        self.assertEqual(len(self.library.freed), 2)


class WorkerDecoderTests(unittest.TestCase):
    def run_worker(self, *, decoder=None, synthetic=False, decoder_kwargs=None):
        raw = make_snapshot(3)
        expected = decode_snapshot(raw, 31, include_entities=True)
        completed = expected['frame']
        native = Mock()
        native.frame = completed-1
        native.game_data_sha256 = hashlib.sha256(b'authored').hexdigest()
        native.dll_sha256 = 'authored-native'
        native.snapshot_bytes.return_value = raw
        native.state.return_value = expected
        native.snapshot.return_value = raw
        def step(*args, **kwargs):
            native.frame = completed
            return 3
        native.process_frame.side_effect = step
        wire = ipc.encode_message(ipc.CREATE, 1, -1, payload=b'authored')
        wire += ipc.encode_message(ipc.STEP, 2, completed, {'dt_ms': 50},
                                   field_uint(1, completed)+field_uint(2, 20)+field_uint(3, 50))
        wire += ipc.encode_message(ipc.STATE, 3, completed, {'viewer': 31, 'include_entities': True})
        wire += ipc.encode_message(ipc.SNAPSHOT, 4, completed, {'viewer': 31})
        wire += ipc.encode_message(ipc.CLOSE, 5, completed)
        sink = io.BytesIO()
        with patch('server.native_simulation.NativeSimulation', return_value=native) as create, \
             patch.object(rust, 'RustSnapshotDecoder', return_value=decoder) as load, \
             patch.object(ipc, 'os', SimpleNamespace(name='nt', getpid=os.getpid)):
            result = ipc.serve(io.BytesIO(wire), sink, test_backend=synthetic, **(decoder_kwargs or {}))
        sink.seek(0)
        responses = []
        while response := ipc.read_message(sink):
            responses.append(response)
        return result, responses, native, create, load

    def test_default_keeps_python_and_opt_in_matches_step_state_and_snapshot(self):
        result, baseline, native, _, load = self.run_worker()
        self.assertEqual(result, 0); load.assert_not_called()
        self.assertEqual(baseline[0][4]['snapshot_decoder'], {'implementation': 'python'})
        decoder = Mock(info={'implementation': 'rust'})
        decoder.decode.side_effect = lambda raw, viewer, include_entities: decode_snapshot(raw, viewer, include_entities=include_entities)
        result, actual, native, _, load = self.run_worker(decoder=decoder,
            decoder_kwargs={'snapshot_decoder_library': 'explicit', 'snapshot_decoder_sha256': 'sha'})
        self.assertEqual(result, 0)
        self.assertEqual(actual[1:], baseline[1:])
        self.assertEqual(decoder.decode.call_count, 2)
        native.state.assert_not_called()
        native.snapshot.assert_called_once_with(31)
        native.close.assert_called_once()

    def test_decoder_failure_is_terminal_no_python_fallback_and_world_is_closed(self):
        decoder = Mock(info={'implementation': 'rust'})
        decoder.decode.side_effect = rust.RustDecoderError('authored refusal')
        result, responses, native, _, _ = self.run_worker(decoder=decoder,
            decoder_kwargs={'snapshot_decoder_library': 'explicit', 'snapshot_decoder_sha256': 'sha'})
        self.assertEqual(result, 2)
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[1][1], ipc.ERROR)
        native.state.assert_not_called(); native.close.assert_called_once()

    def test_synthetic_opt_in_is_refused_before_library_or_world_load(self):
        result, responses, _, create, load = self.run_worker(synthetic=True,
            decoder_kwargs={'snapshot_decoder_library': 'explicit', 'snapshot_decoder_sha256': 'sha'})
        self.assertEqual(result, 2)
        self.assertIn('native Windows', responses[0][4]['message'])
        create.assert_not_called(); load.assert_not_called()


class ClientDecoderTests(unittest.IsolatedAsyncioTestCase):
    async def test_forbidden_backends_fail_before_spawn(self):
        with patch.object(client.subprocess, 'Popen') as spawn:
            for kwargs in ({'_test_backend': True}, {'backend': object()}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    await client.SimulationWorker.create(b'authored', snapshot_decoder_library='explicit',
                                                        snapshot_decoder_sha256='a'*64, **kwargs)
            spawn.assert_not_called()
            with patch.object(client, 'os', SimpleNamespace(name='posix')):
                with self.assertRaisesRegex(ValueError, 'native Windows'):
                    await client.SimulationWorker.create(b'authored', snapshot_decoder_library='explicit',
                                                        snapshot_decoder_sha256='a'*64)
            spawn.assert_not_called()

    async def test_explicit_options_forward_and_response_identity_is_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()/'authored.dll'; path.write_bytes(b'authored')
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            identity = {'implementation': 'rust', 'abi_version': 1, 'library_path': str(path), 'library_sha256': sha}
            response = {'pid': 123, 'game_data_sha256': sha, 'synthetic_test_backend': False,
                        'dll_sha256': 'native', 'snapshot_decoder': identity}
            class Client(client.SimulationWorker):
                def __init__(self, process, **kwargs):
                    self._lock = asyncio.Lock()
                    self._exchange = AsyncMock(return_value=(response, b''))
                    self._abort = AsyncMock()
            with patch.object(client, 'os', SimpleNamespace(name='nt', environ={})), \
                 patch.object(client.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                 patch.object(client.subprocess, 'Popen', return_value=SimpleNamespace(pid=123)) as spawn, \
                 patch.object(client, '_WindowsJob'):
                worker = await Client.create(b'authored', snapshot_decoder_library=path, snapshot_decoder_sha256=sha)
                self.assertEqual(worker.decoder_info, identity)
                self.assertEqual(spawn.call_args.args[0][-4:], ['--snapshot-decoder-library', str(path),
                                                              '--snapshot-decoder-sha256', sha])
                for wrong in ({'implementation': 'python'}, {**identity, 'library_sha256': '0'*64},
                              {**identity, 'abi_version': 2}, {**identity, 'abi_version': True}):
                    response['snapshot_decoder'] = wrong
                    with self.assertRaisesRegex(client.WorkerError, 'decoder identity'):
                        await Client.create(b'authored', snapshot_decoder_library=path, snapshot_decoder_sha256=sha)

    async def test_wine_forwards_host_options_but_checks_translated_worker_identity(self):
        from server.native_simulation import SUPPORTED_DLL_SHA256
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            path = directory/'authored.dll'; path.write_bytes(b'authored')
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            windows_path = r'Z:\authored directory\decoder.dll'
            identity = {'implementation': 'rust', 'abi_version': 1,
                        'library_path': windows_path, 'library_sha256': sha}
            response = {'pid': 77, 'game_data_sha256': sha, 'synthetic_test_backend': False,
                        'dll_sha256': SUPPORTED_DLL_SHA256, 'snapshot_decoder': identity,
                        'runtime': {'python_version': 'test', 'implementation': 'cpython', 'executable': 'test',
                                    'platform': 'win32', 'os_name': 'nt', 'pointer_bits': 64}}
            instances = []
            class Client(client.SimulationWorker):
                def __init__(self, process, **kwargs):
                    self._lock = asyncio.Lock()
                    self._abort = AsyncMock()
                    instances.append(self)
                async def _exchange(self, op, frame, metadata, data, **kwargs):
                    return {**response, 'worker_nonce': metadata['worker_nonce']}, b''
            backend = object.__new__(WineWorkerBackend)  # Authored process stub; no Wine, prefix or cgroup.
            owner = Mock()
            with patch.object(client, 'os', SimpleNamespace(name='posix', environ={})), \
                 patch.object(client.subprocess, 'Popen') as native_spawn, \
                 patch.object(WineWorkerBackend, 'translate_path', return_value=windows_path), \
                 patch.object(WineWorkerBackend, 'launch', return_value=(SimpleNamespace(pid=123), owner)) as launch:
                worker = await Client.create(b'authored', path, backend=backend, working_directory=directory,
                                            snapshot_decoder_library=path, snapshot_decoder_sha256=sha)
                self.assertEqual(worker.decoder_info, identity)
                self.assertIs(worker._backend_owner, owner)
                launch.assert_called_once_with(source_root=client.ROOT, working_directory=directory,
                                               snapshot_decoder_library=path, snapshot_decoder_sha256=sha)
                owner.on_exit.assert_called_once()
                for wrong in (None, {'implementation': 'python'}, {**identity, 'library_path': str(path)},
                              {**identity, 'library_sha256': '0'*64}, {**identity, 'abi_version': 2},
                              {**identity, 'abi_version': True}):
                    if wrong is None:
                        response.pop('snapshot_decoder', None)
                    else:
                        response['snapshot_decoder'] = wrong
                    with self.subTest(wrong=wrong), self.assertRaisesRegex(client.WorkerError, 'decoder identity'):
                        await Client.create(b'authored', path, backend=backend, working_directory=directory,
                                            snapshot_decoder_library=path, snapshot_decoder_sha256=sha)
                    instances[-1]._abort.assert_awaited_once()
                native_spawn.assert_not_called()

    async def test_wine_malformed_decoder_options_never_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            path = directory/'authored.dll'; path.write_bytes(b'authored')
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            backend = object.__new__(WineWorkerBackend)
            with patch.object(client, 'os', SimpleNamespace(name='posix', environ={})), \
                 patch.object(WineWorkerBackend, 'launch') as launch:
                for library, expected in ((path, None), (None, sha), (path, '0'*64), ('relative.dll', sha)):
                    with self.subTest(library=library, expected=expected), self.assertRaises(ValueError):
                        await client.SimulationWorker.create(b'authored', path, backend=backend,
                            working_directory=directory, snapshot_decoder_library=library, snapshot_decoder_sha256=expected)
                launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
