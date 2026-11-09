"""Exact-build native API owner. Loading is explicit and only in the worker."""
from __future__ import annotations

import ctypes as C
import _thread
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import time

from . import wire as w


class HostError(RuntimeError):
    pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def helper_receipt(path, *, arena=False):
    """Installed artifacts need their receipt, not the original C++ source tree."""
    path = Path(path).resolve(strict=True)
    receipt_path = path.with_name('build.json')
    if receipt_path.stat().st_size > 64 * 1024 or path.stat().st_size > 64 * 1024 * 1024:
        raise HostError('helper/receipt exceeds bounded size')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
    fields = ('dll_sha256', 'source_sha256', 'page_source_sha256') if arena else ('dll_sha256', 'source_sha256')
    if (type(receipt) is not dict or receipt.get('experimental') is not True or
            any(type(receipt.get(key)) is not str or not re.fullmatch('[0-9a-f]{64}', receipt[key])
                for key in fields) or receipt['dll_sha256'] != digest(path)):
        raise HostError('helper build receipt identity/schema mismatch')
    return path, receipt


class ArenaStats(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in (
        'version', 'error', 'allocations', 'frees', 'reallocations', 'unknown',
        'foreign_threads', 'high', 'live', 'live_bytes', 'captures', 'restores', 'committed',
        'capture_bytes', 'restore_bytes', 'capture_micros', 'restore_micros', 'saved_bytes')]


class ForeignEvent(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in (
        'version', 'operation', 'size', 'pointer', 'thread_id', 'owner_thread_id',
        'native_base', 'heap', 'caller', 'tick', 'frame_count')] + [
        (name, C.c_uint64 * 16) for name in ('addresses', 'module_bases', 'rvas')]


