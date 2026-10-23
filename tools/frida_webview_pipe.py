"""Opt-in, value-redacted original pipe API metadata on the148 controlled replay.

Names are read transiently only at exact owned source callers. A per-run salted
digest supports cross-process equality without retaining the name. No security,
arguments, results, token or completion state is changed by this added probe.
The composed parent profile retains its explicit CREATE_SUSPENDED mutation.
"""
import json,re
from pathlib import PureWindowsPath
from tools.frida_webview_gate import build_source as gate_source
from tools.frida_webview_child import build_source as child_source

PROFILE='webview-pipe-v1'
PIPE=r'''const pipeWitness=__PIPE__;const pipeBindings=new Map(),pipeHandles=new Map(),pipeEvents=new Map(),pipeCounts={},pipeErrors=[];
const pipeNames=pipeWitness.role==='parent'?['CreateNamedPipeA','ConnectNamedPipe','WaitForSingleObject']:['CreateFileA'];
for(const n of pipeNames)pipeCounts[n]=0;
function pipeNameFacts(p) {
  if(p.isNull())throw new Error('pipe name absent');let name='';
  for(let i=0;i<256;i++){const v=p.add(i).readU8();if(!v)break;if(v>127)throw new Error('pipe name encoding differs');name+=String.fromCharCode(v);if(i===255)throw new Error('pipe name exceeds bound');}
  if(!/^\\\\\.\\pipe\\com\.vuplex\.webview\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(name))throw new Error('owned pipe prefix/UUID differs');
  return {nameLength:name.length,nameSha256:Checksum.compute('sha256',JSON.stringify([pipeWitness.nonce,name])),fixedPrefixMatched:true};
}
function pipeCaller(context,name) {
  const expected=pipeWitness.role==='child'?0x840e8:name==='CreateNamedPipeA'?0x1b6af:name==='ConnectNamedPipe'?0x1b73f:0x1b772;
  const fs=frames(context),base=pipeWitness.role==='parent'?'vuplexwebviewwindows.dll':'vuplex webview.vuplex';
  if(!fs.some(f=>f.module===base && f.rva==='0x'+expected.toString(16)))return null;
  const m=Process.findModuleByName(base);
  if(!m || m.path.toLowerCase()!==pipeWitness.module.toLowerCase() || Checksum.compute('sha256',m.base.add(pipeWitness.prefixRva).readByteArray(16))!==pipeWitness.sha256)throw new Error('owned pipe caller prefix differs');
  return fs;
}
function pipeAttach(module) {
  if(!['kernelbase.dll','kernel32.dll'].includes(module.name.toLowerCase()))return;
  for(const name of pipeNames) {
    const at=module.findExportByName(name);if(!at)continue;if(pipeBindings.has(at.toString()))continue;
    try{Interceptor.attach(at,{
      onEnter(args){
        this.pipeRecord=null;
        try{
          const fs=pipeCaller(this.context,name);if(!fs)return;
          let data={api:module.name.toLowerCase()+':'+name,operation:name,frames:fs};
          if(name==='CreateNamedPipeA')Object.assign(data,pipeNameFacts(args[0]),{openMode:args[1].toUInt32(),pipeMode:args[2].toUInt32(),maxInstances:args[3].toUInt32(),outBuffer:args[4].toUInt32(),inBuffer:args[5].toUInt32(),defaultTimeout:args[6].toUInt32(),securityAttributesNull:args[7].isNull()});
          else if(name==='CreateFileA')Object.assign(data,pipeNameFacts(args[0]),{desiredAccess:args[1].toUInt32(),shareMode:args[2].toUInt32(),securityAttributesNull:args[3].isNull(),creationDisposition:args[4].toUInt32(),flags:args[5].toUInt32(),templateHandleNull:args[6].isNull()});
          else if(name==='ConnectNamedPipe'){
            const facts=pipeHandles.get(args[0].toString());if(!facts)throw new Error('unobserved owned pipe handle');
            Object.assign(data,facts,{overlappedNull:args[1].isNull()});
            if(!args[1].isNull()){const event=args[1].add(24).readPointer();if(!event.isNull())pipeEvents.set(event.toString(),facts);}
          }else{
            const facts=pipeEvents.get(args[0].toString());if(!facts)throw new Error('unobserved pipe connection event');Object.assign(data,facts,{timeout:args[1].toUInt32()});
          }
          const call=++pipeCounts[name];if(call>32)throw new Error('owned pipe event bound exceeded');data.call=call;
          this.pipeRecord=data;
        }catch(error){pipeErrors.push(name+': metadata');emit('pipe-probe-error',{phase:'entry',operation:name});}
      },
      onLeave(value){
        if(!this.pipeRecord)return;
        // Preserve invocation last-error before any metadata work. Never call
        // GetLastError, modify it, or treat a successful API's stale value as failure.
        const saved=this.lastError;
        try{
          const d=this.pipeRecord;const raw=value.toUInt32();
          if(name==='CreateNamedPipeA' || name==='CreateFileA'){
            d.handleValid=!value.isNull() && !value.equals(ptr('0xffffffffffffffff'));d.lastError=d.handleValid?null:saved;
            if(name==='CreateNamedPipeA' && d.handleValid)pipeHandles.set(value.toString(),{nameLength:d.nameLength,nameSha256:d.nameSha256,fixedPrefixMatched:true});
          }else if(name==='ConnectNamedPipe'){d.returned=raw!==0;d.lastError=d.returned?null:saved;}
          else{d.waitResult=raw;d.lastError=raw===0xffffffff?saved:null;}
          if(d.lastError!==null && (!Number.isInteger(d.lastError) || d.lastError<0 || d.lastError>0xffffffff))throw new Error('pipe last-error absent');
          emit('pipe-operation',d);
        }catch(error){pipeErrors.push(name+': return');emit('pipe-probe-error',{phase:'return',operation:name});}
      }
    });pipeBindings.set(at.toString(),module.name.toLowerCase()+':'+name);}
    catch(error){pipeErrors.push(name+': install');emit('pipe-probe-error',{phase:'install',operation:name});}
  }
}
Process.attachModuleObserver({onAdded:pipeAttach});
emit('pipe-probe-ready',{role:pipeWitness.role,descriptor:pipeWitness,bindings:Array.from(pipeBindings.values()),errors:pipeErrors.slice(),nameValuesRetained:false,apiResultsReplaced:false});
setInterval(()=>emit('pipe-probe-snapshot',{role:pipeWitness.role,counts:Object.assign({},pipeCounts),errors:pipeErrors.slice(),nameValuesRetained:false}),1000);
'''

