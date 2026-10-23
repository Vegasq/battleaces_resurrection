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
import csv
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import time
import traceback

from client_patch.transport import client,launcher,rc_setup
from server.worker_client import _WindowsJob
from tools.package_integrity import verify
from tools.run_secure_match import read_native_log
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.verify_native_storage import snapshot,replay_evidence
from tools.local_ai_evidence import public_match,public_search
from tools import replay_retention
from tools import native_replay_evidence
from tools import replay_codec_fixtures
from tools.availability_endpoint import AvailabilityEndpoint, NETWORK_STATES

ROOT=Path(__file__).resolve().parents[1]
require=startup.require

# Authored test driver only. Never installed into the product/package or
# imported from the source checkout by its isolated bundled interpreter.
DRIVER=r'''
import asyncio,ctypes,hashlib,json,os,subprocess,sys,time,traceback
from pathlib import Path
from client_patch.transport import client,launcher,rc_setup
from tools.package_integrity import verify

request_path=Path(sys.argv[1]);request=json.loads(request_path.read_bytes())
package=Path(request['package']);output=Path(request['output']);game=Path(request['game'])
verify(package,'client')
report={'passed':False,'remote_connections':0,'invite_reads':0,'resolver_requests':0,'availability_reasons':[],'production_modules':{}}
network_case=request['connection_state'] in ('rc-refused','rc-handshake-timeout')
report.update(connection_attempts=[],resolved_targets=[],bridge_failures=[])
process=None
original_spawn=launcher.spawn_game
original_connect=launcher.tls.open_verified_connection
original_invite=launcher.read_credential_file
resolver_type=rc_setup.Resolver if request.get('rc_settings') else launcher.RemoteConfigResolver
original_resolve=resolver_type.read
bridge=sys.modules['client_patch.transport.bridge'];original_send=bridge.Bridge.send

async def observe_connection(host,port,tls,**kwargs):
    assert network_case and host=='127.0.0.1' and port==request['endpoint_port'] and not kwargs
    assert tls.verify_certificate is False
    report['remote_connections']+=1
    row=dict(host=host,port=port,verify_certificate=tls.verify_certificate,
             connect_timeout=launcher.tls.DEFAULT_CONNECT_TIMEOUT,
             handshake_timeout=launcher.tls.DEFAULT_HANDSHAKE_TIMEOUT)
    report['connection_attempts'].append(row);began=time.monotonic()
    try:
        result=await original_connect(host,port,tls)
        row['unexpected_success']=True
        return result
    except BaseException as error:
        row.update(error_type=type(error).__name__,winerror=getattr(error,'winerror',None),errno=getattr(error,'errno',None))
        raise
    finally:row['elapsed_seconds']=time.monotonic()-began

async def observe_send(self,kind,identity,data=b''):
    if kind==bridge.FAILURE:
        assert len(data)==1
        report['bridge_failures'].append(dict(session=identity,code=data[0]))
    return await original_send(self,kind,identity,data)
def forbid_connection(*args,**kwargs):
    report['remote_connections']+=1
    raise AssertionError('locally unavailable settings attempted a TLS connection')
def forbid_invite(*args,**kwargs):
    report['invite_reads']+=1
    raise AssertionError('locally unavailable settings attempted an invite read')
def resolve(self):
    from client_patch.transport.bridge import RemoteUnavailable
    report['resolver_requests']+=1
    try:
        target=original_resolve(self)
    except RemoteUnavailable as error:
        report['availability_reasons'].append(error.reason)
        raise
    if network_case:
        assert target.host=='127.0.0.1' and target.port==request['endpoint_port'] and target.tls.verify_certificate is False
        report['resolved_targets'].append(dict(host=target.host,port=target.port,verify_certificate=False))
        return target
    raise AssertionError('unavailable-settings fixture unexpectedly resolved a remote')
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
        # In the Try Deck network-failure cell, let the unchanged5s optional
        # handshake deadline finish BEFORE the authored Play action. Ordinary
        # client timing and all public queue deadlines remain unchanged.
        '-practice-ai-smoke-delay-ms='+('10000' if network_case and request['mode']==4 else '3000'),
        '-lan-audit','-lan-smoke']
    assert request['mode'] in (1,2,4,5)
    if request['mode']!=4:
        diagnostic.extend(['-public-queue-smoke','-public-queue-smoke-mode='+str(request['mode']),'-public-ai-smoke'])
    if request['native_replay_readback']:diagnostic.append('-native-replay-readback-smoke')
    if request['native_replay_faults']:diagnostic.append('-native-replay-faults-smoke')
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
    for module in (client,launcher,rc_setup,launcher.tls,sys.modules['client_patch.transport.bridge'],sys.modules['tools.package_integrity']):
        path=Path(module.__file__).resolve()
        assert path.is_relative_to(package/'program/app')
        report['production_modules'][module.__name__]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():
        assert time.monotonic()<deadline,'parent did not establish owned job before gameplay'
        time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    launcher.spawn_game=spawn;launcher.tls.open_verified_connection=observe_connection if network_case else forbid_connection;launcher.read_credential_file=forbid_invite
    if network_case:bridge.Bridge.send=observe_send
    resolver_type.read=resolve
    report['launcher_exit_code']=client.main(['--config',request['config']])
    report['game_exit_code']=None if process is None else process.poll()
    assert report['launcher_exit_code']==report['game_exit_code']==0
    assert 1<=report['resolver_requests']<=2
    if network_case:
        assert report['invite_reads']==0 and report['availability_reasons']==[]
        assert len(report['resolved_targets'])==report['resolver_requests']
        assert report['remote_connections']==len(report['connection_attempts'])>=1
        assert report['bridge_failures'] and not any(row.get('unexpected_success') for row in report['connection_attempts'])
    else:
        assert report['remote_connections']==report['invite_reads']==0
        expected=9 if request['connection_state']=='invalid-trust' else 8
        assert report['availability_reasons']==[expected]*report['resolver_requests']
    report['passed']=True
except BaseException as error:
    report.update(passed=False,error=repr(error),traceback=traceback.format_exc())
finally:
    launcher.spawn_game=original_spawn;launcher.tls.open_verified_connection=original_connect;launcher.read_credential_file=original_invite
    resolver_type.read=original_resolve;bridge.Bridge.send=original_send
    (output/'bundled-driver.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
'''


