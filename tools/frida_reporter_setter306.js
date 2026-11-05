// Owned recipe27 diagnostic: call the already-initialized reporter-only setter.
// No report payload, SDK queue or network access.
'use strict';
const module=Process.getModuleByName('GameAssembly.dll');
const expected=Process.mainModule.path.replace(/[^\\]+$/, 'GameAssembly.dll').toLowerCase();
if(module.path.toLowerCase()!==expected)throw new Error('GameAssembly path differs');
function hex(at,length) {
  return Array.from(new Uint8Array(at.readByteArray(length)))
    .map(x=>x.toString(16).padStart(2,'0')).join('');
}
const initializer=hex(module.base.add(0x3cc687c),10);
const setterGuard=hex(module.base.add(0x3cc30fd),5);
if(initializer!=='c64118004883c4205fc3' || setterGuard!=='b300907518')
  throw new Error('Reporter state guard bytes differ');
const klass=module.base.add(0x6b42b30).readPointer();
if(klass.isNull() || klass.add(0xe0).readU32()!==1)
  throw new Error('Reporter class not already initialized');
const fields=klass.add(0xb8).readPointer();
if(fields.isNull())throw new Error('Reporter static fields unavailable');
const flag=fields.add(0x18);
const before=flag.readU8();
if(before!==0)throw new Error('Reporter enabled flag was not false before probe');
const setter=new NativeFunction(module.base.add(0x3cc30f0),'void',['pointer','int','pointer']);
setter(ptr('0x1'),1,ptr('0x0'));
const afterTrue=flag.readU8();
setter(ptr('0x1'),0,ptr('0x0'));
const afterFalse=flag.readU8();
send({schema:1,kind:'reporter-setter-probe',pid:Process.id,
  classInitializedBefore:true,initializer,setterGuard,
  inputTrue:1,inputFalse:0,before,afterTrue,afterFalse});
if(afterTrue!==0 || afterFalse!==0)
  throw new Error('Reporter setter changed enabled flag');
