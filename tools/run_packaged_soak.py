"""Own a bounded soak controller/worker job using a verified packaged runtime."""
from __future__ import annotations
import argparse,hashlib,json,subprocess,time
from pathlib import Path
from tools.owned_suspended_launch import SuspendedChild,job_accounting
from tools.package_integrity import verify

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def run(package,assets,output,*,seconds=120,frames=600,rounds=4,rooms=2):
    package,assets,output=(Path(path).resolve() for path in (package,assets,output))
    if not all(path.is_relative_to(ROOT/'local') for path in (package,assets,output)) or output.is_relative_to(package) or output.is_relative_to(assets):
        raise ValueError('separate owned local package/assets/output required')
    from tools.soak_server import arguments
    args=arguments(['--assets',str(assets),'--output',str(output/'soak'),'--seconds',str(seconds),'--rooms',str(rooms),'--match-frames',str(frames),'--minimum-rounds',str(rounds),'--rc-tls'])
    output.mkdir(exist_ok=False);owner=None;started=time.monotonic();report=dict(passed=False,forced_cleanup=False,graphical_qualified=False,Internet_qualified=False,SCM_qualified=False)
    try:
        verify(package,'server');driver=ROOT/'tools/soak_server.py'
        report.update(driver_sha256=sha(driver),controller_sha256=sha(Path(__file__)),package_manifest_sha256=sha(package/'package-manifest.json'))
        request=dict(package=str(package),assets=str(assets),seconds=seconds,frames=frames,rounds=rounds,rooms=rooms)
        (output/'request.json').write_text(json.dumps(request,indent=2)+'\n')
        command=[str(package/'program/runtime/python.exe'),'-I','-B',str(driver),'--assets',str(assets),'--output',str(output/'soak'),'--seconds',str(seconds),'--rooms',str(rooms),'--match-frames',str(frames),'--minimum-rounds',str(rounds),'--rc-tls']
        owner=SuspendedChild.create(command,cwd=output,creationflags=subprocess.CREATE_NO_WINDOW);owner.resume()
        limit=max(seconds,rounds*(frames+60)*.05)+frames*.1+240
        while owner.poll() is None:
            if time.monotonic()-started>limit:raise TimeoutError('owned soak controller deadline')
            time.sleep(.05)
        report['exit_code']=owner.returncode
        report['soak']=json.loads((output/'soak/verification.json').read_bytes())
        report['job_final']=job_accounting(owner.job);deadline=time.monotonic()+5
        while report['job_final']['active_processes'] and time.monotonic()<deadline:time.sleep(.02);report['job_final']=job_accounting(owner.job)
        verify(package,'server')
        report['passed']=owner.returncode==0 and report['soak']['passed'] is True and report['job_final']['active_processes']==report['job_final']['total_terminated_processes']==0 and sha(driver)==report['driver_sha256'] and sha(Path(__file__))==report['controller_sha256']
    except BaseException as error:report['error']=repr(error)
    finally:
        if owner:owner.close();report['launch']=owner.receipt;report['forced_cleanup']=owner.receipt['forced_cleanup']
        report['passed'] &= not report['forced_cleanup'];report['elapsed_seconds']=time.monotonic()-started
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({key:report[key] for key in ('passed','exit_code','elapsed_seconds','forced_cleanup','error') if key in report}))
    return 0 if report['passed'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','assets','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=120);parser.add_argument('--frames',type=int,default=600);parser.add_argument('--rounds',type=int,default=4)
    parser.add_argument('--rooms',type=int,default=2,help='concurrent rooms2..4; default2 retains the original workload')
    args=parser.parse_args();raise SystemExit(run(args.package,args.assets,args.output,seconds=args.seconds,frames=args.frames,rounds=args.rounds,rooms=args.rooms))
