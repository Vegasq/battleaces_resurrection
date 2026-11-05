"""Owned packaged RC identity/key lifecycle185; no game UI or existing host changes.

Runs only under an unrestricted Windows owner. The selected bundled runtime
supplies all production imports. Fresh client settings/data/keys stay in local/;
the game directory is used only for the production settings existence check.
"""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
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


def external(name):
    spec=importlib.util.spec_from_file_location('lifecycle_'+Path(name).stem,ROOT/'tools'/name)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def resolve(path):
    from client_patch.transport import launcher,rc_setup
    config=rc_setup.settings(launcher.read_json(path,32768),path)
    return rc_setup.Resolver(path,config['game_directory']).read()


def identity_child(path,result,gate):
    deadline=time.monotonic()+15
    while not gate.exists():
        require(time.monotonic()<deadline,'identity start gate absent');time.sleep(.01)
    target=resolve(path)
    save(result,dict(player_id=target.player_id))  # Never send the token through output/arguments.
    return 0


def concurrent_identity(path,out):
    processes=[];gate=out/'identities-ready';results=[]
    try:
        for index in range(4):
            result=out/f'identity-{index}.json';results.append(result)
            processes.append(subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),
                '--identity-child',str(path),'--result',str(result),'--gate',str(gate)],
                cwd=out,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW))
        gate.write_bytes(b'owned concurrent identity check\n')
        codes=[process.wait(timeout=20) for process in processes]
        require(codes==[0]*4,'identity child failed')
        ids=[json.loads(result.read_bytes())['player_id'] for result in results]
        require(len(set(ids))==1,'concurrent first launches created different identities')
        return dict(children=4,exit_codes=codes,player_id=ids[0])
    finally:
        live=[process for process in processes if process.poll() is None]
        for process in live:process.terminate()
        for process in live:process.wait(timeout=10)
        require(not live,'identity children required forced cleanup')


def identity_path(client_path,target):
    from client_patch.transport import launcher,rc_setup
    config=rc_setup.settings(launcher.read_json(client_path,32768),client_path)
    route=f"{config['server_host']}:{config['server_port']}/{config['local_profile']}"
    path=client_path.parent/'rc-identities'/(hashlib.sha256(route.encode()).hexdigest()+'.json')
    require(json.loads(path.read_bytes())['player_id']==target.player_id,'identity path binding differs')
    return path


def client_lifecycle(path,out,game,port,report):
    from client_patch.transport import rc_setup
    def edit(host='127.0.0.1',name='Lifecycle Player'):
        rc_setup.save(dict(game_directory=str(game),display_name=name,server_host=host,
                          expected_config_sha256=rc_setup.digest(path)),path)
    edit()
    settings=json.loads(path.read_bytes());settings['server_port']=port;save(path,settings)
    report['concurrent_first_launch']=concurrent_identity(path,out)
    original=resolve(path);identity=identity_path(path,original);original_bytes=identity.read_bytes()
    require(original.player_id==report['concurrent_first_launch']['player_id'],'reopened identity differs')
    edit(name='Renamed Lifecycle Player')
    require(resolve(path).player_id==original.player_id and identity.read_bytes()==original_bytes,
            'display name edit reset identity')
    edit(host='localhost')
    other_route=resolve(path)
    require(other_route.player_id!=original.player_id,'different route reused identity')
    edit()
    require(resolve(path).player_id==original.player_id,'return to route lost identity')
    settings=json.loads(path.read_bytes());settings['local_profile']='another';save(path,settings)
    other_profile=resolve(path)
    require(other_profile.player_id not in (original.player_id,other_route.player_id),'profile isolation failed')
    settings['local_profile']='default';save(path,settings)
    require(resolve(path).player_id==original.player_id,'return to profile lost identity')
    try:
        identity.write_bytes(b'{}')
        try:resolve(path)
        except ValueError:pass
        else:raise AssertionError('damaged identity was accepted')
        require(identity.read_bytes()==b'{}','damaged identity was silently replaced')
    finally:identity.write_bytes(original_bytes)
    require(resolve(path).player_id==original.player_id and identity.read_bytes()==original_bytes,
            'restored identity backup differs')
    report['client_identity']=dict(player_id=original.player_id,rename_preserved=True,route_isolated=True,
        profile_isolated=True,route_profile_return_preserved=True,damaged_file_preserved=True,backup_restored=True)
    return original,[original.token,other_route.token,other_profile.token]


def authenticated_welcome(config,target,deck):
    from server import protocol as p,tls_transport as tls,admission
    helper=external('server_console_match.py')
    plain=socket.create_connection(('127.0.0.1',config.listen_port),timeout=5)
    with tls.rc_client_context('127.0.0.1').context.wrap_socket(plain,server_hostname='127.0.0.1') as stream:
        certificate=hashlib.sha256(stream.getpeercert(binary_form=True)).hexdigest()
        stream.sendall(p.encode(admission.AUTH_RC,struct.pack('<H',admission.AUTH_VERSION)+target.token.encode('ascii')))
        kind,body=helper.packet(stream)
        require(kind==admission.AUTH_OK and body==struct.pack('<HH',admission.AUTH_VERSION,34)+target.player_id.encode(),
                'actual host identity differs')
        stream.sendall(p.encode(p.HELLO,p.hello(0,target.player_id,'Lifecycle Player','lifecycle185')))
        slot,window,saved=p.decode_welcome(helper.receive(stream,p.WELCOME))
        require(slot==0 and window==config.input_window and saved==list(deck),'host returned a different saved deck')
        return dict(player_id=target.player_id,certificate_der_sha256=certificate,tls=stream.version(),
                    certificate_verified=False,saved_deck_equal=True)


