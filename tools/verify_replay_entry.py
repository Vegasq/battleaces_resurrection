"""Owned packaged selected-file playback; diagnostic controls supply Cancel/Leave/Quit.

The bundled ordinary command selects and loads the file. The external adapter
adds observation and original control dispatch only; it never loads a replay.
This does not qualify physical input or the Windows file chooser.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time
import traceback

from tools.package_integrity import verify
from tools.owned_suspended_launch import SuspendedChild
from tools.verify_packaged_multiplayer import owned_diagnostic_path, publish_empty_gate
from tools.verify_native_storage import snapshot, replay_evidence
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.replay_menu_evidence import validate
from tools.run_secure_match import read_native_log

ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

DRIVER=r'''
import json,sys,subprocess,ctypes
from pathlib import Path
from types import SimpleNamespace
out=Path(__file__).resolve().parent
request=json.loads((out/'request.json').read_bytes())
sys.path.insert(0,str(Path(request['package'])/'program/app'))
from tools import package_client
from client_patch.transport import launcher
from client_patch.transport import rc_setup
resolver=rc_setup.Resolver
class ObservedResolver(resolver):
    async def __call__(self):
        with (out/'unexpected-resolver-call.txt').open('a') as f:f.write('OPEN requested\n')
        return await super().__call__()
rc_setup.Resolver=ObservedResolver
original=launcher.subprocess
def spawn(command,**kwargs):
    command=list(command)
    assert '-unified-client' in command and any(s.startswith('-replay-file=') for s in command)
    assert not any('smoke' in s for s in command)
    mode=request.get('control_mode','healthy')
    assert mode in ('healthy','observe-refusal')
    if mode=='healthy': command+=['-native-replay-entry-smoke','-native-replay-menu-button-smoke',
              '-native-replay-menu-cancel-smoke','-replay-binding-inventory',
              '-replay-signal-inventory','-replay-nody-inventory',
              '-native-quit-smoke','-native-quit-gate-smoke','-native-quit-mode=confirm']
    info=kwargs['startupinfo'].copy();info.wShowWindow=0;kwargs['startupinfo']=info
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong
    tick=clock();child=original.Popen(command,**kwargs)
    with (out/'native-launch.json').open('x') as f:
        json.dump(dict(pid=child.pid,launch_tick=tick,command=command,diagnostic_load_calls=0),f,indent=2)
    return child
launcher.subprocess=SimpleNamespace(**{**vars(original),'Popen':spawn})
try:
    code=package_client.main(['start','--config',request['config'],'--replay',request['replay']])
    with (out/'child-result.json').open('x') as f:json.dump(dict(exit_code=code),f)
finally:
    launcher.subprocess=original
    rc_setup.Resolver=resolver
raise SystemExit(code)
'''

def run(args):
    package,game,replay,seed,output,shared=(getattr(args,n).resolve() for n in
        ('package','game','replay','seed_settings','output','shared_settings'))
    assert os.name=='nt' and all(owned_diagnostic_path(p) for p in (package,game,replay,seed,output))
    assert not output.exists() and 60<=args.timeout<=300
    verify(package,'client')
    assert sha(package/'program/client-helper/BattleAcesOffline.dll')==sha(game/'BattleAcesOffline.dll')
    output.mkdir()
    profile='nativestest_replayui_'+secrets.token_hex(6)
    folder=game/'.battleaces-resurrection/profiles'/profile;folder.mkdir(parents=True)
    shutil.copyfile(seed,folder/'gameconfig-localuser.toml')
    selected=output/'selected replay.rep';shutil.copyfile(replay,selected)
    config=output/'client.json'
    config.write_text(json.dumps(dict(schema=3,game_directory=str(game),display_name='Replay Entry',
        local_profile=profile)))
    request=dict(package=str(package),game=str(game),config=str(config),replay=str(selected),profile=profile)
    (output/'request.json').write_text(json.dumps(request,indent=2))
    (output/'driver.py').write_text(DRIVER)
    sources=quit_probe.sources()|{str(Path(__file__).relative_to(ROOT)):sha(__file__)}
    for name,digest in sources.items():
        dest=output/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,dest);assert sha(dest)==digest
    def channels():return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    report=dict(passed=False,scope=__doc__,profile=profile,source_sha256=sources,shared_before=channels(),
        package_manifest_sha256=sha(package/'package-manifest.json'),replay=replay_evidence(selected.read_bytes()),
        settings_before=sha(folder/'gameconfig-localuser.toml'),config_sha256=sha(config),forced_cleanup=False)
    child=None;started=time.monotonic();launch=None;released=False
    try:
        child=SuspendedChild.create([str(package/'program/runtime/python.exe'),'-I','-B',str(output/'driver.py')],
            cwd=output,creationflags=subprocess.CREATE_NO_WINDOW,owned_root=Path(os.environ['LOCALAPPDATA'])/'BattleAcesDiagnostics/local')
        child.resume()
        while time.monotonic()-started<args.timeout:
            if launch is None and (output/'native-launch.json').exists():
                try:launch=json.loads((output/'native-launch.json').read_bytes())
                except json.JSONDecodeError:pass
            if launch:
                log=game/'investigation/runtime'/f"dedicated-native-{launch['pid']}.log"
                text=read_native_log(game,launch['pid'],since_tick=launch['launch_tick']).replace('\r\n','\n') if log.exists() else ''
                for marker in ('Replay file entry refused:','Replay file entry stopped:',
                               'Native replay menu control failed:','Native Quit probe failed:',
                               'Client lifecycle invariant failed:','Offline initialization failed:'):
                    assert marker not in text,marker
                if not released and 'NATIVE REPLAY ENTRY control passed:' in text:
                    report['playback']=validate(text,report['replay'],button_exit=True,cancel_first=True,ordinary_entry=True)
                    publish_empty_gate(folder/'native-quit.ready');released=True
            if child.poll() is not None:break
            time.sleep(.2)
        assert child.poll()==0,'bundled controller did not exit0 before deadline'
        assert launch and released
        text=read_native_log(game,launch['pid'],since_tick=launch['launch_tick']).replace('\r\n','\n')
        report['playback']=validate(text,report['replay'],button_exit=True,cancel_first=True,ordinary_entry=True)
        trace=quit_probe.current_trace_rows((folder/'quit-trace.jsonl').read_bytes(),launch['pid'],launch['launch_tick'])
        assert [r['event'] for r in trace]==['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return']
        report['quit_trace']=trace
        assert 'Client world acquired:' in text and 'owner=replay' in text
        assert 'Client world acquired:' not in text.replace(next(line for line in text.splitlines() if 'Client world acquired:' in line),'')
        assert 'COMMUNITY transport connected:' not in text
        assert not (output/'unexpected-resolver-call.txt').exists(),'replay requested a remote connection'
        assert sha(folder/'gameconfig-localuser.toml')==report['settings_before']
        assert sha(selected)==report['replay']['sha256'] and sha(replay)==report['replay']['sha256']
        assert sha(config)==report['config_sha256']
        assert json.loads((output/'child-result.json').read_bytes())['exit_code']==0
        verify(package,'client')
        report['passed']=True
    except BaseException:
        report['error']=traceback.format_exc()
    finally:
        if child:
            child.close();report['child']=child.receipt
            report['forced_cleanup']=child.receipt['forced_cleanup']
            report['passed'] &= not report['forced_cleanup'] and child.receipt['job_final']['active_processes']==0
        report['shared_after']=channels();report['shared_unchanged']=report['shared_before']==report['shared_after']
        report['source_unchanged']=all(sha(ROOT/n)==v for n,v in sources.items())
        report['passed'] &= report['shared_unchanged'] and report['source_unchanged']
        report['elapsed_seconds']=time.monotonic()-started
        with (output/'verification.json').open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps({k:report[k] for k in ('passed','error','forced_cleanup','elapsed_seconds') if k in report},indent=2))
    return 0 if report['passed'] else 1

def refusal_evidence(text,case):
    """Only the admission boundary; never infer a dialog action or natural exit."""
    assert case in ('locked','missing','invalid-deflate'), 'unsupported refusal case'
    expected=('replay data is invalid, incomplete or exceeds supported decoding limits'
        if case=='invalid-deflate' else 'cosmetic state requires an ordinary local file/directory')
    lines=re.findall(r'^\[\d+\] Replay file entry refused: (.+)$',text.replace('\r\n','\n'),re.M)
    assert lines==[expected], 'unexpected replay refusal'
    assert 'Unified client ready:' in text, 'ordinary client did not reach its local menu'
    for marker in ('Replay file entry:','Client world acquired:','Original replay runner update restored:',
                   'Replay file entry stopped:','Client lifecycle invariant failed:',
                   'Offline initialization failed:','NATIVE REPLAY MENU','NATIVE REPLAY ENTRY'):
        assert marker not in text, 'refusal crossed or failed the admission boundary: '+marker
    return dict(ordinary_admission_refused=True,original_file_loader_called=False,
        world_acquired=False,dialog_action_qualified=False,retry_qualified=False,natural_quit_qualified=False)


def locked_refusal_evidence(text):
    return refusal_evidence(text,'locked')


def missing_file_evidence(selected):
    try:
        with selected.open('rb'):pass
    except FileNotFoundError as error:
        # CRT-backed Python opens can report errno2 with winerror=None on Windows.
        assert error.errno==2
        return dict(errno=error.errno,winerror=getattr(error,'winerror',None))
    raise AssertionError('selected missing fixture unexpectedly exists')


def run_refusal(args,case):
    """Ordinary input refusal, no GUI automation, explicitly incomplete lifecycle."""
    from tools.verify_profile_storage import OwnedFileLock
    assert case in ('locked','missing','invalid-deflate')
    package,game,replay,seed,output,shared=(getattr(args,n).resolve() for n in
        ('package','game','replay','seed_settings','output','shared_settings'))
    assert os.name=='nt' and all(owned_diagnostic_path(p) for p in (package,game,replay,seed,output))
    assert not output.exists() and 60<=args.timeout<=300
    verify(package,'client')
    assert sha(package/'program/client-helper/BattleAcesOffline.dll')==sha(game/'BattleAcesOffline.dll')
    output.mkdir()
    profile='nativestest_replayui_'+secrets.token_hex(6)
    folder=game/'.battleaces-resurrection/profiles'/profile;folder.mkdir(parents=True)
    shutil.copyfile(seed,folder/'gameconfig-localuser.toml')
    # Reuse the existing lock helper's narrow repo-local ownership contract.
    fixture=ROOT/'local'/('replay-refusal-'+secrets.token_hex(6));fixture.mkdir()
    selected=fixture/'selected replay.rep'
    if case=='locked':shutil.copyfile(replay,selected)
    elif case=='invalid-deflate':
        import zlib
        from tools.replay_codec_fixtures import payloads
        selected.write_bytes(payloads()['invalid-deflate'])
        try:zlib.decompress(selected.read_bytes(),-15)
        except zlib.error:pass
        else:raise AssertionError('authored fixture must be invalid raw DEFLATE')
    def selected_state():return dict(exists=selected.exists(),sha256=sha(selected) if selected.exists() else None)
    config=output/'client.json'
    config.write_text(json.dumps(dict(schema=3,game_directory=str(game),display_name='Replay Refusal',local_profile=profile)))
    request=dict(package=str(package),game=str(game),config=str(config),replay=str(selected),
        profile=profile,control_mode='observe-refusal',refusal_case=case)
    (output/'request.json').write_text(json.dumps(request,indent=2))
    (output/'driver.py').write_text(DRIVER)
    sources=quit_probe.sources()|{n:sha(ROOT/n) for n in ('tools/verify_replay_entry.py','tools/verify_profile_storage.py','tools/replay_codec_fixtures.py')}
    for name,digest in sources.items():
        dest=output/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/name,dest);assert sha(dest)==digest
    def channels():return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    report=dict(passed=False,admission_observation_passed=False,
        scope='Ordinary input admission only; no dialog input; forced owned cleanup; lifecycle NOT accepted',
        refusal_case=case,selected_before=selected_state(),profile=profile,source_sha256=sources,shared_before=channels(),
        package_manifest_sha256=sha(package/'package-manifest.json'),replay=replay_evidence(replay.read_bytes()),
        settings_before=sha(folder/'gameconfig-localuser.toml'),config_sha256=sha(config),forced_cleanup=False)
    child=None;lock=None;launch=None;observed=None;started=time.monotonic()
    try:
        if case=='locked':
            lock=OwnedFileLock(selected,fixture,allow_read=False)
            report['sharing_lock']=dict(probe_winerror=lock.probe_winerror,held_through_observation=True)
        elif case=='missing':
            report['missing_file_probe']=missing_file_evidence(selected)
        child=SuspendedChild.create([str(package/'program/runtime/python.exe'),'-I','-B',str(output/'driver.py')],
            cwd=output,creationflags=subprocess.CREATE_NO_WINDOW,owned_root=Path(os.environ['LOCALAPPDATA'])/'BattleAcesDiagnostics/local')
        child.resume()
        while time.monotonic()-started<args.timeout:
            assert child.poll() is None, 'controller exited before admission observation completed'
            if launch is None and (output/'native-launch.json').exists():
                try:launch=json.loads((output/'native-launch.json').read_bytes())
                except json.JSONDecodeError:pass
            if launch:
                log=game/'investigation/runtime'/f"dedicated-native-{launch['pid']}.log"
                text=read_native_log(game,launch['pid'],since_tick=launch['launch_tick']) if log.exists() else ''
                if 'Replay file entry refused:' in text:
                    report['admission']=refusal_evidence(text,case)
                    if observed is None:observed=time.monotonic()
                    if time.monotonic()-observed>=5:break
            time.sleep(.2)
        assert observed is not None and time.monotonic()-observed>=5,'refusal observation deadline'
        assert not any('smoke' in value or 'inventory' in value for value in launch['command'])
        assert not (output/'unexpected-resolver-call.txt').exists(),'replay requested remote OPEN'
        assert not (output/'child-result.json').exists(),'controller unexpectedly completed'
        assert sha(folder/'gameconfig-localuser.toml')==report['settings_before']
        assert sha(config)==report['config_sha256']
        if case=='invalid-deflate':
            # While the game still waits for dialog input, prove that its bounded
            # native decode and selected-file pin have both released this file.
            with OwnedFileLock(selected,fixture,allow_read=False) as reopened:
                report['exclusive_reopen_after_refusal']=dict(opened=True,conflicting_probe_winerror=reopened.probe_winerror)
            assert reopened.handle is None
        elif case=='missing':assert not selected.exists()
        report['observation_seconds']=time.monotonic()-observed
        report['admission_observation_passed']=True
    except BaseException:
        report['error']=traceback.format_exc()
    finally:
        if child:
            child.close();report['child']=child.receipt;report['forced_cleanup']=child.receipt['forced_cleanup']
            report['admission_observation_passed'] &= child.receipt['job_final']['active_processes']==0
        if lock:lock.close()
        report['lock_released']=lock is None or lock.handle is None
        report['selected_after']=selected_state()
        report['replay_unchanged']=report['selected_before']==report['selected_after'] and sha(replay)==report['replay']['sha256']
        report['settings_unchanged']=sha(folder/'gameconfig-localuser.toml')==report['settings_before']
        report['shared_after']=channels();report['shared_unchanged']=report['shared_before']==report['shared_after']
        report['source_unchanged']=all(sha(ROOT/n)==v for n,v in sources.items())
        report['admission_observation_passed'] &= all(report[n] for n in
            ('lock_released','replay_unchanged','settings_unchanged','shared_unchanged','source_unchanged'))
        if launch:
            shutil.copyfile(game/'investigation/runtime'/f"dedicated-native-{launch['pid']}.log",output/'native.log')
        report['elapsed_seconds']=time.monotonic()-started
        with (output/'verification.json').open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps({k:report[k] for k in ('passed','admission_observation_passed','error','forced_cleanup','elapsed_seconds') if k in report},indent=2))
    return 0 if report['admission_observation_passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for n in ('package','game','replay','seed-settings','output','shared-settings'):parser.add_argument('--'+n,type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=150)
    case_group=parser.add_mutually_exclusive_group()
    case_group.add_argument('--locked-refusal',action='store_true',
        help='observe ordinary sharing-lock refusal only; owned forced cleanup is NOT lifecycle acceptance')
    case_group.add_argument('--refusal-case',choices=('locked','missing','invalid-deflate'),
        help='observe one ordinary admission refusal only; never claims dialog recovery or normal Quit')
    args=parser.parse_args()
    case='locked' if args.locked_refusal else args.refusal_case
    return run_refusal(args,case) if case else run(args)

if __name__=='__main__':raise SystemExit(main())
