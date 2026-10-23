"""Passive lifetime evidence for an existing SuspendedChild's owned job only.

No process creation, termination, remote execution, privilege changes or system
enumeration. Retained handles have SYNCHRONIZE | QUERY_LIMITED_INFORMATION only.
Job accounting detects descendants that exited between observations: an empty
job alone is insufficient evidence that every process identity was retained.
"""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import hashlib
import math
import os
from pathlib import Path
import time


class _WindowsObserver:
    ACCESS = 0x00100000 | 0x1000

    def __init__(self):
        if os.name != 'nt':
            raise ValueError('Windows owned job required')
        self.api = c.WinDLL('kernel32', use_last_error=True)
        declarations = {
            'OpenProcess': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'CloseHandle': ([w.HANDLE], w.BOOL),
            'GetProcessId': ([w.HANDLE], w.DWORD),
            'GetProcessTimes': ([w.HANDLE] + [c.POINTER(w.FILETIME)]*4, w.BOOL),
            'IsProcessInJob': ([w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)], w.BOOL),
            'QueryFullProcessImageNameW': ([w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL),
            'QueryInformationJobObject': ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
            'GetExitCodeProcess': ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.api, name)
            fn.argtypes, fn.restype = args, result

    def _check(self, result):
        if not result:
            raise c.WinError(c.get_last_error())

    def validate_owner(self, child):
        from tools.owned_suspended_launch import SuspendedChild
        if type(child) is not SuspendedChild or not child.handle or not child.job or not child.job.handle:
            raise ValueError('Existing live owner handles required')
        if self.api.GetProcessId(child.handle) != child.pid:
            raise ValueError('Owner process handle/PID differs')
        self.in_job(child.handle, child.job.handle)

    def in_job(self, handle, job):
        member = w.BOOL()
        self._check(self.api.IsProcessInJob(handle, job, c.byref(member)))
        if not member.value:
            raise RuntimeError('Process handle is not in the owned job')

    def accounting(self, job):
        class Accounting(c.Structure):
            _fields_ = [(n, c.c_longlong) for n in ('user', 'kernel', 'period_user', 'period_kernel')] + [
                (n, w.DWORD) for n in ('faults', 'total', 'active', 'terminated')]
        value = Accounting()
        length = w.DWORD()
        self._check(self.api.QueryInformationJobObject(job, 1, c.byref(value), c.sizeof(value), c.byref(length)))
        if c.sizeof(value) != 48 or length.value != 48:
            raise RuntimeError('Owned job accounting layout differs')
        return dict(total=int(value.total), active=int(value.active), terminated=int(value.terminated))

    def members(self, job):
        class Members(c.Structure):
            _fields_ = [('assigned', w.DWORD), ('count', w.DWORD), ('pids', c.c_size_t * 4096)]
        value = Members()
        length = w.DWORD()
        self._check(self.api.QueryInformationJobObject(job, 3, c.byref(value), c.sizeof(value), c.byref(length)))
        if value.assigned != value.count or value.count > 4096:
            raise RuntimeError('Complete bounded owned job membership unavailable')
        pids = [int(p) for p in value.pids[:value.count]]
        if len(set(pids)) != len(pids) or any(p <= 0 for p in pids):
            raise RuntimeError('Owned job PID list differs')
        return pids

    def open(self, pid):
        handle = self.api.OpenProcess(self.ACCESS, False, pid)
        self._check(handle)
        return handle

    def identity(self, handle, pid, job):
        if self.api.GetProcessId(handle) != pid:
            raise RuntimeError('Opened handle/PID differs')
        self.in_job(handle, job)
        creation, exit_time, kernel, user = (w.FILETIME() for _ in range(4))
        self._check(self.api.GetProcessTimes(handle, c.byref(creation), c.byref(exit_time), c.byref(kernel), c.byref(user)))
        ticks = lambda t: int(t.dwHighDateTime) << 32 | int(t.dwLowDateTime)
        name = c.create_unicode_buffer(32768)
        size = w.DWORD(len(name))
        self._check(self.api.QueryFullProcessImageNameW(handle, 0, name, c.byref(size)))
        path = Path(name.value)
        if not path.is_absolute() or not ticks(creation):
            raise RuntimeError('Absolute image/creation identity unavailable')
        digest = hashlib.sha256()
        with path.open('rb') as image:
            for chunk in iter(lambda: image.read(1024 * 1024), b''):
                digest.update(chunk)
        return dict(pid=pid, creation_filetime=ticks(creation), image=str(path),
                    image_sha256=digest.hexdigest(), in_owned_job=True)

    def exit(self, handle):
        status = self.api.WaitForSingleObject(handle, 0)
        if status == 258:
            return None
        if status != 0:
            raise RuntimeError(f'Owned retained process wait failed: {status}')
        code = w.DWORD()
        self._check(self.api.GetExitCodeProcess(handle, c.byref(code)))
        creation, exit_time, kernel, user = (w.FILETIME() for _ in range(4))
        self._check(self.api.GetProcessTimes(handle, c.byref(creation), c.byref(exit_time), c.byref(kernel), c.byref(user)))
        ticks = lambda t: int(t.dwHighDateTime) << 32 | int(t.dwLowDateTime)
        if not ticks(exit_time):
            raise RuntimeError('Signaled process exit FILETIME unavailable')
        # STILL_ACTIVE (259) is valid as an actual exit code after signaled wait.
        return dict(exit_code=int(code.value), exit_filetime=ticks(exit_time),
                    kernel_filetime=ticks(kernel), user_filetime=ticks(user), wait_signaled=True)

    def close(self, handle):
        self._check(self.api.CloseHandle(handle))


