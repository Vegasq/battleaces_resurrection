"""External qualification adapters only; never included in a player package.

Restricted-token DACL enrollment stays unqualified. Ephemeral test identities
arrive only over each owned child's stdin, never a command line or disk file.
"""

SERVER=r'''
import asyncio,hashlib,json,secrets,socket,sys,time,traceback
from pathlib import Path
from server import host,worker_client
from server.credentials import AuthenticationError
from server.configuration import load_config
from tools.package_integrity import verify
request=json.loads(Path(sys.argv[1]).read_bytes());output=Path(request['output']);package=Path(request['package'])
fixture=json.loads(sys.stdin.buffer.read(16385));assert len(fixture['identities'])==2
verify(package,'server');report=dict(passed=False,production_modules={},fixture_store=True,workers=[],frozen_matches=[])
workers=[];servers=[];authenticated=[];stores=[];old_sessions={}
def publish(name,value):
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
async def create(*args,**kwargs):
    worker=await original_create(*args,**kwargs);workers.append(worker);return worker
def server(*args,**kwargs):
    value=original_server(*args,**kwargs);servers.append(value);original_audit=value.audit
    def observe(event,**fields):
        original_audit(event,**fields)
        if event=='match_created':
            room=value.rooms[fields['room']];match=room.match
            report['frozen_matches'].append(dict(match=fields['match'],game_data_sha256=match.raw_sha256,
                humans={slot:dict(profile=peer.profile_id,name=peer.name) for slot,peer in room.peers.items()},
                roster=[dict(slot=p.slot,name=p.name,ai_profile_id=p.ai_profile_id) for p in match.roster],
                decks={slot:list(deck) for slot,deck in match.decks_by_slot.items()},
                full_loadout_seats=sorted(room.full_loadout_seats)))
            if request.get('recover_loading') and len(report['frozen_matches'])==2:
                victim,survivor=(p['player_id'] for p in fixture['identities'])
                report['recovery_sessions']=dict(survivor_retained=value.community.sessions[survivor] is old_sessions[survivor],
                    victim_replaced=value.community.sessions[victim] is not old_sessions[victim])
    value.audit=observe;return value
def view():
    if not servers:return {}
    value=servers[0]
    return dict(rooms=len(value.rooms),retired=len(value.retired),entries=len(value.community.public.entries),
                offers=len(value.community.public.offers),cleanup=len(value.worker_cleanup),sessions=len(value.community.sessions))
def inject_loading_disconnect():
    command=output/'server-disconnect.json'
    if not request.get('recover_loading') or report.get('fault') or not command.exists():return
    victim,survivor=(p['player_id'] for p in fixture['identities'])
    assert json.loads(command.read_bytes())==dict(player=victim)
    value=servers[0];session=value.community.sessions[victim];peer=session.peer;room=peer.room
    assert room and room.state=='loading' and not room.loaded and room.frame==0 and len(room.peers)==2
    assert len(report['frozen_matches'])==1 and room.sim is not None
    old_sessions.update({p:value.community.sessions[p] for p in (victim,survivor)})
    report['fault']=dict(stage='loading',match=room.match_id,victim=victim,victim_seat=peer.slot,worker_pid=room.sim.pid,
                        room_state=room.state,next_frame=room.frame,loaded=sorted(room.loaded))
    publish('server-fault.json',report['fault']);peer.close()
async def run():
    config=load_config(request['config']);assert config.listen_host=='127.0.0.1' and not config.allow_insecure_loopback
    ready=False
    def on_ready(address):
        nonlocal ready
        assert address[0]=='127.0.0.1' and address[1]==config.listen_port
        ready=True;publish('server-ready.json',dict(address=list(address[:2]),pid=__import__('os').getpid()))
    running=asyncio.create_task(host.run(config,on_ready=on_ready));began=time.monotonic()
    try:
        while not (output/'server-stop').exists():
            if running.done():await running;raise AssertionError('host ended before explicit stop')
            assert time.monotonic()-began<request['timeout'],'owned host deadline'
            if ready:inject_loading_disconnect();publish('server-live.json',view())
            await asyncio.sleep(.1)
    finally:
        running.cancel()
        result=await asyncio.wait_for(asyncio.gather(running,return_exceptions=True),30)
        assert len(result)==1 and isinstance(result[0],asyncio.CancelledError),'host did not finish its original cancellation cleanup'
    report['final_state']=view();report['authenticated']=authenticated;report['store_instances']=len(stores)
    for worker in workers:
        report['workers'].append(dict(pid=worker.pid,exit_code=worker.process.poll(),failure=worker.failure,
            reaped=worker.process.poll() is not None and worker._cleanup_task is not None and worker._cleanup_task.done() and not worker._stderr_thread.is_alive(),
            executable=worker.process.args[0],module_root=worker.process.args[7],game_data_sha256=worker.game_data_sha256,
            simulation_sha256=worker.dll_sha256,ai=worker.ai_info))
    recovering=request.get('recover_loading',False)
    expected=[p['player_id'] for p in fixture['identities']]+([fixture['identities'][0]['player_id']] if recovering else [])
    assert ready and len(servers)==1 and len(stores)==1 and sorted(authenticated)==sorted(expected)
    assert len(workers)==(3 if recovering else 2) and all(row['exit_code']==0 and not row['failure'] and row['reaped'] for row in report['workers'])
    if recovering:assert report.get('fault') and report['recovery_sessions']==dict(survivor_retained=True,victim_replaced=True)
    assert all(Path(row['executable']).resolve()==(package/'program/runtime/python.exe').resolve() for row in report['workers'])
    assert all(Path(row['module_root']).resolve()==(package/'program/app').resolve() for row in report['workers'])
    with socket.socket() as probe:assert probe.connect_ex(('127.0.0.1',config.listen_port))!=0,'host listener survived stop'
    from server.state_lock import exclusive_state
    with exclusive_state(config.data_directory):pass
    report['listener_closed']=True;report['state_lock_released']=True
try:
    for module in (host,worker_client,sys.modules['server.dedicated_server'],sys.modules['server.credentials'],sys.modules['server.tls_transport']):
        path=Path(module.__file__).resolve();assert path.is_relative_to(package/'program/app')
        report['production_modules'][module.__name__]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():assert time.monotonic()<deadline;time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    host.CredentialStore=MemoryStore;host.DedicatedServer=server;worker_client.SimulationWorker.create=staticmethod(create)
    asyncio.run(run());report['passed']=True
except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
finally:
    host.CredentialStore=original_store;host.DedicatedServer=original_server
    publish('server-driver.json',report)
raise SystemExit(0 if report['passed'] else 1)
'''

