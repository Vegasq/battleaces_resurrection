"""Owned native settings flush/publication failure, retry, normal Quit and restart.

REA injects a failed API result after the real flush returns, only for helper
calls on this profile's ba-*.tmp files. This is not a physical storage failure.
Publication mode instead acquires a real non-delete-sharing destination handle
immediately before the original rename, observes its refusal, then closes it.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time
import traceback

from client_patch.transport import launcher
from server.worker_client import _WindowsJob
from tools import verify_unified_startup as startup,verify_native_quit as quit_probe
from tools.verify_packaged_play import job_accounting
from tools.verify_native_storage import snapshot
from tools.run_secure_match import read_native_log
from tools.owned_suspended_launch import SuspendedChild

ROOT=Path(__file__).resolve().parents[1]
require=startup.require
SOURCE=r'''
const cfg=__CONFIG__;
if(Process.id!==cfg.pid)throw new Error('owned PID differs');
let helper=cfg.firstSave?null:Process.getModuleByName('BattleAcesOffline.dll');
if(helper&&helper.path.toLowerCase()!==cfg.helper.toLowerCase())throw new Error('helper path differs');
const kernel=Process.getModuleByName('kernel32.dll');
const moduleHandle=new NativeFunction(kernel.getExportByName('GetModuleHandleW'),'pointer',['pointer']);
const moduleName=new NativeFunction(kernel.getExportByName('GetModuleFileNameW'),'uint32',['pointer','pointer','uint32']);
const helperName=Memory.allocUtf16String('BattleAcesOffline.dll');
const pathOf=new NativeFunction(kernel.getExportByName('GetFinalPathNameByHandleW'),'uint32',['pointer','pointer','uint32','uint32']);
const clock=new NativeFunction(kernel.getExportByName('GetTickCount64'),'uint64',[]);
const openTarget=new NativeFunction(kernel.getExportByName('CreateFileW'),'pointer',['pointer','uint32','uint32','pointer','uint32','uint32','pointer']);
const closeTarget=new NativeFunction(kernel.getExportByName('CloseHandle'),'int',['pointer']);
const fileSize=new NativeFunction(kernel.getExportByName('GetFileSizeEx'),'int',['pointer','pointer']);
const targetName=Memory.allocUtf16String(cfg.folder+'\\gameconfig-localuser.toml');
const flushed=new Set();
const journal=new File(cfg.journal,'w');let sequence=0;
function emit(kind,data={}){const r={kind,pid:Process.id,sequence:++sequence,tick:Number(clock()),...data};journal.write(JSON.stringify(r)+'\n');journal.flush();send(r);}
function bindHelper(){
 const base=moduleHandle(helperName);if(base.isNull())return;
 const buffer=Memory.alloc(65536),n=moduleName(base,buffer,32768);
 if(n===0||n>=32768||buffer.readUtf16String(n).toLowerCase()!==cfg.helper.toLowerCase()){
  emit('error',{message:'early helper module path differs'});return;
 }
 const pe=base.add(base.add(0x3c).readU32());
 if(base.readU16()!==0x5a4d||pe.readU32()!==0x4550||pe.add(24).readU16()!==0x20b){emit('error',{message:'early helper PE differs'});return;}
 const size=pe.add(24+56).readU32();if(size<4096||size>64*1024*1024){emit('error',{message:'early helper extent differs'});return;}
 helper={base,size};emit('helper-bound',{binding:'GetModuleHandleW',size});
}
function selected(context,handle){
 if(helper===null&&cfg.firstSave)bindHelper();
 if(helper===null)return false;
 if(context.returnAddress.compare(helper.base)<0||context.returnAddress.compare(helper.base.add(helper.size))>=0)return false;
 const buffer=Memory.alloc(65536);const n=pathOf(handle,buffer,32768,0);
 if(n===0||n>=32768){emit('error',{message:'helper flush handle path unavailable'});return false;}
 let path=buffer.readUtf16String(n);if(path.startsWith('\\\\?\\'))path=path.slice(4);
 const prefix=cfg.folder+'\\';
 if(!path.toLowerCase().startsWith(prefix.toLowerCase()))return false;
 const name=path.slice(prefix.length);
 return /^ba-[0-9a-f]{8}-[0-9a-f]{8}\.tmp$/i.test(name)?path:false;
}
const hooks=[];
function canonical(path){return path.replace(/^\\\\\?\\/,'').toLowerCase()===(cfg.folder+'\\gameconfig-localuser.toml').toLowerCase();}
if(cfg.firstSave){
 hooks.push(Interceptor.attach(kernel.getExportByName('CreateFileW'),{
  onEnter(args){this.target=false;if(args[0].isNull())return;
   this.target=canonical(args[0].readUtf16String());if(!this.target)return;
   if(helper===null)bindHelper();this.disposition=args[4].toUInt32();this.caller=this.returnAddress.toString();
  },
  onLeave(retval){if(!this.target)return;const error=this.lastError,success=!retval.equals(ptr(-1));let size=null;
   if(success){const buffer=Memory.alloc(8);if(fileSize(retval,buffer))size=Number(buffer.readU64());}
   emit('target-open',{disposition:this.disposition,success,error,size,caller:this.caller});this.lastError=error;
  }
 }));
 hooks.push(Interceptor.attach(kernel.getExportByName('WriteFile'),{
  onEnter(args){this.target=false;const buffer=Memory.alloc(65536),n=pathOf(args[0],buffer,32768,0);
   if(n===0||n>=32768||!canonical(buffer.readUtf16String(n)))return;
   this.target=true;this.bytes=args[2].toUInt32();
  },
  onLeave(retval){if(this.target)emit('target-write',{requested:this.bytes,result:retval.toInt32()});}
 }));
}
hooks.push(Interceptor.attach(kernel.getExportByName('FlushFileBuffers'),{
 onEnter(args){this.path=selected(this,args[0]);},
 onLeave(retval){if(this.path){const original=retval.toInt32();
  if(cfg.fault==='publication'){if(original===1)flushed.add(this.path);emit('flush-completed',{path:this.path,result:original});}
  else {retval.replace(0);this.lastError=29;emit('flush-failed',{path:this.path,original,result:0,error:29});}
 }}
}));
hooks.push(Interceptor.attach(kernel.getExportByName('SetFileInformationByHandle'),{
 onEnter(args){
  this.lock=null;if(args[1].toInt32()!==3)return;
  this.path=selected(this,args[0]);if(!this.path)return;
  if(cfg.fault!=='publication'){emit('unexpected-rename',{path:this.path});return;}
  const info=args[2],length=info.add(16).readU32();
  if(!flushed.has(this.path)||info.readU8()!==1||!info.add(8).readPointer().isNull()||length===0||length%2||length>65534||args[3].toUInt32()<20+length||
     info.add(20).readUtf16String(length/2).toLowerCase()!==(cfg.folder+'\\gameconfig-localuser.toml').toLowerCase()){
   emit('error',{message:'rename target/flush boundary differs'});return;
  }
  this.lock=openTarget(targetName,0x80000000,3,ptr(0),3,0x00200080,ptr(0));
  if(this.lock.equals(ptr(-1))){this.lock=null;emit('error',{message:'late target lock failed'});return;}
  emit('target-locked',{path:this.path,share:3});
 },
 onLeave(retval){if(this.lock){const error=this.lastError,result=retval.toInt32();
  const closed=closeTarget(this.lock);this.lock=null;this.lastError=error;
  emit('publication-refused',{path:this.path,result,error,lock_closed:closed===1});flushed.delete(this.path);
 }}
}));
Interceptor.flush();emit('armed');
'''


def fault_evidence(rows,pid,fault='flush',first_save=False):
    require(rows and all(r['pid']==pid and r['sequence']==i+1 for i,r in enumerate(rows)), 'flush journal identity/order differs')
    if fault=='publication':
        require(rows[0]['kind']=='armed' and len(rows)>1 and (len(rows)-1)%3==0,'publication journal boundaries missing')
        for i in range(1,len(rows),3):
            flush,lock,rename=rows[i:i+3]
            require([r['kind'] for r in (flush,lock,rename)]==['flush-completed','target-locked','publication-refused'] and
                    flush['path']==lock['path']==rename['path'] and flush['result']==1 and lock['share']==3 and
                    rename['result']==0 and rename['error'] in (5,32) and rename['lock_closed'] is True,
                    'original successful flush/real sharing refusal/release differs')
        return dict(failed_calls=(len(rows)-1)//3,real_flush_succeeded=True,real_rename_refused=True,
                    win32_errors=sorted({r['error'] for r in rows if r['kind']=='publication-refused'}),target_locks_released=True)
    require(fault=='flush','unknown fault mode')
    allowed=('armed','helper-bound','target-open','target-write','flush-failed') if first_save else ('armed','flush-failed')
    require(rows[0]['kind']=='armed' and all(r['kind'] in allowed for r in rows),'probe error or publication during flush failure')
    if first_save:
        require(len(rows)>2 and rows[1]['kind']=='helper-bound' and sum(r['kind']=='helper-bound' for r in rows)==1,
                'first-save helper binding did not precede fault')
        created=[r for r in rows if r['kind']=='target-open' and r['success'] and r['disposition'] in (1,2,4,5)]
        failed=[r for r in rows if r['kind']=='flush-failed']
        require(len(created)==1 and created[0]['size']==0 and failed and created[0]['sequence']<failed[0]['sequence'],
                'original zero-byte placeholder creation before first save unproved')
        require(all(r['size']==0 for r in rows if r['kind']=='target-open' and r['success']) and
                not any(r['kind']=='target-write' and r['requested'] for r in rows),'canonical target received partial serialized bytes')
    failures=[r for r in rows if r['kind']=='flush-failed']
    require(failures and all(r['original']==1 and r['result']==0 and r['error']==29 for r in failures),'failed API result injection missing')
    return dict(failed_calls=len(failures),real_flush_succeeded=True,reported_write_fault=True,rename_while_faulted=False)


def startup_log(raw,tick):
    """Include pre-menu saves; exclude incomplete lines and earlier PID reuse."""
    complete=raw[:raw.rfind(b'\n')+1].decode('utf-8')
    return '\n'.join(line for line in complete.splitlines() if (m:=re.match(r'^\[(\d+)\]',line)) and int(m[1])>=tick)


def unresolved_exit_evidence(rows,log,pid,trace,initial_failures):
    proof=fault_evidence(rows,pid,first_save=True)
    confirms=[r['tick'] for r in trace if r['event']=='OnConfirm.dispatch' and r['pid']==pid]
    require(len(confirms)==1 and proof['failed_calls']>initial_failures and
            any(r['kind']=='flush-failed' and r['tick']>=confirms[0] for r in rows),
            'save fault did not remain active through original Quit')
    require(not re.search(r'NATIVE SETTINGS save result:[^\n]*succeeded=1',log),
            'a successful save preceded unresolved exit')
    return proof|dict(failed_during_quit=True,no_successful_save_before_exit=True)


def run(args):
    fault=getattr(args,'fault','flush');require(fault in ('flush','publication'),'unknown fault mode')
    first_save=getattr(args,'first_save',False);require(not first_save or fault=='flush','first-save requires flush mode')
    quit_unresolved=getattr(args,'quit_unresolved',False);require(not quit_unresolved or first_save,'unresolved Quit requires first-save mode')
    game,out=args.game.resolve(),args.output.resolve()
    require(game.is_relative_to(ROOT/'local') and out.is_relative_to(ROOT/'local'),'owned ignored paths required')
    launcher.verify_game(game,community=True,bridge_version=2,unified=True)
    receipt=quit_probe.verify_build_receipt(game,args.helper_build_receipt.resolve())
    out.mkdir(parents=True,exist_ok=False)
    profile=('nativestest_exit212_' if quit_unresolved else 'nativestest_first211_' if first_save else 'nativestest_publish210_' if fault=='publication' else 'nativestest_flush209_')+secrets.token_hex(5)
    folder=game/'.battleaces-resurrection/profiles'/profile;folder.mkdir()
    target=folder/'gameconfig-localuser.toml';shared=args.shared_settings.resolve()
    def channels():return dict(settings=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    def hashes():return startup.source_hashes()|{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),ROOT/'tools/owned_suspended_launch.py')}
    report=dict(passed=False,scope=__doc__,fault_mode=fault,first_save=first_save,quit_unresolved=quit_unresolved,profile=profile,helper_build=receipt,shared_before=channels(),sources_before=hashes(),forced_cleanup=False,processes=[])
    processes=[];started=time.monotonic()
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong
    def launch(label,write=False):
        phase=out/label;phase.mkdir()
        command=[str(game/'Battle Aces.exe'),'-offline-practice','-practice-ai-experimental','-local-profile='+profile,
                 '-native-settings-deck-proof','-native-quit-smoke','-native-quit-mode=confirm','-native-quit-gate-smoke',
                 '-screen-fullscreen','0','-screen-width','960','-screen-height','540','-logFile',str(phase/'game.log')]
        if write:command+=['-native-settings-write-smoke','-native-settings-notice-smoke']
        info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
        tick=clock();factory=SuspendedChild.create if first_save and label=='failure-retry' else subprocess.Popen
        process=factory(command,cwd=game,startupinfo=info,creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True)
        row=dict(process=process,job=None,pid=process.pid,tick=tick,label=label,output=phase);processes.append(row)
        row['job']=process.job if isinstance(process,SuspendedChild) else _WindowsJob(process.pid)
        report['processes'].append(dict(pid=process.pid,tick=tick,label=label,command=command))
        (out/'processes.json').write_text(json.dumps(report['processes'],indent=2)+'\n')
        return row
    def log(row):
        if not first_save:return read_native_log(game,row['pid'],since_tick=row['tick'])
        path=game/'investigation/runtime'/f'dedicated-native-{row["pid"]}.log'
        return startup_log(path.read_bytes() if path.exists() else b'',row['tick'])
    def wait(row,predicate,timeout=60):
        deadline=time.monotonic()+timeout
        while True:
            text=log(row)
            require(row['process'].poll() is None,'owned client exited before gate')
            require(not any(x in text for x in ('Native settings write smoke failed:','Native settings notice failed:')),'native diagnostic failed')
            value=predicate(text)
            if value:return value
            require(time.monotonic()<deadline,'owned phase deadline');time.sleep(.1)
    def ready(row):wait(row,lambda text:'Offline practice menu ready:' in text and 'NATIVE SETTINGS DECK proof:' in text)
    def phase(row,number):
        def find(text):
            rows=[json.loads(line.split('NATIVE SETTINGS WRITE smoke: ',1)[1]) for line in text.splitlines() if 'NATIVE SETTINGS WRITE smoke: ' in line]
            return next((r for r in rows if r['phase']==number),None)
        return wait(row,find)
    def quit(row):
        gate=folder/'native-quit.ready'
        with gate.open('xb'):pass
        row['process'].wait(timeout=60);require(row['process'].returncode==0,'original Quit exit differs')
        trace_path=folder/'quit-trace.jsonl'
        trace=quit_probe.current_trace_rows(trace_path.read_bytes(),row['pid'],row['tick'])
        require([r['event'] for r in trace]==['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return'],'original Quit trace differs')
        # Trace creation is deliberately exclusive. Preserve the closed first
        # process's evidence before reusing its profile in a fresh process.
        trace_path.rename(row['output']/'quit-trace.jsonl')
        gate.unlink();return trace
    try:
        require(not target.exists(),'fresh profile already contains settings')
        row=launch('failure-retry',True)
        if first_save:old=None;before=None
        else:
            ready(row);before=startup.native_settings_evidence(game,row['output'],row['pid'],row['tick'],profile)
            old=target.read_bytes();(out/'before.toml').write_bytes(old)
        def preserved():return target.is_file() and target.read_bytes()==b'' if first_save else target.read_bytes()==old
        config=dict(pid=row['pid'],fault=fault,firstSave=first_save,helper=str(game/'BattleAcesOffline.dll'),folder=str(folder),journal=str(out/'flush.jsonl'))
        script=SOURCE.replace('__CONFIG__',json.dumps(config)).encode()
        (out/'flush.js').write_bytes(script);report['script_sha256']=hashlib.sha256(script).hexdigest()
        print(json.dumps(dict(stage='attach_flush_probe',pid=row['pid'],script=str(out/'flush.js'))),flush=True)
        def armed(_):
            path=out/'flush.jsonl'
            if not path.exists():return False
            raw=path.read_bytes();rows=[json.loads(line) for line in raw[:raw.rfind(b'\n')+1].splitlines()]
            require(not any(r['kind']=='error' for r in rows),'probe error')
            return any(r['kind']=='armed' and r['pid']==row['pid'] for r in rows)
        wait(row,armed)
        if first_save:
            require(not target.exists() and not log(row),'first-save client advanced before controlled resume')
            row['process'].resume();ready(row)
            proofs=[json.loads(line.split('NATIVE SETTINGS DECK proof: ',1)[1]) for line in log(row).splitlines() if 'NATIVE SETTINGS DECK proof: ' in line]
            require(len(proofs)==1 and proofs[0]['profile']==profile and proofs[0]['owned'] and proofs[0]['worldIdle'],'initial native deck proof missing')
            before=dict(selected_deck={k:proofs[0][k] for k in ('units','activeAbilityGroups')},absent_before_resume=True,menu_target_bytes=0)
            require(preserved(),'first-save failure left nonempty settings before menu')
        require(preserved(),'target changed before first edit')
        if first_save:
            failed=dict(stage='startup',selected_deck=before['selected_deck'],canonical_bytes=0)
        else:
            with Path(str(target)+'.write-test-1.gate').open('xb'):pass
            failed=phase(row,1)
            require(failed['owned'] and failed['worldIdle'] and not failed['lastSucceeded'] and failed['failedWrites']>0 and failed['units']!=before['selected_deck']['units'] and preserved(),'failed flush did not preserve old disk choice')
        wait(row,lambda text:'NATIVE SETTINGS notice pooled reuse passed:' in text)
        report['fault']=fault_evidence([json.loads(line) for line in (out/'flush.jsonl').read_text().splitlines()],row['pid'],fault,first_save)
        markers=(['native settings output publication failed Win32='+str(code) for code in report['fault']['win32_errors']]
                 if fault=='publication' else ['native settings output flush failed'])
        require(preserved() and all(marker in log(row) for marker in markers),'failure notice changed old save or missed selected boundary')
        if first_save:
            require(not re.search(r'NATIVE SETTINGS save result:[^\n]*succeeded=1',log(row)),'early successful settings publication escaped first-save fault')
            report['first_save_target']=dict(absent_before_resume=True,original_empty_placeholder=True,
                                             empty_at_menu=True,empty_after_notice=True,no_successful_save_before_unload=True)
        if quit_unresolved:
            report['unresolved_quit']=quit(row)
            require(preserved(),'unresolved Quit changed the empty settings placeholder')
            report['fault_after_quit']=unresolved_exit_evidence(
                [json.loads(line) for line in (out/'flush.jsonl').read_text().splitlines()],
                log(row),row['pid'],report['unresolved_quit'],report['fault']['failed_calls'])
            report['empty_after_unresolved_quit']=True
            row=launch('restart-unresolved',True);ready(row)
            recovered=startup.native_settings_evidence(game,row['output'],row['pid'],row['tick'],profile)
            proofs=[json.loads(line.split('NATIVE SETTINGS DECK proof: ',1)[1]) for line in log(row).splitlines() if 'NATIVE SETTINGS DECK proof: ' in line]
            require(len(proofs)==1 and all(proofs[0][k]==before['selected_deck'][k]==recovered['selected_deck'][k]
                    for k in ('units','activeAbilityGroups')),'unresolved restart lost original defaults')
            require(f'NATIVE SETTINGS load result: profile={profile} sequence=1 parsed=1' in log(row),
                    'empty placeholder was not parsed on restart')
            report['recovered_from_empty']=recovered
        else:
            print(json.dumps(dict(stage='unload_flush_probe',pid=row['pid'],acknowledgment=str(out/'probe-unloaded'))),flush=True)
            wait(row,lambda _: (out/'probe-unloaded').is_file())
        retry_phase=1 if first_save else 2
        with Path(str(target)+f'.write-test-{retry_phase}.gate').open('xb'):pass
        retry=phase(row,retry_phase)
        require(retry['lastSucceeded'] and retry['failedWrites']==0 and retry['owned'] and retry['worldIdle'],'original retry save failed')
        if first_save:require(retry['units']!=before['selected_deck']['units'],'retry did not save an original native deck edit')
        else:require(all(retry[k]==failed[k] for k in ('units','activeAbilityGroups')),'original retry did not save same live choice')
        saved=startup.native_settings_evidence(game,row['output'],row['pid'],row['tick'],profile)
        require(target.read_bytes()!=old and all(saved['selected_deck'][k]==retry[k] for k in ('units','activeAbilityGroups')),'retry disk differs')
        report.update(before=before,failed=failed,retry=retry,saved=saved,quit=quit(row))
        row=launch('restart');ready(row)
        restarted=startup.native_settings_evidence(game,row['output'],row['pid'],row['tick'],profile)
        proofs=[json.loads(line.split('NATIVE SETTINGS DECK proof: ',1)[1]) for line in log(row).splitlines() if 'NATIVE SETTINGS DECK proof: ' in line]
        require(len(proofs)==1 and all(proofs[0][k]==retry[k]==restarted['selected_deck'][k] for k in ('units','activeAbilityGroups')),'native restart lost saved choice')
        report.update(restarted=restarted,restart_quit=quit(row),passed=True)
    except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        for row in processes:
            if row['process'].poll() is None:report['forced_cleanup']=True;row['process'].terminate();row['process'].wait(timeout=15)
            (row['output']/'native.log').write_text(log(row),encoding='utf-8')
            if row['job']:
                report.setdefault('jobs',[]).append(job_accounting(row['job'].handle))
                if isinstance(row['process'],SuspendedChild):
                    row['process'].close();report['suspended_owner']=row['process'].receipt
                else:row['job'].close()
        report.update(shared_after=channels(),sources_after=hashes(),elapsed_seconds=time.monotonic()-started)
        report['passed'] &= not report['forced_cleanup'] and report['shared_before']==report['shared_after'] and report['sources_before']==report['sources_after'] and all(j['active_processes']==j['total_terminated_processes']==0 for j in report.get('jobs',[]))
        (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','forced_cleanup','elapsed_seconds','error') if k in report}));return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('game','output','helper-build-receipt','shared-settings'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--fault',choices=('flush','publication'),default='flush')
    parser.add_argument('--first-save',action='store_true',help='arm before primary resume; permit only the observed original empty placeholder until retry')
    parser.add_argument('--quit-unresolved',action='store_true',help='keep first-save fault active through normal Quit, then recover in a fresh process')
    raise SystemExit(run(parser.parse_args()))
