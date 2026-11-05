"""Opt-in metadata classification for preexisting NtRead/Write/SetInformation handles."""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_resolved_file_source371 import build_source as base_source

PREEXISTING = r'''
// Resolve only a handle used for file I/O that was absent from the open map.
// GetFileType distinguishes known pipe/character handles from unresolved disk.
const fileResolveFailures=new Set();let fileResolveCalls=0,fileResolveFailed=0;
let nonDiskFileOps=0,unresolvedFileOps=0;
const getFileType=new NativeFunction(
  Process.getModuleByName('kernelbase.dll').getExportByName('GetFileType'),
  'uint',['pointer']);
function resolveFileHandle(handle) {
  const key=handle.toString();
  if(fileResolveFailures.has(key)){unresolvedFileOps++;return null;}
  fileResolveCalls++;
  try {
    const capacity=16384,buffer=Memory.alloc(capacity*2);
    const length=getFinalPath(handle,buffer,capacity,0);
    if(length===0 || length>=capacity)throw new Error('file path unavailable');
    const path=buffer.readUtf16String(length);
    if(!path || path.length!==length)throw new Error('file path length differs');
    const file={path,tracked:relevant(path)};
    files.set(key,file);return file;
  }catch (_) {
    const type=getFileType(handle);
    if(type===2 || type===3){
      const file={path:null,tracked:false,nonDisk:true};
      files.set(key,file);return file;
    }
    fileResolveFailures.add(key);fileResolveFailed++;unresolvedFileOps++;return null;
  }
}
'''


def build_source(config: dict) -> str:
    source = base_source(config)
    source = replace_once(source, 'function objectPath(p) {', PREEXISTING + '\nfunction objectPath(p) {')
    source = replace_once(source,
                          "this.handle=args[0].toString();const file=files.get(this.handle);\n          if(file && file.tracked && name!=='NtClose')",
                          "this.handle=args[0].toString();\n          const file=files.get(this.handle) || (name==='NtClose'?null:resolveFileHandle(args[0]));\n          if(file && file.nonDisk)nonDiskFileOps++;\n          if(file && file.tracked && name!=='NtClose')")
    source = replace_once(source,
                          "if(name==='NtClose' && status>=0 && this.handle)files.delete(this.handle);",
                          "if(name==='NtClose' && status>=0 && this.handle){files.delete(this.handle);rootResolveFailures.delete(this.handle);fileResolveFailures.delete(this.handle);}")
    source = replace_once(source,
                          'rootResolveFailed,overflow,socketHandles:{send:{...socketHandles.send},recv:{...socketHandles.recv}}}),5000);',
                          'rootResolveFailed,fileResolveCalls,fileResolveFailed,nonDiskFileOps,unresolvedFileOps,overflow,socketHandles:{send:{...socketHandles.send},recv:{...socketHandles.recv}}}),5000);')
    source = replace_once(source,
                          'rootResolveFailed,overflow,socketHandles:',
                          'rootResolveFailed,fileResolveCalls,fileResolveFailed,nonDiskFileOps,unresolvedFileOps,overflow,socketHandles:')
    return source
