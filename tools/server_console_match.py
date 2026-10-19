"""External diagnostic: two scripted peers, real packaged native match, stop/restart.

Loaded by verify_server_console under the bundled runtime without changing its
import path. This is server protocol/native-worker evidence, not graphical-client
or original matchmaking UI acceptance. Never packaged as an ordinary entry point.
"""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import socket
import struct
import subprocess
import time


def require(value,message):
    if not value:raise AssertionError(message)


def audit_records(path):
    raw=Path(path).read_bytes()
    require(len(raw)<=4*1024*1024,'diagnostic audit exceeded budget')
    return [json.loads(line) for line in raw.splitlines()]


def packet(stream):
    from server import protocol as p
    def exact(size):
        data=bytearray()
        while len(data)<size:
            part=stream.recv(size-len(data))
            if not part:
                if data:raise AssertionError('partial packet at disconnect')
                raise EOFError
            data.extend(part)
        return bytes(data)
    size,=struct.unpack('<I',exact(4))
    require(1<=size<=p.MAX_BODY,'packet budget exceeded')
    try:body=exact(size)
    except EOFError:raise AssertionError('partial body at disconnect') from None
    return body[0],body[1:]


def receive(stream,expected):
    from server import protocol as p
    deadline=time.monotonic()+10
    for _ in range(128):
        require(time.monotonic()<deadline,'diagnostic peer receive deadline')
        stream.settimeout(max(.01,deadline-time.monotonic()))
        kind,body=packet(stream)
        if kind==expected:return body
        require(kind in (p.LOBBY,p.NOTICE,p.MATCH_INFO),'unexpected diagnostic peer packet')
    raise AssertionError('diagnostic peer packet count exceeded')


class WorkerHandle:
    """Retain only the PID authored by this run's real host audit; never kill it."""
    def __init__(self,kernel,pid,runtime):
        self.kernel=kernel;self.handle=None;self.pid=pid
        kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
        kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];kernel.WaitForSingleObject.restype=w.DWORD
        kernel.GetExitCodeProcess.argtypes=[w.HANDLE,c.POINTER(w.DWORD)]
        kernel.CloseHandle.argtypes=[w.HANDLE]
        handle=kernel.OpenProcess(0x1000|0x100000,False,pid)
        require(handle,'owned match worker query unavailable');self.handle=handle
        try:
            path=c.create_unicode_buffer(32768);size=w.DWORD(len(path))
            require(kernel.QueryFullProcessImageNameW(handle,0,path,c.byref(size)) and
                    Path(path.value).resolve()==Path(runtime).resolve(),'worker image differs from bundled runtime')
            require(kernel.WaitForSingleObject(handle,0)==258,'worker was not live before console stop')
        except BaseException:self.close();raise

    def exited(self):
        code=w.DWORD()
        require(self.kernel.WaitForSingleObject(self.handle,0)==0 and
                self.kernel.GetExitCodeProcess(self.handle,c.byref(code)),'worker did not exit')
        require(code.value==0,'native worker did not exit successfully')
        return dict(pid=self.pid,live_before_stop=True,signaled_after_stop=True,exit_code=code.value)

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


