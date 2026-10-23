"""Owned browser startup entry/return/exception metadata; no payload or argv reads.

Attach before the owner's held primary thread is resumed. Hook installation and
exception forwarding are controlled instrumentation, not unmodified execution or
complete pre-loader coverage. All existing file/network/exit records are kept.
"""
import json,re
from pathlib import PureWindowsPath
from tools.frida_attribution_exit import build_source as exit_source

PROFILE='webview-child-startup-v1'
PROBE=r'''const childProbe=__PROBE__;const childInstalled=new Set(),childCounts={},childErrors=[];
let childExceptions=0;for(const d of childProbe)for(const e of d.entries)childCounts[e.name]=0;
function childPc(address) {
  const m=Process.findModuleByAddress(address);return m?{module:m.name.toLowerCase(),rva:address.sub(m.base).toString()}:{module:null,rva:null};
}
function childResult(kind,value) {
  if(kind==='int32')return value.toInt32();
  if(kind==='bool-al')return (value.toUInt32() & 255)!==0;
  if(kind==='nonnull')return !value.isNull();
  return null;
}
function childObserve(module) {
  const descriptor=childProbe.find(d=>d.module.toLowerCase()===module.path.toLowerCase());if(!descriptor)return;
  if(childInstalled.has(descriptor.module)){childErrors.push('duplicate child module');emit('child-probe-error',{phase:'module-repeat'});return;}
  try {
    // Verify ALL selected prefixes before any of these entries is hooked.
    for(const e of descriptor.entries) {
      if(e.exportName && (!module.findExportByName(e.exportName) || !module.findExportByName(e.exportName).equals(module.base.add(e.rva))))throw new Error('child export RVA differs');
      if(Checksum.compute('sha256',module.base.add(e.rva).readByteArray(16))!==e.sha256)throw new Error('child startup prefix differs');
    }
    for(const e of descriptor.entries)Interceptor.attach(module.base.add(e.rva),{
      onEnter(){this.ordinal=++childCounts[e.name];if(this.ordinal<=8)emit('child-startup-entry',{name:e.name,call:this.ordinal,frames:frames(this.context)});},
      onLeave(value){if(this.ordinal<=8)emit('child-startup-return',{name:e.name,call:this.ordinal,returnKind:e.returnKind,result:childResult(e.returnKind,value)});}
    });
    childInstalled.add(descriptor.module);emit('child-probe-installed',{module:descriptor.module,entries:descriptor.entries,argumentsRead:false,returnsReplaced:false});
  }catch(error){childErrors.push(String(error));emit('child-probe-error',{phase:'install'});}
}
Process.setExceptionHandler(details=>{
  ++childExceptions;
  if(childExceptions<=32) {
    try{emit('child-native-exception',{type:details.type,pc:childPc(details.address),memoryOperation:details.memory?details.memory.operation:null,frames:frames(details.context),handled:false});}
    catch(error){childErrors.push('exception metadata');emit('child-probe-error',{phase:'exception'});}
  }
  // Observe only; original exception/OS handling must continue.
  return false;
});
Process.attachModuleObserver({onAdded:childObserve});
emit('child-probe-ready',{descriptors:childProbe,errors:childErrors.slice(),argumentsRead:false,returnsReplaced:false,exceptionHandlingReplaced:false});
setInterval(()=>emit('child-probe-snapshot',{installed:Array.from(childInstalled),counts:childCounts,exceptions:childExceptions,errors:childErrors.slice(),exceptionEventOverflow:childExceptions>32}),1000);
'''

def build_source(config,cwd,descriptors):
    image=PureWindowsPath(config['image'])
    if image.name!='Vuplex WebView.vuplex' or image.parent.name!='VuplexWebViewChromium' or \
            not isinstance(descriptors,list) or not 1<=len(descriptors)<=2:
        raise ValueError('Exact owned browser and startup descriptors required')
    modules=set();names=set()
    for d in descriptors:
        if not isinstance(d,dict) or set(d)!={'module','entries'} or \
                PureWindowsPath(d['module']) not in (image,image.parent/'libcef.dll') or d['module'] in modules or \
                not isinstance(d['entries'],list) or not 1<=len(d['entries'])<=8:
            raise ValueError('Child startup module differs')
        modules.add(d['module'])
        for e in d['entries']:
            if not isinstance(e,dict) or set(e)!={'name','rva','sha256','returnKind','exportName'} or \
                    not isinstance(e['name'],str) or not re.fullmatch('[a-zA-Z0-9_.-]{1,64}',e['name']) or e['name'] in names or \
                    type(e['rva']) is not int or not 0<e['rva']<0x20000000 or \
                    not isinstance(e['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',e['sha256']) or \
                    e['returnKind'] not in ('int32','bool-al','nonnull','void') or \
                    (e['exportName'] is not None and (not isinstance(e['exportName'],str) or not re.fullmatch('[a-zA-Z0-9_]{1,64}',e['exportName']))):
                raise ValueError('Bounded unique child entry descriptor required')
            names.add(e['name'])
    return exit_source(config,cwd)+'\n'+PROBE.replace('__PROBE__',json.dumps(descriptors))
