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
from server import admission, tls_transport as tls, community_protocol as c, public_protocol as q
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
    paths = [Path(__file__), ROOT/'tools/run_secure_match.py'] + list((ROOT/'client_patch/transport').glob('*.py'))
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
    log='';launch_tick=None;attempts=0;started=time.monotonic()
    report=dict(passed=False,scope=__doc__,mode=args.mode,unavailable=args.unavailable,visible=args.visible,
                cancel=args.cancel,retry=args.retry,delay_enter_ack=args.delay_enter_ack,
                drop_on_ready=args.drop_on_ready,drop_return_ack=args.drop_return_ack,practice_overlap=args.practice_overlap,
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
        if args.practice_overlap: command+=['-public-queue-smoke-practice-overlap']
        if args.mode==1:
            command+=['-dedicated-surrender-smoke','-dedicated-surrender-frame=1200']
        if args.unavailable:
            command+=['-practice-ai-smoke','-practice-ai-smoke-matches=1','-practice-ai-smoke-frames=1200']
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
        preworld=(bool(args.cancel) or args.drop_on_ready) and not args.retry
        marker=('Practice returned: completed=1 mode=1' if args.unavailable else
                'Public intent retired: ticket=1' if preworld or args.drop_return_ack else 'PUBLIC QUEUE completed return:')
        while True:
            require(process.poll() is None,'owned game exited before native return')
            log=read_native_log(game,process.pid,since_tick=launch_tick)
            for failure in ('Public client failure:', 'Client lifecycle invariant failed:', 'Offline loop stopped in '):
                require(failure not in log,'native public failure: '+failure)
            if marker in log: break
            require(time.monotonic()-started<args.timeout,'native public queue/match/Continue timed out')
            await asyncio.sleep(.2)
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
        if args.unavailable:
            require(not workers and not credentials.calls and 'Public fallback accepted:' in log,'unavailable route contacted/started server match')
            require(log.count('Client world acquired:')==1 and 'owner=local-practice' in log and 'owner=remote' not in log,
                    'fallback world ownership differs')
            report.update(local_fallback=True)
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
            maximum=2 if args.retry and (args.cancel=='after-ready' or args.drop_on_ready) else 1
            require(1<=len(workers)<=maximum and 1<=credentials.calls<=(2 if args.retry else 1),
                    'unexpected authenticated match/worker count')
            finished=[row for row in events if row['event']=='match_completed'];require(len(finished)==1,'duplicate/missing completed match')
            match=finished[0]['match']
            offered=next(row for row in events if row['event']=='public_match_offered' and row['match']==match)
            ticket=offered['tickets'][0]
            entered=next(row for row in events if row['event']=='public_queue_entered' and row['ticket']==ticket)
            require(29<=offered['observed_at']-entered['observed_at']<=33,'server fallback did not use real30-second queue wait')
            require(not server.community.public.entries and not server.community.public.offers,'native RETURN retained ticket/offer')
            require('Public native match joined:' in log and 'Public native return:' in log and 'owner=remote' in log and
                    'owner=local-practice' not in log and log.count('Client world acquired:')==1,
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
        report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        for callback in delayed: callback.cancel()
        if child is not None: child.close()
        if process is not None:
            log=read_native_log(game,process.pid,since_tick=launch_tick)
            (output/f'native-{process.pid}.log').write_text(log,encoding='utf-8')
            if process.poll() is None: process.terminate()
            await asyncio.to_thread(process.wait,timeout=15)
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
        report.update(elapsed_seconds=time.monotonic()-started,owned_process_reaped=process is None or process.poll() is not None,
            worker_exit_codes=[worker.process.poll() for worker in workers],cleanup='forced owned termination, not native Quit',
            source_sha256_at_finish=source_hashes())
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['passed'] &= report['source_files_unchanged'] and report['owned_process_reaped'] and all(code==0 for code in report['worker_exit_codes'])
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
    parser.add_argument('--practice-overlap',action='store_true')
    args=parser.parse_args()
    require(os.name=='nt' and args.output.resolve().is_relative_to(ROOT/'local') and 120<=args.timeout<=900,'bounded Windows/ignored probe required')
    require(0<=args.delay_enter_ack<=8 and (not args.retry or args.cancel or args.drop_on_ready),'bounded delay/retry point required')
    require(sum(map(bool,(args.unavailable,args.cancel,args.drop_on_ready,args.drop_return_ack)))<=1,
            'choose one unavailable/cancel/disconnect scenario')
    require(not args.unavailable or args.mode==1,'offline public team adapter is not implemented yet')
    return asyncio.run(run(args))


if __name__=='__main__': raise SystemExit(main())
