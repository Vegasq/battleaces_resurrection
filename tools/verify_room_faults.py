"""Owned packaged RC/native two-room crash and unresponsive-worker controls.

Only this diagnostic duplicates newly returned process/thread handles and
deliberately kills or suspends the selected owned worker. Production API results,
timeouts and simulation implementation remain unchanged. No game UI/SCM proof.
"""
from __future__ import annotations
import argparse,asyncio,contextlib,ctypes as c,hashlib,io,json,os,secrets
from ctypes import wintypes as w
from pathlib import Path
import subprocess,sys,time,traceback

ROOT=Path(__file__).resolve().parents[1]
def require(value,message):
    if not value:raise AssertionError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    temporary=path.with_name(path.name+'.staging');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(path)

class WorkerThread:
    """Duplicate only handles returned by the observed worker's CreateProcess."""
    def __init__(self,raw):
        self.pid,self.tid=raw[2:];self.process=self.thread=None;self.suspended=False
        self.k=c.WinDLL('kernel32',use_last_error=True)
        declarations={'GetCurrentProcess':([],w.HANDLE),'DuplicateHandle':([w.HANDLE,w.HANDLE,w.HANDLE,c.POINTER(w.HANDLE),w.DWORD,w.BOOL,w.DWORD],w.BOOL),
            'CloseHandle':([w.HANDLE],w.BOOL),'GetProcessId':([w.HANDLE],w.DWORD),'GetThreadId':([w.HANDLE],w.DWORD),
            'GetProcessIdOfThread':([w.HANDLE],w.DWORD),'GetThreadTimes':([w.HANDLE]+[c.POINTER(w.FILETIME)]*4,w.BOOL),
            'GetProcessTimes':([w.HANDLE]+[c.POINTER(w.FILETIME)]*4,w.BOOL),'WaitForSingleObject':([w.HANDLE,w.DWORD],w.DWORD),
            'IsProcessInJob':([w.HANDLE,w.HANDLE,c.POINTER(w.BOOL)],w.BOOL),'SuspendThread':([w.HANDLE],w.DWORD),'ResumeThread':([w.HANDLE],w.DWORD)}
        for name,(args,result) in declarations.items():fn=getattr(self.k,name);fn.argtypes,fn.restype=args,result
        try:
            self.process=self.duplicate(raw[0],0x100000|0x1000)
            self.thread=self.duplicate(raw[1],0x42)
            self.identity=self.identify()
        except BaseException:self.close();raise
    def duplicate(self,handle,access):
        value=w.HANDLE();current=self.k.GetCurrentProcess()
        require(self.k.DuplicateHandle(current,handle,current,c.byref(value),access,False,0),'owned duplicate failed');return value.value
    def identify(self):
        require(self.k.GetProcessId(self.process)==self.pid and self.k.GetThreadId(self.thread)==self.tid and self.k.GetProcessIdOfThread(self.thread)==self.pid,'owned process/thread identity differs')
        times=[]
        for fn,handle in ((self.k.GetProcessTimes,self.process),(self.k.GetThreadTimes,self.thread)):
            values=[w.FILETIME() for _ in range(4)];require(fn(handle,*[c.byref(v) for v in values]),'owned creation time unavailable')
            times.append(values[0].dwHighDateTime<<32|values[0].dwLowDateTime)
        require(all(times),'owned creation time absent')
        return dict(pid=self.pid,tid=self.tid,process_creation_filetime=times[0],thread_creation_filetime=times[1])
    def validate(self,worker):
        require(worker.pid==self.pid and not worker._test_backend and worker.process.poll() is None and self.identify()==self.identity,'live real worker identity differs')
        member=w.BOOL();require(worker._job and worker._job.handle and self.k.IsProcessInJob(self.process,worker._job.handle,c.byref(member)) and member.value,'worker is not in its owned job')
        require(self.k.WaitForSingleObject(self.process,0)==258,'owned worker is not live')
    def suspend(self,worker):
        self.validate(worker);require(not self.suspended,'worker already suspended')
        count=self.k.SuspendThread(self.thread)
        if count not in (0,0xffffffff):
            # Undo only OUR increment. Never drain an earlier suspension owned
            # by someone else, or leave our extra increment behind on refusal.
            require(self.k.ResumeThread(self.thread)==count+1,'owned suspend rollback differs')
        if count==0:self.suspended=True
        require(count==0,'expected unsuspended primary thread');return count
    def close(self):
        if self.suspended and self.process and self.k.WaitForSingleObject(self.process,0)==258:
            require(self.k.ResumeThread(self.thread)==1,'owned fault cleanup resume differs');self.suspended=False
        for name in ('thread','process'):
            handle=getattr(self,name,None)
            if handle:require(self.k.CloseHandle(handle),'owned query handle close failed');setattr(self,name,None)

