"""Count selected state-three worker entries in an owned suspended client.

No identity, callback argument, report, queue or network payload is read.
"""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_unresolved_file_status373 import build_source as base_source


ADAPTER = r'''
// Recipe38 UnityPlayer entry bytes are checked before installing each hook.
const state3Specs={
  worker:{rva:0xc402d0,bytes:'40534883ec304d8bd0488bd933c0f00f'},
  setter:{rva:0xc3c5d0,bytes:'4055535741544157488dac2460feffff'},
  caller:{rva:0xc300d0,bytes:'40534883ec20488bd9e8f2c40000488b'},
  dispatcher:{rva:0xc3b990,bytes:'40534883ec204532c0488bd9443881c4'}
};
const state3Counts={worker:0,setter:0,caller:0,dispatcher:0};
const state3First={worker:[],setter:[],caller:[],dispatcher:[]};
const state3Hooks=[],state3Errors=[];
Process.attachModuleObserver({onAdded(module){
  if(module.name.toLowerCase()!=='unityplayer.dll')return;
  try {
    for(const [key,spec] of Object.entries(state3Specs)) {
      const address=module.base.add(spec.rva);
      const actual=Array.from(new Uint8Array(address.readByteArray(16)))
        .map(value=>value.toString(16).padStart(2,'0')).join('');
      if(actual!==spec.bytes)throw new Error(key+' entry bytes differ');
      Interceptor.attach(address,{onEnter(){
        state3Counts[key]++;
        if(state3First[key].length<8)state3First[key].push({
          elapsedMs:Date.now()-started,tid:Process.getCurrentThreadId(),
          returnRva:this.returnAddress.sub(module.base).toString()});
      }});
      state3Hooks.push({key,rva:spec.rva});
    }
  }catch(error){state3Errors.push(String(error));}
  emit('state3-module-ready',{module:module.name.toLowerCase(),
    hooks:state3Hooks.slice(),errors:state3Errors.slice()});
}});
'''


def build_source(config: dict) -> str:
    source = base_source(config)
    source = replace_once(source,
        "emit('observer-ready',{installed:installed.slice(),errors:errors.slice()});",
        ADAPTER + "\nemit('observer-ready',{installed:installed.slice(),errors:errors.slice()});")
    source = replace_once(source,
        "emit('self-terminate-entry',{api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),",
        "emit('self-terminate-entry',{state3Counts:Object.assign({},state3Counts),state3First,state3Hooks:state3Hooks.slice(),state3Errors:state3Errors.slice(),api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),")
    return source
