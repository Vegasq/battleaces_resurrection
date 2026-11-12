"""Prepare-only original-worker correction-query control.

An explicit coordinated run uses two sequential retained-Job children, with the
movement observer OFF. Both reuse a CLOSED original queued-order reference.
Only the enabled child adds the correction-H own-view query. Gameplay uses
only own-view outputs; one terminal Spectator31 query follows all ordinary
evidence, with no later gameplay. This is not per-frame full hidden-state or
Unity smoothing acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools import verify_prediction_worker_reconcile as base
from tools.verify_prediction_worker_ledger import register_batch
from tools.verify_high_latency_clients import state_digest
from server.native_simulation import decode_snapshot
from tools.verify_prediction_combat_fixture import entity_states

require, sha, write = base.require, base.sha, base.write
CASE = dict(received=300, head=310, next=311, last=371, reference_last=420)
ROLES = ('disabled', 'enabled')


def references(folder):
    folder = Path(folder); report = json.loads((folder/'verification.json').read_text())
    require(report.get('passed') is True and report.get('forced') is False and report.get('cleanup_errors') == [] and
        report.get('exit_code') == 0 and report.get('reaped') is True and report.get('retained_handle_closed') is True and
        report['job']['active'] == report['job']['terminated'] == 0, 'closed original reference did not pass naturally')
    proof = report['child']; branch = proof['branches']['intent_queue']
    require(proof['passed'] is True and branch['passed'] is True and branch['closed'] is True and
        proof['evidence']['queued_later_B_response_frame'] == 351, 'retained original intent reference differs')
    folder = folder/'control/intent_queue'
    with (folder/'frames.bin').open('rb') as stream:
        frames = base.read_journal(stream, count=CASE['reference_last']+1)
    rows = [json.loads(line) for line in (folder/'states.jsonl').read_text().splitlines()]
    require([r['frame'] for r in rows] == list(range(CASE['reference_last']+1)), 'original state prefix is incomplete')
    for frame in range(CASE['last']+1):
        row = rows[frame]; snapshot = folder/'snapshots'/f'{frame:08d}.bin'
        require(sha(snapshot) == row['raw_snapshot_sha256'] and base.digest(frames[frame]) == row['input_sha256'],
                'retained input/snapshot hash differs')
        raw = snapshot.read_bytes()
        require(state_digest(decode_snapshot(raw,31,include_entities=True)) == row['parsed_state_sha256'] == state_digest(row['state']) and
                base.normalized(entity_states(raw)) == row['modes'], 'original parsed reference differs from raw snapshot')
    return frames, rows


def metadata(raw, world, frame):
    require(type(raw) is bytes and len(raw) >= 32, 'correction response truncated')
    version, owner, publication, head, revision, count = struct.unpack_from('<IQiiQI', raw)
    require(version == 1 and owner == world and publication == frame and count <= 65536 and len(raw) == 32+32*count and
            (head == frame-1 and frame > 0 and revision > 0 if count else head == -1), 'correction response header differs')
    entries = []; previous = -1; tokens = set()
    for index in range(count):
        entity, kind, army, token, x, y, z = struct.unpack_from('<IIIQfff',raw,32+32*index)
        require(entity > previous and token > 0 and token not in tokens and all(math.isfinite(v) for v in (x,y,z)),
                'correction response identity/Single differs')
        entries.append(dict(entity=entity,type=kind,army=army,incarnation=token,delta=[x,y,z]))
        previous = entity; tokens.add(token)
    return dict(world=owner,frame=publication,head=head,revision=revision,entries=entries,sha256=base.digest(raw))


def compare(observed, reference, frame):
    require(observed['state']['frame'] == frame and state_digest(observed['state']) == reference[frame]['parsed_state_sha256'] and
            base.normalized(observed['entity_states']) == reference[frame]['modes'], 'original native state/UnitState differs at'+str(frame))


def compare_own(observed, reference, frame):
    state = observed['state']; expected = reference[frame]['state']
    require(state['frame'] == frame and state['local_alliance'] == 1, 'wrong own-view frame/alliance')
    expected_entities = {r['id']: r for r in expected['entities']}
    actual_entities = {r['id']: r for r in state['entities']}
    require(len(actual_entities) == len(state['entities']), 'duplicate own-view entity')
    own = lambda rows: {i for i,r in rows.items() if r.get('army') == 1}
    require(own(actual_entities) == own(expected_entities), 'own entity visibility differs from original reference')
    owned = own(actual_entities)
    for entity in owned:
        row = actual_entities[entity]
        require(entity in expected_entities and all(expected_entities[entity].get(k) == value for k,value in row.items()),
                'available own-view component/position differs at'+str(frame))
    require(all(reference[frame]['modes'].get(str(i)) == mode for i,mode in observed['entity_states'].items() if int(i) in owned),
            'available own-view UnitState differs at'+str(frame))
    require(state['game_state'] == expected['game_state'] and
            all(expected['resources'].get(str(i),expected['resources'].get(i)) == value for i,value in state['resources'].items()),
            'available own-view GameState/resource differs')


def admit_query(viewer, phase):
    require(viewer == 1 or (viewer == 31 and phase == 'terminal_full_state'),
            'diagnostic/non-own query would contaminate gameplay control')


def audit_queries(pairs, role):
    require(role in ROLES and pairs and pairs[-1]['viewer'] == 31 and
            pairs[-1]['phase'] == 'terminal_full_state' and pairs[-1]['frame'] == CASE['last'],
            'exact terminal-only Spectator31 snapshot missing')
    require(all(r['viewer'] == 1 for r in pairs[:-1]), 'non-own query preceded terminal evidence')
    ordinary = [r for r in pairs if r['phase'] in ('prefix','pending','continuations')]
    require([r['frame'] for r in ordinary] == list(range(CASE['last']+1)), 'ordinary own-view prefix is incomplete')
    startup = [r for r in pairs if r['phase'] == 'startup']
    require(len(startup) == 1 and startup[0]['viewer'] == 1, 'bootstrap must warm only original own view')
    repair = [r for r in pairs if r['phase'] == 'repair']
    require([r['frame'] for r in repair] == ([CASE['head']] if role == 'enabled' else []),
            'correction query is not exactly the enabled own-H pair')
    require(len(pairs) == len(ordinary)+len(startup)+len(repair)+1, 'unclassified native query')
    return dict(ordinary_own_frames=len(ordinary),terminal_full_frames=1,diagnostic_queries_during_gameplay=0)


def expected_delta(old, corrected, entity):
    def member(raw):
        decoded = decode_snapshot(raw,1,include_entities=True)
        require(decoded['frame'] == CASE['head'] and decoded['local_alliance'] == 1, 'delta inputs are not the same own native H')
        rows = [r for r in decoded['entities'] if r['id'] == entity]
        state = entity_states(raw).get(entity)
        require(len(rows) == 1 and rows[0]['army'] == 1 and rows[0]['type'] == 1 and
                state is not None and state != 6, 'original query subject identity/liveness differs')
        return rows[0]['position']
    return list(struct.unpack('<fff', struct.pack('<fff', *(b-a for a,b in zip(member(old),member(corrected))))))


class Coordinator(base.Coordinator):
    sequence = 1
    def create(self, bootstrap):
        raw = self.success(5,bootstrap); require(len(raw) == 8, 'invalid native worker world')
        world, = struct.unpack('<Q',raw); require(world > 0, 'null worker world')
        # Do not inherit the baseline verifier's 31/0/1 scratch warming.
        base.decode_pair(*self.dispatch(9,struct.pack('<QII',world,1,0)))
        self.success(64,struct.pack('<QII',world,12,16*1024*1024))
        require(self.metrics(world)['captures'] == 1, 'BEGIN did not prime checkpoint')
        return world
    def observe(self, world, frame, phase):
        # No inherited all-view observation: this is the normal own-view query.
        stamp = time.perf_counter()
        raw = base.decode_pair(*self.dispatch(9,struct.pack('<QII',world,1,0)))
        state = decode_snapshot(raw,1,include_entities=True)
        result = base.normalized(dict(state=state,entity_states=entity_states(raw)))
        require(state['frame'] == frame, 'ordinary own-view frame differs')
        key = ('ordinary',1)
        if key not in self.raw_streams:
            path = self.output/'ordinary/view1.bin'; path.parent.mkdir(parents=True,exist_ok=True)
            self.raw_streams[key] = path.open('xb'); self.raw_streams[key].write(b'BASNP001')
            self.observations['ordinary'] = (path.parent/'states.jsonl').open('x')
        self.raw_streams[key].write(struct.pack('<II',frame,len(raw))+raw)
        self.observations['ordinary'].write(json.dumps(dict(frame=frame,**result),sort_keys=True,allow_nan=False)+'\n')
        self.observer_seconds += time.perf_counter()-stamp
        return result
    def batch(self, world, body, assigned):
        register_batch(self.dispatch,world,self.sequence,body,expected_frame=assigned)
        self.sequence += 1
    def canonical(self, world, raw):
        from client_patch.prediction_worker.commands import own_player_body
        from server.protobuf_wire import get_repeated_bytes
        own = own_player_body(raw,1)
        if own and get_repeated_bytes(own,2): self.batch(world,own,self.session.predictions[world].predicted_frame+1)
        return self.enqueue(world,[raw])


def child(output, role):
    require(role in ROLES and sys.stdin.buffer.readline(32) == b'OWNED_JOB\n', 'missing retained Job ownership barrier')
    plan = json.loads((output/'invocation.json').read_text()); prepared = Path(plan['output']); folder = output/'child'
    report = dict(passed=False,role=role,errors=[],native_executed=False,observer_enabled=False,root_bindings=[])
    session = coordinator = None; pairs = []; last_own = {}; repair_raw = []; executed = []; started = time.perf_counter()
    try:
        base.verify_prepared(plan); require(threading.active_count() == 1, 'worker must begin with one Python owner')
        frames, reference = references(prepared/'inputs/reference')
        from client_patch.prediction_worker.native import NativeSession
        from client_patch.prediction_worker.commands import own_player_body
        from server.protobuf_wire import get_repeated_bytes
        session = NativeSession.open(original_dll=prepared/'inputs/native/Simulation.dll',
            heap_helper=prepared/'inputs/heap/BAHeap.dll', cooperative=prepared/'inputs/cooperative/PredictionCooperative.dll',
            data_dir=folder/'native-data')
        report['native_executed'] = True
        if role == 'enabled': session.enable_movement_corrections()
        require(session.movement_observer is None, 'diagnostic state observer must be OFF')
        c = coordinator = Coordinator(session,folder,reference); original_pair = session._pair
        original_call = session.api.call
        def call(name,*args):
            if name == 'SimProcessMsg':
                import ctypes as C
                raw = C.string_at(args[1],args[2]); executed.append(dict(frame=base.frame_number(raw),sha256=base.digest(raw),phase=c.phase))
            return original_call(name,*args)
        session.api.call = call
        def pair(size,make_name,make_args,get_name,get_args,**kwargs):
            if make_name == 'SimMakeSimFrame': admit_query(make_args[1],c.phase)
            stamp = time.perf_counter_ns(); result = original_pair(size,make_name,make_args,get_name,get_args,**kwargs)
            elapsed = time.perf_counter_ns()-stamp
            if make_name == 'SimMakeSimFrame':
                raw = base.decode_pair(*result); viewer = make_args[1]; decoded = decode_snapshot(raw,viewer)
                row = dict(phase=c.phase,frame=decoded['frame'],viewer=viewer,bytes=len(raw),sha256=base.digest(raw),pair_ns=elapsed)
                pairs.append(row)
                if viewer == 1: last_own.update(frame=decoded['frame'],raw=raw)
                if c.phase == 'repair' and decoded['frame'] == CASE['head'] and viewer == 1:
                    repair_raw.append(raw)
            return result
        session._pair = pair
        c.success(3,b'\1'); c.success(4,struct.pack('<I',0)); c.success(1,b'\0')
        world = c.create((prepared/'inputs/reference/control/bootstrap.pb').read_bytes())
        require(c.success(71,struct.pack('<Q',world)) == struct.pack('<I',1), 'qualified native allocation guard unavailable')
        roots = session.arena.root_bindings(); report['root_bindings'].append(dict(phase='begin',token=roots))
        for frame in range(CASE['received']+1):
            c.phase = 'prefix'; c.canonical(world,frames[frame]); c.process(world,frames[frame]); c.step(world)
            compare_own(c.observe(world,frame,'prefix'),reference,frame)
        c.batch(world,own_player_body(frames[301],1),301)
        for frame in range(301,CASE['head']+1):
            if frame == 303: c.batch(world,own_player_body(frames[303],1),303)
            c.phase = 'pending'; c.process(world,frames[frame]); c.step(world); value = c.observe(world,frame,'pending')
            subject = next(r for r in value['state']['entities'] if r['id'] == 11)
            require(math.dist(subject['position'],reference[300]['position']) <= .025 and value['entity_states']['11'] == 0,
                    'omitted pending88/queued12 moved prematurely')
        old = last_own['raw']; before = c.metrics(world)
        require(before['confirmed_frame'] == before['received_frame'] == 300 and before['predicted_frame'] == 310,
                'wrong actual physical correction boundary')
        enqueue = c.enqueue(world,frames[301:312])
        c.phase = 'repair'; stamp = time.perf_counter_ns(); c.process(world,frames[311])
        repair_ns = time.perf_counter_ns()-stamp
        c.step(world); c.phase = 'continuations'; compare_own(c.observe(world,311,'continuations'),reference,311)
        receipt = None; request_ns = None
        if role == 'enabled':
            require(len(repair_raw) == 1, 'exactly one correction-only own-H pair required')
            compare_own(base.normalized(dict(state=decode_snapshot(repair_raw[0],1,include_entities=True),
                entity_states=entity_states(repair_raw[0]))),reference,310)
            stamp = time.perf_counter_ns(); calls = c.native_calls
            raw = c.success(77,struct.pack('<Qi',world,311)); request_ns = time.perf_counter_ns()-stamp
            receipt = metadata(raw,world,311)
            require(c.native_calls == calls and c.success(77,struct.pack('<Qi',world,311)) == raw,
                    'metadata control queried native or changed its immutable result')
            subject = [r for r in receipt['entries'] if r['entity'] == 11]
            require(len(subject) == 1 and subject[0]['delta'] == expected_delta(old,repair_raw[0],11) and
                    any(abs(x) > .025 for x in subject[0]['delta']), 'metadata is not actual same-H native displacement')
            (folder/'old-head-own-view.bin').write_bytes(old); (folder/'corrected-head-own-view.bin').write_bytes(repair_raw[0])
            (folder/'correction-response.bin').write_bytes(raw)
        else:
            require(not repair_raw, 'disabled path made correction-H query')
        for frame in range(312,CASE['last']+1):
            c.phase = 'continuations'; c.canonical(world,frames[frame]); c.process(world,frames[frame]); c.step(world)
            compare_own(c.observe(world,frame,'continuations'),reference,frame)
            if role == 'enabled' and frame == 312:
                require(c.success(77,struct.pack('<Qi',world,311)) == raw, 'published frame lost after one pending output')
            if role == 'enabled' and frame == 313:
                from client_patch.prediction_worker.corrections import CorrectionError
                calls = c.native_calls
                try: c.dispatch(77,struct.pack('<Qi',world,311))
                except CorrectionError: pass
                else: raise AssertionError('stale frame was replaced by nearest metadata')
                require(c.native_calls == calls, 'stale metadata refusal queried native')
        after = c.metrics(world)
        require(after['corrections']-before['corrections'] == 1 and after['replayed_frames']-before['replayed_frames'] == 10 and
            after['confirmed_frame'] == after['received_frame'] == after['predicted_frame'] == 371 and
            session.arena.root_bindings() == roots and session.movement_observer is None,
            'native reconciliation/counter/owner/default-observer contract differs')
        repair_inputs = [r for r in executed if r['phase'] == 'repair']
        require([r['frame'] for r in repair_inputs] == list(range(301,312)) and
                all(r['sha256'] == base.digest(frames[r['frame']]) for r in repair_inputs), 'actual replay/next input bytes differ')
        # The ONE independent full snapshot is after the final own-view bytes.
        # No later ProcessMsg/Step may hide auxiliary effects before comparison.
        c.phase = 'terminal_full_state'
        raw31 = base.decode_pair(*c.dispatch(9,struct.pack('<QII',world,31,0)))
        compare(dict(state=decode_snapshot(raw31,31,include_entities=True),entity_states=entity_states(raw31)),reference,371)
        (folder/'terminal31.bin').write_bytes(raw31)
        query_audit = audit_queries(pairs,role)
        report.update(proof_complete=True,available_own_comparisons=362,terminal_full_comparisons=1,
            corrected_head_own_reference_checked=True if role == 'enabled' else None,
            query_audit=query_audit,continuations=[311,371],
            case_plan=CASE,authority_enqueue=enqueue,metadata=receipt,repair_boundary_ns=repair_ns,
            metadata_request_ns=request_ns,added_pair_ns=[r['pair_ns'] for r in pairs if r['phase']=='repair' and r['frame']==310 and r['viewer']==1],
            before_metrics=before,after_metrics=after,retirement=c.retire(world))
        require(session.movement_corrections is None or not session.movement_corrections.worlds, 'correction cache survived retirement')
        report['root_bindings'].append(dict(phase='retired',token=session.arena.root_bindings()))
    except BaseException as error:
        report['errors'].append(dict(phase='proof',error=repr(error),traceback=traceback.format_exc()))
    finally:
        if session is not None:
            try:
                session.close(); report['session_closed'] = True
                report['arena_after_close'] = session.arena.healthy()
                report['root_bindings'].append(dict(phase='closed',token=session.arena.root_bindings()))
                require(report['arena_after_close']['saved_bytes'] == 0 and not session.worlds and not session.predictions and
                    not session.prediction_adapters and all(r['token'] == report['root_bindings'][0]['token'] for r in report['root_bindings']),
                    'native cleanup retained snapshots/worlds or changed roots')
            except BaseException as error: report['errors'].append(dict(phase='cleanup',error=repr(error)))
        if coordinator is not None:
            report['native_calls_including_cleanup'] = coordinator.native_calls
            try: coordinator.close_observers()
            except BaseException as error: report['errors'].append(dict(phase='trace_cleanup',error=repr(error)))
        try:
            write(folder/'query-pairs.json',pairs); write(folder/'executed-inputs.json',executed)
            base.verify_prepared(plan); report['pinned_inputs_unchanged'] = True
            require(threading.active_count() == 1, 'additional Python threads survived')
            names = ['ordinary/view1.bin','ordinary/states.jsonl','native-calls.jsonl',
                     'query-pairs.json','executed-inputs.json','terminal31.bin']
            if role == 'enabled':
                names += ['old-head-own-view.bin','corrected-head-own-view.bin','correction-response.bin']
            paths = [folder/name for name in names]
            require(not report.get('proof_complete') or all(p.is_file() for p in paths),
                    'completed control is missing an exact observation artifact')
            paths = [p for p in paths if p.is_file()]  # Preserve available failed-run evidence.
            report['raw_observation_sha256'] = {p.relative_to(folder).as_posix():sha(p) for p in paths}
        except BaseException as error: report['errors'].append(dict(phase='identity_cleanup',error=repr(error)))
        report['elapsed_seconds'] = time.perf_counter()-started
        report['passed'] = not report['errors'] and report.get('proof_complete') is True and report.get('session_closed') is True
        write(folder/'report.json',report)
    return 0 if report['passed'] else 1


def compare_roles(disabled, enabled):
    require(disabled['passed'] is enabled['passed'] is True and disabled['role'] == 'disabled' and enabled['role'] == 'enabled' and
        disabled['observer_enabled'] is enabled['observer_enabled'] is False and
        disabled['available_own_comparisons'] == enabled['available_own_comparisons'] == 362 and
        disabled['terminal_full_comparisons'] == enabled['terminal_full_comparisons'] == 1 and
        disabled['corrected_head_own_reference_checked'] is None and enabled['corrected_head_own_reference_checked'] is True and
        all(r['query_audit'] == dict(ordinary_own_frames=372,terminal_full_frames=1,diagnostic_queries_during_gameplay=0)
            for r in (disabled,enabled)), 'both production-like own-view controls did not pass')
    ordinary = lambda r: {p: digest for p,digest in r['raw_observation_sha256'].items() if Path(p).name.startswith('view')}
    require(ordinary(disabled) and ordinary(disabled) == ordinary(enabled), 'enabled correction query changed ordinary Make/Get bytes')
    require(disabled['raw_observation_sha256']['executed-inputs.json'] == enabled['raw_observation_sha256']['executed-inputs.json'],
            'enabled correction query changed executed native inputs')
    require(disabled['raw_observation_sha256']['terminal31.bin'] == enabled['raw_observation_sha256']['terminal31.bin'] and
            enabled['native_calls_including_cleanup'] == disabled['native_calls_including_cleanup']+2,
            'terminal original bytes or exact added Make/Get count differs')
    require(disabled['added_pair_ns'] == [] and len(enabled['added_pair_ns']) == 1 and enabled['metadata']['entries'],
            'correction query count/positive metadata differs')
    return dict(passed=True,ordinary_frame_bytes_identical=True,executed_inputs_identical=True,
        enabled_added_own_pairs=1,query_pair_ns=enabled['added_pair_ns'][0],
        disabled_repair_boundary_ns=disabled['repair_boundary_ns'], enabled_repair_boundary_ns=enabled['repair_boundary_ns'],
        metadata_request_ns=enabled['metadata_request_ns'],timing_scope='Measured owner pair includes guards/allocation/copy and verifier tracing. No diagnostic query precedes the terminal-only snapshot. One sample is not engine-only or a universal speed threshold',
        scope='Production-like own-view bytes/available components plus one terminal full parsed state; not full hidden-state equality every frame')


def prepare(args):
    output = args.output.resolve(); reference = args.reference.resolve()
    require(output.is_relative_to(ROOT/'local') and not os.path.lexists(output), 'fresh ignored output required')
    references(reference)  # File-only audit, never original native execution.
    native, heap, coop, python = [p.resolve(strict=True) for p in (args.original_dll,args.heap_helper,args.cooperative,args.python)]
    require(sha(native) == base.ORIGINAL_SHA, 'original Simulation identity differs')
    helpers = dict(heap=base.validate_helper(heap,arena=True),cooperative=base.validate_helper(coop,arena=False))
    output.mkdir(parents=True)
    sources = sorted(set(base.source_closure(ROOT,[*base.SOURCE_SEEDS,'tools/verify_prediction_correction_queries.py'])+list(base.NATIVE_SOURCES)))
    manifest = base.snapshot_files(ROOT,output/'source',sources)
    names = ['verification.json','control/bootstrap.pb','control/intent_queue/frames.bin','control/intent_queue/states.jsonl']
    names += [f'control/intent_queue/snapshots/{f:08d}.bin' for f in range(CASE['last']+1)]
    inputs = dict(reference=base.snapshot_files(reference,output/'inputs/reference',names),
        native=base.snapshot_files(native.parent,output/'inputs/native',[native.name]),
        heap=base.snapshot_files(heap.parent,output/'inputs/heap',[heap.name,'build.json']),
        cooperative=base.snapshot_files(coop.parent,output/'inputs/cooperative',[coop.name,'build.json']))
    require(native.name == 'Simulation.dll' and heap.name == 'BAHeap.dll' and coop.name == 'PredictionCooperative.dll', 'input native filenames differ')
    plan = dict(output=str(output),source_root=str(ROOT),source_sha256=manifest,input_sha256=inputs,
        input_origins=dict(reference=str(reference),native=str(native.parent),heap=str(heap.parent),cooperative=str(coop.parent)),
        python=dict(path=str(python),sha256=sha(python)),helper_receipts=helpers,timeout=args.timeout,
        native_executed=False,case_plan=CASE,scope=__doc__)
    commands = {}
    for role in ROLES:
        folder = output/role; (folder/'child').mkdir(parents=True)
        command = [str(python),'-I','-S','-B','-u','-c',
            "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.verify_prediction_correction_queries',run_name='__main__')",
            str(output/'source'),'--child','--output',str(folder),'--role',role]
        commands[role] = command; write(folder/'invocation.json',dict(plan,command=command,role=role))
    plan['commands'] = commands; write(output/'invocation.json',plan); base.verify_prepared(plan)
    return plan


def run_prepared(output):
    plan = json.loads((output/'invocation.json').read_text()); base.verify_prepared(plan)
    require(plan['case_plan'] == CASE and not (output/'verification.json').exists(), 'prepared proof changed/already attempted')
    require(os.name == 'nt', 'owned native proof requires Windows')
    inventory = subprocess.run(['powershell','-NoProfile','-Command',
        "@(Get-Process | Where-Object ProcessName -Like '*Battle*Aces*' | Select-Object Id,ProcessName,Path) | ConvertTo-Json -Compress"],
        capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    require(not inventory.stdout.strip() or inventory.stdout.strip() == '[]', 'Battle Aces process active; do not launch')
    report = dict(passed=False,native_executed=False,children=[],errors=[],invocation_sha256=sha(output/'invocation.json'))
    try:
        children = []
        for role in ROLES:
            result = base.run_prepared(output/role); report['native_executed'] = True
            report['children'].append(dict(role=role,passed=result['passed'],verification_sha256=sha(output/role/'verification.json'),
                job=result.get('job_before_close'),exit_code=result.get('exit_code'),reaped=result.get('reaped'),
                retained_handle_closed=result.get('retained_handle_closed'),forced_cleanup=result['forced_cleanup']))
            require(result['passed'] and base.parent_accepts(result), 'owned '+role+' lifecycle/proof failed')
            children.append(result['child'])
        report['comparison'] = compare_roles(*children); base.verify_prepared(plan); report['passed'] = True
    except BaseException as error: report['errors'].append(dict(error=repr(error),traceback=traceback.format_exc()))
    report['scope'] = __doc__; write(output/'verification.json',report); return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    for name in ('reference','original-dll','heap-helper','cooperative'): parser.add_argument('--'+name,type=Path)
    parser.add_argument('--python',type=Path,default=Path(sys.executable)); parser.add_argument('--timeout',type=float,default=120)
    modes = parser.add_mutually_exclusive_group(); modes.add_argument('--prepare-only',action='store_true')
    modes.add_argument('--run-prepared',action='store_true'); modes.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--role',choices=ROLES,help=argparse.SUPPRESS)
    args = parser.parse_args(argv); output = args.output.resolve()
    if args.child: return child(output,args.role)
    if args.run_prepared: return 0 if run_prepared(output)['passed'] else 1
    if any(getattr(args,n) is None for n in ('reference','original_dll','heap_helper','cooperative')):
        parser.error('--reference/--original-dll/--heap-helper/--cooperative required for file-only preparation')
    require(math.isfinite(args.timeout) and 30 <= args.timeout <= 600, 'per-child timeout outside30..600 seconds')
    plan = prepare(args); print(json.dumps(dict(prepared=True,native_executed=False,output=plan['output'])))
    return 0


if __name__ == '__main__': raise SystemExit(main())
