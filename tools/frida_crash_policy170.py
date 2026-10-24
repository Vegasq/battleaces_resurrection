"""Opt-in crash/normal-Quit witnesses without observer stack unwinding.

Retains the old observer unchanged. Collects metadata at selected API boundaries,
not payloads or a kernel/wire trace. A 200ms terminal transport hold is explicit.
"""
import json
from tools.frida_native_crash import build_source as native_source
from tools.frida_attribution_clock import replace_once


def build_source(config, cwd, native):
    source = native_source(config, cwd, native)
    source = replace_once(source, 'function emit(kind,data) {',
                          "function emit(kind,data) {\n  if(kind==='file-operation' && policyScope()){policyFile(data);return;}")
    start = source.index('function frames(context) {')
    end = source.index('function endpoint(', start)
    source = source[:start] + 'function frames(context) { return null; } // deliberately uncollected\n' + source[end:]
    source = replace_once(source, 'function relevant(path) {',
                          'function relevant(path) {\n  if(policyScope())return true;')
    source = replace_once(source, "if(file && file.tracked && name!=='NtClose')",
                          "if(file && (file.tracked || policyScope()) && name!=='NtClose')")
    # Resolve every cwd root as before; avoid a duplicate event per symbol open.
    start = source.index("  emit('resolved-cwd-root',")
    end = source.index('\n  return {path:parentPath', start)
    source = source[:start] + source[end:]
    source = replace_once(source, "else if(name==='SymLoadModule64' && call<=128)",
                          "else if(name==='SymLoadModule64')")
    source = replace_once(source, "this.name=name;const call=++crashCounts[name];this.data=null;",
                          "this.name=name;const call=++crashCounts[name];this.data=null;\n      this.policySymbol=name.startsWith('Sym');if(this.policySymbol)policyPush();")
    source = replace_once(source, "onLeave(value){if(this.data)emit('crash-api-leave',{name,result:value.toString()});}",
                          "onLeave(value){if(this.data)emit('crash-api-leave',{name,result:value.toString()});if(this.policySymbol)policyPop();}")
    source = replace_once(source, 'const call=++crashCounts[label];this.call=call;',
                          "const call=++crashCounts[label];this.call=call;\n            if(label==='filter')policyPush();\n            if(label==='teardown')policyTeardown.call(this,args);")
    source = replace_once(source, "onLeave(value){emit('crash-native-leave',{label,call:this.call,result:value.toInt32()});}",
                          """onLeave(value){
          emit('crash-native-leave',{label,call:this.call,result:value.toInt32()});
          if(label==='teardown')policyOwner=null;
          if(label==='filter'){policySnapshot('filter-return');Thread.sleep(0.2);policyPop();}
        }""")
    source = replace_once(source, 'const crashConfig=', POLICY + '\nconst crashConfig=')
    source = replace_once(source, 'if(!crashModule)return null;',
                          'if(!crashModule || policyTornDown)return null;')
    # Add stream metadata; no socket buffers are read.
    source = replace_once(source, "} else if(name==='connect' || name==='WSAConnect'",
                          """} else if(name==='send' || name==='recv') {
          this.record={operation:name,requestedBytes:args[2].toUInt32(),frames:null};
        } else if(name==='connect' || name==='WSAConnect'""")
    start = source.index(', api=') + len(', api=')
    end = source.index(';', start)
    api = json.loads(source[start:end])
    for module in ('kernelbase.dll', 'kernel32.dll'):
        api.setdefault(module, []).append('TerminateProcess')
    source = source[:start] + json.dumps(api) + source[end:]
    source = replace_once(source, "if(name==='NtCreateFile' || name==='NtOpenFile') {",
                          """if(name==='TerminateProcess') {
          const self=args[0].equals(ptr('0xffffffffffffffff'));
          emit('policy-termination',{self,exitStatus:args[1].toUInt32(),caller:policyCaller(this.returnAddress)});
          if(self){policySnapshot('self-termination-entry');Thread.sleep(0.2);}
        } else if(name==='NtCreateFile' || name==='NtOpenFile') {""")
    source = replace_once(source, "emit('observer-ready',{installed:installed.slice(),errors:errors.slice()});",
                          "emit('observer-ready',{profile:'policy170',stackUnwinding:false,transportHoldMs:200,installed:installed.slice(),errors:errors.slice()});")
    return source