class Arena:
    def __init__(self, path):
        path, self.receipt = helper_receipt(path, arena=True)
        if path.name.lower() != 'baheap.dll':
            raise HostError('early import helper must be named BAHeap.dll')
        self.dll = C.CDLL(str(path))
        self._diagnostic_attempted = False
        self._diagnostic_path = None
        self._bindings_api = None
        self._bindings = None
        self._bindings_revision = 0
        self._bindings_changed = False
        self._unreturned_tokens = set()
        self._forget_api = getattr(self.dll, 'BAForgetCheckpointBaseline', None)
        if self._forget_api is not None:
            self._forget_api.argtypes, self._forget_api.restype = [], C.c_int32
        roots = [getattr(self.dll, name, None) for name in ('BAPrimeRootBindings', 'BAGetRootBindings')]
        if all(roots):
            roots[0].argtypes, roots[0].restype = [], C.c_int32
            roots[1].argtypes, roots[1].restype = [C.POINTER(C.c_uint64), C.c_uint32], C.c_int32
            self._bindings_api = roots
        # Optional diagnostics added in arena08. Older qualified helpers retain
        # the identical mandatory stats ABI and require no new exports.
        self._foreign = None
        names = ('BASizeOfForeignEvent', 'BAGetForeignEventCount', 'BAGetForeignEvents')
        optional = [getattr(self.dll, name, None) for name in names]
        if all(optional):
            for function, arguments, result in zip(optional,
                    ([], [], [C.c_void_p, C.c_uint32, C.c_uint32]),
                    (C.c_uint32, C.c_uint32, C.c_int32)):
                function.argtypes, function.restype = arguments, result
            self._foreign = optional
        for name, arguments in (
            ('BAInitialize', []), ('BAInstall', [C.c_void_p]), ('BASeal', []),
            ('BAGetStats', [C.POINTER(ArenaStats), C.c_uint32]),
            ('BARestore', [C.c_uint64]), ('BADrop', [C.c_uint64]),
        ):
            function = getattr(self.dll, name)
            function.argtypes, function.restype = arguments, C.c_int32
        self.dll.BACapture.argtypes, self.dll.BACapture.restype = [], C.c_uint64
        if self.dll.BAInitialize():
            raise HostError('early heap initialization failed')

    def install(self, native):
        if self.dll.BAInstall(native._handle):
            raise HostError('early heap IAT/layout installation guard failed')
        self.healthy()
        if self.dll.BASeal():
            raise HostError('early heap startup ownership cannot be sealed')

    def prime_bindings(self):
        if self._bindings_api is None:
            return False  # Historical transport-only helpers have no root ABI.
        if self._bindings is not None or self._bindings_api[0]():
            raise HostError('native CRT root priming refused')
        self._bindings = self._read_bindings()
        self.healthy()
        return True

    def _read_bindings(self):
        values = (C.c_uint64 * 7)()
        if self._bindings_api[1](values, len(values)):
            raise HostError('native CRT root binding read failed')
        result = tuple(map(int, values))
        # (owner,tlsIndex,vcrIndex,ucrtIndex,tls,root,root). Indices may be0.
        if not result[0] or not all(result[4:]):
            raise HostError('native CRT roots/TLS are not primed')
        return result

    def root_bindings(self):
        if self._bindings is None:
            raise HostError('checkpoint prediction requires primed native root ABI')
        if self._bindings_changed:
            raise HostError('native CRT root bindings changed; checkpoints invalid')
        try:
            current = self._read_bindings()
        except BaseException:
            self._bindings_revision += 1
            self._bindings_changed = True
            raise
        if current != self._bindings:
            self._bindings_revision += 1
            self._bindings = current
            self._bindings_changed = True
        if self._bindings_changed:
            raise HostError('native CRT root bindings changed; checkpoints invalid')
        return current + (self._bindings_revision,)

    def capture(self):
        if self._forget_api is None:
            raise HostError('prediction requires checkpoint baseline retirement ABI')
        self.healthy()
        token = int(self.dll.BACapture())
        if not token:
            raise HostError('native checkpoint capture failed')
        self._unreturned_tokens.add(token)
        try:
            self.healthy()
        except BaseException as error:
            try:self.drop(token)
            except Exception as cleanup:
                raise HostError(str(error) + '; unreturned checkpoint cleanup: ' + str(cleanup)) from error
            raise
        self._unreturned_tokens.discard(token)
        return token

    def restore(self, token):
        self.healthy()
        if self.dll.BARestore(token):
            raise HostError('native checkpoint restore failed')
        self.healthy()

    def drop(self, token):
        # Cleanup remains possible after a sticky guard failure. BADrop mutates
        # only helper-owned snapshots, on the established native owner.
        if self.dll.BADrop(token):
            raise HostError('native checkpoint release failed')
        self._unreturned_tokens.discard(token)

    def release_unreturned(self):
        errors = []
        for token in tuple(self._unreturned_tokens):
            try:self.drop(token)
            except Exception as error:errors.append(str(error))
        if errors:raise HostError('unreturned snapshot cleanup: ' + '; '.join(errors))

    def forget_baseline(self):
        if self._forget_api is None or self._forget_api():
            raise HostError('native checkpoint baseline retirement failed')

    def _save_foreign_events(self, stats):
        if self._diagnostic_attempted or self._foreign is None:
            return self._diagnostic_path
        self._diagnostic_attempted = True
        report = dict(stats=stats, events=[])
        try:
            size, count, read = self._foreign
            total = count()
            if size() != C.sizeof(ForeignEvent) or not 0 <= total <= 8:
                raise HostError('foreign diagnostic ABI/count mismatch')
            values = (ForeignEvent * total)()
            code = 0
            if total:
                # A failing thread claims its slot before publishing the fixed
                # record. Wait at most50ms, never spin or weaken the guard.
                for attempt in range(11):
                    code = read(values, total, C.sizeof(ForeignEvent))
                    if code != -2 or attempt == 10:
                        break
                    time.sleep(.005)
                if code != total:
                    raise HostError('foreign diagnostic records unavailable: ' + str(code))
            kernel = C.WinDLL('kernel32', use_last_error=True)
            module_name = kernel.GetModuleFileNameW
            module_name.argtypes, module_name.restype = [C.c_void_p, C.c_wchar_p, C.c_uint32], C.c_uint32
            for value in values:
                if value.version != 1 or value.frame_count > 16:
                    raise HostError('foreign diagnostic event layout mismatch')
                event = {name: int(getattr(value, name)) for name, _ in ForeignEvent._fields_[:11]}
                event['frames'] = []
                for index in range(value.frame_count):
                    base = value.module_bases[index]
                    name = C.create_unicode_buffer(32768)
                    length = module_name(base, name, len(name)) if base else 0
                    event['frames'].append(dict(address=int(value.addresses[index]),
                        module_base=int(base), rva=int(value.rvas[index]),
                        module=name.value if 0 < length < len(name) else None))
                report['events'].append(event)
        except Exception as exc:
            report['diagnostic_error'] = str(exc)
        try:
            # NativeSession.open chdirs to a newly created private worker run.
            # Exclusive creation preserves the first failure through cleanup.
            path = Path.cwd() / 'native-foreign-events.json'
            with path.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2)
                stream.write('\n')
            self._diagnostic_path = str(path)
        except Exception:
            pass  # Diagnostic failure must never replace the ownership error.
        return self._diagnostic_path

    def healthy(self):
        value = ArenaStats()
        if self.dll.BAGetStats(C.byref(value), C.sizeof(value)):
            raise HostError('heap stats ABI failed')
        result = {name: int(getattr(value, name)) for name, _ in value._fields_}
        if result['version'] != 2 or any(result[key] for key in ('error', 'unknown', 'foreign_threads')):
            path = self._save_foreign_events(result) if result['foreign_threads'] else None
            raise HostError('unsafe heap ownership: ' + repr(result) +
                            ('; diagnostic=' + path if path else ''))
        if self._bindings is not None:
            self.root_bindings()
        return result


