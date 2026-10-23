"""Owned RC snapshot/restore plus restored native frames, under the desktop owner.

Default requires an unrestricted owner before any private operation. Explicit
transport-control exercises only disposable TLS/native peers, never private backup
or restore. Neither route qualifies SCM, physical clients or a completed game.
Production imports come from the selected bundled runtime, never a sys.path edit.
"""
from __future__ import annotations
import argparse,asyncio,contextlib,ctypes as c,hashlib,importlib.util,io,json,os
from pathlib import Path
import secrets,socket,struct,subprocess,time,traceback

ROOT=Path(__file__).resolve().parents[1]
def require(value,message):
    if not value:raise AssertionError(message)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    temporary=path.with_name(path.name+'.staging')
    temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)
def external(name):
    path=ROOT/'tools'/name;spec=importlib.util.spec_from_file_location('recovery_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def peers_match(config,tokens,expected,helper,peers):
    from server import protocol as p,tls_transport as tls,admission
    from server.game_data import decompress_game_data,encode_player_input,decode_identity,decode_deck
    from server.protobuf_wire import get_bytes,get_repeated_bytes,get_uint,field_bytes,field_uint
    decks=[];authentication=[]
    for slot,token in enumerate(tokens):
        plain=socket.create_connection(('127.0.0.1',config.listen_port),timeout=5);peers.append(plain)
        stream=tls.rc_client_context('127.0.0.1').context.wrap_socket(plain,server_hostname='127.0.0.1');peers[-1]=stream
        profile=admission.rc_player_id(token)
        stream.sendall(p.encode(admission.AUTH_RC,struct.pack('<H',admission.AUTH_VERSION)+token.encode('ascii')))
        kind,body=helper.packet(stream)
        require(kind==admission.AUTH_OK and body==struct.pack('<HH',admission.AUTH_VERSION,34)+profile.encode('ascii'),'RC admission differs')
        authentication.append(dict(player_id=profile,tls_version=stream.version(),certificate_verified=False))
        stream.sendall(p.encode(p.HELLO,p.hello(slot,profile,'Recovery Player '+str(slot),'recovery151')))
        assigned,window,deck=p.decode_welcome(helper.receive(stream,p.WELCOME))
        require(assigned==slot and window==config.input_window and deck==list(expected[profile].deck),'restored welcome/deck differs');decks.append(deck)
    for stream in peers:stream.sendall(p.encode(p.LOBBY_READY,b'\x01'))
    matches=[helper.receive(stream,p.MATCH_INFO) for stream in peers];require(matches[0]==matches[1],'match IDs differ')
    bootstraps=[helper.receive(stream,p.BOOTSTRAP) for stream in peers];require(bootstraps[0]==bootstraps[1],'native bootstrap differs')
    game=get_bytes(decompress_game_data(bootstraps[0]),1,required=True)
    armies={get_uint(a,1):a for a in get_repeated_bytes(game,2)};require(set(armies)=={0,1},'two human armies required')
    identities=[];joins=[]
    for slot in (0,1):
        army=armies[slot];identity=get_bytes(army,2,required=True);deck=get_bytes(army,3,required=True)
        require(decode_identity(identity)['name']=='Recovery Player '+str(slot) and not decode_identity(identity)['ai_profile_id'] and decode_deck(deck)['units']==tuple(decks[slot]),'restored native roster differs')
        join=field_uint(1,slot)+field_bytes(2,deck)
        for target,source in ((3,5),(4,6)):
            value=get_uint(army,source)
            if value:join+=field_uint(target,value)
        identities.append(identity);joins.append(field_bytes(3,join))
    for stream in peers:stream.sendall(p.encode(p.LOADED,hashlib.sha256(bootstraps[0]).digest()))
    require([helper.receive(stream,p.START) for stream in peers]==[b'',b''],'native start differs')
    hashes=[]
    for frame in range(40):
        for slot,stream in enumerate(peers):stream.sendall(p.encode(p.INPUT,struct.pack('<I',frame)+encode_player_input(identities[slot],[joins[slot]] if frame==0 else [])))
        frames=[helper.receive(stream,p.FRAME) for stream in peers]
        require(frames[0]==frames[1] and struct.unpack_from('<I',frames[0])[0]==frame,'native frame streams differ')
        hashes.append(hashlib.sha256(frames[0]).hexdigest())
    return dict(match=matches[0].decode('ascii'),authentication=authentication,frames_per_peer=40,equal_frame_streams=True,frame_payload_sha256=hashes,bootstrap_sha256=hashlib.sha256(bootstraps[0]).hexdigest())

async def restored_host(config,tokens,expected):
    from server import host
    from server.state_lock import exclusive_state
    helper=external('server_console_match.py');ready=asyncio.get_running_loop().create_future()
    running=asyncio.create_task(host.run(config,on_ready=lambda address:ready.set_result(address)))
    peers=[];worker=None;record=None;stop_ns=None
    try:
        async with asyncio.timeout(60):
            while not ready.done():
                if running.done():await running;raise AssertionError('host ended before ready')
                await asyncio.sleep(.02)
        require(ready.result()==('127.0.0.1',config.listen_port),'owned localhost listener differs')
        record=await asyncio.wait_for(asyncio.to_thread(peers_match,config,tokens,expected,helper,peers),20)
        records=helper.audit_records(config.data_directory/'logs/events.jsonl')
        pid=helper.validate_audit(records,record['match'],stopped=False,received_hashes=record['frame_payload_sha256'])
        kernel=c.WinDLL('kernel32',use_last_error=True)
        worker=helper.WorkerHandle(kernel,pid,Path(__import__('sys').executable))
    finally:
        stop_ns=time.perf_counter_ns();running.cancel()
        try:await asyncio.wait_for(asyncio.gather(running,return_exceptions=True),20)
        except BaseException:
            if worker:worker.close();worker=None
            raise
        finally:
            for peer in peers:peer.close()
    try:
        require(record is not None and worker is not None,'native match not observed')
        record['worker']=worker.exited()
        records=helper.audit_records(config.data_directory/'logs/events.jsonl')
        helper.validate_audit(records,record['match'],stopped=True,stop_ns=stop_ns,received_hashes=record['frame_payload_sha256'])
        with exclusive_state(config.data_directory):pass
        with socket.socket() as test:test.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);test.bind(('127.0.0.1',config.listen_port))
        record.update(state_lock_released=True,listener_closed=True,active_match_aborted_on_shutdown=True,completed_game=False)
        return record
    finally:
        if worker:worker.close()