class Capture:
    def __init__(self):self.refs={};self.errors=[];self.original=subprocess.Popen
    def popen(self,args,*positional,**keywords):
        import _winapi
        if not (isinstance(args,list) and args[0]==sys.executable and '--stdio' in args and '--test-backend' not in args):return self.original(args,*positional,**keywords)
        original=_winapi.CreateProcess;expected=subprocess.list2cmdline(args)
        def create(*values):
            raw=original(*values)
            if values[1]==expected:
                ref=None
                try:
                    ref=WorkerThread(raw);require(ref.pid not in self.refs,'duplicate worker process identity');self.refs[ref.pid]=ref
                except BaseException as error:
                    self.errors.append(type(error).__name__)
                    if ref:
                        try:ref.close()
                        except BaseException:self.errors.append('capture_cleanup')
            return raw  # Never alter the original process/thread handles or flags.
        _winapi.CreateProcess=create
        try:return self.original(args,*positional,**keywords)
        finally:_winapi.CreateProcess=original
    def close(self):
        for ref in self.refs.values():ref.close()

class Peer:
    def __init__(self,reader,writer):self.reader,self.writer=reader,writer;self.observed=[];self.identity=self.join=None;self.request=0;self.profile=self.lobby_id=self.room_key=None;self.ticket=0;self.public_states=[];self.frame_kind=14
    async def send(self,kind,body=b''):
        from server import protocol as p
        self.writer.write(p.encode(kind,body));await self.writer.drain()
    async def receive(self,expected):
        from server import protocol as p,community_protocol as community,loadout_protocol as loadout,public_protocol as public
        async with asyncio.timeout(8):
            for _ in range(128):
                kind,body=await p.receive(self.reader);self.observed.append((kind,body))
                if kind==public.STATE:self.public_states.append(public.decode_state(body))
                if kind==expected:return body
                require(kind in (p.LOBBY,p.NOTICE,p.MATCH_INFO,community.DIRECTORY,community.DIRECTORY_PORTRAITS,community.LOBBY,community.INVITATION,loadout.LOBBY_LOADOUT,public.STATE),'unexpected peer packet')
        raise AssertionError('peer message budget')
    async def command(self,kind,body=b''):
        from server import community_protocol as community
        import struct
        self.request+=1;await self.send(kind,struct.pack('<I',self.request)+body)
        r=community.Reader(await self.receive(community.ACK))
        require((r.number('I'),r.number('B'))==(self.request,kind),'command acknowledgement differs')
        accepted,reason,identity=r.flag(),r.text(),r.text();r.end()
        require(accepted,'community command refused: '+reason);return identity
    async def public_command(self,kind,**fields):
        from server import public_protocol as public
        body=public.command(kind,self.request+1,self.ticket,**fields)
        return await self.command(kind,body[4:])
    async def public_phase(self,phase,*,match=None):
        from server import public_protocol as public
        async with asyncio.timeout(8):
            while True:
                candidates=[s for s in self.public_states if s['ticket']==self.ticket and s['phase']==phase and (match is None or s['match']==match)]
                if candidates:return candidates[-1]
                await self.receive(public.STATE)
    async def close(self):
        self.writer.close()
        try:await asyncio.wait_for(self.writer.wait_closed(),2)
        except (OSError,TimeoutError):self.writer.transport.abort()