# Raw C ABI, after IL2CPP marshalling. Arrays are pointers to elements; system
# identification is count*128 inline bytes, not a pointer-bearing string array.
SIGNATURES = {
    'SimInit': [C.c_bool], 'SimDestroy': [], 'SimSetLogCallBack': [C.c_void_p],
    'SimSetLogFlags': [C.c_uint32],
    'SimCreateWorld': [C.c_void_p, C.c_uint32, C.POINTER(C.c_uint64)],
    'SimDestroyWorld': [C.c_uint64], 'SimProcessMsg': [C.c_uint64, C.c_void_p, C.c_uint32],
    'SimStep': [C.c_uint64, C.c_uint32, C.POINTER(C.c_int32)],
    'SimMakeSimFrame': [C.c_uint64, C.c_uint32, C.POINTER(C.c_uint32)],
    'SimGetSimFrameBuffer': [C.c_uint64, C.c_void_p],
    'SimGetLabelsFrameBufferSize': [C.c_uint64, C.c_uint32, C.POINTER(C.c_uint32)],
    'SimGetLabelsFrameBuffer': [C.c_uint64, C.c_uint32, C.c_void_p],
    'SimGetConnectedPlayersSizeAndVersion': [C.c_uint64, C.POINTER(C.c_int32), C.POINTER(C.c_int32)],
    'SimGetConnectedPlayers': [C.c_uint64, C.c_void_p],
    'SimGetMapFrameSize': [C.c_uint64, C.POINTER(C.c_int32)],
    'SimGetMapFrame': [C.c_uint64, C.c_void_p], 'SimCrashOnCommand': [],
    'SimGetDebugDrawCommandBufferCount': [C.c_uint64, C.POINTER(C.c_uint32)],
    'SimGetDebugDrawCommandBufferSize': [C.c_uint64, C.POINTER(C.c_uint32), C.c_uint32],
    'SimGetDebugDrawCommandBuffer': [C.c_uint64, C.c_void_p, C.c_uint32],
    'SimClearAllDebugDrawCommandBuffers': [C.c_uint64],
    'SimSetDebugDrawCommandListsActive': [C.c_uint64, C.c_uint32, C.c_void_p],
    'SimGetSystemCount': [C.c_uint64, C.POINTER(C.c_uint32)],
    'SimGetSystemIDAttributes': [C.c_uint64, C.c_void_p, C.c_uint32],
}

