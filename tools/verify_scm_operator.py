"""Prepare/check/probe a disposable real-SCM operator check (186).

Registration and credentials belong to Run-SCMCheck.ps1. No passwords are
accepted here. No existing deployment/service is selected or modified.
"""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import ctypes as c
from ctypes import wintypes as w
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]


def require(value,message):
    if not value:raise AssertionError(message)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    temporary=path.with_name(path.name+'.staging')
    with temporary.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def external(path):
    spec=importlib.util.spec_from_file_location('scm_'+Path(path).stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def scm_access():
    api=c.WinDLL('advapi32',use_last_error=True)
    api.OpenSCManagerW.argtypes=[w.LPCWSTR,w.LPCWSTR,w.DWORD];api.OpenSCManagerW.restype=w.HANDLE
    api.CloseServiceHandle.argtypes=[w.HANDLE];api.CloseServiceHandle.restype=w.BOOL
    handle=api.OpenSCManagerW(None,None,3)  # Connect + create permission query only.
    result=dict(create_service_access=bool(handle),win32_error=0 if handle else c.get_last_error())
    if handle:api.CloseServiceHandle(handle)
    return result


def verify_plan(plan_path):
    from tools.package_integrity import verify
    from server.configuration import load_config
    from server.windows_service import registration
    plan_path=Path(plan_path).resolve();plan=json.loads(plan_path.read_bytes())
    out=Path(plan['output']).resolve();package=Path(plan['package']).resolve()
    require(out==plan_path.parent and out.is_relative_to(ROOT/'local'),'plan escaped diagnostic output')
    import re
    require(re.fullmatch(r'BattleAcesDiag186_[a-f0-9]{12}',plan['service_name']),
            'unexpected diagnostic service name')
    require(Path(plan['config']).resolve()==out/'config/host.json','unexpected diagnostic config')
    require(Path(plan['runtime']).resolve()==package/'program/runtime/python.exe','runtime differs')
    sources={str(ROOT/'tools'/name) for name in ('verify_scm_operator.py','Run-SCMCheck.ps1',
                                                'verify_server_recovery.py','server_console_match.py')}
    require(set(plan['source_sha256'])==sources,'operator source pins incomplete')
    require(plan['probe_script']==str(ROOT/'tools/verify_scm_operator.py') and
            plan['wrapper_script']==str(ROOT/'tools/Run-SCMCheck.ps1'),'operator script path changed')
    for path,sha in plan['source_sha256'].items():require(digest(path)==sha,'operator source changed')
    require(digest(package/'package-manifest.json')==plan['package_manifest_sha256'],'package manifest changed')
    verify(package,'server')
    config=load_config(Path(plan['config']))
    require(config.listen_host=='127.0.0.1' and config.dashboard_port==0 and config.data_directory==out/'data',
            'diagnostic listener/data differs')
    require(digest(config.source)==plan['config_sha256'],'diagnostic config changed')
    require(registration(package,config.source,plan['service_name'])['binary_path']==plan['binary_path'],
            'registration command changed')
    return plan,config


def prepare(package,assets,out):
    from tools.package_integrity import verify
    from server import rc_host,credentials as private,state_backup,admission
    from server.profiles import ProfileStore
    from server.configuration import load_config
    from server.windows_service import registration
    package,assets,out=(Path(p).resolve() for p in (package,assets,out))
    require(os.name=='nt' and all(p.is_relative_to(ROOT/'local') for p in (package,assets,out)),
            'owned local Windows paths required')
    require(not any(out.is_relative_to(p) or p.is_relative_to(out) for p in (package,assets)),
            'separate fresh output required')
    require(Path(sys.executable).resolve()==package/'program/runtime/python.exe','use bundled Python to prepare')
    verify(package,'server')
    require(not external(ROOT/'tools/verify_owner_credentials.py').restricting_sids_present(),
            'unrestricted desktop owner required before private operations')
    out.mkdir(parents=True,exist_ok=False)
    path=out/'config/host.json';config=rc_host.initialize(path,assets)
    with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    settings=json.loads(path.read_bytes());settings.update(listen_host='127.0.0.1',listen_port=port,
        data_directory=str(out/'data'),dashboard_port=0,diagnostic_audit=True)
    save(path,settings);config=load_config(path)
    template,identity=state_backup.load_inputs(config);catalog=state_backup.load_cosmetics(config,identity)
    require(catalog is not None,'real cosmetic catalog required')
    profiles=ProfileStore(config.data_directory/'profiles',template,catalog=catalog)
    private._ensure_private_directory(out/'peers')
    tokens=['ba1_'+secrets.token_urlsafe(32) for _ in range(2)]
    for slot,token in enumerate(tokens):
        profiles.save(admission.rc_player_id(token),template.default_decks[slot],cosmetics=catalog.normalize_local())
    private._write_file(out/'peers/tokens.json',json.dumps(tokens).encode())
    script=ROOT/'tools/Run-SCMCheck.ps1'
    shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    account=subprocess.check_output([str(shell),'-NoProfile','-NonInteractive','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().Name'],timeout=15,creationflags=subprocess.CREATE_NO_WINDOW).decode().strip()
    name='BattleAcesDiag186_'+secrets.token_hex(6)
    registration_data=registration(package,path,name)
    sources=[Path(__file__).resolve(),script,ROOT/'tools/verify_server_recovery.py',ROOT/'tools/server_console_match.py']
    plan=dict(schema=1,output=str(out),package=str(package),runtime=str(package/'program/runtime/python.exe'),
        config=str(path),service_name=name,binary_path=registration_data['binary_path'],account=account,
        owner_sid=private._windows().sid,probe_script=str(Path(__file__).resolve()),wrapper_script=str(script),
        source_sha256={str(p):digest(p) for p in sources},config_sha256=digest(path),
        package_manifest_sha256=digest(package/'package-manifest.json'),
        profile_sha256={file.name:digest(file) for file in profiles.path.glob('*.json')})
    save(out/'plan.json',plan)
    verify_plan(out/'plan.json')
    save(out/'preflight.json',dict(prepared=True,scm=scm_access(),registered=False,host_started=False,
        private_files_checked=True,package_verified=True,service_name=name))
    print(json.dumps(dict(prepared=True,plan=str(out/'plan.json'),service_name=name,scm=scm_access())))
    return 0


def wait_file(path,timeout,process=None):
    deadline=time.monotonic()+timeout
    while not path.exists():
        require(not (path.parent.parent/'operator-abort').exists(),'operator cancelled the probe')
        require(time.monotonic()<deadline,'operator synchronization timeout')
        if process is not None:require(process.poll() is None,'owned process ended before signal')
        time.sleep(.02)


def probe(plan_path,cycle):
    from server import credentials as private,state_backup,admission
    from server.profiles import ProfileStore
    from server.state_lock import exclusive_state
    plan,config=verify_plan(plan_path);out=Path(plan['output']);folder=out/f'cycle-{cycle}'
    require(cycle in (1,2),'invalid cycle');folder.mkdir(exist_ok=False)
    report=dict(passed=False,stage='connect',cycle=cycle);peers=[];worker=None
    helper=external(ROOT/'tools/server_console_match.py')
    recovery=external(ROOT/'tools/verify_server_recovery.py')
    started=time.monotonic()
    try:
        require(private._windows().sid==plan['owner_sid'],'different operator account')
        tokens=json.loads(private._read_file(out/'peers/tokens.json',4096))
        template,identity=state_backup.load_inputs(config);catalog=state_backup.load_cosmetics(config,identity)
        profiles=ProfileStore(config.data_directory/'profiles',template,catalog=catalog)
        expected={admission.rc_player_id(token):profiles.load_state(admission.rc_player_id(token),[]) for token in tokens}
        audit=config.data_directory/'logs/events.jsonl'
        rows=helper.audit_records(audit)
        # Scope by the new host's session; earlier stop events belong to cycle1.
        starts=[row for row in rows if row['event']=='server_started'];require(len(starts)==cycle,'host cycle count differs')
        session=starts[-1]['session']
        scoped=lambda:[row for row in helper.audit_records(audit) if row['session']==session]
        record=recovery.peers_match(config,tokens,expected,helper,peers)
        pid=helper.validate_audit(scoped(),record['match'],stopped=False,received_hashes=record['frame_payload_sha256'])
        worker=helper.WorkerHandle(c.WinDLL('kernel32',use_last_error=True),pid,Path(sys.executable))
        save(folder/'ready.json',dict(match=record['match'],worker_pid=pid,frames=40))
        report['stage']='await_operator_stop'
        wait_file(folder/'request-stop',60)
        stop_ns=time.perf_counter_ns();(folder/'stop-armed').write_bytes(b'peers held open\n')
        wait_file(folder/'service-stopped',35)
        record['worker']=worker.exited()
        helper.validate_audit(scoped(),record['match'],stopped=True,stop_ns=stop_ns,
                              received_hashes=record['frame_payload_sha256'])
        with exclusive_state(config.data_directory):pass
        with socket.socket() as test:
            test.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);test.bind(('127.0.0.1',config.listen_port))
        require({p.name:digest(p) for p in profiles.path.glob('*.json')}==plan['profile_sha256'],
                'service cycle changed retained profiles')
        require(all(token.encode() not in audit.read_bytes()+json.dumps(record).encode() for token in tokens),
                'token leaked into public evidence')
        report.update(passed=True,stage='complete',native_match=record,listener_closed=True,state_lock_released=True,
                      profile_bytes_preserved=True,tokens_not_logged=True)
    except BaseException as error:
        report.update(error_type=type(error).__name__,error_locations=[dict(file=Path(f.filename).name,line=f.lineno)
            for f in traceback.extract_tb(error.__traceback__)])
    finally:
        for peer in peers:peer.close()
        if worker:worker.close()
        report['elapsed_seconds']=time.monotonic()-started;save(folder/'probe-report.json',report)
    return 0 if report['passed'] else 1


