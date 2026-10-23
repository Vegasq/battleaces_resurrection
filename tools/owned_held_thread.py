"""Resume exactly one already-held thread belonging to a tracked owned process.

No suspension, process creation/termination, privilege changes, global process
enumeration or remote-memory reads. This class does not authenticate a debugger
protocol: its caller must validate that private parent gate separately. Failure
may leave a thread held; the existing owner retains responsibility for its job.
"""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
from pathlib import PureWindowsPath
import re
import struct
from tools.owned_job_tracker import _WindowsObserver
from tools.owned_suspended_launch import SuspendedChild


class HeldThreadFailure(RuntimeError):
    def __init__(self, receipt, *, cleanup=None):
        super().__init__('Owned held-thread validation/resume failed; inspect receipt')
        self.receipt = receipt
        self._cleanup = cleanup

    def close(self):
        """Retry closing this operation's owned handles after a failure."""
        return self._cleanup.close() if self._cleanup is not None else self.receipt


class _HeldObserver(_WindowsObserver):
    ACCESS = 0x00100000 | 0x0400 | 0x0010  # SYNCHRONIZE | QUERY_INFORMATION | VM_READ
    THREAD_ACCESS = 0x0040 | 0x0002  # QUERY_INFORMATION | SUSPEND_RESUME

    def __init__(self):
        super().__init__()
        declarations = {
            'OpenThread': ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            'GetThreadId': ([w.HANDLE], w.DWORD),
            'GetProcessIdOfThread': ([w.HANDLE], w.DWORD),
            'GetThreadTimes': ([w.HANDLE] + [c.POINTER(w.FILETIME)]*4, w.BOOL),
            'GetExitCodeThread': ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
            'ResumeThread': ([w.HANDLE], w.DWORD),
            'GetTickCount64': ([], c.c_ulonglong),
        }
        for name, (args, result) in declarations.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.native = c.WinDLL('ntdll', use_last_error=True)
        self.native.NtQueryInformationProcess.argtypes = [w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.POINTER(w.ULONG)]
        self.native.NtQueryInformationProcess.restype = w.LONG

    def tick(self):
        return int(self.api.GetTickCount64())

    def open_thread(self, tid):
        handle = self.api.OpenThread(self.THREAD_ACCESS, False, tid)
        self._check(handle)
        return handle

    def thread_identity(self, handle, pid, tid):
        if self.api.GetThreadId(handle) != tid or self.api.GetProcessIdOfThread(handle) != pid:
            raise RuntimeError('Owned thread PID/TID identity differs')
        creation, exit_time, kernel, user = (w.FILETIME() for _ in range(4))
        self._check(self.api.GetThreadTimes(handle, c.byref(creation), c.byref(exit_time), c.byref(kernel), c.byref(user)))
        ticks = lambda t: int(t.dwHighDateTime) << 32 | int(t.dwLowDateTime)
        code = w.DWORD()
        self._check(self.api.GetExitCodeThread(handle, c.byref(code)))
        # Exit code259 alone is ambiguous: an exited thread may return259.
        if not ticks(creation) or ticks(exit_time) != 0 or code.value != 259:
            raise RuntimeError('Owned held thread is no longer live')
        return dict(pid=pid, tid=tid, creation_filetime=ticks(creation), exit_filetime=0, exit_code=259)

    def basic(self, handle, pid):
        if c.sizeof(c.c_void_p) != 8:
            raise RuntimeError('Owned x64 process query required')
        buffer = c.create_string_buffer(48)
        size = w.ULONG()
        status = self.native.NtQueryInformationProcess(handle, 0, buffer, len(buffer), c.byref(size))
        if status != 0 or size.value != 48 or struct.unpack_from('<Q', buffer.raw, 32)[0] != pid:
            raise RuntimeError(f'Owned process basic information differs: NTSTATUS={status:#x}')
        peb = struct.unpack_from('<Q', buffer.raw, 8)[0]
        if not 0 < peb < 2**63 or peb % 8:
            raise RuntimeError('Owned x64 PEB address unavailable')
        return dict(pid=pid, pebAddress=hex(peb))

    def resume_thread(self, handle):
        return int(self.api.ResumeThread(handle))


