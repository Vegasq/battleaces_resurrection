"""Prepare a passive Windows x64 file/network/process observer and owned control.

Never launch, attach or change a target here. Records metadata, not file/socket
payloads, headers, command lines or credentials. This is a bounded API observer,
not kernel capture, descendant instrumentation or a complete privacy proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import secrets

API = {
    'ntdll.dll': ['NtCreateFile', 'NtOpenFile', 'NtReadFile', 'NtWriteFile',
                  'NtSetInformationFile', 'NtDeleteFile', 'NtClose', 'RtlExitUserProcess'],
    'ws2_32.dll': ['connect', 'WSAConnect', 'send', 'recv', 'sendto', 'WSASendTo',
                   'getaddrinfo', 'GetAddrInfoW', 'GetAddrInfoExW'],
    'kernelbase.dll': ['CreateProcessW', 'CreateProcessA'],
    'advapi32.dll': ['CreateProcessAsUserW', 'CreateProcessAsUserA'],
    'winhttp.dll': ['WinHttpConnect'],
    'wininet.dll': ['InternetConnectW', 'InternetConnectA'],
}

TEMPLATE = r'''// Metadata only; no NativeFunction, replacements, return/argument writes,
// game API calls, payload/command-line/header/environment reads, or file writes.
'use strict';
const config=__CONFIG__, api=__API__;
if(Process.arch!=='x64' || Process.pointerSize!==8 ||
   Process.mainModule.path.toLowerCase()!==config.image.toLowerCase())throw new Error('selected image/architecture differs');
const started=Date.now(), installed=[], errors=[], addresses=new Map(), files=new Map(), counts={};
let sequence=0, overflow=false, unknownRelativeRoots=0;
function emit(kind,data) {
  if(overflow)return;
  if(sequence>=config.eventLimit) {overflow=true;kind='budget-exceeded';data={};}
  send({schema:1,seq:++sequence,runId:config.runId,pid:Process.id,tid:Process.getCurrentThreadId(),
        elapsedMs:Date.now()-started,kind,data});
}
function text(p,wide) {
  if(p.isNull())return null;
  let result='';for(let i=0;i<256;i++){const unit=wide?p.add(2*i).readU16():p.add(i).readU8();if(!unit)return result;result+=String.fromCharCode(unit);}
  throw new Error('unterminated bounded name');
}
function normalize(path) {
  if(path.startsWith('\\??\\'))path=path.slice(4);
  if(path.startsWith('\\\\?\\'))path=path.slice(4);
  return path.replace(/\//g,'\\').toLowerCase();
}
function relevant(path) {
  const lower=normalize(path);
  return config.fileRoots.some(root=>lower===normalize(root) || lower.startsWith(normalize(root)+'\\'));
}
function objectPath(p) {
  if(p.isNull() || p.readU32()!==48)throw new Error('OBJECT_ATTRIBUTES layout differs');
  const root=p.add(8).readPointer(),name=p.add(16).readPointer();
  if(name.isNull())return null;
  const length=name.readU16(),maximum=name.add(2).readU16();
  if(length>maximum || length>8192 || length%2)throw new Error('UNICODE_STRING length invalid');
  const buffer=name.add(8).readPointer();
  let path=length?buffer.readUtf16String(length/2):'';
  if(!root.isNull() && !path.startsWith('\\')) {
    const parent=files.get(root.toString());
    if(!parent){unknownRelativeRoots++;return null;}
    path=parent.path+'\\'+path;
  }
  return {path,tracked:relevant(path)};
}
function frames(context) {
  return Thread.backtrace(context,Backtracer.ACCURATE).slice(0,8).map(address=>{
    const module=Process.findModuleByAddress(address);
    return module?{module:module.name.toLowerCase(),rva:address.sub(module.base).toString()}:{module:null,rva:null};
  });
}
function endpoint(p,length) {
  if(p.isNull() || length<4)throw new Error('sockaddr missing');
  const family=p.readU16(),port=p.add(2).readU8()*256+p.add(3).readU8();
  if(family===2 && length>=16) {
    const a=Array.from(new Uint8Array(p.add(4).readByteArray(4)));
    return {family:4,address:a.join('.'),port};
  }
  if(family===23 && length>=28) {
    const a=Array.from(new Uint8Array(p.add(8).readByteArray(16))),parts=[];
    for(let i=0;i<16;i+=2)parts.push((a[i]*256+a[i+1]).toString(16));
    return {family:6,address:parts.join(':'),port};
  }
  return {family,address:null,port:null,unsupported:true};
}
function hook(module,name,address) {
  const key=module.name.toLowerCase()+':'+name;
  if(addresses.has(address.toString())) {
    const original=addresses.get(address.toString());
    if(original.name!==name)throw new Error('different ABI aliases same address');
    installed.push({key,aliasOf:original.key});return;
  }
  const callbacks={
    onEnter(args) {
      counts[key]++;
      this.record=null;
      try {
        if(name==='NtCreateFile' || name==='NtOpenFile') {
          this.out=args[0];this.object=objectPath(args[2]);
          if(this.object && this.object.tracked)this.record={operation:name,path:this.object.path,
            access:args[1].toUInt32(),disposition:name==='NtCreateFile'?args[7].toUInt32():null,
            options:args[name==='NtCreateFile'?8:5].toUInt32(),frames:frames(this.context)};
        } else if(['NtReadFile','NtWriteFile','NtSetInformationFile','NtClose'].includes(name)) {
          this.handle=args[0].toString();const file=files.get(this.handle);
          if(file && file.tracked && name!=='NtClose')this.record={operation:name,path:file.path,
            requestedBytes:name==='NtSetInformationFile'?null:args[6].toUInt32(),
            informationClass:name==='NtSetInformationFile'?args[4].toUInt32():null,frames:frames(this.context)};
        } else if(name==='NtDeleteFile') {
          const file=objectPath(args[0]);if(file && file.tracked)this.record={operation:name,path:file.path,frames:frames(this.context)};
        } else if(name==='connect' || name==='WSAConnect' || name==='sendto' || name==='WSASendTo') {
          const ai=name==='sendto'?4:name==='WSASendTo'?5:1;
          this.record={operation:name,endpoint:endpoint(args[ai],args[ai+1].toInt32()),frames:frames(this.context)};
        } else if(['getaddrinfo','GetAddrInfoW','GetAddrInfoExW'].includes(name)) {
          this.record={operation:name,node:text(args[0],name!=='getaddrinfo'),service:text(args[1],name!=='getaddrinfo'),frames:frames(this.context)};
        } else if(['WinHttpConnect','InternetConnectW','InternetConnectA'].includes(name)) {
          this.record={operation:name,node:text(args[1],name!=='InternetConnectA'),port:args[2].toUInt32(),frames:frames(this.context)};
        } else if(name.startsWith('CreateProcess')) {
          const user=name.startsWith('CreateProcessAsUser');this.processInfo=args[user?10:9];
          this.record={operation:name,application:text(args[user?1:0],name.endsWith('W')),frames:frames(this.context)};
        } else if(name==='RtlExitUserProcess') {
          emit('process-exit-entry',{exitStatus:args[0].toUInt32(),counts,installed:installed.slice(),
            errors:errors.slice(),unknownRelativeRoots,overflow});
        }
      }catch(error){errors.push(key+': '+String(error));emit('decode-error',{api:key});}
    },
    onLeave(value) {
      try {
        const status=value.toInt32();
        if(this.object && (name==='NtCreateFile' || name==='NtOpenFile') && status>=0 && status!==0x103) {
          if(files.size>=4096)throw new Error('handle map budget exceeded');
          files.set(this.out.readPointer().toString(),this.object);
        }
        if(name==='NtClose' && status>=0 && this.handle)files.delete(this.handle);
        if(this.record) {
          this.record.api=key;this.record.returnValue=status;
          this.record.pending=status===0x103;
          if(name.startsWith('CreateProcess') && status!==0)this.record.childPid=this.processInfo.add(16).readU32();
          emit(name.startsWith('Nt')?'file-operation':name.startsWith('CreateProcess')?'process-create':'network-operation',this.record);
        }
      }catch(error){errors.push(key+': '+String(error));emit('decode-error',{api:key});}
    }
  };
  Interceptor.attach(address,callbacks);counts[key]=0;addresses.set(address.toString(),{key,name});installed.push({key});
}
Process.attachModuleObserver({onAdded(module){
  const lower=module.name.toLowerCase();if(!api[lower])return;
  try{for(const name of api[lower]){const address=module.findExportByName(name);if(!address)throw new Error('missing export '+name);hook(module,name,address);}}
  catch(error){errors.push(lower+': '+String(error));}
  emit('module-ready',{module:lower,path:module.path,installed:installed.slice(),errors:errors.slice()});
}});
emit('observer-ready',{installed:installed.slice(),errors:errors.slice()});
setInterval(()=>emit('heartbeat',{counts,installed:installed.slice(),errors:errors.slice(),unknownRelativeRoots,overflow}),5000);
'''


def validate_config(config):
    if not isinstance(config,dict) or set(config) != {'image', 'runId', 'fileRoots', 'eventLimit'}:
        raise ValueError('Observer configuration keys differ')
    if not isinstance(config['fileRoots'],list) or not 1<=len(config['fileRoots'])<=8:
        raise ValueError('One to eight selected file roots required')
    for name in (config['image'], *config['fileRoots']):
        if not isinstance(name,str) or not PureWindowsPath(name).is_absolute() or any(ord(c)<32 for c in name):
            raise ValueError('Absolute Windows paths without control characters required')
    if (any(PureWindowsPath(p)==PureWindowsPath(p).parent for p in config['fileRoots'])
            or not isinstance(config['runId'],str) or not re.fullmatch('[0-9a-f]{32}',config['runId'])
            or type(config['eventLimit']) is not int or not 100<=config['eventLimit']<=4096):
        raise ValueError('Bounded selected roots,run nonce and event limit required')


def build_source(config):
    validate_config(config)
    return TEMPLATE.replace('__CONFIG__',json.dumps(config)).replace('__API__',json.dumps(API))


def control_request(image, folder, run_id):
    config=dict(image=str(PureWindowsPath(image)),runId=run_id,
                fileRoots=[str(PureWindowsPath(folder)/'queue')],eventLimit=1000)
    build_source(config)
    code=('import hashlib,json,os,pathlib,socket,subprocess,sys,time\n'
          'root=pathlib.Path('+repr(str(PureWindowsPath(folder)))+')\n'
          'queue=root/"queue";old=queue/"queued.json"\n'
          'assert old.read_bytes()==b"authored queued report; never delivered\\n"\n'
          'temp=queue/"owned.tmp";temp.write_bytes(b"owned107");assert temp.read_bytes()==b"owned107"\n'
          'os.replace(temp,queue/"published.bin");(queue/"published.bin").unlink()\n'
          'with socket.socket() as listener:\n'
          ' listener.settimeout(3);listener.bind(("127.0.0.1",0));listener.listen(1);port=listener.getsockname()[1]\n'
          ' resolved=socket.getaddrinfo("localhost",port)\n'
          ' with socket.socket() as client:\n'
          '  client.settimeout(3);client.connect(("127.0.0.1",port));peer,_=listener.accept()\n'
          '  with peer:\n'
          '   peer.settimeout(3);client.sendall(b"BA107");assert peer.recv(5)==b"BA107"\n'
          '   peer.sendall(b"OK");assert client.recv(2)==b"OK"\n'
          'child=subprocess.Popen([sys.executable,"-I","-B","-c","pass"]);assert child.wait(timeout=3)==0\n'
          'assert old.read_bytes()==b"authored queued report; never delivered\\n"\n'
          'receipt=dict(schema=1,pid=os.getpid(),runId='+repr(run_id)+',port=port,childPid=child.pid,childExit=0,bytesSent=7,bytesReceived=7,queueUnchanged=True)\n'
          'with (root/"positive.json").open("x") as stream:stream.write(json.dumps(receipt)+"\\n")\n'
          'time.sleep(7)\n')
    return config,dict(mode='spawn',device_id='local',program=config['image'],argv=['-I','-B','-c',code],
                       source_kind='file',path=str(PureWindowsPath(folder)/'observer.js'),duration_ms=10000)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--control-dir',type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    folder=args.control_dir.resolve();image=args.image.resolve()
    if not folder.is_relative_to(root/'local') or not image.is_file():
        raise ValueError('Existing selected runtime and new ignored local folder required')
    run=secrets.token_hex(16);config,request=control_request(str(image),str(folder),run)
    folder.mkdir(parents=True,exist_ok=False);(folder/'queue').mkdir()
    (folder/'queue/queued.json').write_bytes(b'authored queued report; never delivered\n')
    source=build_source(config).encode('utf-8');(folder/'observer.js').write_bytes(source)
    (folder/'request.json').write_text(json.dumps(request,indent=2)+'\n')
    inputs=dict(schema=1,config=config,request=request,target_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                source_sha256=hashlib.sha256(source).hexdigest())
    (folder/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    print(json.dumps(dict(prepared=True,runId=run,source_sha256=inputs['source_sha256'])))


if __name__=='__main__':main()
