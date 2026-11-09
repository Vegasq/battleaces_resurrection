"""Exact-build, owned-process native experiments; never installed-client hooks."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import os
from pathlib import Path

from server import native_simulation

SERIAL_POOL_RVA = 0x331B4
SERIAL_POOL_ORIGINAL = bytes.fromhex('8d5603')
SERIAL_POOL_PATCH = bytes.fromhex('8d5600')
COOPERATIVE_FIELDS = ('version','error','waitEntries','pumps','emptyPumps','maxDepth','depth',
                      'consumerWaits','producerWaits','foreignThreads','poolChanges','exceptions',
                      'pool','owner','codeBase')


def _kernel():
    if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
        raise RuntimeError('native prediction experiments require owned Windows x64 processes')
    return C.WinDLL('kernel32', use_last_error=True)


def preload_original(dllpath):
    """Retain the selected original module without initializing its simulation."""
    _kernel()
    if native_simulation._runtime is not None:
        raise RuntimeError('preload/serial preparation must precede SimInit and world creation')
    path = Path(dllpath).resolve()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != native_simulation.SUPPORTED_DLL_SHA256:
        raise ValueError('prediction experiment requires the exact original Simulation.dll')
    dll = C.CDLL(str(path))
    address = dll._handle + SERIAL_POOL_RVA
    if C.string_at(address, len(SERIAL_POOL_ORIGINAL)) != SERIAL_POOL_ORIGINAL:
        raise RuntimeError('native serial-pool instruction guard differs before preparation')
    dll.prediction_preparation = dict(path=str(path), disk_sha256=actual,
        module_base=hex(dll._handle), serial_pool=False, rva=hex(SERIAL_POOL_RVA),
        before=SERIAL_POOL_ORIGINAL.hex(), after=SERIAL_POOL_ORIGINAL.hex())
    return dll


def prepare_serial(dllpath):
    """Retain a loaded original DLL with only its world pool request changed3->0.

    The disk DLL is untouched. Original submission, cooperative execution,
    ownership, destructors and export behavior remain in place. The returned
    module must stay retained through all original-native worlds and helper use.
    This is an experimental process-local mode, not a complete checkpoint API.
    """
    dll = preload_original(dllpath)
    kernel = _kernel()
    kernel.VirtualProtect.argtypes = [C.c_void_p, C.c_size_t, C.c_ulong, C.POINTER(C.c_ulong)]
    kernel.VirtualProtect.restype = C.c_int
    kernel.FlushInstructionCache.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
    kernel.FlushInstructionCache.restype = C.c_int
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = C.c_void_p
    address, size = dll._handle + SERIAL_POOL_RVA, len(SERIAL_POOL_PATCH)
    prior = C.c_ulong()
    if not kernel.VirtualProtect(address, size, 0x40, C.byref(prior)):
        raise C.WinError(C.get_last_error())
    try:
        C.memmove(address, SERIAL_POOL_PATCH, size)
    finally:
        ignored = C.c_ulong()
        if not kernel.VirtualProtect(address, size, prior.value, C.byref(ignored)):
            raise C.WinError(C.get_last_error())
    if not kernel.FlushInstructionCache(kernel.GetCurrentProcess(), address, size):
        raise C.WinError(C.get_last_error())
    if C.string_at(address, size) != SERIAL_POOL_PATCH:
        raise RuntimeError('native serial-pool patch readback differs')
    if hashlib.sha256(Path(dllpath).read_bytes()).hexdigest() != dll.prediction_preparation['disk_sha256']:
        raise RuntimeError('original disk DLL changed during process-local preparation')
    dll.prediction_preparation.update(serial_pool=True, after=SERIAL_POOL_PATCH.hex())
    return dll


class Cooperative:
    """Retain a source-bound isolated helper until its native world is closed.

    healthy() returns bool; close() restores all experiment code hooks and raises
    on failure. The caller must close its NativeSimulation before close().
    """
    def __init__(self, helperpath, native):
        _kernel()
        path = Path(helperpath).resolve()
        receipt_path = path.with_name('build.json')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != receipt['dll_sha256']:
            raise ValueError('cooperative helper differs from its isolated build receipt')
        self.native, self.dll, self.closed = native, C.CDLL(str(path)), False
        self.provenance = dict(path=str(path), dll_sha256=actual, receipt=str(receipt_path),
            receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(), source_sha256=receipt['source_sha256'])
        self.dll.BAEnableCooperative.argtypes = [C.c_void_p]
        self.dll.BAEnableCooperative.restype = C.c_int
        self.dll.BASizeOfCooperativeStats.argtypes = []
        self.dll.BASizeOfCooperativeStats.restype = C.c_uint
        self.dll.BAGetCooperativeStats.argtypes = [C.c_void_p]
        self.dll.BAGetCooperativeStats.restype = C.c_int
        self.dll.BADisableCooperative.argtypes = []
        self.dll.BADisableCooperative.restype = C.c_int
        if self.dll.BASizeOfCooperativeStats() != 8*len(COOPERATIVE_FIELDS):
            raise ValueError('unsupported cooperative helper stats ABI')
        result = self.dll.BAEnableCooperative(native._handle)
        if result:
            raise RuntimeError('cooperative native guard/install failed: '+str(result))

    def stats(self):
        values = (C.c_uint64*len(COOPERATIVE_FIELDS))()
        if self.dll.BAGetCooperativeStats(values):
            raise RuntimeError('cooperative stats query failed')
        return dict(zip(COOPERATIVE_FIELDS, map(int, values)))

    def healthy(self):
        state = self.stats()
        return state['version'] == 1 and not any(state[key] for key in
            ('error','depth','foreignThreads','poolChanges','exceptions'))

    def close(self):
        if self.closed:
            return
        result = self.dll.BADisableCooperative()
        if result:
            raise RuntimeError('cooperative hook cleanup failed: '+str(result))
        self.closed = True


def own_thread_ids():
    """Observe only the current owned process's OS thread IDs."""
    kernel = _kernel()
    class ThreadEntry(C.Structure):
        _fields_ = [('size', C.c_ulong), ('usage', C.c_ulong), ('thread', C.c_ulong),
                    ('process', C.c_ulong), ('base_priority', C.c_long),
                    ('delta_priority', C.c_long), ('flags', C.c_ulong)]
    kernel.CreateToolhelp32Snapshot.argtypes = [C.c_ulong, C.c_ulong]
    kernel.CreateToolhelp32Snapshot.restype = C.c_void_p
    kernel.Thread32First.argtypes = [C.c_void_p, C.POINTER(ThreadEntry)]
    kernel.Thread32First.restype = C.c_int
    kernel.Thread32Next.argtypes = [C.c_void_p, C.POINTER(ThreadEntry)]
    kernel.Thread32Next.restype = C.c_int
    kernel.CloseHandle.argtypes = [C.c_void_p]
    kernel.CloseHandle.restype = C.c_int
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        entry, result = ThreadEntry(), set()
        entry.size = C.sizeof(entry)
        if not kernel.Thread32First(snapshot, C.byref(entry)):
            raise C.WinError(C.get_last_error())
        while True:
            if entry.process == os.getpid():
                result.add(int(entry.thread))
            entry.size = C.sizeof(entry)
            if not kernel.Thread32Next(snapshot, C.byref(entry)):
                if C.get_last_error() != 18:
                    raise C.WinError(C.get_last_error())
                break
        return sorted(result)
    finally:
        kernel.CloseHandle(snapshot)