async def pair(port,room,tokens,peers,*,server=None,custom=False,public_mode=False,existing=None):
    from server import protocol as p,tls_transport as tls,admission,community_protocol as community,loadout_protocol as loadout,public_protocol as public
    import struct
    from server.game_data import decompress_game_data
    from server.protobuf_wire import get_bytes,get_repeated_bytes,get_uint,field_bytes,field_uint
    result=list(existing or [])
    for slot,token in enumerate(tokens if not existing else []):
        reader,writer=await tls.open_verified_connection('127.0.0.1',port,tls.rc_client_context('127.0.0.1'))
        peer=Peer(reader,writer);peers.append(peer);result.append(peer)
        profile=await admission.authenticate_client(reader,writer,token,rc_open=True)
        peer.profile=profile;peer.room_key=room
        if custom or public_mode:
            await peer.send(community.HELLO,community.hello(profile,'Fault Player '+str(slot),version=community.PORTRAIT_VERSION))
            r=community.Reader(await peer.receive(community.WELCOME))
            require((r.number('H'),r.number('H'),r.key())==(2,p.VERSION,profile),'current community identity differs');r.deck();r.end()
            await peer.command(loadout.SET_LOADOUT,struct.pack('<H',loadout.VERSION)+p.deck_bytes(server.template.default_decks[slot])+loadout.encode(server.cosmetic_catalog.normalize_local()))
        else:
            await peer.send(p.HELLO,p.hello(slot,profile,'Fault Player '+str(slot),room))
            assigned,window,deck=p.decode_welcome(await peer.receive(p.WELCOME));require(assigned==slot and window==6,'peer seat/window differs')
    if public_mode:
        for slot,peer in enumerate(result):
            peer.ticket+=1
            await peer.public_command(loadout.ENTER_LOADOUT,mode=1,deck=server.template.default_decks[slot],cosmetics=server.cosmetic_catalog.normalize_local(),wait_ms=30000)
        offered=await asyncio.gather(*(peer.public_phase(public.OFFERED) for peer in result))
        require(offered[0]['match']==offered[1]['match'] and bool(offered[0]['match']),'public proposals differ')
        match=offered[0]['match']
        await asyncio.gather(*(peer.public_command(public.READY,match=match) for peer in result))
        for slot,peer in enumerate(result):
            assignment=public.decode_assignment(await peer.receive(loadout.MATCH_LOADOUT),complete=True)
            require(assignment['match']==match and assignment['generation']==peer.ticket and assignment['mode']==1 and assignment['slot']==slot and assignment['human_mask']==3 and assignment['count']==2 and assignment['input_window']==6,'public human assignment differs')
            require(assignment['deck']==list(server.template.default_decks[slot]),'public frozen deck differs')
            assignment['cosmetics'].validate(server.cosmetic_catalog)
            peer.room_key='public_'+match;peer.frame_kind=public.FRAME
        matches=[match.encode('ascii')]*2
    elif custom:
        if not existing:
            lobby_id=await result[0].command(community.CREATE,b'\x01')
            invitation=await result[0].command(community.INVITE,p.encode_string(result[1].profile))
            require(await result[1].command(community.REPLY,p.encode_string(invitation)+b'\x01')==lobby_id,'invitation target differs')
            for peer in result:peer.lobby_id=lobby_id;peer.room_key='custom_'+lobby_id
        lobby=server.community.lobbies[result[0].lobby_id]
        require(lobby.phase==community.OPEN and len(lobby.members)==2,'custom lobby not reusable')
        await result[0].command(community.START,p.encode_string(lobby.id)+struct.pack('<Q',lobby.revision))
        await result[1].command(community.READY,p.encode_string(lobby.id)+struct.pack('<IB',lobby.epoch,1))
        for slot,peer in enumerate(result):
            assigned,window,deck=p.decode_welcome(await peer.receive(p.WELCOME));require(assigned==slot and window==6 and deck==list(server.template.default_decks[slot]),'custom seat/deck differs')
    else:await asyncio.gather(*(peer.send(p.LOBBY_READY,b'\x01') for peer in result))
    if not public_mode:matches=await asyncio.gather(*(peer.receive(p.MATCH_INFO) for peer in result));require(matches[0]==matches[1],'match IDs differ')
    bootstraps=await asyncio.gather(*(peer.receive(p.BOOTSTRAP) for peer in result));require(bootstraps[0]==bootstraps[1],'native bootstraps differ')
    config=get_bytes(decompress_game_data(bootstraps[0]),1,required=True)
    armies={get_uint(a,1):a for a in get_repeated_bytes(config,2)};require(set(armies)=={0,1},'native human roster differs')
    for slot,peer in enumerate(result):
        army=armies[slot];deck=get_bytes(army,3,required=True);peer.identity=get_bytes(army,2,required=True)
        join=field_uint(1,slot)+field_bytes(2,deck)
        for target,source in ((3,5),(4,6)):
            value=get_uint(army,source)
            if value:join+=field_uint(target,value)
        peer.join=field_bytes(3,join)
    await asyncio.gather(*(peer.send(p.LOADED,hashlib.sha256(bootstraps[0]).digest()) for peer in result))
    require(await asyncio.gather(*(peer.receive(p.START) for peer in result))==[b'',b''],'native start differs')
    return result,matches[0].decode('ascii')