def connect_match(request,peers,cycle):
    from server import protocol as p
    from server.game_data import decompress_game_data,encode_player_input,decode_identity,decode_deck
    from server.protobuf_wire import get_bytes,get_repeated_bytes,get_uint,field_bytes,field_uint
    from server.credentials import read_credential_file
    from server.tls_transport import load_client_context
    from server.admission import AUTH,AUTH_OK,AUTH_VERSION
    welcomes=[];authentication=[]
    context=load_client_context(request['ca'],'localhost') if request['tls'] else None
    for slot in (0,1):
        plain=socket.create_connection(('127.0.0.1',request['port']),timeout=5)
        peers.append(plain)
        if context:
            stream=context.context.wrap_socket(plain,server_hostname='localhost');peers[-1]=stream
            identity=read_credential_file(request['credentials'][slot]['path'])
            require(identity['player_id']==request['credentials'][slot]['player_id'],'strict invite identity differs')
            stream.sendall(p.encode(AUTH,struct.pack('<H',AUTH_VERSION)+identity['token'].encode('ascii')))
            kind,body=packet(stream)
            require(kind==AUTH_OK and body==struct.pack('<HH',AUTH_VERSION,34)+identity['player_id'].encode('ascii'),
                    'real host authentication failed')
            profile=identity['player_id']
            authentication.append(dict(player_id=profile,verified_tls=True,version=stream.version(),authenticated=True))
        else:stream=plain;profile='console40_'+str(slot)
        stream.sendall(p.encode(p.HELLO,p.hello(slot,profile,'Console Player '+str(slot),'console40')))
        assigned,window,deck=p.decode_welcome(receive(stream,p.WELCOME))
        require(assigned==slot and window==6,'diagnostic seat/window differs');welcomes.append(deck)
        stream.sendall(p.encode(p.SET_DECK,p.deck_bytes(deck)))
    for stream in peers:stream.sendall(p.encode(p.LOBBY_READY,b'\x01'))
    matches=[receive(stream,p.MATCH_INFO) for stream in peers]
    require(matches[0]==matches[1] and len(matches[0])==32,'native match identities differ')
    bootstraps=[receive(stream,p.BOOTSTRAP) for stream in peers]
    require(bootstraps[0]==bootstraps[1],'peers received different native bootstrap')
    config=get_bytes(decompress_game_data(bootstraps[0]),1,required=True)
    armies={get_uint(army,1):army for army in get_repeated_bytes(config,2)}
    require(set(armies)=={0,1},'expected a two-human 1v1 bootstrap')
    identities=[];joins=[]
    for slot in (0,1):
        army=armies[slot];identity=get_bytes(army,2,required=True);deck=get_bytes(army,3,required=True)
        require(decode_identity(identity)['name']=='Console Player '+str(slot) and
                not decode_identity(identity)['ai_profile_id'] and decode_deck(deck)['units']==tuple(welcomes[slot]),
                'native roster/deck differs')
        join=field_uint(1,slot)+field_bytes(2,deck)
        for target,source in ((3,5),(4,6)):
            value=get_uint(army,source)
            if value:join+=field_uint(target,value)
        identities.append(identity);joins.append(field_bytes(3,join))
    for stream in peers:stream.sendall(p.encode(p.LOADED,hashlib.sha256(bootstraps[0]).digest()))
    starts=[receive(stream,p.START) for stream in peers]
    require(starts==[b'',b''],'native start markers differ')
    journal=hashlib.sha256();hashes=[]
    for frame in range(40):
        for slot,stream in enumerate(peers):
            body=encode_player_input(identities[slot],[joins[slot]] if frame==0 else [])
            stream.sendall(p.encode(p.INPUT,struct.pack('<I',frame)+body))
        frames=[receive(stream,p.FRAME) for stream in peers]
        require(frames[0]==frames[1] and struct.unpack_from('<I',frames[0])[0]==frame,'native frame stream differs')
        journal.update(struct.pack('<I',len(frames[0]))+frames[0])
        hashes.append(hashlib.sha256(frames[0]).hexdigest())
    return dict(cycle=cycle,room='console40',match=matches[0].decode('ascii'),frames_per_peer=40,
                equal_frame_streams=True,frame_journal_sha256=journal.hexdigest(),decks=welcomes,
                bootstrap_sha256=hashlib.sha256(bootstraps[0]).hexdigest(),authentication=authentication,
                frame_payload_sha256=hashes,
                peers_held_open_until_ctrl_c=True)


def validate_audit(records,match,*,stopped,stop_ns=None,received_hashes):
    selected=[row for row in records if row.get('match')==match]
    def one(event):
        rows=[row for row in selected if row['event']==event]
        require(len(rows)==1,'native match audit event count differs: '+event);return rows[0]
    worker=one('worker_started')['worker_pid'];one('match_created');one('match_started')
    frames=[row for row in selected if row['event']=='frame_queued']
    require([row['frame'] for row in frames]==list(range(40)),'native host frame count differs')
    require([row['frame_payload_sha256'] for row in frames]==received_hashes,'host/peer frame bytes differ')
    snapshots=[row for row in selected if row['event']=='native_snapshot']
    require(sorted((row['frame'],row['viewer']) for row in snapshots)==[(0,0),(0,1),(20,0),(20,1)] and
            all(not row['game_state']['complete'] and row['counts']['type']>0 for row in snapshots),
            'native joined/active snapshot absent')
    forbidden={'connection_error','protocol_error','authentication_failed','authentication_shutdown_incomplete',
               'audit_record_omitted','match_completed','worker_error'}
    require(not any(row['event'] in forbidden for row in records),'host audit contains a failure')
    if stopped:
        aborted=one('match_aborted');released=one('worker_released')
        # CPython 3.14 plain Server.serve_forever cancellation closes clients
        # before host.finally. Both paths must abort AFTER our original Ctrl+C,
        # release the same worker, and finish before server_stopped.
        require(stop_ns is not None and aborted['perf_counter_ns']>=stop_ns and
                aborted['reason'] in ('server stopped','player disconnected') and aborted['next_frame']==40 and
                released['worker_pid']==worker and released['perf_counter_ns']>aborted['perf_counter_ns'],
                'active room did not drain during server stop')
        stops=[row for row in records if row['event']=='server_stopped']
        require(len(stops)==1 and stops[0]['perf_counter_ns']>released['perf_counter_ns'],'server stopped before worker release')
    else:require(not any(row['event'] in ('match_aborted','worker_released','server_stopped') for row in records),
                 'match ended before console stop')
    return worker


