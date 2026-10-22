"""Owned original menu Quit diagnostics: inventory,Cancel,or natural exit.

Uses original persistent payloads on the Unity thread. Confirm must exit0 within
60s of its native dispatch marker. The optional teardown recipe also traces
original instance/AI/OnDestroy return;default-recipe tests claim no disposal trace.
Forced cleanup never qualifies Quit. Shared settings are read/hashed only.
"""
import argparse
import ctypes
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import traceback

from client_patch.transport import launcher
from server.worker_client import _WindowsJob
from tools import verify_unified_startup as startup

ROOT = Path(__file__).resolve().parents[1]


def sources():
    return startup.source_hashes() | {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in (Path(__file__), ROOT/'client_patch/build.ps1',ROOT/'tools/verify_practice_ai.py',
                                               ROOT/'tools/startup_task_evidence.py', ROOT/'client_patch/patcher/startup_tasks.py',
                                               ROOT/'tools/verify_telemetry_audit.py', ROOT/'tools/replay_binding_evidence.py',
                                               ROOT/'tools/replay_signal_evidence.py', ROOT/'tools/replay_nody_evidence.py',
                                               ROOT/'tools/telemetry_cache_evidence.py')}


def telemetry_evidence(text,rows,expected_sha256,*,after_practice=False,device_probe=False):
    """Require complete fields before the original callback,then natural Quit separately."""
    from tools.verify_telemetry_audit import verify_lines
    required=('startup-after-engine-init','menu')
    if after_practice:required+=('ingame','postgame','menu')
    required+=('pre-quit-confirm',)
    result=verify_lines(text.splitlines(),expected_sha256=expected_sha256,required_stages=required)
    startup.require(result['passed'],'pre-Quit telemetry field/stage evidence incomplete')
    boundary=list(re.finditer(r'^\[(\d+)\] TELEMETRY PREQUIT boundary: thread=(\d+) samplesBefore=(\d+) samplesAfter=(\d+) readOnly=1 originalConfirmNext=1$',text,re.M))
    dispatch=[row for row in rows if row['event']=='OnConfirm.dispatch']
    startup.require(len(boundary)==len(dispatch)==1,'one pre-Quit field/original confirmation boundary required')
    item=boundary[0];tick,thread,before,after=map(int,item.groups())
    ends=list(re.finditer(r'^\[(\d+)\] Telemetry audit '+str(after)+r' snapshotEnd singletonPointersStable=1; scalar observations are not atomic or network evidence$',text,re.M))
    native=list(re.finditer(r'^\[(\d+)\] NATIVE QUIT original confirmation dispatch: thread=(\d+) worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60$',text,re.M))
    startup.require(len(ends)==len(native)==1 and 1<=before<17 and after==before+1==result['complete_snapshots'] and
        int(ends[0][1])<=tick<=dispatch[0]['tick']<=int(native[0][1]) and thread==dispatch[0]['thread']==int(native[0][2]) and
        ends[0].end()<item.start()<item.end()<native[0].start(),
        'pre-Quit observation did not precede the same-thread original confirmation')
    if device_probe:
        begin=list(re.finditer(r'^\[(\d+)\] Telemetry audit '+str(after)+r'/17 stage=pre-quit-confirm ',text,re.M))
        calls=list(re.finditer(r'^\[(\d+)\] TELEMETRY DEVICE probe passed: version=1 thread=(\d+) calls=1 returned=0 mainStable=1 disabledFieldsUnchanged=1 rawHeaderUnchanged=1 markerBefore=0 markerAfter=0 configCount=0 payloadRead=0$',text,re.M))
        startup.require(len(calls)==len(begin)==1 and int(calls[0][1])<=int(begin[0][1]) and int(calls[0][2])==thread and
            calls[0].end()<begin[0].start() and 'TELEMETRY DEVICE probe failed:' not in text,
            'guarded device API probe did not pass once before original Quit')
        result['device_api_guarded_false_and_sampled_config_unchanged']=True
        if result['recipe_version']>=10:
            identity=list(re.finditer(r'^\[(\d+)\] TELEMETRY IDENTITY probe passed: version=1 thread=(\d+) calls=2 borrowedUnreadable=1 mainStable=1 emptySsoMetadataUnchanged=1 identityPayloadRead=0$',text,re.M))
            startup.require(len(identity)==1 and int(identity[0][2])==thread and int(identity[0][1])<=int(begin[0][1]) and
                calls[0].end()<identity[0].start()<identity[0].end()<begin[0].start(),
                'guarded identity setters did not return with unchanged metadata before original Quit')
            result['identity_setters_guarded_void_and_metadata_unchanged']=True
            if result['recipe_version']>=11:
                ads=list(re.finditer(r'^\[(\d+)\] TELEMETRY ADS probe passed: version=1 thread=(\d+) calls=1 authoredInput=1 retainedEmpty=1 tracking=1 dirty=1 state=0 borrowedUnchanged=1 retainedPayloadRead=0$',text,re.M))
                startup.require(len(ads)==1 and int(ads[0][2])==thread and int(ads[0][1])<=int(begin[0][1]) and
                    identity[0].end()<ads[0].start()<ads[0].end()<begin[0].start(),
                    'guarded ads callback did not preserve empty storage and data-free progress before original Quit')
                result['ads_callback_copy_guard_and_progress_qualified']=True
                if result['recipe_version']>=12:
                    events=list(re.finditer(r'^\[(\d+)\] TELEMETRY EVENTS probe passed: version=1 thread=(\d+) calls=3 returnedDisabled=3 borrowedUnreadable=1 sampledStateUnchanged=1 payloadRead=0$',text,re.M))
                    startup.require(len(events)==1 and int(events[0][2])==thread and int(events[0][1])<=int(begin[0][1]) and
                        ads[0].end()<events[0].start()<events[0].end()<begin[0].start(),
                        'guarded event APIs did not return disabled with unchanged sampled state before original Quit')
                    result['event_apis_guarded_disabled_before_input_access']=True
                    if result['recipe_version']>=13:
                        controls=list(re.finditer(r'^\[(\d+)\] TELEMETRY EVENTCONTROL probe passed: version=1 thread=(\d+) calls=9 returnedDisabled=9 borrowedUnreadable=1 sampledStateUnchanged=1 payloadRead=0$',text,re.M))
                        startup.require(len(controls)==1 and int(controls[0][2])==thread and int(controls[0][1])<=int(begin[0][1]) and
                            events[0].end()<controls[0].start()<controls[0].end()<begin[0].start(),
                            'guarded transaction/registration/event controls did not return disabled with unchanged sampled state before original Quit')
                        result['event_control_apis_guarded_disabled_before_input_access']=True
                        if result['recipe_version']>=14:
                            data=list(re.finditer(r'^\[(\d+)\] TELEMETRY CUSTOMDATA probe passed: version=1 thread=(\d+) creates=1 adds=7 addFalse=7 destroys=1 realNativeOwner=1 emptyMetadataUnchanged=1 borrowedUnreadable=1 borrowedPayloadRead=0$',text,re.M))
                            startup.require(len(data)==1 and int(data[0][2])==thread and int(data[0][1])<=int(begin[0][1]) and
                                controls[0].end()<data[0].start()<data[0].end()<begin[0].start(),
                                'custom event-data native ownership/empty metadata/Add-false cycle did not complete before original Quit')
                            result['custom_event_data_empty_native_lifetime_and_add_false_qualified']=True
                            if result['recipe_version']>=15:
                                continuous=list(re.finditer(r'^\[(\d+)\] TELEMETRY CONTINUOUS probe passed: version=1 thread=(\d+) calls=5 returnedDisabled=5 borrowedUnreadable=1 sampledStateUnchanged=1 borrowedPayloadRead=0$',text,re.M))
                                startup.require(len(continuous)==1 and int(continuous[0][2])==thread and int(continuous[0][1])<=int(begin[0][1]) and
                                    data[0].end()<continuous[0].start()<continuous[0].end()<begin[0].start(),
                                    'continuous-event guarded inputs did not synchronously return disabled before original Quit')
                                result['continuous_event_inputs_guarded_disabled_before_registration']=True
    return dict(**result,same_original_quit_thread=True,pre_confirm_tick=tick,original_confirm_tick=dispatch[0]['tick'])


