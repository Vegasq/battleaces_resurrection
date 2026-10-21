"""Bundled TLS host + one to four production clients + native result/Continue/Quit.

Default external adapters use explicit stdin-only ephemeral identity fixtures.
Opt-in --real-credentials requires the normal desktop account and uses protected
issuance/enrollment and the actual production store/readers. No ACL relaxation.
Original Play/build/surrender/Continue/Quit are automated;this is not CMD mouse
play,SCM,clean-PC or Internet acceptance. Native simulation clocks are unchanged.
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

from client_patch.transport import client,launcher,rc_setup
from client_patch.transport import enrollment
from server import credentials as private
from server.assets import verify_assets
from server.worker_client import _WindowsJob
from tests.test_tls_transport import generate_test_pki,remove_test_pki
from tools.package_integrity import verify
from tools import packaged_network_drivers as drivers
from tools import packaged_custom_evidence as custom_evidence
from tools.packaged_network_evidence import validate,validate_loading_recovery,validate_running_recovery,validate_replays,validate_worker_shutdown,validate_native_selections,validate_bot_fill,recording_from_proof
from tools.run_secure_match import read_native_log
from tools.verify_packaged_play import job_accounting
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.verify_native_storage import snapshot
from tools.replay_retention import api_path
from tools.packaged_owner_credentials import OwnerCredentials
from tools.verify_owner_credentials import restricting_sids_present

ROOT=Path(__file__).resolve().parents[1]
require=startup.require


def sources():
    paths=[Path(__file__),ROOT/'tools/packaged_network_drivers.py',ROOT/'tools/packaged_network_evidence.py',
           ROOT/'tools/verify_packaged_play.py',ROOT/'tools/verify_native_storage.py',ROOT/'tools/packaged_custom_evidence.py',
           ROOT/'tools/packaged_owner_credentials.py',ROOT/'tools/verify_owner_credentials.py']
    return quit_probe.sources()|{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def rows(path):
    with path.open(encoding='utf-8-sig') as stream:return list(csv.DictReader(stream,delimiter='\t'))


def tokens_not_logged(tokens, paths):
    """Keep private keys separate from RC's public identity-only fixture records."""
    encoded=[token.encode('ascii') for token in tokens]
    return not any(token in Path(path).read_bytes() for path in paths for token in encoded)


def publish_empty_gate(path):
    """Expose a diagnostic gate only after its writer closes (native denies writes)."""
    path=Path(path)
    require(path.resolve().is_relative_to(ROOT/'local') and not os.path.lexists(path),
            'fresh owned diagnostic gate required')
    pending=path.with_name(path.name+'.pending')
    with pending.open('xb'):pass
    pending.rename(path)


def read_live_snapshot(path):
    """Read the last complete bounded status record;never replace an open file."""
    path=Path(path).resolve()
    require(path.is_relative_to(ROOT/'local') and path.name=='server-live.jsonl',
            'owned diagnostic snapshot journal required')
    with path.open('rb') as stream:raw=stream.read(drivers.SNAPSHOT_MAX_BYTES+1)
    require(len(raw)<=drivers.SNAPSHOT_MAX_BYTES,'diagnostic snapshot journal exceeds bound')
    end=raw.rfind(b'\n');require(end>=0,'diagnostic snapshot has no complete record')
    line=raw[raw.rfind(b'\n',0,end)+1:end]
    require(0<len(line)+1<=drivers.SNAPSHOT_MAX_ROW_BYTES,'diagnostic snapshot row exceeds bound')
    record=json.loads(line)
    require(isinstance(record,dict) and type(record.get('sequence')) is int and record['sequence']>0 and
            isinstance(record.get('snapshot'),dict),'invalid diagnostic snapshot record')
    return record['snapshot']


def quit_readiness(live,*,custom=False):
    """A sampled server view can lag native Leave ACKs;wait for actual drain."""
    counts=('rooms','retired','entries','offers','cleanup')
    require(isinstance(live,dict) and all(type(live.get(key)) is int and live[key]>=0 for key in counts),
            'invalid server drain snapshot')
    require(not custom or type(live.get('lobbies')) is list,'invalid Custom lobby drain snapshot')
    return all(live[key]==0 for key in counts) and (not custom or not live['lobbies'])


