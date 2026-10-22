"""Opt-in unresolved-relative-root metadata;retain every legacy source profile.

Entry metadata only,not file contents,handle queries or successful-I/O evidence.
Unknown roots still increment the original counter and prevent absence claims.
"""
from __future__ import annotations
from tools.frida_attribution_clock import build_source as clock_source,control_request as clock_request,replace_once

PROFILE='paths-v3'


def build_source(config):
    source=clock_source(config,include_kernel32=True)
    source=replace_once(source,'function objectPath(p) {','function objectPath(p,context,key,operation) {')
    source=replace_once(source,'if(!parent){unknownRelativeRoots++;return null;}',
        "if(!parent){unknownRelativeRoots++;emit('unresolved-file-root',{api:key,operation,phase:'entry',rootHandle:root.toString(),relativePath:path,frames:frames(context)});return null;}")
    source=replace_once(source,'this.object=objectPath(args[2]);','this.object=objectPath(args[2],this.context,key,name);')
    return replace_once(source,'const file=objectPath(args[0]);','const file=objectPath(args[0],this.context,key,name);')


# Authored positive control: deliberately duplicate a directory handle through
# an API outside this sensor. A subsequent relative NtOpenFile must be reported
# unresolved,not silently treated as a known absolute path. No payload is read.
ROOT_CONTROL=r'''import ctypes
from ctypes import wintypes as w
class US(ctypes.Structure):
 _fields_=[('length',w.USHORT),('maximum',w.USHORT),('buffer',w.LPWSTR)]
class OA(ctypes.Structure):
 _fields_=[('length',w.ULONG),('root',w.HANDLE),('name',ctypes.POINTER(US)),('attributes',w.ULONG),('security',w.LPVOID),('qos',w.LPVOID)]
class IOSB(ctypes.Structure):
 _fields_=[('status',w.LPVOID),('information',ctypes.c_size_t)]
k=ctypes.WinDLL('kernel32',use_last_error=True);nt=ctypes.WinDLL('ntdll')
k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE];k.CreateFileW.restype=w.HANDLE
k.GetCurrentProcess.restype=w.HANDLE
k.DuplicateHandle.argtypes=[w.HANDLE,w.HANDLE,w.HANDLE,ctypes.POINTER(w.HANDLE),w.DWORD,w.BOOL,w.DWORD];k.DuplicateHandle.restype=w.BOOL
k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
nt.NtOpenFile.argtypes=[ctypes.POINTER(w.HANDLE),w.DWORD,ctypes.POINTER(OA),ctypes.POINTER(IOSB),w.ULONG,w.ULONG];nt.NtOpenFile.restype=w.LONG
assert (ctypes.sizeof(US),ctypes.sizeof(OA),ctypes.sizeof(IOSB))==(16,48,16)
directory=k.CreateFileW(str(queue),1,7,None,3,0x02000000,None)
assert directory not in (None,ctypes.c_void_p(-1).value)
alias=w.HANDLE();opened=w.HANDLE()
try:
 current=k.GetCurrentProcess();assert k.DuplicateHandle(current,directory,current,ctypes.byref(alias),0,False,2)
 text=ctypes.create_unicode_buffer('queued.json');name=US(22,24,ctypes.cast(text,w.LPWSTR))
 attrs=OA(ctypes.sizeof(OA),alias,ctypes.pointer(name),0x40,None,None);iosb=IOSB()
 status=nt.NtOpenFile(ctypes.byref(opened),0x100001,ctypes.byref(attrs),ctypes.byref(iosb),7,0x60)
 assert status==0 and opened.value
 unresolvedRootControl=dict(relativePath='queued.json',rootHandle=hex(alias.value),ntStatus=status)
finally:
 for handle in (opened.value,alias.value,directory):
  if handle:assert k.CloseHandle(handle)
'''


def control_request(image,folder,run_id):
    config,request=clock_request(image,folder,run_id,include_kernel32=True)
    code=replace_once(request['argv'][3],'temp=queue/"owned.tmp";',ROOT_CONTROL+'temp=queue/"owned.tmp";')
    request['argv'][3]=replace_once(code,'receipt["clockTicks"]=clockTicks',
                                  'receipt["unresolvedRootControl"]=unresolvedRootControl\nreceipt["clockTicks"]=clockTicks')
    return config,request