async def advance(peers,frame):
    from server import protocol as p
    from server.game_data import encode_player_input
    await asyncio.gather(*(peer.send(p.INPUT,__import__('struct').pack('<I',frame)+encode_player_input(peer.identity,[peer.join] if frame==0 else [])) for peer in peers))
    values=await asyncio.gather(*(peer.receive(peer.frame_kind) for peer in peers))
    require(values[0]==values[1] and __import__('struct').unpack_from('<I',values[0])[0]==frame,'native frames differ')
    if peers[0].frame_kind!=p.FRAME:
        from server import public_protocol as public
        require(public.decode_frame(values[0],2)[0]==frame,'public frame structure differs')
    return dict(frame=frame,at=time.perf_counter(),sha256=hashlib.sha256(values[0]).hexdigest())

async def scenario(folder,assets,kind,capture,*,custom=False,public_mode=False):
    from server import protocol as p,dedicated_server as dedicated,admission,tls_transport as tls,rc_host,community_protocol as community,public_protocol as public
    from server.game_data import GameTemplate
    from server.cosmetics import CosmeticCatalog
    from server.profiles import ProfileStore
    from server.worker_client import SimulationWorker
    from server.host_audit import HostAudit
    folder.mkdir();work=folder/'workers';work.mkdir()
    certificate,key=rc_host.generate_certificate();cert=folder/'server.pem';keypath=folder/'server.key';cert.write_bytes(certificate);keypath.write_bytes(key)
    template=GameTemplate.load(assets/'map-1v1.pb.gz',catalog_path=assets/'unit-catalog.json',descriptors_path=assets/'descriptors')
    workers=[]
    async def factory(data,*,ai=None):
        worker=await SimulationWorker.create(data,assets/'Simulation.dll',working_directory=work,ai=ai)
        workers.append(worker);require(worker.pid in capture.refs and not capture.errors,'worker primary-thread capture failed')
        require(worker.dll_sha256==p.SIM_SHA and worker.game_data_sha256==hashlib.sha256(data).hexdigest() and not worker._test_backend,'real native worker inputs differ')
        return worker
    extra={}
    if public_mode:
        from server.worker_ai import AISetup
        from server.ai_rules import RuleBook
        from server.bot_catalog import BotCatalog
        async def ai_factory(data,bots):return await factory(data,ai=AISetup(assets,bots))
        templates={1:template}
        for mode,name in ((2,'map-2v2.pb.gz'),(5,'map-2vai.pb.gz')):templates[mode]=GameTemplate.load(assets/name,catalog_path=assets/'unit-catalog.json',descriptors_path=assets/'descriptors')
        extra=dict(templates=templates,bot_catalog=BotCatalog(assets,template=template,rules=RuleBook(assets)),ai_factory=ai_factory)
    audit=HostAudit(folder/'logs',max_bytes=8388608,backups=4,diagnostics=True);server=dedicated.DedicatedServer(template,ProfileStore(folder/'profiles',template,catalog=CosmeticCatalog(assets)),sim_factory=factory,audit=audit,audit_state=True,tls_context=tls.load_server_context(cert,keypath),admission=admission.AdmissionController(None,rc_open=True),**extra)
    peers=[];healthy_task=None;healthy_stop=asyncio.Event();healthy_frames=[];record=dict(kind=kind,passed=False,route='public' if public_mode else 'custom' if custom else 'direct')
    try:
        port=(await server.start('127.0.0.1',0))[1]
        tokens=[['ba1_'+secrets.token_urlsafe(32) for _ in range(2)] for _ in range(2)]
        if public_mode:
            victims,match=await pair(port,'victim',tokens[0],peers,server=server,public_mode=True)
            healthy,healthy_match=await pair(port,'healthy',tokens[1],peers,server=server,public_mode=True)
        else:(victims,match),(healthy,healthy_match)=await asyncio.gather(pair(port,'victim',tokens[0],peers,server=server,custom=custom),pair(port,'healthy',tokens[1],peers,server=server,custom=custom))
        victim_key,healthy_key=victims[0].room_key,healthy[0].room_key
        room=server.rooms[healthy_key];healthy_worker=room.sim;victim=server.rooms[victim_key].sim;ref=capture.refs[victim.pid]
        profiles_before={p.name:sha(p) for p in (folder/'profiles').glob('*.json')}
        require(victim.request_timeout==3 and victim.close_timeout==2 and healthy_worker.request_timeout==3,'production deadlines changed')
        ref.validate(victim);capture.refs[healthy_worker.pid].validate(healthy_worker)
        async def pump():
            for frame in range(240):
                if healthy_stop.is_set() and frame>=40:return
                healthy_frames.append(await advance(healthy,frame))
            raise AssertionError('healthy room frame budget exceeded')
        healthy_task=asyncio.create_task(pump())
        for frame in range(10):await advance(victims,frame)
        fault_at=time.perf_counter();record.update(victim_pid=victim.pid,healthy_pid=healthy_worker.pid,thread_identity=ref.identity,fault_at=fault_at,request_timeout=3,close_timeout=2)
        if kind=='crash':ref.validate(victim);victim.process.kill();record['injected_termination']=True
        else:record['suspend_previous_count']=ref.suspend(victim)
        await asyncio.gather(*(peer.send(p.INPUT,__import__('struct').pack('<I',10)+__import__('server.game_data',fromlist=['encode_player_input']).encode_player_input(peer.identity,[])) for peer in victims))
        errors=await asyncio.gather(*(peer.receive(community.ABORTED if custom or public_mode else p.ERROR) for peer in victims));abort_at=time.perf_counter()
        if custom or public_mode:
            for body in errors:
                r=community.Reader(body);require((r.text(),r.text())==(match,'server simulation error'),'custom abort differs');r.end()
        else:require(errors==[b'server simulation error']*2,'victim did not receive explicit unknown-result abort')
        for peer in victims:
            require(not any(k in (peer.frame_kind,p.MATCH_END) and (k==p.MATCH_END or __import__('struct').unpack_from('<I',body)[0]>=10) for k,body in peer.observed),'failed frame or invented result published')
            if not custom and not public_mode:await peer.close()
        async with asyncio.timeout(8):
            while victim_key in server.rooms or victim.process.poll() is None or server.worker_cleanup:await asyncio.sleep(.01)
        require(server.rooms.get(healthy_key) is room and room.sim is healthy_worker and healthy_worker.process.poll() is None,'unrelated room/worker was replaced')
        record.update(victim_exit=victim.process.returncode,abort_seconds=abort_at-fault_at,healthy_frames_during_failure=sum(fault_at<=x['at']<=abort_at for x in healthy_frames))
        if kind=='hang':require(record['abort_seconds']>=2.8 and record['healthy_frames_during_failure']>=20,'default timeout/independent progression not evidenced')
        if public_mode:
            results=await asyncio.gather(*(peer.public_phase(public.RESULTS,match=match) for peer in victims))
            require(all(s['reason']=='server simulation error' for s in results),'public Results reason differs')
            old_tickets=[peer.ticket for peer in victims]
            await asyncio.gather(*(peer.public_command(public.RETURN,match=match) for peer in victims))
            await asyncio.gather(*(peer.public_phase(public.RETIRED,match=match) for peer in victims))
            require(match not in server.community.public.offers and all(peer.profile not in server.community.public.entries for peer in victims),'public return retained old offer/tickets')
            record.update(return_acknowledgements=2,same_connections_reused=True,current_community_version=2,old_tickets=old_tickets,old_offer_retired=True,public_wait_ms=30000)
        elif custom:
            await asyncio.gather(*(peer.command(community.RETURN,p.encode_string(match)) for peer in victims))
            record.update(return_acknowledgements=2,same_connections_reused=True,current_community_version=2)
        replacement,replacement_match=await pair(port,'victim',tokens[0],peers,server=server,custom=custom,public_mode=public_mode,existing=victims if custom or public_mode else None)
        if public_mode:
            record['replacement_tickets']=[peer.ticket for peer in victims]
            require(record['replacement_tickets']==[t+1 for t in old_tickets],'public retry did not advance tickets')
        require(replacement_match!=match,'replacement reused failed match identity')
        for frame in range(10):await advance(replacement,frame)
        profiles_after={p.name:sha(p) for p in (folder/'profiles').glob('*.json')}
        require(profiles_after==profiles_before,'room failure/replacement changed saved profiles')
        record.update(profile_sha256=profiles_before,profiles_preserved=True)
        until=len(healthy_frames)+10
        async with asyncio.timeout(3):
            while len(healthy_frames)<until:await asyncio.sleep(.01)
        healthy_stop.set();await healthy_task;healthy_task=None
        require(room.sim is healthy_worker and healthy_worker.process.poll() is None,'healthy worker did not survive replacement')
        gaps=[(b['at']-a['at'])*1000 for a,b in zip(healthy_frames,healthy_frames[1:])]
        require(gaps and max(gaps)<1000,'unrelated room stalled')
        rows=[json.loads(x) for x in (folder/'logs/events.jsonl').read_text().splitlines()]
        selected=[r for r in rows if r.get('match')==match]
        failed_frames=[r['frame'] for r in selected if r['event']=='frame_queued'];require(failed_frames==list(range(10)),'failed-frame audit differs')
        aborts=[r for r in selected if r['event']=='match_aborted'];require(len(aborts)==1 and aborts[0]['result'] is None and aborts[0]['next_frame']==10,'victim audit invented a result')
        failures=[r for r in selected if r['event']=='simulation_error'];require(len(failures)==1 and failures[0]['error'].startswith('WorkerTimeout(' if kind=='hang' else 'WorkerError('),'worker failure category differs')
        delivered=[r for r in rows if r.get('match')==healthy_match and r['event']=='frame_queued']
        require([r['frame'] for r in delivered]==list(range(len(healthy_frames))) and [r['frame_payload_sha256'] for r in delivered]==[r['sha256'] for r in healthy_frames],'healthy host/client frame journal differs')
        record.update(passed=True,healthy_frames=healthy_frames,max_healthy_gap_ms=max(gaps),replacement_match=replacement_match,replacement_frames=10,failed_frame_not_published=True,unknown_result_abort=True,healthy_same_room_and_worker=True)
    finally:
        healthy_stop.set()
        if healthy_task:healthy_task.cancel();await asyncio.gather(healthy_task,return_exceptions=True)
        for peer in peers:await peer.close()
        try:await server.close()
        finally:
            await asyncio.gather(*(worker.close() for worker in workers),return_exceptions=False);audit.close()
        record['worker_exits']=[dict(pid=worker.pid,exit_code=worker.process.poll()) for worker in workers]
        require(all(row['exit_code'] is not None for row in record['worker_exits']),'owned worker survived scenario')
        require(all(row['exit_code']==0 for row in record['worker_exits'] if row['pid']!=record.get('victim_pid')),'healthy/replacement worker did not close normally')
        save(folder/'result.json',record)
    return record

