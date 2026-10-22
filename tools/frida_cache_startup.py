"""Explicit owned cache-root replacement plus existing metadata observation.

Unlike the passive base observer, this profile MUTATES one SDK getter entry and
calls IL2CPP string/GC-handle APIs lazily. Never changes Unity persistentDataPath.
Only prepared nativestest profiles beneath the selected game may be targeted.
"""
import json
import re
from pathlib import PureWindowsPath
from tools.frida_attribution_cwd import build_source as cwd_source
from tools.frida_attribution_clock import replace_once

ENTRIES={
    'Client.ctor':0x812690,'CacheManager.ctor':0x836660,
    'GetCachedEvent':0x837d10,'GetCachedSession':0x837db0,'GetCachedDeviceId':0x8368b0,
    'WriteFile':0x837740,'DeleteFile':0x837720,
    'Start.string':0x810660,'Start.config':0x8106f0,'AutoInit':0x80b370,
    'Reporter.Subs':0x3cc2140,'StartCached':0x81f730,
    'Process.MoveNext':0x8204c0,'Push.MoveNext':0x820de0,
    'RemoveExpiredPayloads':0x836b50,'CheckForDirectoryCreation':0x837850,
}
OBSERVED={'Client.ctor','CacheManager.ctor','GetCachedEvent','GetCachedSession','GetCachedDeviceId',
          'DeleteFile','RemoveExpiredPayloads','CheckForDirectoryCreation'}
ROOT_SHA='d547e382cad835bbf8f9587fc04aeca3d324dc47e0806e5957ccf7bb06bff003'
SHIM=r'''
const cacheConfig=__CACHE__;
const cacheObserved=__OBSERVED__;
const cacheCounts=Object.fromEntries(cacheObserved.map(name=>[name,0]));
let cacheInstalled=false,cacheCalls=0,cacheHandles=[];
function cacheSnapshot(){return {installed:cacheInstalled,calls:cacheCalls,gcHandles:cacheHandles.length,counts:{...cacheCounts}};}
function cacheAbort(reason) {
  errors.push('cache isolation: '+String(reason));emit('cache-isolation-failed',{reason:String(reason)});
  const stop=new NativeFunction(Process.getModuleByName('kernel32.dll').getExportByName('TerminateProcess'),'bool',['pointer','uint']);
  stop(ptr('0xffffffffffffffff'),1610);
  throw new Error('owned cache isolation terminated');
}
function cacheInstall(module) {
  if(module.name.toLowerCase()!=='gameassembly.dll')return;
  try {
    if(cacheInstalled || normalize(module.path)!==normalize(cacheConfig.module))throw new Error('cache module identity/reload differs');
    const root=module.base.add(0x8364e0);
    if(Checksum.compute('sha256',root.readByteArray(160))!==cacheConfig.rootSha)throw new Error('cache original root body differs');
    for(const entry of cacheConfig.entries)
      if(Checksum.compute('sha256',module.base.add(entry.rva).readByteArray(16))!==entry.sha256)throw new Error('cache witness entry differs: '+entry.name);
    const makeString=new NativeFunction(module.getExportByName('il2cpp_string_new_utf16'),'pointer',['pointer','int']);
    const makeHandle=new NativeFunction(module.getExportByName('il2cpp_gchandle_new'),'uint',['pointer','bool']);
    const getTarget=new NativeFunction(module.getExportByName('il2cpp_gchandle_get_target'),'pointer',['uint']);
    const literal=Memory.allocUtf16String(cacheConfig.root);
    const replacement=new NativeCallback(function(method) {
      let phase='entry';
      try {
        const call=++cacheCalls;
        if(!cacheInstalled || call>64)throw new Error('cache callback not armed/budget exceeded');
        // No IL2CPP call occurs during module addition. This managed getter's
        // calling thread now has an initialized runtime and attached context.
        phase='il2cpp_string_new_utf16';const value=makeString(literal,cacheConfig.root.length);
        if(value.isNull())throw new Error('cache managed String allocation failed');
        // Frida's native Boolean argument marshaller requires integer0/1.
        phase='il2cpp_gchandle_new';const handle=makeHandle(value,0);if(!handle)throw new Error('cache GC root allocation failed');
        cacheHandles.push(handle);
        phase='il2cpp_gchandle_get_target';const target=getTarget(handle);if(target.isNull() || !target.equals(value))throw new Error('cache GC root target differs');
        emit('cache-root-return',{call,gcHandles:cacheHandles.length,root:cacheConfig.root,genuineGcHandle:true});
        return target;
      }catch(error){cacheAbort(phase+': '+String(error.stack||error));return ptr(0);}
    },'pointer',['pointer']);
    Interceptor.replace(root,replacement);
    // Guarded RET entries are recognized, not intercepted: attaching to a
    // replacement RET can be unsupported and would disturb its exact bytes.
    for(const entry of cacheConfig.entries.filter(e=>cacheObserved.includes(e.name)))
      Interceptor.attach(module.base.add(entry.rva),{onEnter(){
        if(++cacheCounts[entry.name]>64)cacheAbort('cache witness call budget exceeded');
        emit('cache-sdk-entry',{name:entry.name,count:cacheCounts[entry.name]});
      }});
    cacheInstalled=true;
    emit('cache-root-installed',{module:module.path,root:cacheConfig.root,rootOriginalSha:cacheConfig.rootSha,
      entryRva:0x8364e0,entries:cacheConfig.entries.map(e=>({name:e.name,rva:e.rva,sha256:e.sha256})),
      observedEntries:cacheObserved,
      allCallingThreads:true,generalUnityPathReplaced:false,originalFallback:false});
  }catch(error){cacheAbort(error);}
}
'''


