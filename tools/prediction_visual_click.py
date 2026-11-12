"""Opt-in genuine programmatic primary callbacks during visual correction.

Queued events alone are not delivery. Original callback/selection/cleanup proofs
remain separate from physical input, commands, Internet feel and full acceptance.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import struct

from tools import prediction_visual_input as queries
from tools import prediction_visual_correction as visual
from tools import prediction_correction_motion as motion

PREFIX = 'VISUAL CLICK '
FAILURE = 'Prediction visual click smoke failed:'
MARKER = b'BA_RESURRECTION_VISUAL_CLICK_SMOKE_V1'
POINTERS = {'selector','manager','simulation','actor','transform','camera'}
COMMON = {'schema','event','world','match','episode','control','sequence','frontend_ordinal','sampled_us',
    'frame','entity','unit_type','army','incarnation','lease','generation','thread','owner_thread',*POINTERS,
    'focus_ordinal','focus_returned_us','pending_commands','current_ids','preview_ids','casting_ids',
    'pointer','queued_point','history','mouse','pose','physical_input','selection_writes','history_writes','sync_transforms'}
CALLBACK = {'kind','ticket_serial','ledger_serial','ledger_completed','single_accepted','method_info',
            'dispatch_thunk','method_token','method_rva','context_pointer'}
PROCESS = {'ticket_serial','down_method_info','method_info','method_rva','original_entry','context_pointer'}
POSE = {'frame','revision','joined_us','policy_us','publication_us','alpha','raw','displayed','offset','actual','root_matches_join'}
HISTORY = {'id','mode','primary','context','drag','now','last_up','window'}
MOUSE = {'action','control','device','queued_sequence','primary','context'}
HIT = {'point','raw_point','viewport','inside','raw_inside','displayed','raw','discriminates'}
EVENTS = ('position_queued','down_queued','callback_before','process_before','process_returned','callback_returned',
          'up_queued','callback_before','callback_returned','closed')
METHODS = {'Down':('0x06002266','0x3bf7d20'), 'Up':('0x06002267','0x3bf7f60')}
MAX_ROWS = 40
PRODUCERS = ('client_patch/src/prediction_visual_click_smoke.hpp',
             'client_patch/src/prediction_input_observer.cpp',
             'client_patch/src/prediction_selection.cpp','client_patch/src/prediction_virtual_mouse_smoke.hpp')


def require(value, why):
    if not value: raise AssertionError('prediction visual click: '+why)


def validate_plan(plan):
    require('visual_click' not in plan or type(plan['visual_click']) is bool, 'option must be Boolean')
    if not plan.get('visual_click'): return
    require(plan.get('visual_input') is True and plan.get('visual_correction') is True,
            'requires explicit visual input and visual correction')
    queries.validate_plan(plan)


def option(args, frames, trace, delay):
    enabled = getattr(args,'visual_click',False)
    require(type(enabled) is bool, 'option must be Boolean')
    if enabled:
        require(getattr(args,'visual_input',False) is True and
                queries.option(args,frames,trace,delay) is True, 'requires --visual-input and --visual-correction')
    return enabled


def helper(enabled, data):
    if enabled:
        require(MARKER in data and PREFIX.encode() in data and
                '-prediction-visual-click-smoke'.encode('utf-16-le') in data,
                'helper lacks explicit click diagnostic marker/flag')


def point2(value):
    require(type(value) is list and len(value) == 2 and all(queries.finite(v) for v in value), 'finite Single point required')
    return motion.vec([*value,0])[:2]


def ids(value):
    require(type(value) is list and len(value) <= 65536 and
            all(queries.integer(v,0,0xfffffffe) for v in value) and len(set(value)) == len(value), 'numeric ID set differs')


def _ray(value):
    require(type(value) is dict and set(value) == {'hit','identity'} and type(value['hit']) is bool, 'original ray schema differs')
    if value['identity'] is not None: queries._identity(value['identity'])


def _hit(value):
    require(type(value) is dict and set(value) == HIT and
            all(type(value[k]) is bool for k in ('inside','raw_inside','discriminates')), 'callback hit-test schema differs')
    value['point'] = point2(value['point']); value['raw_point'] = point2(value['raw_point'])
    require(type(value['viewport']) is list and len(value['viewport']) == 2 and
            all(queries.integer(v,6,65535) for v in value['viewport']), 'callback viewport differs')
    width,height = value['viewport']
    for key,flag in (('point','inside'),('raw_point','raw_inside')):
        x,y = value[key]
        require(value[flag] is (3 <= x <= width-3 and 3 <= y <= height-3), 'callback viewport predicate differs')
    _ray(value['displayed']); _ray(value['raw'])
    actor = lambda ray: None if ray['identity'] is None else ray['identity']['actor']
    require(value['discriminates'] is (value['displayed']['hit'] != value['raw']['hit'] or
            actor(value['displayed']) != actor(value['raw'])), 'callback ray discrimination is fabricated')


def rows(log, *, contract='legacy_two_episode'):
    require(contract in ('legacy_two_episode','first_nonzero','first_nonzero_preposition'), 'unknown explicit callback-record contract')
    first_nonzero=contract=='first_nonzero'
    preposition=contract=='first_nonzero_preposition'
    prefix='VISUAL PREPOSITION ' if preposition else 'VISUAL ACQUIRE ' if first_nonzero else PREFIX
    require(type(log) is str and len(log.encode('utf-8')) <= 64*1024*1024, 'bounded closed log required')
    require(FAILURE not in log, 'original click producer failed')
    def unique(pairs):
        value = {}
        for key,item in pairs:
            require(key not in value, 'duplicate JSON field'); value[key] = item
        return value
    def constant(value): raise AssertionError('prediction visual click: nonfinite JSON '+value)
    result = []; worlds = []; current = None; sequence = 0; ordinal = 0; clock = 0
    for line in log.splitlines():
        if prefix not in line: continue
        raw = line.split(prefix,1)[1]
        require(len(raw.encode('utf-8')) <= 16384, 'click row exceeds byte bound')
        row = json.loads(raw,object_pairs_hook=unique,parse_constant=constant)
        require(type(row) is dict and row.get('event') in ({'queued','consumed'} if preposition else set(EVENTS)), 'unknown click event')
        extra = {'viewport','queued_us','queued_ordinal','primary_callback_count','roots_retained'} if preposition else set()
        if row['event'].startswith('callback_'):
            extra |= CALLBACK
            if row.get('kind') == 'Down' and row['event'] == 'callback_before': extra.add('hit_test')
        if row['event'].startswith('process_'): extra |= PROCESS
        if row['event'] == 'closed': extra |= {'roots_before','roots_after','balanced'}
        require(set(row) == COMMON|extra and type(row['schema']) is int and row['schema'] == 1, 'click schema differs')
        require(queries.integer(row['world'],1) and type(row['match']) is str and re.fullmatch('[a-f0-9]{32}',row['match']) and
                (type(row['episode']) is int and row['episode']==0 and row['control']=='neutral' if preposition else
                 type(row['episode']) is int and row['episode']==1 and row['control']=='nonzero' if first_nonzero else
                 queries.integer(row['episode'],1,2) and row['control'] == ('zero' if row['episode'] == 1 else 'nonzero')) and
                queries.integer(row['sequence'],1,2 if preposition else 10 if first_nonzero else 20) and queries.integer(row['frontend_ordinal'],1) and
                queries.integer(row['sampled_us'],1) and queries.integer(row['frame'],400,650) and
                all(queries.integer(row[k],0,0xffffffff) for k in ('entity','unit_type','army')) and
                all(queries.integer(row[k],1) for k in ('incarnation','lease','generation','focus_ordinal','focus_returned_us')),
                'click world/episode/identity/clock differs')
        key = row['world'],row['match']
        if key != current:
            require(key not in worlds and len(worlds) < 2 and
                    all(key[0] != old[0] and key[1] != old[1] for old in worlds), 'click worlds interleaved/reused')
            worlds.append(key); current = key; sequence = 0
        require(row['sequence'] == sequence+1 and row['frontend_ordinal'] >= ordinal and row['sampled_us'] >= clock,
                'click sequence/frontend/clock regressed')
        sequence,ordinal,clock = row['sequence'],row['frontend_ordinal'],row['sampled_us']
        require(all(queries.pointer(row[k]) for k in POINTERS) and len({row[k] for k in POINTERS}) == len(POINTERS) and
                all(queries.integer(row[k],1,0xffffffff) for k in ('thread','owner_thread')) and row['thread'] == row['owner_thread'],
                'click current roots/main thread differ')
        require(queries.integer(row['pending_commands'],0,4) and row['physical_input'] is row['sync_transforms'] is False and
                type(row['selection_writes']) is int and row['selection_writes'] == 0 and
                type(row['history_writes']) is int and row['history_writes'] == 0, 'click has manual writes or unsupported scope')
        for name in ('current_ids','preview_ids','casting_ids'): ids(row[name])
        row['pointer'] = point2(row['pointer']); row['queued_point'] = point2(row['queued_point'])
        history = row['history']
        require(type(history) is dict and set(history) == HISTORY and queries.integer(history['id'],0,0xffffffff) and
                queries.integer(history['mode'],-2**31,2**31-1) and
                all(type(history[k]) is bool for k in ('primary','context','drag')) and
                all(queries.finite(history[k]) and history[k] >= 0 for k in ('now','last_up','window')),
                'original selector history schema differs')
        history['now'],history['last_up'],history['window'] = motion.vec([history['now'],history['last_up'],history['window']])
        require(history['now'] >= history['last_up'], 'original Single clock regressed')
        mouse = row['mouse']
        require(type(mouse) is dict and set(mouse) == MOUSE and all(queries.pointer(mouse[k]) for k in ('action','control','device')) and
                len({mouse[k] for k in ('action','control','device')}) == 3 and queries.integer(mouse['queued_sequence'],1,1 if preposition else 4 if first_nonzero else 3) and
                all(type(mouse[k]) is bool for k in ('primary','context')), 'bound original Mouse schema differs')
        pose = row['pose']
        require(type(pose) is dict and set(pose) == POSE and queries.integer(pose['frame'],400,650) and pose['frame'] == row['frame'] and
                queries.integer(pose['revision']) and all(queries.integer(pose[k],1) for k in ('joined_us','policy_us','publication_us')) and
                pose['publication_us'] <= pose['policy_us'] <= pose['joined_us'] <= row['sampled_us'] and
                row['sampled_us']-pose['joined_us'] <= queries.MAX_JOIN_AGE_US and queries.finite(pose['alpha']) and
                0 <= pose['alpha'] <= 1 and pose['root_matches_join'] is True, 'callback pose lacks fresh completed join')
        for name in ('raw','displayed','actual'): pose[name] = motion.vec(pose[name])
        require(type(pose['offset']) is list and len(pose['offset']) == 3 and all(queries.finite(v) for v in pose['offset']), 'finite offset required')
        require(pose['actual'] == pose['displayed'], 'callback root differs from joined display')
        visual.close(pose['displayed'],motion.vec(motion.add(pose['raw'],pose['offset'])), 'click offset differs from actual display')
        if row['control'] == 'zero': require(all(v == 0 for v in pose['offset']) and pose['raw'] == pose['displayed'], 'zero episode has correction')
        if preposition:
            require(type(row['viewport']) is list and len(row['viewport'])==2 and
                    all(queries.integer(v,7,65535) for v in row['viewport']) and
                    queries.integer(row['queued_us'],1,row['sampled_us']) and
                    queries.integer(row['queued_ordinal'],1,row['frontend_ordinal']) and
                    type(row['primary_callback_count']) is int and row['primary_callback_count']==0 and
                    type(row['roots_retained']) is int and row['roots_retained']==15,
                    'neutral position queue/callback/root schema differs')
        if row['event'].startswith('callback_'):
            require(row['kind'] in METHODS and (row['method_token'],row['method_rva']) == METHODS[row['kind']] and
                    all(queries.pointer(row[k]) for k in ('method_info','dispatch_thunk','context_pointer')) and
                    queries.integer(row['ticket_serial'],1) and queries.integer(row['ledger_serial']) and
                    type(row['single_accepted']) is bool, 'original callback method/context/ticket differs')
            require(row['ledger_completed'] is None if row['event'] == 'callback_before' else type(row['ledger_completed']) is bool,
                    'callback return is missing or fabricated')
            if 'hit_test' in row: _hit(row['hit_test'])
        if row['event'].startswith('process_'):
            require(queries.integer(row['ticket_serial'],1) and row['method_info'] == '0x0' and
                    row['method_rva'] == '0x3bf4a60' and
                    all(queries.pointer(row[k]) for k in ('down_method_info','original_entry','context_pointer')),
                    'nested original ProcessClick ABI differs')
        if row['event'] == 'closed':
            require(type(row['roots_before']) is int and row['roots_before'] == 15 and
                    type(row['roots_after']) is int and row['roots_after'] == 0 and row['balanced'] is True,
                    'bound Mouse roots or release balance survived close')
        result.append(row); require(len(result) <= (4 if preposition else 20 if first_nonzero else MAX_ROWS), 'click row budget exceeded')
    return result


def _join(row, poses, binding, focus):
    require(all(row[k] == binding[k] for k in binding), 'click subject differs from native/FEEL identity')
    require(all(row[k] == focus[k] for k in ('lease','generation','thread','owner_thread',*POINTERS)) and
            row['focus_ordinal'] == focus['frontend_ordinal'] and row['focus_returned_us'] == focus['returned_us'] and
            row['sampled_us']-focus['returned_us'] >= 200000, 'click lacks its settled original focus owner')
    own = row['pose']
    candidates = [p for p in poses if p['event'] == 'visual_pose' and p['sampled_us'] == own['policy_us'] and
                  all(p[k] == row[k] for k in ('world','match','frame','entity','unit_type','army','incarnation','lease'))]
    require(len(candidates) == 1, 'callback lacks unique exact preceding visual policy sample')
    pose = candidates[0]
    require(pose['publication_us'] == own['publication_us'] and pose['alpha'] == own['alpha'] and
            pose['raw'] == own['raw'] and pose['displayed'] == own['displayed'] and pose['transform'] == own['actual'],
            'callback/publication/alpha/root differs from actual visual pose')
    return pose


def _episode(own, *, queue_contract='three_events'):
    require(queue_contract in ('three_events','neutral_prefix_four_events'), 'unknown explicit queue contract')
    require([r['event'] for r in own] == list(EVENTS), 'episode event order/coverage differs')
    pos,downq,down,process,processed,downret,upq,up,upret,closed = own
    require([r['kind'] for r in (down,downret,up,upret)] == ['Down','Down','Up','Up'], 'callback kinds reordered')
    require(all(pos['history'][k] is False for k in ('primary','context','drag')) and
            pos['mouse']['primary'] is pos['mouse']['context'] is False,
            'position control did not begin released')
    h = down['history']
    elapsed = motion.vec([h['now']-h['last_up'],0,0])[0]
    require(all(h[k] is False for k in ('primary','context','drag')) and
            down['mouse']['primary'] is True and down['mouse']['context'] is False and elapsed > h['window'],
            'original Down lacks released/expired Single precondition')
    stable = ('world','match','episode','control','entity','unit_type','army','incarnation','lease','generation',
              'thread','owner_thread','focus_ordinal','focus_returned_us',*sorted(POINTERS))
    require(all(all(r[k] == pos[k] for k in stable) for r in own), 'click lifetime/owner changed within episode')
    require(all(r['mouse'][k] == pos['mouse'][k] for r in own for k in ('action','control','device')), 'bound action/control/device changed')
    expected=[1,2,2,2,2,2,3,3,3,3] if queue_contract=='three_events' else [2,3,3,3,3,3,4,4,4,4]
    require([r['mouse']['queued_sequence'] for r in own] == expected, 'queue receipts do not bind actual callbacks')
    require(downq['frontend_ordinal'] > pos['frontend_ordinal'] and upq['frontend_ordinal'] > downq['frontend_ordinal'] and
            closed['frontend_ordinal'] > upq['frontend_ordinal'], 'normal frontend delivery observations did not advance')
    require(pos['sampled_us'] < downq['sampled_us'] < down['sampled_us'] <= process['sampled_us'] <=
            processed['sampled_us'] <= downret['sampled_us'] < upq['sampled_us'] < up['sampled_us'] <=
            upret['sampled_us'] < closed['sampled_us'], 'queued event/callback/close causality differs')
    for before,after in ((down,downret),(process,processed),(up,upret)):
        require(before['pending_commands'] == after['pending_commands'], 'original click callback added commands')
    for before,after in ((down,downret),(up,upret)):
        require(all(before[k] == after[k] for k in ('kind','ticket_serial','method_info','dispatch_thunk',
                    'method_token','method_rva','context_pointer')), 'callback return lacks its actual original entry')
    require(all(r['ticket_serial'] == down['ticket_serial'] and r['down_method_info'] == down['method_info'] and
                r['context_pointer'] == down['context_pointer'] for r in (process,processed)) and
            process['original_entry'] == processed['original_entry'], 'ProcessClick is not nested in this original Down')
    require(processed['history']['mode'] == 1 and processed['history']['id'] == pos['entity'] and
            processed['history']['primary'] is True, 'original ProcessClick did not return in subject Single mode')
    require(downret['single_accepted'] is True and downret['ledger_completed'] is True and
            downret['ledger_serial'] == downret['ticket_serial'], 'original Single-mode Down did not complete its exact ticket')
    require(downret['history']['primary'] is True and downret['mouse']['primary'] is True, 'actual primary press not delivered')
    require(up['ticket_serial'] > down['ticket_serial'], 'Up did not use a fresh original entry ticket')
    require(up['mouse']['primary'] is up['mouse']['context'] is False and up['history']['primary'] is True,
            'original release event was not delivered before Up')
    # Up may truthfully invalidate the ledger through original selection changes.
    for row in (upret,closed):
        require(row['current_ids'] == [row['entity']] and not row['preview_ids'] and not row['casting_ids'],
                'returned Up/final selection is not the exact current subject')
        require(row['history']['primary'] is row['history']['context'] is row['history']['drag'] is False and
                row['mouse']['primary'] is row['mouse']['context'] is False and row['history']['mode'] == 0,
                'original primary/context/drag controls were not balanced and released')
    # QueueEvent updates buttons and position together. The selector must have
    # consumed this position event before the later button event; retargeting
    # at press can make a genuine callback observe the previous position.
    point = struct.pack('<ff',*pos['queued_point'])
    require(all(struct.pack('<ff',*r['queued_point']) == point for r in own) and
            all(struct.pack('<ff',*r['pointer']) == point for r in
                (downq,down,process,processed,downret,upq,up,upret,closed)),
            'immutable consumed position differs at press/callback/release')
    hit = down['hit_test']; target = {k:down[k] for k in queries.IDENTITY}
    require(hit['point'] == down['pointer'], 'Down hit-test used a different pointer')
    missing = []
    if not (hit['inside'] and hit['raw_inside']): missing.append('callback counterfactual point offscreen')
    if not (hit['displayed']['hit'] and hit['displayed']['identity'] == target): missing.append('displayed Down ray missed exact current subject')
    magnitude = math.hypot(*down['pose']['offset'])
    if down['control'] == 'nonzero':
        if magnitude < .5: missing.append('original Down lacks0.5unit correction')
        if not hit['discriminates']: missing.append('original Down ray does not discriminate displayed from raw')
    elif hit['discriminates'] or hit['displayed'] != hit['raw']:
        missing.append('zero control ray returns differ')
    return dict(episode=pos['episode'],control=pos['control'],passed=not missing,missing_gates=missing,
        down_ticket=down['ticket_serial'],up_ticket=up['ticket_serial'],down_frame=down['frame'],
        down_offset=magnitude,original_process_returned=True,returned_up=True,
        up_ledger_completed=upret['ledger_completed'],up_single_accepted=upret['single_accepted'],
        final_selected_ids=closed['current_ids'],roots_before=closed['roots_before'],roots_after=closed['roots_after'],
        records=own)


def evaluate(records, visual_records, bindings, *, focus_records):
    require(type(bindings) is list and len(bindings) == 2 and len({b['world'] for b in bindings}) == 2 and
            len({b['match'] for b in bindings}) == 2, 'two external world/subject bindings required')
    require(type(focus_records) is list and len(focus_records) == 2 and
            [(r['world'],r['match']) for r in focus_records] == [(b['world'],b['match']) for b in bindings],
            'two original camera owners required')
    require(all((r['world'],r['match']) in {(b['world'],b['match']) for b in bindings} for r in records), 'unbound click world')
    worlds = []; joined = {}
    for binding,focus in zip(bindings,focus_records):
        own = [r for r in records if r['world'] == binding['world']]
        missing = []; episodes = []
        for row in own:
            pose = _join(row,visual_records,binding,focus)
            joined[(pose['world'],pose['sampled_us'])] = pose
        require([r['episode'] for r in own] == sorted(r['episode'] for r in own), 'click control order regressed')
        require(all(b['frame'] >= a['frame'] and b['pose']['revision'] >= a['pose']['revision']
                    for a,b in zip(own,own[1:])), 'click physical frame/revision regressed')
        for number in (1,2):
            subset = [r for r in own if r['episode'] == number]
            if len(subset) != len(EVENTS):
                missing.append('incomplete '+('zero' if number == 1 else 'nonzero')+' callback/close episode')
                continue
            episode = _episode(subset); episodes.append(episode); missing.extend(episode['missing_gates'])
        if own:
            stable = ('lease','generation',*sorted(POINTERS))
            require(all(len({r[k] for r in own}) == 1 for k in stable), 'same-world click actor/current owner changed')
            if len(episodes) == 2:
                require(episodes[1]['down_ticket'] > episodes[0]['up_ticket'], 'new episode reused an old original callback ticket')
        worlds.append(dict(binding=binding,passed=not missing,status='qualified' if not missing else 'inconclusive',
                           missing_gates=missing,episodes=episodes,records=own))
    passed = all(w['passed'] for w in worlds)
    return dict(schema=1,passed=passed,component_observation_passed=passed,status='qualified' if passed else 'inconclusive',
        scope='programmatic_original_primary_click',worlds=worlds,joined_visual_poses=list(joined.values()),
        focus_records=focus_records,physical_input_accepted=False,commands_accepted=False,full_feature_accepted=False,
        limitations=['Balanced public InputSystem state events and original primary/ProcessClick callbacks only.',
                     'Ray Boolean and out-object are independent original returns; neither is synthesized from the other.',
                     'The current subject may already be selected; first-time selection change from another selection is not proven.',
                     'No distinct inner SingleProcessClick entry,physical gesture,unit-target command or Internet acceptance.'])


def analyze(plan, report, run):
    validate_plan(plan); require(plan.get('visual_click') is True, 'explicit click option missing')
    run = Path(run); inputs = {}
    def read(path):
        require(path.stat().st_size <= 64*1024*1024, 'closed input exceeds bound')
        raw = path.read_bytes(); inputs[str(path)] = hashlib.sha256(raw).hexdigest(); return raw
    log_path = run/'native-0.log'; log = read(log_path).decode('utf-8')
    observed = rows(log); poses = visual.rows(log); focus = queries.focus_rows(log)
    peer = read(run/'native-1.log').decode('utf-8')
    require(PREFIX not in peer and FAILURE not in peer, 'unrequested peer click/failure')
    bindings = [w['binding'] for w in report['native_position_trace']['worlds']]
    result = evaluate(observed,poses,bindings,focus_records=focus)
    producer_sha256 = {}
    for name in PRODUCERS:
        path = run.parent/'source-at-prepare'/name
        require(path.stat().st_size <= 256*1024, 'producer snapshot exceeds bound')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        require(digest == plan['source_sha256'][name], 'consumed original callback producer differs')
        producer_sha256[name] = digest
    parent_error = None
    try:
        visual.parent_gate(plan,report)
        require(queries.gate(plan,report) and report['visual_input_witness_passed'] is True,
                'unchanged full visual/query/lifecycle parents missing')
        require(report['visual_input']['input_sha256'].get(str(log_path)) == inputs[str(log_path)], 'query/click logs differ')
        for module in (queries,visual,motion):
            require(motion.sha(module.__file__) == plan['source_sha256']['tools/'+Path(module.__file__).name], 'consumed join source differs')
        require(motion.sha(__file__) == plan['source_sha256']['tools/prediction_visual_click.py'], 'consumed click analyzer differs')
    except (AssertionError,KeyError,TypeError,ValueError) as error: parent_error = repr(error)
    require(all(motion.sha(path) == digest for path,digest in inputs.items()), 'closed click captures changed')
    result.update(parent_gates_passed=parent_error is None,parent_error=parent_error,file_only=True,
                  input_sha256=inputs,producer_sha256=producer_sha256)
    result['passed'] = result['component_observation_passed'] and parent_error is None
    if parent_error is not None: result['status'] = 'parent_unqualified'
    return result


def gate(plan, report):
    if not plan.get('visual_click'): return True
    try:
        validate_plan(plan); visual.parent_gate(plan,report)
        require(queries.gate(plan,report), 'query parent missing')
        proof = report['visual_click']
        require(proof['passed'] is proof['component_observation_passed'] is proof['parent_gates_passed'] is True and
                proof['status'] == 'qualified' and proof['scope'] == 'programmatic_original_primary_click' and
                proof['physical_input_accepted'] is proof['commands_accepted'] is proof['full_feature_accepted'] is False,
                'saved click proof is not qualified')
        bindings = [w['binding'] for w in report['visual_correction']['worlds']]
        require([w['binding'] for w in proof['worlds']] == bindings, 'saved click world binding differs')
        require(proof['input_sha256'] == report['visual_input']['input_sha256'] and
                len(proof['input_sha256']) == 2 and
                all(type(k) is str and type(v) is str and re.fullmatch('[a-f0-9]{64}',v)
                    for k,v in proof['input_sha256'].items()), 'saved click/query log source differs')
        require(proof['producer_sha256'] == {name:plan['source_sha256'][name] for name in PRODUCERS},
                'saved original callback producer binding missing')
        require(proof['focus_records'] == [w['focus'] for w in report['visual_input']['worlds']],
                'saved click/query original focus owners differ')
        records = [r for w in proof['worlds'] for r in w['records']]
        parsed = rows('\n'.join(PREFIX+json.dumps(r) for r in records))
        poses = visual.rows('\n'.join(visual.PREFIX+json.dumps(r) for r in proof['joined_visual_poses']))
        focus = queries.focus_rows('\n'.join(queries.FOCUS_PREFIX+json.dumps(r) for r in proof['focus_records']))
        rebuilt = evaluate(parsed,poses,bindings,focus_records=focus)
        require(rebuilt['passed'] and rebuilt['worlds'] == proof['worlds'], 'saved click callback/cleanup coverage differs')
        return True
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError): return False


def finalize(plan, report, run):
    if not plan.get('visual_click'): return
    parent = report.get('passed') is True
    try: report['visual_click'] = analyze(plan,report,run)
    except (AssertionError,KeyError,TypeError,ValueError,AttributeError,IndexError,OSError,OverflowError) as error:
        proof = dict(passed=False,component_observation_passed=False,parent_gates_passed=False,status='unqualified',
                     error=repr(error),scope='programmatic_original_primary_click',physical_input_accepted=False,
                     commands_accepted=False,full_feature_accepted=False)
        try: proof['preserved_observations'] = rows((Path(run)/'native-0.log').read_text(encoding='utf-8'))
        except (AssertionError,ValueError,OSError,KeyError,TypeError) as parse_error: proof['observation_error'] = repr(parse_error)
        report['visual_click'] = proof
    report['visual_click_witness_passed'] = report['visual_click'].get('passed') is True
    report['passed'] = parent and report['visual_click_witness_passed'] and gate(plan,report)
