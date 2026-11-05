"""Prepare a separate, opt-in advertising callback caller witness.

No launch/attach, target API invocation, argument/identity reads or gameplay
changes. Frida's entry hook does change live code: never combine this profile
with -telemetry-audit or -telemetry-device-probe. The owner must independently
bind the actual launch, module files, observation interval and process lifetime.
"""
import hashlib
import json
from pathlib import PureWindowsPath
import re

from client_patch.patcher.telemetry import patch_component, RECIPE_VERSION
from client_patch.patcher.patch_client import update_checksum
from tools.extract_descriptors import PE

CALLBACK_RVA = 0xc307c0
CALLBACK_SIZE = 0xb1  # Retained109/116 complete callback through c30871.
GUARD_RVA = 0xc30838
EVENT_LIMIT = 8
PROFILE = 'ads-caller180-v1'


def describe_unity(original, installed):
    """Bind complete installed bytes to the source recipe; never execute them."""
    expected = update_checksum(patch_component('UnityPlayer.dll', original))
    if installed != expected:
        raise ValueError('Installed Unity differs from the complete current recipe')
    pe = PE(installed)
    offset = pe.offset(pe.base + CALLBACK_RVA, CALLBACK_SIZE)
    guard = pe.offset(pe.base + GUARD_RVA, 5)
    if installed[guard:guard + 5] != b'\x90' * 5:
        raise ValueError('Advertising retention guard differs')
    return dict(recipe=RECIPE_VERSION,
                fileSha256=hashlib.sha256(installed).hexdigest(),
                bodySha256=hashlib.sha256(installed[offset:offset + CALLBACK_SIZE]).hexdigest())


def validate_config(config):
    keys = {'image', 'profile', 'argv', 'pid', 'runId', 'unity'}
    if not isinstance(config, dict) or set(config) != keys:
        raise ValueError('Exact caller witness configuration required')
    if any(not isinstance(config[k], str) for k in ('image', 'profile', 'runId')):
        raise ValueError('Caller witness paths/run identity must be strings')
    image, profile = PureWindowsPath(config['image']), PureWindowsPath(config['profile'])
    if not image.is_absolute() or image.drive.startswith('\\') or '..' in image.parts or \
            image.name != 'Battle Aces.exe' or not re.fullmatch(r'adscaller_[0-9a-f]{12}', image.parent.name) or \
            'local' not in image.parts or profile.parent != image.parent / '.battleaces-resurrection/profiles' or \
            not re.fullmatch(r'nativestest_adscaller_[0-9a-f]{12}', profile.name):
        raise ValueError('Separate owned local caller image/profile required')
    argv = config['argv']
    if not isinstance(argv, list) or not argv or argv[0] != config['image'] or \
            any(not isinstance(v, str) or '\0' in v for v in argv):
        raise ValueError('Exact owned launch argv required')
    if any(v.lower().startswith(('-telemetry-audit', '-telemetry-device-probe')) for v in argv):
        raise ValueError('Caller witness conflicts with native field audit/device probe')
    profile_args = [v for v in argv if v.lower().startswith('-local-profile')]
    if profile_args != ['-local-profile=' + profile.name]:
        raise ValueError('One matching owned launch profile required')
    if type(config['pid']) is not int or not 0 < config['pid'] < 2**32 or \
            not re.fullmatch('[0-9a-f]{32}', config['runId']):
        raise ValueError('Owned PID and run identity required')
    unity = config['unity']
    if not isinstance(unity, dict) or set(unity) != {'recipe', 'fileSha256', 'bodySha256'} or \
            type(unity['recipe']) is not int or unity['recipe'] != RECIPE_VERSION or \
            any(not isinstance(unity[k], str) or not re.fullmatch('[0-9a-f]{64}', unity[k])
                for k in ('fileSha256', 'bodySha256')):
        raise ValueError('Current full-file/body descriptor required')
    return str(image.parent / 'UnityPlayer.dll')