async def rehearse(plan_path):
    """Exercise the new peer/control-file handoff with console host tasks, never SCM."""
    from server import host
    from server.worker_client import _WindowsJob
    plan_path=Path(plan_path).resolve()
    plan,config=verify_plan(plan_path);out=Path(plan['output'])
    require('rehearsal' in out.name and not (out/'data/logs').exists(),'fresh rehearsal-only capsule required')
    report=dict(passed=False,scm_registered=False,scm_qualified=False,forced_cleanup=False,cycles=[])
    async def wait(path,process,seconds):
        deadline=time.monotonic()+seconds
        while not path.exists():
            require(process.poll() is None and time.monotonic()<deadline,'rehearsal probe failed or timed out')
            await asyncio.sleep(.02)
    try:
        for cycle in (1,2):
            ready=asyncio.get_running_loop().create_future();process=job=None
            running=asyncio.create_task(host.run(config,on_ready=lambda address:ready.set_result(address)))
            try:
                async with asyncio.timeout(60):
                    while not ready.done():
                        if running.done():await running;raise AssertionError('host ended before ready')
                        await asyncio.sleep(.02)
                process=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'probe',
                    '--plan',str(plan_path),'--cycle',str(cycle)],cwd=out,stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
                job=_WindowsJob(process.pid);folder=out/f'cycle-{cycle}'
                await wait(folder/'ready.json',process,50)
                (folder/'request-stop').write_bytes(b'stop\n')
                await wait(folder/'stop-armed',process,5)
                running.cancel();ended=await asyncio.wait_for(asyncio.gather(running,return_exceptions=True),25)
                require(isinstance(ended[0],asyncio.CancelledError),'rehearsal host cleanup failed')
                (folder/'service-stopped').write_bytes(b'console task stopped; no SCM\n')
                require(await asyncio.to_thread(process.wait,10)==0,'rehearsal native probe failed')
                result=json.loads((folder/'probe-report.json').read_bytes())
                require(result['passed'],'rehearsal probe report failed');report['cycles'].append(result)
            finally:
                if not running.done():
                    running.cancel();await asyncio.wait_for(asyncio.gather(running,return_exceptions=True),25)
                if process is not None and process.poll() is None:
                    (out/'operator-abort').write_bytes(b'abort\n')
                    try:await asyncio.to_thread(process.wait,15)
                    except subprocess.TimeoutExpired:report['forced_cleanup']=True
                if job:job.close()
                if process is not None:await asyncio.to_thread(process.wait,15)
        report['passed']=not report['forced_cleanup']
    except BaseException as error:report['error_type']=type(error).__name__
    finally:save(out/'rehearsal-report.json',report)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','preflight','probe','rehearse'))
    for name in ('package','assets','output','plan'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--cycle',type=int)
    args=parser.parse_args()
    if args.command=='prepare':raise SystemExit(prepare(args.package,args.assets,args.output))
    if args.command=='preflight':
        verify_plan(args.plan);print(json.dumps(dict(plan_verified=True,scm=scm_access())));raise SystemExit(0)
    if args.command=='rehearse':
        with contextlib.redirect_stdout(io.StringIO()):result=asyncio.run(rehearse(args.plan))
        print(json.dumps(dict(rehearsal_passed=result==0,scm_qualified=False)));raise SystemExit(result)
    raise SystemExit(probe(args.plan,args.cycle))