def child(request_path):
    from server import state_backup as b,credentials as private,rc_host,admission
    from server.configuration import load_config
    from server.profiles import ProfileStore
    from tools.package_integrity import verify
    request=json.loads(request_path.read_bytes());out=request_path.parent;report=dict(passed=False,stage='job_gate',protected_operations_attempted=False)
    started=time.monotonic()
    try:
        require(digest(__file__)==request['driver_sha256'] and digest(ROOT/'tools/server_console_match.py')==request['match_driver_sha256'],'diagnostic source changed')
        package=Path(request['package']);assets=Path(request['assets']);verify(package,'server')
        require(Path(b.__file__).resolve()==package/'program/app/server/state_backup.py' and digest(b.__file__)==request['backend_sha256'],'actual bundled backend differs')
        deadline=time.monotonic()+20
        while not (out/'job-ready').exists():require(time.monotonic()<deadline,'owned job gate absent');time.sleep(.02)
        require((out/'job-ready').read_bytes()==b'owned job attached\n','owned job gate differs')
        report['stage']='configure';config_dir=out/'config'
        certificate,key=rc_host.generate_certificate()
        cert,key_path=config_dir/'server.pem',config_dir/'server.key'
        if request['transport_control']:
            config_dir.mkdir()
            cert.write_bytes(certificate);key_path.write_bytes(key)
        else:
            report['protected_operations_attempted']=True
            private._ensure_private_directory(config_dir)
            private._write_file(cert,certificate);private._write_file(key_path,key)
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        settings=json.loads((package/'config/host.example.json').read_bytes())
        settings.update(schema=2,access_mode='rc-open',listen_host='127.0.0.1',listen_port=port,assets_directory=str(assets),data_directory=str(out/'data'),certificate_file=str(cert),private_key_file=str(key_path),credential_directory=None,allow_insecure_loopback=False,diagnostic_audit=True)
        config_path=config_dir/'host.json'
        if request['transport_control']:config_path.write_bytes(b.canonical(settings))
        else:private._write_file(config_path,b.canonical(settings))
        config=load_config(config_path);template,identity=b.load_inputs(config);catalog=b.load_cosmetics(config,identity)
        require(catalog is not None,'real cosmetic catalog required')
        tokens=['ba1_'+secrets.token_urlsafe(32) for _ in range(2)]
        profiles=ProfileStore(config.data_directory/'profiles',template,catalog=catalog)
        expected={}
        for slot,token in enumerate(tokens):
            profile=admission.rc_player_id(token)
            profiles.save(profile,template.default_decks[slot],cosmetics=catalog.normalize_local())
            expected[profile]=profiles.load_state(profile,[])
        original={p.name:digest(p) for p in profiles.path.glob('*.json')};original_config=digest(config_path)
        if not request['transport_control']:
            report['stage']='backup';snapshot=out/'snapshots/recovery.json';report['backup']=b.backup(config,snapshot)
            private._assert_private_path(snapshot)
            report['verified_backup']=b.verify_snapshot(config,snapshot)
            report['stage']='restore';restored=load_config(b.restore(config,snapshot,out/'restored')['config'])
            private._assert_private_path(restored.source)
            require(restored.access_mode=='rc-open' and not restored.allow_insecure_loopback and restored.credential_directory is None,'restored TLS/access mode differs')
            require(json.loads(restored.source.read_bytes())['schema']==2,'restored config schema differs')
            copied=ProfileStore(restored.data_directory/'profiles',template,catalog=catalog)
            require({k:copied.load_state(k,[]) for k in expected}==expected,'restored deck/full cosmetics differ')
            require({p.name:digest(p) for p in profiles.path.glob('*.json')}==original and digest(config_path)==original_config,'original state changed')
            require(not (restored.data_directory/'private/credentials').exists(),'unexpected RC invite store')
            report.update(protected_snapshot_readback=True,protected_config_readback=True,original_state_preserved=True,profile_cosmetics_equal=True)
            config=restored
        report['stage']='restored_native_match' if not request['transport_control'] else 'native_transport_control'
        with contextlib.redirect_stdout(io.StringIO()):report['native_match']=asyncio.run(restored_host(config,tokens,expected))
        copied=ProfileStore(config.data_directory/'profiles',template,catalog=catalog)
        require({k:copied.load_state(k,[]) for k in expected}==expected,'native host changed retained profiles')
        report.update(passed=True,stage='complete',transport_control=request['transport_control'],scm_qualified=False,completed_game_qualified=False)
    except BaseException as error:
        report.update(error_type=type(error).__name__,error_locations=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)])
    finally:
        report['elapsed_seconds']=time.monotonic()-started;save(out/'child-report.json',report)
    return 0 if report['passed'] else 1

