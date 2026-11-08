"""Owned native version rejection -> persistent overlay -> playable offline AI.

Uses ephemeral TLS and an in-memory identity. Forced owned teardown does not
qualify natural Quit or a physical installer/player test. Inspect the retained
Unity screenshot before claiming rendered appearance.
"""
import argparse
import asyncio
import ctypes
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import traceback

from client_patch.transport import launcher, bridge
from server import tls_transport as tls
from server.admission import AdmissionController
from server.dedicated_server import DedicatedServer
from server.profiles import ProfileStore
from server.worker_client import _WindowsJob
from tests.synthetic import template
from tests.test_admission import Store
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools.run_secure_match import read_native_log

ROOT=Path(__file__).resolve().parents[1]
MESSAGE='Client update required.\nDownload the latest installer from GitHub Releases.'


async def run(args):
    game,output=args.game.resolve(),args.output.resolve()
    if not game.is_relative_to(ROOT/'local') or not output.is_relative_to(ROOT/'local'):
        raise ValueError('Use an owned game and a fresh output under local/')
    launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True)
    output.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,output/'verifier-source.py')
    pki=generate_test_pki(output/'ephemeral-pki');store=Store();events=[]
    fixture=template()
    server=DedicatedServer(fixture,ProfileStore(output/'profiles',fixture),
        tls_context=tls.load_server_context(pki['cert'],pki['key']),admission=AdmissionController(store),
        minimum_client_revision=2,client_update_message=MESSAGE,
        audit=lambda event,**fields:events.append(dict(event=event,**fields)))
    process=job=writer=parent=child=task=None; log=''; started=time.monotonic()
    report=dict(passed=False,scope=__doc__,helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest(),
                expected_message=MESSAGE,minimum_client_revision=2,
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),render_window=args.render_window)
    try:
        address=await server.start('127.0.0.1',0)
        remote=bridge.Remote('127.0.0.1',address[1],tls.load_client_context(pki['ca'],'localhost'),store.player,store.token)
        config=dict(game_directory=game,display_name='Update notice probe',server_host='127.0.0.1',server_port=address[1],
                    room='community',local_profile='version_notice_probe',fullscreen=False)
        options=argparse.Namespace(run_name='update-notice',unified_experimental=True,player_features=True,audit=True,smoke=True)
        parent,child=socket.socketpair(socket.AF_INET);parent.setblocking(False)
        reader,writer=await asyncio.open_connection(sock=parent)
        command=launcher.game_arguments(config,None,child.fileno(),options)
        command[command.index('-logFile')+1]=str(output/'game.log')
        command+=['-public-queue-smoke','-public-queue-smoke-mode=1',
                  '-practice-ai-smoke','-public-ai-smoke','-practice-ai-smoke-matches=1',
                  '-practice-ai-smoke-frames=1200','-client-update-overlay-smoke']
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow=4 if args.render_window else 0  # SW_SHOWNOACTIVATE for visual qualification.
        startup.lpAttributeList={'handle_list':[child.fileno()]}
        clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong;launch_tick=clock()
        child.set_inheritable(True)
        try:process=subprocess.Popen(command,cwd=game,startupinfo=startup,close_fds=True,creationflags=subprocess.CREATE_NO_WINDOW)
        finally:child.set_inheritable(False)
        job=_WindowsJob(process.pid);child.close()
        task=asyncio.create_task(bridge.Bridge(reader,writer,remote,version=2).run())
        report['pid']=process.pid
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            if process.poll() is not None:raise AssertionError('owned game exited before proof')
            log=await asyncio.to_thread(read_native_log,game,process.pid,since_tick=launch_tick)
            for failure in ('Practice stopped in ','Client lifecycle invariant failed:','Match loading UI failed:'):
                if failure in log:raise AssertionError('native failure: '+failure)
            persisted=re.search(r'Client update overlay persisted: ageMs=(\d+) nativeVisible=1 inputBlocked=0 text=(.*)',log)
            captures=re.findall(r'file=(match-loading-\d+-\d+-\d+-persistent-after-12s\.png)',log)
            frames=[int(value) for value in re.findall(r'Offline frame (\d+) submitted;',log)]
            ready=(persisted is not None and 'owner=local-practice' in log and frames and max(frames)>=199)
            if ready and captures:
                source=game/'investigation/runtime'/captures[-1]
                if source.is_file() and source.stat().st_size>1000:
                    if json.loads(persisted[2])!=MESSAGE or int(persisted[1])<12000:
                        raise AssertionError('persistent text/age differs')
                    shutil.copyfile(source,output/source.name)
                    report.update(passed=True,overlay_age_ms=int(persisted[1]),screenshot=source.name,
                                  screenshot_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                  local_ai_frames_at_least=200,input_blocked=False)
                    break
            await asyncio.sleep(.25)
        else:raise TimeoutError('native persistent overlay/offline proof timed out')
        rejected=[row for row in events if row['event']=='client_update_required']
        if len(rejected)!=1 or rejected[0]['client_revision']!=1 or server.rooms or server.community.sessions:
            raise AssertionError('version rejection admitted an online room/presence')
        report['server_rejection']=rejected[0]
        if any(row['event']=='worker_started' for row in events):raise AssertionError('server started a match worker')
    except BaseException as error:
        report.update(passed=False,error=f'{type(error).__name__}: {error}',traceback=traceback.format_exc())
    finally:
        if process is not None:
            if process.poll() is None:process.terminate()
            await asyncio.to_thread(process.wait,timeout=15)
        if job is not None:job.close()
        if task is not None:task.cancel();await asyncio.gather(task,return_exceptions=True)
        if writer is not None:
            writer.close()
            try:await asyncio.wait_for(writer.wait_closed(),2)
            except (OSError,TimeoutError):writer.transport.abort()
        if child is not None:child.close()
        await server.close();remove_test_pki(output/'ephemeral-pki')
        report.update(elapsed_seconds=round(time.monotonic()-started,3),cleanup='forced owned teardown; no natural Quit claim')
        (output/'native.log').write_text(log,encoding='utf-8')
        (output/'events.json').write_text(json.dumps(events,indent=2),encoding='utf-8')
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    return not report['passed']


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--render-window',action='store_true',help='show only the owned test window without activating it so Unity can render its screenshot')
    raise SystemExit(asyncio.run(run(parser.parse_args())))