class OwnedJobTracker:
    """Borrow owner job; retain identities and query handles until close().

    observe() samples membership and exits; settle() polls boundedly until the
    whole job empties; report() returns JSON-safe evidence without live handles.
    close() closes tracker handles only and never closes the owner/job handles.
    Completeness means observed lifetime coverage, not a claim of graceful exit.
    """
    def __init__(self, child, *, _observer=None, _clock=time.monotonic, _sleep=time.sleep):
        self._observer = _observer or _WindowsObserver()
        self._observer.validate_owner(child)
        self._child = child
        self._job = child.job.handle
        self.root_pid = child.pid
        self._clock, self._sleep = _clock, _sleep
        self._records = {}
        self._errors = []
        self._samples = []
        self._last = None
        self._closed = False
        self._settle_timeout = False

    def _error(self, phase, error, pid=None):
        self._errors.append(dict(phase=phase, pid=pid, error=repr(error)))

    def observe(self):
        if self._closed:
            raise RuntimeError('Tracker is closed')
        if not self._child.job or self._child.job.handle != self._job:
            raise RuntimeError('Owner job handle changed or closed')
        sample = dict(ordinal=len(self._samples), monotonic=self._clock(), stable=False)
        try:
            before = self._observer.accounting(self._job)
            pids = self._observer.members(self._job)
            sample.update(before=before, member_pids=pids)
            for pid in pids:
                handle = None
                try:
                    # Existing live handles pin their process identity, avoiding
                    # repeated image hashing. Signaled old PID does not match reuse.
                    live = [r for r in self._records.values() if r['pid'] == pid and r.get('exit') is None]
                    for record in live:
                        record['exit'] = self._observer.exit(record['_handle'])
                    if len(live) == 1 and live[0]['exit'] is None:
                        self._observer.in_job(live[0]['_handle'], self._job)
                        live[0]['last_seen_sample'] = sample['ordinal']
                        continue
                    handle = self._observer.open(pid)
                    identity = self._observer.identity(handle, pid, self._job)
                    key = (pid, identity['creation_filetime'])
                    if key in self._records:
                        raise RuntimeError('Membership lists an already signaled retained identity')
                    record = dict(identity, first_seen_sample=sample['ordinal'],
                                  last_seen_sample=sample['ordinal'], exit=None, _handle=handle)
                    self._records[key] = record
                    handle = None
                except Exception as error:
                    self._error('retain_member', error, pid)
                finally:
                    if handle is not None:
                        self._observer.close(handle)
            for record in self._records.values():
                if record['exit'] is None:
                    try:
                        record['exit'] = self._observer.exit(record['_handle'])
                    except Exception as error:
                        self._error('wait_exit', error, record['pid'])
            after = self._observer.accounting(self._job)
            sample['after'] = after
            sample['stable'] = before == after and len(pids) == after['active']
            self._last = after
        except Exception as error:
            self._error('observe', error)
        self._samples.append(sample)
        return self.report()

    def settle(self, *, timeout=10.0, poll=.02):
        if isinstance(timeout, bool) or isinstance(poll, bool) or not all(
                isinstance(v, (int, float)) and math.isfinite(v) for v in (timeout, poll)) or not 0 <= timeout <= 60 or not .001 <= poll <= 1:
            raise ValueError('Finite bounded timeout/poll required')
        deadline = self._clock() + timeout
        while True:
            result = self.observe()
            if self._last is not None and self._last['active'] == 0 and self._samples[-1]['stable']:
                return result
            if self._clock() >= deadline:
                self._settle_timeout = True
                return self.report()
            self._sleep(min(poll, max(0, deadline-self._clock())))

    def report(self):
        records = [{k: v for k, v in record.items() if k != '_handle'} for record in self._records.values()]
        final = self._last
        root_retained = any(r['pid'] == self.root_pid for r in records)
        all_exited = bool(records) and all(r['exit'] is not None for r in records)
        total_matches = final is not None and final['total'] == len(records)
        stable = bool(self._samples) and self._samples[-1]['stable']
        empty = final is not None and final['active'] == 0
        complete = bool(root_retained and all_exited and total_matches and stable and empty and
                        final['terminated'] == 0 and not self._errors and not self._settle_timeout)
        return dict(schema=1, root_pid=self.root_pid, complete=complete,
                    complete_scope='retained owned-job process lifetime coverage; graceful/native causality not inferred',
                    closed=self._closed, root_retained=root_retained, all_retained_exited=all_exited,
                    job_empty=empty, total_matches_retained_identities=total_matches,
                    final_accounting=final, settle_timeout=self._settle_timeout,
                    records=records, errors=list(self._errors), samples=list(self._samples),
                    termination_api_called=False, owner_handles_closed=False)

    def close(self):
        if self._closed:
            return self.report()
        for record in self._records.values():
            handle = record['_handle']
            if handle is not None:
                try:
                    self._observer.close(handle)
                    record['_handle'] = None
                except Exception as error:
                    self._error('close_query_handle', error, record['pid'])
        self._closed = True
        return self.report()

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()
