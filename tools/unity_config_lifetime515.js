'use strict';
const root='E:\\games\\ba\\Battle Aces (Beta)\\battleaces_resuraction\\local\\privacy512-game01\\';
const norm=p=>p.replace(/\//g,'\\').toLowerCase();
if(Process.arch!=='x64'||norm(Process.mainModule.path)!==norm(root+'Battle Aces.exe'))
  throw Error('owned recipe47 game identity differs');
let seq=0,unity=null,counts={fetch:0,close:0,destruct:0};
const emit=(kind,data)=>send({schema:1,seq:++seq,pid:Process.id,kind,data});
const state=p=>({enabled:p.add(0xb58).readS32(),request:p.add(0xb70).readPointer().toString()});
Process.attachModuleObserver({onAdded(m){
  if(m.name.toLowerCase()!=='unityplayer.dll'||unity!==null)return;
  if(norm(m.path)!==norm(root+'UnityPlayer.dll')||m.size<0xc64e23)
    throw Error('UnityPlayer identity differs');
  unity=m;
  const guard=m.base.add(0xc64e20);
  const b=Array.from(new Uint8Array(guard.readByteArray(3)));
  if(b.join(',')!=='49,192,195')throw Error('loaded post guard differs: '+b);
  Interceptor.attach(m.base.add(0xc59350),{
    onEnter(args){counts.fetch++;this.owner=args[0];emit('fetch-enter',{count:counts.fetch,state:state(args[0])});},
    onLeave(ret){emit('fetch-leave',{result:ret.toInt32()&255,state:state(this.owner)});}
  });
  Interceptor.attach(m.base.add(0xc58f50),{
    onEnter(args){counts.close++;this.owner=args[0];emit('close-enter',{count:counts.close,state:state(args[0])});},
    onLeave(ret){emit('close-leave',{result:ret.toInt32()&255,state:state(this.owner)});}
  });
  Interceptor.attach(m.base.add(0xc58b00),{
    onEnter(args){counts.destruct++;emit('destructor-enter',{count:counts.destruct,state:state(args[0])});}
  });
  emit('unity-ready',{path:m.path,base:m.base.toString(),entry:b});
}});
const seen=[];
for(const name of ['kernelbase.dll','kernel32.dll']){
  const p=Process.getModuleByName(name).getExportByName('TerminateProcess');
  if(seen.some(x=>x.equals(p)))continue;
  seen.push(p);
  Interceptor.attach(p,{onEnter(args){
    if(!args[0].equals(ptr('0xffffffffffffffff')))return;
    emit('self-terminate-entry',{exitCode:args[1].toInt32(),counts,unity:unity!==null});
    Thread.sleep(0.2);
  }});
}
emit('observer-ready',{game:root+'Battle Aces.exe',terminationHooks:seen.length});
