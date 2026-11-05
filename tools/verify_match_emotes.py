"""Owned original four-slot emote activation/expiry during one local-AI match.

Original callback and frame/UI state evidence; no physical click, visible pixel,
audio, network-peer delivery or all-item in-match claim.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
from tools import verify_native_quit as quit_probe
from tools.verify_native_replay_menu import scoped_spawn_module
from tools.run_secure_match import read_native_log
from tools.owned_suspended_launch import job_accounting
ROOT=Path(__file__).resolve().parents[1]
COMPLETE='MATCH EMOTE completed: buttons=4 originalLifetime=1 loadoutUnchanged=1'

def require(value,message):
    if not value:raise AssertionError(message)

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def sources():
    return quit_probe.sources() | {Path(__file__).relative_to(ROOT).as_posix():sha(__file__)}

def validate_cases(proof):
    require(proof.get('schema')==1 and proof.get('loadout_unchanged') is True
            and proof.get('physical_input_tested') is False and proof.get('visual_audio_verified') is False,'scope differs')
    rows=proof['observations']
    require(rows and [r['index'] for r in rows]==sorted(r['index'] for r in rows)
            and set(r['index'] for r in rows)=={0,1,2,3},'four ordered equipped slots required')
    require([r['tick'] for r in rows]==sorted(r['tick'] for r in rows),'observation order differs')
    owners=[]
    for index,item in enumerate([6,7,8,9]):
        group=[r for r in rows if r['index']==index]
        require(len(group)>=5 and group[0]['phase']=='dispatch-return' and group[-1]['phase']=='expired'
                and all(r['phase']=='frame' for r in group[1:-1]),'dispatch/frame/expiry evidence incomplete')
        first,last=group[0],group[-1];start,end,rate=first['start'],first['end'],first['rate']
        require(start>0 and 0<rate<=120 and end-start==3*rate,'original three-second lifetime differs')
        require(first['frame']==start and first['asset_present'] is True and first['asset_matches'] is True,'original activation missing')
        require([r['frame'] for r in group]==sorted(r['frame'] for r in group),'presented frames reversed')
        for r in group:
            require(r['item']==r['model_item']==item and r['portrait']==66 and r['vm_initialized'] is True
                    and (r['start'],r['end'],r['rate'])==(start,end,rate),'equipped model or lifetime changed')
            if r['asset_present']:
                require(r['asset_matches'] is True and r['state_start']==start and r['state_end']==end
                        and start<=r['frame']<=end and r['hidden'] is False,'active lifetime ownership differs')
            else:
                require(r['frame']>end and r['state_start']==r['state_end']==0,'early expiry or uncleared lifetime')
        active=[r for r in group if r['asset_present']]
        cleared=[r for r in group if not r['asset_present']]
        require(active and cleared and active[-1]['frame']>=end-2 and cleared[0]['frame']<=end+3,'expiry boundary observation gap')
        # Show/Hide transitions are not the fully Visible terminal state.
        # Require active animation while not hidden, then the observed hide.
        playing=[r for r in active if not r['hidden'] and r['solo_active'] and r['playing'] and r['graph_ready']]
        require(any(b['frame']>a['frame'] and b['seconds']>a['seconds']>=0
                    for i,a in enumerate(playing) for b in playing[i+1:]),'active animation did not advance')
        require(last['hidden'] is True and last['visible'] is False and last['asset_present'] is False
                and last['playing'] is False and last['solo_active'] is False
                and end<last['frame']<end+5*rate,'original hide did not settle')
        owners.extend((r['army'],r['view_id']) for r in group)
    require(len(set(owners))==1,'match emote display owner changed')

def validate_lifecycle(native,text,pid):
    require(native['pid']==pid and native['mode']=='confirm' and native['natural_exit'] is True
            and native['forced_cleanup'] is False and native['exit_code']==0 and native['owned_process_reaped'] is True
            and native['shared_settings_unchanged'] is True and native['source_files_unchanged'] is True,'normal Quit ownership differs')
    trace=native['trace']
    require([r['event'] for r in trace]==['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return']
            and all(r['pid']==pid for r in trace) and len({r['thread'] for r in trace})==1
            and [r['tick'] for r in trace]==sorted(r['tick'] for r in trace),'original Quit trace differs')
    markers=['PRACTICE SMOKE original EditDeck mode4 callback:',COMPLETE,'PRACTICE SMOKE native ConcedeGame (automated)',
             'Practice native EndOfGameResponse delivered;','PRACTICE SMOKE native Continue (automated)',
             'Practice returned: completed=1 mode=4 seat=-1 presenceRetained=0 standalone=1',
             'NATIVE QUIT owned menu verified:','NATIVE QUIT original confirmation dispatch:']
    require(all(text.count(m)==1 for m in markers) and [text.index(m) for m in markers]==sorted(text.index(m) for m in markers),
            'match/result/Continue/Quit sequence differs')

def run(args):
    game,output=args.game.resolve(),args.output.resolve()
    require(game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'),'owned ignored paths required')
    output.mkdir(parents=True,exist_ok=False)
    profile='nativestest_emmatch_'+secrets.token_hex(6)
    original_subprocess,original_job=quit_probe.subprocess,quit_probe._WindowsJob
    original_spawn=original_subprocess.Popen
    process=None
    report=dict(passed=False,scope=__doc__,profile=profile,sources_before=sources())
    class AccountingJob(original_job):
        def close(self):
            if self.handle:
                deadline=time.monotonic()+5;value=job_accounting(self)
                while value['active_processes'] and process is not None and process.poll() is not None and time.monotonic()<deadline:
                    time.sleep(.05);value=job_accounting(self)
                report['owned_job_before_close']=value
            super().close()
    def spawn(command,*positional,**keywords):
        nonlocal process
        require(Path(command[0]).resolve()==game/'Battle Aces.exe' and process is None,'one owned game required')
        command=list(command)+['-local-cosmetics-experimental','-cosmetics-emote-match-smoke',
            '-native-quit-after-practice','-practice-ai-smoke','-practice-ai-smoke-matches=1',
            '-practice-ai-smoke-frames=1200','-practice-ai-smoke-delay-ms=3000','-lan-audit','-lan-smoke']
        info=original_subprocess.STARTUPINFO();info.dwFlags|=original_subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
        keywords['startupinfo']=info
        keywords['creationflags']=original_subprocess.CREATE_NO_WINDOW
        process=original_spawn(command,*positional,**keywords)
        report.update(pid=process.pid,actual_arguments=command,automated_window_hidden=True)
        (output/'process.json').write_text(json.dumps(report,indent=2)+'\n')
        return process
    try:
        control=SimpleNamespace(game=game,output=output/'native-quit',shared_settings=args.shared_settings,
            helper_build_receipt=args.helper_build_receipt,profile=profile,display_name='Match Emote Probe',
            # This wrapper owns the emote/match sequence. The general Quit
            # verifier owns Quit, without its separate bot-movement gate.
            mode='confirm',visible=True,timeout=240,capture_dialog=False,after_practice=False,default_recipe=True)
        quit_probe.subprocess=scoped_spawn_module(original_subprocess,spawn);quit_probe._WindowsJob=AccountingJob
        result=quit_probe.run(control)
        native=json.loads((output/'native-quit/verification.json').read_bytes())
        require(result==0 and native['passed'] and native['natural_exit'] and not native['forced_cleanup']
                and native['exit_code']==0,'normal match/return/Quit incomplete')
        require(report['owned_job_before_close']==dict(total_processes=1,active_processes=0,total_terminated_processes=0),'owned job did not settle')
        text=read_native_log(game,process.pid)
        validate_lifecycle(native,text,process.pid)
        require(text.count(COMPLETE)==1 and 'MATCH EMOTE failed:' not in text,'original emote sequence incomplete')
        proof=json.loads((game/'investigation/runtime'/f'match-emote-cases-{process.pid}.json').read_bytes())
        validate_cases(proof)
        report.update(passed=True,native_cases=proof,native_verification_sha256=sha(output/'native-quit/verification.json'))
    except Exception as error:report['error']=repr(error)
    finally:
        quit_probe.subprocess=original_subprocess;quit_probe._WindowsJob=original_job
        report['sources_after']=sources();report['passed'] &= report['sources_before']==report['sources_after']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['passed','pid','error'] if k in report}))
    return 0 if report['passed'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['game','output','shared-settings','helper-build-receipt']:parser.add_argument('--'+name,type=Path,required=True)
    raise SystemExit(run(parser.parse_args()))
