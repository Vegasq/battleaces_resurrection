"""Owned protected recovery through native surrender and dashboard history (184).

Default requires an unrestricted owner before any private operation. Explicit
transport-control exercises only disposable TLS/native peers, never private backup
or restore. Neither route qualifies SCM or physical clients. Derived from151;
that accepted driver is deliberately preserved. An observer subclass retains the
real coordinator for native-state-derived input; no simulation result is replaced.
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

# Reuse the native coordinator fixture's established post-start surrender point.
SURRENDER_FRAME=140

def dashboard_status(config):
    import http.client
    connection=http.client.HTTPConnection('127.0.0.1',config.dashboard_port,timeout=5)
    try:
        connection.request('GET','/api/status');response=connection.getresponse()
        require(response.status==200,'dashboard HTTP status differs')
        raw=response.read(1024*1024+1);require(len(raw)<=1024*1024,'dashboard response too large')
        result=json.loads(raw);require(result['persistence_ok'],'dashboard persistence failed')
        return result
    finally:connection.close()

def validate_result(result,match):
    require(result['match']==match and result['reason']=='native game complete','public completion differs')
    state=result['result']
    require(state['complete'] is True and state['winning_alliance']==1 and
            state['army_conceded_flag']==1 and state['game_over_frame']==SURRENDER_FRAME,
            'native surrender result differs')

def validate_completion(records,record,*,stop_ns=None):
    selected=[row for row in records if row.get('match')==record['match']]
    def one(event):
        rows=[row for row in selected if row['event']==event]
        require(len(rows)==1,'completion event count differs: '+event);return rows[0]
    worker=one('worker_started');one('match_created');one('match_started')
    native=one('native_game_over');completed=one('match_completed');released=one('worker_released')
    validate_result(record['public_result'],record['match'])
    require(native['result']==completed['result']==record['public_result']['result']==record['native_result'],
            'native/audit/public results differ')
    frames=[row for row in selected if row['event']=='frame_queued']
    require([row['frame'] for row in frames]==list(range(SURRENDER_FRAME+20)) and
            [row['frame_payload_sha256'] for row in frames]==record['frame_payload_sha256'],
            'host/peer frame sequence differs')
    require(completed['next_frame']==SURRENDER_FRAME+20 and worker['worker_pid']==released['worker_pid'] and
            native['perf_counter_ns']<completed['perf_counter_ns']<released['perf_counter_ns'],
            'completion/worker release order differs')
    forbidden={'match_aborted','simulation_error','worker_error','connection_error','protocol_error',
               'authentication_failed','authentication_shutdown_incomplete','audit_record_omitted'}
    require(not any(row['event'] in forbidden for row in records),'host audit contains failure')
    if stop_ns is not None:
        stops=[row for row in records if row['event']=='server_stopped']
        require(len(stops)==1 and released['perf_counter_ns']<stop_ns<=stops[0]['perf_counter_ns'],
                'worker did not finish before host shutdown')
    return worker['worker_pid']

def validate_dashboard(status,record,profiles,*,completed):
    rows=status['history'] if completed else status['active']
    require(len(rows)==1 and rows[0]['id']==record['match'],'dashboard match differs')
    row=rows[0]
    require(row['state']==('completed' if completed else 'running') and
            {p['id'] for p in row['players']}==set(profiles) and
            [p['name'] for p in row['players']]==['Recovery Player 0','Recovery Player 1'] and
            all(not p['bot'] for p in row['players']),'dashboard players/state differ')
    if completed:
        require(not status['active'] and status['completed']==status['history_total']==1 and
                row['winning_alliance']==1,'dashboard completion differs')
    return row

def peers_match(config,tokens,expected,helper,peers,servers,workers):
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
        stream.sendall(p.encode(p.HELLO,p.hello(slot,profile,'Recovery Player '+str(slot),'recovery184')))
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
    require(len(servers)==1,'coordinator observer count differs')
    room=servers[0].rooms['recovery184'];native_worker=room.sim
    worker=helper.WorkerHandle(c.WinDLL('kernel32',use_last_error=True),native_worker.pid,Path(__import__('sys').executable))
    workers.append(worker)
    record=dict(match=matches[0].decode('ascii'),authentication=authentication,
                bootstrap_sha256=hashlib.sha256(bootstraps[0]).hexdigest())
    record['dashboard_running']=dashboard_status(config)
    validate_dashboard(record['dashboard_running'],record,expected,completed=False)
    hashes=[]
    for frame in range(SURRENDER_FRAME+20):
        actions=[]
        if frame==SURRENDER_FRAME:
            from server.protobuf_wire import field_packed_uint,parse_fields
            require(native_worker.frame==frame-1,'native state is not the preceding frame')
            choices=[]
            for entity in native_worker.last_state['entities']:
                if entity.get('army')!=0 or 'type' not in entity:continue
                for key in room.template.entity_abilities.get(entity['type'],()):
                    if any(field.number==24 for field in parse_fields(room.template.abilities[key])):
                        choices.append((entity['id'],entity['type'],key))
            require(choices,'native state has no owned self-destruct ability')
            entity_id,entity_type,ability=min(choices)
            group=field_uint(1,entity_type)+field_uint(2,ability)+field_packed_uint(3,[entity_id])
            command=field_bytes(1,group)+field_bytes(3,field_bytes(1,b''))
            actions=[field_bytes(1,command)]
            record['surrender']=dict(frame=frame,entity_id=entity_id,entity_type=entity_type,ability=ability,
                                     native_state_sha256=hashlib.sha256(json.dumps(native_worker.last_state,sort_keys=True).encode()).hexdigest())
            save(config.data_directory/'completion-progress.json',dict(record,native_before_surrender=native_worker.last_state))
        for slot,stream in enumerate(peers):
            commands=[joins[slot]] if frame==0 else actions if slot==0 else []
            stream.sendall(p.encode(p.INPUT,struct.pack('<I',frame)+encode_player_input(identities[slot],commands)))
        frames=[helper.receive(stream,p.FRAME) for stream in peers]
        require(frames[0]==frames[1] and struct.unpack_from('<I',frames[0])[0]==frame,'native frame streams differ')
        hashes.append(hashlib.sha256(frames[0]).hexdigest())
    save(config.data_directory/'completion-progress.json',dict(record,native_after_frames=native_worker.last_state,
                                                              frame_payload_sha256=hashes))
    results=[helper.receive(stream,p.MATCH_END) for stream in peers]
    require(results[0]==results[1],'peer final results differ')
    record.update(public_result=json.loads(results[0]),native_result=native_worker.last_state['game_state'],
                  frames_per_peer=len(hashes),equal_frame_streams=True,frame_payload_sha256=hashes)
    validate_result(record['public_result'],record['match'])
    deadline=time.monotonic()+10
    while not any(row['event']=='worker_released' and row.get('match')==record['match']
                  for row in helper.audit_records(config.data_directory/'logs/events.jsonl')):
        require(time.monotonic()<deadline,'native worker release deadline exceeded');time.sleep(.02)
    record['worker']=worker.exited()
    require(native_worker.closed and native_worker.process.poll()==0,'native worker did not close cleanly')
    validate_completion(helper.audit_records(config.data_directory/'logs/events.jsonl'),record)
    record['dashboard_completed']=dashboard_status(config)
    validate_dashboard(record['dashboard_completed'],record,expected,completed=True)
    return record

async def restored_host(config,tokens,expected):
    from server import host
    from server.state_lock import exclusive_state
    helper=external('server_console_match.py');ready=asyncio.get_running_loop().create_future()
    servers=[];workers=[];original=host.DedicatedServer
    class ObservedServer(original):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);servers.append(self)
    host.DedicatedServer=ObservedServer
    running=asyncio.create_task(host.run(config,on_ready=lambda address:ready.set_result(address)))
    peers=[];record=None;stop_ns=None
    try:
        async with asyncio.timeout(60):
            while not ready.done():
                if running.done():await running;raise AssertionError('host ended before ready')
                await asyncio.sleep(.02)
        require(ready.result()==('127.0.0.1',config.listen_port),'owned localhost listener differs')
        record=await asyncio.wait_for(asyncio.to_thread(peers_match,config,tokens,expected,helper,peers,servers,workers),45)
    finally:
        stop_ns=time.perf_counter_ns();running.cancel()
        try:
            ended=await asyncio.wait_for(asyncio.gather(running,return_exceptions=True),20)
            require(isinstance(ended[0],asyncio.CancelledError),'host shutdown raised an unexpected result')
        finally:
            for peer in peers:peer.close()
            for worker in workers:worker.close()
            host.DedicatedServer=original
    require(record is not None and len(workers)==1,'native match not observed')
    records=helper.audit_records(config.data_directory/'logs/events.jsonl')
    validate_completion(records,record,stop_ns=stop_ns)
    with exclusive_state(config.data_directory):pass
    for port in (config.listen_port,config.dashboard_port):
        with socket.socket() as test:test.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);test.bind(('127.0.0.1',port))
    from server.web_dashboard import read_history
    history=read_history(config.data_directory/'web-matches.json')
    require(history==record['dashboard_completed']['history'],'persisted native result differs')
    record.update(state_lock_released=True,listener_closed=True,dashboard_listener_closed=True,
                  history_persisted=True,active_match_aborted_on_shutdown=False,completed_game=True)
    return record

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
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',port))
            with socket.socket() as web_reserve:web_reserve.bind(('127.0.0.1',0));web_port=web_reserve.getsockname()[1]
        settings=json.loads((package/'config/host.example.json').read_bytes())
        settings.update(schema=2,access_mode='rc-open',listen_host='127.0.0.1',listen_port=port,assets_directory=str(assets),data_directory=str(out/'data'),certificate_file=str(cert),private_key_file=str(key_path),credential_directory=None,allow_insecure_loopback=False,diagnostic_audit=True)
        settings.update(dashboard_host='127.0.0.1',dashboard_port=web_port)
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
        report.update(passed=True,stage='complete',transport_control=request['transport_control'],scm_qualified=False,completed_game_qualified=True)
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
        report['asset_manifest_sha256']=digest(assets/'asset-manifest.json')
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
        verify(package,'server')
        from server.assets import verify_assets
        verify_assets(assets)
        require(report['package_manifest_sha256']==digest(package/'package-manifest.json') and
                report['asset_manifest_sha256']==digest(assets/'asset-manifest.json'),'package/assets changed')
        report['package_assets_unchanged']=True
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
