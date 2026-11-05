'use strict';
const root='E:\\games\\ba\\Battle Aces (Beta)\\battleaces_resuraction\\local\\privacy512-game01\\';
const norm=p=>p.replace(/\//g,'\\').toLowerCase();
if(Process.arch!=='x64'||norm(Process.mainModule.path)!==norm(root+'Battle Aces.exe'))
  throw Error('owned recipe47 game identity differs');
let seq=0,unity=null,armed=false,attempted=false,constructCalls=0,callbackCalls=0;
const emit=(kind,data)=>send({schema:1,seq:++seq,pid:Process.id,kind,data});
const bytes=(p,n)=>Array.from(new Uint8Array(p.readByteArray(n)));
Process.attachModuleObserver({onAdded(m){
  if(m.name.toLowerCase()==='unityplayer.dll'&&unity===null){
    if(norm(m.path)!==norm(root+'UnityPlayer.dll')||m.size<0x1c0af08)
      throw Error('UnityPlayer identity differs');
    const publicSite=m.base.add(0x5fb70),staticSite=m.base.add(0x361870),
      constructor=m.base.add(0x361900),callback=m.base.add(0xc307c0),
      global=m.base.add(0x1c0af00);
    if(bytes(publicSite,3).join(',')!=='49,192,195'||bytes(staticSite,1)[0]!==195)
      throw Error('loaded advertising guards differ');
    unity={publicSite,staticSite,global};
    Interceptor.attach(constructor,{onEnter(){constructCalls++;}});
    Interceptor.attach(callback,{onEnter(){callbackCalls++;}});
    emit('unity-ready',{path:m.path,base:m.base.toString(),
      publicGuard:bytes(publicSite,3),staticGuard:bytes(staticSite,1),
      globalBefore:global.readPointer().toString()});
  }
  if(m.name.toLowerCase()!=='gameassembly.dll'||armed)return;
  if(norm(m.path)!==norm(root+'GameAssembly.dll'))throw Error('GameAssembly identity differs');
  armed=true;
  const init=m.getExportByName('il2cpp_init');
  Interceptor.attach(init,{onLeave(){
    if(attempted)return;attempted=true;
    try{
      if(unity===null)throw Error('UnityPlayer guard unavailable');
      const before={constructCalls,callbackCalls,global:unity.global.readPointer().toString()};
      const invoke=new NativeFunction(unity.publicSite,'int',['pointer']);
      const result=invoke(ptr(0));
      const after={constructCalls,callbackCalls,global:unity.global.readPointer().toString()};
      const publicGuard=bytes(unity.publicSite,3),staticGuard=bytes(unity.staticSite,1);
      const passed=result===0&&after.constructCalls===before.constructCalls&&
        after.callbackCalls===before.callbackCalls&&after.global===before.global&&
        publicGuard.join(',')==='49,192,195'&&staticGuard[0]===195;
      emit('public-call',{passed,result,before,after,publicGuard,staticGuard,
        thread:Process.getCurrentThreadId()});
    }catch(e){emit('probe-error',{error:String(e)});}
  }});
  emit('module-hook-ready',{assembly:m.path,init:init.toString()});
}});
emit('observer-ready',{game:root+'Battle Aces.exe'});
