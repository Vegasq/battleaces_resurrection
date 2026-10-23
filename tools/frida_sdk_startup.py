"""Passive SDK constructor/cache witnesses without an SDK-root replacement.

Metadata-only entry counters for ordinary installed startup. The composed exit
diagnostic still holds each self-TerminateProcess entry for200ms. No constructor,
collector,queue reader or target API is invoked by this observer. This is selected
API/function coverage,not kernel,descendant or complete privacy qualification.
"""
import json
import re
from pathlib import PureWindowsPath
from tools.frida_attribution_exit import build_source as exit_source
from tools.frida_attribution_clock import replace_once

ENTRIES={
    'Client.ctor':0x812690,'NativeClient.ctor':0x834b50,
    'CacheManager.ctor':0x836660,'CacheRoot':0x8364e0,
    'GetCachedDeviceId':0x8368b0,'GetCachedEvent':0x837d10,
    'GetCachedSession':0x837db0,'DeleteFile':0x837720,
    'RemoveExpiredPayloads':0x836b50,'CheckForDirectoryCreation':0x837850,
    'SendPayloadFailed':0x824b60,'CacheSession':0x824e20,'CacheEvent':0x824f70,
}

WITNESSES=r'''
const sdkConfig=__SDK__;
let sdkInstalled=false;
const sdkCounts=Object.fromEntries(sdkConfig.entries.map(entry=>[entry.name,0]));
function sdkSnapshot(){return {installed:sdkInstalled,counts:{...sdkCounts}};}
function sdkInstall(module) {
  if(module.name.toLowerCase()!=='gameassembly.dll')return;
  try {
    if(sdkInstalled || normalize(module.path)!==normalize(sdkConfig.module))throw new Error('SDK module/reload differs');
    // Verify all entries before installing any interceptor. Guarded RET entry
    // points are deliberately absent;their original patch audit stays intact.
    for(const entry of sdkConfig.entries)
      if(Checksum.compute('sha256',module.base.add(entry.rva).readByteArray(16))!==entry.sha256)
        throw new Error('SDK entry prefix differs: '+entry.name);
    for(const entry of sdkConfig.entries)
      Interceptor.attach(module.base.add(entry.rva),{onEnter(){
        const call=++sdkCounts[entry.name];
        if(call<=8)emit('sdk-entry',{name:entry.name,call,frames:frames(this.context)});
      }});
    sdkInstalled=true;
    emit('sdk-installed',{module:module.path,entries:sdkConfig.entries,
      entryEventLimitPerName:8,argumentsRead:false,targetApisInvoked:false,
      sdkRootReplaced:false,generalUnityPathReplaced:false});
  }catch(error){errors.push('SDK witnesses: '+String(error));emit('decode-error',{api:'sdk-witness-install'});}
}
'''


def build_source(config,cwd,sdk):
    source=exit_source(config,cwd)
    image=PureWindowsPath(config['image'])
    if len(config['fileRoots'])<2:
        raise ValueError('Owned native-test profile required')
    profile=PureWindowsPath(config['fileRoots'][1])
    if profile.parent!=image.parent/'.battleaces-resurrection/profiles' or \
            not re.fullmatch(r'nativestest_[A-Za-z0-9_-]{1,70}',profile.name):
        raise ValueError('Owned native-test profile required')
    if not isinstance(sdk,dict) or set(sdk)!={'module','entries'} or \
            sdk['module']!=str(image.parent/'GameAssembly.dll'):
        raise ValueError('Exact SDK module required')
    entries=sdk['entries']
    if not isinstance(entries,list) or len(entries)!=len(ENTRIES) or \
            any(not isinstance(e,dict) or set(e)!={'name','rva','sha256'} or
                e.get('name') not in ENTRIES or type(e.get('rva')) is not int or
                e['rva']!=ENTRIES[e['name']] or not isinstance(e.get('sha256'),str) or
                not re.fullmatch('[0-9a-f]{64}',e['sha256']) for e in entries) or \
            len({e['name'] for e in entries})!=len(ENTRIES):
        raise ValueError('Exact unique SDK entry witnesses required')
    source=replace_once(source,'Process.attachModuleObserver({onAdded(module){',
        WITNESSES.replace('__SDK__',json.dumps(sdk))+
        '\nProcess.attachModuleObserver({onAdded(module){\n  sdkInstall(module);')
    if source.count('resolvedCwdRoots,overflow')!=3:
        raise ValueError('Exit observer snapshot layout changed')
    return source.replace('resolvedCwdRoots,overflow','resolvedCwdRoots,sdk:sdkSnapshot(),overflow')
