"""Opt-in sanitized child command metadata on the existing passive SDK/I/O profile.

Command lines are parsed transiently; no raw command, option values, pipe names or
license values are emitted. Only a comparison with the caller's owned cache path
and a closed process-type vocabulary survive alongside existing process evidence.
"""
import json
from pathlib import PureWindowsPath
from tools.frida_sdk_startup import build_source as sdk_source
from tools.frida_attribution_clock import replace_once

PROFILE='webview-process-v1'
COMMAND=r'''const webviewExpectedCache=__CACHE__;
function webviewReadCommand(p,wide) {
  if(p.isNull())throw new Error('child command absent');
  let result='';for(let i=0;i<32767;i++) {
    const unit=wide?p.add(2*i).readU16():p.add(i).readU8();
    if(!unit)return result;result+=String.fromCharCode(unit);
  }
  throw new Error('unterminated bounded child command');
}
function webviewCommandFacts(command) {
  if(typeof command!=='string' || command.length>32767)throw new Error('bounded child command required');
  const args=[];let i=0;
  while(i<command.length) {
    while(i<command.length && /[ \t]/.test(command[i]))i++;
    if(i===command.length)break;
    let value='',quoted=false;
    while(i<command.length && (quoted || !/[ \t]/.test(command[i]))) {
      let slashes=0;while(command[i]==='\\'){slashes++;i++;}
      if(command[i]==='"') {
        value+='\\'.repeat(Math.floor(slashes/2));
        if(slashes%2){value+='"';i++;}
        else if(quoted && command[i+1]==='"'){value+='"';i+=2;}
        else{quoted=!quoted;i++;}
      } else {
        value+='\\'.repeat(slashes);
        if(i===command.length || (!quoted && /[ \t]/.test(command[i])))break;
        value+=command[i++];
      }
    }
    if(quoted)throw new Error('unclosed child command quote');
    args.push(value);if(args.length>256)throw new Error('child argument budget exceeded');
  }
  const normalize=p=>p.replace(/\\/g,'/').toLowerCase(),cache=[],names=new Set();let type=null;
  const known=['renderer','gpu-process','utility','crashpad-handler','broker','ppapi','zygote','network-service'];
  for(const a of args.slice(1)) {
    const m=/^(--[a-zA-Z0-9-]{1,64})(?:=|$)/.exec(a);if(m)names.add(m[1]);
    // Original Vuplex prepends '--' to its stored '--vx-cache-path' key.
    if(a.startsWith('----vx-cache-path='))cache.push(a.slice('----vx-cache-path='.length));
    if(a.startsWith('--type=')){const v=a.slice(7);type=known.includes(v)?v:'other';}
  }
  return {schema:1,argumentCount:args.length,optionNames:Array.from(names).sort(),processType:type,
    cacheFlagCount:cache.length,ownedCacheMatches:cache.length===1 && normalize(cache[0])===normalize(webviewExpectedCache)};
}
'''


def build_source(config,cwd,sdk=None,*,cache_path):
    if not isinstance(config,dict) or type(config.get('eventLimit')) is not int or not 100<=config['eventLimit']<=16384:
        raise ValueError('Bounded WebView event limit required')
    if not isinstance(cache_path,str) or '\0' in cache_path or not PureWindowsPath(cache_path).is_absolute():
        raise ValueError('Absolute owned cache path required')
    image=PureWindowsPath(config['image']);cache=PureWindowsPath(cache_path)
    if cache.name!='webview-cache' or cache.parent.parent!=image.parent/'.battleaces-resurrection/profiles' or not cache.parent.name.startswith('nativestest_'):
        raise ValueError('Exact owned profile cache required')
    # The browser proof keeps every selected operation, including repeated gate
    # opens. Its larger opt-in budget does not change any legacy profile limit.
    base=dict(config,eventLimit=min(config['eventLimit'],4096))
    source=sdk_source(base,cwd,sdk)
    source=replace_once(source,'const config='+json.dumps(base)+', api=',
                        'const config='+json.dumps(config)+', api=')
    source=replace_once(source,'// game API calls, payload/command-line/header/environment reads, or file writes.',
        '// game API calls, payload/header/environment reads, or file writes. Child command lines are parsed transiently below.')
    source=replace_once(source,'function hook(module,name,address) {',COMMAND.replace('__CACHE__',json.dumps(cache_path))+'\nfunction hook(module,name,address) {')
    old="this.record={operation:name,application:text(args[user?1:0],name.endsWith('W')),frames:frames(this.context)};"
    new=old+"\n          this.record.processMetadata=webviewCommandFacts(webviewReadCommand(args[user?2:1],name.endsWith('W')));\n          this.record.processMetadata.creationFlags=args[user?6:5].toUInt32();\n          this.record.processMetadata.inheritHandles=args[user?5:4].toInt32()!==0;\n          this.record.processMetadata.environmentInherited=args[user?7:6].isNull();\n          this.record.processMetadata.directoryInherited=args[user?8:7].isNull();"
    return replace_once(source,old,new)
