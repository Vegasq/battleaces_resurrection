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
import secrets
import shutil
import socket
import subprocess
import time
import traceback

from client_patch.transport import bridge, launcher, client
from server import admission, tls_transport as tls, community_protocol as c, public_protocol as q, protocol as p
from server.ai_rules import RuleBook
from server.assets import verify_assets
from server.bot_catalog import BotCatalog
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server.cosmetics import CosmeticCatalog
from server import loadout_protocol
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker, _WindowsJob
from tests.test_admission import Store
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes
from tools import verify_unified_startup as startup_probe
from tools import public_return_evidence
from tools import public_late_assignment

ROOT = Path(__file__).resolve().parents[1]


def source_hashes():
    paths = [Path(__file__), Path(public_return_evidence.__file__), Path(public_late_assignment.__file__), ROOT/'tools/run_secure_match.py', ROOT/'tools/verify_practice_ai.py', ROOT/'tools/verify_unified_startup.py'] + list((ROOT/'client_patch/transport').glob('*.py'))
    return core_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def elapsed_seconds(log,ticket):
    seconds=[int(value) for generation,value in re.findall(r'Native search timer: ticket=(\d+) seconds=(\d+)',log)
             if int(generation)==ticket]
    require(seconds and seconds[0]==0 and max(seconds)>=25 and seconds==sorted(seconds),
            'native search elapsed timer did not advance monotonically through queue wait')
    return seconds


