"""Owned recipe38 running-recovery package run with passive SDK-root changes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
WATCH_SCRIPT = ROOT/'tools/watch_sdk_cache_events.ps1'


def now():
    return datetime.now(timezone.utc).isoformat()


def start_watch(root: Path, folder: Path):
    folder.mkdir(parents=True,exist_ok=False)
    args=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(WATCH_SCRIPT),
          '-Root',str(root),'-Output',str(folder/'watch.json'),
          '-Ready',str(folder/'ready.txt'),'-Stop',str(folder/'stop.txt'),
          '-TimeoutSeconds','420']
    stdout=(folder/'stdout.txt').open('wb')
    stderr=(folder/'stderr.txt').open('wb')
    process=subprocess.Popen(args,cwd=ROOT,stdout=stdout,stderr=stderr,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if (folder/'ready.txt').is_file():return process,stdout,stderr
        if process.poll() is not None:break
        time.sleep(.1)
    if process.poll() is None:
        process.terminate();process.wait(timeout=5)
    stdout.close();stderr.close()
    raise RuntimeError(f'passive watcher failed readiness: {folder}')


def stop_watch(process,stdout,stderr,folder):
    (folder/'stop.txt').write_text(now(),encoding='utf-8')
    try: code=process.wait(timeout=20)
    finally: stdout.close();stderr.close()
    if code!=0 or not (folder/'watch.json').is_file():
        raise RuntimeError(f'passive watcher failed: {folder}, exit={code}')
    return json.loads((folder/'watch.json').read_text(encoding='utf-8'))


def run(args):
    if os.name!='nt':raise RuntimeError('Windows owned runtime required')
    paths={key:getattr(args,key).resolve() for key in
           ('packages','game','assets','case','watch','control','helper_receipt','shared_settings')}
    if not all(path.is_relative_to(ROOT/'local') for key,path in paths.items()
               if key!='shared_settings'):
        raise RuntimeError('owned ignored local/ paths required')
    source=json.loads((ROOT/'local/privacy269-startup01/verification.json').read_text(encoding='utf-8'))
    sdk_root=Path(source['sdk_cache_root'])
    if not sdk_root.is_dir():raise RuntimeError('source-bound SDK root is absent')
    if any(path.exists() for path in (paths['case'],paths['watch'],paths['control'])):
        raise RuntimeError('fresh output directories required')
    record={'passed':False,'sdk_root':str(sdk_root),'watch_script':str(WATCH_SCRIPT),
            'case':str(paths['case']),'started_utc':now()}
    process=stdout=stderr=None
    try:
        process,stdout,stderr=start_watch(sdk_root,paths['watch'])
        record['watch_ready_utc']=now()
        command=[sys.executable,'-m','tools.verify_packaged_multiplayer',
                 '--packages',str(paths['packages']),'--game',str(paths['game']),
                 '--assets',str(paths['assets']),'--output',str(paths['case']),
                 '--helper-build-receipt',str(paths['helper_receipt']),
                 '--shared-settings',str(paths['shared_settings']),
                 '--mode','1','--humans','2','--recover-running',
                 '--disconnect-after-frame','600','--timeout','300']
        record['verifier_command']=command
        record['verifier_launched_utc']=now()
        with (paths['watch']/'verifier-stdout.txt').open('wb') as out, \
             (paths['watch']/'verifier-stderr.txt').open('wb') as err:
            completed=subprocess.run(command,cwd=ROOT,stdout=out,stderr=err)
        record['verifier_finished_utc']=now()
        record['verifier_exit_code']=completed.returncode
        if completed.returncode!=0:raise RuntimeError('packaged running recovery failed')
        record['passed']=True
    except BaseException as error:
        record['error']=f'{type(error).__name__}: {error}'
    finally:
        if process is not None:
            try:record['watch_result']=stop_watch(process,stdout,stderr,paths['watch'])
            except BaseException as error:
                record['passed']=False;record['watch_error']=f'{type(error).__name__}: {error}'
        if 'watch_result' in record:
            observed=record['watch_result']
            if not (observed['stopped_by_sentinel'] and
                    all(value==0 for value in observed['counts'].values()) and
                    observed['started_utc']<=record.get('verifier_launched_utc','') and
                    observed['finished_utc']>=record.get('verifier_finished_utc','z')):
                record['passed']=False;record['watch_error']='SDK-root watcher interval/counts differ'
        try:
            control_root=paths['control']/'root'
            control_root.mkdir(parents=True,exist_ok=False)
            control_folder=paths['control']/'observer'
            positive,out,err=start_watch(control_root,control_folder)
            try:
                probe=control_root/'positive-control.txt'
                probe.write_text('created',encoding='utf-8');time.sleep(.5)
                probe.write_text('changed',encoding='utf-8');time.sleep(.5)
                probe.unlink();time.sleep(.5)
            finally:record['control_result']=stop_watch(positive,out,err,control_folder)
            counts=record['control_result']['counts']
            if not (counts['Created']>=1 and counts['Changed']>=1 and
                    counts['Deleted']>=1 and counts['Error']==0):
                raise RuntimeError('positive watcher control missed file changes')
        except BaseException as error:
            record['passed']=False;record['control_error']=f'{type(error).__name__}: {error}'
        if paths['watch'].is_dir():
            record['finished_utc']=now()
            (paths['watch']/'orchestration.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return 0 if record['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('packages','game','assets','case','watch','control','helper-receipt','shared-settings'):
        parser.add_argument('--'+key,type=Path,required=True)
    return run(parser.parse_args())


if __name__=='__main__':raise SystemExit(main())
