"""Prepare the authored REA call-counter source; never launch or attach a process.

This network positive-control generator intentionally configures no native RVA
hooks. Game entry candidates remain separately reviewed and unqualified.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path,PureWindowsPath
import re
import secrets

TEMPLATE = r'''// Passive call counters only. No NativeFunction, arguments, payload reads,
// return-value changes, replacements, or game API activation.
'use strict';
const config = __CONFIG__;
if (Process.arch !== 'x64' || Process.pointerSize !== 8 ||
    Process.mainModule.path.toLowerCase() !== config.image.toLowerCase())
  throw new Error('Selected image/architecture mismatch');
const counts = {}, installed = [], errors = [], seen = new Set(), loaded = [];
const started = Date.now();
function snapshot(kind) {
  send({schema: 1, kind, pid: Process.id, elapsedMs: Date.now()-started,
    counts: Object.assign({},counts), installed: installed.slice(),
    loaded: loaded.slice(), errors: errors.slice()});
}
function hook(module, name, address, guard) {
  const key=module.name.toLowerCase()+':'+name;
  if (guard) {
    const actual=Array.from(new Uint8Array(address.readByteArray(guard.length/2)))
      .map(x=>x.toString(16).padStart(2,'0')).join('');
    if(actual!==guard)throw new Error('Loaded native guard differs: '+key);
  }
  if(seen.has(address.toString())) {installed.push({key,alias:true});return;}
  const handle=Interceptor.attach(address,{
    onEnter() {
      counts[key]=(counts[key]||0)+1;
      if(counts[key]===1) snapshot('first-call:'+key);
      if (name==='RGameSingleton.OnDestroy' || name==='RtlExitUserProcess') snapshot('lifecycle-enter:'+name);
    }
  });
  seen.add(address.toString());
  counts[key]=0;installed.push({key,offset:address.sub(module.base).toString()});
}
const api={
  'ws2_32.dll':['connect','WSAConnect','WSAConnectByNameW','WSAConnectByNameA',
    'send','sendto','WSASend','WSASendTo','recv','recvfrom','WSARecv','WSARecvFrom',
    'getaddrinfo','GetAddrInfoW','GetAddrInfoExW'],
  'winhttp.dll':['WinHttpConnect','WinHttpSendRequest'],
  'wininet.dll':['InternetConnectW','InternetConnectA','HttpSendRequestW','HttpSendRequestA',
    'HttpSendRequestExW','HttpSendRequestExA','InternetOpenUrlW','InternetOpenUrlA'],
  'dnsapi.dll':['DnsQuery_W','DnsQuery_A','DnsQueryEx'],
  'kernelbase.dll':['CreateProcessW','CreateProcessA'],
  'advapi32.dll':['CreateProcessAsUserW','CreateProcessAsUserA'],
  'ntdll.dll':['RtlExitUserProcess']
};
const observer=Process.attachModuleObserver({
  onAdded(module) {
    const lower=module.name.toLowerCase();
    if(!api[lower] && !config.native[lower])return;
    loaded.push(lower);
    try {
      for(const name of api[lower]||[]) {
        const address=module.findExportByName(name);
        if(!address)throw new Error('Loaded API export missing: '+lower+':'+name);
        hook(module,name,address,null);
      }
      const native=config.native[lower];
      if(native) {
        if(module.path.toLowerCase()!==native.path.toLowerCase())throw new Error('Native module path differs: '+lower);
        for(const entry of native.entries)hook(module,entry.name,module.base.add(entry.rva),entry.guard);
      }
    } catch(error) {errors.push(String(error));}
    snapshot('module-hooks-ready:'+lower);
  }
});
snapshot('observer-ready');
setInterval(()=>snapshot('heartbeat'),5000);
'''


def build_source(image):
    if not isinstance(image,str) or not PureWindowsPath(image).is_absolute() or any(ord(c)<32 for c in image):
        raise ValueError('An absolute Windows image path without control characters is required.')
    return TEMPLATE.replace('__CONFIG__',json.dumps(dict(image=str(PureWindowsPath(image)),native={})))


def build_request(image, folder, run_id):
    """Describe one bounded loopback exchange; argv omits the executable itself."""
    build_source(image)  # Same image/path validation as the observer.
    build_source(folder)
    if not isinstance(run_id,str) or not re.fullmatch('[0-9a-f]{32}',run_id):
        raise ValueError('A lowercase 32-hex run ID is required.')
    folder=str(PureWindowsPath(folder));image=str(PureWindowsPath(image))
    program=('import json,os,pathlib,socket,time\nroot=pathlib.Path('+repr(folder)+')\n'+
        'with socket.socket() as listener:\n'
        ' listener.settimeout(3);listener.bind(("127.0.0.1",0));listener.listen(1)\n'
        ' with socket.socket() as client:\n'
        '  client.settimeout(3);client.connect(listener.getsockname())\n'
        '  peer,_=listener.accept()\n'
        '  with peer:\n'
        '   peer.settimeout(3);client.sendall(b"BA43");assert peer.recv(4)==b"BA43"\n'
        '   peer.sendall(b"OK");assert client.recv(2)==b"OK"\n'
        'with (root/"network-positive.json").open("x") as target:\n'
        ' target.write(json.dumps(dict(schema=1,pid=os.getpid(),run_id='+repr(run_id)+
        ',passed=True,bytes_sent=4,bytes_received=2))+"\\n")\ntime.sleep(2)\n')
    return dict(mode='spawn',device_id='local',program=image,argv=['-I','-B','-c',program],
                source_kind='file',path=str(PureWindowsPath(folder)/'observer.js'),duration_ms=10000)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    destination=parser.add_mutually_exclusive_group(required=True)
    destination.add_argument('--output',type=Path)
    destination.add_argument('--control-dir',type=Path,help='prepare a fresh ignored local request/script/identity manifest, without executing it')
    args=parser.parse_args()
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream:stream.write(build_source(args.image))
        return
    root=Path(__file__).resolve().parents[1];folder=args.control_dir.resolve();image=Path(args.image).resolve()
    if not folder.is_relative_to(root/'local') or not image.is_file():
        raise ValueError('Existing selected runtime and fresh ignored local control directory required.')
    run_id=secrets.token_hex(16);request=build_request(str(image),str(folder),run_id)
    folder.mkdir(parents=True,exist_ok=False)
    with (folder/'observer.js').open('x',encoding='utf-8') as stream:stream.write(build_source(str(image)))
    (folder/'request.json').write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8')
    identity=dict(schema=1,run_id=run_id,target_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256((folder/'observer.js').read_bytes()).hexdigest())
    (folder/'inputs.json').write_text(json.dumps(identity,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(identity))


if __name__=='__main__':main()
