"""Prepare an owned relative NtCreateFile path-resolution control."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

from tools.frida_resolved_file_source371 import build_source

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''import ctypes,json,os,pathlib,time
from ctypes import wintypes
folder=pathlib.Path(__file__).resolve().parent
queue=folder/'queue'
k=ctypes.WinDLL('kernel32',use_last_error=True)
n=ctypes.WinDLL('ntdll')
k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
                         ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
k.CreateFileW.restype=wintypes.HANDLE
k.CloseHandle.argtypes=[wintypes.HANDLE]
k.GetCurrentProcess.restype=wintypes.HANDLE
k.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
class UnicodeString(ctypes.Structure):
    _fields_=[('Length',wintypes.USHORT),('MaximumLength',wintypes.USHORT),
              ('Buffer',ctypes.c_void_p)]
class ObjectAttributes(ctypes.Structure):
    _fields_=[('Length',wintypes.ULONG),('RootDirectory',wintypes.HANDLE),
              ('ObjectName',ctypes.POINTER(UnicodeString)),('Attributes',wintypes.ULONG),
              ('SecurityDescriptor',ctypes.c_void_p),('SecurityQualityOfService',ctypes.c_void_p)]
class IoStatusBlock(ctypes.Structure):
    _fields_=[('Status',ctypes.c_void_p),('Information',ctypes.c_void_p)]
n.NtCreateFile.argtypes=[ctypes.POINTER(wintypes.HANDLE),wintypes.DWORD,
    ctypes.POINTER(ObjectAttributes),ctypes.POINTER(IoStatusBlock),ctypes.c_void_p,
    wintypes.ULONG,wintypes.ULONG,wintypes.ULONG,wintypes.ULONG,ctypes.c_void_p,wintypes.ULONG]
n.NtCreateFile.restype=wintypes.LONG
root=k.CreateFileW(str(queue),0x80,7,None,3,0x02000000,None)
assert root not in (None,0,ctypes.c_void_p(-1).value),ctypes.get_last_error()
if (folder/'attach-mode').exists():
    (folder/'pid.json').write_text(json.dumps({'pid':os.getpid(),'root_handle':int(root)})+'\n')
    deadline=time.monotonic()+60
    while not (folder/'observer-ready').exists() and time.monotonic()<deadline:time.sleep(0.05)
    assert (folder/'observer-ready').read_bytes()==b'FRIDA_READY\n'
namebuf=ctypes.create_unicode_buffer('owned.txt')
name=UnicodeString(len('owned.txt')*2,(len('owned.txt')+1)*2,ctypes.cast(namebuf,ctypes.c_void_p).value)
attrs=ObjectAttributes(ctypes.sizeof(ObjectAttributes),root,ctypes.pointer(name),0,None,None)
status=IoStatusBlock();handle=wintypes.HANDLE()
result=n.NtCreateFile(ctypes.byref(handle),0x80|0x100000,ctypes.byref(attrs),
    ctypes.byref(status),None,0,7,1,0x40,None,0)
assert result==0,(result,ctypes.get_last_error())
assert k.CloseHandle(handle) and k.CloseHandle(root)
(folder/'positive.json').write_text(json.dumps({'pid':os.getpid(),
    'relative_open_status':result,'queue_file_untouched':(queue/'owned.txt').read_bytes()==b'authored control\n'})+'\n')
k.TerminateProcess(k.GetCurrentProcess(),0)
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--attach-gate', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT / 'local') and not output.exists()
    output.mkdir(parents=True)
    (output / 'queue').mkdir()
    (output / 'queue/owned.txt').write_bytes(b'authored control\n')
    if args.attach_gate:(output / 'attach-mode').write_bytes(b'1\n')
    (output / 'probe.py').write_text(PROBE, encoding='utf-8')
    config = dict(image=str(Path(sys.executable).resolve()),runId=secrets.token_hex(16),
                  fileRoots=[str(output / 'queue')],eventLimit=1000)
    observer = output / 'observer.js'
    observer.write_text(build_source(config),encoding='utf-8')
    request = dict(mode='spawn',program=config['image'],argv=['-B',str(output / 'probe.py')],
                   script=str(observer),config=config,
                   source_sha256=hashlib.sha256(observer.read_bytes()).hexdigest())
    (output / 'request.json').write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'prepared':True,'output':str(output)}))


if __name__ == '__main__':
    main()
