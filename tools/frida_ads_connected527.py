"""Passive advertising entry witness for an owned suspended connected client."""
from __future__ import annotations

import json

SOURCE = r''' 'use strict';
const cfg=__CONFIG__;
const norm=p=>p.replace(/\//g,'\\').toLowerCase();
if(Process.arch!=='x64'||Process.id!==cfg.pid||
   norm(Process.mainModule.path)!==norm(cfg.image))throw Error('owned image mismatch');
let seq=0,mod=null,ctor=0,callback=0,sendRequest=0,errors=[];
const emit=(kind,data)=>send({schema:1,seq:++seq,runId:cfg.runId,pid:Process.id,kind,data});
const global=()=>{try{return mod.base.add(0x1c0af00).readPointer().toString();}
  catch(e){errors.push(String(e));return 'error';}};
Process.attachModuleObserver({onAdded(m){
 if(m.name.toLowerCase()!=='unityplayer.dll'||mod)return;
 if(norm(m.path)!==norm(cfg.unity))throw Error('Unity image mismatch');
 const body=m.base.add(0xc307c0).readByteArray(0xb1);
 const guard=new Uint8Array(m.base.add(0xc30838).readByteArray(5));
 if(Checksum.compute('sha256',body)!==cfg.bodySha256||
    m.base.add(0x361870).readU8()!==0xc3||
    m.base.add(0x5fb70).readU8()!==0x31||
    !guard.every(v=>v===0x90))throw Error('loaded guard/body bytes differ');
 mod=m;
 Interceptor.attach(m.base.add(0x361900),{onEnter(){ctor++;emit('handler-constructor',{count:ctor});}});
 Interceptor.attach(m.base.add(0xc307c0),{onEnter(){callback++;emit('ads-callback',{count:callback,caller:this.returnAddress.toString(),module:Process.findModuleByAddress(this.returnAddress)?.name||null});}});
 Interceptor.attach(m.base.add(0xc300f0),{onEnter(){sendRequest++;emit('ads-send-request',{count:sendRequest});}});
 let claimed=false,seen=[];
 for(const name of ['kernelbase.dll','kernel32.dll']){
   const address=Process.getModuleByName(name).getExportByName('TerminateProcess');
   if(seen.some(p=>p.equals(address)))continue;seen.push(address);
   Interceptor.attach(address,{onEnter(args){
     if(claimed||!args[0].equals(ptr('0xffffffffffffffff')))return;
     claimed=true;emit('self-terminate-entry',{api:name,exitCode:args[1].toInt32(),handler:global(),constructorCalls:ctor,callbackCalls:callback,sendRequestCalls:sendRequest,errors});Thread.sleep(0.2);
   }});
 }
 emit('observer-ready',{module:m.path,handler:global(),exitHooks:seen.length,bodySha256:cfg.bodySha256});
}});
emit('script-ready',{image:cfg.image});
'''


def build_source(config: dict) -> str:
    if set(config) != {'pid', 'image', 'unity', 'runId', 'bodySha256'}:
        raise ValueError('exact advertising witness config required')
    if type(config['pid']) is not int or config['pid'] <= 0:
        raise ValueError('positive PID required')
    if not all(isinstance(config[key], str) for key in config if key != 'pid'):
        raise ValueError('string witness fields required')
    return SOURCE.replace('__CONFIG__', json.dumps(config, separators=(',', ':')))
