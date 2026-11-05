"""Bounded direct offline startup234, instrumented original asset-completion Quit.

Not an ordinary packaged-launch, physical-input, I/O-stall or hung-engine test.
The controller owns one suspended child/job, a fresh profile and an attach gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import tomllib
import traceback

from tools import asset_quit_probe, verify_native_quit, verify_unified_startup
from tools.owned_suspended_launch import SuspendedChild, job_accounting
from tools.verify_native_storage import snapshot

ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(args):
    game, output, seed, receipt = (getattr(args,n).resolve() for n in ('game','output','seed','receipt'))
    owned=Path(os.environ['LOCALAPPDATA'])/'BattleAcesDiagnostics/local'
    assert all(p.is_relative_to(owned) for p in (game,output,seed,receipt)) and not output.exists()
    assert 'replay230-manual01' not in str(game)
    helper=verify_native_quit.verify_build_receipt(game,receipt)
    output.mkdir()
    shared=Path.home()/'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
    def channels():
        return dict(settings=verify_unified_startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    def identities():
        return {n:sha(game/n) for n in ('Battle Aces.exe','GameAssembly.dll','BattleAcesOffline.dll','.battleaces-resurrection/patch-manifest.json')}
    source=verify_native_quit.sources()|{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in (Path(__file__),Path(asset_quit_probe.__file__),ROOT/'tools/owned_suspended_launch.py')}
    for name,digest in source.items():
        dest=output/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest);assert sha(dest)==digest
    profile='nativestest_assetquit_'+secrets.token_hex(6)
    folder=game/'.battleaces-resurrection/profiles'/profile;folder.mkdir()
    settings=folder/'gameconfig-localuser.toml';shutil.copyfile(seed,settings)
    (output/'settings-before.toml').write_bytes(settings.read_bytes())
    report=dict(passed=False,scope=__doc__,profile=profile,source_sha256=source,helper_build=helper,
                shared_before=channels(),identities_before=identities(),settings_before=sha(settings))
    command=[str(game/'Battle Aces.exe'),'-offline-practice','-practice-ai-experimental',
             '-local-profile='+profile,'-player-name=Asset Quit Check',
             '-screen-fullscreen','0','-screen-width','960','-screen-height','540','-logFile',str(output/'game.log')]
    report['command']=command
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
    child=None;started=time.monotonic()
    try:
        child=SuspendedChild.create(command,cwd=game,startupinfo=info,owned_root=owned)
        script,config=asset_quit_probe.build_source(game,output,child.pid,request_at=args.request_at)
        (output/'probe.js').write_text(script,encoding='utf-8');report['probe']=config
        ready=dict(pid=child.pid,script=str(output/'probe.js'),resume_gate=str(output/'resume.ready'))
        (output/'attach.json').write_text(json.dumps(ready,indent=2))
        print(json.dumps(dict(stage='attach_required',**ready)),flush=True)
        deadline=time.monotonic()+120
        while not (output/'resume.ready').exists():
            assert child.poll() is None and time.monotonic()<deadline,'attach gate deadline/early exit'
            time.sleep(.05)
        assert (output/'resume.ready').read_bytes()==b'REA observer loaded\n'
        rows=[json.loads(line) for line in (output/'asset-quit.jsonl').read_text().splitlines()]
        assert any(r['kind']=='observer-ready' and r['pid']==child.pid for r in rows)
        assert not any(r['kind']=='error' for r in rows)
        child.resume();report['resume_tick']=child.receipt['resume_return_tick']
        deadline=time.monotonic()+120
        while child.poll() is None and time.monotonic()<deadline:time.sleep(.1)
        assert child.poll()==0,'native exit0 missing before deadline'
        report['natural_exit']=True
        rows=[json.loads(line) for line in (output/'asset-quit.jsonl').read_text().splitlines()]
        report['native_evidence']=asset_quit_probe.validate(rows,child.pid)
        report['passed']=True
    except BaseException as e:
        report.update(error=repr(e),traceback=traceback.format_exc())
    finally:
        if child:
            child.close();report['owned_child']=child.receipt
            native=game/'investigation/runtime'/f'dedicated-native-{child.pid}.log'
            if native.exists():shutil.copyfile(native,output/'native.log')
        report.update(shared_after=channels(),identities_after=identities(),settings_after=sha(settings),elapsed_seconds=time.monotonic()-started)
        (output/'settings-after.toml').write_bytes(settings.read_bytes())
        report['settings_parsed_unchanged']=tomllib.loads((output/'settings-before.toml').read_text(encoding='utf-8-sig'))==tomllib.loads(settings.read_text(encoding='utf-8-sig'))
        report['source_unchanged']=all(sha(ROOT/n)==h for n,h in source.items())
        report['shared_unchanged']=report['shared_before']==report['shared_after']
        report['identities_unchanged']=report['identities_before']==report['identities_after']
        report['passed'] &= bool(child and not child.receipt['forced_cleanup'] and child.receipt['owned_process_reaped'] and child.receipt['job_final']['active_processes']==0 and report['source_unchanged'] and report['shared_unchanged'] and report['identities_unchanged'] and report['settings_parsed_unchanged'])
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report.get(k) for k in ('passed','natural_exit','error','elapsed_seconds')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('game','output','seed','receipt'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--request-at',choices=('completion','loader-return'),default='loader-return')
    raise SystemExit(run(p.parse_args()))
