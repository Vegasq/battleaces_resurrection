"""Own one ignored diagnostic child; attach before controlled primary resume.

Use CreateProcess directly: no global Popen hooks, raw-handle transfer gap,
enumeration, arbitrary-PID selection or privilege changes. Primary suspension
does not prevent Frida's injected threads/Windows loader work. Job assignment
is immediate after creation, not atomic with creation. Diagnostic only.
"""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import time
from server.worker_client import _WindowsJob

ROOT=Path(__file__).resolve().parents[1]


def kernel_api():
    if os.name!='nt':raise ValueError('Windows owned diagnostic required')
    kernel=c.WinDLL('kernel32',use_last_error=True)
    declarations={
        'CloseHandle':([w.HANDLE],w.BOOL),
        'GetThreadId':([w.HANDLE],w.DWORD),
        'GetProcessIdOfThread':([w.HANDLE],w.DWORD),
        'ResumeThread':([w.HANDLE],w.DWORD),
        'GetTickCount64':([],c.c_ulonglong),
        'WaitForSingleObject':([w.HANDLE,w.DWORD],w.DWORD),
        'GetExitCodeProcess':([w.HANDLE,c.POINTER(w.DWORD)],w.BOOL),
        'TerminateProcess':([w.HANDLE,w.UINT],w.BOOL),
        'TerminateJobObject':([w.HANDLE,w.UINT],w.BOOL),
        'QueryInformationJobObject':([w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)],w.BOOL),
        'OpenProcess':([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
        'QueryFullProcessImageNameW':([w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)],w.BOOL),
    }
    for name,(arguments,result) in declarations.items():
        function=getattr(kernel,name);function.argtypes=arguments;function.restype=result
    return kernel


def job_accounting(job):
    class Accounting(c.Structure):
        _fields_=[(name,c.c_longlong) for name in ('user_time','kernel_time','period_user_time','period_kernel_time')]+[
            (name,w.DWORD) for name in ('page_faults','total_processes','active_processes','total_terminated_processes')]
    value=Accounting();length=w.DWORD();kernel=kernel_api()
    if not job.handle or c.sizeof(value)!=48 or not kernel.QueryInformationJobObject(
            job.handle,1,c.byref(value),c.sizeof(value),c.byref(length)) or length.value!=48:
        raise RuntimeError('Owned job accounting unavailable')
    return {name:getattr(value,name) for name in ('total_processes','active_processes','total_terminated_processes')}


def job_members(job):
    """Metadata for this owned job only; no system-wide process enumeration."""
    class Members(c.Structure):
        _fields_=[('assigned',w.DWORD),('count',w.DWORD),('pids',c.c_size_t*32)]
    value=Members();length=w.DWORD();kernel=kernel_api()
    if not job.handle or not kernel.QueryInformationJobObject(job.handle,3,c.byref(value),c.sizeof(value),c.byref(length)) or \
            value.assigned!=value.count or value.count>32:
        raise RuntimeError('Complete bounded owned-job membership unavailable')
    result=[]
    for pid in value.pids[:value.count]:
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            result.append(dict(pid=pid,image=None,windows_error=c.get_last_error()));continue
        try:
            name=c.create_unicode_buffer(32768);size=w.DWORD(len(name))
            if not kernel.QueryFullProcessImageNameW(handle,0,name,c.byref(size)):raise c.WinError(c.get_last_error())
            result.append(dict(pid=pid,image=name.value))
        finally:kernel.CloseHandle(handle)
    return result


class CreationFailure(RuntimeError):
    def __init__(self,receipt):
        super().__init__('Owned suspended creation failed;inspect receipt');self.receipt=receipt