def sources():
    paths=[Path(__file__),ROOT/'tools/availability_endpoint.py',ROOT/'tools/verify_native_storage.py',ROOT/'tools/local_ai_evidence.py',ROOT/'tools/replay_retention.py',ROOT/'tools/native_replay_evidence.py',ROOT/'tools/replay_codec_fixtures.py']
    return quit_probe.sources()|{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def owned_profile(long_replay=False):
    prefix='nativestest_packaged_'
    return prefix+secrets.token_hex(24)[:48-len(prefix)] if long_replay else prefix+secrets.token_hex(6)


def owned_display_name(long_replay=False):
    # Keep random original bot identities. Their short names must not make the
    # explicitly requested long-path fixture depend on a favorable draw.
    return 'Packaged Gameplay Long Path Test' if long_replay else 'Packaged Gameplay'


def availability_settings(settings,state,folder):
    """Public authored fixtures; never create/read a bearer invite or private store."""
    require(state in ('unconfigured','missing-files','invalid-trust'),'unsupported availability fixture')
    value=dict(settings)
    if state=='unconfigured':return value
    require(not folder.exists(),'availability fixtures require a fresh directory')
    value.update(server_host='127.0.0.1',server_port=9,server_name='localhost',
                 ca_bundle=str(folder/'ca.pem'),credential_file=str(folder/'invite-must-not-be-read.json'))
    if state=='invalid-trust':
        folder.mkdir()
        (folder/'ca.pem').write_bytes(b'authored invalid public trust bundle\n')
        (folder/'invite-must-not-be-read.json').write_bytes(b'authored sentinel; no credential\n')
    return value


def availability_evidence(bundled,text,state):
    if state in NETWORK_STATES:return network_availability_evidence(bundled,text,state)
    require(state in ('unconfigured','missing-files','invalid-trust'),'unsupported availability evidence')
    reason=9 if state=='invalid-trust' else 8
    expected='Online connection settings are invalid' if reason==9 else 'Online connection is not configured'
    count=bundled.get('resolver_requests')
    require(type(count) is int and 1<=count<=2 and bundled.get('availability_reasons')==[reason]*count and
            bundled.get('remote_connections')==bundled.get('invite_reads')==0,
            'production resolver did not reject the intended local availability state')
    require(expected+'; localWorldUnaffected=1' in text,'native availability failure differs')
    return dict(state=state,resolver_requests=count,reasons=bundled['availability_reasons'],
                remote_tls_open_calls=0,invite_reads=0,scope='Actual production local-settings rejection;not valid-credential connection refusal or online queue evidence.')


def network_availability_evidence(bundled,text,state):
    require(state in NETWORK_STATES,'unsupported RC transport failure')
    count=bundled.get('resolver_requests');attempts=bundled.get('connection_attempts');targets=bundled.get('resolved_targets')
    require(type(count) is int and 1<=count<=2 and isinstance(attempts,list) and 1<=len(attempts)<=2 and
            type(bundled.get('remote_connections')) is int and bundled['remote_connections']==len(attempts) and
            isinstance(targets,list) and len(targets)==count and bundled.get('availability_reasons')==[] and
            type(bundled.get('invite_reads')) is int and bundled['invite_reads']==0,'real RC resolver/connection evidence missing')
    require(all(isinstance(row,dict) and row.get('host')=='127.0.0.1' and row.get('verify_certificate') is False and
                type(row.get('port')) is int and 1<=row['port']<=65535 for row in targets),'RC resolver target differs')
    expected=[]
    for row in attempts:
        require(isinstance(row,dict) and row.get('host')=='127.0.0.1' and row.get('verify_certificate') is False and
                type(row.get('port')) is int and any(row['port']==target['port'] for target in targets) and
                type(row.get('connect_timeout')) in (int,float) and row['connect_timeout']==10.0 and
                type(row.get('handshake_timeout')) in (int,float) and row['handshake_timeout']==5.0 and
                type(row.get('elapsed_seconds')) in (int,float) and math.isfinite(row['elapsed_seconds']) and
                0<=row['elapsed_seconds']<12 and not row.get('unexpected_success'),'unmodified production TLS defaults/outcome missing')
        if row.get('error_type')=='CancelledError':continue
        if state=='rc-refused':
            require(row.get('error_type')=='ConnectionRefusedError' and
                    (row.get('winerror') in (10061,1225) or row.get('errno')==10061),'OS TCP refusal missing')
            expected.append(2)
        else:
            require(row.get('error_type') in ('ConnectionAbortedError','TimeoutError') and row['elapsed_seconds']>=4.8,
                    'real default TLS/outer deadline did not expire')
            expected.append(7 if row['error_type']=='TimeoutError' else 2)
    failures=bundled.get('bridge_failures')
    require(expected and isinstance(failures,list) and all(isinstance(row,dict) and type(row.get('session')) is int and
            row['session']>0 and type(row.get('code')) is int for row in failures) and
            [row['code'] for row in failures]==expected,'actual private bridge failure differs')
    for code in set(expected):
        reason='Secure server unavailable' if code==2 else 'Secure server connection timed out'
        require(reason in text,'native availability reason missing')
    return dict(state=state,resolver_requests=count,remote_tls_open_calls=len(attempts),
                failed_attempts=len(expected),bridge_codes=expected,invite_reads=0,
                scope='Real schema4 RC resolver/identity and owned-loopback OS refusal or default TLS deadline;not protected-mode or TCP connect timeout.')


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
    state=getattr(args,'connection_state','unconfigured')
    if state not in NETWORK_STATES:return _run(args)
    require(getattr(args,'rc_settings',False),'owned network endpoint requires RC settings')
    endpoint=AvailabilityEndpoint(state)
    try:return _run(args,endpoint)
    finally:endpoint.close()


def _run(args,endpoint=None):
    if not hasattr(args,'rc_settings'):args.rc_settings=False
    if not hasattr(args,'native_replay_faults'):args.native_replay_faults=False
    if not hasattr(args,'connection_state'):args.connection_state='unconfigured'
    require(args.connection_state not in NETWORK_STATES or args.rc_settings,'network fixture requires schema4 RC mode')
    package,game,output=(p.resolve() for p in (args.package,args.game,args.output))
    require(os.name=='nt' and 90<=args.timeout<=300,'bounded Windows play probe required')
    require(args.mode in (1,2,4,5),'unsupported packaged local mode')
    require(all(p.is_relative_to(ROOT/'local') for p in (package,game,output)),'owned ignored paths required')
    inventory=verify(package,'client')
    launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True)
    require((package/'program/client-helper/BattleAcesOffline.dll').read_bytes()==(game/'BattleAcesOffline.dll').read_bytes(),
            'install the exact packaged helper in the owned copy')
    receipt=quit_probe.verify_build_receipt(game,args.helper_build_receipt.resolve())
    if args.native_replay_readback:require(b'BA_RESURRECTION_NATIVE_REPLAY_READER_V1' in (game/'BattleAcesOffline.dll').read_bytes(),'install the owned native replay codec diagnostic helper')
    if args.native_replay_faults:
        require(args.native_replay_readback and not args.replay_retention and b'BA_RESURRECTION_NATIVE_REPLAY_FAULTS_V1' in (game/'BattleAcesOffline.dll').read_bytes(),
                'fault suite requires native readback, current helper and separate non-retention profile')
    manifest=json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
    require(manifest['diagnostics']['native_quit'] is False and manifest['diagnostics']['dlss_enabled'] is False and
            not manifest.get('pointer_hooks') and not any(h['name'].startswith('OfflineNativeQuit') for h in manifest['call_hooks']),
            'default recipe without optional teardown hooks required')
    output.mkdir(parents=True,exist_ok=False)
    profile=owned_profile(args.expect_long_replay)
    folder=game/'.battleaces-resurrection/profiles'/profile
    retention_fixture=replay_retention.prepare(folder/'AutoSaveReplays',args.replay_retention,ROOT/'local') if args.replay_retention else None
    codec_fixture=replay_codec_fixtures.prepare(folder/'AutoSaveReplays',ROOT/'local') if args.native_replay_faults else None
    trace=folder/'quit-trace.jsonl';quit_probe.require_fresh_trace(trace)
    config=output/'client.json';settings=client.defaults(game)
    settings.update(local_profile=profile,display_name=owned_display_name(args.expect_long_replay))
    availability_folder=output/'availability-fixture'
    if endpoint:
        settings.update(server_host='127.0.0.1',server_port=endpoint.port)
    else:settings=availability_settings(settings,args.connection_state,availability_folder)
    if args.rc_settings:
        require(args.connection_state=='unconfigured' or endpoint,'RC fixture must be blank or owned endpoint')
        settings={key:value for key,value in settings.items() if key in rc_setup.KEYS}
        settings['schema']=4
    availability_before=snapshot(availability_folder)
    config.write_text(json.dumps(settings,indent=2)+'\n');config_before=config.read_bytes()
    driver=output/'owned-driver.py';driver.write_text(DRIVER,encoding='utf-8')
    request=output/'request.json'
    request.write_text(json.dumps(dict(rc_settings=args.rc_settings,package=str(package),game=str(game),output=str(output),config=str(config),
                                     profile=profile,visible=args.visible,mode=args.mode,native_replay_readback=args.native_replay_readback,
                                     native_replay_faults=args.native_replay_faults,connection_state=args.connection_state,
                                     endpoint_port=endpoint.port if endpoint else None),indent=2)+'\n')
    cwd=output/'foreign cwd';cwd.mkdir()
    for name in ('sitecustomize.py','tools.py','client_patch.py'):
        (cwd/name).write_text('raise RuntimeError("foreign module must not run")\n')
    shared=args.shared_settings.resolve()
    def channels():return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),
                               backup=snapshot(shared.parent/'StorageSyncBackup'))
    report=dict(passed=False,scope=__doc__,mode=args.mode,expect_long_replay=args.expect_long_replay,
        connection_state=args.connection_state,availability_fixture_before=availability_before,
        native_replay_readback=args.native_replay_readback,
        native_replay_faults=args.native_replay_faults,codec_fixture=codec_fixture,
        retention_fixture=retention_fixture,
        profile=profile,helper_build=receipt,package=str(package),
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
                        'Practice stopped in ','Offline loop stopped in ','Client lifecycle invariant failed:','Cosmetics unlock failed:',
                        'Public client failure:','Dedicated native Play could not ready lobby:','Native search failure cleanup:')),
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
                (endpoint or bundled['remote_connections']==0) and bundled['invite_reads']==0,
                'bundled production launcher/transport proof incomplete')
        report['availability']=availability_evidence(bundled,text,args.connection_state)
        report.update(natural_quit=True,exit_code=exit_code.value,exit_seconds_after_confirm=(exit_tick-rows[3]['tick'])/1000)
        for module in bundled['production_modules'].values():
            path=Path(module['path']).resolve()
            require(path.is_relative_to(package/'program/app') and
                    inventory['files'][path.relative_to(package).as_posix()]['sha256']==module['sha256'],
                    'bundled runtime imported an unverified production module')
        for marker in ('Unified client ready:','BA_RESURRECTION_COSMETICS_UNLOCK_V1 ready:',
                       'BA_RESURRECTION_COSMETICS_PERSIST_V1 ready:'):
            require(marker in text,'ordinary packaged feature marker missing: '+marker)
        if args.mode==4:
            report['practice']=quit_probe.practice_evidence(game,output,native['pid'],text)
            require('expectedTableEntry=1' in text,'native AI profile override was not applied')
            require(report['practice']['produced_bot_units_with_orders_and_position_change'],
                    'packaged bot did not move native units with autonomous orders')
        else:
            import re
            starts=re.findall(r'Practice requested: match=([0-9a-f]{32}) ',text)
            require(len(starts)==1,'expected exactly one packaged public local match')
            resource_path=game/'investigation/runtime'/f'lan-resources-{native["pid"]}-{starts[0]}.tsv'
            (output/'public-resources.tsv').write_bytes(resource_path.read_bytes())
            with resource_path.open(encoding='utf-8') as stream:resources=list(csv.DictReader(stream,delimiter='\t'))
            report['public_match']=public_match(text,resources,mode=args.mode,display_name=settings['display_name'])
            report['public_search']=public_search(text,mode=args.mode)
        report['local_settings']=startup.native_settings_evidence(game,output,native['pid'],native['launch_tick'],profile)
        if retention_fixture:
            replay_path,report['retention']=replay_retention.verify(folder/'AutoSaveReplays',retention_fixture)
        else:
            replays=[p for p in (folder/'AutoSaveReplays').iterdir() if codec_fixture is None or p.name not in codec_fixture['files']]
            require(len(replays)==1,'expected one native profile replay')
            replay_path=replays[0]
        # Read the native file through the same Windows extended-path namespace;
        # Python's caller-side path policy must not hide a successful native save.
        readable=Path('\\\\?\\'+str(replay_path.absolute())) if os.name=='nt' else replay_path
        report['replay']=dict(**replay_evidence(readable.read_bytes()),canonical_path_characters=len(str(replay_path)),
                              native_filename=replay_path.name)
        require('BA_RESURRECTION_NATIVE_REPLAY_LONG_PATH_V2' in text,'ordinary extended native replay path was not observed')
        if args.expect_long_replay:
            require(len(str(replay_path))>260,'native replay did not exercise a long full path')
        if args.native_replay_readback:report['native_codec']=native_replay_evidence.validate(text,report['replay'])
        if codec_fixture:report['native_codec_faults']=native_replay_evidence.validate_faults(text)
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
        report['availability_fixture_after']=snapshot(availability_folder)
        report['availability_fixture_unchanged']=availability_before==report['availability_fixture_after']
        if codec_fixture:
            try:report['codec_fixture_after']=replay_codec_fixtures.verify(folder/'AutoSaveReplays',codec_fixture)
            except BaseException as error:report.update(passed=False,codec_fixture_error=repr(error))
        report.update(shared_after=channels(),source_sha256_at_finish=sources(),elapsed_seconds=time.monotonic()-started)
        report['shared_channels_unchanged']=report['shared_before']==report['shared_after']
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        if endpoint:
            try:
                before=endpoint.snapshot();after=endpoint.close();report['owned_endpoint']=after
                endpoint_ok=not before['live_peers'] and not after['errors'] and not after['owner_closed_peers'] and not after['thread_alive'] and after['closed']
                if args.connection_state=='rc-refused':endpoint_ok &= not after['peers'] and not after['listening']
                else:endpoint_ok &= bool(after['peers']) and all(row['client_hello'] and row['closed_by_client'] for row in after['peers'])
                report['endpoint_qualified']=bool(endpoint_ok)
                identities=list((output/'rc-identities').glob('*.json'));private=[]
                for identity in identities:
                    value=launcher.read_json(identity,4096)
                    require(set(value)=={'player_id','token'} and rc_setup.rc_player_id(value['token'])==value['player_id'],'owned RC identity invalid')
                    private.append(value['token'].encode())
                public=[path for path in output.iterdir() if path.is_file() and path.suffix in ('.json','.txt','.log')]
                report['rc_identity_files']=len(identities)
                report['rc_tokens_not_logged']=not any(token in path.read_bytes() for token in private for path in public)
                report['passed'] &= endpoint_ok and len(identities)==1 and report['rc_tokens_not_logged']
            except BaseException as error:report.update(passed=False,endpoint_error=repr(error))
        report['passed'] &= all(report.get(k,False) for k in ('driver_reaped','game_reaped','package_files_unchanged',
                                                           'config_unchanged','driver_unchanged','shared_channels_unchanged','source_files_unchanged',
                                                           'availability_fixture_unchanged')) and not report['forced_cleanup']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','natural_quit','forced_cleanup','elapsed_seconds','error') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','game','output','shared-settings','helper-build-receipt'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=300)
    parser.add_argument('--rc-settings',action='store_true',help='qualify schema4 RC settings with blank address or owned failure endpoint')
    parser.add_argument('--mode',type=int,choices=(1,2,4,5),default=4,help='1v1,2v2,Try Deck,2vAI respectively')
    parser.add_argument('--connection-state',choices=('unconfigured','missing-files','invalid-trust',*NETWORK_STATES),default='unconfigured',
                        help='local resolver rejection or real RC connection to an owned numeric-loopback endpoint')
    parser.add_argument('--expect-long-replay',action='store_true',help='require the ordinary native replay path to exceed260 characters')
    parser.add_argument('--native-replay-readback',action='store_true',help='explicit owned original-codec probe before native menu Quit; not playback')
    parser.add_argument('--native-replay-faults',action='store_true',help='authored malformed codec inputs after healthy readback, before same idle Quit')
    parser.add_argument('--replay-retention',type=int,choices=(0,100,101),default=0,help='seed authored long replay names for original native retention')
    parser.add_argument('--visible',action='store_true')
    raise SystemExit(run(parser.parse_args()))
