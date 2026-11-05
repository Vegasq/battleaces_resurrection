// Read only: owned recipe27 reporter static-state snapshot at menu.
'use strict';
const module=Process.getModuleByName('GameAssembly.dll');
const expected=Process.mainModule.path.replace(/[^\\]+$/, 'GameAssembly.dll').toLowerCase();
if(module.path.toLowerCase()!==expected)throw new Error('GameAssembly path differs');
function hex(at,length) {
  return Array.from(new Uint8Array(at.readByteArray(length)))
    .map(x=>x.toString(16).padStart(2,'0')).join('');
}
const initializer=hex(module.base.add(0x3cc687c),10);
const setter=hex(module.base.add(0x3cc30fd),5);
if(initializer!=='c64118004883c4205fc3' || setter!=='b300907518')
  throw new Error('Reporter state guard bytes differ');
const klass=module.base.add(0x6b42b30).readPointer();
let state={schema:1,kind:'reporter-state',pid:Process.id,
  initializer,setter,classPointerPresent:!klass.isNull()};
if(!klass.isNull()) {
  state.classInitField=klass.add(0xe0).readU32();
  const fields=klass.add(0xb8).readPointer();
  state.staticFieldsPresent=!fields.isNull();
  if(!fields.isNull())state.enabledByte=fields.add(0x18).readU8();
}
send(state);