DEBUG_STUB_RVA = 0x136f0
DEBUG_STUB_BYTES = bytes.fromhex('b808000000c3')  # MOV EAX,8; RET, no writes.
DEBUG_STUB_NAMES = ('SimGetDebugDrawCommandBufferCount', 'SimGetDebugDrawCommandBufferSize',
                    'SimGetDebugDrawCommandBuffer', 'SimClearAllDebugDrawCommandBuffers',
                    'SimSetDebugDrawCommandListsActive')


def validate_debug_stubs(base, pointers, reader=C.string_at):
    stub = base + DEBUG_STUB_RVA
    if (reader(stub, len(DEBUG_STUB_BYTES)) != DEBUG_STUB_BYTES or
            any(pointers.get(name) != stub for name in DEBUG_STUB_NAMES)):
        raise HostError('exact-build debug no-write stub guard failed')


class NativeRawAPI:
    def __init__(self, dll):
        self.dll = dll
        for name, arguments in SIGNATURES.items():
            function = getattr(dll, name)
            function.argtypes, function.restype = arguments, C.c_int32
        # Exact original aliases return8 and never touch pointers.
        # This guard permits DEBUG_SIZE's special no-write response, even when
        # its unchanged caller seed exceeds the ordinary buffer allocation cap.
        validate_debug_stubs(dll._handle, {name:C.cast(getattr(dll, name), C.c_void_p).value
                                         for name in DEBUG_STUB_NAMES})

    def call(self, name, *args):
        return int(getattr(self.dll, name)(*args))