async def run(args):
    game, assets, output = args.game.resolve(), args.assets.resolve(), args.output.resolve()
    late_assignment=getattr(args,'late_assignment',False)
    launcher.verify_game(game, community=True, bridge_version=2, unified=True, player_features=args.ordinary_player)
    if args.drop_return_ack and args.retry:
        require(args.ordinary_player and b'BA_RESURRECTION_RETURN_RETRY_V1' in (game/'BattleAcesOffline.dll').read_bytes(),
                'install the explicit owned full-loadout RETURN retry diagnostic helper')
    if late_assignment:
        require(args.ordinary_player and args.retry and game.is_relative_to(ROOT/'local') and b'BA_RESURRECTION_LATE_ASSIGNMENT_V2' in (game/'BattleAcesOffline.dll').read_bytes(),
                'late assignment requires the explicit owned three-intent diagnostic helper')
    practice_path=game/'.battleaces-resurrection/practice-settings.ini'
    practice_before=public_late_assignment.preference(practice_path) if late_assignment else None
    verify_assets(assets);output.mkdir(parents=True, exist_ok=False)
    pki_folder=output/'ephemeral-pki';pki=generate_test_pki(pki_folder)
    credentials, workers, events = Store(), [], []
    audit=Audit(output)
    templates={mode: GameTemplate.load(assets/name, catalog_path=assets/'unit-catalog.json', descriptors_path=assets/'descriptors')
               for mode,name in ((1,'map-1v1.pb.gz'),(2,'map-2v2.pb.gz'),(5,'map-2vai.pb.gz'))}
    catalog=BotCatalog(assets, template=templates[1], rules=RuleBook(assets))
    cosmetic_book=CosmeticCatalog(assets) if args.cosmetics_selection else None
    cosmetic_seed=None;cosmetic_profile=None;queue_selections=[];frozen_matches=[]
    if cosmetic_book:
        require(game.is_relative_to(ROOT/'local'),'cosmetic probe requires a disposable copy')
        seed=json.loads(args.cosmetics_selection.read_bytes());seed=seed.get('state',seed)
        require(seed['catalog_sha256']==cosmetic_book.sha256,'native seed/catalog mismatch')
        cosmetic_seed=cosmetic_book.validate_selection(seed['slots'])
        cosmetic_profile='cosmeticstest_'+secrets.token_hex(6)+'_public'
        folder=game/'.battleaces-resurrection/profiles';folder.mkdir(parents=True,exist_ok=True)
        value=dict(schema=1,build=37822,profile=cosmetic_profile,catalog_sha256=cosmetic_seed.catalog_sha256,slots=cosmetic_seed.slots)
        with (folder/(cosmetic_profile+'.cosmetics.json')).open('xb') as stream:
            stream.write((json.dumps(value,separators=(',',':'))+'\n').encode('ascii'))
    def observe(event, **fields):
        events.append(dict(event=event, observed_at=time.monotonic(), **fields));audit(event, **fields)
        if event=='match_created' and cosmetic_book:
            match=server.rooms[fields['room']].match
            frozen_matches.append(dict(match=fields['match'],cosmetics={slot:dict(catalog_sha256=value.catalog_sha256,slots=value.slots)
                                   for slot,value in match.cosmetics_by_slot.items()}))
    late_probe=public_late_assignment.Probe(args.mode,output,observe) if late_assignment else None
    async def factory(data,bots):
        worker=await SimulationWorker.create(data,assets/'Simulation.dll',working_directory=output,ai=AISetup(assets,bots))
        workers.append(worker);return worker
    server=DedicatedServer(templates[1],ProfileStore(output/'profiles',templates[1],catalog=cosmetic_book),templates=templates,bot_catalog=catalog,
        ai_factory=factory,audit=observe,data_dir=output,audit_state=False,input_timeout=30,
        tls_context=tls.load_server_context(pki['cert'],pki['key']),admission=admission.AdmissionController(credentials))
    process=job=writer=parent=child=bridge_task=None
    delayed=[];delayed_enter=False;dropped_ready=False;dropped_return=False
    fault=None;assignment_peer=None;withheld_bootstrap=False
    log='';launch_tick=None;attempts=0;connection_attempts=[];started=time.monotonic();header_gate=None
    report=dict(passed=False,scope=__doc__,mode=args.mode,unavailable=args.unavailable,visible=args.visible,
                cancel=args.cancel,retry=args.retry,delay_enter_ack=args.delay_enter_ack,
                drop_on_ready=args.drop_on_ready,drop_return_ack=args.drop_return_ack,practice_overlap=args.practice_overlap,
                disconnect=args.disconnect,menu_profile_proof=args.menu_profile_proof,
                local_frames=args.local_frames if args.unavailable or late_assignment else None, local_profile=args.local_profile,
                late_assignment=late_assignment,
                practice_preference_before=practice_before,
                helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest(),
                source_sha256_at_start=source_hashes())
    if args.shared_settings: report['shared_settings_before']=startup_probe.shared_state(args.shared_settings.resolve())
    try:
        port=47623 if args.unavailable else (await server.start('127.0.0.1',0))[1]
        report['server_listener_started']=not args.unavailable
        send=server.community.send
        def controlled_send(peer,kind,payload):
            nonlocal delayed_enter,dropped_return
            if kind==c.ACK:
                reader=c.Reader(payload);request=reader.number('I');command=reader.number('B')
                if args.delay_enter_ack and not delayed_enter and command in (q.ENTER,loadout_protocol.ENTER_LOADOUT):
                    delayed_enter=True
                    def deliver():
                        observe('probe_delayed_enter_ack_delivered',request=request)
                        send(peer,kind,payload)
                    delayed.append(asyncio.get_running_loop().call_later(args.delay_enter_ack,deliver))
                    observe('probe_delayed_enter_ack',request=request,seconds=args.delay_enter_ack)
                    return
                if (args.drop_return_ack or late_assignment) and not dropped_return and command==q.RETURN:
                    require(reader.number('B')==1,'RETURN loss fixture requires an accepted completed return')
                    dropped_return=True;observe('probe_drop_return_ack',request=request,success=True)
                    peer.close('probe lost RETURN acknowledgement');return
            send(peer,kind,payload)
        server.community.send=controlled_send
        apply=server.community.public.apply
        async def controlled_apply(session,kind,command,now):
            nonlocal dropped_ready
            if late_probe is not None and kind==loadout_protocol.ENTER_LOADOUT and command['ticket']==1:
                late_probe.attach_peer(session.peer)
            if (args.drop_return_ack or late_assignment) and args.retry and kind==q.RETURN:
                observe('probe_return_request',**command)
            result=await apply(session,kind,command,now)
            if cosmetic_book and kind==loadout_protocol.ENTER_LOADOUT:
                entry=server.community.public.entries[session.peer.profile_id]
                queue_selections.append(dict(ticket=entry.ticket,deck=entry.deck,catalog_sha256=entry.cosmetics.catalog_sha256,slots=entry.cosmetics.slots))
            if args.drop_on_ready and not dropped_ready and kind==q.READY:
                dropped_ready=True;observe('probe_drop_after_ready',ticket=command['ticket'])
                session.peer.close('probe connection lost after READY commit')
            return result
        server.community.public.apply=controlled_apply
        context=tls.load_client_context(pki['ca'],'localhost')
        async def resolve():
            nonlocal attempts
            attempts+=1
            observed=read_native_log(game,process.pid,since_tick=launch_tick)
            attempt=dict(attempt=attempts,play_observed='PUBLIC QUEUE SMOKE original OnMapSelected:' in observed,
                         header_gate_released=header_gate is not None and header_gate.exists(),
                         world_acquired='Client world acquired:' in observed,log_offset=len(observed))
            connection_attempts.append(attempt);observe('probe_resolve_attempt',**attempt)
            if args.unavailable or late_assignment and attempts==2: raise bridge.RemoteUnavailable()
            return bridge.Remote('127.0.0.1',port,context,credentials.player,credentials.token)
        config=dict(game_directory=game,server_host='127.0.0.1',server_port=port,display_name='Public Config Player',room='community')
        if cosmetic_book:config['local_profile']=cosmetic_profile
        options=client.player_options() if args.ordinary_player else argparse.Namespace(run_name='public-queue-probe',unified_experimental=True)
        parent,child=socket.socketpair(socket.AF_INET);parent.setblocking(False)
        reader,writer=await asyncio.open_connection(sock=parent)
        command=launcher.game_arguments(config,None,child.fileno(),options)
        if args.ordinary_player:
            require('-public-queue-experimental' in command and '-local-cosmetics-experimental' in command and
                    not any('smoke' in value or 'audit' in value or 'auto-' in value for value in command),
                    'ordinary player options omit features or include automation')
            report['ordinary_player_base_arguments']=list(command)
        command[command.index('-logFile')+1]=str(output/'game.log')
        if not args.ordinary_player: command.append('-public-queue-experimental')
        command+=['-public-queue-smoke',f'-public-queue-smoke-mode={args.mode}',
                  '-lan-smoke','-lan-audit','-dedicated-rematch-smoke']
        if not args.unavailable: command+=['-match-search-smoke']
        if args.cancel: command+=['-public-queue-smoke-cancel='+args.cancel]
        if args.retry: command+=['-public-queue-smoke-retry']
        if (args.drop_return_ack and args.retry) or late_assignment:command.append('-public-return-retry-smoke')
        if late_assignment:command.append('-public-late-assignment-smoke')
        if args.disconnect in ('loading','running'): command+=['-dedicated-recovery-smoke']
        if args.practice_overlap: command+=['-public-queue-smoke-practice-overlap']
        if args.mode==1:
            command+=['-dedicated-surrender-smoke','-dedicated-surrender-frame=1200']
        if cosmetic_book:
            if not args.ordinary_player: command.append('-local-cosmetics-experimental')
            command+=['-community-cosmetics-smoke','-human-cosmetics-smoke']
        if args.edit_loadout_after_play:command+=['-public-loadout-edit-smoke']
        if args.menu_profile_proof:
            key=secrets.token_hex(16)
            header_gate=game/'investigation/runtime'/f'public-queue-{key}.ready'
            command+=['-menu-profile-proof','-public-queue-smoke-gate='+key]
        if args.unavailable or late_assignment:
            command+=['-practice-ai-smoke','-public-ai-smoke','-practice-ai-smoke-matches=1',f'-practice-ai-smoke-frames={args.local_frames}']
            if args.local_profile: command += [f'-public-ai-smoke-profile={args.local_profile}']
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=1 if args.visible else 0
        startup.lpAttributeList={'handle_list':[child.fileno()]}
        clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong;launch_tick=clock()
        child.set_inheritable(True)
        try: process=subprocess.Popen(command,cwd=game,startupinfo=startup,close_fds=True,creationflags=0 if args.visible else subprocess.CREATE_NO_WINDOW)
        finally: child.set_inheritable(False)
        job=_WindowsJob(process.pid);child.close()
        if late_probe is not None:
            transport=public_late_assignment.WitnessBridge(reader,writer,resolve,version=2,observe=observe)
            late_probe.transport=transport
        else:transport=bridge.Bridge(reader,writer,resolve,version=2)
        bridge_task=asyncio.create_task(transport.run())
        report.update(game_pid=process.pid,launch_tick=launch_tick,client_arguments=command)
        (output/'processes.json').write_text(json.dumps(report,indent=2)+'\n')
        shutil.copyfile(game/'.battleaces-resurrection/patch-manifest.json',output/'patch-manifest.json')
        preworld=(bool(args.cancel) or args.drop_on_ready or args.disconnect=='assignment') and not args.retry
        disconnected_only=bool(args.disconnect) and not args.retry
        marker=(f'Practice returned: completed=1 mode={args.mode}' if args.unavailable else
                'Public intent retired: ticket=3 reason=returned nativeIdle=1 disconnect=0' if late_assignment else
                'Public intent retired: ticket=2 reason=returned nativeIdle=1 disconnect=0' if args.drop_return_ack and args.retry else
                'Public intent retired: ticket=1' if preworld or disconnected_only or (args.drop_return_ack and not args.retry) else 'PUBLIC QUEUE completed return:')
        while True:
            require(process.poll() is None,'owned game exited before native return')
            log=read_native_log(game,process.pid,since_tick=launch_tick)
            if header_gate is not None and 'MENU PROFILE PROOF passed: ' in log and not header_gate.exists():
                with header_gate.open('xb') as stream:stream.write(b'owned initial header observed\n')
            for failure in ('Public client failure:', 'Client lifecycle invariant failed:', 'Practice stopped in ', 'Local menu header binding failed:'):
                require(failure not in log,'native public failure: '+failure)
            if late_probe is not None:await late_probe.maybe_inject(log)
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
            if marker in log:
                # Re-read the current original binding after Continue, rather
                # than accepting a header observed only before the match.
                profile_rows=[line for line in log.splitlines() if 'MENU PROFILE PROOF passed: ' in line]
                if not args.menu_profile_proof or len(profile_rows)>=2 and log.rfind('MENU PROFILE PROOF passed: ')>log.rfind(marker):break
            require(time.monotonic()-started<args.timeout,'native public queue/match/Continue timed out')
            await asyncio.sleep(.02 if args.disconnect and fault is None else .2)
        require('PUBLIC QUEUE SMOKE original OnMapSelected:' in log,'original public button missing')
        if not preworld: require('Native search joining signal:' in log,'original native loading handoff missing')
        if args.cancel:
            require(log.count('PUBLIC QUEUE SMOKE cancellation:')==1 and 'Native search original Cancel invoked:' in log,
                    'original Cancel callback/intent missing or duplicated')
        if args.drop_on_ready: require(dropped_ready,'READY disconnect injection missing')
        if args.drop_return_ack or late_assignment:
            require(dropped_return and 'reason=connection lost after return nativeIdle=1' in log,
                    'RETURN disconnect did not retire the completed native match')
            require('identity=public-error:' not in log,'completed match displayed an incorrect start-failure notice')
        if args.practice_overlap:
            require('PUBLIC QUEUE SMOKE practice overlap rejected:' in log,'practice/public ownership check missing')
        if args.delay_enter_ack:
            require(delayed_enter and any(row['event']=='probe_delayed_enter_ack_delivered' for row in events),
                    'delayed acknowledgement was not delivered')
        if args.retry:
            require(log.count('Public search intent:')==(3 if late_assignment else 2) and 'Native search stale ticket rejected:' in log,
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
            if args.menu_profile_proof:
                require(attempts==2 and
                        not connection_attempts[0]['play_observed'] and not connection_attempts[0]['header_gate_released'] and
                        connection_attempts[1]['play_observed'] and connection_attempts[1]['header_gate_released'] and
                        not any(row['world_acquired'] for row in connection_attempts),
                        'gated unavailable route must have one startup and one Play attempt,none during the local world')
            else:require(attempts==1,'unavailable public intent attempted multiple connections')
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
                if args.local_profile: require(army['players'][0]['aiProfileId']==args.local_profile,'forced fallback qualification profile not used')
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
            return_retry=args.drop_return_ack and args.retry
            multi_remote=return_retry or late_assignment
            maximum=2 if late_assignment or args.retry and (args.cancel=='after-ready' or args.drop_on_ready or args.disconnect or args.drop_return_ack) else 1
            require(1<=len(workers)<=maximum and 1<=credentials.calls<=(2 if args.retry else 1),
                    'unexpected authenticated match/worker count')
            finished=[row for row in events if row['event']=='match_completed']
            require(len(finished)==(2 if multi_remote else 1),'duplicate/missing completed match')
            match=finished[-1]['match']
            offered=next(row for row in events if row['event']=='public_match_offered' and row['match']==match)
            ticket=offered['tickets'][0]
            entered=next(row for row in events if row['event']=='public_queue_entered' and row['ticket']==ticket)
            require(29<=offered['observed_at']-entered['observed_at']<=33,'server fallback did not use real30-second queue wait')
            require(not server.community.public.entries and not server.community.public.offers,'native RETURN retained ticket/offer')
            expected_worlds=2 if multi_remote or args.retry and args.disconnect in ('loading','running') else 1
            require('Public native match joined:' in log and 'Public native return:' in log and 'owner=remote' in log and
                    (late_assignment or 'owner=local-practice' not in log) and log.count('Client world acquired:')==(3 if late_assignment else expected_worlds) and
                    log.count('owner=remote nativeIdle=1')==expected_worlds,
                    'remote native lifecycle missing/overlapped')
            receipts=game/'investigation/runtime'/f'dedicated-receipts-{process.pid}-{match}.tsv'
            rows=list(csv.DictReader(receipts.read_text(encoding='utf-8').splitlines(),delimiter='\t'))
            authoritative={row['frame']:row['frame_payload_sha256'] for row in events if row['event']=='frame_queued' and row['match']==match}
            require(len(rows)>=600 and len(rows)==len(authoritative),'native receipt count differs from server frames')
            for row in rows: require(row['sha256']==authoritative[int(row['frame'])],'native public receipt differs from server input frame')
            shutil.copyfile(receipts,output/receipts.name)
            seconds=elapsed_seconds(log,ticket)
            result=finished[-1]['result']
            report.update(match=match,received_frames=len(rows),result=result,real_queue_seconds=offered['observed_at']-entered['observed_at'],
                          native_elapsed_seconds=seconds)
            if multi_remote:
                require(len(workers)==credentials.calls==2 and attempts==(3 if late_assignment else 2),'completed retry requires exact remote sessions/workers')
                completed_matches=[]
                for completed in finished:
                    key=completed['match']
                    offer=next(row for row in events if row['event']=='public_match_offered' and row['match']==key)
                    generation=offer['tickets'][0]
                    enter=next(row for row in events if row['event']=='public_queue_entered' and row['ticket']==generation)
                    wait=offer['observed_at']-enter['observed_at']
                    require(29<=wait<=33,'completed RETURN retry skipped a real30-second queue wait')
                    path=game/'investigation/runtime'/f'dedicated-receipts-{process.pid}-{key}.tsv'
                    native=list(csv.DictReader(path.read_text(encoding='utf-8').splitlines(),delimiter='\t'))
                    frames={row['frame']:row['frame_payload_sha256'] for row in events if row['event']=='frame_queued' and row['match']==key}
                    require(len(native)>=600 and len(native)==len(frames) and
                            [int(row['frame']) for row in native]==sorted(frames) and
                            all(row['sha256']==frames[int(row['frame'])] for row in native),
                            'completed RETURN retry native frames differ from authoritative input')
                    shutil.copyfile(path,output/path.name)
                    completed_matches.append(dict(match=key,ticket=generation,received_frames=len(native),result=completed['result'],
                        real_queue_seconds=wait,native_elapsed_seconds=elapsed_seconds(log,generation)))
                report['completed_matches']=completed_matches
                if return_retry:report['return_retry']=public_return_evidence.validate(log,args.mode,completed_matches,events)
                if late_assignment:
                    report['late_assignment_evidence']=public_late_assignment.validate(log,args.mode,completed_matches,events,late_probe.capture,late_probe.injection,practice_before['profile'])
                    report['local_fallback_evidence']=public_late_assignment.local_evidence(log,args.mode,late_probe.injection,
                        list(queue_selections[0]['deck']),list(cosmetic_seed.keys))
        if cosmetic_book:
            prefix='HUMAN COSMETICS frozen message: ' if args.unavailable else 'REMOTE COSMETICS frozen snapshot: '
            snapshots=[json.loads(line.split(prefix,1)[1]) for line in log.splitlines() if prefix in line]
            if args.unavailable:
                require('HUMAN COSMETICS SimPlayer passed:' in log and len(snapshots)==2,'local full native map/unit proof missing')
                human=next(army for army in armies if army.get('armyId',0)==0)
                require(human['deck']==snapshots[0]['deck'] and snapshots[0]['deck']==snapshots[1]['deck'],'local config/join frozen deck mismatch')
                expected_items=list(cosmetic_seed.keys)
                require(human['deck']['entitlements']==[dict(cosmeticAssetKeys=expected_items)],'local fallback lost original cosmetic intent')
            else:
                observed_matches=re.findall(r'REMOTE COSMETICS SimPlayer passed: match=([0-9a-f]{32}) ',log)
                require(len(observed_matches)==len(snapshots) and len(set(observed_matches))==len(observed_matches),
                        'duplicate/missing correlated native full-map proof')
                require(all(cosmetic_book.validate_selection(value['slots'])==cosmetic_seed for value in snapshots),
                        'remote native appearance differs from Play intent')
                require(all(cosmetic_book.validate_selection(value['slots'])==cosmetic_seed for value in queue_selections),
                        'server entry lost original full intent')
                require(all(cosmetic_book.validate_selection(value['slots'])==cosmetic_seed
                            for match in frozen_matches for value in match['cosmetics'].values()),
                        'server match did not freeze original human appearance')
                require(set(observed_matches)<={match['match'] for match in frozen_matches},'native proof refers to an unowned match')
                if report.get('match'):require(report['match'] in observed_matches,'completed remote match lacks native full map/unit proof')
                if args.drop_return_ack and args.retry or late_assignment:
                    require(set(observed_matches)=={row['match'] for row in report['completed_matches']},
                            'both finished RETURN retry matches require original native full-loadout proof')
            if args.edit_loadout_after_play:
                original=[json.loads(line.split('PUBLIC LOADOUT original frozen deck: ',1)[1]) for line in log.splitlines() if 'PUBLIC LOADOUT original frozen deck: ' in line]
                require(len(original)==1 and 'PUBLIC LOADOUT edited after freeze: originalIntentRetained=1' in log,'post-Play native edit not exercised')
                changes=[json.loads(line.split('HUMAN COSMETICS rematch equipped: ',1)[1]) for line in log.splitlines() if 'HUMAN COSMETICS rematch equipped: ' in line]
                require(len(changes)==1,'post-Play cosmetic edit missing')
                changed=cosmetic_book.validate_selection(changes[0]['slots']);require(changed!=cosmetic_seed,'post-Play cosmetic edit had no effect')
                edited=[json.loads(line.split('PUBLIC LOADOUT edited menu deck: ',1)[1]) for line in log.splitlines() if 'PUBLIC LOADOUT edited menu deck: ' in line]
                require(len(edited)==1 and edited[0]['units']!=original[0]['units'],'post-Play unit edit missing')
                if args.unavailable:
                    require(human['deck']==original[0],'local fallback replaced its original deck after waiting')
                    original_joins=[json.loads(line.split('Practice original JoinArmy: ',1)[1]) for line in log.splitlines() if 'Practice original JoinArmy: ' in line]
                    require(original_joins[0]['deck']['units']!=original[0]['units'],'native selected deck was not actually changed before fallback JoinArmy')
                else:
                    require(len(queue_selections)==len(frozen_matches)==1,'post-Play single-intent queue/match proof missing')
                    require(list(queue_selections[0]['deck'])==original[0]['units'],'server queue accepted a later deck instead of Play intent')
                    deadline=time.monotonic()+8
                    while True:
                        saved=server.profiles.load_state(credentials.player,[])
                        if saved.cosmetics==changed and list(saved.deck)==edited[0]['units']:break
                        require(time.monotonic()<deadline,'changed menu units and appearance were not republished after public return')
                        await asyncio.sleep(.1)
                    report['post_return_menu_loadout']=dict(deck=list(saved.deck),cosmetics=list(changed.slots))
            report['full_loadouts']=dict(catalog=cosmetic_book.sha256,local_profile=cosmetic_profile,queue=queue_selections,
                server_matches=frozen_matches,native_snapshots=snapshots,post_play_edit=args.edit_loadout_after_play)
        if args.menu_profile_proof:
            rows=[json.loads(line.split('MENU PROFILE PROOF passed: ',1)[1]) for line in log.splitlines()
                  if 'MENU PROFILE PROOF passed: ' in line]
            require(len(rows)>=2 and [row['sequence'] for row in rows]==list(range(1,len(rows)+1)),
                    'missing initial/post-match header proof')
            require(all(row['name']==row['label']==config['display_name'] and row['owned'] and row['worldIdle'] and
                        not row['networkRequest'] and row['capture'] and row['renderStateRestored'] for row in rows),
                    'configured header changed across the match')
            captures=[]
            for row in rows:
                name=f'menu-profile-{process.pid}-{row["sequence"]}.png'
                capture=(game/'investigation/runtime'/name).read_bytes()
                require(capture.startswith(b'\x89PNG\r\n\x1a\n'),'header capture missing/invalid')
                (output/name).write_bytes(capture)
                captures.append(dict(file=name,sha256=hashlib.sha256(capture).hexdigest()))
            report['menu_profile']=dict(proofs=rows,captures_requiring_visual_review=captures)
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
                (output/f'native-{process.pid}.log').write_bytes(log.encode('utf-8'))
            except Exception as error:
                report.update(passed=False,evidence_error=f'{type(error).__name__}: {error}')
            for name in re.findall(r'file=(match-search-\d+-\d+-\d+-\w+\.png)',log):
                source=game/'investigation/runtime'/name
                if source.is_file(): shutil.copyfile(source,output/name)
        if job is not None: job.close()
        if header_gate is not None and header_gate.exists():header_gate.unlink()
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
            remote_attempts=attempts,authentications=credentials.calls,connection_attempts=connection_attempts,
            worker_exit_codes=[worker.process.poll() for worker in workers],cleanup='forced owned termination, not native Quit',
            worker_cleanup=cleanup,source_sha256_at_finish=source_hashes())
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        workers_ok=all(row['passed'] for row in cleanup)
        if not workers_ok: report.setdefault('error','worker cleanup failed; see worker_cleanup evidence')
        report['passed'] &= report['source_files_unchanged'] and report['owned_process_reaped'] and workers_ok
        if args.shared_settings:
            report['shared_settings_after']=startup_probe.shared_state(args.shared_settings.resolve())
            report['shared_settings_unchanged']=report['shared_settings_before']==report['shared_settings_after']
            report['passed'] &= report['shared_settings_unchanged']
        if late_probe is not None:
            report.update(late_assignment_capture=late_probe.capture,late_assignment_injection=late_probe.injection,
                          queue_loadouts_observed=queue_selections,server_frozen_loadouts_observed=frozen_matches)
            try:
                report['practice_preference_after']=public_late_assignment.preference(practice_path)
                report['practice_preference_unchanged']=report['practice_preference_after']==practice_before
                report['passed'] &= report['practice_preference_unchanged']
            except Exception as error:
                report.update(passed=False,practice_preference_error=repr(error))
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','error','elapsed_seconds','received_frames','worker_exit_codes') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('game','assets','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--mode',type=int,choices=(1,2,5),default=1)
    parser.add_argument('--timeout',type=int,default=600)
    parser.add_argument('--unavailable',action='store_true')
    parser.add_argument('--local-frames',type=int,default=3600,
                        help='diagnostic fallback surrender frame; allow original bot build-up before requiring movement')
    parser.add_argument('--local-profile',type=int,choices=(58,62,63,64),
                        help='explicit unavailable1v1 qualification profile; ordinary public selection remains random')
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--ordinary-player',action='store_true',help='use the ordinary Start Client feature options before adding owned automation')
    parser.add_argument('--shared-settings',type=Path,help='read-only baseline; require original shared native settings to stay unchanged')
    parser.add_argument('--cancel',choices=('before-enter','waiting','offered','after-ready'))
    parser.add_argument('--retry',action='store_true')
    parser.add_argument('--delay-enter-ack',type=float,default=0)
    parser.add_argument('--drop-on-ready',action='store_true')
    parser.add_argument('--drop-return-ack',action='store_true')
    parser.add_argument('--late-assignment',action='store_true',help='remote/local/remote: replay original assignment during fallback and prove later stream drainage')
    parser.add_argument('--disconnect',choices=('assignment','loading','running'),
                        help='close first owned TLS peer at a native-observed stage; test cleanup and optional explicit retry')
    parser.add_argument('--practice-overlap',action='store_true')
    parser.add_argument('--cosmetics-selection',type=Path,help='accepted native full-map proof; enables complete public protocol')
    parser.add_argument('--edit-loadout-after-play',action='store_true',help='change native units/cosmetics after freeze to verify original intent survives')
    parser.add_argument('--menu-profile-proof',action='store_true',help='read and capture the configured header before and after a complete match')
    args=parser.parse_args()
    require(not args.ordinary_player or (args.cosmetics_selection and args.shared_settings),
            'ordinary player qualification requires a full native cosmetic selection/catalog and shared-settings baseline')
    require(os.name=='nt' and args.output.resolve().is_relative_to(ROOT/'local') and 120<=args.timeout<=(1800 if args.late_assignment else 900),'bounded Windows/ignored probe required')
    require(1200<=args.local_frames<=7200 and (not args.local_profile or args.unavailable and args.mode==1),
            'bounded local frames and unavailable1v1-only profile override required')
    require(0<=args.delay_enter_ack<=8 and (not args.retry or args.cancel or args.drop_on_ready or args.drop_return_ack or args.disconnect or args.late_assignment),'bounded delay/retry point required')
    require(not args.late_assignment or (args.retry and args.ordinary_player),'late assignment requires ordinary full-loadout retry')
    require(sum(map(bool,(args.unavailable,args.cancel,args.drop_on_ready,args.drop_return_ack,args.disconnect,args.late_assignment)))<=1,
            'choose one unavailable/cancel/disconnect scenario')
    require(not args.edit_loadout_after_play or (args.cosmetics_selection and not any((args.cancel,args.retry,args.drop_on_ready,args.drop_return_ack,args.disconnect))),
            'post-Play edit requires a full single-intent remote/unavailable probe')
    require(not args.menu_profile_proof or not any((args.cancel,args.retry,args.drop_on_ready,args.drop_return_ack,args.disconnect)),
            'header proof requires a complete single match')
    return asyncio.run(run(args))


if __name__=='__main__': raise SystemExit(main())
