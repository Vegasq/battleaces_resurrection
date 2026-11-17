"""Opt-in affinity for a newly spawned, retained owned Windows worker handle.

This is not a host CPU quota. Wine/Linux require a separate pre-CREATE owned
descendant cpuset implementation; this policy deliberately refuses that path.
"""
from __future__ import annotations

import ctypes as c
import os
import struct


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def parse_core_topology(raw):
    """Parse Windows x64 RelationProcessorCore records, refusing other groups."""
    cores, offset, seen = [], 0, 0
    while offset < len(raw):
        _require(offset + 8 <= len(raw), 'truncated processor topology')
        relation, size = struct.unpack_from('<II', raw, offset)
        _require(size >= 32 and offset + size <= len(raw) and relation == 0,
                 'invalid processor core relationship')
        groups, = struct.unpack_from('<H', raw, offset + 30)
        _require(groups == 1 and size == 48, 'multiple processor groups are unsupported')
        mask, group = struct.unpack_from('<QH', raw, offset + 32)
        _require(group == 0 and mask and not seen & mask, 'invalid/overlapping physical core mask')
        cores.append(tuple(i for i in range(64) if mask & (1 << i)))
        seen |= mask
        offset += size
    _require(bool(cores), 'no physical core topology')
    return tuple(cores)


class _WindowsAPI:
    def __init__(self):
        _require(os.name == 'nt' and c.sizeof(c.c_void_p) == 8,
                 'owned worker affinity supports native Windows x64 only')
        from ctypes import wintypes as w
        self.kernel = k = c.WinDLL('kernel32', use_last_error=True)
        k.GetLogicalProcessorInformationEx.argtypes = [c.c_int, c.c_void_p, c.POINTER(w.DWORD)]
        k.GetLogicalProcessorInformationEx.restype = w.BOOL
        k.GetProcessAffinityMask.argtypes = [w.HANDLE, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)]
        k.GetProcessAffinityMask.restype = w.BOOL
        k.SetProcessAffinityMask.argtypes = [w.HANDLE, c.c_size_t]
        k.SetProcessAffinityMask.restype = w.BOOL
        k.GetCurrentProcess.argtypes = []; k.GetCurrentProcess.restype = w.HANDLE
        k.GetProcessId.argtypes = [w.HANDLE]; k.GetProcessId.restype = w.DWORD

    def topology(self):
        from ctypes import wintypes as w
        length = w.DWORD()
        ok = self.kernel.GetLogicalProcessorInformationEx(0, None, c.byref(length))
        _require(not ok and c.get_last_error() == 122 and 0 < length.value <= 1024*1024,
                 'processor topology size query failed')
        buffer = c.create_string_buffer(length.value)
        if not self.kernel.GetLogicalProcessorInformationEx(0, buffer, c.byref(length)):
            raise OSError(c.get_last_error(), 'processor topology query failed')
        return parse_core_topology(buffer.raw[:length.value])

    def masks(self, handle):
        process, system = c.c_size_t(), c.c_size_t()
        if not self.kernel.GetProcessAffinityMask(handle, c.byref(process), c.byref(system)):
            raise OSError(c.get_last_error(), 'GetProcessAffinityMask failed')
        return process.value, system.value

    def set_mask(self, handle, mask):
        if not self.kernel.SetProcessAffinityMask(handle, mask):
            raise OSError(c.get_last_error(), 'SetProcessAffinityMask failed')

    def pid(self, handle):
        return self.kernel.GetProcessId(handle)

    def current_mask(self):
        return self.masks(self.kernel.GetCurrentProcess())[0]


def select_physical_cpus(cores, allowed_mask):
    """Select one allowed logical processor from each of two distinct cores."""
    selected = [next((cpu for cpu in core if allowed_mask & (1 << cpu)), None) for core in cores]
    selected = [cpu for cpu in selected if cpu is not None]
    _require(len(selected) >= 2, 'two distinct allowed physical cores cannot be established')
    return tuple(selected[:2])


def host_topology():
    api = _WindowsAPI()
    cores = api.topology()
    mask = api.current_mask()
    selected = select_physical_cpus(cores, mask)
    return dict(source='GetLogicalProcessorInformationEx/RelationProcessorCore',
                physical_cores=[list(core) for core in cores], coordinator_allowed_mask=mask,
                selected_logical_cpus=list(selected), processor_group=0,
                scope='worker-only affinity; coordinator and host limits unchanged')


class WindowsWorkerAffinity:
    """Apply once before CREATE; never opens a process by PID or changes parent."""
    def __init__(self, cpus):
        _require(isinstance(cpus, (tuple, list)) and 1 <= len(cpus) <= 2
                 and all(type(cpu) is int and 0 <= cpu < 64 for cpu in cpus)
                 and len(set(cpus)) == len(cpus), 'one or two unique logical CPU IDs required')
        self.cpus = tuple(cpus)
        self.mask = sum(1 << cpu for cpu in cpus)
        self._process = self._api = None
        self.receipt = None

    def apply(self, process):
        _require(self._process is None, 'affinity policy is single-use')
        api = _WindowsAPI()
        _require(process.pid != os.getpid() and process.poll() is None
                 and getattr(process, '_handle', None) is not None,
                 'live retained owned Windows Popen handle required')
        handle = int(process._handle)
        _require(api.pid(handle) == process.pid, 'retained handle worker identity differs')
        cores = api.topology()
        memberships = [next((index for index, core in enumerate(cores) if cpu in core), None)
                       for cpu in self.cpus]
        _require(None not in memberships and len(set(memberships)) == len(self.cpus),
                 'requested CPUs must be on distinct physical cores')
        before, system = api.masks(handle)
        _require(before & self.mask == self.mask and system & self.mask == self.mask,
                 'requested CPUs outside inherited effective worker mask')
        self._process, self._api = process, api
        api.set_mask(handle, self.mask)
        actual = self.verify()
        self.receipt = dict(scope='native-windows-owned-worker-only', pid=process.pid,
                            before_create=True, inherited_mask=before, system_mask=system,
                            requested_mask=self.mask, actual_mask=actual,
                            logical_cpus=list(self.cpus), physical_core_indices=memberships,
                            topology=[list(core) for core in cores], processor_group=0)
        return dict(self.receipt)

    def verify(self):
        _require(self._process is not None and self._process.poll() is None,
                 'owned worker must still be alive to verify effective mask')
        handle = int(self._process._handle)
        _require(self._api.pid(handle) == self._process.pid, 'retained worker handle identity differs')
        actual, _ = self._api.masks(handle)
        _require(actual == self.mask, 'effective worker affinity mask differs')
        return actual
