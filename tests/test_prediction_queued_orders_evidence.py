"""Authored two-world queued evidence. No native/client/physical input."""
from copy import deepcopy
from types import SimpleNamespace
import json
import struct
import unittest

from server.game_data import encode_identity,encode_player_input
from server.protobuf_wire import field_bytes,field_packed_uint,field_uint
from tools import prediction_queued_orders_evidence as e
from tools.verify_high_latency_clients import state_digest
from tools.verify_movement_prediction import position_message
from tools import verify_prediction_multiplayer as controller
from tests.test_prediction_close_formation_evidence import Fixture as CloseFixture,bits,f32,SQUARE


def action(ability,ids,target,queued=False):
    group=field_uint(1,1)+field_uint(2,ability)+field_packed_uint(3,ids)
    return field_bytes(1,field_bytes(1,group)+(field_uint(2,1) if queued else b'')+
                       field_bytes(3,field_bytes(3,field_bytes(1,position_message(target)))))


def plan():
    return dict(queued_orders=True,scenario='queued-orders',lifecycle='natural',frames=650,expected_matches=2,move_slot=0,
        rtt_ms=[130.,475.],native_position_trace=None,actor_fixture=None,generic_movement_not_exercised=True,
        surrender_frame=700,native_cohort_spec='1:1:280:420:8',queued_orders_fixture=e.metadata(),queued_orders_scope=e.SCOPE)


