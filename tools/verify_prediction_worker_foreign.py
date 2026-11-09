"""Bounded owned headless diagnostic for late foreign-thread heap failures.

Default/--prepare-only performs file checks only. --run-prepared explicitly
starts one suspended, Job-owned child. The child uses the product NativeSession
setup and polls a quiet world for35s, without simulation steps or Python threads.
A reproduced strict guard failure is diagnostic evidence, not a healthy PASS.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCES = (
    'tools/verify_prediction_worker_foreign.py', 'tools/verify_prediction_client_worker.py',
    'client_patch/prediction_worker/native.py', 'client_patch/prediction_worker/wire.py',
    'tools/prediction_native.py', 'tools/prepare_prediction_native.py',
    'tools/prediction_crt_attach.py',
    'client_patch/checkpoint/thread_state.hpp',
    'client_patch/prediction_worker/checkpoint.py', 'client_patch/prediction_worker/prediction.py',
    'client_patch/prediction_worker/presentation.py',
    'client_patch/checkpoint/arena.cpp', 'client_patch/checkpoint/build.ps1',
    'client_patch/checkpoint/page_checkpoint.hpp', 'client_patch/checkpoint/cooperative.cpp',
    'server/native_simulation.py', 'server/worker_client.py',
)
CRT_RANGES = {
    'CRT thread detach dispatch': (0x3403d4, 0x3403e9),
    'VCR thread detach': (0x3437a0, 0x3437b2),
    'VCR PTD cleanup': (0x343800, 0x34384d),
    'UCRT thread detach': (0x362a6c, 0x362a7c),
    'UCRT PTD cleanup': (0x3630e4, 0x363125),
    'VCR FLS destructor': (0x3437e0, 0x343800),
    'UCRT FLS destructor': (0x362f64, 0x362f84),
}


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    return {name:sha(ROOT / name) for name in SOURCES}


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def classify_events(diagnostic):
    events = diagnostic['events']
    require(type(events) is list and len(events) <= 8, 'foreign events exceed ABI cap')
    result = []
    for event in events:
        require(event['version'] == 1 and 0 <= event['frame_count'] <= 16 and
                len(event['frames']) == event['frame_count'] and event['thread_id'] > 0 and
                event['owner_thread_id'] > 0 and event['thread_id'] != event['owner_thread_id'],
                'foreign event ABI/thread/frame identity differs')
        native = [frame['rva'] for frame in event['frames']
                  if frame.get('module') and Path(frame['module']).name.lower() == 'simulation.dll']
        matches = sorted(name for name,(start,end) in CRT_RANGES.items()
                         if any(start <= rva < end for rva in native))
        result.append(dict(operation=event['operation'], thread_id=event['thread_id'],
                           owner_thread_id=event['owner_thread_id'], pointer=event['pointer'],
                           size=event['size'], native_frame_rvas=native, original_CRT_frame_matches=matches))
    return result


def prepare(args):
    from client_patch.prediction_worker.native import helper_receipt
    from tools.prepare_prediction_native import SUPPORTED_ORIGINAL_SHA256
    output = args.output.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT / 'local') and not os.path.lexists(args.output),
            'fresh ignored Windows diagnostic output required')
    require(30 <= args.idle_seconds <= 35 and 45 <= args.timeout <= 50,
            'idle30..35s and total45..50s bounds required')
    original = args.original_dll.resolve(strict=True)
    require(sha(original) == SUPPORTED_ORIGINAL_SHA256, 'exact original native DLL required')
    bootstrap = args.bootstrap.resolve(strict=True)
    require(0 < bootstrap.stat().st_size <= 32 * 1024 * 1024, 'bounded retained bootstrap required')
    reference = bootstrap.parent.parent / 'baseline/report.json'
    baseline = json.loads(reference.read_text())
    require(baseline['passed'] and baseline['frame_count'] == 1200, 'retained combat01 bootstrap provenance required')
    artifacts = dict(original_dll=dict(path=str(original),sha256=sha(original)),
                     python=dict(path=str(args.python.resolve(strict=True)),sha256=sha(args.python)),
                     bootstrap=dict(path=str(bootstrap),sha256=sha(bootstrap),reference=str(reference),reference_sha256=sha(reference)))
    for name in ('heap_helper','cooperative'):
        path, receipt = helper_receipt(getattr(args,name), arena=name == 'heap_helper')
        if name == 'heap_helper':
            require(receipt.get('foreign_event_abi') == 1 and receipt.get('foreign_event_bytes') == 472 and
                    receipt.get('foreign_event_capacity') == 8 and receipt.get('foreign_event_frames') == 16,
                    'arena08 foreign diagnostic ABI required')
        artifacts[name] = dict(path=str(path),sha256=sha(path),receipt=receipt,receipt_sha256=sha(path.with_name('build.json')))
    output.mkdir(parents=True)
    (output / 'bootstrap.pb').write_bytes(bootstrap.read_bytes())
    child = output / 'child';child.mkdir()
    bootstrap_code = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.verify_prediction_worker_foreign',run_name='__main__')"
    command = [artifacts['python']['path'],'-I','-S','-B','-u','-c',bootstrap_code,str(ROOT),
               '--child','--output',str(output)]
    invocation = dict(scope=__doc__,command=command,source_sha256=sources(),artifacts=artifacts,
                      idle_seconds=args.idle_seconds,timeout=args.timeout,output=str(output),
                      child=str(child),bootstrap_copy_sha256=sha(output / 'bootstrap.pb'),
                      native_executed=False)
    write(output / 'invocation.json',invocation)
    return invocation


def raw_stats(arena):
    from client_patch.prediction_worker.native import ArenaStats
    value = ArenaStats()
    require(arena.dll.BAGetStats(C.byref(value),C.sizeof(value)) == 0,'owner stats read failed')
    return {name:int(getattr(value,name)) for name,_ in value._fields_}


def child(output):
    require(sys.stdin.buffer.read(10) == b'OWNED_JOB\n','owned parent gate did not open')
    invocation = json.loads((output / 'invocation.json').read_text())
    require(sources() == invocation['source_sha256'],'source changed before native child start')
    from client_patch.prediction_worker.native import NativeSession
    from client_patch.prediction_worker import wire as w
    from server.simulation_worker import isolate_protocol_stdout
    import threading
    isolate_protocol_stdout()
    started = time.monotonic()
    folder = Path(invocation['child'])
    report = dict(status='FAILED',scope=__doc__,pid=os.getpid(),no_steps=True,
                  python_threads_before=threading.active_count(),queries=0,
                  source_sha256_at_start=sources(),cleanup_error=None)
    session = None
    kernel = C.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentThreadId.argtypes,kernel.GetCurrentThreadId.restype=[],C.c_uint32
    report['native_owner_thread'] = int(kernel.GetCurrentThreadId())

    def command(op,body):
        return w.decode_request(w.Packet(op,1,body))

    try:
        artifacts=invocation['artifacts']
        session=NativeSession.open(original_dll=artifacts['original_dll']['path'],
            heap_helper=artifacts['heap_helper']['path'],cooperative=artifacts['cooperative']['path'],
            data_dir=folder / 'native-data')
        report['provenance']=session.provenance
        report['module_base']=session.native._handle
        report['after_load']=raw_stats(session.arena)
        for op,body in ((w.Op.SET_LOG_CALLBACK,b'\1'),(w.Op.SET_LOG_FLAGS,b'\0\0\0\0'),(w.Op.INIT,b'\0')):
            code,data=session.dispatch(command(op,body))
            require(code == 0 and not data,'native initialization operation failed')
        code,data=session.dispatch(command(w.Op.CREATE_WORLD,(output / 'bootstrap.pb').read_bytes()))
        require(code == 0 and len(data) == 8,'one native world was not created')
        created=time.monotonic()
        report['world_created_seconds']=created-started
        report['after_create']=raw_stats(session.arena)
        import struct
        world,=struct.unpack('<Q',data)
        deadline=created+invocation['idle_seconds']
        next_record=created
        while time.monotonic() < deadline:
            require(time.monotonic()-started < invocation['timeout']-6,'child owner deadline reached')
            try:
                code,count=session.dispatch(command(w.Op.SYSTEM_COUNT,struct.pack('<QI',world,0)))
                require(code == 0 and len(count) == 4,'safe native system-count query failed')
            except Exception as error:
                report['strict_error']=repr(error)
                report['failure_seconds_after_load']=time.monotonic()-started
                report['failure_seconds_after_world']=time.monotonic()-created
                report['failure_stats']=raw_stats(session.arena)
                require(report['failure_stats']['error'] == 1 and report['failure_stats']['foreign_threads'] > 0,
                        'different failure than foreign-thread guard')
                report['status']='REPRODUCED_FOREIGN_GUARD'
                break
            report['queries']+=1
            now=time.monotonic()
            if now >= next_record:
                write(folder / 'progress.json',dict(pid=os.getpid(),elapsed=now-started,world_elapsed=now-created,
                    queries=report['queries'],stats=raw_stats(session.arena),python_threads=threading.active_count()))
                next_record=now+1
            time.sleep(min(.05,max(0,deadline-time.monotonic())))
        else:
            report['status']='NO_REPRODUCTION'
            report['healthy_observation_seconds']=time.monotonic()-created
    except BaseException as error:
        report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        if session is not None:
            report['before_close']=raw_stats(session.arena)
            try:session.close()
            except Exception as error:report['cleanup_error']=repr(error)
            report['after_close']=raw_stats(session.arena)
            if (report['status'] == 'NO_REPRODUCTION' and report['after_close']['error'] == 1 and
                    report['after_close']['foreign_threads']):
                report['status']='REPRODUCED_DURING_CLOSE'
            elif report['status'] == 'NO_REPRODUCTION' and report['cleanup_error']:
                report['status']='FAILED'
            report['native_logs']=session.drain_logs()
            # JSON-safe bounded logs; native bytes never become process pointers.
            report['native_logs']=[dict(kind=kind,text=value.decode('utf-8')) for kind,value in report['native_logs']]
            path=Path(session.provenance['data_directory']) / 'native-foreign-events.json'
            if path.exists():
                require(path.stat().st_size <= 1024*1024,'foreign diagnostic exceeds bound')
                diagnostic=json.loads(path.read_text())
                report['foreign_diagnostic']=dict(path=str(path),sha256=sha(path),data=diagnostic,
                                                  classified=classify_events(diagnostic))
        report['python_threads_after']=threading.active_count()
        report['source_sha256_at_end']=sources()
        report['elapsed_seconds']=time.monotonic()-started
        report['diagnostic_completed']=report['status'] in (
            'REPRODUCED_FOREIGN_GUARD','REPRODUCED_DURING_CLOSE','NO_REPRODUCTION')
        report['healthy_runtime_pass']=False
        write(folder / 'report.json',report)
    return 0 if report['diagnostic_completed'] else 1


def run_prepared(output):
    from tools.verify_prediction_client_worker import RetainedJob,CREATE_SUSPENDED
    invocation=json.loads((output / 'invocation.json').read_text())
    require(sources() == invocation['source_sha256'],'source changed since diagnostic preparation')
    require(not (output / 'verification.json').exists(),'diagnostic output already completed')
    for info in invocation['artifacts'].values():
        require(sha(info['path']) == info['sha256'],'prepared binary/bootstrap changed')
    require(sha(output / 'bootstrap.pb') == invocation['bootstrap_copy_sha256'],'retained bootstrap changed')
    report=dict(passed=False,scope=__doc__,command=invocation['command'],forced_cleanup=False,
                source_sha256_at_start=sources(),invocation_sha256=sha(output / 'invocation.json'))
    process=job=None;started=time.monotonic()
    try:
        with (output / 'child-stdout.log').open('xb') as stdout,(output / 'child-stderr.log').open('xb') as stderr:
            process=subprocess.Popen(invocation['command'],cwd=invocation['child'],stdin=subprocess.PIPE,
                stdout=stdout,stderr=stderr,close_fds=True,
                creationflags=CREATE_SUSPENDED|subprocess.CREATE_NO_WINDOW)
            report['pid']=process.pid
            job=RetainedJob(process);report['assigned_before_resume']=True
            ntdll=C.WinDLL('ntdll',use_last_error=True)
            ntdll.NtResumeProcess.argtypes,ntdll.NtResumeProcess.restype=[C.c_void_p],C.c_long
            require(ntdll.NtResumeProcess(C.c_void_p(int(process._handle))) == 0,'owned retained child resume failed')
            process.stdin.write(b'OWNED_JOB\n');process.stdin.flush();process.stdin.close()
            write(output / 'process.json',report)
            # Reserve the last5s of the50s maximum for owned cleanup.
            report['exit_code']=process.wait(timeout=max(.1,invocation['timeout']-5-(time.monotonic()-started)))
            report['child']=json.loads((Path(invocation['child']) / 'report.json').read_text())
            require(report['exit_code'] == 0 and report['child']['diagnostic_completed'],'owned diagnostic child failed')
            require(report['child']['python_threads_before'] == report['child']['python_threads_after'] == 1,
                    'diagnostic introduced extra Python threads')
            if report['child']['status'].startswith('REPRODUCED'):
                require(report['child'].get('foreign_diagnostic',{}).get('data',{}).get('events'),
                        'foreign guard reproduced without stack evidence')
            report['passed']=True
    except BaseException as error:
        report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        if process is not None:
            if process.poll() is None:
                report['forced_cleanup']=True
                if job:job.terminate_owned()
                else:process.terminate()
            try:process.wait(timeout=5);report['reaped']=True
            except subprocess.TimeoutExpired:report['reaped']=False
            report['exit_code']=process.poll()
            if process.stdin and not process.stdin.closed:process.stdin.close()
        if job:
            report['job_before_close']=job.accounting()
            if report['job_before_close']['active']:report['forced_cleanup']=True
            job.close()
        if process is not None:
            process._handle.Close();report['retained_handle_closed']=True
        report['source_sha256_at_end']=sources()
        report['elapsed_seconds']=time.monotonic()-started
        report['passed']=bool(report['passed'] and not report['forced_cleanup'] and report.get('reaped') and
            report['source_sha256_at_start'] == report['source_sha256_at_end'] and
            report.get('job_before_close',{}).get('active') == 0 and
            report.get('job_before_close',{}).get('terminated') == 0)
        report['healthy_runtime_pass']=False
        write(output / 'verification.json',report)
    return report


def self_test():
    event=dict(version=1,operation=2,size=0,pointer=123,thread_id=9,owner_thread_id=8,frame_count=1,
               frames=[dict(module='Simulation.dll',rva=0x3403dd)])
    result=classify_events(dict(events=[event]))
    require(result[0]['original_CRT_frame_matches'] == ['CRT thread detach dispatch'],'CRT range classification failed')
    for bad in (dict(event,thread_id=8),dict(event,frame_count=17),dict(event,version=2)):
        try:classify_events(dict(events=[bad]))
        except AssertionError:continue
        raise AssertionError('malformed event accepted')
    return dict(passed=True,native_executed=False,cases=4)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path);parser.add_argument('--original-dll',type=Path)
    parser.add_argument('--heap-helper',type=Path);parser.add_argument('--cooperative',type=Path)
    parser.add_argument('--bootstrap',type=Path);parser.add_argument('--python',type=Path,default=Path(sys.executable))
    parser.add_argument('--idle-seconds',type=float,default=35);parser.add_argument('--timeout',type=float,default=50)
    parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--run-prepared',action='store_true')
    parser.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:print(json.dumps(self_test()));return 0
    if args.output is None:parser.error('--output required')
    output=args.output.resolve()
    if args.child:return child(output)
    if args.run_prepared:
        result=run_prepared(output)
        print(json.dumps({name:result.get(name) for name in ('passed','pid','exit_code','reaped','forced_cleanup','error')},indent=2))
        return 0 if result['passed'] else 1
    for name in ('original_dll','heap_helper','cooperative','bootstrap'):
        if getattr(args,name) is None:parser.error('--'+name.replace('_','-')+' required for preparation')
    result=prepare(args)
    print(json.dumps(dict(prepared=True,native_executed=False,output=str(output),command=result['command']),indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
