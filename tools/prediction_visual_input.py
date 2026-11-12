"""Opt-in stage1 original frontend ray/drag queries, never input acceptance.

Query misses/offscreen/non-discrimination remain truthful inconclusive evidence.
The paired gate additionally requires the original native/wire/visual/lifetime
result; authored records alone cannot qualify physical input or callbacks.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from tools import prediction_visual_correction as visual
from tools import prediction_correction_motion as motion


PREFIX = 'PREDICTION VISUAL INPUT '
FOCUS_PREFIX = 'VISUAL INPUT FOCUS '
FAILURE = 'Prediction visual input smoke failed:'
MAX_JOIN_AGE_US = 50_000
MAX_ROWS = 20
IDENTITY = {'entity','unit_type','army','incarnation','lease','actor','transform'}
POINTERS = {'actor','transform','selector','manager','simulation','camera_controller','camera'}
FIELDS = {'schema','event','scope','world','match','frame','entity','unit_type','army','incarnation',
    'lease','generation','revision','frontend_ordinal','sampled_us','query_end_us','joined_us','policy_us',
    'publication_us','alpha','offset','raw','displayed','actual','root_matches_join','displayed_screen',
    'raw_screen','viewport','displayed_inside','raw_inside','drag_rect_half_pixels','drag_mode','displayed_ray',
    'raw_ray','displayed_drag','raw_drag','ray_discriminates','drag_discriminates','control','physical_input',
    'selection_writes','sync_transforms','focus_ordinal','focus_frame','focus_returned_us','thread','owner_thread',*POINTERS}
FOCUS_FIELDS = {'schema','event','scope','world','match','frame','entity','unit_type','army','incarnation',
    'lease','generation','frontend_ordinal','started_us','returned_us','checked_us','joined_us','policy_us',
    'publication_us','alpha','thread','owner_thread','raw','displayed','offset','actual_before','actual_after',
    'screen_before','screen_after','viewport','method_token','method_rva','camera_calls','settle_us',
    'physical_input','selection_writes','sync_transforms',*POINTERS}


def require(value, why):
    if not value: raise AssertionError('prediction visual input: '+why)


def integer(value, low=0, high=2**64-1):
    return type(value) is int and low <= value <= high


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def pointer(value):
    return type(value) is str and re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}',value) is not None and int(value,16)%8 == 0


def validate_plan(plan):
    require('visual_input' not in plan or type(plan['visual_input']) is bool, 'option must be Boolean')
    if not plan.get('visual_input'): return
    require(plan.get('visual_correction') is True, 'requires explicit visual correction')
    visual.validate_plan(plan)


def option(args, frames, trace, delay):
    enabled = getattr(args,'visual_input',False)
    require(type(enabled) is bool, 'option must be Boolean')
    if enabled: require(visual.option(args,frames,trace,delay) is True, 'requires --visual-correction')
    return enabled


def helper(enabled, data):
    if enabled:
        require('-prediction-visual-input-smoke'.encode('utf-16-le') in data and PREFIX.encode() in data and FOCUS_PREFIX.encode() in data,
                'helper lacks explicit frontend-query diagnostic')


def _identity(row):
    require(type(row) is dict and set(row) == IDENTITY and
        all(integer(row[k],0,0xffffffff) for k in ('entity','unit_type','army')) and
        all(integer(row[k]) for k in ('incarnation','lease')) and
        all(pointer(row[k]) for k in ('actor','transform')), 'ray identity schema differs')


def _point(values, single=True):
    require(type(values) is list and len(values) == 3 and all(finite(x) for x in values), 'finite Vec3 required')
    return motion.vec(values) if single else list(values)


def focus_rows(log):
    require(type(log) is str and len(log.encode('utf-8')) <= 64*1024*1024, 'bounded focus log required')
    def unique(pairs):
        value = {}
        for key,item in pairs:
            require(key not in value, 'duplicate focus JSON field'); value[key] = item
        return value
    result = []
    for line in log.splitlines():
        if FOCUS_PREFIX not in line: continue
        raw = line.split(FOCUS_PREFIX,1)[1]; require(len(raw.encode('utf-8')) <= 8192, 'focus row exceeds byte bound')
        row = json.loads(raw,object_pairs_hook=unique)
        require(type(row) is dict and set(row) == FOCUS_FIELDS and type(row['schema']) is int and row['schema'] == 1 and
                row['event'] == 'focus_returned' and row['scope'] == 'original_camera_acquisition', 'focus schema differs')
        require(integer(row['world'],1) and type(row['match']) is str and re.fullmatch('[a-f0-9]{32}',row['match']) and
            integer(row['frame'],510,511) and all(integer(row[k],0,0xffffffff) for k in ('entity','unit_type','army')) and
            all(integer(row[k],1) for k in ('incarnation','lease','generation','frontend_ordinal','started_us','returned_us',
                'checked_us','joined_us','policy_us','publication_us')), 'focus identity/frame/clock differs')
        require(all(pointer(row[k]) for k in POINTERS) and len({row[k] for k in POINTERS}) == len(POINTERS) and
                all(integer(row[k],1,0xffffffff) for k in ('thread','owner_thread')) and row['thread'] == row['owner_thread'],
                'focus is not bound to distinct current roots and main thread')
        require(row['publication_us'] <= row['policy_us'] <= row['joined_us'] <= row['started_us'] <=
                row['returned_us'] <= row['checked_us'] and row['started_us']-row['joined_us'] <= MAX_JOIN_AGE_US,
                'focus did not follow a fresh completed join')
        require(finite(row['alpha']) and 0 <= row['alpha'] <= 1 and
                row['method_token'] == '0x060015ec' and row['method_rva'] == '0x3e9e310' and
                type(row['camera_calls']) is int and row['camera_calls'] == 1 and
                type(row['settle_us']) is int and row['settle_us'] == 200000,
                'focus original API/call count/settle differs')
        require(row['physical_input'] is row['sync_transforms'] is False and
                type(row['selection_writes']) is int and row['selection_writes'] == 0, 'focus mutated input/selection/sync')
        row['offset'] = _point(row['offset'],False)
        for key in ('raw','displayed','actual_before','actual_after','screen_before','screen_after'):
            row[key] = _point(row[key])
        require(all(x == 0 for x in row['offset']) and row['raw'] == row['displayed'] == row['actual_before'] == row['actual_after'],
                'camera acquisition changed the unit root or acquired during nonzero correction')
        require(type(row['viewport']) is list and len(row['viewport']) == 2 and all(integer(x,6,65535) for x in row['viewport']) and
                row['screen_before'][2] > 0 and row['screen_after'][2] > 0, 'focus projection/viewport differs')
        if result:
            require(row['world'] != result[-1]['world'] and row['match'] != result[-1]['match'] and
                    row['frontend_ordinal'] > result[-1]['frontend_ordinal'] and row['started_us'] > result[-1]['checked_us'] and
                    row['owner_thread'] == result[-1]['owner_thread'], 'focus world/ordinal/main-thread order differs')
        result.append(row); require(len(result) <= 2, 'more than one camera acquisition per world')
    return result


def rows(log):
    require(type(log) is str and len(log.encode('utf-8')) <= 64*1024*1024, 'bounded UTF8 log required')
    require(FAILURE not in log, 'original query producer failed')
    def unique(pairs):
        result = {}
        for key,value in pairs:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    def constant(value): raise AssertionError('prediction visual input: nonfinite JSON number '+value)
    result = []; seen = []; previous_ordinal = previous_clock = -1; current = None
    for line in log.splitlines():
        if PREFIX not in line: continue
        raw = line.split(PREFIX,1)[1]
        require(len(raw.encode('utf-8')) <= 8192, 'query row exceeds byte bound')
        row = json.loads(raw,object_pairs_hook=unique,parse_constant=constant)
        require(type(row) is dict and set(row) == FIELDS and type(row['schema']) is int and row['schema'] == 1 and
                row['event'] == 'query' and row['scope'] == 'original_frontend_queries', 'query schema differs')
        require(integer(row['world'],1) and type(row['match']) is str and re.fullmatch('[a-f0-9]{32}',row['match']) and
                integer(row['frame'],400,650) and all(integer(row[k],0,0xffffffff) for k in ('entity','unit_type','army')) and
                all(integer(row[k],1) for k in ('incarnation','lease','generation','frontend_ordinal','sampled_us',
                    'query_end_us','joined_us','policy_us','publication_us')) and integer(row['revision']),
                'query identity/clock/window differs')
        require(all(pointer(row[k]) for k in POINTERS) and len({row[k] for k in POINTERS}) == len(POINTERS),
                'nonnull distinct owner object pointers required')
        require(row['publication_us'] <= row['policy_us'] <= row['joined_us'] <= row['sampled_us'] <= row['query_end_us'] and
                row['sampled_us']-row['joined_us'] <= MAX_JOIN_AGE_US and
                row['frontend_ordinal'] > previous_ordinal and row['sampled_us'] > previous_clock,
                'query is stale, reordered or not after completed join')
        require(integer(row['focus_ordinal'],1) and row['frontend_ordinal'] > row['focus_ordinal'] and
                integer(row['focus_frame'],510,511) and row['frame'] > row['focus_frame'] and
                integer(row['focus_returned_us'],1) and row['sampled_us'] >= row['focus_returned_us'] and
                row['sampled_us']-row['focus_returned_us'] >= 200000 and
                all(integer(row[k],1,0xffffffff) for k in ('thread','owner_thread')) and row['thread'] == row['owner_thread'],
                'query precedes settled original focus or retained main thread')
        require(finite(row['alpha']) and 0 <= row['alpha'] <= 1 and
                integer(row['drag_mode'],-2**31,2**31-1) and type(row['drag_rect_half_pixels']) is int and
                row['drag_rect_half_pixels'] == 3, 'original alpha/drag-mode/rect schema differs')
        require(all(type(row[k]) is bool for k in ('root_matches_join','displayed_inside','raw_inside','displayed_drag',
            'raw_drag','ray_discriminates','drag_discriminates','physical_input','sync_transforms')) and
            row['physical_input'] is row['sync_transforms'] is False and
            type(row['selection_writes']) is int and row['selection_writes'] == 0,
            'scope contains input, writes, sync or non-Boolean results')
        row['offset'] = _point(row['offset'],False)
        for key in ('raw','displayed','actual','displayed_screen','raw_screen'): row[key] = _point(row[key])
        require(row['root_matches_join'] is True and row['actual'] == row['displayed'], 'actual root does not match completed visual join')
        require(type(row['viewport']) is list and len(row['viewport']) == 2 and
                all(integer(x,6,65535) for x in row['viewport']), 'original viewport dimensions differ')
        width,height = row['viewport']
        for name,flag in (('displayed_screen','displayed_inside'),('raw_screen','raw_inside')):
            x,y,z = row[name]; inside = x >= 3 and x <= width-3 and y >= 3 and y <= height-3
            require(z > 0 and row[flag] is inside, 'screen projection/depth/inside predicate differs')
        for name in ('displayed_ray','raw_ray'):
            ray = row[name]
            require(type(ray) is dict and set(ray) == {'hit','identity'} and type(ray['hit']) is bool,
                    'ray result schema differs')
            if ray['identity'] is not None:
                _identity(ray['identity'])
                if ray['identity']['actor'] == row['actor']:
                    require(all(ray['identity'][k] == row[k] for k in IDENTITY),
                            'same actor pointer claims another identity/lease')
            # The original bool and out Unit are independent observations.
        actor = lambda ray: None if ray['identity'] is None else ray['identity']['actor']
        expected_ray = row['displayed_ray']['hit'] != row['raw_ray']['hit'] or actor(row['displayed_ray']) != actor(row['raw_ray'])
        require(row['ray_discriminates'] is expected_ray and row['drag_discriminates'] is
                (row['displayed_drag'] != row['raw_drag']), 'discrimination flags differ from original returns')
        require(row['control'] in ('zero_before','nonzero','zero_after'), 'unknown control stage')
        magnitude = math.hypot(math.hypot(*row['offset'][:2]),row['offset'][2])
        require(math.isfinite(magnitude), 'nonfinite offset magnitude')
        if row['control'] == 'nonzero':
            require(magnitude >= .5 and row['revision'] > 0, 'nonzero offset was not acquired at0.5units')
        else:
            require(magnitude == 0 and row['raw'] == row['displayed'] and row['displayed_screen'] == row['raw_screen'],
                    'zero control is not genuinely raw-equal')
            if row['control'] == 'zero_after': require(row['frame'] >= 645, 'zero-after precedes final observer tail')
        key = row['world'],row['match']
        if key != current:
            require(key not in seen and len(seen) < 2 and all(key[0] != old[0] and key[1] != old[1] for old in seen),
                    'worlds interleaved/reused')
            seen.append(key); current = key
        previous_ordinal,previous_clock = row['frontend_ordinal'],row['query_end_us']
        result.append(row); require(len(result) <= MAX_ROWS, 'two-world query count exceeded')
    return result


def evaluate(records, visual_records, bindings, *, focus_records=None):
    require(type(bindings) is list and len(bindings) == 2 and len({b['world'] for b in bindings}) == 2 and
            len({b['match'] for b in bindings}) == 2, 'two externally bound worlds required')
    require(type(focus_records) is list and len(focus_records) == 2 and
            [(r['world'],r['match']) for r in focus_records] == [(b['world'],b['match']) for b in bindings],
            'one actual original camera focus per bound world required')
    require(all((r['world'],r['match']) in {(b['world'],b['match']) for b in bindings} for r in records),
            'unbound query world')
    worlds = []
    for binding,focus in zip(bindings,focus_records):
        require(all(focus[k] == binding[k] for k in binding), 'focus subject differs from native/FEEL binding')
        focused = [p for p in visual_records if p['event'] == 'visual_pose' and p['sampled_us'] == focus['policy_us'] and
            all(p[k] == focus[k] for k in ('world','match','frame','entity','unit_type','army','incarnation','lease'))]
        require(len(focused) == 1 and focused[0]['publication_us'] == focus['publication_us'] and
            focused[0]['alpha'] == focus['alpha'] and focused[0]['raw'] == focus['raw'] and
            focused[0]['displayed'] == focus['displayed'] and focused[0]['transform'] == focus['actual_before'],
            'focus lacks its unique original completed visual pose')
        own = [r for r in records if r['world'] == binding['world']]
        missing = []
        if not own:
            worlds.append(dict(binding=binding,passed=False,status='inconclusive',missing_gates=['no frontend queries'],records=[]))
            continue
        require(all(all(r[k] == binding[k] for k in binding) for r in own), 'query subject differs from actual native/FEEL binding')
        require(all(all(r[k] == focus[k] for k in ('lease','generation','thread','owner_thread',*POINTERS)) and
                r['focus_ordinal'] == focus['frontend_ordinal'] and r['focus_frame'] == focus['frame'] and
                r['focus_returned_us'] == focus['returned_us'] and r['policy_us'] >= focus['checked_us'] and
                r['viewport'] == focus['viewport'] for r in own), 'query does not belong to its original focus/camera owner')
        earlier = [r for r in records if r['world'] != binding['world'] and r['sampled_us'] < focus['started_us']]
        require(not earlier or max(r['frontend_ordinal'] for r in earlier) < focus['frontend_ordinal'],
                'focus ordinal interleaves another world query episode')
        stable = ('lease','generation',*sorted(POINTERS))
        require(all(len({r[k] for r in own}) == 1 for k in stable), 'current actor/transform/owner lifetime changed')
        require(all(b['frame'] > a['frame'] and b['revision'] >= a['revision'] for a,b in zip(own,own[1:])),
                'query frame/revision regressed or repeated')
        controls = [r['control'] for r in own]
        require(controls.count('zero_before') <= 1 and controls.count('zero_after') <= 1 and
                ('zero_before' not in controls or controls[0] == 'zero_before') and
                ('zero_after' not in controls or controls[-1] == 'zero_after'), 'control episode is reordered/duplicated')
        nonzero = [r for r in own if r['control'] == 'nonzero']
        require(len(nonzero) <= 8 and all(sum(r['revision'] == revision for r in nonzero) <= 2 for revision in
                {r['revision'] for r in nonzero}), 'nonzero revision/frame budget exceeded')
        for control in ('zero_before','nonzero','zero_after'):
            if control not in controls: missing.append('missing '+control)
        target = {k:own[0][k] for k in IDENTITY}
        joined = []; ray_discriminating = []; drag_discriminating = []
        for row in own:
            poses = [p for p in visual_records if p['event'] == 'visual_pose' and p['sampled_us'] == row['policy_us'] and
                     all(p[k] == row[k] for k in ('world','match','frame','entity','unit_type','army','incarnation','lease'))]
            require(len(poses) == 1, 'query lacks unique exact preceding visual policy sample')
            pose = poses[0]
            require(pose['publication_us'] == row['publication_us'] and pose['alpha'] == row['alpha'] and
                    pose['raw'] == row['raw'] and pose['displayed'] == row['displayed'] and
                    pose['transform'] == row['actual'], 'query/visual pose publication, alpha or root differs')
            visual.close(row['displayed'],motion.vec(motion.add(row['raw'],row['offset'])), 'frontend offset differs from joined display')
            ray = row['displayed_ray']; correct = ray['hit'] is True and ray['identity'] == target
            inside = row['displayed_inside'] and row['raw_inside']
            if not inside: missing.append('offscreen '+row['control'])
            if not correct: missing.append('displayed ray did not hit current subject at '+row['control'])
            if not row['displayed_drag']: missing.append('displayed drag missed current subject at '+row['control'])
            if row['control'] != 'nonzero' and (row['ray_discriminates'] or row['drag_discriminates']):
                missing.append('zero control query returns differ')
            if row['control'] == 'nonzero' and correct and row['displayed_drag'] and inside:
                if row['ray_discriminates']: ray_discriminating.append(row['frontend_ordinal'])
                if row['drag_discriminates']: drag_discriminating.append(row['frontend_ordinal'])
            joined.append(dict(frontend_ordinal=row['frontend_ordinal'],policy_us=row['policy_us'],
                joined_us=row['joined_us'],sampled_us=row['sampled_us'],query_end_us=row['query_end_us'],
                frame=row['frame'],control=row['control'],displayed_subject_hit=correct,
                query_cost_us=row['query_end_us']-row['sampled_us']))
        if not ray_discriminating: missing.append('no discriminating nonzero ray comparison')
        if not drag_discriminating: missing.append('no discriminating nonzero drag comparison')
        worlds.append(dict(binding=binding,passed=not missing,status='qualified' if not missing else 'inconclusive',
            lease=own[0]['lease'],generation=own[0]['generation'],controls=controls,nonzero_queries=len(nonzero),
            ray_discriminating_ordinals=ray_discriminating,drag_discriminating_ordinals=drag_discriminating,
            maximum_join_age_us=max(r['sampled_us']-r['joined_us'] for r in own),
            maximum_query_cost_us=max(r['query_end_us']-r['sampled_us'] for r in own),
            missing_gates=sorted(set(missing)),joins=joined,records=own,focus=focus))
    passed = all(w['passed'] for w in worlds)
    return dict(schema=1,passed=passed,component_observation_passed=passed,
        status='qualified' if passed else 'inconclusive',worlds=worlds,scope='original_frontend_queries',
        physical_input_accepted=False,callback_accepted=False,commands_accepted=False,full_feature_accepted=False,
        limitations=['Original ray and active-mode drag queries only; no gesture, callback or command execution.',
            'Query timing is measured observation cost, not a universal performance guarantee.'])


def analyze(plan, report, run):
    validate_plan(plan); require(plan.get('visual_input') is True, 'explicit input-query option missing')
    run = Path(run); inputs = {}
    def read(path):
        path = Path(path); require(path.stat().st_size <= 64*1024*1024, 'closed input exceeds bound')
        raw = path.read_bytes(); inputs[str(path)] = hashlib.sha256(raw).hexdigest(); return raw
    log_path = run/'native-0.log'; log = read(log_path).decode('utf-8')
    observed = rows(log); poses = visual.rows(log); focuses = focus_rows(log)
    peer = read(run/'native-1.log').decode('utf-8')
    require(PREFIX not in peer and FOCUS_PREFIX not in peer and FAILURE not in peer, 'unrequested peer query/focus/failure')
    bindings = [w['binding'] for w in report['native_position_trace']['worlds']]
    result = evaluate(observed,poses,bindings,focus_records=focuses)
    parent_error = None
    try:
        visual.parent_gate(plan,report)
        proof = report['visual_correction']
        require(proof['passed'] is proof['parent_gates_passed'] is True and
                [w['binding'] for w in proof['worlds']] == bindings and
                proof['input_sha256'].get(str(log_path)) == inputs[str(log_path)], 'qualified visual/log binding missing')
        for module in (visual,motion):
            require(motion.sha(module.__file__) == plan['source_sha256']['tools/'+Path(module.__file__).name],
                    'consumed join analyzer source differs')
        require(motion.sha(__file__) == plan['source_sha256']['tools/prediction_visual_input.py'], 'consumed input analyzer differs')
    except (AssertionError,KeyError,TypeError,ValueError) as error:
        parent_error = repr(error)
    require(all(motion.sha(path) == digest for path,digest in inputs.items()), 'closed query logs changed')
    result.update(parent_gates_passed=parent_error is None,parent_error=parent_error,file_only=True,input_sha256=inputs)
    result['passed'] = result['component_observation_passed'] and parent_error is None
    if parent_error is not None: result['status'] = 'parent_unqualified'
    return result


def _saved_focus(world):
    focus = world['focus']; require(focus_rows(FOCUS_PREFIX+json.dumps(focus)) == [focus], 'persisted focus is malformed')
    require(all(focus[k] == world['binding'][k] for k in world['binding']) and
            focus['lease'] == world['lease'] and focus['generation'] == world['generation'] and world['records'],
            'persisted focus/world binding differs')
    require(all(row['focus_ordinal'] == focus['frontend_ordinal'] and row['focus_frame'] == focus['frame'] and
            row['focus_returned_us'] == focus['returned_us'] and row['sampled_us']-focus['returned_us'] >= 200000 and
            all(row[k] == focus[k] for k in ('lease','generation','thread','owner_thread',*POINTERS)) for row in world['records']),
            'persisted queries lost original focus ownership')
    return True


def gate(plan, report):
    if not plan.get('visual_input'): return True
    try:
        validate_plan(plan); visual.parent_gate(plan,report)
        proof = report['visual_input']
        return bool(proof['passed'] is proof['component_observation_passed'] is proof['parent_gates_passed'] is True and
            proof['status'] == 'qualified' and proof['scope'] == 'original_frontend_queries' and
            len(proof['worlds']) == 2 and all(w['passed'] is True and not w['missing_gates'] and
                w['ray_discriminating_ordinals'] and w['drag_discriminating_ordinals'] and _saved_focus(w) for w in proof['worlds']) and
            [w['binding'] for w in proof['worlds']] == [w['binding'] for w in report['visual_correction']['worlds']] and
            report['visual_correction']['passed'] is True and proof['physical_input_accepted'] is
                proof['callback_accepted'] is proof['commands_accepted'] is proof['full_feature_accepted'] is False)
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError): return False


def finalize(plan, report, run):
    if not plan.get('visual_input'): return
    parent = report.get('passed') is True
    try: report['visual_input'] = analyze(plan,report,run)
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OSError,OverflowError) as error:
        proof = dict(passed=False,component_observation_passed=False,parent_gates_passed=False,status='unqualified',
            error=repr(error),scope='original_frontend_queries',physical_input_accepted=False,full_feature_accepted=False)
        try: proof['preserved_observations'] = rows((Path(run)/'native-0.log').read_text(encoding='utf-8'))
        except (AssertionError,ValueError,OSError,KeyError,TypeError) as parse_error: proof['observation_error'] = repr(parse_error)
        try: proof['preserved_focus'] = focus_rows((Path(run)/'native-0.log').read_text(encoding='utf-8'))
        except (AssertionError,ValueError,OSError,KeyError,TypeError) as parse_error: proof['focus_error'] = repr(parse_error)
        report['visual_input'] = proof
    report['visual_input_witness_passed'] = report['visual_input'].get('passed') is True
    report['passed'] = parent and report['visual_input_witness_passed']
