"""Read directory metadata from an already owned x64 suspended child.

No PID selection/enumeration,remote code,privilege change or target API call.
The owner queries its existing process handle,reads bounded metadata and checks
the directory handle through a duplicate in the owner. Diagnostic only.
"""
import ctypes as c
from ctypes import wintypes as w
from pathlib import PureWindowsPath
import struct
from tools.owned_suspended_launch import SuspendedChild


def snapshot(child,*,allow_uninitialized=False):
    if type(allow_uninitialized) is not bool:raise ValueError('Explicit initialization policy required')
    if type(child) is not SuspendedChild or not child.handle or not child.job or child.poll() is not None:
        raise ValueError('Existing owned live diagnostic child required')
    kernel=c.WinDLL('kernel32',use_last_error=True);native=c.WinDLL('ntdll')
    kernel.GetProcessId.argtypes=[w.HANDLE];kernel.GetProcessId.restype=w.DWORD
    kernel.ReadProcessMemory.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)];kernel.ReadProcessMemory.restype=w.BOOL
    kernel.GetCurrentProcess.restype=w.HANDLE
    kernel.DuplicateHandle.argtypes=[w.HANDLE,w.HANDLE,w.HANDLE,c.POINTER(w.HANDLE),w.DWORD,w.BOOL,w.DWORD];kernel.DuplicateHandle.restype=w.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes=[w.HANDLE,w.LPWSTR,w.DWORD,w.DWORD];kernel.GetFinalPathNameByHandleW.restype=w.DWORD
    kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
    native.NtQueryInformationProcess.argtypes=[w.HANDLE,w.ULONG,c.c_void_p,w.ULONG,c.POINTER(w.ULONG)];native.NtQueryInformationProcess.restype=w.LONG
    if kernel.GetProcessId(child.handle)!=child.pid:raise ValueError('Owned process handle identity differs')
    def read(address,length):
        if not 0<address<2**63 or not 0<length<=32768:raise ValueError('Bounded metadata read required')
        buffer=c.create_string_buffer(length);size=c.c_size_t()
        if not kernel.ReadProcessMemory(child.handle,address,buffer,length,c.byref(size)) or size.value!=length:
            raise RuntimeError('Owned metadata read failed')
        return buffer.raw
    basic=c.create_string_buffer(48);length=w.ULONG()
    status=native.NtQueryInformationProcess(child.handle,0,basic,len(basic),c.byref(length))
    if status or length.value!=48 or struct.unpack_from('<Q',basic.raw,32)[0]!=child.pid:
        raise RuntimeError('Owned x64 process information differs')
    peb=struct.unpack_from('<Q',basic.raw,8)[0];parameters=struct.unpack('<Q',read(peb+0x20,8))[0]
    header=read(parameters+0x38,24);size,maximum=struct.unpack_from('<HH',header)
    buffer,handle=struct.unpack_from('<QQ',header,8)
    if not 0<size<=maximum<=32768 or size%2:
        raise RuntimeError(f'Current directory layout differs:size={size},maximum={maximum},handle={hex(handle)}')
    path=read(buffer,size).decode('utf-16-le')
    if not PureWindowsPath(path).is_absolute() or '\0' in path:raise RuntimeError('Absolute directory metadata required')
    if not handle:
        if not allow_uninitialized:raise RuntimeError('Current directory handle not initialized')
        return dict(schema=1,pid=child.pid,pebAddress=hex(peb),parametersAddress=hex(parameters),
                    rootHandle='0x0',rootPath=path,handleFinalPath=None,viewsAgree=False)
    duplicate=w.HANDLE()
    if not kernel.DuplicateHandle(child.handle,handle,kernel.GetCurrentProcess(),c.byref(duplicate),0,False,2):
        raise RuntimeError('Owned directory handle duplication failed')
    try:
        name=c.create_unicode_buffer(32768);count=kernel.GetFinalPathNameByHandleW(duplicate,name,len(name),0)
        if not 0<count<len(name):raise RuntimeError('Owned directory handle path unavailable')
        final=name.value
    finally:kernel.CloseHandle(duplicate)
    def normalized(value):return str(PureWindowsPath(value.removeprefix('\\\\?\\'))).casefold()
    if normalized(path)!=normalized(final):raise RuntimeError('Directory string/handle disagree')
    if read(parameters+0x38,24)!=header or struct.unpack('<Q',read(peb+0x20,8))[0]!=parameters:
        raise RuntimeError('Directory metadata changed during observation')
    return dict(schema=1,pid=child.pid,pebAddress=hex(peb),parametersAddress=hex(parameters),
                rootHandle=hex(handle),rootPath=path,handleFinalPath=final,viewsAgree=True)
