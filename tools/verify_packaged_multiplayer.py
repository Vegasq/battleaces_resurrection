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
import shutil
import socket
import subprocess
import time
import traceback

from client_patch.transport import client,launcher,rc_setup
from client_patch.transport import enrollment
from server import credentials as private
from server.assets import verify_assets
from server.worker_client import _WindowsJob
from tests.test_tls_transport import generate_test_pki
from tools.package_integrity import verify
from tools import packaged_network_drivers as drivers
from tools import packaged_custom_evidence as custom_evidence
from tools.packaged_network_evidence import validate,validate_loading_recovery,validate_running_recovery,validate_outage_recovery,validate_replays,validate_worker_shutdown,validate_native_selections,validate_bot_fill,recording_from_proof,validate_waiting_cancel
from tools.run_secure_match import read_native_log,frame_timing
from tools.stream_shaper import StreamShaper,ThreadedStreamShaper
from tools.verify_packaged_play import job_accounting
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.verify_native_storage import snapshot
from tools.replay_retention import api_path
from tools.packaged_owner_credentials import OwnerCredentials
from tools.verify_owner_credentials import restricting_sids_present
from tools import loading_delay_probe,graphical_soak_evidence,timing_probe,audit_stage_probe
from tools import python_socket_audit377,python_proactor_bytes412
from tools.soak_server import ProcessSampler
from tools.telemetry_preexisting_seed import seed as seed_sdk_queue, snapshot as snapshot_sdk_queue

ROOT=Path(__file__).resolve().parents[1]
require=startup.require


