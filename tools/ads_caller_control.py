"""Own a finite authored native caller control; never load a real game DLL.

Run after build_ads_caller_control.ps1. An external REA session attaches to the
retained child PID,loads observer.js,and signals resume.flag then invoke.flag.
After retaining ads-finished and detaching REA,signal finish.flag. This owner
keeps process/job handles and requires natural exit. Artifacts stay in local/.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import secrets
import struct
import subprocess
import time

from tools.frida_ads_caller import build_source, validate, CALLBACK_RVA, CALLBACK_SIZE, GUARD_RVA, RECIPE_VERSION
from tools.extract_descriptors import PE
from tools.owned_suspended_launch import SuspendedChild
from tools.owned_job_tracker import OwnedJobTracker

ROOT=Path(__file__).resolve().parents[1]
CONTROL_STOP_ADAPTER="\nconst controlTimer=setInterval(()=>{if(rpc.exports.snapshot().calls===13){clearInterval(controlTimer);rpc.exports.finish();}},20);\n"


def rva_bytes(data,rva,size):
    header=struct.unpack_from('<I',data,60)[0]
    count=struct.unpack_from('<H',data,header+6)[0]
    section=header+24+struct.unpack_from('<H',data,header+20)[0]
    for i in range(count):
        start,length,offset=struct.unpack_from('<III',data,section+i*40+12)
        if start<=rva and rva+size<=start+length:
            result=data[offset+rva-start:offset+rva-start+size]
            if len(result)==size:return result
    raise ValueError('Fixture RVA not file-backed')


def own(folder):
    folder=Path(folder).resolve()
    if not folder.is_relative_to(ROOT/'local') or not re.fullmatch('adscaller_[0-9a-f]{12}',folder.name):
        raise ValueError('Owned control directory required')
    build=json.loads((folder/'build.json').read_bytes())
    if build.get('authored_fixture') is not True or build.get('game_code') is not False:
        raise ValueError('Authored fixture build receipt required')
    for name,sha in build['files'].items():
        if name not in ('Battle Aces.exe','UnityPlayer.dll') or hashlib.sha256((folder/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('Fixture build identity differs')
    if set(build['files'])!={'Battle Aces.exe','UnityPlayer.dll'}:raise ValueError('Exact fixture pair required')
    for name,sha in build['sources'].items():
        if name not in ('host.cpp','callback.asm') or hashlib.sha256((ROOT/'tests/fixtures/ads_caller181'/name).read_bytes()).hexdigest()!=sha:
            raise ValueError('Fixture source differs')
    for name in ('owner-ready.json','owner.json','resume.flag','invoke.flag','finish.flag','calls.json','finished.json'):
        if (folder/name).exists():raise ValueError('Fresh control lifetime required')
    data=(folder/'UnityPlayer.dll').read_bytes()
    body=rva_bytes(data,CALLBACK_RVA,CALLBACK_SIZE)
    if body != b'\x90'*16+bytes.fromhex('488d0411c3')+b'\x90'*(CALLBACK_SIZE-21) or rva_bytes(data,GUARD_RVA,5)!=b'\x90'*5:
        raise ValueError('Only the completely authored arithmetic fixture is executable here')
    descriptor=dict(recipe=RECIPE_VERSION,fileSha256=hashlib.sha256(data).hexdigest(),bodySha256=hashlib.sha256(body).hexdigest())
    profile='nativestest_adscaller_'+folder.name.removeprefix('adscaller_')
    command=[str(folder/'Battle Aces.exe'),'-local-profile='+profile]
    report=dict(passed=False,authored_fixture=True,game_executed=False,command=command,files=build['files'])
    child=None;tracker=None
    try:
        child=SuspendedChild.create(command,cwd=folder,creationflags=subprocess.CREATE_NO_WINDOW)
        tracker=OwnedJobTracker(child);tracker.observe()
        config=dict(image=command[0],profile=str(folder/'.battleaces-resurrection/profiles'/profile),argv=command,
                    pid=child.pid,runId=secrets.token_hex(16),unity=descriptor)
        source=build_source(config)
        # Only the native CONTROL adds this stop adapter: the MCP currently has
        # no RPC invocation operation. It polls our own counter,never target data.
        footer=CONTROL_STOP_ADAPTER
        observer=source+footer
        (folder/'observer.js').write_bytes(observer.encode('utf-8'))
        ready=dict(pid=child.pid,tid=child.tid,config=config,observer_sha256=hashlib.sha256(observer.encode()).hexdigest(),
                   generated_source_sha256=hashlib.sha256(source.encode()).hexdigest(),control_stop_adapter=footer)
        with (folder/'owner-ready.json').open('x') as f:json.dump(ready,f,indent=2)
        print(json.dumps(dict(pid=child.pid,folder=str(folder),ready=True)),flush=True)
        deadline=time.monotonic()+180
        while not (folder/'resume.flag').exists():
            if time.monotonic()>deadline:raise TimeoutError('Control resume not supplied')
            time.sleep(.05)
        child.resume()
        while child.poll() is None:
            tracker.observe()
            if time.monotonic()>deadline:raise TimeoutError('Control lifetime exceeded')
            time.sleep(.1)
        report.update(exit_code=child.poll(),tracker=tracker.settle(timeout=5),calls=json.loads((folder/'calls.json').read_bytes()),
                      final=json.loads((folder/'finished.json').read_bytes()),ready=ready)
        report['passed']=bool(report['exit_code']==0 and report['tracker']['complete'] and report['final']['entryAndGuardRestored'] is True)
    except BaseException as error:
        report['error']=repr(error)
        raise
    finally:
        if tracker:tracker.close()
        if child:
            child.close();report['launch']=child.receipt
        report['files_unchanged']=all(hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha for name,sha in build['files'].items())
        report['passed']=report['passed'] and report['files_unchanged'] and report.get('launch',{}).get('forced_cleanup') is False
        with (folder/'owner.json').open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps({k:report[k] for k in ('passed','exit_code','files_unchanged','launch')}),flush=True)


def review(folder):
    """Read retained evidence; bind real Frida calls to this authored host only."""
    folder=Path(folder)
    read=lambda name:json.loads((folder/name).read_bytes())
    def require(value,message):
        if not value:raise ValueError(message)
    owner,build=read('owner.json'),read('build.json')
    ready=read('owner-ready.json');config=ready['config']
    require(owner['passed'] is True and owner['authored_fixture'] is True and owner['game_executed'] is False,
            'Successful authored owner required')
    require(owner['ready']==ready and owner['command']==config['argv'] and owner['files']==build['files'], 'Owner launch/identity differs')
    require(owner['files_unchanged'] is True and owner['exit_code']==0 and type(owner['exit_code']) is int and
            owner['launch']['forced_cleanup'] is False and owner['launch']['owned_process_reaped'] is True and
            owner['launch']['pid']==config['pid']==ready['pid'] and owner['launch']['tid']==ready['tid'], 'Owned natural lifetime required')
    tracker=owner['tracker'];accounting=tracker['final_accounting']
    require(tracker['complete'] is True and tracker['errors']==[] and accounting['active']==0 and accounting['terminated']==0 and
            accounting['total']==len(tracker['records']) and tracker['root_pid']==ready['pid'] and
            all(r['exit']['wait_signaled'] is True and r['exit']['exit_code']==0 for r in tracker['records']), 'Complete unforced job evidence required')
    roots=[r for r in tracker['records'] if r['pid']==ready['pid']]
    require(len(roots)==1 and roots[0]['image']==config['image'], 'Owned root image differs')
    require(build['authored_fixture'] is True and build['game_code'] is False and
            set(build['files'])=={'Battle Aces.exe','UnityPlayer.dll'}, 'Authored build pair required')
    for name,sha in build['files'].items():
        require(hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha,'Fixture file changed')
    require(set(build['sources'])=={'host.cpp','callback.asm'}, 'Exact fixture sources required')
    for name,sha in build['sources'].items():
        require(hashlib.sha256((ROOT/'tests/fixtures/ads_caller181'/name).read_bytes()).hexdigest()==sha,'Fixture source changed')
    source=build_source(config)
    raw_source=(folder/'observer.js').read_bytes()
    canonical=(source+CONTROL_STOP_ADAPTER).encode()
    require(ready['control_stop_adapter']==CONTROL_STOP_ADAPTER and
            ready['generated_source_sha256']==hashlib.sha256(source.encode()).hexdigest() and
            ready['observer_sha256']==hashlib.sha256((source+CONTROL_STOP_ADAPTER).encode()).hexdigest() and
            raw_source in (canonical,canonical.replace(b'\n',b'\r\n')), 'Observer/adaptor source differs')
    dll=(folder/'UnityPlayer.dll').read_bytes();body=rva_bytes(dll,CALLBACK_RVA,CALLBACK_SIZE)
    require(config['unity']['fileSha256']==build['files']['UnityPlayer.dll'] and
            config['unity']['bodySha256']==hashlib.sha256(body).hexdigest() and
            body==b'\x90'*16+bytes.fromhex('488d0411c3')+b'\x90'*(CALLBACK_SIZE-21), 'Authored body descriptor differs')
    start_result,load_result,final_result=(read(n) for n in ('rea-start.json','rea-load.json','rea-final.json'))
    require(all(not r.get('isError',False) for r in (start_result,load_result,final_result)), 'REA operation error')
    started=start_result['structuredContent']
    loaded=load_result['structuredContent']
    evidence=final_result['structuredContent'];normalized=evidence['normalized_result']
    sid=started['session_id']
    for item,operation in ((loaded,'load_frida_script'),(evidence,'frida_session_status')):
        require(item['provider']['id']=='frida' and item['confidence']=='observed' and item['operation']==operation and
                item['parameters']['session_id']==sid and re.fullmatch('ev_[0-9a-f]{64}',item['evidence_id']), 'REA provider/session differs')
    require(started['pid']==normalized['pid']==ready['pid'] and started['mode']==normalized['mode']=='attach' and
            started['device_id']==normalized['device_id']=='local' and normalized['session_id']==sid and
            normalized['state']=='running' and normalized['messages_truncated'] is False and loaded['normalized_result']['messages_truncated'] is False,
            'REA target/truncation differs')
    script=loaded['normalized_result'];script_id=script['script_id']
    require(script['source_sha256']==hashlib.sha256(raw_source).hexdigest() and script['source_kind']=='file' and
            Path(script['source_path']).resolve()==(folder/'observer.js').resolve() and
            len(normalized['scripts'])==1 and normalized['scripts'][0]['script_id']==script_id, 'REA script identity differs')
    messages=normalized['messages']
    require(all(m['type']=='send' and m['script_id']==script_id for m in messages), 'Mixed/error native messages')
    rows=[m['payload'] for m in messages]
    require(messages[:len(script['messages'])]==script['messages'],'Load/final message prefix differs')
    result=validate(rows,config)
    require(result['calls']==13 and result['caller_records']==8 and result['suppressed']==5, 'Native control counts differ')
    calls=owner['calls'];final=owner['final']
    require(calls==read('calls.json') and final==read('finished.json') and
            calls['mainTid']==ready['tid'] and calls['workerTid']!=calls['mainTid'] and
            (calls['mainCalls'],calls['workerCalls'],calls['mainResult'],calls['workerExit'])==(6,7,252,0) and
            final==dict(afterDetachCalls=2,afterDetachResult=84,entryAndGuardRestored=True) and final['entryAndGuardRestored'] is True,
            'Authored native arithmetic/restoration differs')
    # Export binding and unwind range identify the immediate caller independently
    # of the Frida message's module/RVA claim.
    host=(folder/'Battle Aces.exe').read_bytes();pe=PE(host)
    header=struct.unpack_from('<I',host,60)[0];export_rva=struct.unpack_from('<I',host,header+24+112)[0]
    table=pe.offset(pe.base+export_rva,40)
    functions,names,ordinals=struct.unpack_from('<III',host,table+28)
    count=struct.unpack_from('<I',host,table+24)[0];entry=None
    for i in range(count):
        name_rva=struct.unpack('<I',rva_bytes(host,names+4*i,4))[0]
        offset=pe.offset(pe.base+name_rva)
        name=host[offset:host.index(b'\0',offset)]
        if name==b'AuthoredCaller':
            ordinal=struct.unpack('<H',rva_bytes(host,ordinals+2*i,2))[0]
            entry=struct.unpack('<I',rva_bytes(host,functions+4*ordinal,4))[0]
    require(entry is not None and pe.base+entry in pe.function_ends, 'Authored caller export/unwind missing')
    end=pe.function_ends[pe.base+entry]-pe.base
    events=[r for r in rows if r['kind']=='ads-entry']
    require([r['tid'] for r in events]==[calls['mainTid']]*6+[calls['workerTid']]*2, 'Native thread attribution differs')
    for row in events:
        caller=row['data']['caller']
        require(caller['module']=='battle aces.exe' and entry<=int(caller['rva'],16)<end and
                row['data']['frames'] and row['data']['frames'][0]==caller,'Native caller outside authored function')
    close=read('rea-close.json')
    require(not close.get('isError',False) and close['structuredContent']==dict(target_state='unknown'), 'REA detach receipt missing')
    return dict(passed=True,scope='Actual Frida on authored native arithmetic fixture; not game callback/producer qualification',
                calls=13,caller_records=8,suppressed=5,threads=2,post_detach_calls=2,caller_range=[hex(entry),hex(end)],
                natural_exit=0,job=accounting,files_unchanged=True,producer_resolved=False,game_executed=False,
                evidence_id=evidence['evidence_id'],observer_sha256=hashlib.sha256(raw_source).hexdigest(),
                normalized_source_sha256=ready['observer_sha256'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--review',action='store_true',help='read retained evidence only')
    args=parser.parse_args()
    if args.review:
        report=review(args.folder)
        with (args.folder/'verification.json').open('x') as f:json.dump(report,f,indent=2)
        print(json.dumps(report,indent=2))
    else:own(args.folder)