def build_source(config,cwd,cache):
    source=cwd_source(config,cwd)
    if len(config['fileRoots'])<2:raise ValueError('An owned profile file root is required')
    if not isinstance(cache,dict) or set(cache)!={'root','module','rootSha','entries'} or cache['rootSha']!=ROOT_SHA:
        raise ValueError('Exact supported cache-root contract required')
    image=PureWindowsPath(config['image']);profile=PureWindowsPath(config['fileRoots'][1])
    if (profile.parent!=image.parent/'.battleaces-resurrection/profiles' or
        not re.fullmatch(r'nativestest_[A-Za-z0-9_-]{1,70}',profile.name) or
        cache['root']!=str(profile/'queue123')+'/Bugsnag' or
        cache['module']!=str(image.parent/'GameAssembly.dll')):
        raise ValueError('Cache isolation requires the exact owned game profile root')
    entries=cache['entries']
    if not isinstance(entries,list) or len(entries)!=len(ENTRIES):raise ValueError('All SDK entry witnesses required')
    if any(not isinstance(e,dict) or set(e)!={'name','rva','sha256'} or
           e.get('name') not in ENTRIES or type(e.get('rva')) is not int or e['rva']!=ENTRIES[e['name']] or
           not isinstance(e.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',e['sha256']) for e in entries) or \
       len({e['name'] for e in entries})!=len(ENTRIES):raise ValueError('Exact unique SDK entry hashes required')
    source=replace_once(source,'// Metadata only; no NativeFunction, replacements, return/argument writes,\n// game API calls, payload/command-line/header/environment reads, or file writes.',
        '// EXPLICIT OWNED CACHE ISOLATION: replaces one SDK getter and lazily\n// calls String/GC-handle APIs. The underlying I/O observation remains metadata only.')
    source=replace_once(source,'Process.attachModuleObserver({onAdded(module){',
        SHIM.replace('__CACHE__',json.dumps(cache)).replace('__OBSERVED__',json.dumps(sorted(OBSERVED)))+'\nProcess.attachModuleObserver({onAdded(module){\n  cacheInstall(module);')
    if source.count('resolvedCwdRoots,overflow')!=2:raise ValueError('Observer snapshot layout changed')
    return source.replace('resolvedCwdRoots,overflow','resolvedCwdRoots,cache:cacheSnapshot(),overflow')