def practice_evidence(game, output, pid, text):
    require = startup.require
    from tools.verify_practice_ai import movement_evidence
    starts = re.findall(r'Practice requested: match=([0-9a-f]{32}) ',text)
    require(len(starts)==1 and text.count('Practice AI join captured:')==1 and text.count('Practice AI JoinedGame delivered:')==1,
            'post-practice Quit lacks one original practice join')
    markers = ['PRACTICE SMOKE original EditDeck mode4 callback: owned=1 visible=1 interactable=1 preamble=1',
               'Practice native EndOfGameResponse delivered;','PRACTICE SMOKE native Continue (automated)',
               'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1',
               'NATIVE QUIT owned menu verified:']
    positions = [text.find(marker) for marker in markers]
    require(all(position>=0 and text.count(marker)==1 for marker,position in zip(markers,positions)) and
            positions==sorted(positions),'post-practice original callback/result/Continue/menu order differs')
    joins = [json.loads(line.split('Practice original JoinArmy: ',1)[1]) for line in text.splitlines() if 'Practice original JoinArmy: ' in line]
    require(len(joins)==2 and text.count('Practice AI action:')>=5,'post-practice bot/action evidence missing')
    resource_path = game/'investigation/runtime'/f'lan-resources-{pid}-{starts[0]}.tsv'
    raw = resource_path.read_bytes();(output/'practice-resources.tsv').write_bytes(raw)
    with resource_path.open(encoding='utf-8') as source:
        supplies = [int(row['current_supply']) for row in csv.DictReader(source,delimiter='\t') if row['viewer']=='1' and row['army']=='1']
    require(supplies and max(supplies)>0,'post-practice bot did not produce native unit supply')
    moved,orders = movement_evidence(text,set(joins[1]['deck']['units']))
    return dict(match=starts[0],native_result=True,native_continue=True,returned_to_menu=True,bot_max_supply=max(supplies),
                autonomous_action_records=text.count('Practice AI action:'),produced_bot_units_with_orders_and_position_change=sorted(moved&orders))