async def host_cycle(config,target,deck):
    from server import host
    from server.state_lock import exclusive_state
    ready=asyncio.get_running_loop().create_future()
    running=asyncio.create_task(host.run(config,on_ready=lambda address:ready.set_result(address)))
    output=io.StringIO()
    with contextlib.redirect_stdout(output):
        try:
            async with asyncio.timeout(60):
                while not ready.done():
                    if running.done():await running;raise AssertionError('host ended before ready')
                    await asyncio.sleep(.02)
            require(ready.result()==('127.0.0.1',config.listen_port),'host address differs')
            result=await asyncio.to_thread(authenticated_welcome,config,target,deck)
        finally:
            running.cancel()
            ended=await asyncio.wait_for(asyncio.gather(running,return_exceptions=True),20)
            require(isinstance(ended[0],asyncio.CancelledError),'host cleanup failed')
    health=[json.loads(line) for line in output.getvalue().splitlines() if line.startswith('{')]
    require(len(health)==1 and health[0]['passed'] and health[0]['native']['exit_code']==0,'native host health failed')
    with exclusive_state(config.data_directory):pass
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);probe.bind(('127.0.0.1',config.listen_port))
    return dict(result,native_health=health[0]['native'],state_lock_released=True,listener_closed=True)


def child(request_path):
    from tools.package_integrity import verify
    from server import rc_host,credentials as private,state_backup
    from server.configuration import load_config
    from server.profiles import ProfileStore
    from server.tls_transport import load_server_context
    request=json.loads(request_path.read_bytes());out=request_path.parent
    report=dict(passed=False,stage='gate',protected_operations_attempted=False)
    started=time.monotonic()
    try:
        require(digest(__file__)==request['driver_sha256'],'driver changed')
        package=Path(request['package']);verify(package,'server')
        require(Path(rc_host.__file__).resolve()==package/'program/app/server/rc_host.py','unbundled production import')
        deadline=time.monotonic()+20
        while not (out/'job-ready').exists():
            require(time.monotonic()<deadline,'owned job gate absent');time.sleep(.02)
        report['stage']='automatic_host_keys';report['protected_operations_attempted']=True
        path=out/'host-config/host.json';assets=Path(request['assets'])
        config=rc_host.initialize(path,assets)
        for file in (config.certificate_file,config.private_key_file):private._assert_private_path(file)
        before={str(file):digest(file) for file in (path,config.certificate_file,config.private_key_file)}
        require(rc_host.initialize(path,assets)==config and all(digest(file)==sha for file,sha in before.items()),
                'repeat first start changed existing keys/config')
        report['automatic_key_creation_and_reuse']=True
        settings=json.loads(path.read_bytes())
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        settings.update(listen_host='127.0.0.1',listen_port=port,dashboard_port=0,data_directory=str(out/'data'))
        save(path,settings);config=load_config(path)
        report['stage']='client_identity'
        target,tokens=client_lifecycle(out/'client/client.json',out,Path(request['game']),port,report)
        template,identity=state_backup.load_inputs(config);catalog=state_backup.load_cosmetics(config,identity)
        require(catalog is not None,'real installed cosmetics required')
        profiles=ProfileStore(config.data_directory/'profiles',template,catalog=catalog)
        profiles.save(target.player_id,template.default_decks[1],cosmetics=catalog.normalize_local())
        expected=profiles.load_state(target.player_id,[])
        profile_hashes={file.name:digest(file) for file in profiles.path.glob('*.json')}
        report['stage']='initial_host';report['host_cycles']=[asyncio.run(host_cycle(config,target,expected.deck))]
        report['stage']='replacement_certificate'
        replacement=rc_host.initialize(path.parent/'replacement-host.json',assets)
        for file in (replacement.certificate_file,replacement.private_key_file):private._assert_private_path(file)
        settings.update(certificate_file=str(replacement.certificate_file),private_key_file=str(replacement.private_key_file))
        save(path,settings);config=load_config(path)
        require(resolve(out/'client/client.json').player_id==target.player_id,'certificate change reset local identity')
        report['host_cycles'].append(asyncio.run(host_cycle(config,target,expected.deck)))
        first,second=report['host_cycles']
        require(first['player_id']==second['player_id']==target.player_id and
                first['certificate_der_sha256']!=second['certificate_der_sha256'],'certificate replacement not exercised')
        require(profiles.load_state(target.player_id,[])==expected and
                {file.name:digest(file) for file in profiles.path.glob('*.json')}==profile_hashes,'saved profile changed')
        report['certificate_replacement_preserves_identity_deck_cosmetics']=True
        report['stage']='missing_key_refusal'
        key=config.private_key_file;backup=key.with_name('owned-key-backup');config_hash=digest(path)
        require(key.resolve().is_relative_to(out) and not backup.exists(),'owned key boundary differs')
        key.rename(backup)
        try:
            require(rc_host.initialize(path,assets)==config and not key.exists(),'missing key silently regenerated')
            try:load_server_context(config.certificate_file,key)
            except (OSError,ValueError):pass
            else:raise AssertionError('missing key accepted')
            require(digest(path)==config_hash,'missing key changed host settings')
        finally:backup.rename(key)
        private._assert_private_path(key);load_server_context(config.certificate_file,key)
        report['missing_key_refused_without_regeneration']=True
        raw_logs=b''.join(file.read_bytes() for file in (config.data_directory/'logs').glob('events.jsonl*'))
        require(all(token.encode() not in raw_logs+json.dumps(report).encode() for token in tokens),'credential leaked in public output')
        report.update(passed=True,stage='complete',tokens_absent_from_reports_and_logs=True)
    except BaseException as error:
        report.update(error_type=type(error).__name__,error_locations=[dict(file=Path(f.filename).name,line=f.lineno)
            for f in traceback.extract_tb(error.__traceback__)])
    finally:
        report['elapsed_seconds']=time.monotonic()-started;save(out/'child-report.json',report)
    return 0 if report['passed'] else 1


