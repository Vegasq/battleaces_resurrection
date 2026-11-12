"""Optional matched-point/phase attribution, never a replacement acceptance gate."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import struct

from tools import prediction_visual_click as click
from tools import prediction_visual_input as queries
from tools import prediction_visual_correction as visual
from tools import prediction_correction_motion as motion

PREFIX = 'VISUAL AIM '
MARKER = b'BA_RESURRECTION_VISUAL_AIM_V1'
PHASES = ('down_before','process_before','process_returned')
KINDS = ('consumed','displayed_root','raw_root','matched_raw')
EXTRA = {'phase','ticket_serial','down_method_info','context_pointer','sample_end_us','root_screen','raw_root_screen',
         'relative_offset','points','point_bits','relative_offset_bits','viewport','queries','unchanged'}
FIELDS = click.COMMON|EXTRA
QUERY = {'point_kind','begin_us','end_us','point','inside','hit','identity'}
PRODUCERS = (*click.PRODUCERS,'client_patch/src/prediction_visual_click_protocol.hpp')


def require(value, why):
    if not value: raise AssertionError('prediction visual aim: '+why)


def validate_plan(plan):
    require('visual_click_spatial' not in plan or type(plan['visual_click_spatial']) is bool, 'option must be Boolean')
    if not plan.get('visual_click_spatial'): return
    require(plan.get('visual_click') is True and plan.get('visual_input') is True and
            plan.get('visual_correction') is True, 'requires click, input and visual correction')
    click.validate_plan(plan)


def option(args, frames, trace, delay):
    enabled = getattr(args,'visual_click_spatial',False)
    require(type(enabled) is bool, 'option must be Boolean')
    if enabled: require(click.option(args,frames,trace,delay) is True, 'requires --visual-click')
    return enabled


def helper(enabled, data):
    if enabled:
        require(MARKER in data and PREFIX.encode() in data and
                '-prediction-visual-click-spatial'.encode('utf-16-le') in data, 'helper lacks spatial attribution marker/flag')


def bits(point):
    return list(struct.unpack('<II',struct.pack('<ff',*point)))


def single(value):
    return struct.unpack('<f',struct.pack('<f',value))[0]


def _bits(value):
    require(type(value) is list and len(value) == 2 and all(queries.integer(v,0,0xffffffff) for v in value), 'Single bit pair required')


def _same_result(a,b):
    # Bool and out-object remain independent original return values.
    return a['hit'] == b['hit'] and a['identity'] == b['identity']


def _common(row):
    require(type(row['schema']) is int and row['schema'] == 1 and row['event'] == 'probe' and
            queries.integer(row['world'],1) and type(row['match']) is str and re.fullmatch('[a-f0-9]{32}',row['match']) and
            queries.integer(row['episode'],1,2) and row['control'] == ('zero' if row['episode'] == 1 else 'nonzero') and
            queries.integer(row['frontend_ordinal'],1) and queries.integer(row['sampled_us'],1) and
            queries.integer(row['frame'],400,650) and
            all(queries.integer(row[k],0,0xffffffff) for k in ('entity','unit_type','army')) and
            all(queries.integer(row[k],1) for k in ('incarnation','lease','generation','focus_ordinal','focus_returned_us')),
            'probe world/identity/clock differs')
    require(all(queries.pointer(row[k]) for k in click.POINTERS) and len({row[k] for k in click.POINTERS}) == len(click.POINTERS) and
            all(queries.integer(row[k],1,0xffffffff) for k in ('thread','owner_thread')) and row['thread'] == row['owner_thread'],
            'probe roots or retained main thread differ')
    require(queries.integer(row['pending_commands'],0,4) and row['physical_input'] is row['sync_transforms'] is False and
            type(row['selection_writes']) is int and row['selection_writes'] == 0 and
            type(row['history_writes']) is int and row['history_writes'] == 0, 'probe mutated input/selection/history/synchronization')
    for name in ('current_ids','preview_ids','casting_ids'): click.ids(row[name])
    for name in ('pointer','queued_point'): row[name] = click.point2(row[name])
    h = row['history']
    require(type(h) is dict and set(h) == click.HISTORY and queries.integer(h['id'],0,0xffffffff) and
            queries.integer(h['mode'],-2**31,2**31-1) and all(type(h[k]) is bool for k in ('primary','context','drag')) and
            all(queries.finite(h[k]) and h[k] >= 0 for k in ('now','last_up','window')), 'original gesture schema differs')
    h['now'],h['last_up'],h['window'] = motion.vec([h['now'],h['last_up'],h['window']])
    require(h['now'] >= h['last_up'], 'original gesture clock regressed')
    mouse = row['mouse']
    require(type(mouse) is dict and set(mouse) == click.MOUSE and
            all(queries.pointer(mouse[k]) for k in ('action','control','device')) and
            len({mouse[k] for k in ('action','control','device')}) == 3 and queries.integer(mouse['queued_sequence'],1,3) and
            all(type(mouse[k]) is bool for k in ('primary','context')), 'bound Mouse schema differs')
    p = row['pose']
    require(type(p) is dict and set(p) == click.POSE and p['frame'] == row['frame'] and
            queries.integer(p['frame'],400,650) and queries.integer(p['revision']) and
            all(queries.integer(p[k],1) for k in ('joined_us','policy_us','publication_us')) and
            p['publication_us'] <= p['policy_us'] <= p['joined_us'] <= row['sampled_us'] and
            row['sampled_us']-p['joined_us'] <= queries.MAX_JOIN_AGE_US and
            queries.finite(p['alpha']) and 0 <= p['alpha'] <= 1 and p['root_matches_join'] is True,
            'probe lacks fresh completed visual join')
    for name in ('raw','displayed','actual'): p[name] = motion.vec(p[name])
    require(type(p['offset']) is list and len(p['offset']) == 3 and all(queries.finite(v) for v in p['offset']) and
            p['actual'] == p['displayed'], 'probe root/offset differs')
    visual.close(p['displayed'],motion.vec(motion.add(p['raw'],p['offset'])), 'probe offset differs from display')
    require(row['sampled_us']-row['focus_returned_us'] >= 200000, 'probe precedes settled original camera')
    if row['control'] == 'zero': require(all(v == 0 for v in p['offset']) and p['raw'] == p['displayed'], 'zero probe is not raw-equal')


def rows(log):
    require(type(log) is str and len(log.encode('utf-8')) <= 64*1024*1024, 'bounded closed log required')
    require(click.FAILURE not in log, 'original click/aim producer failed')
    def unique(pairs):
        value = {}
        for key,item in pairs:
            require(key not in value, 'duplicate JSON field'); value[key] = item
        return value
    def constant(value): raise AssertionError('prediction visual aim: nonfinite JSON '+value)
    result = []; worlds = []; current = None; sequence = 0; ordinal = 0; clock = 0
    for line in log.splitlines():
        if PREFIX not in line: continue
        raw = line.split(PREFIX,1)[1]; require(len(raw.encode('utf-8')) <= 16384, 'aim record exceeds bound')
        row = json.loads(raw,object_pairs_hook=unique,parse_constant=constant)
        require(type(row) is dict and set(row) == FIELDS, 'probe schema differs')
        _common(row)
        key = row['world'],row['match']
        if key != current:
            require(key not in worlds and len(worlds) < 2 and all(key[0] != k[0] and key[1] != k[1] for k in worlds),
                    'probe worlds interleaved/reused')
            worlds.append(key);current=key;sequence=0
        require(queries.integer(row['sequence'],1,6) and row['sequence'] == sequence+1 and
                row['frontend_ordinal'] >= ordinal and row['sampled_us'] >= clock and row['phase'] in PHASES,
                'probe phase/sequence/frontend order differs')
        require(queries.integer(row['ticket_serial'],1) and queries.pointer(row['down_method_info']) and
                queries.pointer(row['context_pointer']) and queries.integer(row['sample_end_us'],row['sampled_us']) and
                row['unchanged'] is True, 'probe original Down/readonly stability missing')
        row['root_screen'] = motion.vec(row['root_screen']);row['raw_root_screen'] = motion.vec(row['raw_root_screen'])
        require(row['root_screen'][2] > 0 and row['raw_root_screen'][2] > 0, 'projected roots behind original camera')
        require(type(row['points']) is dict and set(row['points']) == set(KINDS) and
                type(row['point_bits']) is dict and set(row['point_bits']) == set(KINDS), 'four-point schema differs')
        for kind in KINDS:
            row['points'][kind] = click.point2(row['points'][kind]);_bits(row['point_bits'][kind])
            require(bits(row['points'][kind]) == row['point_bits'][kind], 'point decimal/Single bits differ')
        row['relative_offset'] = click.point2(row['relative_offset']);_bits(row['relative_offset_bits'])
        require(bits(row['relative_offset']) == row['relative_offset_bits'], 'relative offset bits differ')
        p,q,r,m = (row['points'][kind] for kind in KINDS)
        delta = [single(a-b) for a,b in zip(p,q)]
        matched = [single(a+b) for a,b in zip(r,delta)]
        require(bits(p) == bits(row['pointer']) == bits(row['queued_point']) and
                bits(q) == bits(row['root_screen'][:2]) and bits(r) == bits(row['raw_root_screen'][:2]) and
                bits(delta) == row['relative_offset_bits'] and bits(matched) == row['point_bits']['matched_raw'],
                'four-point separate Single subtract/add arithmetic differs')
        require(type(row['viewport']) is list and len(row['viewport']) == 2 and
                all(queries.integer(v,6,65535) for v in row['viewport']) and type(row['queries']) is list and
                len(row['queries']) == 4, 'original viewport/query count differs')
        last = row['sampled_us'];width,height = row['viewport']
        for kind,query in zip(KINDS,row['queries']):
            require(type(query) is dict and set(query) == QUERY and query['point_kind'] == kind and
                    queries.integer(query['begin_us'],last) and queries.integer(query['end_us'],query['begin_us']) and
                    query['end_us'] <= row['sample_end_us'] and type(query['inside']) is bool, 'query order/clock/schema differs')
            query['point'] = click.point2(query['point']);x,y = query['point']
            require(bits(query['point']) == row['point_bits'][kind] and
                    query['inside'] is (3 <= x <= width-3 and 3 <= y <= height-3), 'queried point/viewport predicate differs')
            click._ray(dict(hit=query['hit'],identity=query['identity']))
            last = query['end_us']
        result.append(row);require(len(result) <= 12, 'two-world three-phase probe bound exceeded')
        sequence,ordinal,clock = row['sequence'],row['frontend_ordinal'],row['sample_end_us']
    return result


def evaluate(records, click_records, visual_records, bindings, *, focus_records):
    # Reuse the complete genuine-callback/cleanup contract, independent of its
    # overall parent result. A Stage1 failure must remain a parent failure.
    clicks = click.evaluate(click_records,visual_records,bindings,focus_records=focus_records)
    require(clicks['component_observation_passed'], 'original callback/close observations incomplete')
    require(all((r['world'],r['match']) in {(b['world'],b['match']) for b in bindings} for r in records), 'unbound probe world')
    worlds = []
    common = click.COMMON-{'event','sequence'}
    for binding in bindings:
        own = [r for r in records if r['world'] == binding['world']]
        episodes = [];missing = []
        for number in (1,2):
            phase_rows = [r for r in own if r['episode'] == number]
            if len(phase_rows) != 3:
                missing.append('incomplete three-phase '+('zero' if number == 1 else 'nonzero')+' probe')
                continue
            require([r['phase'] for r in phase_rows] == list(PHASES), 'probe phases reordered/duplicated')
            original = [r for r in click_records if r['world'] == binding['world'] and r['episode'] == number]
            anchor = next(r for r in original if r['event'] == 'position_queued')
            down = next(r for r in original if r['event'] == 'callback_before' and r['kind'] == 'Down')
            for row,phase in zip(phase_rows,PHASES):
                event = 'callback_before' if phase == 'down_before' else phase
                candidates = [r for r in original if r['event'] == event and
                              (event != 'callback_before' or r.get('kind') == 'Down')]
                require(len(candidates) == 1 and all(row[k] == candidates[0][k] for k in common),
                        'probe lacks exact corresponding original callback Sample')
                require(row['ticket_serial'] == down['ticket_serial'] and row['down_method_info'] == down['method_info'] and
                        row['context_pointer'] == down['context_pointer'] and
                        row['point_bits']['consumed'] == bits(anchor['queued_point']), 'probe is not bound to the original consumed Down')
            first = phase_rows[0]
            down_return = next(r for r in original if r['event'] == 'callback_returned' and r['kind'] == 'Down')
            require(phase_rows[-1]['sample_end_us'] <= down_return['sampled_us'],
                    'spatial queries extend beyond original Down return')
            require(all(r['pose'] == first['pose'] and r['camera'] == first['camera'] and r['viewport'] == first['viewport'] and
                        r['root_screen'] == first['root_screen'] and r['raw_root_screen'] == first['raw_root_screen'] and
                        r['point_bits'] == first['point_bits'] and r['relative_offset_bits'] == first['relative_offset_bits']
                        for r in phase_rows), 'phase comparison changed frozen points/projection/join')
            spatial = []
            for row in phase_rows:
                results = dict(zip(KINDS,row['queries']))
                spatial.append(dict(phase=row['phase'],sampled_us=row['sampled_us'],sample_end_us=row['sample_end_us'],
                    consumed_vs_root_different=not _same_result(results['consumed'],results['displayed_root']),
                    consumed_vs_matched_raw_different=not _same_result(results['consumed'],results['matched_raw']),
                    displayed_vs_raw_root_different=not _same_result(results['displayed_root'],results['raw_root']),
                    relative_aim_pixels=math.hypot(*row['relative_offset']),results=row['queries']))
            phase_changes = []
            for left,right in ((0,1),(1,2),(0,2)):
                a,b = phase_rows[left],phase_rows[right]
                phase_changes.append(dict(from_phase=a['phase'],to_phase=b['phase'],same_points=True,same_join=True,
                    changed_point_kinds=[kind for kind,qa,qb in zip(KINDS,a['queries'],b['queries']) if not _same_result(qa,qb)],
                    from_history=a['history'],to_history=b['history']))
            episodes.append(dict(episode=number,control=first['control'],ticket_serial=first['ticket_serial'],
                frame=first['frame'],revision=first['pose']['revision'],policy_us=first['pose']['policy_us'],
                points=first['points'],point_bits=first['point_bits'],relative_offset=first['relative_offset'],
                relative_offset_bits=first['relative_offset_bits'],spatial_comparisons=spatial,phase_comparisons=phase_changes,
                records=phase_rows,protocol_valid=True))
        require([r['episode'] for r in own] == sorted(r['episode'] for r in own), 'probe episodes interleaved')
        worlds.append(dict(binding=binding,protocol_valid=not missing,missing_gates=missing,episodes=episodes,records=own))
    valid = len(worlds) == 2 and all(w['protocol_valid'] for w in worlds)
    return dict(schema=1,passed=valid,protocol_valid=valid,component_observation_passed=valid,
        status='observed' if valid else 'incomplete',scope='matched_original_ray_spatial_phase_attribution',worlds=worlds,
        physical_input_accepted=False,full_feature_accepted=False,old_stage1_promoted=False,
        limitations=['All original hit Booleans and out-identities are retained independently; misses do not invalidate attribution.',
            'Differences describe these exact points and phases; no physics synchronization, collider-shape or exclusive cause is inferred.',
            'Protocol-valid observations do not replace original Stage1/native/wire/visual/callback/lifetime acceptance.'])


def analyze(plan, report, run):
    validate_plan(plan);require(plan.get('visual_click_spatial') is True, 'explicit spatial option missing')
    run = Path(run);inputs = {}
    def read(path):
        require(path.stat().st_size <= 64*1024*1024, 'closed input exceeds bound')
        raw = path.read_bytes();inputs[str(path)] = hashlib.sha256(raw).hexdigest();return raw
    log = read(run/'native-0.log').decode('utf-8');peer = read(run/'native-1.log').decode('utf-8')
    require(PREFIX not in peer, 'unrequested peer spatial probe')
    observed = rows(log);callbacks = click.rows(log);poses = visual.rows(log);focus = queries.focus_rows(log)
    bindings = [w['binding'] for w in report['native_position_trace']['worlds']]
    result = evaluate(observed,callbacks,poses,bindings,focus_records=focus)
    require(report['visual_click']['component_observation_passed'] is True and
            callbacks == [r for w in report['visual_click']['worlds'] for r in w['records']] and
            inputs == report['visual_click']['input_sha256'], 'qualified original callback/log binding missing')
    producers = {}
    for name in PRODUCERS:
        path = run.parent/'source-at-prepare'/name
        require(path.stat().st_size <= 256*1024, 'producer snapshot exceeds bound')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        require(digest == plan['source_sha256'][name], 'consumed original probe producer differs')
        producers[name] = digest
    for module in (click,queries,visual,motion):
        require(motion.sha(module.__file__) == plan['source_sha256']['tools/'+Path(module.__file__).name], 'consumed join analyzer differs')
    require(motion.sha(__file__) == plan['source_sha256']['tools/prediction_visual_aim.py'], 'consumed aim analyzer differs')
    parent_error = None
    try:
        require(report.get('passed') is True and click.gate(plan,report), 'unchanged original acceptance parents remain unqualified')
    except (AssertionError,KeyError,TypeError,ValueError) as error: parent_error = repr(error)
    require(all(motion.sha(path) == digest for path,digest in inputs.items()), 'closed probe logs changed')
    result.update(file_only=True,input_sha256=inputs,producer_sha256=producers,parent_gates_passed=parent_error is None,
                  parent_error=parent_error)
    result['passed'] = result['protocol_valid'] and parent_error is None
    if parent_error is not None: result['status'] = 'parent_unqualified'
    return result


def gate(plan, report):
    if not plan.get('visual_click_spatial'): return True
    try:
        validate_plan(plan);require(report.get('passed') is True and click.gate(plan,report), 'original parents failed')
        proof = report['visual_click_spatial']
        require(proof['passed'] is proof['protocol_valid'] is proof['component_observation_passed'] is proof['parent_gates_passed'] is True and
                proof['status'] == 'observed' and proof['scope'] == 'matched_original_ray_spatial_phase_attribution' and
                proof['old_stage1_promoted'] is False and
                proof['physical_input_accepted'] is proof['full_feature_accepted'] is False and
                proof['input_sha256'] == report['visual_click']['input_sha256'] and
                proof['producer_sha256'] == {k:plan['source_sha256'][k] for k in PRODUCERS}, 'saved attribution parent/source binding differs')
        records = rows('\n'.join(PREFIX+json.dumps(r) for w in proof['worlds'] for r in w['records']))
        old = report['visual_click']
        callbacks = click.rows('\n'.join(click.PREFIX+json.dumps(r) for w in old['worlds'] for r in w['records']))
        poses = visual.rows('\n'.join(visual.PREFIX+json.dumps(r) for r in old['joined_visual_poses']))
        focus = queries.focus_rows('\n'.join(queries.FOCUS_PREFIX+json.dumps(r) for r in old['focus_records']))
        rebuilt = evaluate(records,callbacks,poses,[w['binding'] for w in old['worlds']],focus_records=focus)
        require(rebuilt['protocol_valid'] and rebuilt['worlds'] == proof['worlds'], 'saved spatial/phase coverage or summary differs')
        return True
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError): return False


def finalize(plan, report, run):
    if not plan.get('visual_click_spatial'): return
    parent = report.get('passed') is True
    try: report['visual_click_spatial'] = analyze(plan,report,run)
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OSError,OverflowError) as error:
        proof = dict(passed=False,protocol_valid=False,component_observation_passed=False,parent_gates_passed=False,
            status='unqualified',error=repr(error),scope='matched_original_ray_spatial_phase_attribution',
            physical_input_accepted=False,full_feature_accepted=False,old_stage1_promoted=False)
        try: proof['preserved_observations'] = rows((Path(run)/'native-0.log').read_text(encoding='utf-8'))
        except (AssertionError,KeyError,TypeError,ValueError,OSError) as parse_error: proof['observation_error'] = repr(parse_error)
        report['visual_click_spatial'] = proof
    proof = report['visual_click_spatial']
    report['visual_click_spatial_observation_valid'] = proof.get('protocol_valid') is True
    report['visual_click_spatial_witness_passed'] = proof.get('passed') is True
    report['passed'] = parent and report['visual_click_spatial_witness_passed'] and gate(plan,report)
