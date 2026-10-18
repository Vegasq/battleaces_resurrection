"""Opt-in graphical public queue -> TLS/AI match -> native result/Continue.

Uses one isolated game, in-memory credentials and ephemeral test PKI. Original
buttons, build/surrender/Continue are automated callbacks, not manual input.
Forced owned teardown does not qualify native Quit or Internet/friend play.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import traceback

from client_patch.transport import bridge, launcher
from server import admission, tls_transport as tls, community_protocol as c, public_protocol as q, protocol as p
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker, _WindowsJob
from tests.test_admission import Store
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    paths = [Path(__file__), ROOT/'tools/run_secure_match.py', ROOT/'tools/verify_practice_ai.py'] + list((ROOT/'client_patch/transport').glob('*.py'))
    return core_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def elapsed_seconds(log,ticket):
    seconds=[int(value) for generation,value in re.findall(r'Native search timer: ticket=(\d+) seconds=(\d+)',log)
             if int(generation)==ticket]
    require(seconds and seconds[0]==0 and max(seconds)>=25 and seconds==sorted(seconds),
            'native search elapsed timer did not advance monotonically through queue wait')
    return seconds


async def run(args):
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    launcher.verify_game(game, community=True, bridge_version=2, unified=True)
    verify_assets(assets);output.mkdir(parents=True, exist_ok=False)
    pki_folder=output/'ephemeral-pki';pki=generate_test_pki(pki_folder)
    credentials, workers, events = Store(), [], []
    audit=Audit(output)
    templates={mode: GameTemplate.load(assets/name, catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
               for mode,name in ((1,'map-1v1.pb.gz'),(2,'map-2v2.pb.gz'),(5,'map-2vai.pb.gz'))}
    catalog=BotCatalog(assets, template=templates[1], rules=RuleBook(assets))
    def observe(event, **fields):
        events.append(dict(event=event, observed_at=time.monotonic(), **fields));audit(event, **fields)
    async def factory(data,bots):
        worker=await SimulationWorker.create(data,assets/'Simulation.dll',working_directory=output,ai=AISetup(assets,bots))
        workers.append(worker);return worker
    server=DedicatedServer(templates[1],ProfileStore(output/'profiles',templates[1]),templates=templates,bot_catalog=catalog,
        ai_factory=factory,audit=observe,data_dir=output,audit_state=False,input_timeout=30,
        tls_context=tls.load_server_context(pki['cert'],pki['key']),admission=admission.AdmissionController(credentials))
    process=job=writer=parent=child=bridge_task=None
    delayed=[];delayed_enter=False;dropped_ready=False;dropped_return=False
    fault=None;assignment_peer=None;withheld_bootstrap=False
    log='';launch_tick=None;attempts=0;started=time.monotonic()
    report=dict(passed=False,scope=__doc__,mode=args.mode,unavailable=args.unavailable,visible=args.visible,
                cancel=args.cancel,retry=args.retry,delay_enter_ack=args.delay_enter_ack,
                drop_on_ready=args.drop_on_ready,drop_return_ack=args.drop_return_ack,practice_overlap=args.practice_overlap,
                disconnect=args.disconnect,
                helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest(),
                source_sha256_at_start=source_hashes())
    try:
        port=(await server.start('127.0.0.1',0))[1]
        send=server.community.send
        def controlled_send(peer,kind,payload):
            nonlocal delayed_enter,dropped_return
            if kind==c.ACK:
                reader=c.Reader(payload);request=reader.number('I');command=reader.number('B')
                if args.delay_enter_ack and not delayed_enter and command==q.ENTER:
                    delayed_enter=True
                    def deliver():
                        observe('probe_delayed_enter_ack_delivered',request=request)
                        send(peer,kind,payload)
                    delayed.append(asyncio.get_running_loop().call_later(args.delay_enter_ack,deliver))
                    observe('probe_delayed_enter_ack',request=request,seconds=args.delay_enter_ack)
                    return
                if args.drop_return_ack and not dropped_return and command==q.RETURN:
                    dropped_return=True;observe('probe_drop_return_ack',request=request)
                    peer.close('probe lost RETURN acknowledgement');return
            send(peer,kind,payload)
        server.community.send=controlled_send
        apply=server.community.public.apply
        async def controlled_apply(session,kind,command,now):
            nonlocal dropped_ready
            result=await apply(session,kind,command,now)
            if args.drop_on_ready and not dropped_ready and kind==q.READY:
                dropped_ready=True;observe('probe_drop_after_ready',ticket=command['ticket'])
                session.peer.close('probe connection lost after READY commit')
            return result
        server.community.public.apply=controlled_apply
        context=tls.load_client_context(pki['ca'],'localhost')
        async def resolve():
            nonlocal attempts
            attempts+=1
            if args.unavailable: raise bridge.RemoteUnavailable()
            return bridge.Remote('127.0.0.1',port,context,credentials.player,credentials.token)
        config=dict(game_directory=game,server_host='127.0.0.1',server_port=port,display_name='Public Config Player',room='community')
        options=argparse.Namespace(run_name='public-queue-probe',unified_experimental=True)
        parent,child=socket.socketpair(socket.AF_INET);parent.setblocking(False)
        reader,writer=await asyncio.open_connection(sock=parent)
        command=launcher.game_arguments(config,None,child.fileno(),options)
        command[command.index('-logFile')+1]=str(output/'game.log')
        command+=['-public-queue-experimental','-public-queue-smoke',f'-public-queue-smoke-mode={args.mode}',
                  '-lan-smoke','-lan-audit','-dedicated-rematch-smoke']
        if not args.unavailable: command+=['-match-search-smoke']
        if args.cancel: command+=['-public-queue-smoke-cancel='+args.cancel]
        if args.retry: command+=['-public-queue-smoke-retry']
        if args.disconnect in ('loading','running'): command+=['-dedicated-recovery-smoke']
        if args.practice_overlap: command+=['-public-queue-smoke-practice-overlap']
        if args.mode==1:
            command+=['-dedicated-surrender-smoke','-dedicated-surrender-frame=1200']
        if args.unavailable:
            command+=['-practice-ai-smoke','-public-ai-smoke','-practice-ai-smoke-matches=1','-practice-ai-smoke-frames=1200']
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=1 if args.visible else 0
        startup.lpAttributeList={'handle_list':[child.fileno()]}
        clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong;launch_tick=clock()
        child.set_inheritable(True)
        try: process=subprocess.Popen(command,cwd=game,startupinfo=startup,close_fds=True,creationflags=0 if args.visible else subprocess.CREATE_NO_WINDOW)
        finally: child.set_inheritable(False)
        job=_WindowsJob(process.pid);child.close()
        bridge_task=asyncio.create_task(bridge.Bridge(reader,writer,resolve,version=2).run())
        report.update(game_pid=process.pid,launch_tick=launch_tick,client_arguments=command)
        (output/'processes.json').write_text(json.dumps(report,indent=2)+'\n')
        shutil.copyfile(game/'.battleaces-resurrection/patch-manifest.json',output/'patch-manifest.json')
        preworld=(bool(args.cancel) or args.drop_on_ready or args.disconnect=='assignment') and not args.retry
        disconnected_only=bool(args.disconnect) and not args.retry
        marker=(f'Practice returned: completed=1 mode={args.mode}' if args.unavailable else
                'Public intent retired: ticket=1' if preworld or disconnected_only or args.drop_return_ack else 'PUBLIC QUEUE completed return:')
        while True:
            require(process.poll() is None,'owned game exited before native return')
            log=read_native_log(game,process.pid,since_tick=launch_tick)
            for failure in ('Public client failure:', 'Client lifecycle invariant failed:', 'Practice stopped in '):
                require(failure not in log,'native public failure: '+failure)
            for failure in re.findall(r'Offline loop stopped in [^\n]*',log):
                require(fault is not None and args.disconnect in ('loading','running') and re.fullmatch(
                    r'Offline loop stopped in (?:LAN update|LAN front update|dedicated session update): '
                    r'(?:match server disconnected before a result|Secure session is closed)',failure.rstrip('\r')),
                    'unexpected native stop: '+failure)
            if args.disconnect and fault is None:
                entries=list(server.community.public.entries.values())
                if args.disconnect=='assignment' and assignment_peer is None and entries:
                    # Hold only this first peer's bootstrap. Its assignment must
                    # reach the native reader before a world can be constructed.
                    require(len(entries)==1,'fault probe has unexpected public peers')
                    assignment_peer=entries[0].session.peer
                    send_packet=assignment_peer.send
                    def hold_bootstrap(kind,payload=b''):
                        nonlocal withheld_bootstrap
                        if kind==p.BOOTSTRAP:
                            require(not withheld_bootstrap,'duplicate withheld bootstrap')
                            withheld_bootstrap=True
                            observe('probe_withheld_bootstrap',bytes=len(payload))
                            return
                        send_packet(kind,payload)
                    assignment_peer.send=hold_bootstrap
                assigned=re.search(r'Public match assignment: ticket=1 match=([0-9a-f]{32}) ',log)
                joined=re.search(r'Public native match joined: ticket=1 match=([0-9a-f]{32}) ',log)
                received=[int(frame) for frame in re.findall(r'LAN received frame (\d+),',log)]
                reached=(args.disconnect=='assignment' and assigned is not None or
                         args.disconnect=='loading' and joined is not None or
                         args.disconnect=='running' and bool(received) and max(received)>=200)
                if reached:
                    require(len(entries)==1 and assigned is not None,'disconnect target missing or ambiguous')
                    peer=entries[0].session.peer;room=peer.room
                    require(room is not None and room.match_id==assigned[1] and not peer.closed,'disconnect room changed')
                    if args.disconnect=='assignment':
                        require(withheld_bootstrap and joined is None and 'Client world acquired:' not in log,
                                'assignment probe reached native world too early')
                    elif args.disconnect=='loading':
                        require(room.state=='loading' and peer.slot not in room.loaded and 'Offline world ready;' not in log,
                                'loading disconnect missed the asynchronous map-load window')
                    else:
                        require(room.state=='running' and peer.slot in room.loaded and 'Offline world ready;' in log,
                                'running disconnect did not reach a loaded native world')
                    fault=dict(stage=args.disconnect,match=room.match_id,last_native_frame=max(received,default=-1),
                               room_state=room.state,native_joined=joined is not None,withheld_bootstrap=withheld_bootstrap,
                               log_offset=len(log))
                    observe('probe_disconnect',**fault);peer.close()
                    report['injected_disconnect']=fault
            if marker in log: break
            require(time.monotonic()-started<args.timeout,'native public queue/match/Continue timed out')
            await asyncio.sleep(.02 if args.disconnect and fault is None else .2)
        require('PUBLIC QUEUE SMOKE original OnMapSelected:' in log,'original public button missing')
        if not preworld: require('Native search joining signal:' in log,'original native loading handoff missing')
        if args.cancel:
            require(log.count('PUBLIC QUEUE SMOKE cancellation:')==1 and 'Native search original Cancel invoked:' in log,
                    'original Cancel callback/intent missing or duplicated')
        if args.drop_on_ready: require(dropped_ready,'READY disconnect injection missing')
        if args.drop_return_ack:
            require(dropped_return and 'reason=connection lost after return nativeIdle=1' in log,
                    'RETURN disconnect did not retire the completed native match')
            require('identity=public-error:' not in log,'completed match displayed an incorrect start-failure notice')
        if args.practice_overlap:
            require('PUBLIC QUEUE SMOKE practice overlap rejected:' in log,'practice/public ownership check missing')
        if args.delay_enter_ack:
            require(delayed_enter and any(row['event']=='probe_delayed_enter_ack_delivered' for row in events),
                    'delayed acknowledgement was not delivered')
        if args.retry:
            require(log.count('Public search intent:')==2 and 'Native search stale ticket rejected:' in log,
                    'retry did not use a new native search generation')
        if args.disconnect:
            require(fault is not None,'connection loss was not injected')
            require('Public fallback accepted:' not in log and 'owner=local-practice' not in log,
                    'committed remote match incorrectly fell back to a local world')
            retired=re.search(r'Public intent retired: ticket=1 reason=connection lost after (?:READY|match acceptance) nativeIdle=1 disconnect=1',log)
            require(retired is not None and retired.start()>fault['log_offset'],'failed public intent did not retire after disconnect')
            if args.disconnect!='assignment':
                markers=('RECOVERY SMOKE invoking original disconnected modal OnConfirm',
                         'Dedicated Reconnect callback queued:',
                         'RECOVERY SMOKE original OnConfirm returned; modalStillOwned=1 queued=1',
                         'Dedicated retry modal released on later update:',
                         'Dedicated session reset: match='+fault['match'],
                         'Client world released: generation=1 owner=remote nativeIdle=1')
                positions=[log.find(value,fault['log_offset']) for value in markers]+[retired.start()]
                require(all(left>=0 and right>left for left,right in zip(positions,positions[1:])),
                        'native disconnect cleanup/modal/world release order incorrect')
                deferred=re.search(r'Dedicated retry modal released on later update: requested=(\d+) current=(\d+)',log)
                require(deferred is not None and int(deferred[1])<int(deferred[2]),'Reconnect released its invoking modal inline')
                require('Dedicated aborted match: requesting original CleanupGameState(reason=1)' in log,
                        'failed native world bypassed original cleanup')
            if args.retry:
                retry=re.search(r'Public search intent: ticket=2 ',log)
                require(retry is not None and retry.start()>retired.end(),'retry started before failed intent/world retired')
                dismissed=re.search(r'Match loading event=notice-dismissed [^\r\n]*identity=public-error:1 [^\r\n]*reason=public search restarted',log)
                require(dismissed is not None and retired.end()<dismissed.start()<retry.start(),
                        'retry retained its old public failure banner')
                require(len(workers)==2 and credentials.calls==attempts==2,'disconnect/retry did not use exactly two sessions/workers')
            deadline=time.monotonic()+5
            while any(entry.ticket==1 for entry in server.community.public.entries.values()) or fault['match'] in server.community.public.offers:
                require(time.monotonic()<deadline,'disconnected public ticket/offer retained capacity')
                await asyncio.sleep(.05)
            aborted=[row for row in events if row['event']=='match_aborted' and row['match']==fault['match']]
            require(len(aborted)==1,'server did not abort exactly the disconnected match')
            entered=next(row for row in events if row['event']=='public_queue_entered' and row['ticket']==1)
            offered=next(row for row in events if row['event']=='public_match_offered' and row['match']==fault['match'])
            require(29<=offered['observed_at']-entered['observed_at']<=33,'faulted match skipped the real queue wait')
            report['faulted_queue_seconds']=offered['observed_at']-entered['observed_at']
            report['faulted_native_elapsed_seconds']=elapsed_seconds(log,1)
            if args.disconnect=='running':
                receipts=game/'investigation/runtime'/f'dedicated-receipts-{process.pid}-{fault["match"]}.tsv'
                rows=list(csv.DictReader(receipts.read_text(encoding='utf-8').splitlines(),delimiter='\t'))
                authoritative={row['frame']:row['frame_payload_sha256'] for row in events
                               if row['event']=='frame_queued' and row['match']==fault['match']}
                require(len(rows)>=201 and [int(row['frame']) for row in rows]==list(range(len(rows))),
                        'disconnected native frame prefix missing/out of order')
                require(all(row['sha256']==authoritative.get(int(row['frame'])) for row in rows),
                        'disconnected native frames differ from authoritative prefix')
                shutil.copyfile(receipts,output/receipts.name)
                report['aborted_match_received_frames']=len(rows)
        if args.unavailable:
            require(not workers and not credentials.calls and 'Public fallback accepted:' in log,'unavailable route contacted/started server match')
            require(log.count('Client world acquired:')==1 and 'owner=local-practice' in log and 'owner=remote' not in log,
                    'fallback world ownership differs')
            require(attempts==1,'unavailable public intent attempted multiple connections')
            from tools.verify_practice_ai import movement_evidence
            armies=[json.loads(line.split('Practice army snapshot: ',1)[1]) for line in log.splitlines() if 'Practice army snapshot: ' in line]
            participants=2 if args.mode==1 else 4
            require(len(armies)==participants,'fallback roster size mismatch')
            require([army.get('armyId',0) for army in armies]==list(range(participants)) and
                    [army.get('allianceId',0) for army in armies]==[seat%2 for seat in range(participants)],'fallback topology changed')
            require(f'Local AI all ready: bots={participants-1} sharedSimulation=1 producers={participants}' in log,
                    'fallback did not wait for every local bot')
            bots=[]
            for seat,army in enumerate(armies[1:],1):
                moved,ordered=movement_evidence(log,set(army['deck']['units']),seat)
                require(moved & ordered,'fallback bot did not autonomously move produced units: '+str(seat))
                require(log.count(f'Practice native JoinArmy validated: army={seat} ')==1,'fallback bot duplicate/missing exact deck join')
                require(any('Public AI identity binding: phase=result ' in line and line.endswith(f'army={seat}') for line in log.splitlines()),
                        'fallback bot result identity missing')
                bots.append(dict(seat=seat,profile=army['players'][0]['aiProfileId'],ordered_moving_units=sorted(moved & ordered)))
            report.update(local_fallback=True,local_bots=bots)
        elif disconnected_only:
            require(len(workers)==1 and credentials.calls==1 and attempts==1,'disconnect-only probe created extra session/worker')
            expected=0 if args.disconnect=='assignment' else 1
            require(log.count('Client world acquired:')==expected and log.count('owner=remote nativeIdle=1')==expected,
                    'disconnect-only probe retained or duplicated a native world')
            require(not server.community.public.entries and not server.community.public.offers,'disconnected server state retained')
            report.update(disconnected_match_retired=True)
        elif preworld:
            # Disconnect retirement is asynchronous on the server. Wait for it
            # before claiming capacity release, without closing the server first.
            deadline=time.monotonic()+5
            while server.community.public.entries or server.community.public.offers:
                require(time.monotonic()<deadline,'cancel/disconnect retained server ticket/offer')
                await asyncio.sleep(.05)
            require('Client world acquired:' not in log and 'Public native match joined:' not in log and
                    'Public fallback accepted:' not in log,'cancel/ambiguous READY created a client world')
            require(len(workers)<=1 if args.cancel=='after-ready' or args.drop_on_ready else not workers,
                    'unexpected worker allocation before cancellation')
            require('Native search released:' in log,'cancel/disconnect retained search presentation')
            report.update(retired_without_world=True)
            if args.cancel in ('offered','after-ready') or args.drop_on_ready:
                report['native_elapsed_seconds']=elapsed_seconds(log,1)
        else:
            maximum=2 if args.retry and (args.cancel=='after-ready' or args.drop_on_ready or args.disconnect) else 1
            require(1<=len(workers)<=maximum and 1<=credentials.calls<=(2 if args.retry else 1),
                    'unexpected authenticated match/worker count')
            finished=[row for row in events if row['event']=='match_completed'];require(len(finished)==1,'duplicate/missing completed match')
            match=finished[0]['match']
            offered=next(row for row in events if row['event']=='public_match_offered' and row['match']==match)
            ticket=offered['tickets'][0]
            entered=next(row for row in events if row['event']=='public_queue_entered' and row['ticket']==ticket)
            require(29<=offered['observed_at']-entered['observed_at']<=33,'server fallback did not use real30-second queue wait')
            require(not server.community.public.entries and not server.community.public.offers,'native RETURN retained ticket/offer')
            expected_worlds=2 if args.retry and args.disconnect in ('loading','running') else 1
            require('Public native match joined:' in log and 'Public native return:' in log and 'owner=remote' in log and
                    'owner=local-practice' not in log and log.count('Client world acquired:')==expected_worlds and
                    log.count('owner=remote nativeIdle=1')==expected_worlds,
                    'remote native lifecycle missing/overlapped')
            receipts=game/'investigation/runtime'/f'dedicated-receipts-{process.pid}-{match}.tsv'
            rows=list(csv.DictReader(receipts.read_text(encoding='utf-8').splitlines(),delimiter='\t'))
            authoritative={row['frame']:row['frame_payload_sha256'] for row in events if row['event']=='frame_queued' and row['match']==match}
            require(len(rows)>=600 and len(rows)==len(authoritative),'native receipt count differs from server frames')
            for row in rows: require(row['sha256']==authoritative[int(row['frame'])],'native public receipt differs from server input frame')
            shutil.copyfile(receipts,output/receipts.name)
            seconds=elapsed_seconds(log,ticket)
            result=finished[0]['result']
            report.update(match=match,received_frames=len(rows),result=result,real_queue_seconds=offered['observed_at']-entered['observed_at'],
                          native_elapsed_seconds=seconds)
        report.update(passed=True,remote_attempts=attempts,authentications=credentials.calls)
    except BaseException as error:
        report.update(passed=False,error=f'{type(error).__name__}: {error}',traceback=traceback.format_exc())
    finally:
        for callback in delayed: callback.cancel()
        if child is not None: child.close()
        if process is not None:
            if process.poll() is None: process.terminate()
            await asyncio.to_thread(process.wait,timeout=15)
            try:
                log=read_native_log(game,process.pid,since_tick=launch_tick)
                (output/f'native-{process.pid}.log').write_text(log,encoding='utf-8')
            except Exception as error:
                report.update(passed=False,evidence_error=f'{type(error).__name__}: {error}')
            for name in re.findall(r'file=(match-search-\d+-\d+-\d+-\w+\.png)',log):
                source=game/'investigation/runtime'/name
                if source.is_file(): shutil.copyfile(source,output/name)
        if job is not None: job.close()
        if bridge_task is not None: bridge_task.cancel();await asyncio.gather(bridge_task,return_exceptions=True)
        if writer is not None:
            writer.close()
            try: await asyncio.wait_for(writer.wait_closed(),2)
            except (OSError,TimeoutError): writer.transport.abort()
        elif parent is not None: parent.close()
        await server.close();await asyncio.gather(*(worker.close() for worker in workers))
        remove_test_pki(pki_folder);audit.close()
        cleanup=[]
        for worker in workers:
            match=next((row['match'] for row in events if row['event']=='worker_started' and row['worker_pid']==worker.pid),None)
            released=any(row['event']=='worker_released' and row['worker_pid']==worker.pid and row['match']==match for row in events)
            reaped=worker.process.poll() is not None and worker._cleanup_task is not None and worker._cleanup_task.done() and not worker._stderr_thread.is_alive()
            # Room cancellation can interrupt a native IPC request. Its existing
            # contract kills/reaps that worker instead of reusing unknown state.
            # Only the injected aborted match may take that identified path;
            # ordinary results and unknown nonzero exits still fail this probe.
            cancelled=bool(fault and args.disconnect=='running' and match==fault['match'] and released and
                           worker.process.poll()==1 and (worker.failure or '').startswith('CancelledError:'))
            okay=reaped and ((worker.process.poll()==0 and not worker.failure) or cancelled)
            cleanup.append(dict(pid=worker.pid,match=match,exit_code=worker.process.poll(),failure=worker.failure,
                                stderr_tail=worker.stderr_tail[-4096:],owned_resources_reaped=reaped,
                                expected_cancelled_request=cancelled,passed=okay))
        report.update(elapsed_seconds=time.monotonic()-started,owned_process_reaped=process is None or process.poll() is not None,
            worker_exit_codes=[worker.process.poll() for worker in workers],cleanup='forced owned termination, not native Quit',
            worker_cleanup=cleanup,source_sha256_at_finish=source_hashes())
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        workers_ok=all(row['passed'] for row in cleanup)
        if not workers_ok: report.setdefault('error','worker cleanup failed; see worker_cleanup evidence')
        report['passed'] &= report['source_files_unchanged'] and report['owned_process_reaped'] and workers_ok
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','error','elapsed_seconds','received_frames','worker_exit_codes') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('game','assets','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--mode',type=int,choices=(1,2,5),default=1)
    parser.add_argument('--timeout',type=int,default=600)
    parser.add_argument('--unavailable',action='store_true')
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--cancel',choices=('before-enter','waiting','offered','after-ready'))
    parser.add_argument('--retry',action='store_true')
    parser.add_argument('--delay-enter-ack',type=float,default=0)
    parser.add_argument('--drop-on-ready',action='store_true')
    parser.add_argument('--drop-return-ack',action='store_true')
    parser.add_argument('--disconnect',choices=('assignment','loading','running'),
                        help='close first owned TLS peer at a native-observed stage; test cleanup and optional explicit retry')
    parser.add_argument('--practice-overlap',action='store_true')
    args=parser.parse_args()
    require(os.name=='nt' and args.output.resolve().is_relative_to(ROOT/'local') and 120<=args.timeout<=900,'bounded Windows/ignored probe required')
    require(0<=args.delay_enter_ack<=8 and (not args.retry or args.cancel or args.drop_on_ready or args.disconnect),'bounded delay/retry point required')
    require(sum(map(bool,(args.unavailable,args.cancel,args.drop_on_ready,args.drop_return_ack,args.disconnect)))<=1,
            'choose one unavailable/cancel/disconnect scenario')
    return asyncio.run(run(args))


if __name__=='__main__': raise SystemExit(main())
