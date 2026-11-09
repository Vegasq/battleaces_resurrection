"""Source-bound actual local-worker parity through the owned C++ process channel.

Use --prepare-only, launch the printed driver argv with exec_command, then
--analyze-only for coordinated native slots. Default mode orchestrates that same
driver; the native Python host is always launched suspended/Job-owned by C++.
No Unity game, user client, live server or view-only movement is involved.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.native_simulation import SUPPORTED_DLL_SHA256, decode_snapshot
from tools.verify_movement_prediction import decode_cooldowns
from tools.verify_prediction_combat_fixture import entity_states

SOURCES = ('tools/prediction_worker_probe.cpp', 'tools/verify_prediction_worker.py',
    'client_patch/checkpoint/native_worker_wire.hpp', 'client_patch/checkpoint/native_worker_channel.hpp',
    'client_patch/checkpoint/native_rpc_backend.hpp', 'client_patch/checkpoint/native_api_proxy.hpp',
    'client_patch/checkpoint/arena.cpp', 'client_patch/checkpoint/page_checkpoint.hpp',
    'client_patch/checkpoint/cooperative.cpp', 'client_patch/prediction_worker/__init__.py',
    'client_patch/prediction_worker/__main__.py', 'client_patch/prediction_worker/wire.py',
    'client_patch/prediction_worker/native.py', 'tools/prepare_prediction_native.py',
    'tools/prediction_native.py', 'server/native_simulation.py', 'server/simulation_worker.py',
    'tools/prediction_crt_attach.py',
    'client_patch/checkpoint/thread_state.hpp',
    'client_patch/prediction_worker/checkpoint.py', 'client_patch/prediction_worker/prediction.py',
    'client_patch/prediction_worker/presentation.py',
    'server/worker_client.py', 'server/game_data.py', 'server/protobuf_wire.py',
    'tools/verify_movement_prediction.py', 'tools/verify_prediction_combat_fixture.py')
MAGIC = b'BASNP001'
MAX_SNAPSHOT = 16*1024*1024


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def normalized(value):
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def source_hashes():
    return {name: digest((ROOT/name).read_bytes()) for name in SOURCES}


def snapshot_records(stream, count):
    """BASNP001 then count LE{u32frame,u32length,raw}, exact EOF.

    Frame IDs must start0/contiguous, length8..16MiB. Separate filenames bind
    viewer31/0/1 and cycle. These are private raw native captures, never tracked.
    """
    require(stream.read(8) == MAGIC, 'snapshot stream magic/version differs')
    for frame in range(count):
        header = stream.read(8)
        require(len(header) == 8, 'truncated snapshot record header')
        number, length = struct.unpack('<II', header)
        require(number == frame and 8 <= length <= MAX_SNAPSHOT, 'snapshot frame/order/length outside bound')
        raw = stream.read(length)
        require(len(raw) == length, 'truncated snapshot payload')
        yield frame, raw
    require(stream.read(1) == b'', 'snapshot stream has trailing records/bytes')


def reader_self_test():
    valid = MAGIC+struct.pack('<II', 0, 8)+b'12345678'+struct.pack('<II', 1, 8)+b'abcdefgh'
    require(list(snapshot_records(io.BytesIO(valid), 2)) == [(0, b'12345678'), (1, b'abcdefgh')], 'valid snapshot reader failed')
    invalid = (b'', valid[:-1], b'BADMAGIC'+valid[8:], valid+b'x',
               MAGIC+struct.pack('<II', 1, 8)+b'12345678',
               MAGIC+struct.pack('<II', 0, 7)+b'1234567',
               MAGIC+struct.pack('<II', 0, MAX_SNAPSHOT+1))
    for value in invalid:
        rejected = False
        try:
            list(snapshot_records(io.BytesIO(value), 2 if value in (valid[:-1], valid+b'x') else 1))
        except AssertionError:
            rejected = True
        require(rejected, 'malformed snapshot stream accepted')
    return dict(passed=True, reader_cases=1+len(invalid), native_launched=False)


def assets(args):
    names = ('driver', 'python', 'original_dll', 'heap_helper', 'cooperative')
    result = {name: dict(path=str(getattr(args, name).resolve()), sha256=digest(getattr(args, name).read_bytes())) for name in names}
    for name in ('heap_helper', 'cooperative'):
        receipt = getattr(args, name).with_name('build.json')
        result[name]['receipt_sha256'] = digest(receipt.read_bytes())
        value = json.loads(receipt.read_text(encoding='utf-8-sig'))
        require(value['experimental'] is True and value['dll_sha256'] == result[name]['sha256'], 'helper build receipt differs')
        result[name]['receipt'] = value
        source='client_patch/checkpoint/arena.cpp' if name=='heap_helper' else 'client_patch/checkpoint/cooperative.cpp'
        require(value['source_sha256'] == digest((ROOT/source).read_bytes()), 'helper source differs from build receipt')
        if name=='heap_helper':
            require(value['page_source_sha256'] == digest((ROOT/'client_patch/checkpoint/page_checkpoint.hpp').read_bytes()), 'heap page source differs from receipt')
    driver_receipt=args.driver.with_name('build.json')
    compiled=json.loads(driver_receipt.read_text(encoding='utf-8-sig'))
    require(compiled['executable_sha256'] == result['driver']['sha256'] and
            all(digest((ROOT/name).read_bytes()) == value for name,value in compiled['source_sha256'].items()) and
            'tools/prediction_worker_probe.cpp' in compiled['source_sha256'], 'driver source/build receipt differs')
    result['driver']['receipt_sha256']=digest(driver_receipt.read_bytes())
    result['driver']['receipt']=compiled
    return result


def prepare(args):
    output = args.output.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT/'local') and not output.exists(), 'fresh private Windows output required')
    require(args.module_root.resolve() == ROOT, 'probe must use this source-bound module root')
    baseline = args.baseline.resolve()
    reference = json.loads((baseline/'baseline/report.json').read_text())
    require(reference['passed'] and reference['frame_count'] == 1200 and reference['dead'] and reference['disappeared'],
            'positive1200-frame combat baseline required')
    selected = assets(args)
    require(selected['original_dll']['sha256'] == SUPPORTED_DLL_SHA256, 'exact original native DLL required')
    output.mkdir(parents=True)
    command = [str(args.driver.resolve()), str(args.python.resolve()), str(ROOT), str(args.original_dll.resolve()),
               str(args.heap_helper.resolve()), str(args.cooperative.resolve()), str(output/'native-data'),
               str(baseline), str(output/'driver')]
    invocation = dict(scope=__doc__, command=command, source_sha256=source_hashes(), artifacts=selected,
        baseline=str(baseline), baseline_report_sha256=digest((baseline/'baseline/report.json').read_bytes()),
        journal_sha256=digest((baseline/'shared/canonical-frames.bin').read_bytes()),
        bootstrap_sha256=digest((baseline/'shared/bootstrap.pb').read_bytes()),
        snapshot_format='BASNP001 + repeated little-endian uint32frame,uint32length,raw; exact count/EOF; one viewer per file')
    write(output/'invocation.json', invocation)
    return invocation


def summarize(values):
    require(values, 'timing sample vector empty')
    ordered = sorted(values)
    return dict(count=len(ordered), minimum=min(ordered), median=statistics.median(ordered),
                p95=ordered[min(len(ordered)-1, (95*len(ordered)+99)//100-1)], maximum=max(ordered),
                mean=statistics.mean(ordered))


def analyze(args):
    output = args.output.resolve()
    invocation = json.loads((output/'invocation.json').read_text())
    report = dict(passed=False, scope=__doc__, invocation_sha256=digest((output/'invocation.json').read_bytes()))
    try:
        require(source_hashes() == invocation['source_sha256'], 'probe source changed after preparation')
        for value in invocation['artifacts'].values():
            require(digest(Path(value['path']).read_bytes()) == value['sha256'], 'probe executable/native/helper artifact changed')
        baseline = Path(invocation['baseline'])
        require(digest((baseline/'baseline/report.json').read_bytes()) == invocation['baseline_report_sha256'] and
                digest((baseline/'shared/canonical-frames.bin').read_bytes()) == invocation['journal_sha256'] and
                digest((baseline/'shared/bootstrap.pb').read_bytes()) == invocation['bootstrap_sha256'], 'retained baseline changed')
        driver = json.loads((output/'driver/driver.json').read_text())
        report['driver'] = driver
        require(driver['passed'] and driver['job_assigned_before_resume'] and driver['natural_shutdown'] and
                driver['process_reaped'] and driver['io_joined'] and driver['exit_code'] == 0 and
                driver['job_terminations'] == driver['timeouts'] == driver['io_abandoned'] == 0,
                'C++ owned driver/native-host lifecycle did not pass')
        require(driver['combat_frames'] == 1200 and driver['rematch_frames'] == 240 and driver['rematch_world'] != driver['first_world'],
                'combat/rematch prefix or world ownership differs')
        counts = dict(spawned=set(), damaged=set(), dead=set(), removed_after_dead=set(), attack_cooldown=set())
        rolling = hashlib.sha256()
        combat = output/'driver/combat'
        with (combat/'frames31.bin').open('rb') as f31, (combat/'frames0.bin').open('rb') as f0, (combat/'frames1.bin').open('rb') as f1, (baseline/'baseline/states.jsonl').open() as expected:
            readers = [snapshot_records(stream, 1200) for stream in (f31, f0, f1)]
            for frame in range(1200):
                row = json.loads(next(expected))
                records = [next(reader) for reader in readers]
                require(row['frame'] == frame and all(number == frame for number, _ in records), 'paired snapshot frame differs')
                state = decode_snapshot(records[0][1], 31, include_entities=True)
                state.pop('raw_sha256', None);state=normalized(state)
                require(state == row['state'] and digest(state) == row['state_sha256'], 'all parsed main-view state differs from combat baseline at'+str(frame))
                modes = normalized(entity_states(records[0][1]))
                require(modes == row['entity_states'], 'native entity-state/death buffer differs at'+str(frame))
                charges = {str(viewer): decode_cooldowns(records[viewer+1][1]) for viewer in (0, 1)}
                require(charges == row['ability_charges'], 'native allied ability-charge observations differ at'+str(frame))
                rolling.update(bytes.fromhex(row['state_sha256']))
                visible = set()
                for unit in state['entities']:
                    if unit.get('type') != 75 or unit.get('army') not in (0, 1):
                        continue
                    entity = unit['id'];counts['spawned'].add(entity)
                    if 'position' in unit:
                        visible.add(entity)
                    if unit.get('current_damage', 0) > 0:
                        counts['damaged'].add(entity)
                    if modes.get(str(entity)) == 6:
                        counts['dead'].add(entity)
                    if modes.get(str(entity)) == 4:
                        counts['attack_cooldown'].add(entity)
                counts['removed_after_dead'].update(counts['dead']-visible)
            require(next(expected, None) is None and all(next(reader, None) is None for reader in readers), 'snapshot/reference stream has unexpected tail')
        require(len(counts['spawned']) == 6 and len(counts['damaged']) == 6 and len(counts['dead']) == 5 and
                len(counts['removed_after_dead']) == 5, 'actual worker combat lifecycle positive gates missing')
        with (output/'driver/rematch/frames31.bin').open('rb') as stream, (baseline/'baseline/states.jsonl').open() as expected:
            reader=snapshot_records(stream, 240)
            for frame in range(240):
                number, raw=next(reader);row=json.loads(next(expected));state=decode_snapshot(raw,31,include_entities=True)
                state.pop('raw_sha256',None)
                require(number == frame and normalized(state) == row['state'] and
                        normalized(entity_states(raw)) == row['entity_states'], 'rematch parsed prefix differs at'+str(frame))
            require(next(reader,None) is None, 'rematch snapshot stream has a tail')
        with (output/'driver/calls.tsv').open() as stream:
            calls=list(csv.DictReader(stream,delimiter='\t'))
        require(len(calls) == driver['calls'] and all(int(row['ordinal']) == index+1 and int(row['opcode']) != 17 for index,row in enumerate(calls)),
                'call journal sequence/counter differs or crash opcode was invoked')
        require([int(row['opcode']) for row in calls[:4]] == [3,4,1,5], 'raw native startup ordering differs')
        benchmark=[int(row['duration_us']) for row in calls if row['phase']=='roundtrip_benchmark']
        require(len(benchmark) == 500 and all(int(row['opcode']) == 23 and int(row['result']) == 0 for row in calls if row['phase']=='roundtrip_benchmark'),
                'system-count timing benchmark differs')
        attributes=(output/'driver/system-records.bin').read_bytes()
        require(len(attributes) == driver['system_count']*128 and any(value != 0xa5 for value in attributes), '128-byte system array output differs')
        timings={str(op):summarize([int(row['duration_us']) for row in calls if int(row['opcode'])==op]) for op in sorted({int(row['opcode']) for row in calls})}
        report.update(passed=True, equal_combat_frames=1200,equal_rematch_frames=240,main_state_prefix_sha256=rolling.hexdigest(),
            combat_observations={key:len(value) for key,value in counts.items()},ability_charge_positive_coverage=False,
            system_record_count=driver['system_count'],cheap_native_call_plus_ipc_microseconds=summarize(benchmark),
            native_call_plus_ipc_microseconds_by_opcode=timings,
            limitations=['No Unity/GameAssembly client integration or live-network prediction proof.',
              'Decoded observables/entity states/charge vectors do not establish every hidden native state byte.',
              'Timing includes native API work, Python host/health checks, framing and IPC; it is not IPC-only latency.',
              'Combat charge vectors are empty; attack COOLDOWN4 state is positive but charge-specific cooldown behavior is unproven.',
              'Crowded combat does not independently instrument native collision-solver execution.'])
    except BaseException as error:
        report.update(error=type(error).__name__+': '+str(error),traceback=traceback.format_exc())
    report['source_sha256_at_finish']=source_hashes()
    write(output/'verification.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver',type=Path)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    parser.add_argument('--module-root',type=Path,default=ROOT)
    parser.add_argument('--original-dll',type=Path)
    parser.add_argument('--heap-helper',type=Path)
    parser.add_argument('--cooperative',type=Path)
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--output',type=Path)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--prepare-only',action='store_true')
    modes.add_argument('--analyze-only',action='store_true')
    modes.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        print(json.dumps(reader_self_test()));return 0
    require(args.output is not None, '--output required')
    if args.analyze_only:
        report=analyze(args)
    else:
        require(all(getattr(args,name) is not None for name in ('driver','original_dll','heap_helper','cooperative','baseline')), 'driver/native/helper/baseline paths required')
        invocation=prepare(args)
        if args.prepare_only:
            print(json.dumps(dict(prepared=True,command=invocation['command'])));return 0
        started=time.perf_counter()
        # This owns only the verifier executable. Its NativeHost is separately
        # started SUSPENDED and assigned a kill-on-close Job before Resume.
        with (args.output/'driver.stdout').open('xb') as stdout,(args.output/'driver.stderr').open('xb') as stderr:
            process=subprocess.Popen(invocation['command'],cwd=args.output,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            forced=False
            try:
                process.wait(timeout=95)
            except subprocess.TimeoutExpired:
                forced=True;process.terminate();process.wait(timeout=5)
            write(args.output/'driver-process.json',dict(pid=process.pid,exit_code=process.returncode,reaped=True,
                forced_cleanup=forced,retained_popen_handle=True,elapsed_seconds=time.perf_counter()-started))
        report=analyze(args)
        if forced or process.returncode:
            report.update(passed=False,driver_exit_code=process.returncode,driver_forced_cleanup=forced)
            write(args.output/'verification.json',report)
    print(json.dumps({key:report[key] for key in ('passed','error','equal_combat_frames','equal_rematch_frames','combat_observations','cheap_native_call_plus_ipc_microseconds') if key in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
