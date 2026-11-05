"""Count native device-I/O calls by handle/code without reading buffers."""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_unresolved_file_status373 import build_source as base_source


ADAPTER = r'''
// Owned passive diagnostic. NtDeviceIoControlFile is a selected user-mode
// boundary, not a kernel or whole-wire observer. Never read input/output data.
const deviceIo={calls:0,codes:{},errors:[],overflow:false};
const deviceIoSeen={};
const deviceIoAddress=Process.getModuleByName('ntdll.dll').getExportByName('NtDeviceIoControlFile');
Interceptor.attach(deviceIoAddress,{
  onEnter(args){
    this.bucket=null;
    deviceIo.calls++;
    try {
      const handle=args[0].toString(),code='0x'+args[5].toUInt32().toString(16);
      if(!Object.hasOwn(deviceIo.codes,code)) {
        if(Object.keys(deviceIo.codes).length>=128){deviceIo.overflow=true;return;}
        deviceIo.codes[code]={calls:0,success:0,pending:0,failure:0,
                              uniqueHandles:0,firstHandles:[]};
        deviceIoSeen[code]=new Set();
      }
      this.bucket=deviceIo.codes[code];this.bucket.calls++;
      if(!deviceIoSeen[code].has(handle)) {
        deviceIoSeen[code].add(handle);this.bucket.uniqueHandles++;
        if(this.bucket.firstHandles.length<8)this.bucket.firstHandles.push(handle);
      }
    }catch(error){if(deviceIo.errors.length<8)deviceIo.errors.push(String(error));else deviceIo.overflow=true;}
  },
  onLeave(value){
    if(!this.bucket)return;
    try {
      const status=value.toInt32();
      if(status===0x103)this.bucket.pending++;
      else if(status>=0)this.bucket.success++;
      else this.bucket.failure++;
    }catch(error){if(deviceIo.errors.length<8)deviceIo.errors.push(String(error));else deviceIo.overflow=true;}
  }
});
emit('device-io-armed',{api:'ntdll.dll:NtDeviceIoControlFile'});
'''


def build_source(config: dict) -> str:
    source = base_source(config)
    source = replace_once(source,
        "emit('observer-ready',{installed:installed.slice(),errors:errors.slice()});",
        ADAPTER + "\nemit('observer-ready',{installed:installed.slice(),errors:errors.slice()});")
    source = replace_once(source,
        "emit('self-terminate-entry',{api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),",
        "emit('self-terminate-entry',{deviceIo,api:name+':TerminateProcess',exitStatus:args[1].toUInt32(),")
    return source
