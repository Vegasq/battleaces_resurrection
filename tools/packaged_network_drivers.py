"""External qualification adapters only; never included in a player package.

Default restricted-token controls use explicit stdin-only identity fixtures.
Opt-in normal-owner controls use real protected credentials and production
readers/store;stdin then carries public expected identities only. Never packaged.
"""

SERVER_CHECK=r'''
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
from tools.package_integrity import verify
request=json.loads(Path(sys.argv[1]).read_bytes());output=Path(request['output']);package=Path(request['package'])
assert json.loads(sys.stdin.buffer.read(128))=={}
report=dict(passed=False,scope='Actual packaged BattleAces-Server.cmd check, not Start Server/Ctrl+C or Internet acceptance')
try:
    verify(package,'server')
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():assert time.monotonic()<deadline;time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    entry=package/'BattleAces-Server.cmd';config=Path(request['config'])
    shell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/cmd.exe'
    command='"'+str(shell)+'" /d /s /c ""'+str(entry)+'" check --config "'+str(config)+'""'
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
    result=subprocess.run(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=60,startupinfo=info,close_fds=True)
    (output/'command-stdout.txt').write_bytes(result.stdout);(output/'command-stderr.txt').write_bytes(result.stderr)
    assert result.returncode==0 and not result.stderr
    objects=[]
    for line in result.stdout.decode('utf-8-sig').splitlines():
        if line.startswith('{'):objects.append(json.loads(line))
    assert len(objects)==1
    health=objects[0];native=health['native']
    assert health['passed'] and health['tls'] and health['credential_store_checked'] and health['pointer_bits']==64
    assert native['created'] and native['stepped_frame']==0 and native['exit_code']==0 and native['reaped']
    report.update(passed=True,health=health,command=command,entry_sha256=hashlib.sha256(entry.read_bytes()).hexdigest(),command_exit_code=0)
except BaseException as error:report['error_type']=type(error).__name__
finally:(output/'server-command-check.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
'''

SNAPSHOT_MAX_BYTES=4*1024*1024
SNAPSHOT_MAX_ROW_BYTES=65536

from pathlib import Path
WORKER_OBSERVATION_SOURCE=Path(__file__).with_name('worker_observation.py').read_text(encoding='utf-8')
TIMING_PROBE_SOURCE=Path(__file__).with_name('timing_probe.py').read_text(encoding='utf-8')
AUDIT_STAGE_SOURCE=Path(__file__).with_name('audit_stage_probe.py').read_text(encoding='utf-8')

