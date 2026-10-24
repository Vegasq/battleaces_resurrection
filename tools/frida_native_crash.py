"""Passive witnesses for an explicitly armed original native game exception.

Composes the qualified cwd metadata observer. No native call, replacement,
exception handler installation, argument write, policy change or transport hold.
Function hooks change entry code as normal Frida instrumentation; full selected
bodies are checked before hooking. The registered crash wrapper stays untouched.
"""
import json
import re
from pathlib import PureWindowsPath
from tools.frida_attribution_cwd import build_source as cwd_source
from tools.frida_attribution_clock import replace_once

HOOKS={'filter':0x9fdec0,'local-stack':0x9fde30,'handoff':0x9e0e10,'teardown':0x9f8290}

def build_source(config,cwd,native):
    image=PureWindowsPath(config['image'])
    if image.name!='Battle Aces.exe' or not re.fullmatch('r169g',image.parent.name):
        raise ValueError('Owned crash169 diagnostic image required')
    if not isinstance(native,dict) or set(native)!={'module','bodies','armFile'} or native['module']!=str(image.parent/'UnityPlayer.dll'):
        raise ValueError('Exact owned Unity module required')
    arm=PureWindowsPath(native['armFile'])
    if arm.name!='native-crash169.arm' or arm.parent.parent!=image.parent/'.battleaces-resurrection/profiles' or \
            not re.fullmatch('nativestest_crash169_[0-9a-f]{12}',arm.parent.name):
        raise ValueError('Exact owned private arm file required')
    bodies=native['bodies']
    if not isinstance(bodies,list) or not bodies or len(bodies)>32:
        raise ValueError('Bounded native body inventory required')
    starts=set()
    for body in bodies:
        if not isinstance(body,dict) or set(body)!={'rva','size','sha256'} or type(body['rva']) is not int or \
                not 0<body['rva']<0x1e58000 or type(body['size']) is not int or not 1<=body['size']<=16384 or \
                not isinstance(body['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',body['sha256']) or body['rva'] in starts:
            raise ValueError('Unique typed native body hashes required')
        starts.add(body['rva'])
    if not set(HOOKS.values()).union({0x1484d0,0x6f4b60}).issubset(starts):
        raise ValueError('Original wrapper and witness bodies required')
    source=cwd_source(config,cwd)
    source=replace_once(source,'        if(this.record) {', '''        if(this.record && name==='NtCreateFile' && status===-1073741772 &&
           normalize(this.record.path)===normalize(crashConfig.armFile)) {
          crashGateMisses++;
          if(crashGateMisses>4)return;
        }
        if(this.record) {''')
    addition=SOURCE.replace('__NATIVE__',json.dumps(native)).replace('__HOOKS__',json.dumps(HOOKS))
    return replace_once(source,'Process.attachModuleObserver({onAdded(module){',addition+
        '\nProcess.attachModuleObserver({onAdded(module){\n  crashInstall(module);')

SOURCE=r'''
const crashConfig=__NATIVE__, crashHooks=__HOOKS__, crashCounts={}, crashApis=new Map();
let crashModule=null, crashInstalled=false, crashGateMisses=0;
function crashText(p,wide){
  if(p.isNull())return null;
  for(let i=0;i<8192;i++)if((wide?p.add(2*i).readU16():p.add(i).readU8())===0)
    return wide?p.readUtf16String(i):p.readAnsiString(i);
  throw new Error('bounded crash path exceeded');
}
function crashState(){
  if(!crashModule)return null;
  const b=crashModule.base,c=b.add(0x1d0e128).readPointer();
  if(c.isNull())return {controller:null};
  return {controller:c.toString(),savedMode:c.add(8).readU32(),expectedMode:c.add(0x40).readU32(),
    callback:c.add(0x70).readPointer().sub(b).toString(),
    ipc:[0x20,0x28,0x30,0x38,0x40,0x48].map(o=>c.add(0x78+o).readPointer().toString()),
    recursion:b.add(0x1d0e941).readU8(),breakOnCrash:b.add(0x1d0e930).readU8(),
    manager:b.add(0x1d08f98).readPointer().toString(),
    wrapperSha256:Checksum.compute('sha256',b.add(0x1484d0).readByteArray(0x42)),
    dispatcherSha256:Checksum.compute('sha256',b.add(0x6f4b60).readByteArray(0x120))};
}
function crashApi(module,name){
  const address=module.findExportByName(name);if(!address)return;
  if(crashApis.has(address.toString()))return;
  crashApis.set(address.toString(),name);crashCounts[name]=0;
  const callbacks={
    onEnter(args){
      this.name=name;const call=++crashCounts[name];this.data=null;
      try {
        if(name==='RaiseException') {
          if(args[0].toUInt32()!==0xc0000005)return;
          this.data={name,code:args[0].toUInt32(),flags:args[1].toUInt32(),count:args[2].toUInt32(),
            nullArguments:args[3].isNull(),frames:frames(this.context)};
        } else if(name==='SetErrorMode')this.data={name,requested:args[0].toUInt32(),frames:frames(this.context)};
        else if(name==='GetErrorMode') {if(!crashModule || !Process.findModuleByAddress(this.returnAddress) ||
          Process.findModuleByAddress(this.returnAddress).name.toLowerCase()!=='battleacesoffline.dll')return;
          this.data={name,frames:frames(this.context)};
        } else if(name==='SetUnhandledExceptionFilter') {
          const m=Process.findModuleByAddress(args[0]);this.data={name,filterModule:m?m.name:null,
            filterRva:m?args[0].sub(m.base).toString():null,frames:frames(this.context)};
        } else if(name==='SymInitialize' || name==='SymInitializeW')this.data={name,
          searchPath:crashText(args[1],name.endsWith('W')),invadeProcess:args[2].toInt32()!==0,frames:frames(this.context)};
        else if(name==='SymSetSearchPath' || name==='SymSetSearchPathW')this.data={name,searchPath:crashText(args[1],name.endsWith('W'))};
        else if(name==='SymSetOptions')this.data={name,requested:args[0].toUInt32()};
        else if(name==='SymLoadModule64' && call<=128)this.data={name,imagePath:crashText(args[2],false),moduleName:crashText(args[3],false)};
        if(this.data)emit('crash-api-enter',this.data);
      }catch(error){errors.push('crash API '+name+': '+String(error));emit('decode-error',{api:name});}
    },
    onLeave(value){if(this.data)emit('crash-api-leave',{name,result:value.toString()});}
  };
  // Exceptions unwind through RaiseException. A return trampoline here changes
  // that boundary even when onEnter declines to journal an unrelated exception.
  if(name==='RaiseException')delete callbacks.onLeave;
  Interceptor.attach(address,callbacks);
  emit('crash-api-installed',{module:module.name,path:module.path,name,address:address.toString()});
}
function crashInstall(module){
  try {
    const name=module.name.toLowerCase();
    // Reuse the qualified control's single exported exception entry. Generic
    // process policy/filter APIs are intentionally outside this hook profile.
    // The C++ preflight independently journals GetErrorMode and stored modes.
    // RaiseException is left untouched during loader/OutputDebugString startup.
    // A separate passive entry-only script may attach after native menu-ready,
    // before the external arm file is published.
    if(name==='dbghelp.dll') {
      emit('crash-dbghelp-module',{path:module.path,base:module.base.toString(),size:module.size});
      for(const api of ['SymInitialize','SymInitializeW','SymSetSearchPath','SymSetSearchPathW','SymSetOptions','SymLoadModule64'])crashApi(module,api);
    }
    if(name!=='unityplayer.dll')return;
    if(crashInstalled || normalize(module.path)!==normalize(crashConfig.module))throw new Error('Unity reload/path differs');
    for(const body of crashConfig.bodies)
      if(Checksum.compute('sha256',module.base.add(body.rva).readByteArray(body.size))!==body.sha256)
        throw new Error('native body hash differs: '+body.rva.toString(16));
    crashModule=module;
    for(const [label,rva] of Object.entries(crashHooks)) {
      crashCounts[label]=0;
      Interceptor.attach(module.base.add(rva),{
        onEnter(args){
          try {
            const call=++crashCounts[label];this.call=call;
            const data={label,rva,call,missingArmFileOpens:crashGateMisses,frames:frames(this.context)};
            if(label==='filter')data.exceptionCode=args[0].readPointer().readU32();
            emit('crash-native-enter',data);
          }catch(error){errors.push('native '+label+': '+String(error));emit('decode-error',{api:label});}
        },onLeave(value){emit('crash-native-leave',{label,call:this.call,result:value.toInt32()});}
      });
    }
    crashInstalled=true;emit('crash-native-installed',{path:module.path,bodies:crashConfig.bodies,
      hooks:crashHooks,originalWrapperUntouched:true,observerCallsTargetApis:false});
  }catch(error){errors.push('crash install: '+String(error));emit('decode-error',{api:'crash-install'});}
}
setInterval(()=>{
  try{emit('crash-snapshot',{installed:crashInstalled,state:crashState(),counts:{...crashCounts},missingArmFileOpens:crashGateMisses,errors:errors.slice(),overflow});}
  catch(error){emit('crash-state-unavailable',{});}
},2000);
'''