def child(request_path):
    from tools.package_integrity import verify
    from server.assets import verify_assets
    request=json.loads(request_path.read_bytes());out=request_path.parent;package=Path(request['package']);assets=Path(request['assets'])
    report=dict(passed=False,scope=__doc__,faults_deliberately_injected=True,graphical_recovery_qualified=False,ordinary_entry_qualified=False)
    capture=Capture();started=time.monotonic()
    try:
        require(sha(__file__)==request['driver_sha256'],'driver changed');verify(package,'server');verify_assets(assets)
        from server import worker_client,dedicated_server
        require(Path(worker_client.__file__).resolve()==package/'program/app/server/worker_client.py','bundled imports differ')
        report['module_sha256']={str(Path(m.__file__).resolve()):sha(m.__file__) for m in (worker_client,dedicated_server)}
        deadline=time.monotonic()+20
        while not (out/'job-ready').exists():require(time.monotonic()<deadline,'owned job gate absent');time.sleep(.02)
        subprocess.Popen=capture.popen
        async def execute():return [await scenario(out/kind,assets,kind,capture,custom=request['custom'],public_mode=request.get('public_mode',False)) for kind in ('crash','hang')]
        report['cases']=asyncio.run(execute());require(not capture.errors,'creation observer errors')
        verify_assets(assets);report['assets_verified_after']=True
        report['passed']=True
    except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        subprocess.Popen=capture.original
        capture.close();report['duplicated_handle_pairs_closed']=len(capture.refs)
        report['source_unchanged']=sha(__file__)==request['driver_sha256'];report['passed'] &= report['source_unchanged']
        report['elapsed_seconds']=time.monotonic()-started;save(out/'child-report.json',report)
    return 0 if report['passed'] else 1