SERVER=f'SNAPSHOT_MAX_BYTES={SNAPSHOT_MAX_BYTES}\nSNAPSHOT_MAX_ROW_BYTES={SNAPSHOT_MAX_ROW_BYTES}\n'+WORKER_OBSERVATION_SOURCE+'\n'+TIMING_PROBE_SOURCE+'\n'+AUDIT_STAGE_SOURCE+'\n'+r'''
import asyncio,hashlib,json,secrets,socket,sys,time,traceback
from pathlib import Path
from server import host,worker_client
from server.credentials import AuthenticationError
from server.configuration import load_config
from tools.package_integrity import verify
request=json.loads(Path(sys.argv[1]).read_bytes());output=Path(request['output']);package=Path(request['package'])
fixture=json.loads(sys.stdin.buffer.read(16385));assert len(fixture['identities']) in (1,2,3,4)
assert not request.get('recover_stage') or len(fixture['identities'])==2
real_credentials=bool(request.get('real_credentials'))
rc_open=bool(request.get('rc_open'))
verify(package,'server');report=dict(passed=False,production_modules={},fixture_store=not (real_credentials or rc_open),workers=[],frozen_matches=[],custom_commands=[])
workers=WorkerObservations();servers=[];authenticated=[];stores=[];old_sessions={};snapshot_sequence=0
timing=TimingObservations(capacity=131072 if request.get('custom_soak') else 65536) if request.get('timing_probe') else None
stage_observers=[];original_audits=[];gc_observer=GCWindows() if request.get('audit_stages') else None
def publish(name,value):
    global snapshot_sequence
    if name=='server-live.jsonl':
        snapshot_sequence+=1
        raw=(json.dumps(dict(sequence=snapshot_sequence,snapshot=value),separators=(',',':'))+'\n').encode('ascii')
        assert len(raw)<=SNAPSHOT_MAX_ROW_BYTES,'diagnostic snapshot row exceeds bound'
        with (output/name).open('ab') as stream:
            assert stream.tell()+len(raw)<=SNAPSHOT_MAX_BYTES,'diagnostic snapshot journal exceeds bound'
            assert stream.write(raw)==len(raw)
        return
    temporary=output/(name+'.tmp');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(output/name)
class MemoryStore:
    def __init__(self,path):
        assert Path(path)==Path(request['credential_directory']);stores.append(self)
    def list_public(self):return []
    def authenticate(self,token):
        for identity in fixture['identities']:
            if secrets.compare_digest(token,identity['token']):authenticated.append(identity['player_id']);return identity['player_id']
        raise AuthenticationError()
original_create=worker_client.SimulationWorker.create;original_server=host.DedicatedServer;original_store=host.CredentialStore
original_popen=worker_client.subprocess.Popen
worker_audit_launches=0
worker_audit_pids=[]
if request.get('worker_socket_audit'):
    def worker_popen(command,*args,**kwargs):
        global worker_audit_launches
        selected=(isinstance(command,list) and len(command)>=9 and
                  command[1:6]==['-I','-S','-B','-u','-c'] and
                  command[6].startswith('import runpy,sys;sys.path.insert(0,sys.argv.pop(1));') and
                  command[8]=='--stdio')
        if selected:
            assert worker_audit_launches<len(request['worker_audit_sources']),'owned worker audit capacity exceeded'
            command=list(command);command[6]=request['worker_audit_sources'][worker_audit_launches]+command[6]
        process=original_popen(command,*args,**kwargs)
        if selected:
            worker_audit_launches+=1;worker_audit_pids.append(process.pid)
        return process
    worker_client.subprocess.Popen=worker_popen
async def create(*args,**kwargs):
    worker=await original_create(*args,**kwargs);return workers.add(worker)
def server(*args,**kwargs):
    value=original_server(*args,**kwargs);servers.append(value);original_audit=value.audit
    original_audits.append(original_audit)
    stages=AuditStages(original_audit,sys.modules['server.host_audit'],timing) if request.get('audit_stages') else None
    if stages:stage_observers.append(stages)
    if real_credentials or rc_open:
        store=value.admission.store
        if rc_open:
            assert store is None and value.admission.rc_open
            report['production_rc_admission_verified']=True
        else:
            assert type(store) is original_store and store.directory==Path(request['credential_directory'])
            stores.append(store)
        actual_authenticate=value.admission.authenticate
        async def observe_authentication(reader,writer):
            player=await actual_authenticate(reader,writer);authenticated.append(player);return player
        value.admission.authenticate=observe_authentication
        report['production_store_type_verified']=not rc_open
    def observe(event,**fields):
        if stages:stages.call(event,**fields)
        elif timing is None:original_audit(event,**fields)
        else:timing.call('audit',original_audit,event,metadata=dict(event=event,**{key:fields[key] for key in ('match','frame') if key in fields}),**fields)
        if request.get('cancel_waiting') and event=='public_queue_entered':
            entry=value.community.public.entries[fields['profile']]
            selection=dict(profile=entry.profile,ticket=entry.ticket,mode=entry.mode,deck=list(entry.deck),
                           full_loadout=entry.full_loadout,cosmetics=dict(catalog_sha256=entry.cosmetics.catalog_sha256,slots=dict(entry.cosmetics.slots)))
            report.setdefault('queue_selections',[]).append(selection)
            assert len(report['queue_selections'])<=2,'unexpected additional cancellation diagnostic ticket'
        if event=='match_created':
            room=value.rooms[fields['room']];match=room.match
            report['frozen_matches'].append(dict(match=fields['match'],game_data_sha256=match.raw_sha256,
                lobby=room.community_lobby,epoch=value.community.lobbies[room.community_lobby].epoch if room.community_lobby else None,
                humans={slot:dict(profile=peer.profile_id,name=peer.name) for slot,peer in room.peers.items()},
                complete_profiles=sorted(peer.profile_id for peer in room.peers.values() if value.community.sessions[peer.profile_id].full_loadout),
                cosmetics={slot:dict(catalog_sha256=appearance.catalog_sha256,slots=appearance.slots) for slot,appearance in match.cosmetics_by_slot.items()},
                roster=[dict(slot=p.slot,player_id=p.player_id,name=p.name,ai_profile_id=p.ai_profile_id) for p in match.roster],
                decks={slot:list(deck) for slot,deck in match.decks_by_slot.items()},
                active_ability_groups={slot:list(groups) for slot,groups in match.active_ability_groups_by_slot.items()},
                full_loadout_seats=sorted(room.full_loadout_seats)))
            if request.get('network_outage') and len(report['frozen_matches'])==1:
                old_sessions.update({p['player_id']:value.community.sessions[p['player_id']]
                                     for p in fixture['identities']})
            if request.get('network_outage') and len(report['frozen_matches'])==2:
                report['recovery_sessions']=dict(both_replaced=all(
                    value.community.sessions[p['player_id']] is not old_sessions[p['player_id']]
                    for p in fixture['identities']))
            if request.get('recover_stage') and len(report['frozen_matches'])==2:
                victim,survivor=(p['player_id'] for p in fixture['identities'])
                report['recovery_sessions']=dict(survivor_retained=value.community.sessions[survivor] is old_sessions[survivor],
                    victim_replaced=value.community.sessions[victim] is not old_sessions[victim])
    value.audit=observe
    if request.get('custom_rematch'):
        original_apply=value.community.apply
        async def apply(session,kind,command,now):
            report['custom_commands'].append(dict(profile=session.peer.profile_id,kind=kind,request=command.get('request'),lobby=command.get('lobby'),epoch=command.get('epoch'),perf_counter_ns=time.perf_counter_ns()))
            if request.get('custom_start_rejection') and kind==48 and 'start_rejection' not in report:
                from server.community import Rejected
                lobby=value.community.lobbies[command['lobby']]
                assert lobby.phase==1 and lobby.epoch==0 and lobby.host==session.peer.profile_id
                assert not value.rooms and not report['frozen_matches']
                report['start_rejection']=dict(lobby=lobby.id,profile=lobby.host,request=command['request'],
                    epoch=lobby.epoch,phase=lobby.phase,revision=lobby.revision,rooms=0,matches=0,
                    reason='qualification: host start rejected',
                    selections={profile:dict(deck=list(value.community.sessions[profile].deck),
                        full=value.community.sessions[profile].full_loadout,
                        cosmetics=dict(catalog_sha256=value.community.sessions[profile].cosmetics.catalog_sha256,
                            slots=value.community.sessions[profile].cosmetics.slots)) for profile in lobby.members})
                # Authored one-shot rejection; the normal server handler emits
                # the correlated negative ACK. No epoch or worker is created.
                raise Rejected(report['start_rejection']['reason'])
            if request.get('custom_ready_expiry') and kind==49 and 'ready_expiry' not in report:
                from server.community import Rejected
                lobby=value.community.lobbies[command['lobby']]
                assert value.community.start_timeout==10 and lobby.phase==2 and lobby.epoch==command['epoch']==1
                proof=dict(lobby=lobby.id,profile=session.peer.profile_id,request=command['request'],old_epoch=1,
                    configured_timeout=value.community.start_timeout,deadline=lobby.deadline,held_at=time.monotonic())
                report['ready_expiry']=proof
                # Let real maintenance expire epoch1 and the original host UI
                # retry. Retain the guest's old pending request until epoch3.
                while lobby.epoch!=3 or lobby.phase!=2:
                    assert time.monotonic()-proof['held_at']<20,'native host did not retry expired Start'
                    await asyncio.sleep(.01)
                def state():
                    return dict(lobby=lobby.id,epoch=lobby.epoch,phase=lobby.phase,revision=lobby.revision,
                        deadline=lobby.deadline,ready=sorted(lobby.ready),members=list(lobby.members),
                        room=lobby.room,rooms=len(value.rooms),matches=len(report['frozen_matches']))
                proof.update(released_at=time.monotonic(),before=state())
                assert proof['released_at']>=proof['deadline'] and not value.rooms and not report['frozen_matches']
                try:
                    await original_apply(session,kind,command,time.monotonic())
                except Rejected as error:
                    proof.update(rejection=str(error),after=state(),rejected_at=time.monotonic())
                    assert proof['before']==proof['after'] and str(error)=='start attempt changed'
                    raise
                raise AssertionError('expired Ready unexpectedly accepted')
            return await original_apply(session,kind,command,now)
        value.community.apply=apply
    return value
def view():
    if not servers:return {}
    value=servers[0]
    return dict(active_workers=workers.active(),
                rooms=len(value.rooms),retired=len(value.retired),entries=len(value.community.public.entries),
                offers=len(value.community.public.offers),cleanup=len(value.worker_cleanup),sessions=len(value.community.sessions),
                lobbies=[dict(id=l.id,phase=l.phase,epoch=l.epoch,members=sorted(l.members)) for l in value.community.lobbies.values()])
def inject_disconnect():
    command=output/'server-disconnect.json'
    stage=request.get('recover_stage')
    if not stage or report.get('fault') or not command.exists():return
    victim,survivor=(p['player_id'] for p in fixture['identities'])
    assert json.loads(command.read_bytes())==dict(player=victim)
    value=servers[0];session=value.community.sessions[victim];peer=session.peer;room=peer.room
    assert room and len(room.peers)==2 and not peer.closed
    if stage=='loading':assert room.state=='loading' and not room.loaded and room.frame==0
    else:assert stage=='running' and room.state=='running' and room.loaded==set(room.peers) and room.frame>=request['disconnect_after_frame']+1
    assert len(report['frozen_matches'])==1 and room.sim is not None
    old_sessions.update({p:value.community.sessions[p] for p in (victim,survivor)})
    report['fault']=dict(stage=stage,match=room.match_id,victim=victim,victim_seat=peer.slot,worker_pid=room.sim.pid,
                        room_state=room.state,next_frame=room.frame,loaded=sorted(room.loaded),peer_seats=sorted(room.peers))
    if stage=='running':report['fault']['after_frame']=request['disconnect_after_frame']
    publish('server-fault.json',report['fault']);peer.close()
async def run():
    config=load_config(request['config']);assert config.listen_host=='127.0.0.1' and not config.allow_insecure_loopback
    ready=False
    def on_ready(address):
        nonlocal ready
        assert address[0]=='127.0.0.1' and address[1]==config.listen_port
        ready=True;publish('server-ready.json',dict(address=list(address[:2]),pid=__import__('os').getpid()))
    running=asyncio.create_task(host.run(config,on_ready=on_ready));began=time.monotonic()
    probe=asyncio.create_task(timing.loop_probe()) if timing else None
    status_writer=AsyncStatusPublisher(timing)
    try:
        while not (output/'server-stop').exists():
            if running.done():await running;raise AssertionError('host ended before explicit stop')
            assert time.monotonic()-began<request['timeout'],'owned host deadline'
            if ready:
                inject_disconnect()
                status=timing.call('status_view',view) if timing else view()
                await status_writer.call(publish,'server-live.jsonl',status)
            await asyncio.sleep(.5 if request.get('custom_soak') else .1)
    finally:
        running.cancel()
        try:
            result=await asyncio.wait_for(asyncio.gather(running,return_exceptions=True),30)
            assert len(result)==1 and isinstance(result[0],asyncio.CancelledError),'host did not finish its original cancellation cleanup'
        finally:
            try:
                if probe:
                    probe.cancel();probe_result=await asyncio.gather(probe,return_exceptions=True)
                    assert isinstance(probe_result[0],asyncio.CancelledError),'timing loop ended unexpectedly'
                    report['timing_probe_drained']=True
            finally:
                status_writer.close();report['status_writer_drained']=True
    report['final_state']=view();report['authenticated']=authenticated;report['store_instances']=len(stores)
    await asyncio.sleep(0)  # Drain observations of completed cleanup tasks.
    report['workers']=workers.report()
    recovering=bool(request.get('recover_stage') or request.get('network_outage')) and not request.get('pending_load_quit')
    expected=[p['player_id'] for p in fixture['identities']]+(
        [p['player_id'] for p in fixture['identities']] if request.get('network_outage') else
        [fixture['identities'][0]['player_id']] if recovering else [])
    assert ready and len(servers)==1 and len(stores)==(0 if rc_open else 1) and sorted(authenticated)==sorted(expected)
    # Parent qualifies exact native worker exit/cancellation against the original
    # host audit journal. This driver only claims every child has been reaped.
    assert len(workers)==(22 if request.get('custom_soak') else 3 if recovering or request.get('custom_rematch') else 2) and all(row['reaped'] for row in report['workers'])
    if request.get('network_outage'):assert report['recovery_sessions']==dict(both_replaced=True)
    elif recovering:assert report.get('fault') and report['recovery_sessions']==dict(survivor_retained=True,victim_replaced=True)
    if request.get('pending_load_quit'):assert report.get('fault') and len(report['frozen_matches'])==1
    assert all(Path(row['executable']).resolve()==(package/'program/runtime/python.exe').resolve() for row in report['workers'])
    assert all(Path(row['module_root']).resolve()==(package/'program/app').resolve() for row in report['workers'])
    with socket.socket() as probe:assert probe.connect_ex(('127.0.0.1',config.listen_port))!=0,'host listener survived stop'
    from server.state_lock import exclusive_state
    with exclusive_state(config.data_directory):pass
    report['listener_closed']=True;report['state_lock_released']=True
try:
    for module in (host,worker_client,sys.modules['server.dedicated_server'],sys.modules['server.credentials'],sys.modules['server.tls_transport'],sys.modules['server.host_audit']):
        path=Path(module.__file__).resolve();assert path.is_relative_to(package/'program/app')
        report['production_modules'][module.__name__]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():assert time.monotonic()<deadline;time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    if not real_credentials and not rc_open:host.CredentialStore=MemoryStore
    else:assert host.CredentialStore is original_store
    host.DedicatedServer=server;worker_client.SimulationWorker.create=staticmethod(create)
    asyncio.run(run());report['passed']=True
except BaseException as error:
    if real_credentials:report['error_type']=type(error).__name__
    else:report.update(error=repr(error),traceback=traceback.format_exc())
finally:
    worker_client.subprocess.Popen=original_popen
    report['worker_audit_launches']=worker_audit_launches
    report['worker_audit_pids']=worker_audit_pids
    host.CredentialStore=original_store;host.DedicatedServer=original_server
    report['queued_audits']=[audit.status() for audit in original_audits if getattr(type(audit),'ASYNCHRONOUS',False)]
    for observer in stage_observers:observer.detach()
    if gc_observer:
        publish('gc-timing.json',gc_observer.detach())
        report['audit_stages_detached']=len(stage_observers)==1
    if timing:publish('server-timing.json',timing.report())
    publish('server-driver.json',report)
raise SystemExit(0 if report['passed'] else 1)
'''