def build_source(config):
    module = validate_config(config)
    return SOURCE.replace('__CONFIG__', json.dumps(config)).replace('__MODULE__', json.dumps(module)) \
        .replace('__BODY_SIZE__', str(CALLBACK_SIZE)).replace('__LIMIT__', str(EVENT_LIMIT))


SOURCE = r'''// Standalone caller witness; incompatible with native field audit.
'use strict';
const config=__CONFIG__,selectedModule=__MODULE__,limit=__LIMIT__;
const normalize=p=>p.replace(/\//g,'\\').toLowerCase();
if(Process.arch!=='x64'||Process.pointerSize!==8||Process.id!==config.pid||
   normalize(Process.mainModule.path)!==normalize(config.image))throw new Error('owned image/PID differs');
let sequence=0,calls=0,records=0,installed=false,failed=false,finished=false;
let selected=null,listener=null,moduleObserver=null;
const started=Date.now();
function emit(kind,data){send({schema:1,seq:++sequence,runId:config.runId,pid:Process.id,
  tid:Process.getCurrentThreadId(),elapsedMs:Date.now()-started,kind,data});}
function snapshot(){return {installed,failed,finished,calls,records,suppressed:calls-records};}
function fail(code){
  if(failed||finished)return;
  failed=true;
  if(listener){listener.detach();listener=null;}
  emit('ads-error',{code});
}
function location(address){
  const m=Process.findModuleByAddress(address);
  return m?{module:m.name.toLowerCase(),rva:address.sub(m.base).toString()}:{module:null,rva:null};
}
function guardIntact(){
  const bytes=new Uint8Array(selected.base.add(0xc30838).readByteArray(5));
  return bytes.length===5&&bytes.every(v=>v===0x90);
}
emit('ads-ready',{profile:'ads-caller180-v1',fieldAuditCompatible:false,argumentsRead:false,targetApisInvoked:false});
moduleObserver=Process.attachModuleObserver({onAdded(module){
  if(module.name.toLowerCase()!=='unityplayer.dll'||finished||failed)return;
  try{
    if(installed){fail('module-reloaded');return;}
    if(normalize(module.path)!==normalize(selectedModule)){fail('module-path');return;}
    if(module.size<0xc307c0+__BODY_SIZE__){fail('module-size');return;}
    selected=module;
    if(Checksum.compute('sha256',module.base.add(0xc307c0).readByteArray(__BODY_SIZE__))!==config.unity.bodySha256||!guardIntact()){
      fail('body-or-guard');return;
    }
    listener=Interceptor.attach(module.base.add(0xc307c0),{onEnter(){
      if(finished||failed)return;
      try{
        if(!Number.isSafeInteger(calls+1)){fail('counter-overflow');return;}
        calls++;
        if(calls>limit)return;
        const caller=location(this.returnAddress);
        const frames=Thread.backtrace(this.context,Backtracer.ACCURATE).slice(0,8).map(location);
        records++;
        emit('ads-entry',{call:calls,caller,frames});
      }catch(_){fail('caller-decode');}
    }});
    installed=true;
    emit('ads-installed',{module:selectedModule,descriptor:config.unity,callbackRva:0xc307c0,bodySize:__BODY_SIZE__,eventLimit:limit});
  }catch(_){fail('install');}
},onRemoved(module){
  if(selected&&normalize(module.path)===normalize(selectedModule))fail('module-unloaded');
}});
rpc.exports={snapshot(){return snapshot();},finish(){
  if(finished)throw new Error('caller witness already finished');
  let guard=false;
  if(installed&&!failed){try{guard=guardIntact();}catch(_){}if(!guard)fail('final-guard');}
  if(listener){listener.detach();listener=null;}
  moduleObserver.detach();
  finished=true;
  const result={...snapshot(),guardIntact:guard,hookDetached:listener===null};
  emit('ads-finished',result);
  return result;
}};
'''