class Fixture(CloseFixture):
    TURN=351

    @classmethod
    def position(cls,identity,frame):
        if identity == 10: return [60.,0.,60.]
        original=SQUARE[identity]; travel=max(0,min(frame-180,50))*.2
        p=[f32(original[0]+travel),0.,f32(original[2]+travel)]
        if identity == 11:
            first=max(0,min(frame-300,50)); back=max(0,min(frame-cls.TURN+1,100))
            p[0]=f32(p[0]+first*.02-back*.01); p[2]=f32(p[2]-first*.3+back*.3)
        return p

    @classmethod
    def view_position(cls,identity,frame):
        # The repaired worker omits88 and its blocked successor before A arrives.
        p=cls.position(identity,300 if identity == 11 and 301 <= frame <= 310 else frame)
        return [f32(-v if identity != 10 and axis in (0,2) else v) for axis,v in enumerate(p)]

    def snapshot(self,world,match,slot,frame,event):
        row=super().snapshot(world,match,slot,frame,event)
        if slot and frame >= 290:
            row.update(selection_calls=2,current_ids=[11],current_all_ids=[11],current_typed_ids=[11],current_count=1)
        if slot and 301 <= frame <= 310: row['members'][0]['native_state']=0
        if event == 'targets_frozen':
            row.update(target_a=[70.,0.,66.],target_a_bits=bits([70.,0.,66.]),target_b=[71.,0.,35.],target_b_bits=bits([71.,0.,35.]))
            row['sampled_us']+=500
        return row

    def emit(self,slot,row):
        self.logs[slot].append(e.PREFIX+json.dumps(row))

    def command(self,world,match,frame,tag,target,sequence,raw_action):
        ids=e.IDS if tag == 'approach' else [11]
        q=self.common(world,match,1,frame,'move_queued',tag=tag,extra_us=1000)
        command=f'{world*1000+frame:X}'; proto=f'{world*1000+frame+10000:X}'
        q.update(source_ids=ids[:],incarnations=[world*100+i for i in ids],origins=[self.view_position(i,frame) for i in ids],
            origins_sampled_us=[world*100000000+frame*50000+(0 if tag == 'first' else 500)]*len(ids),target=target,target_bits=bits(target),
            command=command,command_class='Uncapped.ExecuteTargetGroundCommand',queued=tag == 'queued',ability=88 if tag == 'first' else 12,
            queue_before=0,queue_after=1,originalCtor=True,original_callback='Uncapped.ExecuteTargetGroundCommand..ctor',
            enqueue_sampled_us=world*100000000+frame*50000+2000,local_alliance=1,map_perspective=1,
            map_perspective_source='Uncapped.Map.GetAlliancePerspective',map_perspective_enum='Uncapped.Map.Perspective',
            map_perspective_enum_matches_ctor=True,map_perspective_normal=0,map_perspective_flipped=1,map_perspective_value_name='Flipped')
        self.emit(1,q)
        body=encode_player_input(encode_identity(2,'human'),[raw_action]); self.raw[match,1,sequence]=body
        for event,extra,us in (
            ('serialized',dict(command=command,action=proto,sequence=sequence,source_next_frame=frame+1,action_index=0),3000),
            ('batch_registered',dict(command=command,action=proto,sequence=sequence,speculative_frame=frame+1,action_index=0,
                action_sha256=e.shared.digest(raw_action),body_sha256=e.shared.digest(body)),4000)):
            self.emit(1,self.common(world,match,1,frame,event,tag=tag,extra_us=us)|extra)
        tick=world*100000+frame*50
        self.logs[1].append(f'Movement local batch registered: sequence={sequence} speculativeFrame={frame+1} tick={tick+3} match={match}')
        self.logs[1].append(f'Original command batch submitted: match={match} sequence={sequence} actions=1 bytes={len(body)} body_sha256={e.shared.digest(body)} sendTick={tick+4} sourceNextFrame={frame+1}')

    def world(self,world,match):
        hashes={f:state_digest(self.state(f)) for f in range(650)}
        wires={f:e.shared.digest(f'{match}/wire/{f}'.encode()) for f in hashes}
        targets=dict(approach=[70.,0.,50.],first=[70.,0.,66.],queued=[71.,0.,35.])
        actions={tag:action(88 if tag == 'first' else 12,e.IDS if tag == 'approach' else [11],
            [-v if axis in (0,2) else v for axis,v in enumerate(target)],tag == 'queued') for tag,target in targets.items()}
        schedule={181:'approach',301:'first',303:'queued'}
        journal=[dict(frame=f,players={0:[],1:[actions[schedule[f]]] if f in schedule else []}) for f in hashes]
        commits=[dict(event='command_batch_committed',match=match,slot=1,sequence=s,frame=f) for s,f in ((2,181),(3,301),(4,303))]
        bridges=[dict(match=match,frame=f,payload_sha256=wires[f],received_tick_ms=world*100000+(f+9)*50+6) for f in hashes]
        self.peer_bridge.extend(bridges)
        for slot in (0,1):
            self.receipts[slot,match]=[dict(frame=f,sha256=wires[f]) for f in hashes]
            self.logs[slot].append(f'Movement prediction ready: generation={world} match={match} world={world if slot else world+100} slot={slot} source=authored')
            for f in hashes:
                correction=int(slot == 1 and f >= 301)
                self.worker[slot].append(dict(schema=1,event='confirmed_native_state',world=world if slot else world+100,frame=f,
                    parsed_state_sha256=hashes[f],confirmed_frontier=f,corrections=correction,corrections_delta=int(slot == 1 and f == 301),
                    replayed_frames_total=10*correction,replayed_frames_delta=10*int(slot == 1 and f == 301),tick_ms=world*100000+(f+9)*50+20))
            for f in range(130,450):
                if f <= 420:
                    event='selected' if slot and f == 130 else 'setup' if f == 130 else 'single_selected' if slot and f == 290 else 'complete' if f == 420 else 'sample'
                    self.emit(slot,self.snapshot(world,match,slot,f,event))
                if slot and f == 300: self.emit(1,self.snapshot(world,match,1,f,'targets_frozen'))
                if slot and f in (180,300,302):
                    tag={180:'approach',300:'first',302:'queued'}[f]
                    self.command(world,match,f,tag,targets[tag],{180:2,300:3,302:4}[f],actions[tag])
                canonical=f-9
                if 130 <= canonical <= 440:
                    self.emit(slot,self.common(world,match,slot,f,'authority',extra_us=5000)|dict(canonical_frame=canonical,wire_sha256=wires[canonical],canonical_sha256='c'*64))
        for f in range(280,421):
            row=self.native_row(world,f); self.native.append(row)
            if f == 310:
                self.native.append(dict(row,event='before_restore_cached_head',revision=1,checkpoint_base=300,first_divergent_frame=301,
                    context_source='cached_query_before_restore',cached_from_record=row['record'],cached_physical_head=310,record=len(self.native)))
                for replay in range(301,311): self.native.append(self.native_row(world,replay,stage='replay',at=15510000+(replay-301)*1000))
        self.contexts.append(dict(match=match,raw_bodies=self.raw,commits=commits,journal=journal,canonical_states=hashes,
            canonical_payloads=wires,bridge_frames=bridges,native_states=[e.native_observation(self.state(f),hashes[f]) for f in range(130,441)]))

    def native_row(self,world,frame,*,stage='ordinary',at=None):
        replay=stage == 'replay'; revision=int(replay or frame >= 311)
        begin=world*100000000+(frame*50000-4000 if at is None else at); tick=begin//1000
        return dict(schema=1,event='after_replay_same_head' if replay and frame == 310 else 'native_cohort_positions',
            record=len(self.native),world=world,frame=frame,revision=revision,query_revision=revision,checkpoint_base=300 if revision else None,
            first_divergent_frame=301 if revision else None,cohort_spec=e.SPEC.copy(),context_source='same_decoded_native_query',stage=stage,
            head=310 if replay else frame-1,confirmed=300 if replay else frame-10,received=301 if replay else frame-10,
            corrections=0 if replay else revision,replayed_frames=frame-301 if replay else revision*10,
            query_begin_us=begin,query_end_us=begin+10,query_begin_tick_ms=tick,query_end_tick_ms=tick,status='present',count=4,
            entities=[dict(id=i,type=1,army=1,position=self.position(i,300 if i == 11 and not replay and 301 <= frame <= 310 else frame),
                position_bits=bits(self.position(i,300 if i == 11 and not replay and 301 <= frame <= 310 else frame))) for i in e.IDS],
            clock_source='python.perf_counter_ns//1000',query_scope='existing-native-make-get-and-decode')

    def mutate_rows(self,slot,function):
        amended=[]
        for line in self.logs[slot]:
            if line.startswith(e.PREFIX):
                row=json.loads(line[len(e.PREFIX):]); function(row); line=e.PREFIX+json.dumps(row)
            amended.append(line)
        self.logs[slot]=amended; self.refresh_logs()

    def run(self):
        return e.evaluate(contexts=self.contexts,cohort_trace=self.native,worker_states=self.worker,native_receipts=self.receipts,
            peer_bridge_frames=self.peer_bridge,authority_rows=lambda _:self.fail_generic(),join_check=controller.joined_worker_evidence)

    @staticmethod
    def fail_generic(): raise AssertionError('generic authority cannot replace actual queued successful65')