CLIENT=r'''
import ctypes,hashlib,json,subprocess,sys,time,traceback
from pathlib import Path
from client_patch.transport import client,launcher,rc_setup
from server.credentials import parse_credential_handoff
from tools.package_integrity import verify
request=json.loads(Path(sys.argv[1]).read_bytes());output=Path(request['output']);package=Path(request['package']);game=Path(request['game'])
real_credentials=bool(request.get('real_credentials'))
rc_open=bool(request.get('rc_open'))
raw=sys.stdin.buffer.read(4097)
fixture=json.loads(raw) if real_credentials or rc_open else parse_credential_handoff(raw)
if real_credentials or rc_open:assert set(fixture)=={'player_id'}
verify(package,'client')
report=dict(passed=False,production_modules={},invite_reads=0,tls_connections=0,credential_fixture=not (real_credentials or rc_open));process=None
original_connect=launcher.tls.open_verified_connection
original_invite=launcher.read_credential_file
def invite(path):
    assert Path(path).resolve()==Path(request['invite_placeholder']).resolve()
    report['invite_reads']+=1
    if real_credentials:
        value=original_invite(path);assert value['player_id']==fixture['player_id']
        report['production_private_reader_verified']=True;return value
    return fixture
async def connect(host,port,context,**kwargs):
    assert host=='127.0.0.1' and port==request['port']
    if rc_open:assert context.verify_certificate is False and not context.context.check_hostname
    report['tls_connections']+=1
    return await original_connect(host,port,context,**kwargs)
def spawn(config,remote,options,child):
    global process
    assert config['local_profile']==request['profile'] and config['game_directory']==game
    command=launcher.game_arguments(config,None,child.fileno(),options)
    assert '-unified-client' in command and '-public-queue-experimental' in command and '-local-cosmetics-experimental' in command
    assert not any(any(word in value.partition('=')[0].casefold() for word in ('smoke','audit','capture','proof','export','auto-')) for value in command if value.startswith('-'))
    ordinary=list(command);command[command.index('-logFile')+1]=str(output/'game.log')
    diagnostic=['-lan-smoke','-lan-audit','-dedicated-surrender-smoke','-dedicated-surrender-frame=1200',
        '-native-quit-smoke','-native-quit-mode=confirm','-native-quit-gate-smoke']
    if request.get('custom_rematch'):
        diagnostic.extend(['-community-match-'+('host' if request['index']==0 else 'guest')+'-smoke',
            '-community-match-deck-smoke','-community-match-leave-quit-smoke'])
        if not request.get('custom_start_rejection'):diagnostic.append('-community-match-duplicate-smoke')
        if request.get('custom_soak'):diagnostic.append('-community-match-soak-smoke')
    else:
        diagnostic.extend(['-public-queue-smoke','-public-queue-smoke-mode='+str(request['mode']),'-public-queue-smoke-gate='+request['gate'],
            '-dedicated-rematch-smoke','-public-team-surrender-smoke','-match-search-smoke'])
        if request['index']%2==1 or request.get('cancel_waiting'):diagnostic.append('-public-queue-smoke-edit-deck')
    if request.get('cancel_waiting'):
        assert request['mode'] in (1,2,5) and request['index']==0 and rc_open and not request.get('recover_stage')
        diagnostic.extend(['-public-queue-smoke-cancel=waiting','-public-queue-smoke-retry','-public-queue-smoke-retry-gate'])
    if request.get('recover_stage'):
        diagnostic.extend(['-public-queue-smoke-retry','-public-queue-smoke-retry-gate','-public-team-retry-smoke'])
        if (request['index']==0 or request.get('network_outage')) and not request.get('pending_load_quit'):
            diagnostic.append('-dedicated-recovery-smoke')
    if request.get('pending_load_quit') and request['index']==0:
        assert request.get('recover_stage')=='loading' and request['mode']==1 and not rc_open
        diagnostic=[value for value in diagnostic if not value.startswith('-native-quit-')]
        diagnostic.append('-dedicated-pending-load-quit-smoke')
    command.extend(diagnostic)
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=1 if request['visible'] else 0
    info.lpAttributeList={'handle_list':[child.fileno()]}
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong;tick=clock()
    try:
        child.set_inheritable(True);process=subprocess.Popen(command,cwd=game,startupinfo=info,close_fds=True,
            creationflags=0x00000004 if request.get('prelaunch_observer') else 0)
    finally:child.set_inheritable(False)
    row=dict(pid=process.pid,launch_tick=tick,ordinary_arguments=ordinary,diagnostic_arguments=diagnostic,actual_arguments=command,
             suspended_for_observer=bool(request.get('prelaunch_observer')))
    temporary=output/'game-process.tmp';temporary.write_text(json.dumps(row,indent=2)+'\n');temporary.rename(output/'game-process.json')
    return process
try:
    for module in (client,launcher,rc_setup,sys.modules['client_patch.transport.bridge'],sys.modules['server.credentials'],sys.modules['tools.package_integrity']):
        path=Path(module.__file__).resolve();assert path.is_relative_to(package/'program/app')
        report['production_modules'][module.__name__]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():assert time.monotonic()<deadline;time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    launcher.spawn_game=spawn;launcher.read_credential_file=invite;launcher.tls.open_verified_connection=connect
    report['launcher_exit_code']=client.main(['--config',request['config']])
    report['game_exit_code']=None if process is None else process.poll()
    assert report['launcher_exit_code']==report['game_exit_code']==0
    expected=2 if request.get('recover_stage') and (request['index']==0 or request.get('network_outage')) and not request.get('pending_load_quit') else 1
    if request.get('network_outage'):
        assert 2<=report['tls_connections']<=8 and report['invite_reads']==report['tls_connections']
    else:
        assert report['tls_connections']==expected and report['invite_reads']==(0 if rc_open else expected)
    report['passed']=True
except BaseException as error:
    if real_credentials:report['error_type']=type(error).__name__
    else:report.update(error=repr(error),traceback=traceback.format_exc())
finally:(output/'client-driver.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
'''