def sources():
    paths=[Path(__file__),ROOT/'tools/python_socket_audit377.py',ROOT/'tools/python_proactor_bytes412.py',ROOT/'tools/packaged_network_drivers.py',ROOT/'tools/worker_observation.py',ROOT/'tools/timing_probe.py',ROOT/'tools/audit_stage_probe.py',ROOT/'tools/packaged_network_evidence.py',
           ROOT/'tools/verify_packaged_play.py',ROOT/'tools/verify_native_storage.py',ROOT/'tools/packaged_custom_evidence.py',
           ROOT/'tools/packaged_owner_credentials.py',ROOT/'tools/verify_owner_credentials.py',
           ROOT/'tools/loading_delay_probe.py',ROOT/'tools/graphical_soak_evidence.py',ROOT/'tools/soak_server.py',ROOT/'tools/stream_shaper.py',ROOT/'tools/run_secure_match.py']
    paths.append(ROOT/'tests/test_tls_transport.py')
    return quit_probe.sources()|{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def rows(path):
    with path.open(encoding='utf-8-sig') as stream:return list(csv.DictReader(stream,delimiter='\t'))


def tokens_not_logged(tokens, paths):
    """Keep private keys separate from RC's public identity-only fixture records."""
    encoded=[token.encode('ascii') for token in tokens]
    return not any(token in Path(path).read_bytes() for path in paths for token in encoded)


def owned_diagnostic_path(path):
    """Only repository local or the dedicated per-user diagnostic area."""
    path=Path(path).resolve()
    root=Path(os.environ.get('LOCALAPPDATA',''))/'BattleAcesDiagnostics/local'
    return path.is_relative_to(ROOT/'local') or (root.is_absolute() and path.is_relative_to(root.resolve()))


def owned_game_path(path):
    return owned_diagnostic_path(path)


def remove_owned_pki(folder, output):
    """Remove only this fresh run's fixed temporary certificate directory."""
    folder,output=Path(folder),Path(output).resolve()
    require(owned_diagnostic_path(output) and folder.name=='ephemeral-pki' and
            folder.parent.resolve()==output and not folder.is_symlink() and
            not folder.is_junction(), 'owned temporary PKI directory required')
    target=folder.resolve()
    require(target.is_relative_to(output) and target!=output and target.is_dir(),
            'temporary PKI escaped its run directory')
    shutil.rmtree(target)


def finish_verification(output, pki_folder, report):
    """A cleanup failure must fail acceptance and still preserve the report."""
    output=Path(output).resolve()
    require(owned_diagnostic_path(output), 'owned verification output required')
    try:
        remove_owned_pki(pki_folder,output)
        report['temporary_pki_removed']=True
    except BaseException as error:
        report.update(passed=False,temporary_pki_removed=False,pki_cleanup_error=repr(error))
    finally:
        with (output/'verification.json').open('x',encoding='utf-8') as stream:
            json.dump(report,stream,indent=2);stream.write('\n')


def publish_empty_gate(path):
    """Expose a diagnostic gate only after its writer closes (native denies writes)."""
    path=Path(path)
    require(owned_game_path(path.resolve()) and not os.path.lexists(path),
            'fresh owned diagnostic gate required')
    pending=path.with_name(path.name+'.pending')
    with pending.open('xb'):pass
    pending.rename(path)


def read_live_snapshot(path):
    """Read the last complete bounded status record;never replace an open file."""
    path=Path(path).resolve()
    require(owned_diagnostic_path(path) and path.name=='server-live.jsonl',
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
        self.output=output;self.process=self.job=None;self.native=None;self.handle=None;self.job_launch=None
        output.mkdir(parents=True,exist_ok=False)
        if request.get('worker_socket_audit'):
            require(output.name=='server' and request.get('python_socket_audit'),
                    'worker audit requires owned server Python audit')
            worker_sources=[]
            for index in range(2):
                worker_output=output/f'worker-{index}';worker_output.mkdir()
                worker_sources.append(python_socket_audit377.source(
                    worker_output/'socket-audit.jsonl',positive_probe=True))
            request=dict(request,worker_audit_sources=worker_sources)
        script=output/'owned-driver.py'
        script.write_text((python_socket_audit377.source(output/'socket-audit.jsonl')
                           if request.get('python_socket_audit') else '')+
                          (python_proactor_bytes412.source(output/'byte-audit.jsonl')
                           if request.get('python_byte_audit') else '')+driver,encoding='utf-8')
        request_path=output/'request.json';request_path.write_text(json.dumps(request,indent=2)+'\n')
        self.inputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (script,request_path)}
        cwd=output/'foreign cwd';cwd.mkdir()
        for name in ('sitecustomize.py','server.py','client_patch.py'):(cwd/name).write_text('raise RuntimeError("foreign module must not run")\n')
        environment=os.environ.copy();environment.update(PATH=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'),PYTHONPATH=str(cwd))
        self.stdout=(output/'stdout.txt').open('wb');self.stderr=(output/'stderr.txt').open('wb')
        try:
            info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
            command=[str(package/'program/runtime/python.exe'),'-I','-B',str(script),str(request_path)]
            kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetTickCount64.restype=ctypes.c_ulonglong
            self.process=subprocess.Popen(command,cwd=cwd,env=environment,stdin=subprocess.PIPE,stdout=self.stdout,stderr=self.stderr,startupinfo=info,close_fds=True,creationflags=0x00000004)
            created=kernel.GetTickCount64()
            self.job=_WindowsJob(self.process.pid)
            assigned=kernel.GetTickCount64()
            ntdll=ctypes.WinDLL('ntdll',use_last_error=True)
            ntdll.NtResumeProcess.argtypes=[ctypes.c_void_p]
            ntdll.NtResumeProcess.restype=ctypes.c_long
            status=ntdll.NtResumeProcess(self.process._handle)
            require(status==0,'owned packaged driver resume failed')
            resumed=kernel.GetTickCount64()
            self.job_launch=dict(pid=self.process.pid,created_suspended=True,
                                 create_return_tick=created,job_assigned_tick=assigned,
                                 resumed_tick=resumed,job_attached_before_resume=True)
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


def validate_pending_quit_run(report, records, server_child, game, server_package, client_package, inventories, data, kernel):
    """One loading abort, held client original Quit, survivor idle menu Quit."""
    server_report=json.loads((server_child.output/'server-driver.json').read_bytes())
    imports(server_report,server_package,inventories['server'])
    require(server_report.get('status_writer_drained'), 'pending-Quit status writer not drained')
    require(sorted(server_report['authenticated'])==sorted(row['player'] for row in records),
            'pending-Quit clients unexpectedly reconnected')
    require(len(server_report['frozen_matches'])==1, 'pending-Quit replacement match appeared')
    fault=json.loads((server_child.output/'server-fault.json').read_bytes())
    frozen=server_report['frozen_matches'][0]
    require(fault==server_report['fault'] and fault['stage']==fault['room_state']=='loading' and
            fault['match']==frozen['match'] and fault['victim']==records[0]['player'] and
            fault['loaded']==[] and fault['next_frame']==0, 'pending-Quit loading fault differs')
    events=[]
    for path in sorted((data/'logs').glob('events.jsonl*'),reverse=True):
        events.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())
    require(sum(e['event']=='match_created' for e in events)==1 and
            sum(e['event']=='match_aborted' and e.get('match')==fault['match'] for e in events)==1 and
            not any(e['event'] in ('frame_queued','match_completed','simulation_error','protocol_error') for e in events),
            'pending-Quit match advanced/completed/failed unexpectedly')
    require(sum(e['event']=='public_queue_entered' for e in events)==2 and
            all(e.get('ticket')==1 for e in events if e['event']=='public_queue_entered'),
            'pending-Quit public retry bypassed its gate')
    report['fault']=fault
    report['worker_cleanup']=validate_worker_shutdown(server_report['workers'],events,fault=fault)
    clients=[]
    for index,row in enumerate(records):
        child=row['child'];native=child.native
        require(kernel.WaitForSingleObject(child.handle,0)==0, 'pending-Quit game still alive')
        code=ctypes.c_ulong()
        require(kernel.GetExitCodeProcess(child.handle,ctypes.byref(code)) and code.value==0,
                'pending-Quit native exit not zero')
        bundled=json.loads((child.output/'client-driver.json').read_bytes())
        imports(bundled,client_package,inventories['client'])
        log=read_native_log(game,native['pid'],since_tick=native['launch_tick'])
        settings=startup.native_settings_evidence(game,child.output,native['pid'],native['launch_tick'],row['profile'])
        require(settings['selected_deck']==row['pending_settings']['selected_deck'], 'pending-Quit lost saved deck')
        evidence=dict(pid=native['pid'],profile=row['profile'],settings=settings,driver_report=bundled)
        if index==0:
            require(hashlib.sha256((child.output/'loading-delay.js').read_bytes()).hexdigest()==report['loading_delay_script_sha256'],
                    'pending-Quit script changed during run')
            evidence['pending_quit']=loading_delay_probe.validate_pending_quit(
                loading_delay_probe.read_rows(child.output/'loading-delay.jsonl'),log,native['pid'],
                game_exit=code.value,launcher_exit=child.process.returncode,forced_cleanup=False)
            require(evidence['pending_quit']['passed'], 'pending load original Quit did not exit naturally')
        else:
            trace=quit_probe.current_trace_rows((row['folder']/'quit-trace.jsonl').read_bytes(),native['pid'],native['launch_tick'])
            require([r['event'] for r in trace]==['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return'],
                    'survivor original menu Quit trace differs')
            require('Public intent retired: ticket=1 reason=returned nativeIdle=1 disconnect=0' in log,
                    'survivor did not retire the aborted match')
            evidence['trace']=trace
        clients.append(evidence)
    require(quit_readiness(server_report['final_state']) and server_report['final_state']['active_workers']==0 and
            server_report['final_state']['sessions']==0, 'pending-Quit server retained native state or sessions')
    report.update(passed=True,server=server_report,clients=clients,
                  scope='Instrumented held pre-scene map iterator Quit; no hung engine/positive-counter recovery claim')


def run(args):
    for key,value in (('rtt_ms',None),('jitter_ms',0),('network_seed',17)):
        if not hasattr(args,key):setattr(args,key,value)
    if not hasattr(args,'delay_loading'):args.delay_loading=False
    if not hasattr(args,'prelaunch_observer'):args.prelaunch_observer=False
    if not hasattr(args,'python_socket_audit'):args.python_socket_audit=False
    if not hasattr(args,'python_byte_audit'):args.python_byte_audit=False
    if not hasattr(args,'worker_socket_audit'):args.worker_socket_audit=False
    if not hasattr(args,'pending_load_quit'):args.pending_load_quit=False
    if not hasattr(args,'recover_loading'):args.recover_loading=False
    if not hasattr(args,'recover_running'):args.recover_running=False
    if not hasattr(args,'outage_running'):args.outage_running=False
    if not hasattr(args,'disconnect_after_frame'):args.disconnect_after_frame=600
    if not hasattr(args,'humans'):args.humans=2
    if not hasattr(args,'cancel_waiting'):args.cancel_waiting=False
    if not hasattr(args,'custom_rematch'):args.custom_rematch=False
    if not hasattr(args,'custom_ready_expiry'):args.custom_ready_expiry=False
    if not hasattr(args,'custom_start_rejection'):args.custom_start_rejection=False
    if not hasattr(args,'custom_soak'):args.custom_soak=False
    if not hasattr(args,'timing_probe'):args.timing_probe=False
    if not hasattr(args,'audit_stages'):args.audit_stages=False
    if not hasattr(args,'require_queued_audit'):args.require_queued_audit=False
    require(not (args.require_queued_audit and args.audit_stages), 'queued audit cannot use synchronous stage observer')
    require(not args.audit_stages or args.timing_probe and not args.custom_soak,
            'audit stages require the bounded two-match timing probe')
    require(not args.timing_probe or args.custom_rematch and getattr(args,'rc_open',False),
            'timing probe requires bounded RC Custom control')
    require(not args.custom_soak or args.custom_rematch and getattr(args,'rc_open',False),'graphical soak requires RC Custom rematch')
    rounds=21 if args.custom_soak else 2
    if not hasattr(args,'real_credentials'):args.real_credentials=False
    if not hasattr(args,'rc_open'):args.rc_open=False
    require(not args.rc_open or not (args.real_credentials or args.recover_loading or args.recover_running or args.outage_running),
            'RC qualification uses production open admission without invite/fault fixtures')
    if not hasattr(args,'preflight_only'):args.preflight_only=False
    require(not args.preflight_only or args.real_credentials,'read-only owner preflight requires real-credential mode')
    require(sum((args.recover_loading,args.recover_running,args.outage_running))<=1,'select one recovery stage')
    recovering=args.recover_loading or args.recover_running or args.outage_running
    delayed=args.rtt_ms is not None
    require(not args.outage_running or args.rtt_ms==0 and args.jitter_ms==0 and args.mode==1 and
            args.humans==2 and not args.rc_open and not args.real_credentials,
            'outage requires isolated two-human public1 with the zero-delay owned relay')
    require(not args.cancel_waiting or args.rc_open and args.mode in (1,2,5) and args.humans==1 and
            not (recovering or delayed or args.custom_rematch or args.delay_loading),
            'waiting cancellation requires one RC public-mode client and no other fault')
    StreamShaper(1,rtt_ms=args.rtt_ms or 0,jitter_ms=args.jitter_ms,seed=args.network_seed)
    require(delayed or args.jitter_ms==0,'jitter requires an explicit RTT control')
    require(not delayed or args.outage_running or args.rc_open and args.mode==1 and args.humans==2 and not recovering and not args.custom_rematch,
            'stream-delay qualification currently requires RC public1v1/two humans without other faults')
    require(not args.delay_loading or args.recover_loading and args.mode==1 and args.humans==2,
            'native delay requires two-player public1 loading recovery')
    require(not args.prelaunch_observer or args.outage_running or args.rc_open and
            (args.mode in (1,5) and args.humans==2 or args.mode==2 and args.humans==4) and
            not (recovering or delayed or args.delay_loading or args.real_credentials or
                 args.custom_ready_expiry or args.custom_start_rejection or args.custom_soak or args.timing_probe),
            'prelaunch observer requires isolated RC public1/public5 two humans or public2 four humans without other faults')
    preexisting_sdk_queue=getattr(args,'preexisting_sdk_queue',False)
    require(not preexisting_sdk_queue or args.prelaunch_observer and args.rc_open and
            args.mode==1 and args.humans==2 and not args.custom_rematch and
            not (recovering or delayed or args.delay_loading or args.real_credentials),
            'preexisting SDK queue requires an owned observed RC public1 two-client run')
    # The two-client outage uses the same owned suspended-launch gate,with its
    # fault and relay controlled only after both native clients reach frame600.
    require(not args.python_socket_audit or args.rc_open and args.mode in (1,2,5) and
            (args.humans==2 or args.mode==2 and args.humans==4) and
            not (recovering or delayed or args.delay_loading or args.real_credentials or
                 args.custom_ready_expiry or args.custom_start_rejection or args.custom_soak or args.timing_probe),
            'Python socket audit requires isolated RC public/Custom two humans or public2 four humans without faults')
    require(not args.python_byte_audit or args.python_socket_audit and args.rc_open and
            args.mode==1 and args.humans==2 and not args.custom_rematch,
            'Proactor byte audit requires one isolated RC public1/two-human match with socket endpoints')
    require(not args.worker_socket_audit or args.python_socket_audit and
            (args.mode==1 and args.humans==2 or args.mode==2 and args.humans==4) and
            not args.custom_rematch,
            'worker socket audit requires one isolated RC public1 or four-human public2 match')
    require(not args.pending_load_quit or args.delay_loading and args.recover_loading and not args.real_credentials and
            not args.rc_open and not delayed and not args.custom_rematch and not args.cancel_waiting,
            'pending-load Quit requires the isolated two-player loading fault/delay fixture')
    require(args.disconnect_after_frame in (200,600),'unsupported running disconnect threshold')
    recover_stage='running' if args.recover_running or args.outage_running else 'loading' if args.recover_loading else None
    packages,game,assets,output=(p.resolve() for p in (args.packages,args.game,args.assets,args.output))
    require(os.name=='nt' and 120<=args.timeout<=(2400 if args.custom_soak else 600) and args.mode in (1,2,5),'bounded supported Windows match required')
    require(args.humans in (1,2,3,4) and (args.humans<=2 or args.mode==2),'three or four humans require public2v2')
    require(not args.real_credentials or args.humans in (2,4),'protected enrollment diagnostic supports two or four humans')
    require(not recovering or args.humans==2,'packaged recovery control requires two human clients')
    require(not args.custom_rematch or args.mode==1 and args.humans==2 and not recovering,'Custom rematch requires two humans and no public fault injection')
    require(not args.custom_ready_expiry or args.custom_rematch and args.rc_open and
            not (args.custom_soak or args.timing_probe or args.delay_loading or delayed),
            'Ready expiry requires the bounded RC Custom rematch without other diagnostics')
    require(not args.custom_start_rejection or args.custom_rematch and args.rc_open and
            not (args.custom_ready_expiry or args.custom_soak or args.timing_probe or args.delay_loading or delayed),
            'Start rejection requires the bounded RC Custom rematch without other faults')
    server_override=args.server_package.resolve() if args.server_package else None
    require(all(owned_diagnostic_path(p) for p in (packages,assets,server_override) if p is not None) and
            owned_diagnostic_path(output) and owned_game_path(game),'owned ignored paths required')
    server_package=server_override or packages/'battleaces-server-win64'
    client_package=packages/'battleaces-client-win64'
    inventories={kind:verify(path,kind) for kind,path in (('server',server_package),('client',client_package))}
    launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True)
    helper=(game/'BattleAcesOffline.dll').read_bytes()
    require(helper==(client_package/'program/client-helper/BattleAcesOffline.dll').read_bytes() and b'BA_RESURRECTION_NATIVE_QUIT_GATE_V1' in helper,'install the exact packaged gated-Quit diagnostic helper')
    require(not args.custom_rematch or b'BA_RESURRECTION_CUSTOM_LEAVE_GATE_V1' in helper,'Custom qualification requires the owned post-match Leave diagnostic')
    require(not args.custom_soak or b'BA_RESURRECTION_CUSTOM_SOAK_V1' in helper,'install the owned21-round diagnostic helper')
    require(not args.pending_load_quit or b'BA_RESURRECTION_PENDING_LOAD_QUIT_V1' in helper,
            'install the explicit pending-load Quit diagnostic helper')
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
    route_port=port;relay=None
    if delayed:
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));route_port=reservation.getsockname()[1]
        require(route_port!=port,'relay and host reservations collided')
    config_folder=output/'config';config_folder.mkdir();data=output/'host-data'
    host_config=json.loads((server_package/'config/host.example.json').read_bytes())
    host_config.update(listen_host='127.0.0.1',listen_port=port,assets_directory=str(assets),data_directory=str(data),
                       certificate_file=str(pki['cert']),private_key_file=str(pki['key']),credential_directory=str(output/'authored-private-store'),
                       diagnostic_audit=True,log_max_bytes=8*1024*1024,log_backups=8 if args.custom_soak else host_config['log_backups'])
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
                            server_host='127.0.0.1',server_port=route_port)
            config.write_text(json.dumps(settings,indent=2)+'\n')
            target=rc_setup.Resolver(config,game).read()
            identities[index]=dict(player_id=target.player_id)
            private_tokens.append(target.token)
            rc_clients.append((profile,config,settings))
    owner=OwnerCredentials(output) if args.real_credentials else None
    gate=secrets.token_hex(16);gate_path=game/'investigation/runtime'/('public-queue-'+gate+'.ready')
    retry_path=gate_path.with_name('public-queue-'+gate+'-retry.ready')
    require(not gate_path.exists() and not retry_path.exists(),'public start/retry gate already exists')
    configs=[host_path];children=[];records=[];preexisting=[];server_child=None;gate_created=False;quit_released=False;fault_requested=False;retry_released=False;leave_stage=0;quit_readiness_began=None;outage_restored=False
    shared=args.shared_settings.resolve()
    def channels():return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    report=dict(passed=False,scope=__doc__,pending_load_quit=args.pending_load_quit,cancel_waiting=args.cancel_waiting,delay_loading=args.delay_loading,prelaunch_observer=args.prelaunch_observer,preexisting_sdk_queue=preexisting_sdk_queue,python_socket_audit=args.python_socket_audit,python_byte_audit=args.python_byte_audit,worker_socket_audit=args.worker_socket_audit,rc_open=args.rc_open,mode=args.mode,humans=args.humans,real_credentials=args.real_credentials,custom_rematch=args.custom_rematch,custom_ready_expiry=args.custom_ready_expiry,custom_start_rejection=args.custom_start_rejection,custom_soak=args.custom_soak,recover_loading=args.recover_loading,outage_running=args.outage_running,recover_stage=recover_stage,helper_build=receipt,shared_before=channels(),source_sha256_at_start=sources(),forced_cleanup=False,
                packages=str(packages),server_package=str(server_package),
                assets_manifest_sha256=hashlib.sha256((assets/'asset-manifest.json').read_bytes()).hexdigest())
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetTickCount64.restype=ctypes.c_ulonglong
    soak_boundaries=[];soak_trend=[];soak_gates=[];soak_wait=None;next_sample=0
    sampler=ProcessSampler() if args.custom_soak else None
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
                     credential_directory=host_config['credential_directory'],pending_load_quit=args.pending_load_quit,cancel_waiting=args.cancel_waiting,recover_stage=recover_stage,disconnect_after_frame=args.disconnect_after_frame,custom_rematch=args.custom_rematch,custom_ready_expiry=args.custom_ready_expiry,custom_start_rejection=args.custom_start_rejection,custom_soak=args.custom_soak,timing_probe=args.timing_probe,audit_stages=args.audit_stages,real_credentials=args.real_credentials,rc_open=args.rc_open,python_socket_audit=args.python_socket_audit,python_byte_audit=args.python_byte_audit,worker_socket_audit=args.worker_socket_audit)
        if args.outage_running:request.update(recover_stage=None,network_outage=True)
        server_identities=[dict(player_id=value['player_id']) for value in identities] if owner else identities
        server_child=Child(server_package,server_output,drivers.SERVER,request,dict(identities=server_identities));children.append(server_child)
        while not (server_output/'server-ready.json').exists():
            require(server_child.process.poll() is None and time.monotonic()-started<60,'bundled host did not become ready');time.sleep(.05)
        ready=json.loads((server_output/'server-ready.json').read_bytes());require(ready['address']==['127.0.0.1',port],'bundled host bound the wrong listener')
        if delayed:
            relay=ThreadedStreamShaper(port,listen_port=route_port,rtt_ms=args.rtt_ms,jitter_ms=args.jitter_ms,seed=args.network_seed)
            require(relay.port==route_port,'relay bound an unexpected route')
            report['stream_delay']=dict(rtt_ms=args.rtt_ms,jitter_ms=args.jitter_ms,seed=args.network_seed,
                                       host_port=port,route_port=route_port,input_window=host_config['input_window'],
                                       scope='ordered loopback stream chunks; no packet loss or physical Internet claim')
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
                settings.update(server_host='127.0.0.1',server_port=route_port,server_name='localhost',ca_bundle=str(pki['ca']),credential_file=str(placeholder))
                config.write_text(json.dumps(settings,indent=2)+'\n')
            paths=(config,) if args.rc_open else (config,placeholder)
            configs.extend(paths)
            for path in paths:config_bytes[str(path)]=path.read_bytes()
            if preexisting_sdk_queue:
                queue_root,queue_before=seed_sdk_queue(game,profile)
                preexisting.append(dict(index=index,profile=profile,root=queue_root,before=queue_before))
                report['preexisting_queue_before']=[dict(index=item['index'],profile=item['profile'],
                    root=str(item['root']),files=item['before']) for item in preexisting]
            request=dict(package=str(client_package),game=str(game),output=str(client_output),config=str(config),profile=profile,
                port=route_port,invite_placeholder=str(placeholder),pending_load_quit=args.pending_load_quit,cancel_waiting=args.cancel_waiting,mode=args.mode,index=index,gate=gate,visible=args.visible,recover_stage=recover_stage,custom_rematch=args.custom_rematch,custom_start_rejection=args.custom_start_rejection,custom_soak=args.custom_soak,real_credentials=args.real_credentials,rc_open=args.rc_open,prelaunch_observer=args.prelaunch_observer,python_socket_audit=args.python_socket_audit,python_byte_audit=args.python_byte_audit)
            if args.outage_running:request['network_outage']=True
            child=Child(client_package,client_output,drivers.CLIENT,request,dict(player_id=identity['player_id']) if owner or args.rc_open else identity);children.append(child)
            records.append(dict(child=child,folder=folder,profile=profile,name=settings['display_name'],player=identity['player_id'],deck_edited=index%2==1))
        prelaunch_released=False
        while True:
            require(server_child.process.poll() is None,'bundled host stopped during client gameplay')
            for index,row in enumerate(records):
                child=row['child'];process_path=child.output/'game-process.json'
                if child.native is None and process_path.exists():
                    child.native=json.loads(process_path.read_bytes());child.handle=kernel.OpenProcess(0x100000|0x1000,False,child.native['pid'])
                    require(child.handle,'cannot observe owned native game')
                    if args.prelaunch_observer:
                        require(child.native['suspended_for_observer'] is True,'game was not created suspended')
                        print(json.dumps(dict(stage='prelaunch_attach_required',client=index,
                                              pid=child.native['pid'],output=str(child.output))),flush=True)
                    if args.delay_loading and index==0:
                        source,config=loading_delay_probe.build_source(game,child.output,child.native['pid'],pending_quit=args.pending_load_quit)
                        with (child.output/'loading-delay.js').open('xb') as stream:stream.write(source.encode('utf-8'))
                        report['loading_delay_config']=config
                        report['loading_delay_script_sha256']=hashlib.sha256(source.encode()).hexdigest()
                        print(json.dumps(dict(stage='loading_delay_attach_required',pid=child.native['pid'],
                                              script=str(child.output/'loading-delay.js'))),flush=True)
                if child.native:
                    row['log']=read_native_log(game,child.native['pid'],since_tick=child.native['launch_tick'])
                    failure=native_lifecycle_failure(row['log'])
                    if failure:report['native_failure']=dict(client=index,pid=child.native['pid'],marker=failure,observed_tick=kernel.GetTickCount64())
                    require(failure is None,'native bundled multiplayer lifecycle failed')
                    for failure in re.findall(r'Offline loop stopped in [^\n]*',row['log']):
                        require(recovering and fault_requested and (index==0 or args.outage_running) and re.fullmatch(
                            r'Offline loop stopped in (?:LAN update|LAN front update|dedicated session update): '
                            r'(?:match server disconnected before a result|Secure session is closed)',failure.rstrip('\r')),
                            'unexpected native bundled multiplayer stop')
                    if (row['folder']/'quit-trace.jsonl').exists():
                        trace=quit_probe.current_trace_rows((row['folder']/'quit-trace.jsonl').read_bytes(),child.native['pid'],child.native['launch_tick'])
                        confirm=[r['tick'] for r in trace if r['event']=='OnConfirm.dispatch']
                        if confirm:require(len(confirm)==1 and (child.process.poll() is not None or kernel.GetTickCount64()-confirm[0]<60000),'native Quit exceeded60s')
                require(child.process.poll() is None or (quit_released or args.pending_load_quit and fault_requested) and
                        child.process.returncode==0,'bundled client exited before accepted match/Quit')
            if args.prelaunch_observer and not prelaunch_released and all(row['child'].native for row in records):
                gates=[row['child'].output/'observer-ready' for row in records]
                if all(path.is_file() for path in gates):
                    require(all(path.read_bytes()==b'FRIDA_READY\n' for path in gates),
                            'prelaunch observer gate contents differ')
                    ntdll=ctypes.WinDLL('ntdll',use_last_error=True)
                    ntdll.NtResumeProcess.argtypes=[ctypes.c_void_p]
                    ntdll.NtResumeProcess.restype=ctypes.c_long
                    resume=[]
                    for row in records:
                        pid=row['child'].native['pid']
                        handle=kernel.OpenProcess(0x0800,False,pid)
                        require(handle,'cannot resume owned native game')
                        try:status=ntdll.NtResumeProcess(handle)
                        finally:kernel.CloseHandle(handle)
                        require(status==0,'owned native game resume failed')
                        resume.append(dict(pid=pid,tick=kernel.GetTickCount64()))
                    report['prelaunch_resume']=resume
                    prelaunch_released=True
                    print(json.dumps(dict(stage='prelaunch_resumed',pids=[item['pid'] for item in resume])),flush=True)
            delay_ready=not args.delay_loading
            if args.delay_loading and records[0]['child'].native:
                delay_journal=records[0]['child'].output/'loading-delay.jsonl'
                if delay_journal.exists():
                    delay_ready=loading_delay_probe.armed(loading_delay_probe.read_rows(delay_journal),records[0]['child'].native['pid'])
            if not gate_created and delay_ready and all('PUBLIC QUEUE SMOKE waiting for shared gate: key='+gate in row.get('log','') for row in records):
                require(not any('Public search intent:' in row['log'] for row in records),'public search bypassed shared menu gate')
                publish_empty_gate(gate_path)
                gate_created=True
            if args.cancel_waiting and not retry_released and all('PUBLIC QUEUE SMOKE waiting for retry gate: key='+gate in row.get('log','') for row in records):
                live=read_live_snapshot(server_output/'server-live.jsonl')
                if quit_readiness(live) and live.get('active_workers')==0 and live.get('sessions')==1:
                    for row in records:
                        require(row['log'].count('Public search intent:')==1 and
                                'Public intent retired: ticket=1 reason=cancelled nativeIdle=1 disconnect=0' in row['log'] and
                                'Client world acquired:' not in row['log'], 'cancelled search did not retire before replacement')
                    report['cancel_before_retry']=live
                    publish_empty_gate(retry_path)
                    retry_released=True
            if recovering and not fault_requested and all('Public native match joined: ticket=1 ' in row.get('log','') for row in records):
                received=[[int(value) for value in re.findall(r'LAN received frame (\d+),',row['log'])] for row in records]
                reached=args.recover_loading or all(values and max(values)>=args.disconnect_after_frame for values in received)
                if reached:
                    require(all(('Offline world ready;' in row['log'])==(args.recover_running or args.outage_running) for row in records),
                            'disconnect missed the requested native map-load/running window')
                    report['fault_native_frames']=[max(values,default=-1) for values in received]
                    if args.pending_load_quit:
                        for row in records:
                            child=row['child']
                            row['pending_settings']=startup.native_settings_evidence(game,child.output,
                                child.native['pid'],child.native['launch_tick'],row['profile'])
                            shutil.copyfile(child.output/'isolated-localuser.toml',child.output/'settings-before-quit.toml')
                    if args.outage_running:
                        require(relay is not None,'owned outage relay missing')
                        report['outage']=dict(started_seconds=time.monotonic()-started,
                            native_frames=list(report['fault_native_frames']),
                            before=read_live_snapshot(server_output/'server-live.jsonl'),
                            control=relay.outage())
                        with socket.socket() as probe:
                            report['outage']['connect_ex']=probe.connect_ex(('127.0.0.1',route_port))
                        require(report['outage']['control']['disconnected']==2 and
                                report['outage']['connect_ex']!=0,'owned outage did not drop both streams and refuse TCP')
                    else:
                        command=server_output/'server-disconnect.tmp';command.write_text(json.dumps(dict(player=identities[0]['player_id']))+'\n');command.rename(server_output/'server-disconnect.json')
                    fault_requested=True
            if args.outage_running and fault_requested and not outage_restored and time.monotonic()-started>=report['outage']['started_seconds']+2:
                require(relay.restore()==route_port,'owned outage restored a different port')
                report['outage']['restored_seconds']=time.monotonic()-started
                outage_restored=True
            if recovering and not args.pending_load_quit and fault_requested and not retry_released and all('PUBLIC QUEUE SMOKE waiting for retry gate: key='+gate in row.get('log','') for row in records):
                live=read_live_snapshot(server_output/'server-live.jsonl')
                if all(live.get(key)==0 for key in ('rooms','retired','entries','offers','cleanup')):
                    if args.outage_running:
                        require(outage_restored and live['sessions']==0,'old outage sessions remained before retry')
                        report['outage']['before_retry']=live
                    else:
                        require((server_output/'server-fault.json').exists() and live['sessions']==1,'old room/session cleanup was not complete before retry')
                        report['fault']=json.loads((server_output/'server-fault.json').read_bytes())
                    for row in records:
                        require(row['log'].count('Public search intent:')==1,'replacement Play bypassed the retry gate')
                        row['retry_offset']=len(row['log'])
                    publish_empty_gate(retry_path)
                    retry_released=True
            if args.pending_load_quit and fault_requested:
                if not quit_released and 'Public intent retired: ticket=1 reason=returned nativeIdle=1 disconnect=0' in records[1].get('log',''):
                    live=read_live_snapshot(server_output/'server-live.jsonl')
                    if quit_readiness(live) and live.get('active_workers')==0:
                        report['pending_quit_before_peer_exit']=live
                        publish_empty_gate(records[1]['folder']/'native-quit.ready')
                        quit_released=True
                requested=re.findall(r'^\[(\d+)\] PENDING LOAD QUIT SMOKE ',records[0].get('log',''),re.M)
                if requested:
                    require(len(requested)==1 and (records[0]['child'].process.poll() is not None or
                            kernel.GetTickCount64()-int(requested[0])<60000),'pending native Quit exceeded60s')
            if args.custom_soak and all(row['child'].native for row in records) and not quit_released:
                def resource_sample():
                    require(server_child.process.poll() is None,'soak host ended before sampling')
                    measured={'server':sampler.sample(server_child.process.pid)}
                    for index,row in enumerate(records):
                        child=row['child']
                        require(child.process.poll() is None and kernel.WaitForSingleObject(child.handle,0)==258,
                                'owned soak client ended before sampling')
                        measured['launcher'+str(index)]=sampler.sample(child.process.pid)
                        measured['game'+str(index)]=sampler.sample(child.native['pid'])
                        require(child.process.poll() is None and kernel.WaitForSingleObject(child.handle,0)==258,
                                'owned soak client ended during sampling')
                    require(server_child.process.poll() is None,'soak host ended during sampling')
                    return dict(seconds=time.monotonic()-started,processes=measured)
                if time.monotonic()>=next_sample:
                    sample=resource_sample();soak_trend.append(sample)
                    with (output/'resource-trend.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(sample)+'\n')
                    next_sample=time.monotonic()+10
                next_round=len(soak_boundaries)+1
                if next_round<=rounds and all(graphical_soak_evidence.idle_round(row['log'])==next_round for row in records):
                    live=read_live_snapshot(server_output/'server-live.jsonl');lobbies=live.get('lobbies',[])
                    settled=all(live.get(key)==0 for key in ('rooms','retired','entries','offers','cleanup'))
                    settled=settled and live['active_workers']==0 and live['sessions']==2 and len(lobbies)==1 and lobbies[0]['phase']==1 and lobbies[0]['epoch']==next_round
                    if settled:
                        if soak_wait is None:soak_wait=time.monotonic()
                        if time.monotonic()-soak_wait>=2:
                            sample=resource_sample()|dict(round=next_round,lobby=lobbies[0]['id'],snapshot=live)
                            soak_boundaries.append(sample)
                            with (output/'idle-boundaries.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(sample)+'\n')
                            print(json.dumps(dict(stage='graphical_soak_idle',round=next_round,seconds=sample['seconds'])),flush=True)
                            for row in records:
                                path=row['folder']/f'custom-soak-{next_round}.ready';publish_empty_gate(path);soak_gates.append(path)
                            soak_wait=None
                    else:soak_wait=None
            if args.custom_rematch:
                ready=(all(('COMMUNITY MATCH SMOKE passed: '+('21' if args.custom_soak else 'two')+' native Start/result/Continue cycles;') in row.get('log','') for row in records)
                       if leave_stage==0 else 'COMMUNITY MATCH SMOKE post-match leave passed: role=guest' in records[1].get('log',''))
                if leave_stage<2 and ready:
                    live=read_live_snapshot(server_output/'server-live.jsonl');lobbies=live.get('lobbies',[])
                    expected=sorted(row['player'] for row in records) if leave_stage==0 else [records[0]['player']]
                    if all(live.get(key)==0 for key in ('rooms','retired','entries','offers','cleanup')) and len(lobbies)==1 and lobbies[0]['members']==expected:
                        from server.community_protocol import OPEN
                        require(lobbies[0]['phase']==OPEN and lobbies[0]['epoch']==custom_evidence.expected_epochs(rounds,args.custom_ready_expiry)[-1],
                                'Custom lobby failed to reopen at its final expected epoch')
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
        if args.pending_load_quit:
            validate_pending_quit_run(report,records,server_child,game,server_package,client_package,inventories,data,kernel)
        else:
            server_report=json.loads((server_output/'server-driver.json').read_bytes());imports(server_report,server_package,inventories['server'])
            require(server_report.get('status_writer_drained'),'diagnostic status writer did not drain')
            if owner:require(not server_report['fixture_store'] and server_report['production_store_type_verified'],'host did not use the production protected store')
            if args.rc_open:require(not server_report['fixture_store'] and server_report['production_rc_admission_verified'],
                                   'RC host did not use actual open admission')
            expected_authenticated=[row['player'] for row in records]+(
                [row['player'] for row in records] if args.outage_running else
                [records[0]['player']] if recovering else [])
            require(sorted(server_report['authenticated'])==sorted(expected_authenticated),'bundled TLS identity ownership differs')
            frozen=server_report['frozen_matches'];require(len(frozen)==(rounds if args.custom_rematch else 2 if recovering else 1),'bundled host match count differs')
            final=frozen[-1]
            events=[]
            for path in sorted((data/'logs').glob('events.jsonl*'),reverse=True):events.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())
            if args.outage_running:
                initial=frozen[0]
                started_events=[e for e in events if e['event']=='worker_started' and e.get('match')==initial['match']]
                frames=[e for e in events if e['event']=='frame_queued' and e.get('match')==initial['match']]
                require(len(started_events)==1 and len(frames)>args.disconnect_after_frame,'outage first match evidence missing')
                report['fault']=dict(stage='running',match=initial['match'],worker_pid=started_events[0]['worker_pid'])
                report['outage']['authoritative_frames']=len(frames)
            report['worker_cleanup']=validate_worker_shutdown(server_report['workers'],events,fault=report.get('fault'))
            final_frames=sum(e['event']=='frame_queued' and e.get('match')==final['match'] for e in events)
            report['frame_timing']=frame_timing(events,final['match'])
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
                    if args.recover_running or args.outage_running:
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
                    row['replays']=custom_evidence.replays(replay_bytes,frozen,counts,expected_rounds=rounds);row['replay_set']=dict(completed_matches=row['replays'])
                    row['replay']=row['replays'][final['match']]
                else:
                    row['replay_set']=validate_replays(replay_bytes,frozen=frozen,frames=final_frames,
                        loading_abort=args.recover_loading,running_abort_frames=len(row['initial_receipts']) if args.recover_running or args.outage_running else None)
                    row['replay']=row['replay_set']['completed']
                row['settings']=startup.native_settings_evidence(game,child.output,row['pid'],child.native['launch_tick'],row['profile'])
                row['trace']=trace;row['driver_report']=bundled
            report.update(server=server_report,clients=[{k:row[k] for k in ('pid','name','player','profile','replay','replay_set','settings','trace','driver_report')} for row in records])
            if args.require_queued_audit:
                queued=server_report.get('queued_audits',[])
                require(len(queued)==1, 'packaged host did not use queued audit')
                q=queued[0]
                require(q['asynchronous'] and q['closed'] and not q['thread_alive'] and not q['failed'] and
                        q['accepted']==q['written']==len(events) and q['accepted']>0 and
                        all(q[key]==0 for key in ('rejected','abandoned','pending_records','pending_bytes')) and
                        q['notification_error'] is None and q['peak_records']<=q['record_limit'] and q['peak_bytes']<=q['byte_limit'],
                        'queued audit did not preserve and drain every record within bounds')
                report['queued_audit_verified']=True
            selected=events
            if recovering:
                if args.outage_running:
                    report['recovery']=validate_outage_recovery(events,records,report['outage'],mode=args.mode)
                else:
                    validator=validate_running_recovery if args.recover_running else validate_loading_recovery
                    report['recovery']=validator(events,records,fault=report['fault'],mode=args.mode)
                if args.delay_loading:
                    delay_output=records[0]['child'].output
                    require(hashlib.sha256((delay_output/'loading-delay.js').read_bytes()).hexdigest()==report['loading_delay_script_sha256'],
                            'delay script changed during run')
                    report['loading_delay']=loading_delay_probe.validate(
                        loading_delay_probe.read_rows(delay_output/'loading-delay.jsonl'),
                        records[0]['full_log'],records[0]['pid'])
                selected=[e for e in events if e.get('match')==final['match'] or e['event']=='public_queue_entered' and e.get('ticket')==2]
            if args.cancel_waiting:
                require(retry_released,'cancel retry gate never released')
                report['waiting_cancel']=validate_waiting_cancel(events,records,server_report['queue_selections'],
                    frozen=final,before_retry=report['cancel_before_retry'],mode=args.mode)
                selected=[e for e in events if e.get('match')==final['match'] or e['event']=='public_queue_entered' and e.get('ticket')==2]
            if args.custom_rematch:
                require(not args.custom_ready_expiry or server_report.get('ready_expiry'),'Ready expiry injection missing')
                require(not args.custom_start_rejection or server_report.get('start_rejection'),'Start rejection injection missing')
                report['custom']=custom_evidence.validate(events,records,frozen=frozen,commands=server_report['custom_commands'],expected_rounds=rounds,
                    ready_expiry=server_report.get('ready_expiry') if args.custom_ready_expiry else None,
                    start_rejection=server_report.get('start_rejection') if args.custom_start_rejection else None)
                if args.timing_probe:
                    report['round_timing']={r['match']:frame_timing(events,r['match']) for r in frozen}
                    require(server_report.get('timing_probe_drained'),'timing observer did not drain')
                    timing_path=server_output/'server-timing.json'
                    report['timing_probe']=timing_probe.review_timing(json.loads(timing_path.read_bytes()),events)
                    report['timing_probe']['sha256']=hashlib.sha256(timing_path.read_bytes()).hexdigest()
                    require(report['timing_probe']['frame_audits']==1220*rounds,'timing probe did not cover every complete match')
                    if args.audit_stages:
                        require(server_report.get('audit_stages_detached'),'audit stages not detached')
                        raw=json.loads(timing_path.read_bytes())
                        raw['rows']=[row for row in raw['rows'] if row['kind'].startswith('audit')]
                        report['audit_stages']=audit_stage_probe.review_stages(raw)
                        gc_path=server_output/'gc-timing.json';gc_raw=json.loads(gc_path.read_bytes())
                        require(gc_raw['schema']==1 and not gc_raw['errors'] and not gc_raw['dropped'] and
                                gc_raw['active'] is None and gc_raw['before']==gc_raw['after'] and gc_raw['callbacks_preserved'],
                                'GC observation incomplete or runtime changed')
                        report['gc_probe']=dict(sha256=hashlib.sha256(gc_path.read_bytes()).hexdigest(),
                                               collections=len(gc_raw['rows']),runtime_unchanged=True)
                if args.custom_soak:
                    report['graphical_soak']=graphical_soak_evidence.assess(soak_boundaries,soak_trend)
                    report['round_timing']={r['match']:frame_timing(events,r['match']) for r in frozen}
                    if args.timing_probe:
                        report['graphical_cadence']=graphical_soak_evidence.assess_cadence(events,[r['match'] for r in frozen])
                    require(report['graphical_soak']['passed'],'graphical soak resource growth exceeded predeclared limits')
                    if args.timing_probe:require(report['graphical_cadence']['passed'],'graphical soak cadence exceeded predeclared limits')
            else:
                native_selections=validate_native_selections(records,final) if args.humans>=3 else None
                report['match']=validate(selected,records,mode=args.mode,ticket=2 if recovering or args.cancel_waiting else 1,expected_decks=native_selections)
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
                report['jobs'].append(dict(pid=child.process.pid,launch=child.job_launch,**accounting))
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
        if relay:
            try:
                report['stream_delay']['relay']=relay.close()
                stats=report['stream_delay']['relay']
                require(stats['accepted']==args.humans*(2 if args.outage_running else 1) and stats['rejected']==stats['failures']==stats['active_connections']==0 and
                        stats['listener_closed'] and stats['thread_stopped'] and stats['forwarded_bytes']>0 and stats['delay_samples']>0,
                        'owned relay routing/drain evidence differs')
            except BaseException as error:report.update(passed=False,relay_error=repr(error))
        for path in soak_gates:
            require(owned_game_path(path.resolve()) and not path.is_symlink(),'owned soak gate changed path');path.unlink()
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
        if preexisting_sdk_queue:
            try:
                report['preexisting_queue_after']=[dict(index=item['index'],profile=item['profile'],
                    root=str(item['root']),files=snapshot_sdk_queue(item['root'])) for item in preexisting]
                report['preexisting_queue_unchanged']=(len(preexisting)==args.humans and
                    report['preexisting_queue_after']==report['preexisting_queue_before'])
            except (OSError,ValueError) as error:
                report.update(preexisting_queue_unchanged=False,preexisting_queue_error=repr(error))
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
        checks=('adapters_unchanged','config_unchanged','package_files_unchanged','assets_unchanged','shared_channels_unchanged','source_files_unchanged','fixture_tokens_not_logged')
        report['passed'] &= all(report.get(k,False) for k in checks) and not report['forced_cleanup']
        if preexisting_sdk_queue:report['passed'] &= report.get('preexisting_queue_unchanged',False)
        if owner:report['passed'] &= report.get('disposable_invites_revoked_and_handoffs_removed',False) and report['real_tokens_not_logged']
        finish_verification(output,pki_folder,report)
    print(json.dumps({k:report[k] for k in ('passed','forced_cleanup','elapsed_seconds','error') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('packages','game','assets','output','helper-build-receipt','shared-settings'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--server-package',type=Path,
                        help='owned actual native server install; client still comes from --packages')
    parser.add_argument('--mode',type=int,choices=(1,2,5),default=1)
    parser.add_argument('--cancel-waiting',action='store_true',help='one RC public1v1/2v2/2vAI client: original waiting Cancel, gated retry and normal Quit')
    parser.add_argument('--humans',type=int,choices=(1,2,3,4),default=2,help='one client qualifies an empty queue;three or four clients require public2v2')
    parser.add_argument('--custom-soak',action='store_true',help='21 Custom matches in the same clients with gated idle resource measurements')
    parser.add_argument('--timing-probe',action='store_true',help='RC Custom audit/status/loop timing; with --custom-soak also enforce21-match cadence bounds')
    parser.add_argument('--audit-stages',action='store_true',help='with two-match timing probe: original audit subcalls and automatic GC windows')
    parser.add_argument('--require-queued-audit',action='store_true',help='require bounded production writer and complete error-free journal drain')
    parser.add_argument('--custom-rematch',action='store_true',help='original Custom invite, two human matches, changed-deck rematch, sequential Leave and Quit')
    parser.add_argument('--custom-ready-expiry',action='store_true',help='with RC Custom rematch: hold first Ready past real expiry until native host retries')
    parser.add_argument('--custom-start-rejection',action='store_true',help='with RC Custom rematch: reject first host Start, then original retry and normal Quit')
    parser.add_argument('--delay-loading',action='store_true',help='owned Frida130s first-iterator delay; waits for explicit attach before opening the match gate')
    parser.add_argument('--prelaunch-observer',action='store_true',help='diagnostic only: create owned native clients suspended; wait for external observer-ready files before resume')
    parser.add_argument('--preexisting-sdk-queue',action='store_true',help='with RC public1 prelaunch observer:seed two authored SDK files per fresh owned profile before clients launch')
    parser.add_argument('--python-socket-audit',action='store_true',help='diagnostic only: record packaged Python driver socket endpoints from script entry')
    parser.add_argument('--python-byte-audit',action='store_true',help='diagnostic only: count packaged Python Proactor socket bytes without reading payloads')
    parser.add_argument('--worker-socket-audit',action='store_true',help='diagnostic only: record one packaged simulation worker socket endpoints with localhost audit control')
    parser.add_argument('--pending-load-quit',action='store_true',help='with loading fault/delay: hold until original Quit; never release the load on a timer')
    parser.add_argument('--timeout',type=int,default=420)
    parser.add_argument('--rtt-ms',type=float,default=None,help='enable ordered stream delay; explicit0 is the relay control')
    parser.add_argument('--jitter-ms',type=float,default=0)
    parser.add_argument('--network-seed',type=int,default=17)
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--real-credentials',action='store_true',help='normal-owner protected issuance/enrollment, actual store/readers and server CMD check')
    parser.add_argument('--rc-open',action='store_true',help='production schema4 identities/open admission, no invite/CA fixtures')
    parser.add_argument('--preflight-only',action='store_true',help='with --real-credentials:read-only readiness/token check; never start a game/server or attempt protected files')
    recovery=parser.add_mutually_exclusive_group()
    recovery.add_argument('--recover-loading',action='store_true',help='disconnect first accepted loading match, then complete a new native match in the same processes')
    recovery.add_argument('--recover-running',action='store_true',help='disconnect after both clients play/build, then complete a new native match in the same processes')
    recovery.add_argument('--outage-running',action='store_true',help='drop both owned relay streams after frame600,refuse connections,restore same port and observe native recovery')
    parser.add_argument('--disconnect-after-frame',type=int,choices=(200,600),default=600,help='owned running fault threshold; default600 covers original builds on both clients')
    raise SystemExit(run(parser.parse_args()))
