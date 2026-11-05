"""Passive SDK queue/send entry counts for an owned suspended recipe38 client.

Reads no queue files,request content,URL,payload or identifiers. Exact entry
bytes are checked before each hook;all counters end at original self-exit.
"""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_unresolved_file_status373 import build_source as base_source

GUARDED={
    'deliver':(0x81c6a0,'c38954241048894c2408535657415441'),
    'cache_start':(0x81f730,'c3895c2408574883ec30488bd9803d2f'),
    'cached_move':(0x8201f0,'31c0c32410574883ec20803d79896206'),
    'process_move':(0x8204c0,'31c0c32408535657415641574881eca0'),
    'push_move':(0x820de0,'31c0c3241048894c2408565741544156'),
    'cache_write':(0x837130,'c38bc04533c94c8bc2488bd0e9ff0500'),
}
ENTRIES={
    'deliver_cached_factory':(0x81f8b0,'40534883ec20803db792620600488bd9'),
    'process_cached_factory':(0x81f950,'48895c2408574883ec20803d14926206'),
    'push_factory':(0x81cf00,'48895c2408574883ec20803d57bc6206'),
    'wrapper_send':(0x80e920,'40534883ec20803dc4a1630600488bd9'),
    'core_send':(0x53dd0d0,'40534883ec20488b0523bca801488bd9'),
}

ADAPTER=r'''
const sdkExpected=__ENTRIES__;
const sdkCounts=Object.fromEntries(Object.keys(sdkExpected).map(key=>[key,0]));
const sdkHooks=[],sdkErrors=[];
Process.attachModuleObserver({onAdded(module){
  if(module.name.toLowerCase()!=='gameassembly.dll')return;
  try {
    for(const [key,spec] of Object.entries(sdkExpected)) {
      const address=module.base.add(spec.rva);
      const actual=Array.from(new Uint8Array(address.readByteArray(16)))
        .map(value=>value.toString(16).padStart(2,'0')).join('');
      if(actual!==spec.bytes)throw new Error(key+' entry bytes differ');
      Interceptor.attach(address,{onEnter(){
        const count=++sdkCounts[key];
        if(count<=8)emit('sdk-entry',{key,count});
      }});
      sdkHooks.push({key,rva:spec.rva});
    }
  }catch(error){sdkErrors.push(String(error));}
  emit('sdk-module-ready',{hooks:sdkHooks.slice(),errors:sdkErrors.slice()});
}});
'''

def build_source(config:dict)->str:
    import json
    source=base_source(config)
    source=replace_once(source,
        "emit('self-terminate-entry',{api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),",
        "emit('self-terminate-entry',{sdkCounts:Object.assign({},sdkCounts),sdkHooks:sdkHooks.slice(),sdkErrors:sdkErrors.slice(),api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),")
    entries={key:dict(rva=rva,bytes=bytes_) for key,(rva,bytes_) in ENTRIES.items()}
    return source+ADAPTER.replace('__ENTRIES__',json.dumps(entries,separators=(',',':')))