CLIENT=r'''
import ctypes,hashlib,json,subprocess,sys,time,traceback
from pathlib import Path
from client_patch.transport import client,launcher
from server.credentials import parse_credential_handoff
from tools.package_integrity import verify
request=json.loads(Path(sys.argv[1]).read_bytes());output=Path(request['output']);package=Path(request['package']);game=Path(request['game'])
fixture=parse_credential_handoff(sys.stdin.buffer.read(4097));verify(package,'client')
report=dict(passed=False,production_modules={},invite_reads=0,tls_connections=0,credential_fixture=True);process=None
original_connect=launcher.tls.open_verified_connection
def invite(path):
    assert Path(path).resolve()==Path(request['invite_placeholder']).resolve()
    report['invite_reads']+=1;return fixture
async def connect(host,port,context,**kwargs):
    assert host=='127.0.0.1' and port==request['port']
    report['tls_connections']+=1
    return await original_connect(host,port,context,**kwargs)
def spawn(config,remote,options,child):
    global process
    assert config['local_profile']==request['profile'] and config['game_directory']==game
    command=launcher.game_arguments(config,None,child.fileno(),options)
    assert '-unified-client' in command and '-public-queue-experimental' in command and '-local-cosmetics-experimental' in command
    assert not any(any(word in value.partition('=')[0].casefold() for word in ('smoke','audit','capture','proof','export','auto-')) for value in command if value.startswith('-'))
    ordinary=list(command);command[command.index('-logFile')+1]=str(output/'game.log')
    diagnostic=['-public-queue-smoke','-public-queue-smoke-mode='+str(request['mode']),'-public-queue-smoke-gate='+request['gate'],
        '-lan-smoke','-lan-audit','-dedicated-rematch-smoke','-dedicated-surrender-smoke','-dedicated-surrender-frame=1200',
        '-public-team-surrender-smoke','-match-search-smoke','-native-quit-smoke','-native-quit-mode=confirm','-native-quit-gate-smoke']
    if request['index']==1:diagnostic.append('-public-queue-smoke-edit-deck')
    if request.get('recover_loading'):
        diagnostic.extend(['-public-queue-smoke-retry','-public-queue-smoke-retry-gate','-public-team-retry-smoke'])
        if request['index']==0:diagnostic.append('-dedicated-recovery-smoke')
    command.extend(diagnostic)
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=1 if request['visible'] else 0
    info.lpAttributeList={'handle_list':[child.fileno()]}
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong;tick=clock()
    try:
        child.set_inheritable(True);process=subprocess.Popen(command,cwd=game,startupinfo=info,close_fds=True)
    finally:child.set_inheritable(False)
    row=dict(pid=process.pid,launch_tick=tick,ordinary_arguments=ordinary,diagnostic_arguments=diagnostic,actual_arguments=command)
    temporary=output/'game-process.tmp';temporary.write_text(json.dumps(row,indent=2)+'\n');temporary.rename(output/'game-process.json')
    return process
try:
    for module in (client,launcher,sys.modules['client_patch.transport.bridge'],sys.modules['tools.package_integrity']):
        path=Path(module.__file__).resolve();assert path.is_relative_to(package/'program/app')
        report['production_modules'][module.__name__]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():assert time.monotonic()<deadline;time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    launcher.spawn_game=spawn;launcher.read_credential_file=invite;launcher.tls.open_verified_connection=connect
    report['launcher_exit_code']=client.main(['--config',request['config']])
    report['game_exit_code']=None if process is None else process.poll()
    assert report['launcher_exit_code']==report['game_exit_code']==0
    expected=2 if request.get('recover_loading') and request['index']==0 else 1
    assert report['invite_reads']==report['tls_connections']==expected
    report['passed']=True
except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
finally:(output/'client-driver.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
'''
