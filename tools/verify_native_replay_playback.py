"""Owned original ReplayFiles full-playback qualification with bundled client.

An external diagnostic adapter adds one explicit startup flag. The original batch
owns decode, Load/Play, updates and Quit. Ordinary Start Client has no replay test
actions. This qualifies native simulation/presentation progress, not rendered
pixels, independent determinism, physical input or general network silence.
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import traceback

from client_patch.transport import client,launcher
from server.worker_client import _WindowsJob
from tools.package_integrity import verify
from tools.run_secure_match import read_native_log
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.verify_native_storage import snapshot,replay_evidence
from tools.verify_packaged_play import job_accounting
from tools.replay_retention import api_path
from tools.native_replay_playback_evidence import validate

ROOT=Path(__file__).resolve().parents[1]
require=startup.require
LEAF='native-playback-'+'x'*100+'.rep'

# Not part of any shipped package. Imports only inventoried production modules
# from the isolated bundled runtime; no source-checkout imports or input macros.
DRIVER=r'''
import ctypes,hashlib,json,subprocess,sys,time,traceback
from pathlib import Path
from client_patch.transport import client,launcher
from tools.package_integrity import verify
request=json.loads(Path(sys.argv[1]).read_bytes())
package=Path(request['package']);game=Path(request['game']);output=Path(request['output'])
verify(package,'client')
report=dict(passed=False,remote_connections=0,invite_reads=0,production_modules={});process=None
def forbid_connection(*args,**kwargs):
    report['remote_connections']+=1
    raise AssertionError('unconfigured replay attempted TLS')
def forbid_invite(*args,**kwargs):
    report['invite_reads']+=1
    raise AssertionError('unconfigured replay attempted invite read')
def spawn(config,remote,options,child):
    global process
    assert config['local_profile']==request['profile'] and config['game_directory']==game
    command=launcher.game_arguments(config,None,child.fileno(),options)
    assert '-unified-client' in command and '-public-queue-experimental' in command
    assert not any(any(word in value.partition('=')[0].casefold() for word in ('smoke','audit','capture','proof','export','auto-')) for value in command if value.startswith('-'))
    ordinary=list(command)
    command[command.index('-logFile')+1]=str(output/'game.log')
    diagnostic=['-native-replay-playback-smoke'];command.extend(diagnostic)
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow=1 if request['visible'] else 0;info.lpAttributeList={'handle_list':[child.fileno()]}
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong;tick=clock()
    try:
        child.set_inheritable(True)
        process=subprocess.Popen(command,cwd=game,startupinfo=info,close_fds=True)
    finally:child.set_inheritable(False)
    record=dict(pid=process.pid,launch_tick=tick,ordinary_arguments=ordinary,diagnostic_arguments=diagnostic,actual_arguments=command)
    temporary=output/'game-process.tmp';temporary.write_text(json.dumps(record,indent=2)+'\n');temporary.rename(output/'game-process.json')
    return process
try:
    for module in (client,launcher,sys.modules['client_patch.transport.bridge'],sys.modules['tools.package_integrity']):
        path=Path(module.__file__).resolve();assert path.is_relative_to(package/'program/app')
        report['production_modules'][module.__name__]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():
        assert time.monotonic()<deadline,'parent owned job missing'
        time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    launcher.spawn_game=spawn;launcher.tls.open_verified_connection=forbid_connection;launcher.read_credential_file=forbid_invite
    report['launcher_exit_code']=client.main(['--config',request['config']])
    report['game_exit_code']=None if process is None else process.poll()
    assert report['launcher_exit_code']==report['game_exit_code']==0
    assert report['remote_connections']==report['invite_reads']==0
    report['passed']=True
except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
finally:(output/'bundled-driver.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
'''


def sources():
    paths=[Path(__file__),ROOT/'tools/native_replay_playback_evidence.py',ROOT/'tools/verify_packaged_play.py',ROOT/'tools/verify_native_storage.py',ROOT/'tools/replay_retention.py']
    return quit_probe.sources()|{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run(args):
    package,game,output,source_report=(p.resolve() for p in (args.package,args.game,args.output,args.source_verification))
    require(os.name=='nt' and 30<=args.timeout<=300,'bounded Windows replay probe required')
    require(all(p.is_relative_to(ROOT/'local') for p in (package,game,output,source_report)),'owned ignored paths required')
    inventory=verify(package,'client');launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True)
    helper=(game/'BattleAcesOffline.dll').read_bytes()
    require(helper==(package/'program/client-helper/BattleAcesOffline.dll').read_bytes() and b'BA_RESURRECTION_NATIVE_REPLAY_PLAYBACK_V1' in helper,'exact playback diagnostic helper required')
    receipt=quit_probe.verify_build_receipt(game,args.helper_build_receipt.resolve())
    manifest=json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
    require(manifest['diagnostics']['native_quit'] is False and manifest['diagnostics']['dlss_enabled'] is False and
            not manifest.get('pointer_hooks'),'default patch recipe required')
    source_raw=source_report.read_bytes();source=json.loads(source_raw)
    request=json.loads((source_report.parent/'request.json').read_bytes())
    require(source['passed'] is True and source['native_codec']['original_codec'] is True,'source must have passed original native codec qualification')
    original=Path(request['game'])/'.battleaces-resurrection/profiles'/source['profile']/'AutoSaveReplays'/source['replay']['native_filename']
    require(original.resolve().is_relative_to(ROOT/'local'),'source replay must remain in ignored owned storage')
    raw=api_path(original).read_bytes();replay=replay_evidence(raw)
    require(all(replay[key]==source['replay'][key] for key in replay),'source replay changed since original codec qualification')
    output.mkdir(parents=True,exist_ok=False)
    profile='nativestest_replay_'+secrets.token_hex(6);folder=game/'.battleaces-resurrection/profiles'/profile
    (folder/'AutoSaveReplays').mkdir(parents=True,exist_ok=False)
    seed=folder/'AutoSaveReplays'/LEAF
    require(len(str(seed))>260 and len(seed.name)<255,'exercise full long path within component bound')
    with api_path(seed).open('xb') as stream:stream.write(raw)
    selected=str(api_path(seed))
    config=output/'client.json';settings=client.defaults(game);settings.update(local_profile=profile,display_name='Native Replay Qualification')
    config.write_text(json.dumps(settings,indent=2)+'\n');config_before=config.read_bytes()
    driver=output/'owned-driver.py';driver.write_text(DRIVER,encoding='utf-8')
    request_path=output/'request.json'
    request_path.write_text(json.dumps(dict(package=str(package),game=str(game),output=str(output),config=str(config),profile=profile,visible=args.visible),indent=2)+'\n')
    cwd=output/'foreign cwd';cwd.mkdir()
    for name in ('sitecustomize.py','tools.py','client_patch.py'):(cwd/name).write_text('raise RuntimeError("foreign module must not run")\n')
    shared=args.shared_settings.resolve()
    def channels():return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    report=dict(passed=False,scope=__doc__,profile=profile,selected=selected,selected_path_characters=len(str(seed)),replay=replay,
                helper_build=receipt,package=str(package),source_verification=str(source_report),
                source_verification_sha256=hashlib.sha256(source_raw).hexdigest(),source_replay=str(original),
                source_sha256_at_start=sources(),shared_before=channels(),forced_cleanup=False,natural_batch_exit=False,
                driver_sha256=hashlib.sha256(driver.read_bytes()).hexdigest())
    started=time.monotonic();parent=job=None;native=None;game_handle=None
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.WaitForSingleObject.restype=ctypes.c_ulong
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    try:
        environment=os.environ.copy();environment.update(PATH=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'),PYTHONPATH=str(cwd))
        command=[str(package/'program/runtime/python.exe'),'-I','-B',str(driver),str(request_path)]
        with (output/'stdout.txt').open('wb') as stdout,(output/'stderr.txt').open('wb') as stderr:
            info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
            parent=subprocess.Popen(command,cwd=cwd,env=environment,stdout=stdout,stderr=stderr,startupinfo=info,close_fds=True)
            job=_WindowsJob(parent.pid);report['driver_pid']=parent.pid
            ready=output/'job-ready.tmp';ready.write_bytes(b'owned job attached\n');ready.rename(output/'job-ready')
            while parent.poll() is None:
                if native is None and (output/'game-process.json').exists():
                    native=json.loads((output/'game-process.json').read_bytes())
                    require(type(native['pid']) is int and native['pid']>0 and type(native['launch_tick']) is int,'owned native identity missing')
                    game_handle=kernel.OpenProcess(0x100000|0x1000,False,native['pid']);require(game_handle,'cannot observe owned native process')
                    report['game']=native
                if native:
                    text=read_native_log(game,native['pid'],since_tick=native['launch_tick'])
                    require(not any(marker in text for marker in ('Native replay startup refused:','Native replay observation failed:','Local menu initialization failed:','Offline loop stopped in ')),'native replay startup/observation failed')
                require(time.monotonic()-started<args.timeout,'owned original replay batch deadline reached')
                time.sleep(.05)
        require(parent.returncode==0 and native and game_handle,'bundled original replay did not exit naturally0')
        deadline=time.monotonic()+5
        while job_accounting(job.handle)['active_processes']:
            require(time.monotonic()<deadline,'owned replay descendants remain alive');time.sleep(.05)
        require(kernel.WaitForSingleObject(game_handle,0)==0,'game alive after bundled driver exit')
        code=ctypes.c_ulong();require(kernel.GetExitCodeProcess(game_handle,ctypes.byref(code)),'native replay exit unavailable')
        bundled=json.loads((output/'bundled-driver.json').read_bytes())
        require(bundled['passed'] and bundled['game_exit_code']==code.value==bundled['launcher_exit_code']==0 and
                bundled['remote_connections']==bundled['invite_reads']==0,'bundled launcher/bridge replay evidence incomplete')
        for module in bundled['production_modules'].values():
            path=Path(module['path']).resolve()
            require(path.is_relative_to(package/'program/app') and inventory['files'][path.relative_to(package).as_posix()]['sha256']==module['sha256'],'unverified production import')
        native_text=read_native_log(game,native['pid'],since_tick=native['launch_tick'])
        unity=(output/'game.log').read_text(encoding='utf-8-sig')
        report['playback']=validate(native_text,unity,selected=selected,profile=profile,replay=replay,game_exit=code.value,driver_exit=parent.returncode)
        require(not (folder/'quit-trace.jsonl').exists(),'batch qualification unexpectedly used menu Quit test')
        report.update(passed=True,natural_batch_exit=True,game_exit_code=code.value,bundled_driver=bundled)
    except BaseException as error:report.update(passed=False,error=repr(error),traceback=traceback.format_exc())
    finally:
        if (parent is not None and parent.poll() is None) or (game_handle and kernel.WaitForSingleObject(game_handle,0)!=0):report['forced_cleanup']=True
        if job:
            try:
                report['job_before_close']=job_accounting(job.handle)
                if report['job_before_close']['active_processes']:report['forced_cleanup']=True
            except BaseException as error:report.update(passed=False,forced_cleanup=True,job_error=repr(error))
            job.close()
        if parent:
            try:parent.wait(timeout=15)
            except subprocess.TimeoutExpired:parent.kill();parent.wait(timeout=15);report['forced_cleanup']=True
        report['driver_reaped']=parent is None or parent.poll() is not None
        report['game_reaped']=game_handle is None or kernel.WaitForSingleObject(game_handle,15000)==0
        if game_handle:kernel.CloseHandle(game_handle)
        if native:(output/'native.log').write_text(read_native_log(game,native['pid'],since_tick=native['launch_tick']),encoding='utf-8')
        try:report['package_files_unchanged']=verify(package,'client')==inventory
        except BaseException as error:report.update(package_files_unchanged=False,package_error=repr(error))
        report['config_unchanged']=config.read_bytes()==config_before
        report['driver_unchanged']=hashlib.sha256(driver.read_bytes()).hexdigest()==report['driver_sha256']
        report['source_replay_unchanged']=api_path(original).read_bytes()==raw and source_report.read_bytes()==source_raw
        report['seed_replay_unchanged']=api_path(seed).read_bytes()==raw
        report.update(shared_after=channels(),source_sha256_at_finish=sources(),elapsed_seconds=time.monotonic()-started)
        report['shared_channels_unchanged']=report['shared_before']==report['shared_after']
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        keys=('driver_reaped','game_reaped','package_files_unchanged','config_unchanged','driver_unchanged','source_replay_unchanged','seed_replay_unchanged','shared_channels_unchanged','source_files_unchanged')
        report['passed'] &= all(report.get(k,False) for k in keys) and not report['forced_cleanup']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','natural_batch_exit','forced_cleanup','elapsed_seconds','error') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','game','output','shared-settings','helper-build-receipt','source-verification'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--visible',action='store_true')
    raise SystemExit(run(parser.parse_args()))
