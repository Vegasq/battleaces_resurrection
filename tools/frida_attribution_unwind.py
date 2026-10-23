"""Opt-in observer-unwind provenance; retain operations and avoid recursive unwinds.

Depth marks the emitting thread inside this observer's ACCURATE backtrace call.
It does not classify unmarked activity or recover provenance from older captures.
Nested frame requests record the current PC explicitly instead of unwinding again.
Legacy observer builders and game patches remain unchanged.
"""
from tools.frida_attribution_cwd import build_source as cwd_source
from tools.frida_sdk_startup import build_source as sdk_source
from tools.frida_attribution_clock import replace_once

PROFILE = 'observer-unwind-v1'
ORIGINAL_FRAMES = '''function frames(context) {
  return Thread.backtrace(context,Backtracer.ACCURATE).slice(0,8).map(address=>{
    const module=Process.findModuleByAddress(address);
    return module?{module:module.name.toLowerCase(),rva:address.sub(module.base).toString()}:{module:null,rva:null};
  });
}'''
UNWIND = '''const observerUnwinds=new Map();
let observerUnwindsStarted=0,observerUnwindsCompleted=0,observerNestedPcFrames=0;
function observerUnwindSnapshot() {
  const current=observerUnwinds.get(Process.getCurrentThreadId());
  return {schema:1,depth:current?1:0,scopeId:current||0,
    started:observerUnwindsStarted,completed:observerUnwindsCompleted,
    activeScopes:observerUnwinds.size,nestedPcFrames:observerNestedPcFrames};
}
function observerFrame(address) {
  const module=Process.findModuleByAddress(address);
  return module?{module:module.name.toLowerCase(),rva:address.sub(module.base).toString()}:{module:null,rva:null};
}
function frames(context) {
  const tid=Process.getCurrentThreadId();
  if(observerUnwinds.has(tid)) {
    observerNestedPcFrames++;
    if(!context || !context.pc)throw new Error('nested frame current PC unavailable');
    return [observerFrame(context.pc)];
  }
  observerUnwinds.set(tid,++observerUnwindsStarted);
  try {return Thread.backtrace(context,Backtracer.ACCURATE).slice(0,8).map(observerFrame);}
  finally {observerUnwinds.delete(tid);observerUnwindsCompleted++;}
}'''


def build_source(config, cwd, sdk=None):
    source = cwd_source(config, cwd) if sdk is None else sdk_source(config, cwd, sdk)
    # Install state before attachModuleObserver can synchronously call handlers.
    source = replace_once(source, 'function emit(kind,data) {', UNWIND + '\nfunction emit(kind,data) {')
    source = replace_once(source, ORIGINAL_FRAMES, '')
    source = replace_once(source, 'elapsedMs:Date.now()-started,kind,data});',
                          'elapsedMs:Date.now()-started,kind,data,observerUnwind:observerUnwindSnapshot()});')
    return '// EXPLICIT OBSERVER UNWIND PROVENANCE: emit-time per-thread scope; nested frames use current PC.\n' + source