def native_lifecycle_failure(text):
    markers=('Public client failure:','Client lifecycle invariant failed:','Public result Continue routing failed:',
             'Native Quit probe failed:','Offline initialization failed:','LAN normal-build smoke disabled',
             'LAN normal-build smoke stopped','COMMUNITY LEAVE gate open refused:',
             'Custom leave gate sharing retry exceeded 1000ms')
    return next((marker for marker in markers if marker in text),None)


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
    if not hasattr(args,'real_credentials'):args.real_credentials=False
    if not hasattr(args,'rc_open'):args.rc_open=False
    require(not args.rc_open or not (args.real_credentials or args.recover_loading or args.recover_running),
            'RC qualification uses production open admission without invite/fault fixtures')
    if not hasattr(args,'preflight_only'):args.preflight_only=False
    require(not args.preflight_only or args.real_credentials,'read-only owner preflight requires real-credential mode')
    require(not (args.recover_loading and args.recover_running),'select one recovery stage')
    recovering=args.recover_loading or args.recover_running
    require(args.disconnect_after_frame in (200,600),'unsupported running disconnect threshold')
    recover_stage='running' if args.recover_running else 'loading' if args.recover_loading else None
    packages,game,assets,output=(p.resolve() for p in (args.packages,args.game,args.assets,args.output))
    require(os.name=='nt' and 120<=args.timeout<=600 and args.mode in (1,2,5),'bounded supported Windows match required')
    require(args.humans in (1,2,3,4) and (args.humans<=2 or args.mode==2),'three or four humans require public2v2')
    require(not args.real_credentials or args.humans in (2,4),'protected enrollment diagnostic supports two or four humans')
    require(not recovering or args.humans==2,'packaged recovery control requires two human clients')
    require(not args.custom_rematch or args.mode==1 and args.humans==2 and not recovering,'Custom rematch requires two humans and no public fault injection')
    require(all(p.is_relative_to(ROOT/'local') for p in (packages,game,assets,output)),'owned ignored paths required')
    server_package=packages/'battleaces-server-win64';client_package=packages/'battleaces-client-win64'
    inventories={kind:verify(path,kind) for kind,path in (('server',server_package),('client',client_package))}
    launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True)
    helper=(game/'BattleAcesOffline.dll').read_bytes()
    require(helper==(client_package/'program/client-helper/BattleAcesOffline.dll').read_bytes() and b'BA_RESURRECTION_NATIVE_QUIT_GATE_V1' in helper,'install the exact packaged gated-Quit diagnostic helper')
    require(not args.custom_rematch or b'BA_RESURRECTION_CUSTOM_LEAVE_GATE_V1' in helper,'Custom qualification requires the owned post-match Leave diagnostic')
    receipt=quit_probe.verify_build_receipt(game,args.helper_build_receipt.resolve());assets_before=verify_assets(assets)
    if args.real_credentials:
        for module in (client,enrollment,private):
            path=Path(module.__file__).resolve();relative=path.relative_to(ROOT).as_posix()
            require(hashlib.sha256(path.read_bytes()).hexdigest()==inventories['client']['files']['program/app/'+relative]['sha256'],
                    'owner issuer/enrollment SDK differs from the actual client bundle')
        restricted=restricting_sids_present()
        if args.preflight_only or restricted:
            output.mkdir(parents=True,exist_ok=False)
            report=dict(passed=False,stage='preflight_only' if args.preflight_only else 'normal_desktop_required',
                private_api_attempted=False,restricting_sids_present=restricted,preflight_only=args.preflight_only,
                source_sha256=sources(),helper_build=receipt,package_files_verified=True,assets_verified=True)
            (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            print(json.dumps({k:report[k] for k in ('passed','stage','private_api_attempted','restricting_sids_present')}))
            return 2
    output.mkdir(parents=True,exist_ok=False);pki_folder=output/'ephemeral-pki'
    if args.rc_open:
        from server.rc_host import generate_certificate
        pki_folder.mkdir()
        certificate,key=generate_certificate()
        pki=dict(cert=pki_folder/'server.pem',key=pki_folder/'server.key')
        pki['cert'].write_bytes(certificate);pki['key'].write_bytes(key)
    else:pki=generate_test_pki(pki_folder)
    with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    config_folder=output/'config';config_folder.mkdir();data=output/'host-data'
    host_config=json.loads((server_package/'config/host.example.json').read_bytes())
    host_config.update(listen_host='127.0.0.1',listen_port=port,assets_directory=str(assets),data_directory=str(data),
                       certificate_file=str(pki['cert']),private_key_file=str(pki['key']),credential_directory=str(output/'authored-private-store'),
                       diagnostic_audit=True,log_max_bytes=8*1024*1024)
    if args.rc_open:host_config.update(schema=2,access_mode='rc-open',credential_directory=None)
    host_path=config_folder/'host.json';host_path.write_text(json.dumps(host_config,indent=2)+'\n')
    identities=[] if args.real_credentials else [dict(schema=1,player_id='p_'+secrets.token_hex(16),invite_id='i_'+secrets.token_hex(16),token='ba1_'+secrets.token_urlsafe(32)) for _ in range(args.humans)]
    private_tokens=[value['token'] for value in identities]
    rc_clients=[]
    if args.rc_open:
        private_tokens=[]
        for index in range(args.humans):
            profile='nativestest_rcnetwork_'+secrets.token_hex(6)+'_'+str(index)
            config=config_folder/f'client-{index}.json'
            settings={key:value for key,value in client.defaults(game).items() if key in rc_setup.KEYS}
            settings.update(schema=4,display_name=f'Packaged Human {index+1}',local_profile=profile,
                            server_host='127.0.0.1',server_port=port)
            config.write_text(json.dumps(settings,indent=2)+'\n')
            target=rc_setup.Resolver(config,game).read()
            identities[index]=dict(player_id=target.player_id)
            private_tokens.append(target.token)
            rc_clients.append((profile,config,settings))
    owner=OwnerCredentials(output) if args.real_credentials else None
    gate=secrets.token_hex(16);gate_path=game/'investigation/runtime'/('public-queue-'+gate+'.ready')
    retry_path=gate_path.with_name('public-queue-'+gate+'-retry.ready')
    require(not gate_path.exists() and not retry_path.exists(),'public start/retry gate already exists')
    configs=[host_path];children=[];records=[];server_child=None;gate_created=False;quit_released=False;fault_requested=False;retry_released=False;leave_stage=0;quit_readiness_began=None
    shared=args.shared_settings.resolve()
    def channels():return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    report=dict(passed=False,scope=__doc__,rc_open=args.rc_open,mode=args.mode,humans=args.humans,real_credentials=args.real_credentials,custom_rematch=args.custom_rematch,recover_loading=args.recover_loading,recover_stage=recover_stage,helper_build=receipt,shared_before=channels(),source_sha256_at_start=sources(),forced_cleanup=False,
                packages=str(packages),assets_manifest_sha256=hashlib.sha256((assets/'asset-manifest.json').read_bytes()).hexdigest())
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetTickCount64.restype=ctypes.c_ulonglong
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.WaitForSingleObject.restype=ctypes.c_ulong
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    started=time.monotonic();config_bytes={str(host_path):host_path.read_bytes()}
    try:
        if owner:
            report['private_api_attempted']=True;identities=owner.issue(args.humans)
            private_tokens=[value['token'] for value in identities]
            check_output=output/'server-command-check'
            check=Child(server_package,check_output,drivers.SERVER_CHECK,
                dict(package=str(server_package),output=str(check_output),config=str(host_path)),{})
            children.append(check);check.process.wait(timeout=75)
            require(check.process.returncode==0,'actual packaged server check command failed')
            command_report=json.loads((check_output/'server-command-check.json').read_bytes())
            require(command_report['passed'],'actual packaged server check evidence failed')
            report['server_command_check']=command_report
        server_output=output/'server'
        request=dict(package=str(server_package),output=str(server_output),config=str(host_path),timeout=args.timeout,
                     credential_directory=host_config['credential_directory'],recover_stage=recover_stage,disconnect_after_frame=args.disconnect_after_frame,custom_rematch=args.custom_rematch,real_credentials=args.real_credentials,rc_open=args.rc_open)
        server_identities=[dict(player_id=value['player_id']) for value in identities] if owner else identities
        server_child=Child(server_package,server_output,drivers.SERVER,request,dict(identities=server_identities));children.append(server_child)
        while not (server_output/'server-ready.json').exists():
            require(server_child.process.poll() is None and time.monotonic()-started<60,'bundled host did not become ready');time.sleep(.05)
        ready=json.loads((server_output/'server-ready.json').read_bytes());require(ready['address']==['127.0.0.1',port],'bundled host bound the wrong listener')
        for index,identity in enumerate(identities):
            client_output=output/f'client-{index}'
            profile='nativestest_network_'+secrets.token_hex(6)+'_'+str(index)
            folder=game/'.battleaces-resurrection/profiles'/profile
            require(not folder.exists(),'owned native profile already exists')
            config=config_folder/f'client-{index}.json';placeholder=config_folder/f'authored-invite-{index}.placeholder'
            settings=client.defaults(game);settings.update(display_name=f'Packaged Human {index+1}',local_profile=profile)
            if args.rc_open:
                profile,config,settings=rc_clients[index]
                folder=game/'.battleaces-resurrection/profiles'/profile
            elif owner:
                placeholder=owner.enroll(index,config,settings,pki['ca'],port,client_package=client_package)
            else:
                placeholder.write_bytes(b'authored nonsecret placeholder; stdin fixture only\n')
                settings.update(server_host='127.0.0.1',server_port=port,server_name='localhost',ca_bundle=str(pki['ca']),credential_file=str(placeholder))
                config.write_text(json.dumps(settings,indent=2)+'\n')
            paths=(config,) if args.rc_open else (config,placeholder)
            configs.extend(paths)
            for path in paths:config_bytes[str(path)]=path.read_bytes()
            request=dict(package=str(client_package),game=str(game),output=str(client_output),config=str(config),profile=profile,
                port=port,invite_placeholder=str(placeholder),mode=args.mode,index=index,gate=gate,visible=args.visible,recover_stage=recover_stage,custom_rematch=args.custom_rematch,real_credentials=args.real_credentials,rc_open=args.rc_open)
            child=Child(client_package,client_output,drivers.CLIENT,request,dict(player_id=identity['player_id']) if owner or args.rc_open else identity);children.append(child)
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
                    failure=native_lifecycle_failure(row['log'])
                    if failure:report['native_failure']=dict(client=index,pid=child.native['pid'],marker=failure,observed_tick=kernel.GetTickCount64())
                    require(failure is None,'native bundled multiplayer lifecycle failed')
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
                publish_empty_gate(gate_path)
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
                live=read_live_snapshot(server_output/'server-live.jsonl')
                if all(live.get(key)==0 for key in ('rooms','retired','entries','offers','cleanup')):
                    require((server_output/'server-fault.json').exists() and live['sessions']==1,'old room/session cleanup was not complete before retry')
                    report['fault']=json.loads((server_output/'server-fault.json').read_bytes())
                    for row in records:
                        require(row['log'].count('Public search intent:')==1,'replacement Play bypassed the retry gate')
                        row['retry_offset']=len(row['log'])
                    publish_empty_gate(retry_path)
                    retry_released=True
            if args.custom_rematch:
                ready=(all('COMMUNITY MATCH SMOKE passed: two native Start/result/Continue cycles;' in row.get('log','') for row in records)
                       if leave_stage==0 else 'COMMUNITY MATCH SMOKE post-match leave passed: role=guest' in records[1].get('log',''))
                if leave_stage<2 and ready:
                    live=read_live_snapshot(server_output/'server-live.jsonl');lobbies=live.get('lobbies',[])
                    expected=sorted(row['player'] for row in records) if leave_stage==0 else [records[0]['player']]
                    if all(live.get(key)==0 for key in ('rooms','retired','entries','offers','cleanup')) and len(lobbies)==1 and lobbies[0]['members']==expected:
                        from server.community_protocol import OPEN
                        require(lobbies[0]['phase']==OPEN and lobbies[0]['epoch']==2,'Custom lobby failed to reopen after two matches')
                        publish_empty_gate(records[1-leave_stage]['folder']/'custom-match-leave.ready')
                        leave_stage+=1
                returned=leave_stage==2 and all('COMMUNITY MATCH SMOKE post-match leave passed:' in row.get('log','') for row in records)
            else:
                returned=(all('Public intent retired: ticket=2 reason=returned nativeIdle=1 disconnect=0' in row.get('log','') for row in records)
                          if recovering else all('PUBLIC QUEUE completed return:' in row.get('log','') for row in records))
            if not quit_released and returned:
                if quit_readiness_began is None:quit_readiness_began=time.monotonic()
                live=read_live_snapshot(server_output/'server-live.jsonl')
                ready=quit_readiness(live,custom=args.custom_rematch)
                if args.custom_rematch:
                    elapsed=time.monotonic()-quit_readiness_began
                    observations=report.setdefault('custom_quit_readiness',[])
                    observations.append(dict(seconds=elapsed,ready=ready,lobbies=len(live['lobbies']),
                        **{key:live[key] for key in ('rooms','retired','entries','offers','cleanup')}))
                    del observations[:-5]
                    require(elapsed<5,'Custom leave lobby cleanup did not settle within5s')
                if ready:
                    require(not args.custom_rematch or not live['lobbies'],'Custom lobby retained after both original Leaves')
                    for row in records:
                        publish_empty_gate(row['folder']/'native-quit.ready')
                    quit_released=True
            if quit_released and all(row['child'].process.poll()==0 for row in records):break
            require(time.monotonic()-started<args.timeout,'bundled multiplayer deadline reached');time.sleep(.1)
        (server_output/'server-stop').write_bytes(b'owned qualification complete\n');server_child.process.wait(timeout=35)
        require(server_child.process.returncode==0,'bundled host did not stop through original cleanup')
        server_report=json.loads((server_output/'server-driver.json').read_bytes());imports(server_report,server_package,inventories['server'])
        if owner:require(not server_report['fixture_store'] and server_report['production_store_type_verified'],'host did not use the production protected store')
        if args.rc_open:require(not server_report['fixture_store'] and server_report['production_rc_admission_verified'],
                               'RC host did not use actual open admission')
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
            if owner:require(not bundled['credential_fixture'] and bundled['production_private_reader_verified'],'client did not use the production private reader')
            if args.rc_open:require(not bundled['credential_fixture'] and bundled['invite_reads']==0,'RC client used an invite fixture')
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
            report['recovery']=validator(events,records,fault=report['fault'],mode=args.mode)
            selected=[e for e in events if e.get('match')==final['match'] or e['event']=='public_queue_entered' and e.get('ticket')==2]
        if args.custom_rematch:
            report['custom']=custom_evidence.validate(events,records,frozen=frozen,commands=server_report['custom_commands'])
        else:
            native_selections=validate_native_selections(records,final) if args.humans>=3 else None
            report['match']=validate(selected,records,mode=args.mode,ticket=2 if recovering else 1,expected_decks=native_selections)
            if native_selections is not None:report['native_selections']=native_selections
            require(final['full_loadout_seats']==report['match']['human_seats'],'bundled native clients lost complete human loadouts')
            if report['match']['bot_seats']:
                report['bot_fill']=validate_bot_fill(events,final,server_report['workers'][-1]['ai'],
                    recording_from_proof(replay_bytes,records[-1]['replay']),bot_seats=report['match']['bot_seats'])
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
        if owner:
            require(len(owner.commands)==args.humans,'actual packaged client enrollment command evidence missing')
            report['client_enrollment_commands']=owner.commands
    except BaseException as error:
        report['passed']=False
        if owner:report['error_type']=type(error).__name__
        else:report.update(error=repr(error),traceback=traceback.format_exc())
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
        public_paths=[path for child in children for path in child.output.iterdir()
                      if path.is_file() and path.suffix in ('.txt','.json','.jsonl','.log')]
        report['fixture_tokens_not_logged']=tokens_not_logged(private_tokens,public_paths)
        if owner:
            public=list((data/'logs').glob('events.jsonl*'))
            report['real_tokens_not_logged']=report['fixture_tokens_not_logged'] and not any(
                identity['token'].encode() in path.read_bytes() for identity in identities for path in public)
            report['real_tokens_not_logged'] &= not any(identity['token'] in json.dumps(report) for identity in identities)
            report.update(owner.dispose())
        remove_test_pki(pki_folder)
        checks=('adapters_unchanged','config_unchanged','package_files_unchanged','assets_unchanged','shared_channels_unchanged','source_files_unchanged','fixture_tokens_not_logged')
        report['passed'] &= all(report.get(k,False) for k in checks) and not report['forced_cleanup']
        if owner:report['passed'] &= report.get('disposable_invites_revoked_and_handoffs_removed',False) and report['real_tokens_not_logged']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','forced_cleanup','elapsed_seconds','error') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('packages','game','assets','output','helper-build-receipt','shared-settings'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--mode',type=int,choices=(1,2,5),default=1)
    parser.add_argument('--humans',type=int,choices=(1,2,3,4),default=2,help='one client qualifies an empty queue;three or four clients require public2v2')
    parser.add_argument('--custom-rematch',action='store_true',help='original Custom invite, two human matches, changed-deck rematch, sequential Leave and Quit')
    parser.add_argument('--timeout',type=int,default=420)
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--real-credentials',action='store_true',help='normal-owner protected issuance/enrollment, actual store/readers and server CMD check')
    parser.add_argument('--rc-open',action='store_true',help='production schema4 identities/open admission, no invite/CA fixtures')
    parser.add_argument('--preflight-only',action='store_true',help='with --real-credentials:read-only readiness/token check; never start a game/server or attempt protected files')
    recovery=parser.add_mutually_exclusive_group()
    recovery.add_argument('--recover-loading',action='store_true',help='disconnect first accepted loading match, then complete a new native match in the same processes')
    recovery.add_argument('--recover-running',action='store_true',help='disconnect after both clients play/build, then complete a new native match in the same processes')
    parser.add_argument('--disconnect-after-frame',type=int,choices=(200,600),default=600,help='owned running fault threshold; default600 covers original builds on both clients')
    raise SystemExit(run(parser.parse_args()))
