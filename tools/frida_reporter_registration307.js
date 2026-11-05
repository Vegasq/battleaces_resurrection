// Owned recipe28 guard check. Calls only the patched void AddOnSendError RET.
'use strict';
const module=Process.getModuleByName('GameAssembly.dll');
const expected=Process.mainModule.path.replace(/[^\\]+$/, 'GameAssembly.dll').toLowerCase();
if(module.path.toLowerCase()!==expected)throw new Error('GameAssembly path differs');
const address=module.base.add(0x81b2b0);
const bytes=Array.from(new Uint8Array(address.readByteArray(16)))
  .map(x=>x.toString(16).padStart(2,'0')).join('');
if(bytes!=='c3895c2410574883ec40488bfa488bd9')
  throw new Error('AddOnSendError loaded guard/tail differs');
const call=new NativeFunction(address,'void',['pointer','pointer','pointer']);
call(ptr('0x1'),ptr('0x1'),ptr('0x0'));
send({schema:1,kind:'reporter-registration-guard',pid:Process.id,
  loadedBytes:bytes,borrowedUnreadable:true,returned:true});