def verify_build_receipt(game, path):
    raw = path.read_bytes()
    startup.require(len(raw)<=256*1024,'helper build receipt exceeds bound')
    receipt = json.loads(raw)
    paths = [ROOT/'client_patch/build.ps1'] + [p for p in (ROOT/'client_patch/src').rglob('*')
                                              if p.is_file() and p.suffix in ('.cpp','.h','.hpp')]
    expected = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    startup.require(receipt.get('schema')==1 and receipt.get('sources_unchanged_during_build') is True and
                    receipt.get('source_sha256')==expected and
                    receipt.get('helper_sha256')==hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest(),
                    'helper build receipt does not bind installed helper to current sources')
    return dict(path=str(path.resolve()),sha256=hashlib.sha256(raw).hexdigest(),receipt=receipt)


def observe_exit(process, quit_tick, clock):
    startup.require(clock()-quit_tick<60000,'native process did not exit within60s after original Quit confirmation')
    if process.poll() is None: return None
    observed = clock()
    startup.require(observed-quit_tick<60000,'native exit observation exceeded60s after original Quit confirmation')
    return observed


def require_fresh_trace(path):
    startup.require(not os.path.lexists(path),'native Quit diagnostic requires a fresh trace path; archive the prior completed owned run first')


def current_trace_rows(raw,pid,launch_tick):
    startup.require(len(raw)<=64*1024,'native Quit trace exceeds bound')
    rows=[json.loads(line) for line in raw[:raw.rfind(b'\n')+1].splitlines()]
    startup.require(all(isinstance(row,dict) and row.get('pid')==pid and type(row.get('tick')) is int and
                        row['tick']>=launch_tick for row in rows),'native Quit trace belongs to another process/run')
    return rows


