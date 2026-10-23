"""Opt-in exact Unity log-function scope; code/caller metadata only, no arguments."""
import json,re
from pathlib import PureWindowsPath
from tools.frida_attribution_clock import replace_once
from tools.frida_attribution_symbols import build_source as symbols_source

PROFILE='unity-log-scope-v1'


def check_entry(entry):
    if not isinstance(entry,dict) or set(entry)!={'module','rva','sha256'}:
        raise ValueError('exact Unity log entry required')
    if not isinstance(entry['module'],str) or not PureWindowsPath(entry['module']).is_absolute() or \
       PureWindowsPath(entry['module']).name.lower()!='unityplayer.dll' or '\0' in entry['module']:
        raise ValueError('absolute UnityPlayer module required')
    if type(entry['rva']) is not int or not 0<=entry['rva']<=2**32-16 or \
       not isinstance(entry['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',entry['sha256']):
        raise ValueError('Unity log entry binding differs')


LOG_SCOPE=r'''const logEntrySpec=__LOG_ENTRY__,logStacks=new Map(),logErrors=[],logHistory=[];
let logEntered=0,logReturned=0,logInstalled=null;
function logScopeSnapshot() {
  return {schema:1,entered:logEntered,returned:logReturned,module:logInstalled,
    active:(logStacks.get(Process.getCurrentThreadId())||[]).map(c=>Object.assign({},c)),
    history:logHistory.slice(),errors:logErrors.slice()};
}
const logModuleObserver=Process.attachModuleObserver({onAdded(m) {
  if(m.name.toLowerCase()!=='unityplayer.dll')return;
  try {
    if(m.path.toLowerCase().replace(/\\/g,'/')!==logEntrySpec.module.toLowerCase().replace(/\\/g,'/'))throw new Error('foreign Unity log module');
    if(logInstalled)throw new Error('Unity log module repeated');
    if(logEntrySpec.rva+16>m.size)throw new Error('Unity log entry outside module');
    const address=m.base.add(logEntrySpec.rva),hash=Checksum.compute('sha256',address.readByteArray(16));
    if(hash!==logEntrySpec.sha256)throw new Error('Unity log entry prefix differs');
    Interceptor.attach(address,{
      onEnter() {
        try {
          const tid=Process.getCurrentThreadId(),stack=logStacks.get(tid)||[];
          if(stack.length>=16)throw new Error('Unity log scope depth exceeded');
          const call={id:++logEntered,caller:symbolFrame(this.returnAddress)};
          this.logScopeId=call.id;stack.push(call);logStacks.set(tid,stack);
          if(logHistory.length<8)logHistory.push(Object.assign({tid},call));
        }catch(error){logErrors.push(String(error));}
      },
      onLeave() {
        try {
          const tid=Process.getCurrentThreadId(),stack=logStacks.get(tid);
          if(!this.logScopeId || !stack || stack[stack.length-1].id!==this.logScopeId)throw new Error('Unity log scope return differs');
          stack.pop();if(!stack.length)logStacks.delete(tid);logReturned++;
        }catch(error){logErrors.push(String(error));}
      }
    });
    logInstalled={name:m.name.toLowerCase(),path:m.path,base:m.base.toString(),size:m.size,
      rva:logEntrySpec.rva,sha256:hash};
  }catch(error){logErrors.push(String(error));}
}});
'''


def build_source(config,cwd,sdk=None,*,entry):
    check_entry(entry)
    source=symbols_source(config,cwd,sdk,include_module_load=True)
    code=replace_once(LOG_SCOPE,'__LOG_ENTRY__',json.dumps(entry,separators=(',',':')))
    source=replace_once(source,'function emit(kind,data) {',code+'\nfunction emit(kind,data) {')
    return replace_once(source,'nativeSymbols:symbolSnapshot(kind)});',
                        'nativeSymbols:symbolSnapshot(kind),unityLogScope:logScopeSnapshot()});')