class NativeSession:
    """One active world, sequential rematches; no implicit SimInit or Step.

    Tests inject a fake raw ABI. Product open() binds exact native files and
    enters the same dispatcher. Every method runs on the sole owner thread.
    """
    def __init__(self, api, *, arena=None, cooperative=None, cooperative_factory=None):
        self.api, self.arena, self.cooperative = api, arena, cooperative
        self.cooperative_factory = cooperative_factory
        self.worlds, self.next_world = {}, 1
        self.predictions, self.prediction_adapters, self.prepared_prediction = {}, {}, {}
        self.dirty_worlds = set()
        self.terminal_admitted, self.terminal_masked = {}, {}
        self.initialized = self.closed = False
        self.logs, self.log_overflow = [], False
        self.log_enabled = False
        self.retired_cooperative = None  # Keep the last helper retained without an unbounded history.
        self.owner_thread = _thread.get_ident()
        self.callback = C.CFUNCTYPE(None, C.c_int32, C.c_char_p)(self._log)
        self.provenance = {}

    @classmethod
    def open(cls, *, original_dll, heap_helper, cooperative, data_dir):
        if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
            raise HostError('prediction worker requires Windows x64')
        # Imports are function utilities, never verifier modules. The exact-base
        # derive function has an independent SHA constant unaffected by override.
        from tools.prepare_prediction_native import derive_native
        from tools.prediction_crt_attach import defer_crt_thread_attach
        from tools.prediction_native import prepare_serial, Cooperative
        from server import native_simulation
        original = Path(original_dll).resolve(strict=True)
        if original.stat().st_size > 16 * 1024 * 1024:
            raise HostError('original DLL exceeds bounded size')
        original_bytes = original.read_bytes()
        derived_bytes, manifest = derive_native(original_bytes)
        derived_bytes, manifest = defer_crt_thread_attach(derived_bytes, manifest)
        heap_path, _ = helper_receipt(heap_helper, arena=True)
        coop_path, _ = helper_receipt(cooperative)
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.GetModuleHandleW.argtypes, kernel.GetModuleHandleW.restype = [C.c_wchar_p], C.c_void_p
        if kernel.GetModuleHandleW('Simulation.dll') or kernel.GetModuleHandleW('BAHeap.dll'):
            raise HostError('native setup must precede any simulation/heap helper load')
        folder = Path(data_dir).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        run = Path(tempfile.mkdtemp(prefix='native-worker-', dir=folder))
        derived = run / 'Simulation.dll'
        with derived.open('xb') as stream:
            stream.write(derived_bytes)
        manifest.update(original=str(original), output=str(derived))
        (run / 'Simulation.derivation.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        # DLL CRT/log sinks use relative paths. This is the private worker
        # process, so keep those files in its fresh data directory as well.
        os.chdir(run)
        search = os.add_dll_directory(str(heap_path.parent))
        # REQUIRED ORDER: BAInitialize -> derived DLL CRT initializers -> serial
        # patch -> cooperative hooks -> BAInstall/Seal -> client-requested Init.
        arena = Arena(heap_path)
        native_simulation.SUPPORTED_DLL_SHA256 = manifest['derived_sha256']
        native = prepare_serial(derived)
        coop = None
        try:
            coop = Cooperative(coop_path, native)
            arena.install(native)
            arena.prime_bindings()
            session = cls(NativeRawAPI(native), arena=arena, cooperative=coop,
                          cooperative_factory=lambda: Cooperative(coop_path, native))
            session.search, session.native = search, native  # Retain through DLL CRT detach/process exit.
            session.provenance = dict(original_sha256=manifest['original_sha256'],
                derived_sha256=manifest['derived_sha256'], heap_sha256=digest(heap_path),
                cooperative_sha256=digest(coop_path), data_directory=str(run))
            return session
        except BaseException as error:
            if coop is not None:
                try:
                    coop.close()
                except Exception as cleanup:
                    raise HostError(str(error) + '; startup cleanup: ' + str(cleanup)) from error
            raise

    def _log(self, kind, text):
        # Never raise through a native callback. c_char_p is the native's own
        # NUL-terminated ABI; only bounded valid UTF8 reaches the IPC envelope.
        try:
            if _thread.get_ident() != self.owner_thread:
                self.log_overflow = True
                return
            value = (text or b'').decode('utf-8', errors='replace').encode('utf-8')
            if len(self.logs) >= w.MAX_LOGS or len(value) > w.MAX_LOG_BYTES:
                self.log_overflow = True
                return
            self.logs.append((int(kind), value))
        except BaseException:
            self.log_overflow = True

    def drain_logs(self):
        result, self.logs = self.logs, []
        return result

    def healthy(self):
        if _thread.get_ident() != self.owner_thread:
            raise HostError('native API called outside the sole worker owner thread')
        if self.arena:
            self.arena.healthy()
        if self.cooperative and not self.cooperative.healthy():
            raise HostError('unsafe cooperative native boundary')

    def _call(self, name, *args):
        self.healthy()
        result = self.api.call(name, *args)
        return self._after_call(result)

    def _after_call(self, result):
        self.healthy()
        if self.log_overflow:
            raise HostError('native callback log queue exceeded bounds')
        return result

    def _world(self, key):
        if key not in self.worlds:
            raise HostError('unknown/stale worker world ID')
        return self.worlds[key]

    def _retire_prediction(self, key):
        prediction = self.predictions.pop(key, None)
        adapter = self.prediction_adapters.pop(key, None)
        self.prepared_prediction.pop(key, None)
        self.terminal_admitted.pop(key, None)
        self.terminal_masked.pop(key, None)
        errors = []
        if prediction:
            try:prediction.close()
            except Exception as error:errors.append(str(error))
        if adapter:
            try:adapter.close()
            except Exception as error:errors.append(str(error))
        if prediction and self.arena:
            try:self.arena.forget_baseline()
            except Exception as error:errors.append(str(error))
        if errors:
            raise HostError('native prediction cleanup: ' + '; '.join(errors))

    def _enable_cooperative(self):
        if self.cooperative is None and self.cooperative_factory:
            self.cooperative = self.cooperative_factory()
            self.healthy()

    def _close_cooperative(self):
        if self.cooperative is not None:
            errors = []
            try:
                self.healthy()
            except Exception as exc:
                errors.append(str(exc))
            try:
                self.cooperative.close()
            except Exception as exc:
                errors.append(str(exc))
            finally:
                self.retired_cooperative = self.cooperative
                self.cooperative = None
            if errors:
                raise HostError('; '.join(errors))

    @staticmethod
    def _buffer(size):
        if not 0 <= size <= w.MAX_BUFFER:
            raise HostError('successful native buffer size exceeds bounds')
        return C.create_string_buffer(max(1, size))

    def _pair(self, size, make_name, make_args, get_name, get_args, *, signed=False):
        code = self._call(make_name, *make_args)
        get_code, payload = -1, b''
        if code == 0:
            output = self._buffer(size.value)
            get_code = self._call(get_name, *get_args(output))
            if get_code == 0:
                payload = output.raw[:size.value]
        return code, struct.pack('<iiI' if signed else '<IiI', size.value, get_code, len(payload)) + payload

    def dispatch(self, command):
        if _thread.get_ident() != self.owner_thread:
            raise HostError('native dispatch called outside the sole worker owner thread')
        if self.closed:
            raise HostError('native worker session is closed')
        op, args = command.opcode, command.args
        if op == w.Op.INIT:
            if self.initialized or self.worlds:
                raise HostError('native runtime already initialized')
            self.healthy()
            code = self.api.call('SimInit', bool(args[0]))
            if code == 0:
                self.initialized = True
            return self._after_call(code), b''
        if op == w.Op.DESTROY:
            if self.worlds:
                raise HostError('destroy every world before SimDestroy')
            self.healthy()
            code = self.api.call('SimDestroy')
            if code == 0:
                self.initialized = False
            return self._after_call(code), b''
        if op == w.Op.SET_LOG_CALLBACK:
            pointer = C.cast(self.callback, C.c_void_p) if args[0] else C.c_void_p()
            code = self._call('SimSetLogCallBack', pointer)
            if code == 0:
                self.log_enabled = bool(args[0])
            return code, b''
        if op == w.Op.SET_LOG_FLAGS:
            return self._call('SimSetLogFlags', args[0]), b''
        if op == w.Op.CREATE_WORLD:
            if not self.initialized or self.worlds:
                raise HostError('one initialized active native world required')
            if self.next_world > 0xffffffffffffffff:
                raise HostError('native world IDs exhausted')
            self._enable_cooperative()
            raw = C.create_string_buffer(args[0])
            world = C.c_uint64()
            self.healthy()
            # Track ownership BEFORE a failing post-call health/log check so
            # teardown can reclaim a world that the native call already made.
            try:
                code = self.api.call('SimCreateWorld', raw, len(args[0]), C.byref(world))
            finally:
                if world.value:
                    key = self.next_world
                    self.next_world += 1
                    self.worlds[key] = world.value
            self._after_call(code)
            if code != 0:
                if world.value:
                    raise HostError('failed native creation returned an owned world')
                return code, struct.pack('<Q', 0)
            if not world.value:
                raise HostError('native world creation/ID failed')
            return code, struct.pack('<Q', key)
        if op == w.Op.CRASH:
            return self._call('SimCrashOnCommand'), b''
        if op == w.Op.SHUTDOWN:
            return 0, b''  # Stream owner performs cleanup before acknowledging.
        world = self._world(args[0])
        if op == w.Op.PREDICTION_BEGIN:
            if args[0] in self.dirty_worlds or args[0] in self.predictions:
                raise HostError('prediction must begin once,before first native frame')
            from .checkpoint import CheckpointAdapter
            from .prediction import Reconciler
            adapter = CheckpointAdapter(self, args[0])
            prediction = Reconciler(adapter, max_ahead=args[1], max_journal_bytes=args[2])
            # Retain cleanup ownership before the initial full capture.
            self.prediction_adapters[args[0]], self.predictions[args[0]] = adapter, prediction
            prediction.prime()
            return 0, b''
        if op in (w.Op.PREDICTION_AUTHORITY, w.Op.PREDICTION_METRICS):
            if args[0] not in self.predictions:
                raise HostError('native prediction is not enabled for this world')
            prediction = self.predictions[args[0]]
            if op == w.Op.PREDICTION_AUTHORITY:
                prediction.enqueue_authority(args[1])  # NO restore or native call here.
                return 0, b''
            stats = prediction.metrics
            values = tuple(stats[name] for name in ('captures','restores','drops','corrections',
                'replayed_frames','matched_frames','peak_ahead')) + (int(stats['max_reconcile_ms'] * 1000),)
            flags = (int(stats['prepared']) | (int(stats['failed']) << 1) | (int(stats['closed']) << 2) |
                     (int(args[0] in self.terminal_admitted) << 3))
            return 0, struct.pack('<iiiI8Q', prediction.confirmed_frame, prediction.predicted_frame,
                prediction.received_frame, flags, *values)
        if op == w.Op.DESTROY_WORLD:
            self._retire_prediction(args[0])
            self.healthy()
            code = self.api.call('SimDestroyWorld', world)
            if code == 0:
                del self.worlds[args[0]]
                self.dirty_worlds.discard(args[0])
            self._after_call(code)
            if code == 0:
                if not self.worlds:
                    self._close_cooperative()
            return code, b''
        if op == w.Op.PROCESS_MSG:
            prediction = self.predictions.get(args[0])
            actual = prediction.before_next_frame(args[1]) if prediction else args[1]
            raw = C.create_string_buffer(actual)
            self.dirty_worlds.add(args[0])
            code = self._call('SimProcessMsg', world, raw, len(actual))
            if prediction:
                if code:raise HostError('predicted native ProcessMsg failed')
                self.prepared_prediction[args[0]] = actual
            return code, b''
        if op == w.Op.STEP:
            prediction = self.predictions.get(args[0])
            if prediction and (args[0] not in self.prepared_prediction or args[1] != 50):
                raise HostError('predicted Step needs one prepared50ms frame')
            value = C.c_int32(args[2])
            self.dirty_worlds.add(args[0])
            code = self._call('SimStep', world, args[1], C.byref(value))
            if prediction:
                if code:raise HostError('predicted native Step failed')
                prediction.after_native_frame(self.prepared_prediction.pop(args[0]))
            return code, struct.pack('<i', value.value)
        if op == w.Op.MAKE_FRAME:
            size = C.c_uint32(args[2])
            code, data = self._pair(size, 'SimMakeSimFrame', (world, args[1], C.byref(size)),
                                   'SimGetSimFrameBuffer', lambda output: (world, output))
            prediction = self.predictions.get(args[0])
            if prediction and code == 0 and struct.unpack_from('<i',data,4)[0] == 0:
                from .presentation import confirmed_terminal_view
                view, masked, key = confirmed_terminal_view(data[12:],
                    confirmed_frame=prediction.confirmed_frame, physical_frame=prediction.predicted_frame)
                if args[0] in self.terminal_admitted and key != self.terminal_admitted[args[0]]:
                    raise HostError('confirmed native terminal result changed')
                if masked:
                    self.terminal_masked[args[0]] = self.terminal_masked.get(args[0],0) + 1
                elif key is not None:
                    self.terminal_admitted[args[0]] = key
                data = data[:12] + view
            return code, data
        if op == w.Op.LABEL_SIZE:
            size = C.c_uint32(args[2])
            return self._pair(size, 'SimGetLabelsFrameBufferSize', (world, args[1], C.byref(size)),
                              'SimGetLabelsFrameBuffer', lambda output: (world, args[1], output))
        if op == w.Op.MAP_SIZE:
            size = C.c_int32(args[1])
            return self._pair(size, 'SimGetMapFrameSize', (world, C.byref(size)),
                              'SimGetMapFrame', lambda output: (world, output), signed=True)
        if op == w.Op.PLAYERS_SIZE:
            size, version = C.c_int32(args[1]), C.c_int32(args[2])
            code = self._call('SimGetConnectedPlayersSizeAndVersion', world, C.byref(size), C.byref(version))
            get_code, payload = -1, b''
            if code == 0:
                output = self._buffer(size.value)
                get_code = self._call('SimGetConnectedPlayers', world, output)
                if get_code == 0:
                    payload = output.raw[:size.value]
            return code, struct.pack('<iiiI', size.value, version.value, get_code, len(payload)) + payload
        if op in (w.Op.DEBUG_COUNT, w.Op.SYSTEM_COUNT):
            value = C.c_uint32(args[1])
            name = 'SimGetSystemCount' if op == w.Op.SYSTEM_COUNT else 'SimGetDebugDrawCommandBufferCount'
            code = self._call(name, world, C.byref(value))
            if code == 0 and value.value > w.MAX_SYSTEMS:
                raise HostError('successful native system/debug count exceeds bounds')
            return code, struct.pack('<I', value.value)
        if op == w.Op.DEBUG_SIZE:
            size = C.c_uint32(args[1])
            code = self._call('SimGetDebugDrawCommandBufferSize', world, C.byref(size), args[2])
            if code != 8 or size.value != args[1]:
                raise HostError('guarded debug stub result/write contract changed')
            # The guarded stub has no writes, so the client Get must preserve
            # its existing bytes. A nonzero seed is not an allocation request.
            return code, struct.pack('<IiI', size.value, 8, 0)
        if op == w.Op.DEBUG_CLEAR:
            return self._call('SimClearAllDebugDrawCommandBuffers', world), b''
        if op == w.Op.DEBUG_ACTIVE:
            count = len(args[1])
            values = (C.c_int32 * max(1, count))(*args[1])
            return self._call('SimSetDebugDrawCommandListsActive', world, count, values), b''
        if op == w.Op.SYSTEM_ATTRIBUTES:
            output = C.create_string_buffer(args[2], max(1, len(args[2])))
            code = self._call('SimGetSystemIDAttributes', world, output, args[1])
            return code, output.raw[:len(args[2])]
        raise HostError('native opcode implementation missing')

    def close(self):
        if _thread.get_ident() != self.owner_thread:
            raise HostError('native cleanup called outside the sole worker owner thread')
        if self.closed:
            return
        self.closed = True
        errors = []

        def attempt(name, *args):
            try:
                code = self.api.call(name, *args)
                if code:
                    errors.append(name + ' returned ' + str(code))
            except BaseException as exc:
                errors.append(name + ': ' + str(exc))

        for key in tuple(self.predictions):
            try:self._retire_prediction(key)
            except BaseException as error:errors.append(str(error))
        if self.arena and hasattr(self.arena, 'release_unreturned'):
            try:self.arena.release_unreturned()
            except BaseException as error:errors.append(str(error))
        for world in reversed(tuple(self.worlds.values())):
            attempt('SimDestroyWorld', world)
        self.worlds.clear()
        self.dirty_worlds.clear()
        # Retain callback and helpers until every original native teardown call
        # completes. Heap interception stays loaded through process CRT detach.
        attempt('SimSetLogCallBack', C.c_void_p())
        self.log_enabled = False
        if self.initialized:
            attempt('SimDestroy')
            self.initialized = False
        try:
            self._close_cooperative()
            self.healthy()
        except BaseException as exc:
            errors.append(str(exc))
        if errors:
            raise HostError('native cleanup failed: ' + '; '.join(errors))
