'use strict';
const expectedRoot='E:\\games\\ba\\Battle Aces (Beta)\\battleaces_resuraction\\local\\privacy512-game01\\';
const norm=p=>p.replace(/\//g,'\\').toLowerCase();
if(Process.arch!=='x64'||norm(Process.mainModule.path)!==norm(expectedRoot+'Battle Aces.exe'))
  throw Error('owned recipe47 game identity differs');
let seq=0, unity=null, armed=false, attempted=false, prepareCalls=0, beginCalls=0;
const emit=(kind,data)=>send({schema:1,seq:++seq,pid:Process.id,kind,data});
const bytes=(p,n)=>Array.from(new Uint8Array(p.readByteArray(n)));
Process.attachModuleObserver({onAdded(m){
  if(m.name.toLowerCase()==='unityplayer.dll'&&unity===null){
    if(norm(m.path)!==norm(expectedRoot+'UnityPlayer.dll')||m.size<0xc64ea3)
      throw Error('UnityPlayer identity differs');
    const site=m.base.add(0xc64e20),prepare=m.base.add(0xc64310),begin=m.base.add(0xc64ea0);
    const entry=bytes(site,3);
    if(entry.join(',')!=='49,192,195')throw Error('loaded recipe47 guard differs: '+entry);
    unity={site,prepare,begin};
    Interceptor.attach(prepare,{onEnter(){prepareCalls++;}});
    Interceptor.attach(begin,{onEnter(){beginCalls++;}});
    emit('unity-ready',{path:m.path,base:m.base.toString(),site:site.toString(),entry,
      prepare:prepare.toString(),begin:begin.toString()});
  }
  if(m.name.toLowerCase()!=='gameassembly.dll'||armed)return;
  if(norm(m.path)!==norm(expectedRoot+'GameAssembly.dll'))throw Error('GameAssembly identity differs');
  armed=true;
  const init=m.getExportByName('il2cpp_init');
  Interceptor.attach(init,{onLeave(){
    if(attempted)return;
    attempted=true;
    try{
      if(unity===null)throw Error('UnityPlayer guard unavailable');
      const before={prepareCalls,beginCalls};
      const invoke=new NativeFunction(unity.site,'int',['pointer']);
      const result=invoke(ptr(0));
      const after={prepareCalls,beginCalls};
      const entry=bytes(unity.site,3);
      const passed=result===0&&after.prepareCalls===before.prepareCalls&&
        after.beginCalls===before.beginCalls&&entry.join(',')==='49,192,195';
      emit('guard-call',{passed,result,before,after,entry,thread:Process.getCurrentThreadId()});
    }catch(e){emit('probe-error',{error:String(e)});}
  }});
  emit('module-hook-ready',{assembly:m.path,init:init.toString()});
}});
emit('observer-ready',{game:expectedRoot+'Battle Aces.exe'});
