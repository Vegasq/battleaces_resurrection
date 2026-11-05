"""Owned recipe25 Tutorial01 entry,mission audit,or active-tutorial window close."""
import argparse
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
from ctypes import wintypes

from client_patch.transport.launcher import verify_game
from tools.helper_provenance import validate as validate_helper
from tools.owned_suspended_launch import SuspendedChild
from tools.verify_native_crash import components
from tools.verify_telemetry_audit import verify_lines
from tools.verify_unified_startup import shared_state

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owned_windows(pid):
    user=ctypes.WinDLL('user32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=[callback_type,wintypes.LPARAM];user.EnumWindows.restype=wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype=wintypes.DWORD
    user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.GetClassNameW.restype=ctypes.c_int
    user.IsWindowVisible.argtypes=[wintypes.HWND];user.IsWindowVisible.restype=wintypes.BOOL
    rows=[]
    def visit(hwnd,_):
        owner=wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid:
            name=ctypes.create_unicode_buffer(256)
            count=user.GetClassNameW(hwnd,name,len(name))
            rows.append(dict(hwnd=int(hwnd),class_name=name.value if count else '',visible=bool(user.IsWindowVisible(hwnd))))
        return True
    if not user.EnumWindows(callback_type(visit),0):raise ctypes.WinError(ctypes.get_last_error())
    return rows


def run(game,helper,output,*,through_mission=False,window_close=False,
        current_recipe=False,prelaunch_observer=False):
    game,helper,output=(Path(p).resolve() for p in (game,helper,output))
    expected_game=(ROOT/'local/privacy301-runtime01/game' if current_recipe else
                   ROOT/('local/'+('privacy291-runtime01' if window_close else 'privacy288-runtime01')+'/game'))
    expected_helper=(ROOT/'local/privacy357-helper-build01/BattleAcesOffline.dll' if current_recipe else
                     ROOT/('local/'+('privacy291-helper01' if window_close else 'privacy288-helper01')+'/BattleAcesOffline.dll'))
    prefix=('privacy431-tutorial' if current_recipe else
            'privacy294-tutorial' if window_close else
            'privacy290-tutorial' if through_mission else 'privacy289-tutorial')
    recipe=38 if current_recipe else 25
    if (os.name!='nt' or (window_close and not through_mission) or
            (prelaunch_observer and not (current_recipe and window_close)) or
            game!=expected_game or helper!=expected_helper or
            output.parent!=ROOT/'local' or not output.name.startswith(prefix) or
            output.exists()):
        raise ValueError('Exact fresh owned Tutorial01 diagnostic required')
    verify_game(game,community=True,bridge_version=2,unified=True)
    binding=validate_helper(helper,(game/'BattleAcesOffline.dll').read_bytes(),ROOT)
    manifest=json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
    if (manifest.get('telemetry',{}).get('recipe_version')!=recipe or
            manifest.get('telemetry',{}).get('runtime_validated') is not False or
            manifest.get('diagnostics',{}).get('native_quit') is not False):
        raise ValueError('Current default recipe25 manifest required')
    profile='nativestest_tutorial_'+secrets.token_hex(6)
    if (game/'.battleaces-resurrection/profiles'/profile).exists():
        raise ValueError('Fresh profile required')
    output.mkdir();(output/'tmp').mkdir();(game/'investigation/runtime').mkdir(parents=True,exist_ok=True)
    shared=Path.home()/'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
    source_files=[Path(__file__),ROOT/'tools/verify_telemetry_audit.py',ROOT/'tools/owned_suspended_launch.py']
    source_before={str(p.relative_to(ROOT)):sha(p) for p in source_files}
    report=dict(passed=False,scope=__doc__,profile=profile,through_mission=through_mission,window_close=window_close,
                recipe=recipe,prelaunch_observer=prelaunch_observer,helper_binding=binding,
                components_before=components(game),shared_before=shared_state(shared),source_before=source_before)
    child=None;start=time.monotonic();tick=None
    def log():
        if not child:return ''
        p=game/'investigation/runtime/offline-native.log'
        if not p.exists():return ''
        raw=p.read_bytes()
        complete=raw[:raw.rfind(b'\n')+1].decode('utf-8')
        lines=complete.splitlines()
        selections=[]
        for index,line in enumerate(lines):
            match=re.match(r'^\[(\d+)\] NATIVE SETTINGS path selected: (.+) BA_RESURRECTION_NATIVE_SETTINGS_V1$',line)
            if match:
                proof=json.loads(match[2])
                if int(match[1])>=tick and proof.get('profile')==profile:
                    selections.append(index)
        if not selections:return ''
        if len(selections)!=1:raise RuntimeError('Tutorial profile selection not unique')
        following=lines[selections[0]:]
        next_selection=next((i for i,line in enumerate(following[1:],1)
                            if ' NATIVE SETTINGS path selected: ' in line),len(following))
        return '\n'.join(following[:next_selection])
    try:
        command=[str(game/'Battle Aces.exe'),'-offline-tutorial','-local-profile='+profile,
                 '-player-name=Owned Tutorial01 Privacy','-telemetry-audit',
                 '-screen-fullscreen','0','-screen-width','960','-screen-height','540',
                 '-logFile',str(output/'game.log')]
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong
        tick=clock()
        child=SuspendedChild.create(command,cwd=game,startupinfo=startup,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        report.update(command=command,pid=child.pid,thread=child.tid)
        if prelaunch_observer:
            process=dict(pid=child.pid,actual_arguments=command,
                         suspended_for_observer=True,
                         launch_tick=child.receipt['create_return_tick'])
            (output/'game-process.json').write_text(json.dumps(process,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(dict(stage='prelaunch_attach_required',pid=child.pid,
                                  output=str(output))),flush=True)
            gate=output/'observer-ready';gate_deadline=time.monotonic()+45
            while not gate.exists() and time.monotonic()<gate_deadline and child.poll() is None:
                time.sleep(.05)
            if gate.read_bytes()!=b'FRIDA_READY'+bytes([10]):
                raise RuntimeError('prelaunch observer gate absent or invalid')
        child.resume()
        deadline=time.monotonic()+90
        audit=None
        while True:
            text=log()
            if 'Offline initialization failed:' in text or 'Telemetry audit disabled:' in text:
                raise RuntimeError('Tutorial or audit failed;retain native log')
            if 'stage=tutorial' in text:
                audit=verify_lines(text.splitlines(),expected_sha256=sha(game/'UnityPlayer.dll'),
                                   required_stages=('startup-after-engine-init','tutorial'),recipe_version=recipe)
                if audit['passed']:
                    if not through_mission:break
                    unity=(output/'game.log').read_text(encoding='utf-8',errors='strict') if (output/'game.log').exists() else ''
                    ready=re.findall(r'^\[(\d+)\] Offline world ready; original GameStarted applied\.$',text,re.M)
                    repeat=re.findall(r'^\[(\d+)\] Telemetry audit 3/\d+ stage=tutorial ',text,re.M)
                    if (len(ready)==len(repeat)==1 and int(ready[0])<int(repeat[0]) and
                            audit['observed_stages']==['startup-after-engine-init','tutorial','tutorial'] and
                            '-- [Objectives] - Start Mission - Tutorial 1' in unity and
                            'Enter Objective:' in unity):
                        report.update(world_ready_tick=int(ready[0]),post_world_audit_tick=int(repeat[0]),
                                      mission_started=True,original_objective_entered=True)
                        break
            if child.poll() is not None:raise RuntimeError('Tutorial exited before selected entry audit')
            if time.monotonic()>=deadline:raise TimeoutError('Tutorial entry audit deadline')
            time.sleep(.05)
        if text.count('Entering existing tutorial01 state')!=1:
            raise RuntimeError('Original Tutorial01 state entry not unique')
        if 'tutorial' not in audit['observed_entries']:
            raise RuntimeError('Complete Tutorial01 selected field audit failed')
        report.update(entry_audit=audit,tutorial_entry=True)
        if window_close:
            windows=owned_windows(child.pid)
            report['owned_windows']=windows
            candidates=[row for row in windows if row['class_name']=='UnityWndClass']
            if len(candidates)!=1:raise RuntimeError('Exactly one owned Unity top-level window required')
            user=ctypes.WinDLL('user32',use_last_error=True)
            user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
            user.PostMessageW.restype=wintypes.BOOL
            report['window_close_tick']=clock()
            if not user.PostMessageW(candidates[0]['hwnd'],0x0010,0,0):
                raise ctypes.WinError(ctypes.get_last_error())
            report['window_close_posted']=True
            child.wait(60)
            if child.returncode!=0:raise RuntimeError('Owned tutorial WM_CLOSE did not exit0')
            report['window_close_exit_zero']=True
    except BaseException as error:
        report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        if child:
            (output/'native.log').write_text(log(),encoding='utf-8')
            if child.poll() is None:child.terminate()
            child.close();report['launch']=child.receipt
        report.update(components_after=components(game),shared_after=shared_state(shared),
                      source_after={str(p.relative_to(ROOT)):sha(p) for p in source_files},
                      elapsed_seconds=time.monotonic()-start)
        report['passed']=(not report.get('error') and report.get('tutorial_entry') is True and
                          (not through_mission or report.get('mission_started') is True) and
                          (not window_close or (report.get('window_close_exit_zero') is True and
                           report.get('launch',{}).get('forced_cleanup') is False and
                           report.get('launch',{}).get('job_final')==dict(total_processes=1,active_processes=0,total_terminated_processes=0))) and
                          report.get('launch',{}).get('owned_process_reaped') is True and
                          report['components_before']==report['components_after'] and
                          report['shared_before']==report['shared_after'] and
                          report['source_before']==report['source_after'])
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report.get(k) for k in ('passed','error','elapsed_seconds')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('game','helper','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--through-mission',action='store_true',help='require original GameStarted,mission objective and later tutorial audit')
    parser.add_argument('--window-close-after-mission',action='store_true',help='send WM_CLOSE only to the owned Tutorial01 Unity window after mission/audit')
    parser.add_argument('--current-recipe',action='store_true',help='use owned current recipe38/helper357 game')
    parser.add_argument('--prelaunch-observer',action='store_true',help='wait for a diagnostic observer before primary-thread resume;current recipe only')
    args=parser.parse_args()
    raise SystemExit(run(args.game,args.helper,args.output,through_mission=args.through_mission,
                         window_close=args.window_close_after_mission,
                         current_recipe=args.current_recipe,
                         prelaunch_observer=args.prelaunch_observer))
