"""Opt-in owned diagnostic that resolves otherwise unknown RootDirectory handles.

This calls GetFinalPathNameByHandleW on a handle already supplied by the target.
It reads handle metadata only; no file content, queue entry, or endpoint is opened.
It is an active metadata query, unlike the passive base observer.
"""
from __future__ import annotations

from tools.frida_attribution_clock import replace_once
from tools.frida_prelaunch_socket_exit370 import build_source as base_source

RESOLVER = r'''
// Query an existing directory handle once. The queried path is retained in
// process memory for selected-root comparison, never emitted on its own.
const rootResolveFailures=new Set();let rootResolveCalls=0,rootResolveFailed=0;
const getFinalPath=new NativeFunction(
  Process.getModuleByName('kernelbase.dll').getExportByName('GetFinalPathNameByHandleW'),
  'uint',['pointer','pointer','uint','uint']);
function resolveRoot(root) {
  const key=root.toString();
  if(rootResolveFailures.has(key))return null;
  rootResolveCalls++;
  try {
    const capacity=16384,buffer=Memory.alloc(capacity*2);
    const length=getFinalPath(root,buffer,capacity,0);
    if(length===0 || length>=capacity)throw new Error('root path unavailable');
    const path=buffer.readUtf16String(length);
    if(!path || path.length!==length)throw new Error('root path length differs');
    const parent={path,tracked:relevant(path)};
    files.set(key,parent);return parent;
  }catch (_) {rootResolveFailures.add(key);rootResolveFailed++;return null;}
}
'''


def build_source(config: dict) -> str:
    source = base_source(config)
    source = replace_once(source, 'function objectPath(p) {', RESOLVER + '\nfunction objectPath(p) {')
    source = replace_once(source,
                          'const parent=files.get(root.toString());\n    if(!parent){unknownRelativeRoots++;return null;}',
                          'const parent=files.get(root.toString()) || resolveRoot(root);\n    if(!parent){unknownRelativeRoots++;return null;}')
    source = replace_once(source,
                          'unknownRelativeRoots,overflow,socketHandles:{send:{...socketHandles.send},recv:{...socketHandles.recv}}}),5000);',
                          'unknownRelativeRoots,rootResolveCalls,rootResolveFailed,overflow,socketHandles:{send:{...socketHandles.send},recv:{...socketHandles.recv}}}),5000);')
    source = replace_once(source,
                          'unknownRelativeRoots,overflow,socketHandles:',
                          'unknownRelativeRoots,rootResolveCalls,rootResolveFailed,overflow,socketHandles:')
    return source
