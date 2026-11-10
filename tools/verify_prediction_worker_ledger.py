"""Prepare-only by default: changed-path original/worker ledger qualification.

An explicit coordinated --run-prepared uses TWO sequential suspended Job-owned
children. The first loads only the unmodified three-thread original DLL, records
a fresh changed canonical journal and independent raw observations. The second
loads only the product NativeSession derived DLL and exercises64..71 plus the
ordinary native ABI. No Unity client, live server or user game is contacted.
Parsed native state, correction/continuation and lifecycle are the proof scope;
complete hidden state, graphical actor repair and command-admission UX are not.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import struct
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools import verify_prediction_worker_reconcile as base

CASE_PLAN=dict(first_local=500,second_local=506,server_commit=502,authority_frontier=503,
               head=507,continuation_last=537,dead_commit=800,terminal_frame=850,last_frame=859)
require,digest,sha,write=base.require,base.digest,base.sha,base.write


def entity_packet(raw):
    require(len(raw)>=8,'entity packet truncated')
    frame,count=struct.unpack_from('<iI',raw)
    require(-1<=frame<=0x7fffffff and count<=262144 and len(raw)==8+12*count,'entity packet frame/count/length mismatch')
    rows={};last=-1
    for offset in range(8,len(raw),12):
        entity,army,kind=struct.unpack_from('<III',raw,offset)
        require(entity>last,'entity packet IDs must be unique and sorted')
        rows[entity]=(army,kind);last=entity
    return frame,rows


def append_own_actions(raw,identity,actions,validate):
    from client_patch.prediction_worker.commands import own_player_body,player_slot
    from server.game_data import encode_player_input
    from server.protobuf_wire import field_bytes,get_repeated_bytes,replace_fields
    own=own_player_body(raw,0)
    merged=encode_player_input(identity,(*get_repeated_bytes(own,2),*actions))
    merged=validate(0,merged)
    players=[player for player in get_repeated_bytes(raw,6) if player_slot(player)!=0]
    return replace_fields(raw,{6:[field_bytes(6,merged),*(field_bytes(6,player) for player in players)]})


def register_batch(dispatch,world,sequence,body,*,expected_frame):
    code,data=dispatch(67,struct.pack('<QQ',world,sequence)+body)
    require(code==0 and len(data)==12,'LOCAL_BATCH failed/response length mismatch')
    received,assigned=struct.unpack('<Qi',data)
    require((received,assigned)==(sequence,expected_frame),'LOCAL_BATCH sequence/assigned frame mismatch')
    return received


def prepare(args):
    invocation=base.prepare(args)
    output=Path(invocation['output'])
    extra=base.source_closure(ROOT,['tools/verify_prediction_worker_ledger.py'])
    missing=[name for name in extra if name not in invocation['source_sha256']]
    invocation['source_sha256'].update(base.snapshot_files(ROOT,output/'source',missing))
    invocation.update(scope=__doc__,case_plan=CASE_PLAN,native_executed=False)
    commands={}
    for role in ('control','prediction'):
        folder=output/role;folder.mkdir();(folder/'child').mkdir()
        command=[invocation['python']['path'],'-I','-S','-B','-u','-c',
            "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.verify_prediction_worker_ledger',run_name='__main__')",
            str(output/'source'),'--child','--role',role,'--output',str(folder)]
        commands[role]=command
        child=dict(invocation,command=command,role=role)
        write(folder/'invocation.json',child)
    invocation['commands']=commands
    write(output/'invocation.json',invocation)
    base.verify_prepared(invocation)
    return invocation


def parsed_views(raw):
    from server.native_simulation import decode_snapshot
    from tools.verify_prediction_combat_fixture import entity_states
    from tools.verify_movement_prediction import decode_cooldowns
    state=decode_snapshot(raw[31],31,include_entities=True);state.pop('raw_sha256',None)
    return base.normalized(dict(state=state,entity_states=entity_states(raw[31]),
        ability_charges={str(viewer):decode_cooldowns(raw[viewer]) for viewer in (0,1)}))


class Recordings:
    def __init__(self,folder):self.folder,self.streams,self.count=folder,{},0
    def save(self,frame,raw,observation):
        for viewer,body in raw.items():
            if viewer not in self.streams:
                stream=(self.folder/('view'+str(viewer)+'.bin')).open('xb');stream.write(b'BASNP001')
                self.streams[viewer]=stream
            self.streams[viewer].write(struct.pack('<II',frame,len(body))+body)
        if 'states' not in self.streams:self.streams['states']=(self.folder/'states.jsonl').open('x',encoding='utf-8')
        self.streams['states'].write(json.dumps(dict(frame=frame,**observation,
            raw_sha256={str(viewer):digest(body) for viewer,body in raw.items()}),sort_keys=True,separators=(',',':'))+'\n')
        self.count+=1
    def close(self):
        for stream in self.streams.values():stream.close()


def terminal_action(template,state):
    from server.protobuf_wire import field_bytes,parse_fields
    from tools.verify_movement_prediction import execute
    choices=[(row,ability) for row in state['entities'] if row.get('army')==0 and
        template.catalog.get(row.get('type'),{}).get('name')=='Core'
        for ability in template.entity_abilities[row['type']]
        if any(field.number==24 for field in parse_fields(template.abilities[ability]))]
    require(len(choices)==1,'one original owned Core SelfDestructAbility required')
    core,ability=choices[0]
    require(ability==8,'exact original Core SelfDestruct8 changed')
    return execute(core,ability,field_bytes(1,b'')),core


def control_child(output,invocation,report):
    from server.native_simulation import NativeSimulation
    from server.game_data import InputValidation,encode_frame
    from tools.verify_movement_prediction import fixture,move_action
    from tools.prediction_native import own_thread_ids
    root=Path(invocation['output']);folder=output/'child';assets=root/'inputs/assets'
    baseline=root/'inputs/baseline'
    with (baseline/'shared/canonical-frames.bin').open('rb') as stream:original=base.read_journal(stream)
    retained=base.read_reference(baseline,original)
    template,match,crab=fixture(assets)
    wrong,actor=base.choose_divergence(template,match,crab,retained,CASE_PLAN['first_local'])
    from client_patch.prediction_worker.commands import own_player_body
    from server.protobuf_wire import get_repeated_bytes
    move=get_repeated_bytes(own_player_body(wrong,0),2)[0]
    known,dead,absent={},set(),set()
    world=None;recordings=Recordings(folder);journal=None;before_threads=own_thread_ids()
    try:
        world=NativeSimulation(match.raw_game_data,assets/'Simulation.dll')
        report['added_original_world_threads']=sorted(set(own_thread_ids())-set(before_threads))
        require(len(report['added_original_world_threads'])==3,'unmodified control did not create three original workers')
        journal=(folder/'canonical-frames.bin').open('xb')
        state=world.state(31,include_entities=True)
        known.update({row['id']:(row['army'],row['type']) for row in state['entities'] if 'army' in row and 'type' in row})
        validation=InputValidation(match,template,entity_lookup=known.get)
        prefix_equal=0;dead_actor=None;terminal=None;first_complete=None
        for number in range(CASE_PLAN['last_frame']+1):
            raw=original[number]
            if number==CASE_PLAN['server_commit']:
                raw=append_own_actions(raw,match.identities_by_slot[0],[move,move],validation.validate_player_input)
            if number==CASE_PLAN['dead_commit']:
                choices=sorted(entity for entity in dead & absent if known.get(entity)==(0,crab))
                require(choices,'changed control lacks a real confirmed-dead/despawned owned Crab before800')
                dead_actor=dict(id=choices[0],army=0,type=crab)
                dead_move=move_action(dead_actor,actor['target'])
                raw=append_own_actions(raw,match.identities_by_slot[0],[dead_move],validation.validate_player_input)
            if number==CASE_PLAN['terminal_frame']:
                action,core=terminal_action(template,state)
                terminal=dict(action_sha256=digest(action),core=core,ability=8)
                raw=append_own_actions(raw,match.identities_by_slot[0],[action],validation.validate_player_input)
            if number>CASE_PLAN['terminal_frame']:
                raw=encode_frame(number,{0:b'',1:b''})
            journal.write(struct.pack('<I',len(raw))+raw)
            world.process_frame(raw,dt_ms=50)
            raw_views={viewer:world.snapshot(viewer) for viewer in (31,0,1)}
            observed=parsed_views(raw_views);state=observed['state']
            recordings.save(number,raw_views,observed)
            if number<CASE_PLAN['server_commit']:
                base.compare_observation(observed,retained[number],number);prefix_equal+=1
                require(raw==original[number],'control unchanged prefix input differs')
            identities={row['id']:(row['army'],row['type']) for row in state['entities'] if 'army' in row and 'type' in row}
            known.update(identities)
            dead.update(int(entity) for entity,mode in observed['entity_states'].items() if mode==6)
            absent.update(entity for entity in dead if entity not in identities)
            if state['game_state']['complete'] and first_complete is None:first_complete=number
            require(first_complete is None or first_complete==CASE_PLAN['terminal_frame'],'unexpected early/native terminal frame')
            if number>=CASE_PLAN['terminal_frame']:
                require(state['game_state']['complete'] and state['game_state']['game_over_frame']==CASE_PLAN['terminal_frame'],
                        'original SelfDestruct did not produce/stably retain true native completion')
        require(first_complete==CASE_PLAN['terminal_frame'] and dead_actor and terminal,'control path prerequisites missing')
        journal.flush()
        report.update(passed=True,frame_count=recordings.count,unchanged_prefix_equal=prefix_equal,
            move_actor=actor,move_sha256=digest(move),dead_actor=dead_actor,terminal=terminal,
            first_complete=first_complete,canonical_journal_sha256=sha(folder/'canonical-frames.bin'))
    finally:
        if journal:journal.close()
        recordings.close()
        if world:world.close()
        require(own_thread_ids()==before_threads,'original control worker threads remained after teardown')
        report['native_world_closed']=world is not None and world.closed


class LedgerCoordinator(base.Coordinator):
    def __init__(self,*args):super().__init__(*args);self.sequence=1
    def metrics(self,world):
        value=base.decode_metrics(self.success(66,struct.pack('<Q',world)))
        require(not value['failed'] and not value['closed'],'ledger prediction became failed/closed')
        return value
    def batch(self,world,body,assigned):
        sequence=self.sequence
        register_batch(self.dispatch,world,sequence,body,expected_frame=assigned)
        self.sequence+=1
        return sequence
    def canonical(self,world,raw,*,register=True):
        from client_patch.prediction_worker.commands import own_player_body
        from server.protobuf_wire import get_repeated_bytes
        own=own_player_body(raw,0)
        if register and own and get_repeated_bytes(own,2):self.batch(world,own,self.session.predictions[world].predicted_frame+1)
        return self.enqueue(world,[raw])
    def entities(self,world):return entity_packet(self.success(68,struct.pack('<Q',world)))
    def active_entities(self,world):
        raw=self.success(70,struct.pack('<Q',world))
        frame,count=struct.unpack_from('<iI',raw)
        require(count<=65536 and len(raw)==8+count*20,'active entity packet size differs')
        rows={}
        for offset in range(8,len(raw),20):
            entity,army,kind,token=struct.unpack_from('<IIIQ',raw,offset)
            require(entity not in rows and token,'active entity ID/token invalid')
            rows[entity]=(army,kind,token)
        return frame,rows


def rejected_batch(c,world,body):
    ledger=c.session.command_ledgers[world]
    before=(ledger.metrics,ledger.pending,c.snapshot(world),c.entities(world))
    rejected=False
    try:c.dispatch(67,struct.pack('<QQ',world,c.sequence)+body)
    except ValueError:rejected=True
    require(rejected,'invalid entity command unexpectedly admitted')
    current=c.session.command_ledgers[world]
    require((current.metrics,current.pending,c.snapshot(world),c.entities(world))==before,
            'rejected registration mutated ledger/native/identity state')
    return dict(rejected=True,native_work=False,sequence=c.sequence)


def replay_boundary(c,world,next_frame,head,reference,phase):
    adapter=c.session.prediction_adapters[world];original=adapter.process_frame
    audit=dict(observed=False,replayed=[],replay_dispatch_seconds=0.,head_observer_seconds=0.)
    def observe(raw,dt):
        start=time.perf_counter();original(raw,dt)
        audit['replay_dispatch_seconds']+=time.perf_counter()-start
        require(c.last_process==dict(frame=base.frame_number(raw),sha256=digest(raw)),
                'original native ProcessMsg did not receive the recorded replay bytes')
        audit['replayed'].append(dict(frame=base.frame_number(raw),sha256=digest(raw)))
        if base.frame_number(raw)==head:
            start=time.perf_counter();value=c.observe(world,head,phase+'/corrected_head')
            if reference is not None:base.compare_observation(value,reference[head],head)
            audit['head_observer_seconds']=time.perf_counter()-start;audit['observed']=True
    adapter.process_frame=observe
    c.phase=phase+'/boundary'
    from server.game_data import encode_frame
    supplied=encode_frame(next_frame,{0:b'',1:b''})
    started=time.perf_counter()
    try:c.process(world,supplied)
    finally:
        audit['boundary_seconds']=time.perf_counter()-started;adapter.process_frame=original
    require(audit['observed'],'quiescent boundary failed to replay the old physical head')
    audit['metrics_after']=c.metrics(world)
    return audit


def prediction_child(output,invocation,report):
    from client_patch.prediction_worker.native import NativeSession
    from client_patch.prediction_worker.commands import own_player_body
    from server.protobuf_wire import get_repeated_bytes
    from server.game_data import encode_player_input
    from tools.verify_movement_prediction import fixture,move_action
    root=Path(invocation['output']);folder=output/'child'
    control=root/'control/child'
    control_report=json.loads((control/'report.json').read_text())
    require(control_report['passed'] and json.loads((root/'control/verification.json').read_text())['passed'],
            'fresh original control must finish successfully before derived child starts')
    receipts=json.loads((root/'control-artifacts.json').read_text())
    base.verify_files(root,receipts)
    with (control/'canonical-frames.bin').open('rb') as stream:
        frames=base.read_journal(stream,count=CASE_PLAN['last_frame']+1)
    require(sha(control/'canonical-frames.bin')==control_report['canonical_journal_sha256'],'changed canonical journal hash mismatch')
    reference=[json.loads(line) for line in (control/'states.jsonl').read_text().splitlines()]
    require([row['frame'] for row in reference]==list(range(len(frames))),'fresh control state journal frame order')
    template,match,crab=fixture(root/'inputs/assets')
    move=get_repeated_bytes(own_player_body(frames[CASE_PLAN['server_commit']],0),2)
    require(len(move)==2 and move[0]==move[1] and digest(move[0])==control_report['move_sha256'],
            'control must contain exactly two byte-identical whole movement batches at502')
    local=encode_player_input(match.identities_by_slot[0],[move[0]])
    session=c=None
    try:
        session=NativeSession.open(original_dll=root/'inputs/assets/Simulation.dll',
            heap_helper=root/'inputs/heap'/invocation['heap_name'],cooperative=root/'inputs/cooperative'/invocation['cooperative_name'],
            data_dir=folder/'native-data')
        report['provenance']=session.provenance
        c=LedgerCoordinator(session,folder,reference)
        c.success(3,b'\1');c.success(4,struct.pack('<I',0));c.success(1,b'\0')
        world=c.create(match.raw_game_data);roots=session.arena.root_bindings()
        require(c.success(71,struct.pack('<Q',world))==struct.pack('<I',1),'native entity observer capability is absent')
        report['root_bindings']=roots
        c.phase='confirmed_prefix'
        for number in range(CASE_PLAN['first_local']):
            c.canonical(world,frames[number]);c.process(world,frames[number]);c.step(world)
            base.compare_observation(c.observe(world,number,'confirmed_prefix'),reference[number],number)
        promoted,known=c.entities(world)
        actor=control_report['move_actor']
        require(promoted==499 and known.get(actor['entity'])==(0,crab),'movement actor was not admitted from real confirmed499 view')
        active_frame,active_before=c.active_entities(world)
        require(active_frame==499 and active_before[actor['entity']][:2]==(0,crab),'confirmed active movement actor missing')
        bad=[]
        for entity in (dict(id=0xffffffff,type=crab),dict(id=actor['entity'],type=crab+1),
                       dict(id=next(entity for entity,value in known.items() if value==(1,crab)),type=crab)):
            bad.append(rejected_batch(c,world,encode_player_input(match.identities_by_slot[0],[move_action(entity,actor['target'])])))
        report['invalid_admission']=bad
        c.phase='local_speculation'
        first=c.batch(world,local,500);second=None;divergence=[];maximum=0.
        for number in range(500,508):
            if number==506:second=c.batch(world,local,506)
            c.process(world,frames[number]);c.step(world)
            observed=c.observe(world,number,'local_speculation')
            expected_actor=next((row for row in reference[number]['state']['entities'] if row['id']==actor['entity']),None)
            actual_actor=next((row for row in observed['state']['entities'] if row['id']==actor['entity']),None)
            if expected_actor and actual_actor and 'position' in expected_actor and 'position' in actual_actor:
                distance=math.dist(expected_actor['position'],actual_actor['position'])
                maximum=max(maximum,distance)
                if distance>.05:divergence.append(number)
        ledger=session.command_ledgers[world]
        ordinals=[item.ordinal for item in ledger.pending]
        require(first!=second and ordinals==[(first,0),(second,0)] and maximum>.05 and 500 in divergence,
                'local movement did not precede authority with two distinct identical-command ordinals')
        c.phase='authority_delayed_and_early'
        enqueue=c.enqueue(world,frames[500:504])
        require(not session.command_ledgers[world].pending,'canonical502 did not retire both whole distinct batches')
        before=c.metrics(world)
        require((before['confirmed_frame'],before['predicted_frame'],before['received_frame'])==(499,507,503),'episode cursors differ')
        history=session.identity_histories[world];invalidations=[];original_invalidate=history.invalidate_after
        def audited_invalidate(frame):
            before=list(history.views);original_invalidate(frame)
            invalidations.append(dict(base=frame,before=before,after=list(history.views)))
            require(all(value<=frame for value in history.views),'speculative identity views survived restore base')
        history.invalidate_after=audited_invalidate
        repair=replay_boundary(c,world,508,507,reference,'movement_repair')
        history.invalidate_after=original_invalidate
        require([row['frame'] for row in repair['replayed']]==list(range(500,508)), 'movement repair did not replay all eight physical frames')
        require(all(row['sha256']==digest(frames[row['frame']]) for row in repair['replayed']),
                'delayed/early own orders were duplicated or lost during revised replay')
        require(repair['metrics_after']['confirmed_frame']==503 and c.entities(world)[0]==503,
                'corrected confirmed-frontier entity view was not refreshed/promoted')
        active_frame,active_after=c.active_entities(world)
        require(active_frame==503 and active_after[actor['entity']]==active_before[actor['entity']],
                'guarded four-frame replay interval lost the confirmed actor incarnation')
        report['active_identity']=dict(before_frame=499,after_frame=active_frame,
            entity=actor['entity'],identity_and_token=active_after[actor['entity']],
            guarded_interval_creates=sum(session.entity_guards[world].counts[number] for number in range(500,504)))
        require(invalidations and invalidations[0]['base']==499 and all(value<=499 for value in invalidations[0]['after']),
                'identity correction invalidation was not observed')
        c.phase='movement_continuation'
        # Authority504..508 arrives while ordinary508 is already prepared.
        # It must stay immutable; these bytes are exactly its neutral forecast.
        c.enqueue(world,frames[504:509]);c.step(world)
        base.compare_observation(c.observe(world,508,'movement_continuation'),reference[508],508)
        for number in range(509,538):
            c.canonical(world,frames[number]);c.process(world,frames[number]);c.step(world)
            base.compare_observation(c.observe(world,number,'movement_continuation'),reference[number],number)
        report['movement']=dict(assigned_frames=[500,506],committed_frame=502,ordinals=ordinals,
            max_position_delta=maximum,divergence_frames=divergence,enqueue=enqueue,repair=repair,
            identity_invalidations=invalidations,corrected_heads_equal=1,continuation_frames_equal=30)
        c.phase='confirmed_continuation'
        for number in range(538,850):
            if number==800:
                entity=control_report['dead_actor']['id'];frame,identities=c.entities(world)
                require(frame==799 and identities.get(entity)==(0,crab) and
                        not any(row['id']==entity and 'army' in row and 'type' in row for row in reference[799]['state']['entities']),
                        'dead-entity admission was not from retained confirmed history')
                report['known_dead_admission']=dict(entity=entity,promoted_frame=frame,identity=identities[entity],absent_from_current=True)
                active_frame,active=c.active_entities(world)
                require(active_frame==799 and entity not in active,'dead known-command source leaked into active selection admission')
            c.canonical(world,frames[number]);c.process(world,frames[number]);c.step(world)
            base.compare_observation(c.observe(world,number,'confirmed_continuation'),reference[number],number)

        c.phase='terminal_speculation'
        terminal_body=own_player_body(frames[850],0)
        terminal_sequence=c.batch(world,terminal_body,850)
        for number in range(850,858):
            c.process(world,frames[number]);c.step(world)
            value=c.observe(world,number,'terminal_speculation')
            require(not value['state']['game_state']['complete'],'native terminal happened before authoritative SelfDestruct')
        pending_sequence=c.batch(world,local,858)
        c.process(world,frames[858])  # Original NativeProcessMsg858 is now immutable/inflight.
        prepared=session.prepared_prediction[world]
        require(get_repeated_bytes(prepared,6),'prepared858 did not contain the never-committed move')
        c.phase='terminal_authority_and_end'
        terminal_enqueue=c.canonical(world,frames[850],register=False)
        before_end=c.snapshot(world)
        response=c.success(69,struct.pack('<Qi',world,850))
        require(response==struct.pack('<I',1) and c.snapshot(world)==before_end and
                session.prepared_prediction[world]==prepared,'END changed native/checkpoint/inflight state or canceled wrong action count')
        require(not c.metrics(world)['terminal_admitted'],'terminal flag was admitted before physical canonical repair')
        c.step(world)
        value=c.observe(world,858,'terminal_inflight')
        require(not value['state']['game_state']['complete'],'inflight guess manufactured a native terminal state')
        raw_terminal=[];original_record=session._record_identity_view
        def record_native(key,raw,physical):
            from server.native_simulation import decode_snapshot
            if key==world and physical in (850,858):
                state=decode_snapshot(raw,0)
                raw_terminal.append(dict(frame=physical,game_state=state['game_state'],raw_sha256=digest(raw)))
            return original_record(key,raw,physical)
        session._record_identity_view=record_native
        terminal_repair=replay_boundary(c,world,859,858,None,'terminal_repair')
        session._record_identity_view=original_record
        require([row['frame'] for row in terminal_repair['replayed']]==list(range(850,859)) and
                all(row['sha256']==digest(frames[row['frame']]) for row in terminal_repair['replayed']),
                'terminal repair failed to remove never-committed future move')
        require(any(row['frame']==858 and row['game_state']['complete'] and row['game_state']['game_over_frame']==850 for row in raw_terminal),
                'actual unfiltered native replay did not complete at850')
        require(not c.metrics(world)['terminal_admitted'] and session.terminal_masked.get(world,0)>0,
                'terminal presentation filter admitted completion before real confirmed frontier')
        c.phase='terminal_final';c.step(world)
        base.compare_observation(c.observe(world,859,'terminal_final'),reference[859],859)
        final=c.metrics(world)
        require(final['terminal_admitted'] and (final['confirmed_frame'],final['predicted_frame'],final['received_frame'])==(850,859,850),
                'final terminal admission/cursors differ from real authority/physical drain')
        report['terminal']=dict(authentic_control_first_complete=control_report['first_complete'],terminal_sequence=terminal_sequence,
            canceled_uncommitted_sequence=pending_sequence,canceled_actions=1,enqueue=terminal_enqueue,
            end_native_work=False,prepared858_sha256=digest(prepared),repair=terminal_repair,
            unfiltered_native_views=raw_terminal,final_metrics=final,final859_equal=True)
        require(session.arena.root_bindings()==roots,'root bindings/sticky revision changed')
        observer=session.entity_guards[world]
        require(observer.total_creations>0,'native master observer never witnessed actual entity creation')
        report['entity_observer']=dict(stats=list(observer.snapshot()),retained_frames=sorted(observer.counts),
            total_creations_including_replay=observer.total_creations,
            creation_samples=observer.creation_samples,maximum_14tick_creations=observer.maximum_interval_creations)
        report['retirement']=c.retire(world)
        report.update(passed=True,registered_batches=c.sequence-1,root_bindings_after=session.arena.root_bindings(),
            native_calls=c.native_calls,observer_seconds=c.observer_seconds)
    finally:
        if session:session.close()
        if c:
            report['native_calls_including_cleanup']=c.native_calls;c.close_observers()
            trace=[json.loads(line) for line in (folder/'native-calls.jsonl').read_text().splitlines()]
            require(len(trace)==c.native_calls and all(row['index']==index and row.get('result')==0 and 'error' not in row
                    for index,row in enumerate(trace)),'original native trace missing/failed calls')
            for phase,ids in (('movement_repair/boundary',range(500,509)),('terminal_repair/boundary',range(850,860))):
                messages=[row for row in trace if row['phase']==phase and row['name']=='SimProcessMsg']
                # Preserve a primary native/observer failure rather than
                # replacing it with "missing" phases never reached afterward.
                expected=list(ids) if report.get('passed') else list(ids)[:len(messages)]
                require([row['input_frame'] for row in messages]==expected and
                        all(row['input_sha256']==digest(frames[row['input_frame']]) for row in messages),
                        'original native repaired input order/bytes differ from canonical journal')
            report['native_trace_verified']=True
            report['native_trace_complete']=bool(report.get('passed'))
        if session:
            report['arena_after_close']=session.arena.healthy()
            require(not session.worlds and not session.predictions and not session.command_ledgers and not session.identity_histories and
                    not session.entity_guards and not session.active_identity_histories and
                    report['arena_after_close']['saved_bytes']==0,'derived worker retained world/ledger/identity/checkpoint state')
            report['native_session_closed']=True


def child(output,role):
    require(sys.stdin.buffer.readline(32)==b'OWNED_JOB\n','missing retained suspended Job ownership barrier')
    invocation=json.loads((output/'invocation.json').read_text())
    require(invocation['role']==role and invocation['case_plan']==CASE_PLAN,'child role/case plan mismatch')
    folder=output/'child'
    report=dict(passed=False,pid=os.getpid(),scope=__doc__,role=role,native_executed=False,errors=[])
    write(folder/'report.json',report);started=time.perf_counter()
    try:
        base.verify_prepared(invocation)
        os.chdir(folder)
        report['native_executed']=True;write(folder/'report.json',report)
        if role=='control':control_child(output,invocation,report)
        elif role=='prediction':prediction_child(output,invocation,report)
        else:raise AssertionError('unknown owned child role')
    except BaseException as error:
        report.update(passed=False)
        report['errors'].append(dict(error=repr(error),traceback=traceback.format_exc()))
    finally:
        try:base.verify_prepared(invocation);report['pinned_inputs_unchanged']=True
        except BaseException as error:
            report.update(passed=False);report['errors'].append(dict(phase='identity_cleanup',error=repr(error)))
        paths=[path for path in folder.rglob('*') if path.is_file() and
            (path.name.startswith('view') or path.name in ('canonical-frames.bin','states.jsonl','native-calls.jsonl'))]
        report['raw_observation_sha256']={path.relative_to(folder).as_posix():sha(path) for path in paths}
        report['elapsed_seconds']=time.perf_counter()-started
        write(folder/'report.json',report)
    return 0 if report['passed'] else 1


def run_prepared(output):
    invocation=json.loads((output/'invocation.json').read_text())
    base.verify_prepared(invocation)
    require(invocation['case_plan']==CASE_PLAN and not (output/'verification.json').exists(),'plan changed or owned proof already attempted')
    report=dict(passed=False,scope=__doc__,native_executed=False,children=[],errors=[],
                invocation_sha256=sha(output/'invocation.json'))
    try:
        for role in ('control','prediction'):
            require(not report['children'] or report['children'][-1]['passed'],'previous owned child did not finish successfully')
            # Shared immutable source/input snapshot, separate fresh lifecycle
            # reports. The two original/derived native images never coexist.
            result=base.run_prepared(output/role)
            report['native_executed']=True
            report['children'].append(dict(role=role,passed=result['passed'],
                verification_sha256=sha(output/role/'verification.json'),
                job=result.get('job_before_close'),job_process_attribution=result.get('job_process_attribution'),
                exit_code=result.get('exit_code'),reaped=result.get('reaped'),forced_cleanup=result['forced_cleanup']))
            require(result['passed'],'owned '+role+' child failed; preserve its evidence')
            if role=='control':
                names=['control/verification.json','control/child/report.json',
                       'control/child/canonical-frames.bin','control/child/states.jsonl']
                names += ['control/child/view'+str(viewer)+'.bin' for viewer in (31,0,1)]
                write(output/'control-artifacts.json',{name:sha(output/name) for name in names})
        base.verify_files(output,json.loads((output/'control-artifacts.json').read_text()))
        base.verify_prepared(invocation)
        report['passed']=True
        report['scope_limits']=['Two sequential owned headless children, extra cumulative Job processes unattributed.',
            'Original three-thread changed-journal control and product derived worker; no Unity rendering or hidden-state equality claim.',
            'Invalid67 diagnostics call actual NativeSession.dispatch directly and catch expected rejection; real client transport is fail-closed.',
            'Replay-head observers add original Make/Get queries and are timed separately; timing is not engine-only.']
    except BaseException as error:
        report['errors'].append(dict(error=repr(error),traceback=traceback.format_exc()))
    write(output/'verification.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    for name in ('original-dll','heap-helper','cooperative','baseline','assets'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--python',type=Path,default=Path(sys.executable));parser.add_argument('--timeout',type=float,default=120)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--prepare-only',action='store_true')
    mode.add_argument('--run-prepared',action='store_true');mode.add_argument('--child',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--role',choices=('control','prediction'),help=argparse.SUPPRESS)
    args=parser.parse_args();output=args.output.resolve()
    if args.child:
        require(args.role is not None,'owned child role required');return child(output,args.role)
    if args.run_prepared:
        result=run_prepared(output);print(json.dumps(dict(passed=result['passed'],report=str(output/'verification.json'))))
        return 0 if result['passed'] else 1
    require(all(value is not None for value in (args.original_dll,args.heap_helper,args.cooperative,args.baseline)),
            'original-dll/heap-helper/cooperative/baseline required for static preparation')
    invocation=prepare(args)
    print(json.dumps(dict(prepared=True,native_executed=False,output=invocation['output'])))
    return 0


if __name__=='__main__':raise SystemExit(main())
