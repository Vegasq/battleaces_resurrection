"""Bundled TLS host + two or four production clients + native result/Continue/Quit.

Explicit external adapters use stdin-only ephemeral credential fixtures because
protected DACL enrollment is unqualified under the tool token. They never relax
production ACL rules. Original Play/build/surrender/Continue/Quit are automated;
this is not actual CMD mouse play, protected deployment, clean-PC or Internet
acceptance. Native worker and simulation clocks remain unchanged.
"""
from __future__ import annotations
import argparse
import csv
import ctypes
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import socket
import subprocess
import time
import traceback

from client_patch.transport import client,launcher
from server.assets import verify_assets
from server.worker_client import _WindowsJob
from tests.test_tls_transport import generate_test_pki,remove_test_pki
from tools.package_integrity import verify
from tools import packaged_network_drivers as drivers
from tools import packaged_custom_evidence as custom_evidence
from tools.packaged_network_evidence import validate,validate_loading_recovery,validate_running_recovery,validate_replays,validate_worker_shutdown,validate_native_selections
from tools.run_secure_match import read_native_log
from tools.verify_packaged_play import job_accounting
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.verify_native_storage import snapshot
from tools.replay_retention import api_path

ROOT=Path(__file__).resolve().parents[1]
require=startup.require


def sources():
    paths=[Path(__file__),ROOT/'tools/packaged_network_drivers.py',ROOT/'tools/packaged_network_evidence.py',
           ROOT/'tools/verify_packaged_play.py',ROOT/'tools/verify_native_storage.py',ROOT/'tools/packaged_custom_evidence.py']
    return quit_probe.sources()|{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def rows(path):
    with path.open(encoding='utf-8-sig') as stream:return list(csv.DictReader(stream,delimiter='\t'))


def imports(report,package,inventory):
    require(report['passed'],'bundled driver reported failure')
    for module in report['production_modules'].values():
        path=Path(module['path']).resolve()
        require(path.is_relative_to(package/'program/app') and inventory['files'][path.relative_to(package).as_posix()]['sha256']==module['sha256'],'bundled driver imported unverified code')


class Child:
    def __init__(self,package,output,driver,request,fixture):
        self.output=output;self.process=self.job=None;self.native=None;self.handle=None
        output.mkdir(parents=True,exist_ok=False)
        script=output/'owned-driver.py';script.write_text(driver,encoding='utf-8')
        request_path=output/'request.json';request_path.write_text(json.dumps(request,indent=2)+'\n')
        self.inputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (script,request_path)}
        cwd=output/'foreign cwd';cwd.mkdir()
        for name in ('sitecustomize.py','server.py','client_patch.py'):(cwd/name).write_text('raise RuntimeError("foreign module must not run")\n')
        environment=os.environ.copy();environment.update(PATH=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'),PYTHONPATH=str(cwd))
        self.stdout=(output/'stdout.txt').open('wb');self.stderr=(output/'stderr.txt').open('wb')
        try:
            info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
            command=[str(package/'program/runtime/python.exe'),'-I','-B',str(script),str(request_path)]
            self.process=subprocess.Popen(command,cwd=cwd,env=environment,stdin=subprocess.PIPE,stdout=self.stdout,stderr=self.stderr,startupinfo=info,close_fds=True)
            self.job=_WindowsJob(self.process.pid)
            raw=json.dumps(fixture,separators=(',',':')).encode('ascii');require(len(raw)<=16384,'private test fixture exceeds bound')
            self.process.stdin.write(raw);self.process.stdin.close()
            ready=output/'job-ready.tmp';ready.write_bytes(b'owned job attached\n');ready.rename(output/'job-ready')
        except BaseException:
            if self.job:self.job.close()
            if self.process is not None:
                if self.process.poll() is None:self.process.kill()
                self.process.wait(timeout=15)
            self.stdout.close();self.stderr.close();raise

    def unchanged(self):
        return all(hashlib.sha256((self.output/name).read_bytes()).hexdigest()==digest for name,digest in self.inputs.items())


def run(args):
    if not hasattr(args,'recover_loading'):args.recover_loading=False
    if not hasattr(args,'recover_running'):args.recover_running=False
    if not hasattr(args,'disconnect_after_frame'):args.disconnect_after_frame=600
    if not hasattr(args,'humans'):args.humans=2
    if not hasattr(args,'custom_rematch'):args.custom_rematch=False
    require(not (args.recover_loading and args.recover_running),'select one recovery stage')
    recovering=args.recover_loading or args.recover_running
    require(args.disconnect_after_frame in (200,600),'unsupported running disconnect threshold')
    recover_stage='running' if args.recover_running else 'loading' if args.recover_loading else None
    packages,game,assets,output=(p.resolve() for p in (args.packages,args.game,args.assets,args.output))
    require(os.name=='nt' and 120<=args.timeout<=600 and args.mode in (1,2,5),'bounded supported Windows match required')
    require(args.humans in (2,4) and (args.humans==2 or args.mode==2),'four humans require public2v2')
    require(not recovering or args.mode==1,'packaged recovery control requires two full-human1v1 attempts')
    require(not args.custom_rematch or args.mode==1 and args.humans==2 and not recovering,'Custom rematch requires two humans and no public fault injection')
    require(all(p.is_relative_to(ROOT/'local') for p in (packages,game,assets,output)),'owned ignored paths required')
    server_package=packages/'battleaces-server-win64';client_package=packages/'battleaces-client-win64'
    inventories={kind:verify(path,kind) for kind,path in (('server',server_package),('client',client_package))}
    launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True)
    helper=(game/'BattleAcesOffline.dll').read_bytes()
    require(helper==(client_package/'program/client-helper/BattleAcesOffline.dll').read_bytes() and b'BA_RESURRECTION_NATIVE_QUIT_GATE_V1' in helper,'install the exact packaged gated-Quit diagnostic helper')
    require(not args.custom_rematch or b'BA_RESURRECTION_CUSTOM_LEAVE_GATE_V1' in helper,'Custom qualification requires the owned post-match Leave diagnostic')
    receipt=quit_probe.verify_build_receipt(game,args.helper_build_receipt.resolve());assets_before=verify_assets(assets)
    output.mkdir(parents=True,exist_ok=False);pki_folder=output/'ephemeral-pki';pki=generate_test_pki(pki_folder)
    with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    config_folder=output/'config';config_folder.mkdir();data=output/'host-data'
    host_config=json.loads((server_package/'config/host.example.json').read_bytes())
    host_config.update(listen_host='127.0.0.1',listen_port=port,assets_directory=str(assets),data_directory=str(data),
                       certificate_file=str(pki['cert']),private_key_file=str(pki['key']),credential_directory=str(output/'authored-private-store'),
                       diagnostic_audit=True,log_max_bytes=8*1024*1024)
    host_path=config_folder/'host.json';host_path.write_text(json.dumps(host_config,indent=2)+'\n')
    identities=[dict(schema=1,player_id='p_'+secrets.token_hex(16),invite_id='i_'+secrets.token_hex(16),token='ba1_'+secrets.token_urlsafe(32)) for _ in range(args.humans)]
    gate=secrets.token_hex(16);gate_path=game/'investigation/runtime'/('public-queue-'+gate+'.ready')
    retry_path=gate_path.with_name('public-queue-'+gate+'-retry.ready')
    require(not gate_path.exists() and not retry_path.exists(),'public start/retry gate already exists')
    configs=[host_path];children=[];records=[];server_child=None;gate_created=False;quit_released=False;fault_requested=False;retry_released=False;leave_stage=0
    shared=args.shared_settings.resolve()
    def channels():return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    report=dict(passed=False,scope=__doc__,mode=args.mode,humans=args.humans,custom_rematch=args.custom_rematch,recover_loading=args.recover_loading,recover_stage=recover_stage,helper_build=receipt,shared_before=channels(),source_sha256_at_start=sources(),forced_cleanup=False,
                packages=str(packages),assets_manifest_sha256=hashlib.sha256((assets/'asset-manifest.json').read_bytes()).hexdigest())
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetTickCount64.restype=ctypes.c_ulonglong
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.WaitForSingleObject.restype=ctypes.c_ulong
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    started=time.monotonic();config_bytes={str(host_path):host_path.read_bytes()}
    try:
        server_output=output/'server'
        request=dict(package=str(server_package),output=str(server_output),config=str(host_path),timeout=args.timeout,
                     credential_directory=host_config['credential_directory'],recover_stage=recover_stage,disconnect_after_frame=args.disconnect_after_frame,custom_rematch=args.custom_rematch)
        server_child=Child(server_package,server_output,drivers.SERVER,request,dict(identities=identities));children.append(server_child)
        while not (server_output/'server-ready.json').exists():
            require(server_child.process.poll() is None and time.monotonic()-started<60,'bundled host did not become ready');time.sleep(.05)
        ready=json.loads((server_output/'server-ready.json').read_bytes());require(ready['address']==['127.0.0.1',port],'bundled host bound the wrong listener')
        for index,identity in enumerate(identities):
            client_output=output/f'client-{index}'
            profile='nativestest_network_'+secrets.token_hex(6)+'_'+str(index)
            folder=game/'.battleaces-resurrection/profiles'/profile
            require(not folder.exists(),'owned native profile already exists')
            config=config_folder/f'client-{index}.json';placeholder=config_folder/f'authored-invite-{index}.placeholder'
            placeholder.write_bytes(b'authored nonsecret placeholder; stdin fixture only\n')
            settings=client.defaults(game);settings.update(display_name=f'Packaged Human {index+1}',local_profile=profile,
                server_host='127.0.0.1',server_port=port,server_name='localhost',ca_bundle=str(pki['ca']),credential_file=str(placeholder))
            config.write_text(json.dumps(settings,indent=2)+'\n');configs.extend((config,placeholder))
            for path in (config,placeholder):config_bytes[str(path)]=path.read_bytes()
            request=dict(package=str(client_package),game=str(game),output=str(client_output),config=str(config),profile=profile,
                port=port,invite_placeholder=str(placeholder),mode=args.mode,index=index,gate=gate,visible=args.visible,recover_stage=recover_stage,custom_rematch=args.custom_rematch)
            child=Child(client_package,client_output,drivers.CLIENT,request,identity);children.append(child)
            records.append(dict(child=child,folder=folder,profile=profile,name=settings['display_name'],player=identity['player_id'],deck_edited=index%2==1))
        while True:
            require(server_child.process.poll() is None,'bundled host stopped during client gameplay')
            for index,row in enumerate(records):
                child=row['child'];process_path=child.output/'game-process.json'
                if child.native is None and process_path.exists():
                    child.native=json.loads(process_path.read_bytes());child.handle=kernel.OpenProcess(0x100000|0x1000,False,child.native['pid'])
                    require(child.handle,'cannot observe owned native game')
                if child.native:
                    row['log']=read_native_log(game,child.native['pid'],since_tick=child.native['launch_tick'])
                    require(not any(marker in row['log'] for marker in ('Public client failure:','Client lifecycle invariant failed:','Public result Continue routing failed:',
                        'Native Quit probe failed:','Offline initialization failed:','LAN normal-build smoke disabled','LAN normal-build smoke stopped')),
                        'native bundled multiplayer lifecycle failed')
                    for failure in re.findall(r'Offline loop stopped in [^\n]*',row['log']):
                        require(recovering and fault_requested and index==0 and re.fullmatch(
                            r'Offline loop stopped in (?:LAN update|LAN front update|dedicated session update): '
                            r'(?:match server disconnected before a result|Secure session is closed)',failure.rstrip('\r')),
                            'unexpected native bundled multiplayer stop')
                    if (row['folder']/'quit-trace.jsonl').exists():
                        trace=quit_probe.current_trace_rows((row['folder']/'quit-trace.jsonl').read_bytes(),child.native['pid'],child.native['launch_tick'])
                        confirm=[r['tick'] for r in trace if r['event']=='OnConfirm.dispatch']
                        if confirm:require(len(confirm)==1 and (child.process.poll() is not None or kernel.GetTickCount64()-confirm[0]<60000),'native Quit exceeded60s')
                require(child.process.poll() is None or quit_released and child.process.returncode==0,'bundled client exited before accepted match/Quit')
            if not gate_created and all('PUBLIC QUEUE SMOKE waiting for shared gate: key='+gate in row.get('log','') for row in records):
                require(not any('Public search intent:' in row['log'] for row in records),'public search bypassed shared menu gate')
                with gate_path.open('xb'):pass
                gate_created=True
            if recovering and not fault_requested and all('Public native match joined: ticket=1 ' in row.get('log','') for row in records):
                received=[[int(value) for value in re.findall(r'LAN received frame (\d+),',row['log'])] for row in records]
                reached=args.recover_loading or all(values and max(values)>=args.disconnect_after_frame for values in received)
                if reached:
                    require(all(('Offline world ready;' in row['log'])==args.recover_running for row in records),
                            'disconnect missed the requested native map-load/running window')
                    report['fault_native_frames']=[max(values,default=-1) for values in received]
                    command=server_output/'server-disconnect.tmp';command.write_text(json.dumps(dict(player=identities[0]['player_id']))+'\n');command.rename(server_output/'server-disconnect.json')
                    fault_requested=True
            if recovering and fault_requested and not retry_released and all('PUBLIC QUEUE SMOKE waiting for retry gate: key='+gate in row.get('log','') for row in records):
                live=json.loads((server_output/'server-live.json').read_bytes())
                if all(live.get(key)==0 for key in ('rooms','retired','entries','offers','cleanup')):
                    require((server_output/'server-fault.json').exists() and live['sessions']==1,'old room/session cleanup was not complete before retry')
                    report['fault']=json.loads((server_output/'server-fault.json').read_bytes())
                    for row in records:
                        require(row['log'].count('Public search intent:')==1,'replacement Play bypassed the retry gate')
                        row['retry_offset']=len(row['log'])
                    with retry_path.open('xb'):pass
                    retry_released=True
            if args.custom_rematch:
                ready=(all('COMMUNITY MATCH SMOKE passed: two native Start/result/Continue cycles;' in row.get('log','') for row in records)
                       if leave_stage==0 else 'COMMUNITY MATCH SMOKE post-match leave passed: role=guest' in records[1].get('log',''))
                if leave_stage<2 and ready:
                    live=json.loads((server_output/'server-live.json').read_bytes());lobbies=live.get('lobbies',[])
                    expected=sorted(row['player'] for row in records) if leave_stage==0 else [records[0]['player']]
                    if all(live.get(key)==0 for key in ('rooms','retired','entries','offers','cleanup')) and len(lobbies)==1 and lobbies[0]['members']==expected:
                        from server.community_protocol import OPEN
                        require(lobbies[0]['phase']==OPEN and lobbies[0]['epoch']==2,'Custom lobby failed to reopen after two matches')
                        with (records[1-leave_stage]['folder']/'custom-match-leave.ready').open('xb'):pass
                        leave_stage+=1
                returned=leave_stage==2 and all('COMMUNITY MATCH SMOKE post-match leave passed:' in row.get('log','') for row in records)
            else:
                returned=(all('Public intent retired: ticket=2 reason=returned nativeIdle=1 disconnect=0' in row.get('log','') for row in records)
                          if recovering else all('PUBLIC QUEUE completed return:' in row.get('log','') for row in records))
            if not quit_released and returned:
                live=json.loads((server_output/'server-live.json').read_bytes())
                if all(live.get(key)==0 for key in ('rooms','retired','entries','offers','cleanup')):
                    require(not args.custom_rematch or not live['lobbies'],'Custom lobby retained after both original Leaves')
                    for row in records:
                        with (row['folder']/'native-quit.ready').open('xb'):pass
                    quit_released=True
            if quit_released and all(row['child'].process.poll()==0 for row in records):break
            require(time.monotonic()-started<args.timeout,'bundled multiplayer deadline reached');time.sleep(.1)
        (server_output/'server-stop').write_bytes(b'owned qualification complete\n');server_child.process.wait(timeout=35)
        require(server_child.process.returncode==0,'bundled host did not stop through original cleanup')
        server_report=json.loads((server_output/'server-driver.json').read_bytes());imports(server_report,server_package,inventories['server'])
        expected_authenticated=[row['player'] for row in records]+([records[0]['player']] if recovering else [])
        require(sorted(server_report['authenticated'])==sorted(expected_authenticated),'bundled TLS identity ownership differs')
        frozen=server_report['frozen_matches'];require(len(frozen)==(2 if recovering or args.custom_rematch else 1),'bundled host match count differs')
        final=frozen[-1]
        events=[]
        for path in sorted((data/'logs').glob('events.jsonl*'),reverse=True):events.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())
        report['worker_cleanup']=validate_worker_shutdown(server_report['workers'],events,fault=report.get('fault'))
        final_frames=sum(e['event']=='frame_queued' and e.get('match')==final['match'] for e in events)
        for row in records:
            child=row['child'];bundled=json.loads((child.output/'client-driver.json').read_bytes());imports(bundled,client_package,inventories['client'])
            require(kernel.WaitForSingleObject(child.handle,0)==0,'owned game still alive after launcher exit')
            code=ctypes.c_ulong();require(kernel.GetExitCodeProcess(child.handle,ctypes.byref(code)) and code.value==0,'native game exit is not0')
            row['pid']=child.native['pid'];row['log']=read_native_log(game,row['pid'],since_tick=child.native['launch_tick'])
            trace=quit_probe.current_trace_rows((row['folder']/'quit-trace.jsonl').read_bytes(),row['pid'],child.native['launch_tick'])
            require([r['event'] for r in trace]==['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return'],'original menu Quit trace invalid')
            row['full_log']=row['log'];(child.output/'native.log').write_text(row['log'],encoding='utf-8')
            row['receipts']=rows(game/'investigation/runtime'/f'dedicated-receipts-{row["pid"]}-{final["match"]}.tsv')
            row['audit']=rows(game/'investigation/runtime'/f'lan-audit-{row["pid"]}-{final["match"]}.tsv')
            if recovering:
                row['initial_log']=row['log'][:row['retry_offset']];row['log']=row['log'][row['retry_offset']:]
                initial_receipts=game/'investigation/runtime'/f'dedicated-receipts-{row["pid"]}-{frozen[0]["match"]}.tsv'
                row['initial_receipts']=rows(initial_receipts) if initial_receipts.exists() else []
                if args.recover_running:
                    row['initial_audit']=rows(game/'investigation/runtime'/f'lan-audit-{row["pid"]}-{frozen[0]["match"]}.tsv')
            for kind in ('receipts','audit'):(child.output/(kind+'.json')).write_text(json.dumps(row[kind],indent=2)+'\n')
            replays=list((row['folder']/'AutoSaveReplays').iterdir())
            replay_bytes=[api_path(path).read_bytes() for path in replays]
            if args.custom_rematch:
                row['matches']={}
                for round_ in frozen:
                    match=round_['match'];row['matches'][match]=dict(receipts=rows(game/'investigation/runtime'/f'dedicated-receipts-{row["pid"]}-{match}.tsv'),
                        audit=rows(game/'investigation/runtime'/f'lan-audit-{row["pid"]}-{match}.tsv'))
                    for kind,value in row['matches'][match].items():(child.output/(kind+'-'+match+'.json')).write_text(json.dumps(value,indent=2)+'\n')
                counts={r['match']:sum(e['event']=='frame_queued' and e.get('match')==r['match'] for e in events) for r in frozen}
                row['replays']=custom_evidence.replays(replay_bytes,frozen,counts);row['replay_set']=dict(completed_matches=row['replays'])
                row['replay']=row['replays'][final['match']]
            else:
                row['replay_set']=validate_replays(replay_bytes,frozen=frozen,frames=final_frames,
                    loading_abort=args.recover_loading,running_abort_frames=len(row['initial_receipts']) if args.recover_running else None)
                row['replay']=row['replay_set']['completed']
            row['settings']=startup.native_settings_evidence(game,child.output,row['pid'],child.native['launch_tick'],row['profile'])
            row['trace']=trace;row['driver_report']=bundled
        selected=events
        if recovering:
            validator=validate_running_recovery if args.recover_running else validate_loading_recovery
            report['recovery']=validator(events,records,fault=report['fault'])
            selected=[e for e in events if e.get('match')==final['match'] or e['event']=='public_queue_entered' and e.get('ticket')==2]
        if args.custom_rematch:
            report['custom']=custom_evidence.validate(events,records,frozen=frozen,commands=server_report['custom_commands'])
        else:
            native_selections=validate_native_selections(records,final) if args.humans==4 else None
            report['match']=validate(selected,records,mode=args.mode,ticket=2 if recovering else 1,expected_decks=native_selections)
            if native_selections is not None:report['native_selections']=native_selections
            require(final['full_loadout_seats']==report['match']['human_seats'],'bundled native clients lost complete human loadouts')
        for row in records:
            human=[value for value in final['humans'].values() if value['profile']==row['player']]
            require(len(human)==1 and human[0]['name']==row['name'],'configured name lost in authoritative native roster')
            if recovering:
                before=[deck for slot,deck in frozen[0]['decks'].items() if frozen[0]['humans'].get(slot,{}).get('profile')==row['player']]
                after=[deck for slot,deck in final['decks'].items() if final['humans'].get(slot,{}).get('profile')==row['player']]
                require(len(before)==len(after)==1 and before==after,'recovery lost the selected native human deck')
        last_worker=report['custom']['worker_pids'][-1] if args.custom_rematch else report['match']['worker_pid']
        require(last_worker==server_report['workers'][-1]['pid'] and final['game_data_sha256']==server_report['workers'][-1]['game_data_sha256'],'bundled native worker ran a different game')
        report.update(passed=True,server=server_report,clients=[{k:row[k] for k in ('pid','name','player','profile','replay','replay_set','settings','trace','driver_report')} for row in records])
    except BaseException as error:report.update(passed=False,error=repr(error),traceback=traceback.format_exc())
    finally:
        if server_child and server_child.process.poll() is None:
            try:(server_child.output/'server-stop').write_bytes(b'owned failure cleanup\n');server_child.process.wait(timeout=35)
            except BaseException as error:report.update(server_stop_error=repr(error),forced_cleanup=True)
        report['jobs']=[]
        for child in children:
            try:
                accounting=job_accounting(child.job.handle)
                report['jobs'].append(dict(pid=child.process.pid,**accounting))
                if accounting['active_processes']:report['forced_cleanup']=True
            except BaseException as error:report.update(passed=False,forced_cleanup=True,job_error=repr(error))
            child.job.close()
            try:child.process.wait(timeout=15)
            except subprocess.TimeoutExpired:child.process.kill();child.process.wait(timeout=15);report['forced_cleanup']=True
            child.stdout.close();child.stderr.close()
            if child.native:(child.output/'native.log').write_text(read_native_log(game,child.native['pid'],since_tick=child.native['launch_tick']),encoding='utf-8')
            if child.handle:
                if kernel.WaitForSingleObject(child.handle,15000)!=0:report['passed']=False
                kernel.CloseHandle(child.handle)
        if gate_created:
            require(gate_path.resolve().parent==(game/'investigation/runtime').resolve() and not gate_path.is_symlink(),'owned public gate changed path')
            gate_path.unlink()
        if retry_released:
            require(retry_path.resolve().parent==(game/'investigation/runtime').resolve() and not retry_path.is_symlink(),'owned retry gate changed path');retry_path.unlink()
        for index in (1,0)[:leave_stage]:
            path=records[index]['folder']/'custom-match-leave.ready'
            require(path.parent.resolve()==records[index]['folder'].resolve() and not path.is_symlink(),'owned Custom leave gate changed path');path.unlink()
        report['adapters_unchanged']=all(child.unchanged() for child in children)
        report['config_unchanged']=all(Path(path).read_bytes()==raw for path,raw in config_bytes.items())
        try:report['package_files_unchanged']=all(verify(path,kind)==inventories[kind] for kind,path in (('server',server_package),('client',client_package)))
        except BaseException as error:report.update(package_files_unchanged=False,package_error=repr(error))
        report['assets_unchanged']=verify_assets(assets)==assets_before
        report.update(shared_after=channels(),source_sha256_at_finish=sources(),elapsed_seconds=time.monotonic()-started)
        report['shared_channels_unchanged']=report['shared_before']==report['shared_after'];report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        # Check actual public evidence files for accidental fixture-token disclosure.
        report['fixture_tokens_not_logged']=not any(identity['token'].encode() in path.read_bytes() for identity in identities for child in children
            for path in child.output.iterdir() if path.is_file() and path.suffix in ('.txt','.json','.log'))
        remove_test_pki(pki_folder)
        checks=('adapters_unchanged','config_unchanged','package_files_unchanged','assets_unchanged','shared_channels_unchanged','source_files_unchanged','fixture_tokens_not_logged')
        report['passed'] &= all(report.get(k,False) for k in checks) and not report['forced_cleanup']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','forced_cleanup','elapsed_seconds','error') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('packages','game','assets','output','helper-build-receipt','shared-settings'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--mode',type=int,choices=(1,2,5),default=1)
    parser.add_argument('--humans',type=int,choices=(2,4),default=2,help='four independent native clients are supported for full-human2v2')
    parser.add_argument('--custom-rematch',action='store_true',help='original Custom invite, two human matches, changed-deck rematch, sequential Leave and Quit')
    parser.add_argument('--timeout',type=int,default=420)
    parser.add_argument('--visible',action='store_true')
    recovery=parser.add_mutually_exclusive_group()
    recovery.add_argument('--recover-loading',action='store_true',help='disconnect first accepted loading match, then complete a new native match in the same processes')
    recovery.add_argument('--recover-running',action='store_true',help='disconnect after both clients play/build, then complete a new native match in the same processes')
    parser.add_argument('--disconnect-after-frame',type=int,choices=(200,600),default=600,help='owned running fault threshold; default600 covers original builds on both clients')
    raise SystemExit(run(parser.parse_args()))