class SuspendedChild:
    @classmethod
    def create(cls,command,*,cwd=None,startupinfo=None,creationflags=0,close_fds=True):
        """Narrow no-pipe/no-inheritance launch, sufficient for native diagnostics."""
        kernel=kernel_api()
        if not isinstance(command,(list,tuple)) or not command or not all(isinstance(a,str) and '\0' not in a for a in command):
            raise ValueError('Explicit bounded argument vector required')
        image=Path(command[0]).resolve();line=subprocess.list2cmdline(command)
        if not image.is_relative_to(ROOT/'local') or not image.is_file() or len(line)>=32767:
            raise ValueError('Existing ignored owned image and bounded command required')
        if close_fds is not True or type(creationflags) is not int or creationflags & ~subprocess.CREATE_NO_WINDOW:
            raise ValueError('No inherited handles or unsupported creation flags')
        if cwd is not None:
            cwd=Path(cwd).resolve()
            if not cwd.is_relative_to(ROOT/'local') or not cwd.is_dir():raise ValueError('Owned existing cwd required')
        info=startupinfo.copy() if startupinfo is not None else subprocess.STARTUPINFO()
        if info.lpAttributeList not in (None,{}, {'handle_list':[]}) or info.dwFlags & subprocess.STARTF_USESTDHANDLES:
            raise ValueError('Diagnostic launch does not support inherited standard/attribute handles')
        import _winapi
        self=cls();self.kernel=kernel;self.handle=None;self.thread=None;self.job=None
        self.returncode=None;self.resumed=False;self.process=self
        self.receipt=dict(forced_cleanup=False,owned_process_reaped=False,primary_thread_resumed=False,
                          create_before_tick=kernel.GetTickCount64())
        hp,ht,self.pid,self.tid=_winapi.CreateProcess(str(image),line,None,None,False,
            creationflags|4,None,str(cwd) if cwd else None,info)
        self.handle=hp;self.thread=ht
        self.receipt.update(pid=self.pid,tid=self.tid,create_suspended=True,create_return_tick=kernel.GetTickCount64())
        try:
            self.job=_WindowsJob(self.pid)
            self.receipt.update(job_assigned=job_accounting(self.job),job_assigned_tick=kernel.GetTickCount64())
            self._identity()
            return self
        except BaseException as error:
            self.receipt['creation_error']=repr(error)
            try:self.close()
            except BaseException as cleanup:self.receipt['cleanup_error']=repr(cleanup)
            raise CreationFailure(self.receipt) from error

    def _identity(self):
        if not self.thread or self.kernel.GetThreadId(self.thread)!=self.tid or self.kernel.GetProcessIdOfThread(self.thread)!=self.pid:
            raise RuntimeError('Owned primary-thread identity differs')

    def resume(self):
        if self.resumed or self.poll() is not None:raise RuntimeError('Owned primary thread unavailable')
        self._identity();before=self.kernel.GetTickCount64();count=self.kernel.ResumeThread(self.thread)
        self.receipt.update(resume_before_tick=before,resume_return_tick=self.kernel.GetTickCount64(),resume_previous_count=count)
        if count!=1:raise RuntimeError('Expected exactly one primary-thread suspension')
        self.resumed=True;self.receipt['primary_thread_resumed']=True
        self.kernel.CloseHandle(self.thread);self.thread=None

    def poll(self):
        if self.returncode is not None:return self.returncode
        if not self.handle:raise RuntimeError('Owned process handle closed')
        status=self.kernel.WaitForSingleObject(self.handle,0)
        if status==258:return None
        if status!=0:raise RuntimeError('Owned process wait failed')
        code=w.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle,c.byref(code)):raise c.WinError(c.get_last_error())
        self.returncode=code.value;self.receipt.update(owned_process_reaped=True,exit_code=code.value)
        return self.returncode

    def wait(self,timeout):
        if not isinstance(timeout,(int,float)) or not 0<=timeout<=300:raise ValueError('Bounded wait required')
        if self.poll() is not None:return self.returncode
        status=self.kernel.WaitForSingleObject(self.handle,int(timeout*1000))
        if status==258:raise subprocess.TimeoutExpired('owned suspended child',timeout)
        if status!=0:raise RuntimeError('Owned process wait failed')
        return self.poll()

    def terminate(self):
        if self.poll() is None:
            self.receipt['forced_cleanup']=True
            if not self.kernel.TerminateProcess(self.handle,1) and self.poll() is None:raise c.WinError(c.get_last_error())

    def close(self):
        if not self.handle:return
        try:
            if self.job:
                before=job_accounting(self.job);self.receipt['job_before_close']=before
                if before['active_processes']:
                    self.receipt['forced_cleanup']=True
                    if not self.kernel.TerminateJobObject(self.job.handle,1):raise c.WinError(c.get_last_error())
            else:self.terminate()
            self.wait(15)
            if self.job:
                deadline=time.monotonic()+5
                while job_accounting(self.job)['active_processes'] and time.monotonic()<deadline:time.sleep(.02)
                self.receipt['job_final']=job_accounting(self.job)
                if self.receipt['job_final']['active_processes']:raise RuntimeError('Owned job still has active processes')
        finally:
            try:
                if self.job:self.job.close()
            finally:
                try:
                    if self.thread:self.kernel.CloseHandle(self.thread);self.thread=None
                finally:self.kernel.CloseHandle(self.handle);self.handle=None

    def __enter__(self):return self
    def __exit__(self,*unused):self.close()
