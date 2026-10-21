"""Three owned native clients: two original invites and one original Accept.

Loopback-development fixtures and explicit diagnostic callbacks only. No
ordinary launcher, TLS, protected enrollment, physical controls or Quit claim.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import traceback

from client_patch.transport.launcher import verify_game
from server.assets import verify_assets
from server.dedicated_server import Audit, DedicatedServer
from server.game_data import GameTemplate
from server.profiles import ProfileStore
from server import community_protocol as wire
from server.worker_client import _WindowsJob
from tools.run_secure_match import read_native_log
from tools.verify_custom_lobby import require, source_hashes as core_hashes
from tools.verify_native_quit import verify_build_receipt
from tools.verify_packaged_play import job_accounting
from tools import verify_unified_startup as startup

ROOT=Path(__file__).resolve().parents[1]


def sources():
    names=('tools/verify_custom_multisender.py','tools/run_secure_match.py','tools/verify_native_quit.py',
           'tools/verify_packaged_play.py','tools/verify_unified_startup.py')
    return core_hashes() | {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}


def settled_evidence(logs,profiles,lobbies,events):
    """Cross-check the three native owners against live server group authority."""
    target=profiles['target']
    rows=re.findall(r'MULTI INVITE target accepted original popup: invite=([0-9a-f]{32}) sender=(\S+) lobby=([0-9a-f]{32}) received=2 pendingDelta=1',logs['target'])
    require(len(rows)==1,'one original target Accept with two incoming invitations required')
    invite,sender,lobby=rows[0]
    require(sender in (profiles['first'],profiles['second']),'accepted sender is not one of the two owned inviters')
    selected='first' if sender==profiles['first'] else 'second'
    other='second' if selected=='first' else 'first'
    require(f'MULTI INVITE target settled: sender={sender} lobby={lobby} members=2 replyCounter=0 incoming=0 popup=0 world=0' in logs['target'],
            'target native lobby/popup/counter did not settle')
    hosts={}
    for role in ('first','second'):
        rows=re.findall(r'MULTI INVITE host settled: role=(\w+) invite=([0-9a-f]{32}) lobby=([0-9a-f]{32}) status=(\d+) members=(\d+) replyCounter=0 sent=0 world=0 partyUnchanged=([01])',logs[role])
        require(len(rows)==1 and rows[0][0]==role,'one settled native inviter owner required')
        _,identity,room,status,members,unchanged=rows[0]
        require((int(status),int(members))==((wire.ACCEPTED,2) if role==selected else (wire.BUSY,1)),
                'native invitation resolution/group differs from chosen sender')
        require(role==selected or unchanged=='1','unselected inviter native Party changed')
        hosts[role]=dict(invite=identity,lobby=room,status=int(status),members=int(members),party_unchanged=unchanged=='1')
        require(room in lobbies and len(lobbies[room].members)==int(members) and lobbies[room].host==profiles[role] and
                set(lobbies[room].members)==({sender,target} if role==selected else {profiles[role]}),
                'live server lobby moved an unrelated player or lost the accepted group')
    require(len(lobbies)==2 and len({host['invite'] for host in hosts.values()})==2 and
            hosts[selected]['invite']==invite and hosts[selected]['lobby']==lobby,
            'accepted native invitation differs from its authoritative lobby')
    created=[e for e in events if e['event']=='custom_invite_created']
    ended=[e for e in events if e['event']=='custom_invite_resolved']
    require(len(created)==len(ended)==2 and {e['sender'] for e in created}=={profiles['first'],profiles['second']} and
            all(e['target']==target for e in created),'both simultaneous invitations were not created for the target')
    by_id={e['invite']:e['status'] for e in ended}
    require(by_id=={hosts[selected]['invite']:wire.ACCEPTED,hosts[other]['invite']:wire.BUSY},
            'server did not accept one and retire precisely the other invitation')
    return dict(selected_role=selected,unselected_role=other,target=target,selected_lobby=lobby,hosts=hosts,
                native_reply_counter=0,native_incoming_invites=0,native_popup_released=True,
                native_unselected_party_unchanged=True,simulation_workers=0)


async def run(args):
    game,assets,output=(path.resolve() for path in (args.game,args.assets,args.output))
    require(os.name=='nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'),
            'owned ignored Windows paths required')
    require(60<=args.timeout<=300,'bounded diagnostic timeout required')
    verify_game(game,community=True);verify_assets(assets)
    helper=game/'BattleAcesOffline.dll';helper_hash=hashlib.sha256(helper.read_bytes()).hexdigest()
    require(b'MULTI INVITE target accepted original popup:' in helper.read_bytes(),'install the explicit multisender diagnostic helper')
    receipt=verify_build_receipt(game,args.helper_build_receipt.resolve())
    manifest=(game/'.battleaces-resurrection/patch-manifest.json').read_bytes()
    output.mkdir(parents=True,exist_ok=False)
    (output/'patch-manifest.json').write_bytes(manifest)
    audit=Audit(output);events=[]
    def observe(event,**fields):
        events.append(dict(event=event,**fields));audit(event,**fields)
    async def unexpected_match(_):raise AssertionError('invitation-only diagnostic must not create a match worker')
    template=GameTemplate.load(assets/'map-1v1.pb.gz',catalog_path=assets/'unit-catalog.json',descriptors_path=assets/'descriptors')
    server=DedicatedServer(template,ProfileStore(output/'profiles',template),audit=observe,
                           sim_factory=unexpected_match,data_dir=output,lobby_timeout=300)
    profiles={role:'multi_'+role+'_'+secrets.token_hex(12) for role in ('first','second','target')}
    names={'first':'<b>First inviter</b>','second':'Second inviter','target':'Target player'}
    original_send=server.community.send;timers=[]
    def send(peer,kind,payload):
        if kind==wire.ACK and len(payload)>=5 and payload[4] in (wire.INVITE,wire.REPLY):
            timers.append(asyncio.get_running_loop().call_later(.35,original_send,peer,kind,payload))
        else:original_send(peer,kind,payload)
    server.community.send=send
    processes=[];jobs=[];started=time.monotonic()
    report=dict(passed=False,scope=__doc__,profiles=profiles,helper_sha256=helper_hash,helper_build=receipt,
                source_sha256_at_start=sources(),clients=[],forced_cleanup=True,natural_quit=False)
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong
    try:
        report['shared_before']=startup.shared_state(args.shared_settings.resolve())
        address=await server.start('127.0.0.1',0)
        for role in ('first','second','target'):
            command=[str(game/'Battle Aces.exe'),'-offline-lan','-dedicated-community',
                '-dedicated-server=127.0.0.1:'+str(address[1]),'-local-profile=nativeprobe_'+secrets.token_hex(8),
                '-player-id='+profiles[role],'-player-name='+names[role],'-community-multisender-smoke',
                '-community-multisender-role='+role,'-community-multisender-target='+profiles['target'],
                '-screen-fullscreen','0','-screen-width','960','-screen-height','540','-logFile',str(output/(role+'-game.log'))]
            info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=1 if args.visible else 0
            tick=clock();process=subprocess.Popen(command,cwd=game,startupinfo=info,
                creationflags=0 if args.visible else subprocess.CREATE_NO_WINDOW,close_fds=True)
            owned=dict(role=role,process=process,tick=tick,job=None)
            processes.append(owned) # Retain ownership even if job attachment fails.
            owned['job']=_WindowsJob(process.pid)
            report['clients'].append(dict(role=role,pid=process.pid,launch_tick=tick,arguments=command))
            (output/'processes.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        ready_at=None
        while True:
            require(all(row['process'].poll() is None for row in processes),'native actor exited before settled evidence')
            logs={row['role']:read_native_log(game,row['process'].pid,since_tick=row['tick']) for row in processes}
            require(not any('Offline loop stopped in ' in log or 'Local menu initialization failed:' in log for log in logs.values()),
                    'native multisender probe failed;inspect retained native logs')
            settled=all(('MULTI INVITE target settled:' if role=='target' else 'MULTI INVITE host settled:') in log
                        for role,log in logs.items())
            if settled:
                require(len(server.community.sessions)==3 and not server.community.invites and not server.rooms and
                        not any(e['event']=='worker_started' for e in events),'invitation-only run retained invites or allocated a match')
                evidence=settled_evidence(logs,profiles,server.community.lobbies,events)
                ready_at=ready_at or time.monotonic()
                if time.monotonic()-ready_at>=1:
                    report.update(passed=True,evidence=evidence);break
            require(time.monotonic()-started<args.timeout,'multisender diagnostic deadline')
            await asyncio.sleep(.1)
    except BaseException as error:
        report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        cleanup_errors=[]
        for row in processes:
            process=row['process']
            try:(output/('native-'+row['role']+'.log')).write_text(read_native_log(game,process.pid,since_tick=row['tick'])+'\n',encoding='utf-8')
            except Exception as error:cleanup_errors.append('capture '+row['role']+': '+repr(error))
            try:
                if process.poll() is None:process.terminate()
            except OSError as error:cleanup_errors.append('terminate '+row['role']+': '+repr(error))
        for row in processes:
            process=row['process']
            try:process.wait(timeout=15)
            except Exception as error:cleanup_errors.append('wait '+row['role']+': '+repr(error))
            finally:
                if row['job'] is not None:
                    try:jobs.append(dict(role=row['role'],**job_accounting(row['job'].handle)))
                    except Exception as error:cleanup_errors.append('job '+row['role']+': '+repr(error))
                    finally:row['job'].close()
            if process.poll() is None:
                try:process.wait(timeout=15)
                except Exception as error:cleanup_errors.append('post-job wait '+row['role']+': '+repr(error))
        for timer in timers:timer.cancel()
        try:await asyncio.wait_for(server.close(),15)
        except Exception as error:cleanup_errors.append('server close: '+repr(error))
        finally:audit.close()
        report.update(jobs=jobs,owned_processes_reaped=all(row['process'].poll() is not None for row in processes),
            source_sha256_at_finish=sources(),elapsed_seconds=time.monotonic()-started,
            helper_unchanged=hashlib.sha256(helper.read_bytes()).hexdigest()==helper_hash,
            manifest_unchanged=(game/'.battleaces-resurrection/patch-manifest.json').read_bytes()==manifest)
        try:report['shared_after']=startup.shared_state(args.shared_settings.resolve())
        except OSError as error:cleanup_errors.append('shared state: '+repr(error))
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['shared_settings_unchanged']=report.get('shared_before')==report.get('shared_after') and 'shared_before' in report and 'shared_after' in report
        report['cleanup_errors']=cleanup_errors
        report['passed'] &= (report['source_files_unchanged'] and report['shared_settings_unchanged'] and
            report['owned_processes_reaped'] and report['helper_unchanged'] and report['manifest_unchanged'] and
            not cleanup_errors and len(jobs)==3 and all(job['active_processes']==0 for job in jobs))
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('passed','error','elapsed_seconds') if key in report}),flush=True)
    return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('game','assets','output','helper-build-receipt','shared-settings'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--visible',action='store_true')
    return asyncio.run(run(parser.parse_args()))


if __name__=='__main__':raise SystemExit(main())