def validate(rows, config):
    """Validate a closed observation interval, never whole-process absence."""
    module = validate_config(config)
    def require(value, message):
        if not value:
            raise ValueError(message)
    def integer(v, minimum=0):
        return type(v) is int and minimum <= v <= 2**53 - 1
    def location(v):
        if not isinstance(v, dict) or set(v) != {'module', 'rva'}:
            return False
        if v == dict(module=None, rva=None):
            return True
        return isinstance(v['module'], str) and 1 <= len(v['module']) <= 256 and \
            v['module'] == v['module'].lower() and not any(c in v['module'] for c in '/\\\0') and \
            isinstance(v['rva'], str) and re.fullmatch('0x[0-9a-f]{1,16}', v['rva']) is not None
    require(isinstance(rows, list) and 3 <= len(rows) <= EVENT_LIMIT + 3, 'Bounded complete caller rows required')
    installed = False
    count = 0
    elapsed = -1
    for seq, row in enumerate(rows, 1):
        require(isinstance(row, dict) and set(row) == {'schema','seq','runId','pid','tid','elapsedMs','kind','data'}, 'Caller envelope differs')
        require(type(row['schema']) is int and row['schema'] == 1 and type(row['seq']) is int and row['seq'] == seq and
                type(row['pid']) is int and row['pid'] == config['pid'] and row['runId'] == config['runId'] and
                integer(row['tid'], 1) and row['tid'] < 2**32 and integer(row['elapsedMs']) and row['elapsedMs'] >= elapsed,
                'Caller identity/order differs')
        elapsed = row['elapsedMs']
        kind, data = row['kind'], row['data']
        require(isinstance(data, dict), 'Caller data differs')
        if seq == 1:
            require(kind == 'ads-ready' and data == dict(profile=PROFILE,fieldAuditCompatible=False,argumentsRead=False,targetApisInvoked=False)
                    and all(data[k] is False for k in ('fieldAuditCompatible','argumentsRead','targetApisInvoked')), 'Caller ready contract differs')
        elif kind == 'ads-installed':
            require(seq == 2 and not installed and data == dict(module=module,descriptor=config['unity'],callbackRva=CALLBACK_RVA,
                    bodySize=CALLBACK_SIZE,eventLimit=EVENT_LIMIT) and all(type(data[k]) is int for k in ('callbackRva','bodySize','eventLimit'))
                    and type(data['descriptor']['recipe']) is int, 'Caller installation differs')
            installed = True
        elif kind == 'ads-entry':
            require(installed and set(data) == {'call','caller','frames'} and type(data['call']) is int and data['call'] == count+1 and
                    data['call'] <= EVENT_LIMIT and location(data['caller']) and isinstance(data['frames'],list) and len(data['frames']) <= 8 and
                    all(location(v) for v in data['frames']), 'Caller entry differs')
            count += 1
        elif kind == 'ads-finished':
            require(seq == len(rows) and installed and set(data) == {'installed','failed','finished','calls','records','suppressed','guardIntact','hookDetached'} and
                    data['installed'] is True and data['failed'] is False and data['finished'] is True and data['guardIntact'] is True and data['hookDetached'] is True and
                    integer(data['calls']) and integer(data['records']) and integer(data['suppressed']) and data['records'] == count == min(data['calls'],EVENT_LIMIT) and
                    data['suppressed'] == data['calls']-count, 'Caller final interval differs')
        else:
            raise ValueError('Unexpected/error caller row')
    require(rows[-1]['kind'] == 'ads-finished', 'Caller interval not closed')
    final = rows[-1]['data']
    return dict(passed=True, calls=final['calls'], caller_records=count, suppressed=final['suppressed'],
                producer_resolved=False, full_privacy_qualified=False, whole_process_coverage=False,
                scope='Explicitly stopped instrumented interval only; owner launch/files/lifetime require independent proof')