def exercise(request,report,kernel,received,console_ids):
    from server.state_lock import exclusive_state
    output=Path(request['output']);package=Path(request['package']);data=Path(request['data'])
    audit=data/'logs/events.jsonl';report['active_match_cycles']=[];process=None;worker=None;peers=[]
    try:
        for cycle in (0,1):
            record=dict(cycle=cycle,passed=False);report['active_match_cycles'].append(record)
            before=audit_records(audit) if audit.exists() else []
            stdout_path=output/f'match-{cycle}-stdout.txt';stderr_path=output/f'match-{cycle}-stderr.txt'
            with stdout_path.open('xb') as stdout,stderr_path.open('xb') as stderr:
                process=subprocess.Popen([str(package/'Start Server.exe'),'--config',str(output/'config/host.json')],
                    cwd=output/'foreign cwd',stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
                record['launcher_pid']=process.pid;deadline=time.monotonic()+60
                while True:
                    raw=stdout_path.read_bytes();require(len(raw)<=1024*1024,'host output budget exceeded')
                    if b'Ctrl+C stops it cleanly.' in raw:break
                    require(process.poll() is None and time.monotonic()<deadline,'host readiness failed');time.sleep(.05)
                healths=[json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.startswith('{')]
                require(len(healths)==1,'host health count differs');health=healths[0];native=health['native']
                require(health['passed'] and health['tls'] is request['tls'] and health['credential_store_checked'] is request['tls'] and
                        health['pointer_bits']==64 and native['created'] and native['stepped_frame']==0 and
                        native['exit_code']==0 and native['reaped'],'host/native health differs')
                record['health']=health;ids=console_ids(kernel)
                require(len(ids)==3 and process.pid in ids,'private console audience differs');record['console_pids']=ids
                record.update(connect_match(request,peers,cycle))
                records=audit_records(audit)[len(before):]
                pid=validate_audit(records,record['match'],stopped=False,received_hashes=record['frame_payload_sha256'])
                worker=WorkerHandle(kernel,pid,package/'program/runtime/python.exe')
                stop=time.monotonic();stop_ns=time.perf_counter_ns()
                require(kernel.GenerateConsoleCtrlEvent(0,0),'owned console Ctrl+C failed')
                record['ctrl_c_sent']=True;process.wait(timeout=15)
                require(process.returncode==0 and received==[0]*(cycle+1),'console stop/exit differs')
                record.update(exit_code=process.returncode,stop_seconds=time.monotonic()-stop,worker=worker.exited())
            for stream in peers:
                stream.settimeout(3);reason=None
                try:
                    kind,body=packet(stream)
                    require(kind==255 and body==b'server stopped','unexpected stop message')
                    reason=body.decode('ascii');packet(stream)
                    raise AssertionError('connection remained open after server stop')
                except EOFError:pass
                record.setdefault('peer_disconnects',[]).append(dict(eof=True,reason=reason))
                stream.close()
            peers.clear();worker.close();worker=None
            require(not stderr_path.read_bytes(),'host stderr during active stop')
            records=audit_records(audit)[len(before):]
            require(validate_audit(records,record['match'],stopped=True,stop_ns=stop_ns,
                received_hashes=record['frame_payload_sha256'])==pid,'worker identity changed')
            record['abort_reason']=next(row['reason'] for row in records if row['event']=='match_aborted')
            record['audit_sha256']=hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);probe.bind(('127.0.0.1',request['port']))
            with exclusive_state(data):pass
            profiles={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (data/'profiles').glob('*.json')}
            require(len(profiles)==2,'expected two persisted native peer profiles')
            if cycle:require(profiles==report['persisted_profile_sha256'],'restart changed saved profiles')
            report['persisted_profile_sha256']=profiles
            record.update(listener_port_released=True,state_lock_released=True,passed=True)
        require(report['active_match_cycles'][0]['match']!=report['active_match_cycles'][1]['match'],'restart reused a match identity')
        require(report['active_match_cycles'][0]['decks']==report['active_match_cycles'][1]['decks'],'restart lost selected decks')
        report.update(passed=True,restart_same_port_data_and_identities=True,controller_events=received)
    finally:
        for stream in peers:stream.close()
        if worker:worker.close()
        if process is not None and process.poll() is None:
            report['forced_cleanup']=True;process.terminate();process.wait(timeout=10)
