"""Authored native-fault propagation control, never an arbitrary target caller.

The selected executable must be built from native_crash_control.cpp and owned
before attach. Its original main thread invokes the exception after its owner
creates a local gate file. The probe only observes; it calls no target API and
does not replace a handler or suppress OS policy.
"""
from __future__ import annotations
import json
import re
from pathlib import PureWindowsPath


def build_source(config):
    if not isinstance(config, dict) or set(config) != {'image', 'runId', 'pid', 'mainThread'}:
        raise ValueError('Exact owned control configuration required')
    image = config['image']
    if not isinstance(image, str) or not PureWindowsPath(image).is_absolute() or \
            PureWindowsPath(image).name != 'native_crash_control.exe' or any(ord(c) < 32 for c in image):
        raise ValueError('Owned authored control executable required')
    if not isinstance(config['runId'], str) or not re.fullmatch('[0-9a-f]{32}', config['runId']) or \
            any(type(config[k]) is not int or not 0 < config[k] < 2**32 for k in ('pid', 'mainThread')):
        raise ValueError('Owned identity and nonce required')
    return SOURCE.replace('__CONFIG__', json.dumps(config))


SOURCE = r'''// Passive witnesses for one original authored main-thread exception.
'use strict';
const config=__CONFIG__;
if(Process.arch!=='x64' || Process.pointerSize!==8 || Process.id!==config.pid ||
   Process.mainModule.path.toLowerCase()!==config.image.toLowerCase())throw new Error('owned control identity differs');
let seq=0, fired=false;
function emit(kind,data){send({schema:1,seq:++seq,runId:config.runId,pid:Process.id,
  thread:Process.getCurrentThreadId(),kind,data});}
const tick=Process.mainModule.getExportByName('CrashControlTick');
const entry=Process.mainModule.getExportByName('CrashControlInvoke');
const raise=Process.getModuleByName('kernel32.dll').getExportByName('RaiseException');
Interceptor.attach(raise,{onEnter(args){if(fired)emit('raise-entry',{
  code:args[0].toUInt32(),flags:args[1].toUInt32(),count:args[2].toUInt32(),nullArguments:args[3].isNull()});}});
Interceptor.attach(entry,{onEnter(){
  if(fired)throw new Error('duplicate control exception');
  if(Process.getCurrentThreadId()!==config.mainThread)throw new Error('original control thread differs');
  fired=true;emit('trigger',{target:'CrashControlInvoke',nativeCaller:true,mainThread:config.mainThread});
},onLeave(){emit('unexpected-return',{});}});
emit('control-ready',{mainThread:config.mainThread,tick:tick.toString(),entry:entry.toString(),
  handlerReplaced:false,errorModeChangedByObserver:false,targetApisInvoked:false});
'''
