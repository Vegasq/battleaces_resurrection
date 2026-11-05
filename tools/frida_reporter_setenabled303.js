// Passive owned runtime observation. No original method invocation or mutation.
'use strict';
const expected=Process.mainModule.path.replace(/[^\\]+$/, 'GameAssembly.dll').toLowerCase();
const guard='40534883ec20803d78631903000fb6da';
let attached=false, calls=0;
function emit(kind, extra={}) {send(Object.assign({schema:1,kind,pid:Process.id,attached,calls},extra));}
Process.attachModuleObserver({onAdded(module) {
  if(module.name.toLowerCase()!=='gameassembly.dll')return;
  if(module.path.toLowerCase()!==expected)throw new Error('GameAssembly path differs');
  const address=module.base.add(0x3cc30f0);
  const actual=Array.from(new Uint8Array(address.readByteArray(guard.length/2)))
    .map(x=>x.toString(16).padStart(2,'0')).join('');
  if(actual!==guard)throw new Error('SetEnabled entry differs: '+actual);
  Interceptor.attach(address,{onEnter(args) {
    calls++;
    const caller=Process.findModuleByAddress(this.returnAddress);
    emit('SetEnabled.enter',{thread:Process.getCurrentThreadId(),
      enabledByte:args[1].toUInt32()&255,
      returnModule:caller?caller.name:null,
      returnRva:caller?this.returnAddress.sub(caller.base).toString():null});
  }});
  attached=true;emit('SetEnabled.hook-ready',{modulePath:module.path,guard:actual});
}});
emit('observer-ready');
setInterval(()=>emit('heartbeat'),5000);