def run(package,assets,output,*,transport_control=False,preflight_only=False):
    from tools.package_integrity import verify
    from server.worker_client import _WindowsJob
    helper=external('verify_owner_credentials.py')
    package,assets,output=(Path(p).resolve() for p in (package,assets,output))
    require(os.name=='nt' and all(p.is_relative_to(ROOT/'local') for p in (package,assets,output)),'owned ignored Windows paths required')
    require(not output.is_relative_to(package) and not output.is_relative_to(assets),'separate output required')
    output.mkdir(parents=True,exist_ok=False)
    report=dict(passed=False,stage='preflight',transport_control=transport_control,protected_operations_attempted=False,controller_started=False,forced_cleanup=False)
    process=job=None;started=time.monotonic();accounting=external('owned_suspended_launch.py').job_accounting
    try:
        verify(package,'server');report['package_manifest_sha256']=digest(package/'package-manifest.json')
        report['driver_sha256']=digest(__file__);report['match_driver_sha256']=digest(ROOT/'tools/server_console_match.py')
        report['backend_sha256']=digest(package/'program/app/server/state_backup.py')
        require(report['backend_sha256']==digest(ROOT/'server/state_backup.py'),'source/backend differs')
        report['restricting_sids_present']=helper.restricting_sids_present()
        if (report['restricting_sids_present'] and not transport_control) or preflight_only:
            report['stage']='normal_owner_required' if report['restricting_sids_present'] else 'preflight_ready'
            return 2 if report['restricting_sids_present'] else 0
        request=dict(package=str(package),assets=str(assets),transport_control=transport_control,
                     **{k:report[k] for k in ('driver_sha256','match_driver_sha256','backend_sha256')})
        save(output/'request.json',request)
        process=subprocess.Popen([str(package/'program/runtime/python.exe'),'-I','-B',str(Path(__file__).resolve()),'--child-request',str(output/'request.json')],cwd=output,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        report['controller_started']=True;job=_WindowsJob(process.pid)
        gate=output/'job-ready.staging';gate.write_bytes(b'owned job attached\n');gate.rename(output/'job-ready')
        report['child_exit']=process.wait(timeout=180)
        result=json.loads((output/'child-report.json').read_bytes());report['child']=result
        report['protected_operations_attempted']=result['protected_operations_attempted']
        deadline=time.monotonic()+5
        while accounting(job)['active_processes'] and time.monotonic()<deadline:time.sleep(.02)
        report['job_final']=accounting(job)
        require(report['job_final']['active_processes']==report['job_final']['total_terminated_processes']==0,'owned processes remain')
        report['passed']=report['child_exit']==0 and result['passed'] is True
        report['stage']=result['stage']
    except BaseException as error:report.update(error_type=type(error).__name__)
    finally:
        if process is not None and process.poll() is None:report['forced_cleanup']=True
        if job and accounting(job)['active_processes']:report['forced_cleanup']=True
        if job:job.close()
        if process is not None:
            if process.poll() is None:process.terminate()
            process.wait(timeout=15)
        report['sources_unchanged']=report.get('driver_sha256')==digest(__file__) and report.get('match_driver_sha256')==digest(ROOT/'tools/server_console_match.py')
        report['passed'] &= report['sources_unchanged'] and not report['forced_cleanup']
        report['elapsed_seconds']=time.monotonic()-started;save(output/'verification.json',report)
        print(json.dumps({k:report[k] for k in ('passed','stage','transport_control','controller_started','forced_cleanup','elapsed_seconds') if k in report}))
    return 0 if report['passed'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child-request',type=Path,help=argparse.SUPPRESS)
    for name in ('package','assets','output'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--transport-control',action='store_true')
    parser.add_argument('--preflight-only',action='store_true')
    args=parser.parse_args()
    if args.child_request:raise SystemExit(child(args.child_request))
    require(all((args.package,args.assets,args.output)),'package/assets/output required')
    raise SystemExit(run(args.package,args.assets,args.output,transport_control=args.transport_control,preflight_only=args.preflight_only))
