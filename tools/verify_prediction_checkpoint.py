"""Owned headless checkpoint experiment; never imported by launchers.

This experiment is deliberately separate from the authoritative worker and
normal client. A native crash/hang stays within an owned child process/job.
It does not qualify Unity integration or prove coverage of arbitrary native
FLS, pre-load allocations and operating-system state.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    paths = ('tools/verify_prediction_checkpoint.py','tools/prediction_native.py',
             'tools/owned_native_context.py','tools/verify_movement_prediction.py',
             'server/native_simulation.py','server/game_data.py',
             'client_patch/checkpoint/arena.cpp','client_patch/checkpoint/build.ps1',
             'client_patch/checkpoint/page_checkpoint.hpp',
             'tools/prepare_prediction_native.py','client_patch/checkpoint/cooperative.cpp',
             'client_patch/checkpoint/build-cooperative.ps1','tools/verify_prediction_combat_fixture.py')
    return {name:digest(ROOT/name) for name in paths}


class Stats(C.Structure):
    _fields_ = [(key, C.c_uint64) for key in (
        'version', 'error', 'allocations', 'frees', 'reallocations', 'unknown',
        'foreign_threads', 'high', 'live', 'live_bytes', 'captures', 'restores', 'committed',
        'capture_bytes','restore_bytes','capture_micros','restore_micros','saved_bytes')]


class Unknown(C.Structure):
    _fields_ = [(key, C.c_uint64) for key in ('operation','pointer','size','caller','heap')]


class Arena:
    def __init__(self, helper):
        helper = Path(helper).resolve()
        helper.relative_to(ROOT/'local')
        receipt = json.loads(helper.with_name('build.json').read_text(encoding='utf-8-sig'))
        if (receipt['dll_sha256'] != digest(helper) or
                receipt['source_sha256'] != digest(ROOT/'client_patch/checkpoint/arena.cpp') or
                receipt['page_source_sha256'] != digest(ROOT/'client_patch/checkpoint/page_checkpoint.hpp')):
            raise RuntimeError('arena helper/source build receipt mismatch')
        self.dll = C.CDLL(str(helper))
        signatures = {'BAInitialize': ([],C.c_int),'BAInstall': ([C.c_void_p], C.c_int),
                      'BACapture': ([], C.c_uint64),
                      'BARestore': ([C.c_uint64], C.c_int),
                      'BADrop': ([C.c_uint64], C.c_int),
                      'BASeal': ([], C.c_int),
                      'BAGetUnknown': ([C.POINTER(Unknown),C.c_uint32], C.c_int),
                      'BAGetStats': ([C.POINTER(Stats), C.c_uint32], C.c_int)}
        for name, (args, result) in signatures.items():
            function = getattr(self.dll, name)
            function.argtypes, function.restype = args, result
        result = self.dll.BAInitialize()
        if result:
            raise RuntimeError(f'BAInitialize rejected: {result}')

    def install(self, native):
        result = self.dll.BAInstall(native._handle)
        if result:
            raise RuntimeError(f'BAInstall rejected: {result}, {self.stats()}')

    def startup(self):
        before = self.stats()
        count = before['unknown']
        rows = (Unknown*count)()
        if self.dll.BAGetUnknown(rows,count) != count:
            raise RuntimeError('startup unknown allocation records unavailable')
        acknowledged = self.dll.BASeal()
        report = dict(before=before, acknowledged=acknowledged,
                      records=[{key:int(getattr(row,key)) for key,_ in Unknown._fields_} for row in rows])
        if acknowledged != count:
            raise RuntimeError(f'pre-hook ownership cannot be sealed: {report}')
        return report

    def stats(self):
        value = Stats()
        if self.dll.BAGetStats(C.byref(value), C.sizeof(value)):
            raise RuntimeError('BAGetStats failed')
        return {key: int(getattr(value, key)) for key, _ in Stats._fields_}

    def healthy(self):
        value = self.stats()
        if value['error'] or value['unknown'] or value['foreign_threads']:
            raise RuntimeError(f'unsafe allocator boundary: {value}')
        return value

    def capture(self):
        self.healthy()
        handle = self.dll.BACapture()
        if not handle:
            raise RuntimeError(f'checkpoint refused: {self.stats()}')
        return handle

    def restore(self, handle):
        self.healthy()
        result = self.dll.BARestore(handle)
        if result:
            raise RuntimeError(f'restore refused: {result}, {self.stats()}')


def comparable(world):
    result = world.state(31, include_entities=True)
    result.pop('raw_sha256', None)
    return result


def choose_unit(state,crab):
    return min((entity for entity in state['entities'] if entity.get('army') == 0 and entity.get('type') == crab),
               key=lambda entity:entity['id'])


def journal(path):
    data = path.read_bytes()
    if len(data) > 64*1024*1024: raise ValueError('baseline journal exceeds64MiB')
    result,offset = [],0
    while offset < len(data):
        if offset+4 > len(data): raise ValueError('truncated journal length')
        size, = struct.unpack_from('<I',data,offset); offset += 4
        if not 0 < size <= 2*1024*1024 or offset+size > len(data): raise ValueError('invalid journal body')
        result.append(data[offset:offset+size]); offset += size
        if len(result) > 2400: raise ValueError('baseline journal too long')
    return result


def extra_observations(world):
    from tools.verify_prediction_combat_fixture import entity_states
    from tools.verify_movement_prediction import decode_cooldowns
    return dict(entity_states=entity_states(world.snapshot(31)),
                ability_charges={str(viewer):decode_cooldowns(world.snapshot(viewer)) for viewer in (0,1)})


def read_progress(path):
    """Use the last complete append record even while its successor is written."""
    data = path.read_bytes()
    if len(data) > 16*1024*1024: raise ValueError('progress journal exceeds16MiB')
    complete = data[:data.rfind(b'\n')+1].splitlines()
    if not complete: return None
    return json.loads(complete[-1])


def child(args):
    if sys.stdin.buffer.read(10) != b'OWNED_JOB\n':
        raise RuntimeError('parent ownership gate did not open')
    from tools.prediction_native import prepare_serial, Cooperative, own_thread_ids
    from tools.verify_movement_prediction import (
        fixture, canonical_frame, opening_actions, selected_unit, targets, move_action)
    from server import native_simulation
    from tools.prepare_prediction_native import prepare_native
    from server.simulation_worker import isolate_protocol_stdout
    # Native stdout cannot pollute a JSON receipt. Raw stderr stays private.
    protocol = isolate_protocol_stdout()
    report = {'status': 'FAILED', 'pid': os.getpid(), 'experimental': True,
              'helper_sha256': digest(args.helper), 'source_sha256': digest(__file__),
              'cases': []}
    world = None
    arena = None
    cooperative = None
    progress_stream = None
    output = Path(args.output)
    output.resolve().relative_to(ROOT/'local')
    if not output.is_dir():
        raise ValueError('existing owned evidence directory required')
    try:
        assets = Path(args.assets).resolve()
        template, match, crab = fixture(assets)
        arena = Arena(args.helper)
        derived = output / 'Simulation.dll'
        report['derivation'] = prepare_native(assets/'Simulation.dll',derived)
        # This private child accepts only its explicitly derived image. Neither
        # the normal worker source nor the supported installed DLL is changed.
        native_simulation.SUPPORTED_DLL_SHA256 = digest(derived)
        native = prepare_serial(derived)
        if args.cooperative:
            cooperative = Cooperative(args.cooperative,native)
            if cooperative.provenance['source_sha256'] != digest(ROOT/'client_patch/checkpoint/cooperative.cpp'):
                raise RuntimeError('cooperative helper source receipt differs')
            report['cooperative_helper'] = cooperative.provenance
        arena.install(native)
        world = native_simulation.NativeSimulation(match.raw_game_data, derived)
        report['startup'] = arena.startup()
        report['after_create'] = arena.healthy()
        report['world_threads'] = own_thread_ids()
        if args.startup_only:
            world.close(); world = None
            report['after_close'] = arena.healthy()
            report['status'] = 'PASS'
            report['scope'] = 'startup/teardown only; no steps or checkpoint'
            return 0
        original_call = world._runtime.call
        kernel = C.WinDLL('kernel32')
        kernel.GetCurrentThreadId.restype = C.c_uint32
        thread_id = kernel.GetCurrentThreadId()
        trace_enabled = True
        progress_stream = (output/'progress.jsonl').open('ab',buffering=0)
        def traced_call(name, *arguments):
            if trace_enabled:
                record = json.dumps(dict(
                    pid=os.getpid(), thread_id=thread_id, module_base=native._handle,
                    next_frame=world.frame+1, operation=name)).encode()+b'\n'
                if progress_stream.write(record) != len(record):
                    raise OSError('partial progress journal write')
            return original_call(name, *arguments)
        world._runtime.call = traced_call
        authority = []
        expected = []
        captures = {}
        checkpoints = set(args.histories)
        baseline_states = None
        baseline_rows = None
        combat = False
        if args.baseline:
            baseline = Path(args.baseline).resolve()
            baseline.relative_to(ROOT/'local')
            reference = json.loads((baseline/'baseline/report.json').read_text())
            ordinary = reference.get('mode') == 'baseline' and not reference['preparation']['serial_pool']
            combat = reference.get('simulation_sha256') == report['derivation']['original_sha256'] and len(reference.get('added_world_thread_ids',[])) == 3
            if not reference['passed'] or not (ordinary or combat):
                raise ValueError('baseline must be the passed unmodified threaded control')
            if (baseline/'shared/bootstrap.pb').read_bytes() != match.raw_game_data:
                raise ValueError('baseline bootstrap differs')
            authority = journal(baseline/'shared/canonical-frames.bin')
            if digest(baseline/'shared/canonical-frames.bin') != reference['canonical_journal_sha256']:
                raise ValueError('baseline journal digest differs')
            baseline_rows = [json.loads(line) for line in (baseline/'baseline/states.jsonl').read_text().splitlines()]
            baseline_states = [row['state'] for row in baseline_rows]
            if len(baseline_states) != len(authority) or max(checkpoints)+args.ahead+args.continuation > len(authority):
                raise ValueError('baseline does not cover correction tails')
            report['unmodified_control'] = dict(report_sha256=digest(baseline/'baseline/report.json'),
                journal_sha256=digest(baseline/'shared/canonical-frames.bin'), frames=len(authority))
        count = len(authority) if baseline_states else max(checkpoints)+args.ahead+args.continuation
        for frame in range(count):
            before = comparable(world) if frame else None
            if frame in checkpoints:
                started = time.perf_counter()
                handle = arena.capture()
                captures[frame] = (handle, world.frame, world.game_time_seconds)
                report['cases'].append({'history': frame, 'capture_ms': (time.perf_counter()-started)*1000,
                                        'stats': arena.healthy(), 'handle': handle})
            if baseline_states:
                raw = authority[frame]
            else:
                actions = opening_actions(template, match, frame, before)
                if frame >= 240 and frame % 80 == 0:
                    unit = choose_unit(before, crab)
                    actions[0] = [move_action(unit, targets(unit)[frame//80 % 2])]
                raw = canonical_frame(template, match, frame, actions, before)
                authority.append(raw)
            world.process_frame(raw, dt_ms=50)
            expected.append(comparable(world))
            if baseline_states and json.loads(json.dumps(expected[-1])) != baseline_states[frame]:
                (output/f'baseline-mismatch-{frame}.json').write_text(json.dumps(
                    dict(actual=expected[-1],expected=baseline_states[frame]),indent=2))
                raise AssertionError(f'early arena differs from unmodified control at frame {frame}')
            if combat:
                extra = json.loads(json.dumps(extra_observations(world)))
                if any(extra[key] != baseline_rows[frame][key] for key in extra):
                    raise AssertionError(f'combat state/charge observation differs at frame {frame}')
        report['original_continuation'] = arena.healthy()
        for case in report['cases']:
            start = case['history']
            handle, old_frame, old_time = captures[start]
            timings = []
            for repetition in range(3):
                begun = time.perf_counter()
                arena.restore(handle)
                world.frame, world.game_time_seconds = old_frame, old_time
                timings.append((time.perf_counter()-begun)*1000)
                # First fork genuinely moves in a different direction, forcing
                # different native path state before another restore.
                unit = choose_unit(comparable(world), crab)
                future = next(entity for entity in expected[start+args.ahead-1]['entities'] if entity['id'] == unit['id'])
                x,y,z = unit['position']; fx,_,fz = future['position']
                import math
                dx,dz = x-fx,z-fz; length = math.hypot(dx,dz)
                if length < .001: dx,dz,length = 1.,0.,1.
                different_target = [x+24*dx/length,y,z+24*dz/length]
                for frame in range(start, start + args.ahead):
                    before = comparable(world)
                    actions = {0:[move_action(unit, different_target)]} if frame == start else {}
                    raw = canonical_frame(template, match, frame, actions, before)
                    world.process_frame(raw, dt_ms=50)
                divergent = comparable(world)
                if divergent == expected[start + args.ahead - 1]:
                    raise AssertionError('speculative branch did not diverge')
                begun = time.perf_counter()
                arena.restore(handle)
                world.frame, world.game_time_seconds = old_frame, old_time
                restored = time.perf_counter()
                trace_enabled = not args.minimal_replay
                # Replay only the bounded speculative tail; the old prefix is
                # restored from native storage, never re-simulated here.
                for frame in range(start, start + args.ahead + args.continuation):
                    world.process_frame(authority[frame], dt_ms=50)
                    if args.minimal_replay and frame < start+args.ahead-1:
                        continue
                    if frame == start+args.ahead-1:
                        case.setdefault('restore_native_tail_ms',[]).append((time.perf_counter()-begun)*1000)
                        trace_enabled = True
                    actual = comparable(world)
                    if actual != expected[frame]:
                        (output / f'mismatch-{start}-{repetition}-{frame}.json').write_text(
                            json.dumps(dict(actual=actual, expected=expected[frame]),indent=2))
                        raise AssertionError(f'restored continuation mismatch at frame {frame}')
                    if combat:
                        extra = json.loads(json.dumps(extra_observations(world)))
                        if any(extra[key] != baseline_rows[frame][key] for key in extra):
                            raise AssertionError(f'restored combat state/charge differs at frame {frame}')
                    if frame == start+args.ahead-1:
                        case.setdefault('correction_to_predicted_head_ms',[]).append((time.perf_counter()-begun)*1000)
                case.setdefault('repetitions', []).append({
                    'restore_ms': (restored-begun)*1000,
                    'restore_replay_observe_ms': (time.perf_counter()-begun)*1000,
                    'compared_frames': (1 if args.minimal_replay else args.ahead) + args.continuation,
                    'minimal_replay': args.minimal_replay,
                    'stats': arena.healthy()})
            case['initial_restore_ms'] = timings
        report['before_close'] = arena.healthy()
        if cooperative:
            report['cooperative_before_close'] = cooperative.stats()
            if not cooperative.healthy(): raise AssertionError('cooperative scheduler failed')
        world.close(); world = None
        report['after_close'] = arena.healthy()
        if cooperative:
            if not cooperative.healthy(): raise AssertionError('cooperative scheduler cleanup failed')
            cooperative.close()
        report['status'] = 'PASS'
    except BaseException:
        report['error'] = traceback.format_exc()
    finally:
        (output / 'child.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if world:
            try:
                world.close()
                world = None
            except BaseException:
                report['close_error'] = traceback.format_exc()
        if arena:
            report['final_stats'] = arena.stats()
        if cooperative:
            report['cooperative_final_stats'] = cooperative.stats()
            if world is None:
                try: cooperative.close()
                except BaseException:
                    report['cooperative_close_error'] = traceback.format_exc()
                    report['status'] = 'FAILED'
        if progress_stream: progress_stream.close()
        (output / 'child.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        protocol.close()
    return 0 if report['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', required=True)
    parser.add_argument('--helper', required=True)
    parser.add_argument('--cooperative')
    parser.add_argument('--baseline')
    parser.add_argument('--minimal-replay',action='store_true',help='Replay the bounded tail without intermediate display/query I/O, then compare its head and continuation')
    parser.add_argument('--output', required=True)
    parser.add_argument('--histories', type=int, nargs='+', default=[240,600])
    parser.add_argument('--ahead', type=int, default=8)
    parser.add_argument('--continuation', type=int, default=30)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--startup-only', action='store_true', help='Only qualify startup allocator ownership and cleanup')
    args = parser.parse_args()
    if not args.startup_only and not args.cooperative:
        parser.error('full proof requires the source-bound cooperative helper')
    if not (1 <= args.ahead <= 12 and 1 <= args.continuation <= 120 and
            1 <= len(args.histories) <= 4 and all(240 <= value <= 1200 for value in args.histories)):
        parser.error('bounded histories240..1200, ahead1..12 and continuation1..120 required')
    if args.child:
        return child(args)
    output = Path(args.output).resolve()
    output.relative_to(ROOT / 'local')
    output.mkdir(parents=True, exist_ok=False)
    from server.worker_client import _WindowsJob
    command = [sys.executable,'-I','-S','-B','-u','-c',
        "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.verify_prediction_checkpoint',run_name='__main__')",
        str(ROOT),'--child','--assets',str(Path(args.assets).resolve()),'--helper',str(Path(args.helper).resolve()),
        '--output',str(output),'--histories',*map(str,args.histories),'--ahead',str(args.ahead),
        '--continuation',str(args.continuation)]
    if args.startup_only:
        command.append('--startup-only')
    if args.cooperative:
        command.extend(('--cooperative',str(Path(args.cooperative).resolve())))
    if args.baseline:
        command.extend(('--baseline',str(Path(args.baseline).resolve())))
    if args.minimal_replay:
        command.append('--minimal-replay')
    before_sources = sources()
    report = {'status':'FAILED','command':command,'forced':False,'source_sha256':before_sources}
    with (output/'stdout.txt').open('wb') as stdout, (output/'stderr.txt').open('wb') as stderr:
        process = subprocess.Popen(command,cwd=output,stdout=stdout,stderr=stderr,
            stdin=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW,close_fds=True)
        report['pid'] = process.pid
        job = None
        try:
            job = _WindowsJob(process.pid)
            process.stdin.write(b'OWNED_JOB\n'); process.stdin.flush(); process.stdin.close()
            try:
                report['exit_code'] = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                from tools.owned_native_context import capture_native_context
                try:
                    progress = read_progress(output/'progress.jsonl')
                    if progress and time.time()-(output/'progress.jsonl').stat().st_mtime > 2:
                        context = capture_native_context(process,job,progress['thread_id'],progress['module_base'])
                        (output/'hang-context.json').write_text(json.dumps(context,indent=2),encoding='utf-8')
                except (OSError,ValueError,RuntimeError) as error:
                    report['diagnostic_error'] = str(error)
                report['exit_code'] = process.wait(timeout=35)
            child_report = json.loads((output/'child.json').read_text(encoding='utf-8'))
            report['status'] = 'PASS' if process.returncode == 0 and child_report['status'] == 'PASS' else 'FAILED'
        except BaseException:
            report['error'] = traceback.format_exc()
        finally:
            if process.poll() is None:
                report['forced'] = True
                if job: job.close()
                else: process.kill()
                process.wait(timeout=5)
            if job: job.close()
            if process.stdin and not process.stdin.closed: process.stdin.close()
            report['reaped'] = process.poll() is not None
            report['exit_code'] = process.returncode
    report['source_sha256_at_finish'] = sources()
    if report['source_sha256_at_finish'] != before_sources:
        report['status'] = 'FAILED'
        report['source_drift'] = True
    (output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({key:report[key] for key in ('status','pid','exit_code','reaped','forced','source_drift','error') if key in report}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