def run(package,assets,game,output):
    from tools.package_integrity import verify
    from server.assets import verify_assets
    from server.worker_client import _WindowsJob
    package,assets,game,out=(Path(path).resolve() for path in (package,assets,game,output))
    require(os.name=='nt' and all(path.is_relative_to(ROOT/'local') for path in (package,assets,game,out)),
            'owned ignored Windows paths required')
    require(not any(out.is_relative_to(path) or path.is_relative_to(out) for path in (package,assets,game)),
            'separate output required')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(passed=False,stage='preflight',forced_cleanup=False,protected_operations_attempted=False)
    process=job=None;started=time.monotonic();accounting=external('owned_suspended_launch.py').job_accounting
    try:
        report['driver_sha256']=digest(__file__)
        report['helper_sha256']=digest(ROOT/'tools/server_console_match.py')
        verify(package,'server');verify_assets(assets)
        report['package_manifest_sha256']=digest(package/'package-manifest.json')
        report['asset_manifest_sha256']=digest(assets/'asset-manifest.json')
        report['game_exe_sha256']=digest(game/'Battle Aces.exe')
        report['restricting_sids_present']=external('verify_owner_credentials.py').restricting_sids_present()
        if report['restricting_sids_present']:
            report['stage']='normal_owner_required';return 2
        save(out/'request.json',dict(package=str(package),assets=str(assets),game=str(game),driver_sha256=report['driver_sha256']))
        process=subprocess.Popen([str(package/'program/runtime/python.exe'),'-I','-B',str(Path(__file__).resolve()),
            '--child-request',str(out/'request.json')],cwd=out,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        job=_WindowsJob(process.pid);(out/'job-ready').write_bytes(b'owned job attached\n')
        report['child_exit']=process.wait(timeout=180)
        report['child']=json.loads((out/'child-report.json').read_bytes())
        report['protected_operations_attempted']=report['child']['protected_operations_attempted']
        report['job_final']=accounting(job)
        require(report['job_final']['active_processes']==report['job_final']['total_terminated_processes']==0,'owned children remain')
        verify(package,'server');verify_assets(assets)
        require(report['package_manifest_sha256']==digest(package/'package-manifest.json') and
                report['asset_manifest_sha256']==digest(assets/'asset-manifest.json') and
                report['game_exe_sha256']==digest(game/'Battle Aces.exe'),'input changed')
        report['inputs_unchanged']=True
        report.update(passed=report['child_exit']==0 and report['child']['passed'],stage=report['child']['stage'])
    except BaseException as error:report['error_type']=type(error).__name__
    finally:
        if process is not None and process.poll() is None:report['forced_cleanup']=True
        if job and accounting(job)['active_processes']:report['forced_cleanup']=True
        if job:job.close()
        if process is not None:
            if process.poll() is None:process.terminate()
            process.wait(timeout=15)
        report['sources_unchanged']=(report.get('driver_sha256')==digest(__file__) and
                                     report.get('helper_sha256')==digest(ROOT/'tools/server_console_match.py'))
        report['passed'] &= report['sources_unchanged'] and not report['forced_cleanup']
        report['elapsed_seconds']=time.monotonic()-started;save(out/'verification.json',report)
        print(json.dumps({key:report[key] for key in ('passed','stage','forced_cleanup','elapsed_seconds')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','assets','game','output','child-request','identity-child','result','gate'):
        parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.identity_child:raise SystemExit(identity_child(args.identity_child,args.result,args.gate))
    if args.child_request:raise SystemExit(child(args.child_request))
    require(all((args.package,args.assets,args.game,args.output)),'package/assets/game/output required')
    raise SystemExit(run(args.package,args.assets,args.game,args.output))