def report(proof):
    matches=[p['match'] for p in proof['episodes']]
    return dict(queued_orders=proof,matches=[dict(match=m,canonical_frames=650,exact_bridge_and_native_authority_receipts=True) for m in matches],
        clients=[dict(index=slot,matches=matches,natural_worker_shutdown=True,movement_route=True) for slot in (0,1)],cleanup_errors=[])


class Pipeline(unittest.TestCase):
    def test_complete_pipeline_detects_actual_turn_while_old_origin_projection_is_negative(self):
        fixture=Fixture(); result=fixture.run()
        self.assertTrue(result['passed']); self.assertEqual(result['all_closed_native_hashes_checked'],2600)
        for ep in result['episodes']:
            self.assertEqual(ep['B_native_turn']['frame'],351)
            self.assertLess(e.shared._progress(ep['B_native_turn']['first']['position'],fixture.position(11,300),ep['orders']['queued']['protocol_target']),0)
            self.assertEqual(ep['B_confirmation_frame'],353)
            self.assertEqual(len(ep['B_after_turn_20']['continuation_row_indices']),20)
            self.assertTrue(ep['no_premature_B']['native_records'])
        r=report(result); e.finalize(r,plan()); self.assertTrue(e.gate(json.loads(json.dumps(plan())),json.loads(json.dumps(r))))

    def test_turn_is_not_hardcoded_to_native_control351(self):
        class Late(Fixture): TURN=356
        result=Late().run()
        self.assertTrue(result['passed']); self.assertEqual(result['episodes'][0]['B_native_turn']['frame'],356)

    def test_one_actor_native_or_render_premature_motion_is_refused(self):
        for kind in ('native','render'):
            fixture=Fixture()
            if kind == 'native':
                row=next(r for r in fixture.native if r['world'] == 1 and r['frame'] == 305 and r['stage'] == 'ordinary')
                row['entities'][0]['position'][2]+=.1; row['entities'][0]['position_bits']=bits(row['entities'][0]['position'])
            else:
                def early(row):
                    if row['event'] == 'sample' and row['frame'] == 305:
                        row['members'][0]['position'][2]-=.1; row['members'][0]['position_bits']=bits(row['members'][0]['position'])
                fixture.mutate_rows(1,early)
            with self.subTest(kind=kind),self.assertRaisesRegex(AssertionError,'queued B moved'): fixture.run()

    def test_post_B67_pre_both_A_receipts_interval_must_be_observed(self):
        fixture=Fixture(); c=fixture.contexts[0]
        next(r for r in c['bridge_frames'] if r['frame'] == 301)['received_tick_ms']=115103
        with self.assertRaisesRegex(AssertionError,'no measured post-B67'): fixture.run()

    def test_exact_bodies_frozen_target_scope_and_manual_group_are_required(self):
        for kind in ('queued','ability','frozen','counter','current','group','token','origin','extra_host','wire','hash'):
            fixture=Fixture(); c=fixture.contexts[0]
            def corrupt(row):
                if row['match'] != fixture.matches[0]: return
                if row['event'] == 'move_queued' and row['order_tag'] == 'queued':
                    if kind == 'queued': row['queued']=False
                    elif kind == 'ability': row['ability']=88
                if row['event'] == 'targets_frozen' and kind == 'frozen': row['target_b'][2]+=1.; row['target_b_bits']=bits(row['target_b'])
                if row['event'] == 'move_queued' and row['order_tag'] == 'first' and kind == 'origin': row['origins_sampled_us'][0]+=1
                if row['event'] == 'sample' and row['frame'] == 320:
                    if kind == 'counter': row['selection_calls']=3
                    elif kind == 'current': row.update(current_ids=e.IDS[:],current_all_ids=e.IDS[:],current_typed_ids=e.IDS[:],current_count=4)
                    elif kind == 'group': row['group_typed_ids'].pop()
                    elif kind == 'token': row['members'][2]['incarnation']+=1
            fixture.mutate_rows(1,corrupt)
            if kind == 'extra_host': c['journal'][320]['players'][0]=c['journal'][303]['players'][1][:]
            elif kind == 'wire': fixture.receipts[1,c['match']][401]['sha256']='0'*64
            elif kind == 'hash': fixture.worker[0][401]['parsed_state_sha256']='0'*64
            with self.subTest(kind=kind),self.assertRaises(AssertionError): fixture.run()

    def test_real_A_replay_and_twenty_AFTER_dynamic_B_turn_cannot_be_substituted(self):
        for kind in ('replay','missing_samehead','tail','native_turn','render_turn'):
            fixture=Fixture()
            if kind == 'replay':
                for r in fixture.worker[1]: r.update(corrections=0,corrections_delta=0,replayed_frames_total=0,replayed_frames_delta=0)
            elif kind == 'missing_samehead':
                next(r for r in fixture.native if r['event'] == 'after_replay_same_head')['event']='native_cohort_positions'
            elif kind == 'tail': fixture.worker[1][373]['parsed_state_sha256']='0'*64
            elif kind == 'native_turn':
                for r in fixture.native:
                    if r['world'] == 1 and r['frame'] >= 351:
                        r['entities'][0].update(position=fixture.position(11,350),position_bits=bits(fixture.position(11,350)))
            else:
                def freeze(row):
                    if row['event'] in e.SNAPSHOTS and row['frame'] >= 351:
                        row['members'][0].update(position=fixture.view_position(11,350),position_bits=bits(fixture.view_position(11,350)))
                fixture.mutate_rows(1,freeze)
            with self.subTest(kind=kind),self.assertRaises(AssertionError): fixture.run()

    def test_persisted_proof_deletions_empty_interval_or_wrong_links_fail_closed(self):
        original=report(Fixture().run()); e.finalize(original,plan())
        for name in ('orders','A_replay','same_head','B_canonical_turn','B_native_turn','B_render_turn','B_after_turn_20','no_premature_B'):
            altered=deepcopy(original); del altered['queued_orders']['episodes'][0][name]
            with self.subTest(missing=name):
                self.assertFalse(e.gate(plan(),altered))
                with self.assertRaises(AssertionError): e.finalize(altered,plan())
        for mode in ('empty','render','frame','replay','error','lifetime'):
            altered=deepcopy(original); ep=altered['queued_orders']['episodes'][0]
            if mode == 'empty': ep['no_premature_B']['native_records']=[]
            elif mode == 'render': ep['no_premature_B']['render_samples']=0
            elif mode == 'frame': ep['B_confirmation_frame']-=1
            elif mode == 'replay': ep['A_replay']['input_actions']=[]
            elif mode == 'error': altered['error']='authored failure'
            else: altered['clients'][0]['natural_worker_shutdown']=False
            with self.subTest(mode=mode): self.assertFalse(e.gate(plan(),altered))

    def test_plan_and_actual_native_copy_are_bounded_and_strict(self):
        e.validate_plan(plan())
        for key,value in (('frames',649),('surrender_frame',260),('close_formation',True),('rtt_ms',[True,475]),('native_cohort_spec','1:1:130:360:8')):
            altered=plan(); altered[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError): e.validate_plan(altered)
        for frame in (130,440):
            state=Fixture.state(frame); self.assertEqual(e.native_observation(state,state_digest(state))['frame'],frame)
        self.assertIsNone(e.native_observation(dict(frame=441),None))
        state=Fixture.state(400); digest=state_digest(state); state['entities'].pop()
        with self.assertRaises(AssertionError): e.native_observation(state,digest)


if __name__ == '__main__': unittest.main()
