"""Passive clock-return anchors for the bounded metadata observer.

Never invoke a target API here. The added hook observes existing GetTickCount64
returns only. Legacy source/control remain byte-for-byte selectable separately.
Game observations select include_kernel32=True;v1 qualifies only kernelbase.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import secrets
from tools import frida_attribution_source as legacy

CLOCK_KEY='kernelbase.dll:GetTickCount64'
PROFILE='clocked-v1'
CLOCK_KEY_KERNEL32='kernel32.dll:GetTickCount64'
PROFILE_KERNEL32='clocked-v2'


def replace_once(source, old, new):
    if source.count(old)!=1:raise ValueError('Metadata observer template changed')
    return source.replace(old,new)


def build_source(config,*,include_kernel32=False):
    if type(include_kernel32) is not bool:raise ValueError('Explicit clock export selection required')
    source=legacy.build_source(config)
    api={module:list(names) for module,names in legacy.API.items()}
    api['kernelbase.dll'].append('GetTickCount64')
    if include_kernel32:api['kernel32.dll']=['GetTickCount64']
    source=replace_once(source,', api='+json.dumps(legacy.API)+';',', api='+json.dumps(api)+';')
    source=replace_once(source,'let sequence=0, overflow=false, unknownRelativeRoots=0;',
                       'let sequence=0, overflow=false, unknownRelativeRoots=0, lastClock=-250, clockReady=false;')
    source=replace_once(source,"emit('observer-ready',{installed:installed.slice(),errors:errors.slice()});",
                        "clockReady=true;emit('observer-ready',{installed:installed.slice(),errors:errors.slice()});")
    return replace_once(source,'        const status=value.toInt32();', '''        if(name==='GetTickCount64') {
          if(!clockReady)return;
          const tickMs=Number(value.toString()), elapsed=Date.now()-started;
          if(!Number.isSafeInteger(tickMs) || tickMs<0)throw new Error('invalid native clock return');
          if(elapsed-lastClock>=250){lastClock=elapsed;emit('clock-anchor',{tickMs});}
          return;
        }
        const status=value.toInt32();''')


def control_request(image,folder,run_id,*,include_kernel32=False):
    if type(include_kernel32) is not bool:raise ValueError('Explicit clock export selection required')
    config,request=legacy.control_request(image,folder,run_id)
    code=request['argv'][3]
    clock='''import ctypes
clock=ctypes.WinDLL('kernelbase',use_last_error=True).GetTickCount64
clock.restype=ctypes.c_ulonglong
clockTicks=[]
for _ in range(8):
 time.sleep(.3);clockTicks.append(clock())
'''
    code=replace_once(code,'receipt=dict(schema=1',clock+'receipt=dict(schema=1')
    code=replace_once(code,'with (root/"positive.json").open',
                      'receipt["clockTicks"]=clockTicks\nwith (root/"positive.json").open')
    code=replace_once(code,'time.sleep(7)\n','time.sleep(4.6)\n')
    if include_kernel32:
        code=replace_once(code,"clock=ctypes.WinDLL('kernelbase',use_last_error=True).GetTickCount64\nclock.restype=ctypes.c_ulonglong",
                          "clocks=[]\nfor module in ('kernelbase','kernel32'):\n clock=ctypes.WinDLL(module,use_last_error=True).GetTickCount64\n clock.restype=ctypes.c_ulonglong;clocks.append(clock)")
        code=replace_once(code,'time.sleep(.3);clockTicks.append(clock())','time.sleep(.3);clockTicks.append(clocks[_%2]())')
        code=replace_once(code,'receipt["clockTicks"]=clockTicks',
                          'receipt["clockTicks"]=clockTicks\nreceipt["clockModules"]=["kernelbase.dll","kernel32.dll"]*4')
    request['argv'][3]=code
    return config,request


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--control-dir',type=Path,required=True)
    parser.add_argument('--include-kernel32',action='store_true',help='qualify both Windows clock exports using alternating control calls')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    image=args.image.resolve();folder=args.control_dir.resolve()
    if not image.is_file() or not folder.is_relative_to(root/'local'):
        raise ValueError('Existing selected runtime and fresh ignored local folder required')
    config,request=control_request(str(PureWindowsPath(image)),str(PureWindowsPath(folder)),secrets.token_hex(16),include_kernel32=args.include_kernel32)
    folder.mkdir(parents=True,exist_ok=False);(folder/'queue').mkdir()
    (folder/'queue/queued.json').write_bytes(b'authored queued report; never delivered\n')
    source=build_source(config,include_kernel32=args.include_kernel32).encode();(folder/'observer.js').write_bytes(source)
    (folder/'request.json').write_text(json.dumps(request,indent=2)+'\n')
    inputs=dict(schema=1,observer_profile=PROFILE_KERNEL32 if args.include_kernel32 else PROFILE,config=config,request=request,
                target_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),source_sha256=hashlib.sha256(source).hexdigest())
    (folder/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    print(json.dumps(dict(prepared=True,observer_profile=inputs['observer_profile'],source_sha256=inputs['source_sha256'])))


if __name__=='__main__':main()