def descriptor(role,image,nonce):
    image=PureWindowsPath(image)
    if not image.is_absolute() or role not in ('parent','child') or not isinstance(nonce,str) or not re.fullmatch('[0-9a-f]{32}',nonce):
        raise ValueError('Explicit pipe role and run nonce required')
    if role=='parent':
        if image.name!='Battle Aces.exe':raise ValueError('Owned game image required')
        module=image.parent/'Battle Aces_Data/Plugins/x86_64/VuplexWebViewWindows.dll';rva=0x1b630
        digest='910387d611f5f9c79f433b80b3e779542995d6b5cc399da69b3b45f860bce871'
    else:
        if image.name!='Vuplex WebView.vuplex' or image.parent.name!='VuplexWebViewChromium':raise ValueError('Owned browser image required')
        # The startup observer already hooks84050. Verify the original CALL
        # window inside the same body instead of rejecting our own entry hook.
        module=image;rva=0x840e2;digest='8151084b6508f9be5bb689a6e44ab3dc949dd4876f1caa545751c2e551cf723e'
    return dict(role=role,module=str(module),prefixRva=rva,sha256=digest,nonce=nonce)

def parent_build_source(config,cwd,sdk,*,cache_path,gate,pipe_nonce):
    return gate_source(config,cwd,sdk,cache_path=cache_path,gate=gate)+'\n'+PIPE.replace('__PIPE__',json.dumps(descriptor('parent',config['image'],pipe_nonce)))

def child_build_source(config,cwd,descriptors,*,pipe_nonce):
    return child_source(config,cwd,descriptors)+'\n'+PIPE.replace('__PIPE__',json.dumps(descriptor('child',config['image'],pipe_nonce)))
