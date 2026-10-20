"""Canonical passive native-entry observer source. Never launch or attach a target.

Reviewed build37822/recipe4 sites only. Prefix guards are safety checks, not
complete instruction blocks. Frida performs relocation; silent counts are not
proof of no collection or traffic. External owners control all target lifetimes.
"""
from __future__ import annotations
import json
from pathlib import PureWindowsPath
import re
from tools.frida_control_source import TEMPLATE

ENTRIES = {
    'unityplayer.dll': (
        (0xc49110, 'device_payload_constructor', '40555356574154415541564157488d6c'),
        (0xc49dc0, 'hardware_fill_collector', '488bc45641554881ec38030000488958'),
        (0xc300f0, 'internal_configuration_processor', '405553488dac24f8feffff4881ec0802'),
        (0xc3a680, 'configuration_drain', '40555356574154415541564157488dac'),
        (0xc2e5a0, 'worker_state_transition_callback', '40574883ec200fb681c3000000488bf9'),
        (0xc3b990, 'analytics_state_transition_dispatch', '40534883ec204532c0488bd9443881c4'),
        (0xc40840, 'device_payload_build_and_compare', '885424105553564154488dac2448f8ff'),
        (0xc48fa0, 'device_identity_cache_compare', '48895c240848896c2410488974241857'),
        (0xc402d0, 'analytics_worker_dispatch', '40534883ec304d8bd0488bd933c0f00f'),
        (0xc2f640, 'registered_connection_state_callback', '48895c2410564883ec608bf2488bd985'),
        (0xc3b1f0, 'configuration_request_continuation', '40555356574154488d6c24e04881ec20'),
        (0xc38c80, 'queueevent_adapter_before_guarded_sink', '4055535657415441554157488dac2440'),
        (0xc21b20, 'continuous_event_collector_registration', '48895c242055415641574883ec40488b'),
    ),
    'gameassembly.dll': ((0x3de4820, 'RGameSingleton.OnDestroy', '48895c2408574883ec20803dd5550703'),),
}
SIZES = {'unityplayer.dll': 31817728, 'gameassembly.dll': 124194816}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def validate_config(config):
    require(set(config)=={'image','runId','journal','native'}, 'observer configuration keys differ')
    image=PureWindowsPath(config['image']);journal=PureWindowsPath(config['journal'])
    require(image.is_absolute() and image.name=='Battle Aces.exe' and
            journal.is_absolute() and journal.name=='events.jsonl', 'absolute selected image/journal required')
    require(isinstance(config['runId'],str) and re.fullmatch('[0-9a-f]{32}',config['runId']), 'invalid run nonce')
    require(set(config['native'])==set(ENTRIES), 'reviewed native modules required')
    for name,entries in ENTRIES.items():
        module=config['native'][name]
        require(set(module)=={'path','size','entries'} and module['size']==SIZES[name] and
                PureWindowsPath(module['path'])==image.parent/name, 'native module identity differs')
        require(module['entries']==[dict(rva=rva,name=label,guard=guard) for rva,label,guard in entries],
                'reviewed native entries/guards differ')


def build_source(config):
    validate_config(config)
    source=TEMPLATE.replace('__CONFIG__',json.dumps(config))
    start=source.index('function snapshot(kind) {');end=source.index('\nfunction hook(',start)
    source=source[:start]+'''let sequence=0;
const handles=[],loadedNative=[];
const expectedNative=Object.entries(config.native).flatMap(([module,value])=>value.entries.map(entry=>module+':'+entry.name));
function snapshot(kind) {
  const row={schema:2,sequence:++sequence,runId:config.runId,kind,pid:Process.id,
    thread:Process.getCurrentThreadId(),architecture:Process.arch,pointerSize:Process.pointerSize,
    elapsedMs:Date.now()-started,counts:Object.assign({},counts),installed:installed.slice(),
    loaded:loaded.slice(),loadedNative:loadedNative.slice(),errors:errors.slice(),
    nativeReady:expectedNative.every(key=>installed.some(entry=>entry.key===key && entry.guarded===true)) && errors.length===0};
  try {const file=new File(config.journal,'a');try {file.write(JSON.stringify(row)+'\\n');file.flush();}finally{file.close();}}
  catch(error) {errors.push('Journal write failed: '+String(error));row.errors=errors.slice();}
  send(row);
}'''+source[end:]
    old="""  const handle=Interceptor.attach(address,{
    onEnter() {
      counts[key]=(counts[key]||0)+1;
      if(counts[key]===1) snapshot('first-call:'+key);
      if (name==='RGameSingleton.OnDestroy' || name==='RtlExitUserProcess') snapshot('lifecycle-enter:'+name);
    }
  });
  seen.add(address.toString());
  counts[key]=0;installed.push({key,offset:address.sub(module.base).toString()});"""
    new="""  counts[key]=0;
  const callbacks={onEnter() {
    counts[key]++;
    if(counts[key]===1) snapshot('first-call:'+key);
    if(name==='RGameSingleton.OnDestroy' || name==='RtlExitUserProcess') snapshot('lifecycle-enter:'+name);
  }};
  if(name==='RGameSingleton.OnDestroy')callbacks.onLeave=function(){snapshot('lifecycle-return:'+name);};
  const handle=Interceptor.attach(address,callbacks);handles.push(handle);
  seen.add(address.toString());
  installed.push({key,offset:address.sub(module.base).toString(),guarded:guard!==null,guardHex:guard});"""
    require(source.count(old)==1, 'base hook template changed');source=source.replace(old,new)
    old="""        if(module.path.toLowerCase()!==native.path.toLowerCase())throw new Error('Native module path differs: '+lower);
        for(const entry of native.entries)hook(module,entry.name,module.base.add(entry.rva),entry.guard);"""
    new="""        if(module.path.toLowerCase()!==native.path.toLowerCase() || module.size!==native.size)throw new Error('Native module path/size differs: '+lower);
        loadedNative.push({name:lower,path:module.path,size:module.size});
        for(const entry of native.entries)hook(module,entry.name,module.base.add(entry.rva),entry.guard);"""
    require(source.count(old)==1, 'base module template changed');source=source.replace(old,new)
    source=source.replace('// Passive call counters only. No NativeFunction, arguments, payload reads,\n// return-value changes, replacements, or game API activation.',
        '// Owned counter observation with a public diagnostic journal.\n// No NativeFunction, arguments/payload reads, return changes or game API activation.')
    return source


def matches_source(raw, config):
    canonical=build_source(config)
    return raw in (canonical.encode('utf-8'),canonical.replace('\n','\r\n').encode('utf-8'))
