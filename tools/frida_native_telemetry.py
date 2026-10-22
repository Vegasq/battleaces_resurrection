"""Opt-in passive native identity/archive entry witnesses plus exit diagnostic.

No original collector is invoked and no inputs/payloads are read. The composed
exit profile retains its explicit200ms hold per self-termination entry.
"""
import json
import re
from pathlib import PureWindowsPath
from tools.frida_attribution_exit import build_source as exit_source
from tools.frida_attribution_clock import replace_once

ENTRIES={
    'ads.identity.callback':0xc307c0,'identity.field.writer':0xc416b0,
    'identity.fallback':0xc43ae0,'identity.cloud.user':0xc478c0,
    'device.payload.ctor':0xc49110,'device.hardware.query':0xc49dc0,
    'archive.owner.init':0xc58bf0,'archive.path.init':0xc5a610,
    'analytics.initialize':0xc3bb20,'archive.worker.flush':0xc51630,
    'archive.public.flush':0x207a80,'archive.lifecycle.a':0xc3d120,
    'archive.lifecycle.b':0xc3d1b0,
}
# The native read-only auditor independently recognizes this original prologue.
# Interceptor would alter it and disable the field audit;never call it count0.
OBSERVED=set(ENTRIES)-{'ads.identity.callback'}

WITNESSES=r'''
const nativeConfig=__NATIVE__;
const nativeObserved=__OBSERVED__;
let nativeInstalled=false;
const nativeCounts=Object.fromEntries(nativeObserved.map(name=>[name,0]));
function nativeSnapshot(){return {installed:nativeInstalled,counts:{...nativeCounts}};}
function nativeInstall(module) {
  if(module.name.toLowerCase()!=='unityplayer.dll')return;
  try {
    if(nativeInstalled || normalize(module.path)!==normalize(nativeConfig.module))throw new Error('native witness module/reload differs');
    for(const entry of nativeConfig.entries)
      if(Checksum.compute('sha256',module.base.add(entry.rva).readByteArray(16))!==entry.sha256)
        throw new Error('native witness prefix differs: '+entry.name);
    for(const entry of nativeConfig.entries.filter(e=>nativeObserved.includes(e.name)))
      Interceptor.attach(module.base.add(entry.rva),{onEnter(){
        const call=++nativeCounts[entry.name];
        if(call<=8)emit('native-telemetry-entry',{name:entry.name,call,frames:frames(this.context)});
      }});
    nativeInstalled=true;
    emit('native-telemetry-installed',{module:module.path,entries:nativeConfig.entries,
      observedEntries:nativeObserved,recognizedOnlyEntries:nativeConfig.entries.filter(e=>!nativeObserved.includes(e.name)).map(e=>e.name),
      entryEventLimitPerName:8,argumentsRead:false,collectorInvoked:false});
  }catch(error){errors.push('native witnesses: '+String(error));emit('decode-error',{api:'native-witness-install'});}
}
'''


def build_source(config,cwd,native):
    source=exit_source(config,cwd)
    image=PureWindowsPath(config['image'])
    if len(config['fileRoots'])<2:raise ValueError('Owned native-test profile required')
    profile=PureWindowsPath(config['fileRoots'][1])
    if profile.parent!=image.parent/'.battleaces-resurrection/profiles' or \
            not re.fullmatch(r'nativestest_[A-Za-z0-9_-]{1,70}',profile.name):
        raise ValueError('Owned native-test profile required')
    if not isinstance(native,dict) or set(native)!={'module','entries'} or \
            native['module']!=str(image.parent/'UnityPlayer.dll'):
        raise ValueError('Exact native module required')
    entries=native['entries']
    if not isinstance(entries,list) or len(entries)!=len(ENTRIES) or \
            any(not isinstance(e,dict) or set(e)!={'name','rva','sha256'} or e.get('name') not in ENTRIES or
                type(e.get('rva')) is not int or e['rva']!=ENTRIES[e['name']] or
                not isinstance(e.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',e['sha256']) for e in entries) or \
            len({e['name'] for e in entries})!=len(ENTRIES):
        raise ValueError('Exact unique native entry witnesses required')
    source=replace_once(source,'Process.attachModuleObserver({onAdded(module){',
        WITNESSES.replace('__NATIVE__',json.dumps(native)).replace('__OBSERVED__',json.dumps(sorted(OBSERVED)))+'\nProcess.attachModuleObserver({onAdded(module){\n  nativeInstall(module);')
    if source.count('resolvedCwdRoots,overflow')!=3:raise ValueError('Exit observer snapshot layout changed')
    return source.replace('resolvedCwdRoots,overflow','resolvedCwdRoots,nativeTelemetry:nativeSnapshot(),overflow')