def run(args):
    require = startup.require
    game,output = args.game.resolve(),args.output.resolve()
    require(os.name=='nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'), 'owned ignored Windows paths required')
    require(60<=args.timeout<=300 and (args.mode=='inventory' or args.visible) and
            (not args.capture_dialog or args.mode!='inventory'), 'bounded timeout and visible dialog required')
    require(not args.after_practice or args.mode=='confirm','post-practice requires original Confirm/natural exit mode')
    require(not getattr(args,'replay_binding_inventory',False) or args.after_practice,
            'replay binding inventory requires a healthy owned practice match')
    require(not getattr(args,'replay_signal_inventory',False) or getattr(args,'replay_binding_inventory',False),
            'replay signal inventory requires the read-only button inventory')
    require(not getattr(args,'replay_nody_inventory',False) or getattr(args,'replay_signal_inventory',False),
            'replay Nody inventory requires the read-only stream inventory')
    require(not args.default_recipe or args.mode=='confirm','default recipe qualification requires original Confirm/natural exit')
    require(not getattr(args,'telemetry_audit',False) or args.mode=='confirm','pre-Quit telemetry requires original Confirm/natural exit')
    require(not getattr(args,'telemetry_device_probe',False) or getattr(args,'telemetry_audit',False),
            'device API probe requires full telemetry/native-Quit evidence')
    require(args.profile is None or re.fullmatch(r'nativestest_[a-z0-9_-]{1,34}',args.profile),
            'explicit Quit profile must be an owned nativestest_ key')
    display_name = getattr(args,'display_name',None) or 'Native Quit Probe'
    require(0<len(display_name.encode('utf-8'))<=96 and not any(ord(c)<32 for c in display_name),
            'bounded diagnostic player name required')
    launcher.verify_game(game,community=True,bridge_version=2,unified=True)
    build_receipt = verify_build_receipt(game,args.helper_build_receipt.resolve())
    manifest = json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
    if getattr(args,'startup_tasks_audit',False):
        from client_patch.patcher import startup_tasks
        require(manifest.get('diagnostics',{}).get('startup_tasks') is True and
                all(h in manifest['call_hooks'] for h in startup_tasks.CALL_HOOKS) and
                all(h in manifest['tail_hooks'] for h in startup_tasks.TAIL_HOOKS),
                'install exact owned startup diagnostic recipe')
    if args.default_recipe:
        require(manifest.get('diagnostics',{}).get('native_quit') is False and
                manifest['diagnostics'].get('dlss_enabled') is False and not manifest.get('pointer_hooks') and
                not any(h['name'].startswith('OfflineNativeQuit') for h in manifest['call_hooks']) and
                manifest.get('graphics',{}).get('dlss_setup')=='unavailable-before-native-init',
                'install the default NGX-free recipe without optional Quit hooks')
    else: require(manifest.get('diagnostics',{}).get('native_quit') is True and
            all(any(h['name']==name and h['rva']==rva and h['before']==before for h in manifest['call_hooks'])
                for name,rva,before in (('OfflineNativeQuitDispose',0x3de4968,'e8c3e0ffff'),
                                        ('OfflineNativeQuitAIDispose',0x3de4a0f,'e89c39dbff'))) and
            any(h['name']=='OfflineNativeQuitOnDestroy' and h['rva']==0x6d41a18 and h['before']=='2048de8301000000'
                for h in manifest.get('pointer_hooks',[])),
            'install exact owned native Quit diagnostic recipe')
    output.mkdir(parents=True,exist_ok=False)
    runtime = game/'investigation/runtime';runtime.mkdir(parents=True,exist_ok=True)
    profile = args.profile or 'nativestest_quit_'+secrets.token_hex(6)
    trace = game/'.battleaces-resurrection/profiles'/profile/'quit-trace.jsonl'
    require_fresh_trace(trace)
    report = dict(passed=False,scope=__doc__,mode=args.mode,visible=args.visible,profile=profile,capture_requested=args.capture_dialog,
                  source_sha256_at_start=sources(),helper_sha256=hashlib.sha256((game/'BattleAcesOffline.dll').read_bytes()).hexdigest(),
                  helper_build=build_receipt,
                  installed_diagnostics=manifest['diagnostics'],
                  patch_manifest_sha256=hashlib.sha256((game/'.battleaces-resurrection/patch-manifest.json').read_bytes()).hexdigest(),
                  after_practice=args.after_practice,
                  default_recipe=args.default_recipe,
                  natural_exit=False,forced_cleanup=False)
    process = job = None;started = time.monotonic();tick = None
    clock = ctypes.WinDLL('kernel32').GetTickCount64;clock.restype = ctypes.c_ulonglong

    def log():
        path = runtime/f'dedicated-native-{process.pid}.log'
        raw = path.read_bytes() if path.exists() else b''
        return '\n'.join(line for line in raw[:raw.rfind(b'\n')+1].decode('utf-8').splitlines()
                         if (m:=re.match(r'^\[(\d+)\]',line)) and int(m[1])>=tick)

    def trace_rows():
        raw = trace.read_bytes() if trace.exists() else b''
        return current_trace_rows(raw,process.pid,tick)

    try:
        report['shared_settings_before'] = startup.shared_state(args.shared_settings.resolve())
        command = [str(game/'Battle Aces.exe'),'-offline-practice','-practice-ai-experimental','-local-profile='+profile,
                   '-player-name='+display_name,'-native-quit-smoke','-native-quit-mode='+args.mode,
                   '-screen-fullscreen','0','-screen-width','960','-screen-height','540','-logFile',str(output/'game.log')]
        if args.capture_dialog: command.append('-native-quit-capture')
        if getattr(args,'startup_tasks_audit',False): command.append('-startup-tasks-audit')
        if getattr(args,'telemetry_audit',False): command.append('-telemetry-audit')
        if getattr(args,'telemetry_device_probe',False): command.append('-telemetry-device-probe')
        if getattr(args,'telemetry_cache_probe',False) or getattr(args,'telemetry_cache_disk_probe',False): command.append('-telemetry-cache-probe')
        if getattr(args,'telemetry_cache_disk_probe',False):command.append('-telemetry-cache-disk-probe')
        if getattr(args,'telemetry_cache_probe',False) or getattr(args,'telemetry_cache_disk_probe',False):
            require(getattr(args,'telemetry_audit',False) and args.mode=='confirm',
                    'cache probe requires telemetry audit and original confirmed Quit')
        if getattr(args,'replay_binding_inventory',False): command.append('-replay-binding-inventory')
        if getattr(args,'replay_signal_inventory',False): command.append('-replay-signal-inventory')
        if getattr(args,'replay_nody_inventory',False): command.append('-replay-nody-inventory')
        if getattr(args,'storage_directory_fault',False):
            require(profile.startswith('nativestest_storage_'),'storage directory fault requires an explicit owned profile')
            command.append('-native-storage-directory-failure-smoke')
        if getattr(args,'backup_notice_smoke',False):
            require(profile.startswith('nativestest_'),'backup notice smoke requires an owned profile')
            command.append('-native-backup-notice-smoke')
        if getattr(args,'backup_write_smoke',False):
            require(profile.startswith('nativestest_'),'backup writer probe requires an owned profile')
            command.append('-native-backup-write-smoke')
        if args.after_practice:
            command.extend(['-native-quit-after-practice','-practice-ai-smoke','-practice-ai-smoke-matches=1',
                            '-practice-ai-smoke-frames=1200','-practice-ai-smoke-delay-ms=3000','-lan-audit','-lan-smoke'])
        info = subprocess.STARTUPINFO();info.dwFlags |= subprocess.STARTF_USESHOWWINDOW;info.wShowWindow = 5 if args.visible else 0
        tick = clock();process = subprocess.Popen(command,cwd=game,startupinfo=info,
            creationflags=0 if args.visible else subprocess.CREATE_NO_WINDOW,close_fds=True)
        job = _WindowsJob(process.pid)
        report.update(pid=process.pid,launch_tick=tick,command=command)
        (output/'process.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        quit_tick = None
        while True:
            text = log();rows = trace_rows()
            require('Native Quit probe failed:' not in text and 'Local menu initialization failed:' not in text,'native Quit ownership/callback probe failed')
            require(not any(marker in text for marker in ('Practice stopped in ','Offline loop stopped in ',
                        'Offline practice initialization failed:')),'post-practice native failure')
            require(not any(r['event'] in ('probe.failed','OnConfirm.exception') for r in rows),'native Quit callback reported failure')
            dispatch = [r for r in rows if r['event']=='OnConfirm.dispatch']
            if dispatch:
                require(args.mode=='confirm' and len(dispatch)==1,'unexpected/repeated Quit dispatch')
                quit_tick = dispatch[0]['tick'];report['quit_dispatch_tick'] = quit_tick
                observed_exit = observe_exit(process,quit_tick,clock)
                if observed_exit is not None:
                    report['observed_exit_tick'] = observed_exit
                    break
            else:
                require(process.poll() is None,'native process exited before the expected diagnostic result')
                if args.mode=='inventory' and 'NATIVE QUIT inventory passed: callbacks=0' in text: break
                if args.mode=='cancel' and 'NATIVE QUIT cancel passed:' in text: break
                require(time.monotonic()-started<args.timeout,'native menu/dialog diagnostic deadline reached')
            time.sleep(.1)
        rows = trace_rows();events = [r['event'] for r in rows]
        require(rows and all(r['pid']==process.pid and r['tick']>=tick and type(r['thread']) is int for r in rows) and
                all(a['tick']<=b['tick'] for a,b in zip(rows,rows[1:])) and events[0]=='armed','native Quit trace identity/order invalid')
        require('NATIVE QUIT owned menu verified:' in log(),'owned menu proof missing')
        if args.mode=='confirm':
            prelude = ['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return']
            expected = prelude+['RGameSingleton.OnDestroy.enter','RGameInstance.Dispose.enter','RGameInstance.Dispose.return']
            ai_events = ['AIManager.Dispose.enter','AIManager.Dispose.return']
            end = ['RGameSingleton.OnDestroy.return']
            allowed = (prelude,) if args.default_recipe else (expected+end,expected+ai_events+end)
            require(events in allowed and process.returncode==0 and quit_tick is not None and
                    report['observed_exit_tick']-quit_tick<60000,
                    'natural original Quit/disposal proof incomplete')
            report.update(natural_exit=True,native_quit_passed=True,exit_code=process.returncode,
                          original_disposal_traced=not args.default_recipe,
                          instance_disposal_boundary_seconds=(rows[7]['tick']-rows[6]['tick'])/1000 if not args.default_recipe else None,
                          ai_disposal_observed=events==expected+ai_events+end,
                          ai_disposal_boundary_seconds=(rows[9]['tick']-rows[8]['tick'])/1000 if events==expected+ai_events+end else None,
                          observed_exit_seconds_after_dispatch=(report['observed_exit_tick']-quit_tick)/1000)
        elif args.mode=='cancel':
            require(events==['armed','Show.dispatch','Show.return','OnCancel.dispatch','OnCancel.return','Cancel.verified'] and process.poll() is None,
                    'original Cancel/release proof incomplete')
        else: require(events==['armed'] and process.poll() is None,'inventory invoked a lifecycle callback')
        if args.capture_dialog:
            capture = runtime/('native-quit-'+profile+'.png');raw = capture.read_bytes()
            require(raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>8,'original modal capture missing')
            (output/'quit-dialog.png').write_bytes(raw);report['capture_sha256'] = hashlib.sha256(raw).hexdigest()
        else:
            require(not (runtime/('native-quit-'+profile+'.png')).exists(),'noncapture probe unexpectedly captured a frame')
        report['local_settings'] = startup.native_settings_evidence(game,output,process.pid,tick,profile)
        if getattr(args,'startup_tasks_audit',False):
            from tools.startup_task_evidence import evidence
            report['startup_tasks'] = evidence(log(),thread=rows[0]['thread'])
        if args.after_practice: report['practice'] = practice_evidence(game,output,process.pid,log())
        if getattr(args,'replay_binding_inventory',False):
            from tools.replay_binding_evidence import validate
            report['replay_binding_inventory'] = validate(log())
        if getattr(args,'replay_signal_inventory',False):
            from tools.replay_signal_evidence import validate
            report['replay_signal_inventory'] = validate(log())
        if getattr(args,'replay_nody_inventory',False):
            from tools.replay_nody_evidence import validate
            report['replay_nody_inventory'] = validate(log())
        if getattr(args,'telemetry_audit',False):
            report['telemetry']=telemetry_evidence(log(),rows,hashlib.sha256((game/'UnityPlayer.dll').read_bytes()).hexdigest(),
                after_practice=args.after_practice,device_probe=getattr(args,'telemetry_device_probe',False))
        if getattr(args,'telemetry_cache_probe',False) or getattr(args,'telemetry_cache_disk_probe',False):
            from tools.telemetry_cache_evidence import validate
            report['telemetry_cache_contract']=validate(log(),rows,disk_probe=getattr(args,'telemetry_cache_disk_probe',False))
        report['trace'] = rows;report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        if process is not None:
            if process.poll() is None:
                report['forced_cleanup'] = True;process.terminate()
            process.wait(timeout=15)
            (output/'native.log').write_text(log()+'\n',encoding='utf-8')
            if trace.exists():
                (output/'quit-trace.jsonl').write_bytes(trace.read_bytes())
                report['trace'] = trace_rows()
            waiting = runtime/('native-quit-'+profile+'-waiting.png')
            if waiting.exists():
                raw = waiting.read_bytes();(output/'waiting-dialog.png').write_bytes(raw)
                report['waiting_capture_sha256'] = hashlib.sha256(raw).hexdigest()
            report.update(exit_code=process.returncode,owned_process_reaped=True)
        if job is not None: job.close()
        try: report['shared_settings_after'] = startup.shared_state(args.shared_settings.resolve())
        except OSError as error: report.update(passed=False,shared_settings_read_error=repr(error))
        report['shared_settings_unchanged'] = ('shared_settings_before' in report and 'shared_settings_after' in report and
                                              report['shared_settings_before']==report['shared_settings_after'])
        report.update(elapsed_seconds=time.monotonic()-started,source_sha256_at_finish=sources())
        report['source_files_unchanged'] = report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['passed'] &= report.get('owned_process_reaped',False) and report['source_files_unchanged'] and report['shared_settings_unchanged']
        if args.mode=='confirm': report['passed'] &= report['natural_exit'] and not report['forced_cleanup']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','mode','natural_exit','forced_cleanup','error','elapsed_seconds') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game','output','shared-settings'): parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--helper-build-receipt',type=Path,required=True)
    parser.add_argument('--profile',help='explicit owned nativestest_ profile for a seeded native-settings regression')
    parser.add_argument('--display-name',help='bounded diagnostic name for replay filename failure controls')
    parser.add_argument('--storage-directory-fault',action='store_true',help='owned original managed directory failure control')
    parser.add_argument('--backup-notice-smoke',action='store_true',help='explicit owned backup warning capture and original acknowledgment')
    parser.add_argument('--backup-write-smoke',action='store_true',help='explicit owned original writer Boolean-result probe')
    parser.add_argument('--startup-tasks-audit',action='store_true',help='opt-in original startup Task/pump observation; requires owned diagnostic patch')
    parser.add_argument('--telemetry-audit',action='store_true',help='require read-only startup/lifecycle/pre-original-Quit field observations')
    parser.add_argument('--telemetry-device-probe',action='store_true',help='one guarded no-argument device API call in an owned menu,never during teardown')
    parser.add_argument('--telemetry-cache-probe',action='store_true',help='explicit owned scoped original cache-path diagnostic; does not prove startup cache isolation')
    parser.add_argument('--telemetry-cache-disk-probe',action='store_true',help='real original cache manager/readers on fresh owned authored files; no startup isolation or delivery claim')
    parser.add_argument('--after-practice',action='store_true',help='explicit automated one-match result/Continue before original menu Quit')
    parser.add_argument('--replay-binding-inventory',action='store_true',help='read existing hidden replay-button actions in healthy owned practice; no click')
    parser.add_argument('--replay-signal-inventory',action='store_true',help='read existing UIButton broadcast subscribers; no signal dispatch')
    parser.add_argument('--replay-nody-inventory',action='store_true',help='read existing Nody callback/graph/port/event data; no graph transition')
    parser.add_argument('--default-recipe',action='store_true',help='qualify natural exit using the default patch without optional teardown hooks')
    parser.add_argument('--mode',choices=('inventory','cancel','confirm'),default='cancel')
    parser.add_argument('--visible',action='store_true')
    parser.add_argument('--capture-dialog',action='store_true',help='explicit GPU capture; omit to avoid capture work during the exit test')
    parser.add_argument('--timeout',type=int,default=180)
    raise SystemExit(run(parser.parse_args()))
