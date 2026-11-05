"""Replay retained audit records through a packaged logger; no game or listener."""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from tools.package_integrity import verify
from tools.verify_packaged_multiplayer import Child,imports
from tools.verify_packaged_play import job_accounting
from tools.audit_stage_probe import review_stages

ROOT=Path(__file__).resolve().parents[1]
SOURCES=('tools/verify_audit_stages.py','tools/audit_stage_probe.py','tools/timing_probe.py',
         'tools/verify_packaged_multiplayer.py','tools/verify_packaged_play.py','tools/package_integrity.py',
         'server/worker_client.py')


def hashes():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


DRIVER=r'''
import hashlib,json,sys,time,traceback
from pathlib import Path
from server import host_audit
from tools.package_integrity import verify
request=json.loads(Path(sys.argv[1]).read_bytes());output=Path(request['output']);package=Path(request['package'])
assert json.loads(sys.stdin.buffer.read(128))=={}
report=dict(passed=False,production_modules={});audit=stages=None
timing=TimingObservations(capacity=131072)
try:
    verify(package,'server')
    module=Path(host_audit.__file__).resolve();assert module.is_relative_to(package/'program/app')
    report['production_modules']['server.host_audit']=dict(path=str(module),sha256=hashlib.sha256(module.read_bytes()).hexdigest())
    deadline=time.monotonic()+10
    while not (output/'job-ready').exists():assert time.monotonic()<deadline;time.sleep(.02)
    assert (output/'job-ready').read_bytes()==b'owned job attached\n'
    records=[];total=0
    for item in request['inputs']:
        raw=Path(item['path']).read_bytes();total+=len(raw)
        assert total<=64*1024*1024 and hashlib.sha256(raw).hexdigest()==item['sha256']
        records.extend(json.loads(line) for line in raw.decode('utf-8').splitlines())
        assert len(records)<=40000
    assert records
    normalize=lambda row:{key:value for key,value in row.items() if key not in ('utc','session','perf_counter_ns')}
    expected=[normalize(row) for row in records]
    original_json=host_audit.json
    audit=host_audit.HostAudit(output/'replayed-logs',max_bytes=8*1024*1024,backups=8,diagnostics=True)
    stages=AuditStages(audit,host_audit,timing)
    began=time.perf_counter()
    for row in expected:
        assert isinstance(row['event'],str)
        stages.call(row['event'],**{key:value for key,value in row.items() if key!='event'})
    audit.close();stages.detach();stages=None
    report['elapsed_replay_seconds']=time.perf_counter()-began
    assert host_audit.json is original_json and '_rotate' not in audit.__dict__ and audit.stream is None
    actual=[];paths=sorted((output/'replayed-logs').glob('events.jsonl*'),reverse=True)
    for path in paths:
        assert path.stat().st_size<=8*1024*1024
        actual.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())
    assert [normalize(row) for row in actual]==expected,'replayed events differ or retention lost records'
    stamps={row['audit_id']:row for row in timing.rows if row['kind']=='audit'}
    assert len(stamps)==len(actual)
    assert all(stamps[i+1]['started_ns']<=row['perf_counter_ns']<=stamps[i+1]['finished_ns'] for i,row in enumerate(actual))
    assert all(Path(item['path']).is_file() and hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['sha256'] for item in request['inputs'])
    report.update(passed=True,events=len(expected),input_bytes=total,output_files=len(paths),original_records_in_order=True,
                  producer_timestamps_within_calls=True,observer_detached=True,python=sys.version)
except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
finally:
    try:
        if audit is not None:audit.close()
    finally:
        if stages is not None:stages.detach()
    (output/'audit-timing.json').write_text(json.dumps(timing.report(),indent=2)+'\n')
    (output/'audit-driver.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
'''


def run(args):
    package,evidence,output=(value.resolve() for value in (args.package,args.evidence,args.output))
    if not all(path.is_relative_to(ROOT/'local') for path in (package,evidence,output)) or output.exists():
        raise ValueError('owned local inputs and unused output required')
    inventory=verify(package,'server')
    inputs=[]
    for path in sorted((evidence/'host-data/logs').glob('events.jsonl*'),reverse=True):
        if not re.fullmatch(r'events\.jsonl(?:\.[1-8])?',path.name) or path.is_symlink() or not path.is_file():
            raise ValueError('ordinary retained audit journals required')
        inputs.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size))
    if not inputs or sum(item['bytes'] for item in inputs)>64*1024*1024:
        raise ValueError('bounded nonempty input required')
    output.mkdir();child=None;began=time.monotonic()
    report=dict(passed=False,scope=__doc__,source_before=hashes(),inputs=inputs,forced_cleanup=False)
    script=(ROOT/'tools/timing_probe.py').read_text()+'\n'+(ROOT/'tools/audit_stage_probe.py').read_text()+'\n'+DRIVER
    try:
        child=Child(package,output/'driver',script,dict(package=str(package),output=str(output/'driver'),inputs=inputs),{})
        child.process.wait(timeout=120)
        report['child_exit_code']=child.process.returncode
        driver=json.loads((child.output/'audit-driver.json').read_bytes());report['driver']=driver
        if child.process.returncode!=0:raise RuntimeError('packaged audit replay failed')
        imports(driver,package,inventory)
        path=child.output/'audit-timing.json'
        report['timing']=review_stages(json.loads(path.read_bytes()))
        report['timing_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        if report['timing']['calls']!=driver['events']:raise RuntimeError('audit event coverage differs')
        report['passed']=True
    except BaseException as error:report['error']=repr(error)
    finally:
        if child:
            report['job']=job_accounting(child.job.handle)
            report['forced_cleanup']=report['job']['active_processes']!=0
            child.job.close();child.process.wait(timeout=15)
            child.stdout.close();child.stderr.close()
            report['adapter_unchanged']=child.unchanged()
        report['source_after']=hashes()
        report['source_unchanged']=report['source_before']==report['source_after']
        report['package_unchanged']=verify(package,'server')==inventory
        report['inputs_unchanged']=all(hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['sha256'] for item in inputs)
        report['elapsed_seconds']=time.monotonic()-began
        report['passed'] &= all(report.get(key,False) for key in ('adapter_unchanged','source_unchanged','package_unchanged','inputs_unchanged')) and not report['forced_cleanup']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report.get(key) for key in ('passed','error','elapsed_seconds','forced_cleanup')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','evidence','output'):parser.add_argument('--'+name,type=Path,required=True)
    raise SystemExit(run(parser.parse_args()))
