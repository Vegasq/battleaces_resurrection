"""Passive entry counts for the SDK wrapper and shared Unity request send.

For an owned suspended-start client only. No request, URL, header, payload,
queue or identifier is read. The shared send is not itself an SDK event.
"""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_unresolved_file_status373 import build_source as base_source


SDK_ADAPTER = r'''
// Original/current recipe38 RVAs; require exact entry bytes before hooking.
const sdkExpected={
  wrapper:{rva:0x80e920,bytes:'40534883ec20803dc4a1630600488bd9'},
  core:{rva:0x53dd0d0,bytes:'40534883ec20488b0523bca801488bd9'}
};
const sdkCounts={wrapper:0,core:0},sdkHooks=[],sdkErrors=[];
Process.attachModuleObserver({onAdded(module){
  if(module.name.toLowerCase()!=='gameassembly.dll')return;
  try {
    for(const [key,spec] of Object.entries(sdkExpected)) {
      const address=module.base.add(spec.rva);
      const actual=Array.from(new Uint8Array(address.readByteArray(16)))
        .map(value=>value.toString(16).padStart(2,'0')).join('');
      if(actual!==spec.bytes)
        throw new Error(key+' entry bytes differ');
      Interceptor.attach(address,{onEnter(){sdkCounts[key]++;}});
      sdkHooks.push({key,rva:spec.rva});
    }
  }catch(error){sdkErrors.push(String(error));}
  emit('sdk-module-ready',{module:module.name.toLowerCase(),hooks:sdkHooks.slice(),errors:sdkErrors.slice()});
}});
'''


def build_source(config: dict) -> str:
    source = base_source(config)
    source = replace_once(source,
        "emit('self-terminate-entry',{api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),",
        "emit('self-terminate-entry',{sdkCounts:Object.assign({},sdkCounts),sdkHooks:sdkHooks.slice(),sdkErrors:sdkErrors.slice(),api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),")
    return source + SDK_ADAPTER
