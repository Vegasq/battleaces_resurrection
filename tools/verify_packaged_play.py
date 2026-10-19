"""Owned bundled unified-client AI/result/Continue/original-Quit qualification.

The isolated bundled runtime executes its actual production client.main and
bridge. An external authored spawn adapter adds explicit native diagnostics;
ordinary generated arguments must contain none. This is NOT a seamless CMD,
mouse,visual,audio,clean-PC or Internet gameplay acceptance claim. The separate
packaged startup probe qualifies the actual ordinary Start Client.cmd command.
No forced cleanup can qualify Quit. Shared storage is read/hash-only.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import traceback

from client_patch.transport import client,launcher
from server.worker_client import _WindowsJob
from tools.package_integrity import verify
from tools.run_secure_match import read_native_log
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.verify_native_storage import snapshot,replay_evidence

ROOT=Path(__file__).resolve().parents[1]
require=startup.require

# Authored test driver only. Never installed into the product/package or
# imported from the source checkout by its isolated bundled interpreter.
DRIVER=r'''
import ctypes,hashlib,json,os,subprocess,sys,time,traceback
from pathlib import Path
from client_patch.transport import client,launcher
from tools.package_integrity import verify

request_path=Path(sys.argv[1]);request=json.loads(request_path.read_bytes())
package=Path(request['package']);output=Path(request['output']);game=Path(request['game'])
verify(package,'client')
report={'passed':False,'remote_connections':0,'invite_reads':0,'production_modules':{}}
process=None
original_spawn=launcher.spawn_game
original_connect=launcher.tls.open_verified_connection
original_invite=launcher.read_credential_file
def forbid_connection(*args,**kwargs):
    report['remote_connections']+=1
    raise AssertionError('unconfigured local play attempted a TLS connection')
def forbid_invite(*args,**kwargs):
    report['invite_reads']+=1
    raise AssertionError('unconfigured local play attempted an invite read')
def spawn(config,remote,options,child):
    global process
    command=launcher.game_arguments(config,None,child.fileno(),options)
    assert '-unified-client' in command and '-public-queue-experimental' in command and '-local-cosmetics-experimental' in command
    assert not any(any(word in value.partition('=')[0].casefold() for word in ('smoke','audit','capture','proof','export','auto-')) for value in command if value.startswith('-'))
    assert config['local_profile']==request['profile'] and config['game_directory']==game
    ordinary=list(command)
    command[command.index('-logFile')+1]=str(output/'game.log')
    diagnostic=['-native-quit-smoke','-native-quit-mode=confirm','-native-quit-after-practice',
        '-practice-ai-smoke','-practice-ai-smoke-matches=1','-practice-ai-smoke-frames=3600',
        '-practice-ai-smoke-delay-ms=3000','-lan-audit','-lan-smoke']
    command.extend(diagnostic)
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow=1 if request['visible'] else 0
    info.lpAttributeList={'handle_list':[child.fileno()]}
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong
    tick=clock()
    try:
        child.set_inheritable(True)
        process=subprocess.Popen(command,cwd=game,startupinfo=info,close_fds=True)
    finally:child.set_inheritable(False)
    record=dict(pid=process.pid,launch_tick=tick,ordinary_arguments=ordinary,diagnostic_arguments=diagnostic,actual_arguments=command)
    (output/'game-process.json').write_text(json.dumps(record,indent=2)+'\n')
    return process
try:
    for module in (client,launcher,sys.modules['client_patch.transport.bridge'],sys.modules['tools.package_integrity']):
        path=Path(module.__file__).resolve()
        assert path.is_relative_to(package/'program/app')
        report['production_modules'][module.__name__]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():
        assert time.monotonic()<deadline,'parent did not establish owned job before gameplay'
        time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    launcher.spawn_game=spawn;launcher.tls.open_verified_connection=forbid_connection;launcher.read_credential_file=forbid_invite
    report['launcher_exit_code']=client.main(['--config',request['config']])
    report['game_exit_code']=None if process is None else process.poll()
    assert report['launcher_exit_code']==report['game_exit_code']==0
    assert report['remote_connections']==report['invite_reads']==0
    report['passed']=True
except BaseException as error:
    report.update(passed=False,error=repr(error),traceback=traceback.format_exc())
finally:
    launcher.spawn_game=original_spawn;launcher.tls.open_verified_connection=original_connect;launcher.read_credential_file=original_invite
    (output/'bundled-driver.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
'''


def sources():
    paths=[Path(__file__),ROOT/'tools/verify_native_storage.py']
    return quit_probe.sources()|{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def job_accounting(handle):
    """Read the owned job before closing it; a close may otherwise hide children."""
    class Accounting(ctypes.Structure):
        _fields_=[(name,ctypes.c_longlong) for name in ('user_time','kernel_time','period_user_time','period_kernel_time')]+[
            (name,ctypes.c_uint32) for name in ('page_faults','total_processes','active_processes','total_terminated_processes')]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.QueryInformationJobObject.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_void_p]
    value=Accounting();length=ctypes.c_ulong()
    require(ctypes.sizeof(value)==48 and kernel.QueryInformationJobObject(handle,1,ctypes.byref(value),ctypes.sizeof(value),ctypes.byref(length)) and
            length.value==ctypes.sizeof(value),'owned job process accounting unavailable')
    return {name:getattr(value,name) for name in ('total_processes','active_processes','total_terminated_processes')}


def run(args):
    package,game,output=(p.resolve() for p in (args.package,args.game,args.output))
    require(os.name=='nt' and 90<=args.timeout<=300,'bounded Windows play probe required')
    require(all(p.is_relative_to(ROOT/'local') for p in (package,game,output)),'owned ignored paths required')
    inventory=verify(package,'client')
    launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True)
    require((package/'program/client-helper/BattleAcesOffline.dll').read_bytes()==(game/'BattleAcesOffline.dll').read_bytes(),
            'install the exact packaged helper in the owned copy')
    receipt=quit_probe.verify_build_receipt(game,args.helper_build_receipt.resolve())
    manifest=json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
    require(manifest['diagnostics']['native_quit'] is False and manifest['diagnostics']['dlss_enabled'] is False and
            not manifest.get('pointer_hooks') and not any(h['name'].startswith('OfflineNativeQuit') for h in manifest['call_hooks']),
            'default recipe without optional teardown hooks required')
    output.mkdir(parents=True,exist_ok=False)
    profile='nativestest_packaged_'+secrets.token_hex(6)
    folder=game/'.battleaces-resurrection/profiles'/profile
    trace=folder/'quit-trace.jsonl';quit_probe.require_fresh_trace(trace)
    config=output/'client.json';settings=client.defaults(game)
    settings.update(local_profile=profile,display_name='Packaged Gameplay')
    config.write_text(json.dumps(settings,indent=2)+'\n');config_before=config.read_bytes()
    driver=output/'owned-driver.py';driver.write_text(DRIVER,encoding='utf-8')
    request=output/'request.json'
    request.write_text(json.dumps(dict(package=str(package),game=str(game),output=str(output),config=str(config),
                                     profile=profile,visible=args.visible),indent=2)+'\n')
    cwd=output/'foreign cwd';cwd.mkdir()
    for name in ('sitecustomize.py','tools.py','client_patch.py'):
        (cwd/name).write_text('raise RuntimeError("foreign module must not run")\n')
    shared=args.shared_settings.resolve()
    def channels():return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),
                               backup=snapshot(shared.parent/'StorageSyncBackup'))
    report=dict(passed=False,scope=__doc__,profile=profile,helper_build=receipt,package=str(package),
        package_inventory_sha256=hashlib.sha256(json.dumps(inventory,sort_keys=True).encode()).hexdigest(),
        shared_before=channels(),source_sha256_at_start=sources(),forced_cleanup=False,natural_quit=False,
        driver_sha256=hashlib.sha256(driver.read_bytes()).hexdigest())
    started=time.monotonic();parent=job=None;native=None;game_handle=None;exit_tick=None
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetTickCount64.restype=ctypes.c_ulonglong
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.WaitForSingleObject.restype=ctypes.c_ulong
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    try:
        environment=os.environ.copy()
        environment.update(PATH=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'),PYTHONPATH=str(cwd))
        command=[str(package/'program/runtime/python.exe'),'-I','-B',str(driver),str(request)]
        with (output/'stdout.txt').open('wb') as stdout,(output/'stderr.txt').open('wb') as stderr:
            info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
            parent=subprocess.Popen(command,cwd=cwd,env=environment,stdout=stdout,stderr=stderr,startupinfo=info,close_fds=True)
            job=_WindowsJob(parent.pid);report['driver_pid']=parent.pid
            ready=output/'job-ready.tmp';ready.write_bytes(b'owned job attached\n');ready.rename(output/'job-ready')
            while parent.poll() is None:
                if native is None and (output/'game-process.json').exists():
                    try:native=json.loads((output/'game-process.json').read_bytes())
                    except json.JSONDecodeError:native=None
                    if native is not None:
                        require(type(native['pid']) is int and native['pid']>0 and type(native['launch_tick']) is int,'native process identity missing')
                        game_handle=kernel.OpenProcess(0x100000|0x1000,False,native['pid'])
                        require(game_handle,'cannot observe owned game exit')
                        report['game']=native
                if native is not None:
                    text=read_native_log(game,native['pid'],since_tick=native['launch_tick'])
                    require(not any(marker in text for marker in ('Native Quit probe failed:','Local menu initialization failed:',
                        'Practice stopped in ','Offline loop stopped in ','Client lifecycle invariant failed:','Cosmetics unlock failed:')),
                        'native packaged lifecycle failed')
                    rows=quit_probe.current_trace_rows(trace.read_bytes() if trace.exists() else b'',native['pid'],native['launch_tick'])
                    dispatch=[r['tick'] for r in rows if r['event']=='OnConfirm.dispatch']
                    if dispatch:
                        require(len(dispatch)==1,'repeated native Quit dispatch')
                        require(kernel.GetTickCount64()-dispatch[0]<60000,'game did not exit within60s of original Quit')
                        if kernel.WaitForSingleObject(game_handle,0)==0 and exit_tick is None:
                            exit_tick=kernel.GetTickCount64();report['exit_tick']=exit_tick
                require(time.monotonic()-started<args.timeout,'bundled native play deadline reached')
                time.sleep(.15)
        require(parent.returncode==0 and native is not None and game_handle,'bundled launcher did not exit naturally0')
        drain_deadline=time.monotonic()+5
        while True:
            report['job_after_driver_exit']=job_accounting(job.handle)
            if report['job_after_driver_exit']['active_processes']==0:break
            require(time.monotonic()<drain_deadline,'owned descendants remained alive after normal launcher exit')
            time.sleep(.05)
        require(kernel.WaitForSingleObject(game_handle,0)==0,'bundled driver exited while game remained alive')
        exit_code=ctypes.c_ulong();require(kernel.GetExitCodeProcess(game_handle,ctypes.byref(exit_code)) and exit_code.value==0,
                                        'native game exit code is not0')
        if exit_tick is None:exit_tick=kernel.GetTickCount64()
        text=read_native_log(game,native['pid'],since_tick=native['launch_tick'])
        rows=quit_probe.current_trace_rows(trace.read_bytes(),native['pid'],native['launch_tick'])
        require([r['event'] for r in rows]==['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return'] and
                all(type(r.get('thread')) is int for r in rows) and all(a['tick']<=b['tick'] for a,b in zip(rows,rows[1:])) and
                exit_tick-rows[3]['tick']<60000,'original natural Quit trace/deadline invalid')
        bundled=json.loads((output/'bundled-driver.json').read_bytes())
        require(bundled['passed'] and bundled['launcher_exit_code']==bundled['game_exit_code']==0 and
                bundled['remote_connections']==bundled['invite_reads']==0,'bundled production launcher/transport proof incomplete')
        report.update(natural_quit=True,exit_code=exit_code.value,exit_seconds_after_confirm=(exit_tick-rows[3]['tick'])/1000)
        for module in bundled['production_modules'].values():
            path=Path(module['path']).resolve()
            require(path.is_relative_to(package/'program/app') and
                    inventory['files'][path.relative_to(package).as_posix()]['sha256']==module['sha256'],
                    'bundled runtime imported an unverified production module')
        for marker in ('Unified client ready:','BA_RESURRECTION_COSMETICS_UNLOCK_V1 ready:',
                       'BA_RESURRECTION_COSMETICS_PERSIST_V1 ready:','Online connection is not configured; localWorldUnaffected=1'):
            require(marker in text,'ordinary packaged feature marker missing: '+marker)
        report['practice']=quit_probe.practice_evidence(game,output,native['pid'],text)
        require('expectedTableEntry=1' in text,'native AI profile override was not applied')
        require(report['practice']['produced_bot_units_with_orders_and_position_change'],
                'packaged bot did not move native units with autonomous orders')
        report['local_settings']=startup.native_settings_evidence(game,output,native['pid'],native['launch_tick'],profile)
        replays=list((folder/'AutoSaveReplays').iterdir());require(len(replays)==1,'expected one native profile replay')
        report['replay']=replay_evidence(replays[0].read_bytes())
        backup=folder/'StorageSyncBackup/A3079428-5DC5-4617-AF2D-0C8656DA760B'
        raw=backup.read_bytes();value=json.loads(raw)
        require(value['Id']==backup.name and isinstance(value['Data'],dict) and
                'NATIVE BACKUP save published: originalJsonAndWriter=1 flushed=1 inPlaceFallback=0' in text,
                'original native backup publication missing')
        report.update(backup_sha256=hashlib.sha256(raw).hexdigest(),bundled_driver=bundled,trace=rows,
                      natural_quit=True,exit_code=exit_code.value,exit_seconds_after_confirm=(exit_tick-rows[3]['tick'])/1000,passed=True)
    except BaseException as error:
        report.update(passed=False,error=repr(error),traceback=traceback.format_exc())
    finally:
        if (parent is not None and parent.poll() is None) or (game_handle and kernel.WaitForSingleObject(game_handle,0)!=0):
            report['forced_cleanup']=True
        if job is not None:
            try:
                report['job_before_close']=job_accounting(job.handle)
                if report['job_before_close']['active_processes']:report['forced_cleanup']=True
            except BaseException as error:report.update(passed=False,forced_cleanup=True,job_accounting_error=repr(error))
        if job is not None:job.close()
        if parent is not None:
            try:parent.wait(timeout=15)
            except subprocess.TimeoutExpired:parent.kill();parent.wait(timeout=15);report['forced_cleanup']=True
        report['driver_reaped']=parent is None or parent.poll() is not None
        report['game_reaped']=game_handle is None or kernel.WaitForSingleObject(game_handle,15000)==0
        if game_handle:kernel.CloseHandle(game_handle)
        if native is not None:
            (output/'native.log').write_text(read_native_log(game,native['pid'],since_tick=native['launch_tick']),encoding='utf-8')
        if trace.exists():(output/'quit-trace.jsonl').write_bytes(trace.read_bytes())
        try:report['package_files_unchanged']=verify(package,'client')==inventory
        except BaseException as error:report.update(package_files_unchanged=False,package_error=repr(error))
        report['config_unchanged']=config.read_bytes()==config_before
        report['driver_unchanged']=hashlib.sha256(driver.read_bytes()).hexdigest()==report['driver_sha256']
        report.update(shared_after=channels(),source_sha256_at_finish=sources(),elapsed_seconds=time.monotonic()-started)
        report['shared_channels_unchanged']=report['shared_before']==report['shared_after']
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['passed'] &= all(report.get(k,False) for k in ('driver_reaped','game_reaped','package_files_unchanged',
                                                           'config_unchanged','driver_unchanged','shared_channels_unchanged','source_files_unchanged')) and not report['forced_cleanup']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','natural_quit','forced_cleanup','elapsed_seconds','error') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','game','output','shared-settings','helper-build-receipt'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--visible',action='store_true')
    raise SystemExit(run(parser.parse_args()))
