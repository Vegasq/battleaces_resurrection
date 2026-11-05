"""Prepare an owned pre-attach file-handle read positive control."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

from tools.frida_preexisting_file_source372 import build_source

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''import ctypes,json,os,pathlib,time
from ctypes import wintypes
folder=pathlib.Path(__file__).resolve().parent
file=folder/'queue'/'owned.txt'
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
    ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
k.CreateFileW.restype=wintypes.HANDLE
k.ReadFile.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
k.CloseHandle.argtypes=[wintypes.HANDLE]
k.GetCurrentProcess.restype=wintypes.HANDLE
k.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
handle=k.CreateFileW(str(file),0x80000000,7,None,3,0,None)
assert handle not in (None,0,ctypes.c_void_p(-1).value),ctypes.get_last_error()
(folder/'pid.json').write_text(json.dumps({'pid':os.getpid(),'file_handle':int(handle)})+'\n')
deadline=time.monotonic()+60
while not (folder/'observer-ready').exists() and time.monotonic()<deadline:time.sleep(0.05)
assert (folder/'observer-ready').read_bytes()==b'FRIDA_READY\n'
buffer=ctypes.create_string_buffer(64);read=wintypes.DWORD()
assert k.ReadFile(handle,buffer,64,ctypes.byref(read),None),ctypes.get_last_error()
assert buffer.raw[:read.value]==b'authored control\n'
assert k.CloseHandle(handle)
(folder/'positive.json').write_text(json.dumps({'pid':os.getpid(),
    'read_bytes':read.value,'authored_content_matched':True})+'\n')
k.TerminateProcess(k.GetCurrentProcess(),0)
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT / 'local') and not output.exists()
    output.mkdir(parents=True)
    (output / 'queue').mkdir()
    (output / 'queue/owned.txt').write_bytes(b'authored control\n')
    (output / 'probe.py').write_text(PROBE,encoding='utf-8')
    config = dict(image=str(Path(sys.executable).resolve()),runId=secrets.token_hex(16),
                  fileRoots=[str(output / 'queue')],eventLimit=1000)
    observer = output / 'observer.js'
    observer.write_text(build_source(config),encoding='utf-8')
    request = dict(mode='attach',program=config['image'],argv=['-B',str(output / 'probe.py')],
                   script=str(observer),config=config,
                   source_sha256=hashlib.sha256(observer.read_bytes()).hexdigest())
    (output / 'request.json').write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'prepared':True,'output':str(output)}))


if __name__ == '__main__':main()
