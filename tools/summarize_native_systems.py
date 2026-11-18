"""Strict offline qualification of an explicitly selected native systems capture.

Never executes a native library, launches a process or attaches instrumentation.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
from tools import profile_native_systems as helper
from tools import verify_compact_worker as v

ROOT = v.ROOT
RESIDUAL = 'Unmeasured immediate-return stubs, dispatch/call/other STEP work and observer overhead; not a measured subsystem.'


def require(value, message):
    if not value:
        raise ValueError(message)


def integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**53-1


def strict_json(raw):
    def pairs(items):
        result = {}
        for k, value in items:
            require(k not in result, 'duplicate JSON key')
            result[k] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite JSON: '+value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def stats(values):
    values = sorted(values)
    require(values and all(type(x) in (int, float) and math.isfinite(x) for x in values), 'invalid statistics')
    return dict(count=len(values), mean=sum(values)/len(values), p50=values[math.ceil(len(values)*.5)-1],
                p95=values[math.ceil(len(values)*.95)-1], p99=values[math.ceil(len(values)*.99)-1],
                maximum=values[-1], above_50ms=sum(x>50 for x in values), above_100ms=sum(x>100 for x in values))


def capture_envelope(bundle, evidence_id, session_id, config, script_sha, script_path, expected_count, *, schema=1, sensor_kind=None):
    records = bundle['records']
    selected = [r for r in records if r['evidence_id'] == evidence_id]
    require(len(selected) == 1, 'exact final evidence absent/duplicate')
    record = selected[0]
    require(record['operation'] == 'frida_session_status' and record['parameters']['session_id'] == session_id,
            'final operation/session differs')
    final = record['normalized_result']
    require(final['session_id'] == session_id and final['state'] == 'detached' and final['mode'] == 'attach'
            and final['pid'] == config['pid'] and final['messages_truncated'] is False, 'final identity/truncation differs')
    require(len(final['scripts']) == 1, 'unexpected script count')
    script = final['scripts'][0]['script_id']
    loads = [r['normalized_result'] for r in records if r['operation'] == 'load_frida_script'
             and r['parameters']['session_id'] == session_id]
    require(len(loads) == 1, 'script load absent/duplicate')
    load = loads[0]
    require(load['script_id'] == script and load['source_kind'] == 'file'
            and load['source_path'] == str(script_path) and load['source_sha256'] == script_sha
            and load['messages_truncated'] is False, 'script source/identity differs')
    messages = final['messages']
    require(len(messages) == 3+math.ceil(expected_count/60), 'message/chunk count differs')
    payloads = []
    # Inspect ALL messages; a prior complete cannot hide a later exception.
    for message in messages:
        require(message['type'] == 'send' and message['script_id'] == script, 'script error/unknown message')
        payload = message['payload']
        require(set(payload) == ({'schema','nonce','pid','kind','data'} | ({'sensorKind'} if sensor_kind else set()))
                and (sensor_kind is None or payload['sensorKind'] == sensor_kind)
                and type(payload['schema']) is int and payload['schema'] == schema
                and payload['nonce'] == config['nonce'] and payload['pid'] == config['pid'], 'payload identity/schema differs')
        require(payload['kind'] in ('armed','inventory','frames','complete'), 'capture error/unknown payload')
        payloads.append(payload)
    require([p['kind'] for p in payloads] == ['armed','inventory']+['frames']*math.ceil(expected_count/60)+['complete'],
            'message order/duplicate differs')
    require(load['messages'] == messages[:1], 'load armed message differs')
    return payloads


def validate_capture(bundle, evidence_id, session_id, config, script_sha, script_path, expected_count, timestep):
    payloads = capture_envelope(bundle,evidence_id,session_id,config,script_sha,script_path,expected_count)
    armed, inventory, complete = payloads[0]['data'], payloads[1]['data'], payloads[-1]['data']
    require(armed['world'] == config['world'] == inventory['world'] and armed['moduleBase'] == inventory['moduleBase']
            and armed['expectedFrames'] == expected_count == config['expected_frames']
            and armed['byteChecks'] == len(config['byte_checks']), 'world/armed binding differs')
    frequency = inventory['ticksPerSecond']
    require(integer(frequency,1) and armed['ticksPerSecond'] == frequency and inventory['unit'] == 'QPC ticks', 'QPC units differ')
    require(integer(inventory['moduleSize'],1) and type(inventory['checksumEnabled']) is int and inventory['checksumEnabled'] in (0,1), 'inventory module/flag differs')
    systems = inventory['systems']
    require(1 <= len(systems) <= 256, 'system count outside bound')
    objects = set()
    for i, system in enumerate(systems):
        require(integer(system['index']) and system['index'] == i and system['object'] not in objects, 'system index/object duplicate')
        objects.add(system['object'])
        require(isinstance(system['type'],str) and system['type'].startswith('.?AVSystem'), 'unknown system type')
        for role in ('update','checksum'):
            entry = system[role+'EntryHex']
            require(isinstance(entry,str) and re.fullmatch('[0-9a-f]{6}', entry), 'invalid entry bytes')
            trivial = entry.startswith('c3') or entry == '33c0c3'
            require(type(system[role+'Timed']) is bool and system[role+'Timed'] is not trivial, 'invalid timed/excluded method')
            require(system[role+'Reason'] == ('exact immediate-return/return-zero leaf; not instrumented' if trivial else None), 'method exclusion reason differs')
    require(complete['frames'] == complete['expectedFrames'] == expected_count and complete['failed'] is False
            and complete['inventoryCount'] == len(systems) and complete['capturedThrough'] == expected_count-1,
            'completion counts/failure differs')
    frames = []
    tid = None
    for chunk in payloads[2:-1]:
        chunk = chunk['data']
        require(set(chunk) == {'start','rows'} and chunk['start'] == len(frames)
                and len(chunk['rows']) == min(60,expected_count-len(frames)), 'chunk omission/duplicate/truncation')
        for row in chunk['rows']:
            require(set(row) == {'frame','tid','dt','checksumEnabled','systems','stepTicks','returnCode','countsValid'}, 'frame schema differs')
            require(row['frame'] == len(frames) and integer(row['frame']) and row['dt'] == timestep
                    and integer(row['dt']) and integer(row['tid'],1), 'frame/dt/thread differs')
            tid = row['tid'] if tid is None else tid
            require(row['tid'] == tid and type(row['checksumEnabled']) is int and row['checksumEnabled'] == inventory['checksumEnabled']
                    and row['countsValid'] is True and type(row['returnCode']) is int and row['returnCode'] == 0,
                    'frame thread/checksum/return differs')
            require(integer(row['stepTicks']) and len(row['systems']) == len(systems), 'frame elapsed/system count differs')
            measured = 0
            for system, cell in zip(systems,row['systems']):
                require(isinstance(cell,list) and len(cell) == 4, 'system cell schema differs')
                for role,offset,enabled in (('update',0,row['dt']>0),('checksum',2,bool(row['checksumEnabled']))):
                    count,elapsed = cell[offset:offset+2]
                    timed = system[role+'Timed']
                    require(integer(count) and count == int(timed and enabled), 'missing/extra timed role dispatch')
                    require(integer(elapsed) if timed else elapsed is None, 'elapsed for excluded/nonfinite method')
                    if timed:
                        require(enabled or elapsed == 0, 'disabled role has elapsed time')
                        measured += elapsed
            require(measured <= row['stepTicks'], 'sequential role timing exceeds STEP')
            frames.append(row)
    require(len(frames) == expected_count, 'incomplete frames')
    return inventory, frames


class PE:
    def __init__(self, raw):
        self.raw = raw
        pe = struct.unpack_from('<I',raw,0x3c)[0]
        require(raw[:2] == b'MZ' and raw[pe:pe+4] == b'PE\0\0', 'invalid PE')
        count, optional = struct.unpack_from('<H',raw,pe+6)[0], pe+24
        require(struct.unpack_from('<H',raw,optional)[0] == 0x20b, 'PE64 required')
        self.base = struct.unpack_from('<Q',raw,optional+24)[0]
        self.size = struct.unpack_from('<I',raw,optional+56)[0]
        start = optional+struct.unpack_from('<H',raw,pe+20)[0]
        self.sections = [struct.unpack_from('<IIII',raw,start+40*i+8) for i in range(count)]
    def at(self, rva, size):
        for virtual_size,virtual,raw_size,offset in self.sections:
            if virtual <= rva and rva+size <= virtual+raw_size:
                return self.raw[offset+rva-virtual:offset+rva-virtual+size]
        raise ValueError('RVA outside raw PE')


def validate_inventory_image(inventory, config, raw):
    pe = PE(raw)
    require(inventory['moduleSize'] == pe.size, 'loaded module size differs')
    for check in config['byte_checks']:
        require(pe.at(check['rva'],len(check['hex'])//2).hex() == check['hex'], 'script exact image guard differs')
    for system in inventory['systems']:
        table = int(system['vtableRva'],16)
        for role,offset in (('update',8),('checksum',16)):
            rva = int(system[role+'Rva'],16)
            require(struct.unpack('<Q',pe.at(table+offset,8))[0] == pe.base+rva
                    and pe.at(rva,3).hex() == system[role+'EntryHex'], 'unknown/changed vtable method')
        locator = struct.unpack('<Q',pe.at(table-8,8))[0]-pe.base
        require(struct.unpack('<I',pe.at(locator,4))[0] == 1, 'RTTI locator differs')
        descriptor = struct.unpack('<I',pe.at(locator+12,4))[0]
        typename = bytearray()
        for i in range(256):
            value = pe.at(descriptor+16+i,1)
            if value == b'\0': break
            typename.extend(value)
        require(typename.decode('ascii') == system['type'], 'unknown/changed system RTTI')


def bound_replay(capture, control):
    bindings = {}
    def read(path):
        path = Path(path)
        require(not path.is_symlink() and path.stat().st_size <= 128*1024*1024, 'unbounded/redirected input')
        raw = path.read_bytes(); bindings[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        return raw
    def document(path): return strict_json(read(path))
    report = document(capture/'verification.json'); launch = document(capture/'launch.json')
    ready = document(capture/'ready.json'); identity = document(capture/'identity.json')
    release = document(capture/'release.json'); released = document(capture/'released.json')
    finished = document(capture/'worker-finished.json')
    require(report['passed'] is True and report['schema'] == 1 and report['sources_unchanged'] is True
            and report['inputs_unchanged'] is True and report['worker_exit_code'] == 0
            and report['external_instrumentation'] is True and report['performance_acceptance_evaluated'] is False,
            'helper qualification/cleanup incomplete')
    require(launch['output'] == str(capture) and helper.nonce_ok(launch['nonce'])
            and launch['schema'] == ready['schema'] == identity['schema'] == 1 and ready['frame'] == -1
            and ready['nonce'] == launch['nonce'] == report['nonce'] == identity['nonce'] == finished['nonce']
            and ready['pid'] == identity['pid'] == finished['pid'] and finished['exit_code'] == 0
            and finished['drain_seconds'] == launch['drain_seconds'] and report['worker_finished'] == finished,
            'gate/completion identity differs')
    require(ready['image'] == launch['image'] == identity['actual_image'] and identity['job_member'] is True
            and identity['retained_handle'] is True and ready['parent_pid'] == launch['parent_pid'] == identity['parent_pid']
            and identity['ready_sha256'] == helper.sha(capture/'ready.json') and report['identity'] == identity,
            'owned identity differs')
    source = launch['source_sha256']
    require(source == ready['source_sha256'] == identity['source_sha256'] and source == helper.sources(), 'helper source binding differs')
    for path,digest in source.items(): require(hashlib.sha256(read(ROOT/path)).hexdigest() == digest, 'source changed')
    expected_release = dict(schema=1,action='release',nonce=ready['nonce'],pid=ready['pid'],parent_pid=ready['parent_pid'],
                            ready_sha256=helper.sha(capture/'ready.json'),identity_sha256=helper.sha(capture/'identity.json'),
                            source_sha256=source,attached=True)
    require(release == released == expected_release and report['release_sha256'] == helper.sha(capture/'release.json'), 'release binding differs')
    for path,digest in report['input_sha256'].items(): require(hashlib.sha256(read(Path(path))).hexdigest() == digest, 'helper input changed')
    arm = document(capture/'arm/benchmark.json'); ordinary = document(control/'verification.json')
    require(report['arm'] == arm and document(control/'arm/benchmark.json') == ordinary, 'arm evidence differs')
    for a in (arm,ordinary):
        require(a['passed'] is True and a['native_qualified'] is True and a['source_unchanged'] is True
                and a['source_at_start'] == a['source_at_finish'] == v.sources() and v.w.clean_exit(a)
                and a['frames'] == 1562 and a['state_mode'] == 'full' and a['timestep_ms'] == 50, 'replay/control qualification differs')
    for key in ('simulation_sha256','bootstrap_sha256','asset_manifest_sha256','input_journal_sha256','workload','backend','snapshot_decoder','initial_full_state_sha256'):
        require(arm[key] == ordinary[key], 'control workload/runtime identity differs: '+key)
    require(arm['native_worker_pid'] == ready['pid'] and ready['dll'] == launch['dll']
            and ready['dll_sha256'] == launch['dll_sha256'] == arm['simulation_sha256']
            and ready['world_hex'] == hex(ready['world']), 'native world/DLL differs')
    args = argparse.Namespace(assets=Path(report['reference']['assets']),journal=Path(report['reference']['journal']),
                              baseline_inputs=next(Path(p) for p in report['input_sha256'] if p.endswith('baseline-inputs.json')),fresh_ai=False)
    retained = v.load_inputs(args,{})
    require(retained['reference'] == report['reference'], 'retained journal guards differ')
    rows,controls = [],[]
    for directory,target in ((capture/'arm',rows),(control/'arm',controls)):
        target.extend(strict_json(line) for line in read(directory/'frames.jsonl').splitlines())
        require(len(target) == 1562 and read(directory/'frames.bin') == retained['inputs'], 'replay input coverage differs')
        for i,(actual,expected) in enumerate(zip(target,retained['rows'])):
            require(actual['frame'] == i and actual['phase'] == expected['phase']
                    and actual['input_sha256'] == expected['input_sha256']
                    and actual['state_sha256'] == actual['full_reference_state_sha256'] == expected['state_sha256'], 'actual input/state differs')
            require(type(actual['step_rpc_ms']) in (int,float) and math.isfinite(actual['step_rpc_ms']) and actual['step_rpc_ms']>=0, 'invalid RPC timing')
    return dict(read=read,document=document,bindings=bindings,report=report,launch=launch,ready=ready,source=source,arm=arm,ordinary=ordinary,rows=rows,controls=controls)


def summarize(capture, control, evidence_id, session_id):
    context = bound_replay(capture,control)
    read,document,bindings,launch,ready,source,rows,controls = (context[k] for k in ('read','document','bindings','launch','ready','source','rows','controls'))
    script = read(capture/'sensor.js'); match = re.search(rb'const config = (\{[^\r\n]+\});',script)
    require(match is not None,'sensor config absent'); config = strict_json(match[1])
    require(config['pid'] == ready['pid'] and config['nonce'] == ready['nonce'] and config['image'] == ready['image']
            and config['dll'] == ready['dll'] and config['world'] == ready['world_hex'], 'sensor/gate identity differs')
    inventory,frames = validate_capture(document(capture/'rea-evidence.json'),evidence_id,session_id,config,
        hashlib.sha256(script).hexdigest(),capture/'sensor.js',1562,50)
    require(len(inventory['systems']) == 41, 'exact retained41system dispatch contract differs')
    validate_inventory_image(inventory,config,read(Path(launch['dll'])))
    factor = 1000/inventory['ticksPerSecond']; phases = {}
    perframe=[]
    for row,actual in zip(frames,rows):
        measured=sum(c[1] or 0 for c in row['systems'])+sum(c[3] or 0 for c in row['systems'])
        perframe.append(dict(frame=row['frame'],phase=actual['phase'],step_ms=row['stepTicks']*factor,
            residual_ms=(row['stepTicks']-measured)*factor,role_ms=[[c[1]*factor if c[1] is not None else None,
            c[3]*factor if c[3] is not None else None] for c in row['systems']]))
    for phase in v.c.PHASES:
        selected=[r for r in perframe if r['phase']==phase]; ranked=[]
        step=stats([r['step_ms'] for r in selected])
        for i,system in enumerate(inventory['systems']):
            for role,offset in (('update',0),('checksum',1)):
                if system[role+'Timed']:
                    timing=stats([r['role_ms'][i][offset] for r in selected])
                    ranked.append(dict(index=i,type=system['type'],role=role,rva=system[role+'Rva'],timings_ms=timing,
                                       fraction_step_mean=timing['mean']/step['mean']))
        instrumented_rpc=stats([r['step_rpc_ms'] for r in rows if r['phase']==phase]);control_rpc=stats([r['step_rpc_ms'] for r in controls if r['phase']==phase])
        phases[phase]=dict(frames=len(selected),step_ms=step,residual_ms=stats([r['residual_ms'] for r in selected]),
            ranked_roles=sorted(ranked,key=lambda r:r['timings_ms']['mean'],reverse=True),
            tail_frames=sorted(selected,key=lambda r:r['step_ms'],reverse=True)[:max(1,math.ceil(.05*len(selected)))],
            observer_comparison=dict(instrumented_rpc_ms=instrumented_rpc,control_rpc_ms=control_rpc,
                mean_delta_ms=instrumented_rpc['mean']-control_rpc['mean'],
                p95_delta_ms=instrumented_rpc['p95']-control_rpc['p95']))
    for name in ('tools/summarize_native_systems.py','tests/test_summarize_native_systems.py'):
        read(ROOT/name)
    for path,digest in list(bindings.items()):require(helper.sha(path)==digest,'evidence changed during summary')
    return dict(schema=1,passed=True,instrumentation_qualified=True,helper_replay_qualified=True,evidence_id=evidence_id,
        session_id=session_id,sensor_source_sha256=hashlib.sha256(script).hexdigest(),sources=source,evidence_sha256=bindings,
        inventory=inventory,phases=phases,frames=perframe,residual_scope=RESIDUAL,
        limitations=['One instrumented replay and one ordinary control; no repeated performance gate or 20Hz acceptance.',
        'RPC deltas combine observer effects and uncontrolled scheduling/frequency/contention; they are not isolated hook overhead.',
        'Inclusive wall timings measure direct native system calls including their internal workers/waits; no CPU stacks/wait reason attribution.',
        'Trivial immediate-return roles are unmeasured with null elapsed, not measured zero-cost. Checksums disabled means no checksum work observed.',
        'Windows machine only; no cross-hardware Wine penalty, Linux hotspot timing, live deployment or capacity inference.'])


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('capture','control','output'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('evidence-id','session-id'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    output=helper.fresh_output(args.output)
    result=summarize(args.capture.resolve(),args.control.resolve(),args.evidence_id,args.session_id)
    output.mkdir(parents=True,exist_ok=False)
    helper.write_new(output/'summary.json',result)
    text=['Native systems capture qualified; instrumented inclusive wall milliseconds. Residual: '+RESIDUAL]
    for phase,p in result['phases'].items():
        text.append(f"{phase}: STEP mean={p['step_ms']['mean']:.3f}, p95={p['step_ms']['p95']:.3f}; RPC delta={p['observer_comparison']['mean_delta_ms']:.3f}ms")
        text.extend(f"  {r['type']} {r['role']} {r['rva']}: mean={r['timings_ms']['mean']:.3f}, p95={r['timings_ms']['p95']:.3f}, share={r['fraction_step_mean']:.3%}" for r in p['ranked_roles'][:8])
    text.extend(result['limitations'])
    (output/'summary.txt').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,output=str(output),summary_sha256=helper.sha(output/'summary.json'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