def _pid(value):
    return type(value) is int and 0 < value <= 0xffffffff


def _image(value):
    if not isinstance(value, str) or '\0' in value or not PureWindowsPath(value).is_absolute():
        raise ValueError('Tracked absolute Windows image required')
    return str(PureWindowsPath(value.removeprefix('\\\\?\\'))).casefold()


def _record(value):
    if type(value) is not dict or value.get('in_owned_job') is not True or 'exit' not in value or value['exit'] is not None:
        raise ValueError('Live tracked owned-job identity record required')
    pid, creation, image, digest = (value.get(k) for k in ('pid', 'creation_filetime', 'image', 'image_sha256'))
    if not _pid(pid) or type(creation) is not int or not 0 < creation < 2**64:
        raise ValueError('Tracked PID/creation identity required')
    normalized = _image(image)
    if not isinstance(digest, str) or re.fullmatch('[0-9a-fA-F]{64}', digest) is None:
        raise ValueError('Tracked image SHA256 required')
    return dict(pid=pid, creation_filetime=creation, image=image, image_normalized=normalized, image_sha256=digest.lower())


class OwnedHeldThread:
    """Own only new query/thread handles; the original owner/job remain borrowed.

    cwd_descriptor contains ONLY {pid, pebAddress}, obtained from48byte process
    basic information. No environment or target-memory read occurs here.
    resume() attempts ResumeThread at most once, accepting previouscount1 only.
    close() never resumes implicitly, and is retryable if a handle close fails.
    """
    def __init__(self, owner: SuspendedChild, *, record: dict, tid: int, _observer=None):
        if type(owner) is not SuspendedChild or not getattr(owner, 'handle', None) or not getattr(owner, 'job', None) or not getattr(owner.job, 'handle', None) or not _pid(owner.pid):
            raise ValueError('Exact existing SuspendedChild owner handles required')
        expected = _record(record)
        if not _pid(tid):
            raise ValueError('Explicit tracked thread ID required')
        self._owner, self._job, self._expected = owner, owner.job.handle, expected
        self._pid, self._tid = expected['pid'], tid
        self._observer = _observer or _HeldObserver()
        self._process = self._thread = None
        self._thread_identity = self._descriptor = None
        self._attempted = False
        self._closed = False
        self._close_requested = False
        self.receipt = dict(schema=1, pid=self.pid, tid=self.tid,
                            process_access=_HeldObserver.ACCESS, thread_access=_HeldObserver.THREAD_ACCESS,
                            process_validated=False, thread_validated=False, resume_attempted=False,
                            resumed=False, resume_previous_count=None, closed=False, close_requested=False,
                            termination_api_called=False, suspension_api_called=False,
                            owner_handles_closed=False, errors=[], close_errors=[])
        try:
            self._validate_owner()
            self._process = self._observer.open(self.pid)
            if not self._process:
                self._process = None
                raise RuntimeError('Owned process query handle absent')
            self._validate_process()
            self._thread = self._observer.open_thread(self.tid)
            if not self._thread:
                self._thread = None
                raise RuntimeError('Owned held-thread handle absent')
            self._validate_thread()
            self._descriptor = self._observer.basic(self._process, self.pid)
            if type(self._descriptor) is not dict or set(self._descriptor) != {'pid', 'pebAddress'} or self._descriptor['pid'] != self.pid:
                raise RuntimeError('Owned cwd descriptor layout differs')
            try:
                peb = int(self._descriptor['pebAddress'], 16)
            except (TypeError, ValueError) as error:
                raise RuntimeError('Owned cwd PEB address differs') from error
            if not 0 < peb < 2**63 or peb % 8:
                raise RuntimeError('Owned cwd PEB address differs')
            self.receipt['cwd_descriptor'] = dict(self._descriptor)
        except Exception as error:
            self.receipt['errors'].append(dict(phase='constructor', error=repr(error)))
            self.close()
            raise HeldThreadFailure(self.receipt, cleanup=self) from error

    @property
    def pid(self):
        return self._pid

    @property
    def tid(self):
        return self._tid

    @property
    def cwd_descriptor(self):
        if self._descriptor is None:
            raise RuntimeError('Owned cwd descriptor unavailable')
        return dict(self._descriptor)

    def _validate_owner(self):
        if not self._owner.handle or not self._owner.job or self._owner.job.handle != self._job:
            raise RuntimeError('Original owner/job handles changed')
        self._observer.validate_owner(self._owner)
        if self._observer.exit(self._owner.handle) is not None:
            raise RuntimeError('Original owned root process is no longer live')

    def _validate_process(self):
        if not self._process:
            raise RuntimeError('Owned process query handle unavailable')
        actual = self._observer.identity(self._process, self.pid, self._job)
        for key in ('pid', 'creation_filetime', 'image_sha256'):
            if actual.get(key) != self._expected[key]:
                raise RuntimeError(f'Tracked owned process {key} differs')
        if _image(actual.get('image')) != self._expected['image_normalized'] or actual.get('in_owned_job') is not True:
            raise RuntimeError('Tracked owned process image/job differs')
        if self._observer.exit(self._process) is not None:
            raise RuntimeError('Tracked owned process is no longer live')
        self.receipt['process_validated'] = True
        self.receipt['process_identity'] = actual

    def _validate_thread(self):
        if not self._thread:
            raise RuntimeError('Owned held-thread handle unavailable')
        actual = self._observer.thread_identity(self._thread, self.pid, self.tid)
        if actual.get('pid') != self.pid or actual.get('tid') != self.tid or actual.get('exit_filetime') != 0 or actual.get('exit_code') != 259:
            raise RuntimeError('Owned held-thread identity/state differs')
        if type(actual.get('creation_filetime')) is not int or actual['creation_filetime'] < self._expected['creation_filetime']:
            raise RuntimeError('Owned held-thread creation identity differs')
        if self._thread_identity is not None and actual != self._thread_identity:
            raise RuntimeError('Retained held-thread identity changed')
        self._thread_identity = dict(actual)
        self.receipt['thread_validated'] = True
        self.receipt['thread_identity'] = dict(actual)

    def resume(self):
        if self._close_requested or self._closed or not self._process or not self._thread:
            raise RuntimeError('Owned held-thread query handles closed/unavailable')
        if self._attempted:
            raise RuntimeError('Owned held-thread resume already attempted')
        # Consume the one permitted call even if revalidation fails. No later
        # repair/retry may turn a refused held-thread operation into a resume.
        self._attempted = True
        try:
            self._validate_owner()
            self._validate_process()
            self._validate_thread()
            before = self._observer.tick()
            self.receipt.update(resume_attempted=True, resume_before_tick=before)
            count = self._observer.resume_thread(self._thread)
            self.receipt.update(resume_previous_count=count, resume_return_tick=self._observer.tick())
            if type(count) is not int or count != 1:
                raise RuntimeError('Expected exactly one prior thread suspension')
            self.receipt['resumed'] = True
            return self.receipt
        except Exception as error:
            self.receipt['errors'].append(dict(phase='resume', error=repr(error)))
            raise HeldThreadFailure(self.receipt, cleanup=self) from error

    def close(self):
        # No implicit resume, process/job close or force-cleanup here. Both own
        # handles get an independent close attempt even when the first fails.
        self._close_requested = True
        self.receipt['close_requested'] = True
        for name in ('_thread', '_process'):
            handle = getattr(self, name)
            if handle is not None:
                try:
                    self._observer.close(handle)
                    setattr(self, name, None)
                except Exception as error:
                    self.receipt['close_errors'].append(dict(handle_kind=name, error=repr(error)))
        self._closed = self._thread is None and self._process is None
        self.receipt['closed'] = self._closed
        return self.receipt

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()