POLICY = r'''
const policyDepth=new Map(),policyFiles=new Map();let policyOwner=null,policyModeInstalled=false,policyTornDown=false;
let policyFileCount=0,policyFileOverflow=false;
function policyFile(data){
  const tid=Process.getCurrentThreadId(),key=JSON.stringify({tid,...data}),ordinal=++policyFileCount,ms=Date.now()-started;
  let row=policyFiles.get(key);
  if(!row){
    if(policyFiles.size>=8192){policyFileOverflow=true;return;}
    row={tid,...data,count:0,firstOrdinal:ordinal,lastOrdinal:ordinal,firstMs:ms,lastMs:ms};policyFiles.set(key,row);
  }
  row.count++;row.lastOrdinal=ordinal;row.lastMs=ms;
}
function policyScope(){return (policyDepth.get(Process.getCurrentThreadId())||0)>0;}
function policyPush(){const t=Process.getCurrentThreadId();policyDepth.set(t,(policyDepth.get(t)||0)+1);}
function policyPop(){const t=Process.getCurrentThreadId(),n=policyDepth.get(t)||0;if(n<1)throw new Error('scope underflow');policyDepth.set(t,n-1);}
function policyCaller(address){const m=Process.findModuleByAddress(address);return {module:m?m.name:null,rva:m?address.sub(m.base).toString():null};}
function policySnapshot(boundary){
  const rows=[...policyFiles.values()];
  for(let i=0;i<rows.length;i+=32)emit('policy-files',{boundary,offset:i,rows:rows.slice(i,i+32)});
  emit('policy-final',{boundary,counts:{...counts},crashCounts:{...crashCounts},
  installed:installed.slice(),errors:errors.slice(),unknownRelativeRoots,resolvedCwdRoots,overflow,
  stackUnwinding:false,transportHoldMs:200,scopeDepth:[...policyDepth.entries()],
  fileAggregate:{operations:policyFileCount,rows:rows.length,overflow:policyFileOverflow}});}
function policyTeardown(args){
  const b=crashModule.base,owner=args[0];
  policyOwner={pointer:owner.toString(),saved:owner.add(8).readU32(),expected:owner.add(0x40).readU32(),
    ownsGlobal:b.add(0x1d0e128).readPointer().equals(owner),caller:policyCaller(this.returnAddress),tid:Process.getCurrentThreadId()};
  emit('policy-teardown',policyOwner);
  if(['0x8052d4','0x8046f4'].includes(policyOwner.caller.rva))policyTornDown=true;
  if(policyModeInstalled)return;
  for(const [name,rva] of [['GetErrorMode',0x9f82be],['SetErrorMode',0x9f82cc]]){
    const instruction=b.add(rva);
    if(instruction.readU16()!==0x15ff)throw new Error('mode IAT instruction differs');
    const target=instruction.add(6).add(instruction.add(2).readS32()).readPointer();
    Interceptor.attach(target,{
      onEnter(args){
        this.selected=policyOwner!==null && policyOwner.tid===Process.getCurrentThreadId() && this.returnAddress.equals(instruction.add(6));
        if(this.selected)emit('policy-mode-enter',{name,requested:name==='SetErrorMode'?args[0].toUInt32():null,
          caller:policyCaller(this.returnAddress),owner:policyOwner});
      },
      onLeave(value){if(this.selected)emit('policy-mode-leave',{name,result:value.toUInt32()});}
    });
    emit('policy-mode-installed',{name,target:target.toString(),targetModule:policyCaller(target),returnRva:'0x'+(rva+6).toString(16)});
  }
  policyModeInstalled=true;
  Interceptor.flush();
}
'''