def owned_paths(package,assets,out):
    package,assets,out=(Path(p).resolve() for p in (package,assets,out))
    require(os.name=='nt' and all(p.is_relative_to(ROOT/'local') for p in (package,assets,out)),'owned Windows local paths required')
    require(not out.is_relative_to(package) and not out.is_relative_to(assets),'keep diagnostic output outside packages and imported assets')
    return package,assets,out

def run(package,assets,out,*,custom=True,public_mode=False):
    from tools.owned_suspended_launch import SuspendedChild,job_accounting
    from tools.package_integrity import verify
    package,assets,out=owned_paths(package,assets,out);out.mkdir(exist_ok=False)
    owner=None;started=time.monotonic();report=dict(passed=False,scope=__doc__,forced_harness_cleanup=False)
    try:
        manifest=verify(package,'server');report['package_manifest_sha256']=sha(package/'package-manifest.json');report['asset_manifest_sha256']=sha(assets/'asset-manifest.json')
        report['driver_sha256']=sha(__file__);save(out/'request.json',dict(package=str(package),assets=str(assets),custom=custom and not public_mode,public_mode=public_mode,driver_sha256=report['driver_sha256']))
        owner=SuspendedChild.create([str(package/'program/runtime/python.exe'),'-I','-B',str(Path(__file__).resolve()),'--child-request',str(out/'request.json')],cwd=out,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'job-ready').write_bytes(b'owned job attached\n');owner.resume()
        deadline=time.monotonic()+90
        while owner.poll() is None:
            require(time.monotonic()<deadline,'owned controller deadline');time.sleep(.02)
        report['exit_code']=owner.returncode
        report['child']=json.loads((out/'child-report.json').read_bytes());report['job_final']=job_accounting(owner.job)
        deadline=time.monotonic()+5
        while report['job_final']['active_processes'] and time.monotonic()<deadline:
            time.sleep(.02);report['job_final']=job_accounting(owner.job)
        require(report['job_final']['active_processes']==0,'owned process remains')
        verify(package,'server');require(sha(assets/'asset-manifest.json')==report['asset_manifest_sha256'] and sha(__file__)==report['driver_sha256'],'inputs changed')
        report['passed']=report['exit_code']==0 and report['child']['passed'] is True
    except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        if owner:owner.close();report['launch']=owner.receipt;report['forced_harness_cleanup']=owner.receipt['forced_cleanup']
        report['passed'] &= not report['forced_harness_cleanup'];report['elapsed_seconds']=time.monotonic()-started;save(out/'verification.json',report)
        print(json.dumps({k:report[k] for k in ('passed','exit_code','forced_harness_cleanup','elapsed_seconds','error') if k in report}))
    return 0 if report['passed'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--child-request',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--direct-rooms',action='store_true',help='legacy direct-room comparison instead of current Custom flow')
    parser.add_argument('--public',action='store_true',dest='public_mode',help='two complete human public1v1 rooms, original queue/Ready/Return')
    for name in ('package','assets','output'):parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.child_request:raise SystemExit(child(args.child_request))
    require(all((args.package,args.assets,args.output)),'package/assets/output required')
    require(not (args.direct_rooms and args.public_mode),'choose one room route')
    raise SystemExit(run(args.package,args.assets,args.output,custom=not args.direct_rooms,public_mode=args.public_mode))
