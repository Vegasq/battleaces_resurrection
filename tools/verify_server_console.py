"""Actual packaged Start Server.exe, private console Ctrl+C and natural cleanup.

Default TLS mode requires the normal Windows owner; restricted-token preflight
never creates protected storage. Explicit development loopback is a separate
console-control qualification, never private/TLS/auth/SCM/active-match proof.
No game launches or production module/permission substitutions.
"""
from __future__ import annotations
import argparse
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def require(value,message):
    if not value:raise AssertionError(message)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owned_job_processes(handle):
    """Only PIDs currently returned by this owned job, never a system inventory."""
    from ctypes import wintypes as w
    class Ids(c.Structure):
        _fields_=[('assigned',w.DWORD),('count',w.DWORD),('ids',c.c_size_t*128)]
    kernel=c.WinDLL('kernel32',use_last_error=True)
    kernel.QueryInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]
    value=Ids();length=w.DWORD()
    require(kernel.QueryInformationJobObject(handle,3,c.byref(value),c.sizeof(value),c.byref(length)) and
            value.count<=128,'owned job PID query failed')
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];kernel.WaitForSingleObject.restype=w.DWORD
    kernel.CloseHandle.argtypes=[w.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
    rows=[]
    for pid in list(value.ids)[:value.count]:
        row=dict(pid=pid);process=kernel.OpenProcess(0x1000|0x100000,False,pid)
        if not process:row['query_error']=c.get_last_error()
        else:
            try:
                row['signaled']=kernel.WaitForSingleObject(process,0)==0
                path=c.create_unicode_buffer(32768);size=w.DWORD(len(path))
                if kernel.QueryFullProcessImageNameW(process,0,path,c.byref(size)):row['image']=Path(path.value).name
            finally:kernel.CloseHandle(process)
        rows.append(row)
    return rows


def settle_job(handle,*,query,inspect=owned_job_processes,clock=time.monotonic,sleep=time.sleep,timeout=5):
    """Observe natural job drain before closing it; never force a passing result."""
    require(0<timeout<=5,'bounded job settle interval required')
    started=clock();deadline=started+timeout;samples=[]
    while True:
        accounting=query(handle);observed=clock()
        sample=dict(seconds=observed-started,**accounting)
        if accounting['active_processes']:sample['processes']=inspect(handle)
        samples.append(sample)
        if (not accounting['active_processes'] or accounting['total_terminated_processes'] or clock()>=deadline):break
        sleep(min(.05,max(0,deadline-clock())))
    return dict(final=accounting,samples=samples,elapsed_seconds=clock()-started,
                naturally_empty=not accounting['active_processes'] and not accounting['total_terminated_processes'] and observed<deadline)


def console_ids(kernel):
    values=(c.c_uint*32)();kernel.GetConsoleProcessList.argtypes=[c.POINTER(c.c_uint),c.c_uint]
    count=kernel.GetConsoleProcessList(values,32)
    require(0<count<=32,'owned console enumeration failed');return list(values)[:count]


def child(request_path):
    # Runs under the actual bundled runtime. Its _.pth selects production imports;
    # this external script never inserts checkout code into that runtime's path.
    from tools.package_integrity import verify
    from server.state_lock import exclusive_state
    request=json.loads(Path(request_path).read_bytes());package=Path(request['package']);output=Path(request['output'])
    require(all(p.resolve().is_relative_to(ROOT/'local') for p in (package,output)), 'owned paths required')
    require(Path(request_path).resolve()==output/'request.json','unexpected console request location')
    report=dict(passed=False,tls=request['tls'],forced_cleanup=False,additional_stdin=False)
    process=None;handler=None;started=time.monotonic()
    try:
        require(digest(__file__)==request['driver_sha256'],'console driver source changed')
        verify(package,'server')
        kernel=c.WinDLL('kernel32',use_last_error=True)
        require(kernel.GetConsoleCP()!=0 and console_ids(kernel)==[os.getpid()], 'controller needs its own otherwise empty console')
        received=[];HANDLER=c.WINFUNCTYPE(c.c_int,c.c_uint)
        handler=HANDLER(lambda event:(received.append(event) or 1) if event==0 else 0)
        kernel.SetConsoleCtrlHandler.argtypes=[HANDLER,c.c_int]
        require(kernel.SetConsoleCtrlHandler(handler,1),'controller handler unavailable')
        deadline=time.monotonic()+20
        while not (output/'job-ready').exists():
            require(time.monotonic()<deadline,'owned job gate missing');time.sleep(.02)
        require((output/'job-ready').read_bytes()==b'owned job attached\n','owned job gate differs')
        report['exit_controls']=[]
        for label,args,expected,marker in (
                ('help',['--help'],0,b'usage:'),
                ('missing-config',['--config',str(output/'config/does-not-exist.json')],1,b'Host configuration failed:'),
                ('invalid-option',['--authored-unsupported-option'],2,b'Invalid command or arguments; use --help.')):
            result=subprocess.run([str(package/'Start Server.exe'),*args],cwd=output/'foreign cwd',
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
            require(result.returncode==expected and marker in result.stdout+result.stderr,
                    'native launcher did not propagate actual packaged CLI result')
            report['exit_controls'].append(dict(case=label,exit_code=result.returncode,
                stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),stderr_sha256=hashlib.sha256(result.stderr).hexdigest()))
        require(console_ids(kernel)==[os.getpid()],'CLI controls left a console process')
        command=[str(package/'Start Server.exe'),'--config',str(output/'config/host.json')]
        with (output/'host-stdout.txt').open('xb') as stdout,(output/'host-stderr.txt').open('xb') as stderr:
            process=subprocess.Popen(command,cwd=output/'foreign cwd',stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
            report.update(launcher_pid=process.pid,command=command,entry_sha256=digest(package/'Start Server.exe'))
            deadline=time.monotonic()+60
            while True:
                raw=(output/'host-stdout.txt').read_bytes();require(len(raw)<=1024*1024,'host output exceeded budget')
                if b'Ctrl+C stops it cleanly.' in raw:break
                require(process.poll() is None and time.monotonic()<deadline,'host readiness failed');time.sleep(.05)
            healths=[json.loads(line) for line in raw.decode('utf-8-sig').splitlines() if line.startswith('{')]
            require(len(healths)==1,'host health count differs');health=healths[0];native=health['native']
            require(health['passed'] and health['tls'] is request['tls'] and health['credential_store_checked'] is request['tls'] and
                health['pointer_bits']==64 and native['created'] and native['stepped_frame']==0 and native['exit_code']==0 and native['reaped'],
                'actual host/native health differs')
            report['health']=health
            ids=console_ids(kernel)
            require(len(ids)==3 and os.getpid() in ids and process.pid in ids,'private console audience differs')
            report['console_pids']=ids
            if request['tls']:
                from server.tls_transport import load_client_context
                context=load_client_context(request['ca'],'localhost')
                with socket.create_connection(('127.0.0.1',request['port']),timeout=5) as plain:
                    with context.context.wrap_socket(plain,server_hostname='localhost') as secure:
                        require(secure.getpeercert() and secure.version() in ('TLSv1.2','TLSv1.3'),'verified TLS handshake absent')
                        report['tls_handshake']=dict(verified=True,version=secure.version(),peer_sha256=hashlib.sha256(secure.getpeercert(binary_form=True)).hexdigest())
            kernel.GenerateConsoleCtrlEvent.argtypes=[c.c_uint,c.c_uint]
            stop=time.monotonic();require(kernel.GenerateConsoleCtrlEvent(0,0),'owned Ctrl+C event failed')
            report['ctrl_c_sent']=True
            process.wait(timeout=15)
            report.update(exit_code=process.returncode,controller_events=received,stop_seconds=time.monotonic()-stop)
            require(process.returncode==0 and received==[0],'natural Ctrl+C/launcher exit differs')
        require(not (output/'host-stderr.txt').read_bytes(),'host wrote unexpected stderr')
        require(b'Terminate batch job' not in (output/'host-stdout.txt').read_bytes(),'batch confirmation unexpectedly requested')
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            probe.bind(('127.0.0.1',request['port']))
        with exclusive_state(Path(request['data'])):pass
        report.update(listener_port_released=True,state_lock_released=True,passed=True)
    except BaseException as error:report.update(error_type=type(error).__name__)
    finally:
        if process is not None and process.poll() is None:
            report['forced_cleanup']=True;process.terminate();process.wait(timeout=10)
        report.update(elapsed_seconds=time.monotonic()-started,driver_source_unchanged=digest(__file__)==request['driver_sha256'])
        report['passed'] &= report['driver_source_unchanged'] and not report['forced_cleanup']
        (output/'console-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 1


def run(package,assets,output,*,development_loopback=False,preflight_only=False):
    from tools.package_integrity import verify
    from tools.build_windows_packages import SERVER,LAUNCHER_SOURCES
    from server.assets import verify_assets
    from tools.verify_owner_credentials import restricting_sids_present
    from server.worker_client import _WindowsJob
    from tools.verify_packaged_play import job_accounting
    from tests.test_tls_transport import generate_test_pki,remove_test_pki
    package,assets,output=(Path(p).resolve() for p in (package,assets,output))
    require(os.name=='nt' and all(p.is_relative_to(ROOT/'local') for p in (package,assets,output)), 'owned ignored Windows paths required')
    require(not output.is_relative_to(package) and not output.is_relative_to(assets),'separate acceptance output required')
    output.mkdir(parents=True,exist_ok=False)
    report=dict(passed=False,scope=__doc__,development_loopback=development_loopback,preflight_only=preflight_only,
                protected_operations_attempted=False,controller_started=False,forced_cleanup=False)
    process=job=None;started=time.monotonic();pki=None
    try:
        inventory=verify(package,'server');asset_manifest=verify_assets(assets)
        report['production_sources']={name:digest(ROOT/name) for name in SERVER if name.endswith('.py')}
        require(all(inventory['files']['program/app/'+name]['sha256']==value for name,value in report['production_sources'].items()),
                'package production modules differ from current source')
        report['launcher_sources']={name:digest(ROOT/name) for name in LAUNCHER_SOURCES}
        receipt=json.loads((package/'program/launcher/launcher-build.json').read_bytes())
        require(receipt['source_sha256']==report['launcher_sources'] and receipt['argument_tests_passed'] is True and
                receipt['launcher_sha256']==digest(package/'Start Server.exe'),'launcher source/build receipt differs')
        report.update(package_manifest_sha256=digest(package/'package-manifest.json'),
                      asset_manifest_sha256=digest(assets/'asset-manifest.json'),driver_sha256=digest(__file__))
        if not development_loopback:
            report['restricting_sids_present']=restricting_sids_present()
            if report['restricting_sids_present'] or preflight_only:
                report['stage']='normal_owner_required' if report['restricting_sids_present'] else 'preflight_ready'
                return 2 if report['restricting_sids_present'] else 0
        elif preflight_only:
            report.update(stage='development_preflight_ready',preflight_ready=True);return 0
        report['stage']='console_start'
        (output/'config').mkdir();(output/'foreign cwd').mkdir()
        for name in ('server.py','sitecustomize.py'):(output/'foreign cwd'/name).write_text('raise RuntimeError("foreign import")\n')
        config=json.loads((ROOT/'server/host-config.example.json').read_bytes())
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        config.update(listen_host='127.0.0.1',listen_port=port,assets_directory=str(assets),data_directory=str(output/'data'),
                      certificate_file=None,private_key_file=None,credential_directory=None,allow_insecure_loopback=development_loopback)
        if not development_loopback:
            report['protected_operations_attempted']=True
            pki=generate_test_pki(output/'pki')
            config.update(certificate_file=str(pki['cert']),private_key_file=str(pki['key']),
                          credential_directory=str(output/'data/private/credentials'))
        (output/'config/host.json').write_text(json.dumps(config,indent=2)+'\n')
        request=dict(package=str(package),output=str(output),tls=not development_loopback,port=port,data=str(output/'data'),
                     ca=str(pki['ca']) if pki else None,driver_sha256=report['driver_sha256'])
        request_path=output/'request.json';request_path.write_text(json.dumps(request)+'\n')
        report['input_sha256']={name:digest(output/name) for name in ('request.json','config/host.json')}
        info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
        environment=os.environ.copy();environment['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
        process=subprocess.Popen([str(package/'program/runtime/python.exe'),'-I','-B',str(Path(__file__).resolve()),'--child-request',str(request_path)],
            cwd=output/'foreign cwd',env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_CONSOLE,startupinfo=info)
        report.update(controller_started=True,controller_pid=process.pid)
        job=_WindowsJob(process.pid);(output/'job-ready').write_bytes(b'owned job attached\n')
        report['controller_exit_code']=process.wait(timeout=100)
        report['job_settle']=settle_job(job.handle,query=job_accounting)
        report['job']=report['job_settle']['final']
        report['console']=json.loads((output/'console-report.json').read_bytes())
        require(process.returncode==0 and report['console']['passed'] and report['job_settle']['naturally_empty'] and report['job']['active_processes']==0 and
                report['job']['total_terminated_processes']==0,'console/owned descendant qualification failed')
        require(verify_assets(assets)==asset_manifest,'assets changed')
        verify(package,'server')
        report.update(stage='complete',passed=True)
    except BaseException as error:report.update(error_type=type(error).__name__)
    finally:
        if process is not None and process.poll() is None:
            report['forced_cleanup']=True;process.terminate();process.wait(timeout=10)
        if job is not None:
            try:
                report['job_before_close']=job_accounting(job.handle)
                if report['job_before_close']['active_processes']:report.update(forced_cleanup=True,passed=False)
                if report['job_before_close']['total_terminated_processes']:report['passed']=False
            finally:job.close()
        if (output/'pki').exists():
            try:remove_test_pki(output/'pki');report['authored_test_pki_removed']=True
            except OSError:report.update(authored_test_pki_removed=False,passed=False)
        report['driver_source_unchanged']=report.get('driver_sha256')==digest(__file__)
        report['launcher_source_unchanged']=report.get('launcher_sources')=={name:digest(ROOT/name) for name in LAUNCHER_SOURCES}
        report['production_source_unchanged']=report.get('production_sources')=={name:digest(ROOT/name) for name in SERVER if name.endswith('.py')}
        if 'input_sha256' in report:
            report['inputs_unchanged']=report['input_sha256']=={name:digest(output/name) for name in report['input_sha256']}
            report['passed'] &= report['inputs_unchanged']
        report['passed'] &= all(report[k] for k in ('driver_source_unchanged','launcher_source_unchanged','production_source_unchanged')) and not report['forced_cleanup']
        report['elapsed_seconds']=time.monotonic()-started
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ('passed','stage','development_loopback','controller_started','forced_cleanup','elapsed_seconds') if k in report}))
    return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child-request',type=Path,help=argparse.SUPPRESS)
    for name in ('package','assets','output'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--development-loopback',action='store_true',help='separate explicit non-TLS console control')
    parser.add_argument('--preflight-only',action='store_true')
    args=parser.parse_args()
    if args.child_request:return child(args.child_request)
    require(all((args.package,args.assets,args.output)),'package/assets/output required')
    return run(args.package,args.assets,args.output,development_loopback=args.development_loopback,preflight_only=args.preflight_only)


if __name__=='__main__':raise SystemExit(main())
