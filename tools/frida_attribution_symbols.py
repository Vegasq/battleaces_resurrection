"""Opt-in loaded DbgHelp identity and native symbol-API dynamic extents.

Records only code/module/caller metadata, never arguments, symbol text or payloads.
Scopes are observed at emission; entries retain one direct return address without
unwinding. Counts continue after the bounded entry history. No API is invoked or
replaced. Legacy builders are unchanged.
"""
from tools.frida_attribution_unwind import build_source as unwind_source
from tools.frida_attribution_clock import replace_once

PROFILE='symbols-v1'
APIS=('SymInitialize','SymCleanup','SymFromAddr','StackWalk64')
LOAD_PROFILE='symbols-module-load-v1'
LOAD_APIS=APIS+('SymLoadModule64',)
SYMBOLS=r'''const symbolModules=[],symbolAddresses=new Map(),symbolStacks=new Map(),symbolErrors=[];
let symbolEntered=0,symbolReturned=0;
function symbolFrame(address) {
  const m=Process.findModuleByAddress(address);
  return m?{module:m.name.toLowerCase(),rva:address.sub(m.base).toString()}:{module:null,rva:null};
}
function symbolSnapshot(kind) {
  const full=['observer-ready','heartbeat','process-exit-entry'].includes(kind);
  return {schema:1,entered:symbolEntered,returned:symbolReturned,
    active:(symbolStacks.get(Process.getCurrentThreadId())||[]).map(s=>Object.assign({},s)),
    modules:full?symbolModules:null,errors:symbolErrors.slice()};
}
function symbolModule(m) {
  if(!['dbghelp.dll','dbghelp-x86_64.dll'].includes(m.name.toLowerCase()))return;
  if(symbolModules.some(v=>v.base===m.base.toString()))throw new Error('symbol module repeated');
  const info={id:symbolModules.length+1,name:m.name.toLowerCase(),path:m.path,base:m.base.toString(),size:m.size,
    exports:[],counts:{},history:[]};symbolModules.push(info);
  for(const name of ['SymInitialize','SymCleanup','SymFromAddr','StackWalk64']) {
    const address=m.findExportByName(name);if(!address)continue;
    const offset=address.sub(m.base).toUInt32();
    if(offset>m.size-16 || !address.equals(m.base.add(offset)))throw new Error('symbol export outside module');
    const entry={name,rva:offset,sha256:Checksum.compute('sha256',address.readByteArray(16))};info.exports.push(entry);info.counts[name]=0;
    if(symbolAddresses.has(address.toString())) {
      const original=symbolAddresses.get(address.toString());entry.aliasOf=original.key;entry.sha256=original.sha256;continue;
    }
    symbolAddresses.set(address.toString(),{key:info.id+':'+name,sha256:entry.sha256});
    Interceptor.attach(address,{
      onEnter() {
        try {
          const tid=Process.getCurrentThreadId(),stack=symbolStacks.get(tid)||[];
          if(stack.length>=16)throw new Error('symbol scope depth exceeded');
          const call={id:++symbolEntered,moduleId:info.id,api:name,caller:symbolFrame(this.returnAddress),
            observerUnwindDepth:observerUnwindSnapshot().depth};
          info.counts[name]++;this.symbolScope=call.id;stack.push(call);symbolStacks.set(tid,stack);
          if(info.history.filter(v=>v.api===name).length<8)info.history.push(Object.assign({tid},call));
        }catch(error){symbolErrors.push(String(error));}
      },
      onLeave() {
        try {
          if(!this.symbolScope)throw new Error('symbol return without entry');
          const tid=Process.getCurrentThreadId(),stack=symbolStacks.get(tid);
          if(!stack || stack[stack.length-1].id!==this.symbolScope)throw new Error('symbol scope return differs');
          stack.pop();if(!stack.length)symbolStacks.delete(tid);symbolReturned++;
        }catch(error){symbolErrors.push(String(error));}
      }
    });
  }
}
const symbolModuleObserver=Process.attachModuleObserver({onAdded(m){try{symbolModule(m);}catch(error){symbolErrors.push(String(error));}}});
'''


def build_source(config,cwd,sdk=None,*,include_module_load=False):
    if type(include_module_load) is not bool:
        raise TypeError('include_module_load must be bool')
    source=unwind_source(config,cwd,sdk)
    symbols=SYMBOLS
    if include_module_load:
        symbols=replace_once(symbols,"['SymInitialize','SymCleanup','SymFromAddr','StackWalk64']",
                             "['SymInitialize','SymCleanup','SymFromAddr','StackWalk64','SymLoadModule64']")
    source=replace_once(source,'function emit(kind,data) {',symbols+'\nfunction emit(kind,data) {')
    return replace_once(source,'observerUnwind:observerUnwindSnapshot()});',
                        'observerUnwind:observerUnwindSnapshot(),nativeSymbols:symbolSnapshot(kind)});')
