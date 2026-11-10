"""Authored retained-evidence controls; no native DLL/process is used."""
from copy import deepcopy
import json
import struct
import unittest

from server.game_data import encode_identity, encode_player_input
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint
from tools import prediction_mobile_evidence as mobile
from tools import verify_prediction_multiplayer as controller


def move(entity, target, ability=12):
    position = b''.join(field_uint(n, int(v * 2**32) & (2**64-1)) for n, v in enumerate(target, 1))
    group = field_uint(1, 1) + field_uint(2, ability) + field_packed_uint(3, [entity])
    return field_bytes(1, field_bytes(1, group) + field_bytes(3, field_bytes(3, field_bytes(1, position))))


class Fixture:
    """A complete synthetic capture joined through the real wire/state checkers."""
    def __init__(self):
        self.match = 'a'*32
        self.escape_action = move(10, [-32., 0., 0.])
        self.fresh_action = move(11, [21., 0., 0.])
        self.bodies = {(self.match, 0, 2): encode_player_input(encode_identity(1, 'Attacker'), [self.escape_action]),
                       (self.match, 1, 2): encode_player_input(encode_identity(2, 'Victim'), [self.fresh_action])}
        self.commits = [dict(event='command_batch_committed', match=self.match, slot=slot, sequence=2, frame=frame)
                        for slot, frame in ((0, 151), (1, 181))]
        self.journal = [dict(frame=f, players={0:[self.escape_action] if f == 151 else [],
                                             1:[self.fresh_action] if f == 181 else []}) for f in range(281)]
        self.hashes = {f:mobile.digest(str(f).encode()) for f in range(281)}
        self.wires = {f:mobile.digest(('wire'+str(f)).encode()) for f in (151, 181)}
        self.receipts = [dict(schema=1, world=2, match=self.match, frame=f, tick_ms=t,
            canonical_sha256=mobile.digest(('input'+str(f)).encode()), wire_sha256=self.wires[f])
            for f, t in ((151, 300), (181, 1700))]
        self.bridges = [dict(match=self.match, frame=f, received_tick_ms=t, payload_sha256=self.wires[f])
                        for f, t in ((151, 290), (181, 1680))]
        self.worker = []
        for f in range(281):
            tick = f if f < 151 else 330 if f <= 152 else 330+(f-152)*20 if f < 181 else 1710+(max(f,182)-182)*20
            self.worker.append(dict(schema=1, event='confirmed_native_state', world=2, frame=f,
                parsed_state_sha256=self.hashes[f], confirmed_frontier=152 if f == 151 else 182 if f == 181 else f,
                corrections=int(f >= 151), corrections_delta=int(f == 151),
                replayed_frames_total=10 if f >= 151 else 0, replayed_frames_delta=10 if f == 151 else 0,
                tick_ms=tick))
        self.native = [dict(frame=f, parsed_state_sha256=self.hashes[f],
            victim=dict(id=11, army=1, type=1, max_health=100, current_damage=0 if f < 142 else 50),
            attacker=dict(id=10, army=0, type=1, max_health=100,
                current_damage=0 if f < 142 else 50 if f < 153 else 100) if f <= 153 else None,
            game_state=dict(complete=False)) for f in range(130, 221)]
        self.rows = []
        for event, frame, tick in zip(mobile.EVENTS, (130,153,154,163,180,180,260), (100,200,220,350,1490,1491,6000)):
            active = event not in ('original_mobile_release_observed',)
            dead = event == 'native_dead_observed'
            row = dict(schema=1, event=event, world=2, match=self.match, entity=11, army=1, unit_type=1,
                frame=frame, completed_frame=frame, tick_ms=tick, sampled_us=tick*1000,
                original_actor='000001A0', current_actor='000001A0' if active else '0',
                original_incarnation=7, current_incarnation=7 if active else 0, original_actual_entity=11,
                old_dead_to_sim=dead, old_component_present=active, old_in_active=active, old_in_retained=False,
                current_in_active=active, current_admitted=active, native_identity_present=active,
                native_state_present=active, native_state=6 if dead else 1 if active else None,
                current_actual_entity=11 if active else None, current_actual_type=1 if active else None,
                current_actual_army=1 if active else None, native_identity_type=1 if active else None,
                native_identity_army=1 if active else None, selected_ids=[11] if active else [], preview_ids=[], casting_ids=[],
                casting_references_victim=False, active_caster='0', focus_actor='000001A0' if active and not dead else '0',
                focus_group=4 if active else -1, group_ids=[11], tracked_released_ids=[11] if not active else [],
                auto_type1=False, pending_commands=0, left_held=False, right_held=False, live_click_id=0,
                pool_callback_observed=False, physicalUI=False)
            row['selection_scope_player_initiated'] = (True if event=='original_mobile_selection_established' else
                False if event=='original_fresh_reselection_established' else None)
            has_focus=bool(int(row['focus_actor'],16))
            row.update(focus_class_name='Unit' if has_focus else None,focus_class_namespace='Uncapped' if has_focus else None,
                focus_is_unit=True if has_focus else None,focus_actual_entity=11 if has_focus else None,
                focus_actual_type=1 if has_focus else None,focus_actual_army=1 if has_focus else None,
                focus_dead_to_sim=False if has_focus else None,focus_component_present=True if has_focus else None,
                focus_in_active=True if has_focus else None,focus_in_retained=False if has_focus else None,
                focus_current_admitted=True if has_focus else None,focus_observed_incarnation=7 if has_focus else None,
                focus_confirmed_incarnation=7 if has_focus else None,focus_cached_ptr=0x1234 if has_focus else None,
                focus_unity_truth=True if has_focus else None,focus_is_active_and_enabled=True if has_focus else None,
                focus_unity_proof_error=None,focus_lookup_id_present=True if has_focus else None,
                focus_lookup_actor=row['focus_actor'] if has_focus else None,
                focus_lookup_source='manager-active-UnitSet-id-enumeration',focus_lookup_proof_error=None)
            self.rows.append(row)
        self.escape = dict(schema=1, event='original_escape_move', world=1, match=self.match, entity=10, army=0,
            unit_type=1, incarnation=4, ability=12, frame=150, tick_ms=190, sampled_us=190000,
            origin_sampled_us=189000, enqueue_sampled_us=191000, origin=[-2.,0.,0.], target=[-32.,0.,0.],
            target_bits=[struct.unpack('<I',struct.pack('<f',v))[0] for v in [-32.,0.,0.]],
            action_sha256=mobile.digest(self.escape_action), originalCtor=True, physicalUI=False,
            original_callback='Uncapped.ExecuteTargetGroundCommand..ctor', queueDelta=1, reselected_current=False)
        self.order = dict(schema=1, event='original_fresh_move', world=2, match=self.match, entity=11, army=1,
            unit_type=1, incarnation=7, ability=12, frame=180, tick_ms=1500, sampled_us=1500000,
            origin_sampled_us=1495000, enqueue_sampled_us=1501000, origin=[5.,0.,0.], target=[21.,0.,0.],
            target_bits=[struct.unpack('<I',struct.pack('<f',v))[0] for v in [21.,0.,0.]],
            action_sha256=mobile.digest(self.fresh_action), originalCtor=True, physicalUI=False,
            original_callback='Uncapped.ExecuteTargetGroundCommand..ctor', queueDelta=1, reselected_current=True)
        self.order.update(local_alliance=17,map_perspective=0,
            map_perspective_source='Uncapped.Map.GetAlliancePerspective',map_perspective_enum='Uncapped.Map.Perspective',
            map_perspective_enum_matches_ctor=True,map_perspective_normal=0,map_perspective_flipped=1,
            map_perspective_value_name='Normal')
        self.poses=[]
        self.fresh_assigned=181
        for us, baseline, x in [(1250000,True,5.),(1300000,True,5.),(1350000,True,5.),
                                (1400000,True,5.),(1450000,True,5.),(1494000,True,5.),
                                (1530000,False,5.1),(1550000,False,5.3)]:
            self.poses.append(dict(schema=1,event='transform',world=2,match=self.match,entity=11,unit_type=1,
                army=1,incarnation=7,frame=180 if us<1500000 else 181,tick_ms=us//1000,
                move_id=1,position=[x,0.,0.],sampled_us=us,presented_frame=180 if us<1500000 else 181,
                completed_frame=181,baseline=baseline,source='UnityEngine.Transform.get_position',jobsJoined=True,physicalUI=False))

    def sender(self, slot, order, assigned, tick):
        body=self.bodies[self.match,slot,2]
        return ('MOBILE ORDER '+json.dumps(order)+'\n'+
            f'Movement local batch registered: sequence=2 speculativeFrame={assigned} tick={tick} match={self.match}\n'+
            f'Original command batch submitted: match={self.match} sequence=2 actions=1 bytes={len(body)} '+
            f'body_sha256={mobile.digest(body)} sendTick={tick+1} sourceNextFrame={assigned}\n')

    def fresh_wire_target(self, target):
        self.fresh_action=move(11,target);self.order['action_sha256']=mobile.digest(self.fresh_action)
        self.bodies[self.match,1,2]=encode_player_input(encode_identity(2,'Victim'),[self.fresh_action])
        self.journal[181]['players'][1]=[self.fresh_action]

    def log(self):
        return ('\n'.join('MOBILE CORRECTION '+json.dumps(r) for r in self.rows)+'\n'+
                '\n'.join('MOBILE FEEL '+json.dumps(r) for r in self.poses)+'\n'+self.sender(1,self.order,self.fresh_assigned,1501))

    def evaluate(self, **changes):
        args=dict(attacker_log=self.sender(0,self.escape,151,191), match=self.match, commits=self.commits,
            raw_bodies=self.bodies,journal=self.journal,bridge_frames=self.bridges,canonical_payloads=self.wires,
            canonical_states=self.hashes,native_states=self.native,worker_states=self.worker,
            escape_check=controller.actor_escape_evidence,join_check=controller.joined_worker_evidence,
            authority_rows=self.receipts)
        args.update(changes)
        return mobile.evaluate(self.log(),**args)


class MobileEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture()

    def test_original_release_same_pointer_same_token_and_fresh_actual_response(self):
        r=self.f.evaluate()
        self.assertTrue(r['passed']);self.assertTrue(r['same_observed_pointer']);self.assertTrue(r['same_confirmed_token'])
        self.assertEqual(r['escape_native_replay']['promotion_group_replayed_delta'],10)
        self.assertEqual(r['fresh_native_confirmation']['continuation_frames'],20)
        self.assertEqual(r['fresh_motion']['response_after_enqueue_ms'],29)
        self.assertFalse(r['physicalUI']);self.assertFalse(r['full_feature_accepted'])
        self.assertFalse(r['inactive_casting_scratch_exercised']);self.assertFalse(r['active_caster_exercised'])
        self.assertEqual(r['observed_group_timeline'][2]['tracked_released_ids'],[11])
        self.assertEqual(r['observed_group_timeline'][3]['group_ids'],[11])
        self.assertEqual(r['group_intent_observation']['status'],'preserved')
        self.assertFalse(r['group_intent_observation']['full_mobile_controls_accepted'])

    def test_new_current_pointer_token_is_allowed_only_when_all_observations_match(self):
        f=self.f
        for r in f.rows[3:]:
            r.update(current_actor='BEEF',current_incarnation=9,focus_actor='BEEF')
            r.update(focus_lookup_actor='BEEF',focus_observed_incarnation=9,focus_confirmed_incarnation=9)
        f.order['incarnation']=9
        for r in f.poses:r['incarnation']=9
        r=f.evaluate();self.assertFalse(r['same_observed_pointer']);self.assertFalse(r['same_confirmed_token'])

    def test_inactive_focus_cache_and_original_group_contents_are_reported_without_emptying(self):
        # The -1 group marks an inactive cached reference; this is not an active
        # focus/current-mobile proof and must not be erased to make the test pass.
        f=self.f;f.rows[2].update(focus_actor='ABCD',focus_group=-1)
        r=f.evaluate()
        self.assertEqual(r['observed_group_timeline'][2]['focus_actor'],'ABCD')
        self.assertEqual(r['observed_group_timeline'][2]['tracked_released_ids'],[11])

    def test_release_is_observed_membership_and_component_not_callback_invention(self):
        for field in ('old_in_active','old_in_retained','old_component_present','pool_callback_observed'):
            with self.subTest(field=field):
                f=Fixture();f.rows[2][field]=True
                with self.assertRaises(AssertionError):f.evaluate()

    def test_missing_dead_release_or_reselection_fails(self):
        for index in (1,2,5):
            with self.subTest(index=index):
                f=Fixture();f.rows.pop(index)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_raw_focus_rejects_stale_pointer_unadmitted_or_wrong_native_identity(self):
        for changes in (dict(focus_actor='DEAD'),dict(current_admitted=False),dict(current_actual_type=3),
                        dict(native_identity_type=3),dict(current_incarnation=0)):
            with self.subTest(changes=changes):
                f=Fixture();f.rows[4].update(changes)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_transient_frontupdate_focus_cache_is_preserved_without_whole_frame_claim(self):
        f=self.f
        f.rows[1]['focus_actor']=f.rows[1]['original_actor']
        f.rows[2].update(focus_actor=f.rows[2]['original_actor'],focus_group=4)
        f.rows[3]['focus_actor']='DEAD'
        r=f.evaluate()
        self.assertEqual(r['rows'][2]['focus_actor'],f.rows[2]['original_actor'])
        self.assertTrue(all(item['transient_front_update']
                            for item in r['focus_observations'][1:4]))
        self.assertFalse(r['whole_unity_frame_focus_safety_claim'])
        f.rows[4]['focus_actor']='DEAD'
        with self.assertRaises(AssertionError):f.evaluate()

    def test_each_known_false_original_predicate_proves_cached_branch_inactive_despite_unknowns(self):
        keys=('focus_unity_truth','focus_lookup_id_present','focus_is_active_and_enabled')
        for false_key in keys:
            with self.subTest(false_key=false_key):
                f=Fixture();r=f.rows[4]
                r.update(focus_actor='ABCD',focus_group=4,focus_dead_to_sim=True,focus_component_present=False,
                    focus_in_active=False,focus_current_admitted=False,focus_observed_incarnation=0,
                    focus_lookup_actor=None,focus_unity_proof_error='one independent getter unobserved')
                r.update({key:False if key==false_key else None for key in keys})
                result=f.evaluate();focus=result['focus_observations'][4]
                self.assertEqual(focus['classification'],'would_not_focus_known_false')
                self.assertFalse(focus['would_focus_per_original_predicates'])
                self.assertFalse(focus['actual_camera_call_observed'])
                self.assertIsNone(focus['predicates'][next(k for k in keys if k!=false_key)])

    def test_group_number_and_raw_pointer_alone_cannot_fill_missing_stable_predicates(self):
        for group in (-1,4):
            with self.subTest(group=group):
                f=Fixture();r=f.rows[4];r['focus_group']=group
                r.update(focus_unity_truth=None,focus_lookup_id_present=None,focus_lookup_actor=None,
                         focus_is_active_and_enabled=None)
                with self.assertRaisesRegex(AssertionError,'stable original focus predicates missing'):
                    f.evaluate()

    def test_all_true_original_focus_predicates_require_complete_initialized_confirmed_camera_lease(self):
        for changes in (dict(focus_lookup_actor='BEEF'),dict(focus_actual_entity=None),
                        dict(focus_actual_type=0),dict(focus_actual_army=None),dict(focus_component_present=False),
                        dict(focus_dead_to_sim=True),dict(focus_in_active=False),
                        dict(focus_observed_incarnation=6),dict(focus_confirmed_incarnation=6),
                        dict(focus_cached_ptr=0),dict(focus_is_unit=False)):
            with self.subTest(changes=changes):
                f=Fixture();f.rows[4].update(changes)
                with self.assertRaises(AssertionError):f.evaluate()

    def camera_retarget(self, *, army=0, entity=0, unit_type=3):
        f=self.f
        for row in f.rows[3:]:
            row.update(focus_actor='F00',focus_lookup_actor='F00',focus_actual_entity=entity,
                focus_actual_type=unit_type,focus_actual_army=army,focus_current_admitted=False,
                focus_observed_incarnation=1,focus_confirmed_incarnation=1,group_ids=[],tracked_released_ids=[])
        return f

    def test_actual19_enemy_hq0_camera_is_valid_while_own_input_and_group_loss_stay_separate(self):
        f=self.camera_retarget();result=f.evaluate()
        self.assertTrue(result['passed'])
        retarget=result['camera_retarget_observations'][-1]
        self.assertEqual(retarget['target_identity'],dict(entity=0,unit_type=3,army=0))
        self.assertEqual(retarget['classification'],'would_focus_valid_camera_lease')
        self.assertFalse(retarget['facts']['focus_current_admitted'])
        self.assertFalse(retarget['own_input_admission_required'])
        self.assertFalse(retarget['actual_camera_call_observed'])
        self.assertEqual(result['fresh']['order']['entity'],11)
        self.assertEqual(result['fresh']['order']['army'],1)
        self.assertEqual(result['group_intent_observation']['status'],'lost')
        self.assertTrue(result['group_intent_observation']['followup_open'])

    def test_other_valid_camera_identity_allowed_but_mismatched_token_not(self):
        f=self.camera_retarget(army=1,entity=99,unit_type=75)
        self.assertTrue(f.evaluate()['passed'])
        f.rows[4]['focus_confirmed_incarnation']=2
        with self.assertRaisesRegex(AssertionError,'camera lease'):f.evaluate()

    def test_camera_permission_does_not_admit_enemy_or_changed_mobile_input(self):
        f=self.camera_retarget();f.order['army']=0
        with self.assertRaises(AssertionError):f.evaluate()
        f=self.camera_retarget();f.rows[4]['current_admitted']=False
        with self.assertRaises(AssertionError):f.evaluate()

    def test_initial_camera_setup_still_requires_original_owned_mobile(self):
        f=self.camera_retarget()
        f.rows[0].update(focus_actual_entity=0,focus_actual_type=3,focus_actual_army=0,
            focus_observed_incarnation=1,focus_confirmed_incarnation=1,focus_current_admitted=False)
        with self.assertRaisesRegex(AssertionError,'initial repeat-focus'):f.evaluate()

    def test_nullable_predicate_types_lookup_source_and_initial_positive_are_strict(self):
        for changes in (dict(focus_unity_truth=1),dict(focus_lookup_source='invented-TryGet'),
                        dict(focus_lookup_id_present=False,focus_lookup_actor='A0')):
            with self.subTest(changes=changes):
                f=Fixture();f.rows[4].update(changes)
                with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.rows[0]['focus_is_active_and_enabled']=False
        with self.assertRaisesRegex(AssertionError,'initial repeat-focus setup'):
            f.evaluate()

    def test_original_programmatic_fresh_selection_scope_is_not_a_physical_input_claim(self):
        f=self.f;f.rows[5]['selection_scope_player_initiated']=True
        with self.assertRaisesRegex(AssertionError,'programmatic selection scope'):
            f.evaluate()
        f=Fixture();f.rows[0]['selection_scope_player_initiated']=None
        with self.assertRaises(AssertionError):f.evaluate()

    def test_lost_original_group_intent_is_named_open_while_mobile_release_fresh_scope_can_pass(self):
        f=self.f
        for r in f.rows[3:]:r.update(group_ids=[],tracked_released_ids=[])
        result=f.evaluate();group=result['group_intent_observation']
        self.assertTrue(result['passed']);self.assertEqual(group['status'],'lost')
        self.assertTrue(group['followup_open']);self.assertFalse(group['full_mobile_controls_accepted'])
        self.assertTrue(group['same_confirmed_token'])
        self.assertEqual(result['observed_group_timeline'][-1]['group_ids'],[])

    def test_held_caster_and_scratch_are_outside_claimed_scope(self):
        for changes in (dict(active_caster='F00'),dict(left_held=True),dict(live_click_id=11),
                        dict(casting_ids=[11]),dict(casting_references_victim=True)):
            with self.subTest(changes=changes):
                f=Fixture();f.rows[0].update(changes)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_actual_dead_victim_or_missing_attacker_death_cannot_pass(self):
        for index, entity, damage in ((30,'victim',100),(23,'attacker',50)):
            with self.subTest(entity=entity):
                f=Fixture();f.native[index][entity]['current_damage']=damage
                with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.native[24]['attacker']=dict(id=10,army=0,type=1)
        with self.assertRaises(AssertionError):f.evaluate()

    def test_later_victim_damage_is_observed_not_frozen_beyond_qualified_control(self):
        f=self.f
        for row in f.native:
            if row['frame']>173:row['victim']['current_damage']=49
        self.assertTrue(f.evaluate()['passed'])
        f.native[50]['victim']['current_damage']=100
        with self.assertRaises(AssertionError):f.evaluate()

    def test_native_authority_gap_or_hash_mismatch_fails(self):
        f=self.f;f.native.pop(1)
        with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.native[2]['parsed_state_sha256']='0'*64
        with self.assertRaises(AssertionError):f.evaluate()

    def test_escape_arrival_cannot_precede_actual_death_or_wire_disagree(self):
        f=self.f;f.receipts[0]['tick_ms']=190
        with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.bridges[0]['payload_sha256']='f'*64
        with self.assertRaises(AssertionError):f.evaluate()

    def test_release_after_raw_bridge_and_same65_tick_keeps_actual18_style_ordering(self):
        f=self.f;f.rows[2].update(tick_ms=300,sampled_us=300100)
        result=f.evaluate();observation=result['release_receipt_observation']
        self.assertEqual(observation['release_tick_ms'],observation['actual_victim65_tick_ms'])
        self.assertGreater(observation['release_tick_ms'],observation['raw_bridge_tick_ms'])
        self.assertTrue(observation['same_quantized_tick'])
        self.assertEqual(result['escape_native_replay']['promotion_group_replayed_delta'],10)
        self.assertEqual(result['escape_native_replay']['continuation_frames'],20)

    def test_release_may_follow65_enqueue_but_must_precede_restored_view(self):
        f=self.f;f.rows[2].update(tick_ms=310,sampled_us=310000)
        self.assertTrue(f.evaluate()['passed'])
        f.rows[2].update(tick_ms=351,sampled_us=351000)
        with self.assertRaises(AssertionError):f.evaluate()

    def test_coalesced_replay_must_contain_own_frame_and_all_member_hashes(self):
        f=self.f;f.worker[152]['parsed_state_sha256']='0'*64
        with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.worker[151]['replayed_frames_delta']=0;f.worker[151]['corrections_delta']=0
        with self.assertRaises(AssertionError):f.evaluate()

    def test_unrelated_replay_group_input_and_missing_twenty_tail_fails(self):
        f=self.f;f.journal[152]['players'][1]=[b'other action']
        with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.worker=f.worker[:201]
        with self.assertRaises(AssertionError):f.evaluate()

    def test_fresh_original_body_target_source_and_float_bits_are_bound(self):
        for changes in (dict(entity=10),dict(target_bits=[0,0,0]),dict(incarnation=4),dict(originalCtor=False),
                        dict(queueDelta=2),dict(reselected_current=False),dict(target=[20.,0.,0.])):
            with self.subTest(changes=changes):
                f=Fixture();f.order.update(changes)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_nine_digit_float_json_and_subquantum_coordinate_preserve_original_bits(self):
        f=self.f
        origin=[mobile._f32(5.4253),0.,mobile._f32(-1e-10)]
        target=[mobile._f32(origin[0]+16),0.,origin[2]]
        # Match the source's setprecision(9), which is not exact binary64 text.
        f.order['origin']=[float(format(v,'.9g')) for v in origin]
        f.order['target']=[float(format(v,'.9g')) for v in target]
        f.order['target_bits']=[mobile._bits(v) for v in target]
        f.fresh_action=move(11,target);f.order['action_sha256']=mobile.digest(f.fresh_action)
        f.bodies[f.match,1,2]=encode_player_input(encode_identity(2,'Victim'),[f.fresh_action])
        f.journal[181]['players'][1]=[f.fresh_action]
        for row in f.poses:
            row['position']=[f.order['origin'][0]+row['position'][0]-5,0.,f.order['origin'][2]]
        r=f.evaluate()
        self.assertEqual(r['fresh']['target_quantization'][0]['difference_raw'],0)
        self.assertNotEqual(r['fresh']['target_quantization'][2]['difference_raw'],0)
        # A whole extra Q32 unit on an exactly representable axis is rejected.
        wrong=move(11,[target[0]+1/2**32,0.,target[2]])
        f.order['action_sha256']=mobile.digest(wrong)
        f.bodies[f.match,1,2]=encode_player_input(encode_identity(2,'Victim'),[wrong])
        f.journal[181]['players'][1]=[wrong]
        with self.assertRaises(AssertionError):f.evaluate()

    def test_json_negative_integer_zero_loses_sign_but_explicit_bits_remain_authoritative(self):
        f=self.f
        # The actual ostream spelling '-0' decodes to an unsigned Python int0.
        f.order['target'][1]=json.loads('-0');f.order['origin'][1]=json.loads('-0')
        f.order['target_bits'][1]=0x80000000
        r=f.evaluate()
        self.assertEqual(r['fresh']['json_zero_sign_loss_axes'],[1])
        self.assertIn('JSON cannot prove zero sign',r['fresh']['target_scope'])
        f.order['target_bits'][1]=0x80000001
        with self.assertRaises(AssertionError):f.evaluate()

    def test_flipped_original_perspective_maps_wire_xz_without_changing_unity_motion(self):
        f=self.f;f.order.update(map_perspective=1,map_perspective_value_name='Flipped')
        f.fresh_wire_target([-21.,0.,0.])
        result=f.evaluate();fresh=result['fresh']
        self.assertEqual(fresh['unity_target'],[21.,0.,0.])
        self.assertEqual(fresh['protocol_target_expected'],[-21.,0.,0.])
        self.assertEqual(fresh['target'],[-21.,0.,0.])
        self.assertEqual(fresh['perspective_proof']['local_alliance'],17)
        self.assertTrue(result['fresh_motion']['passed'])
        self.assertGreater(result['fresh_motion']['first_new_motion']['position'][0],f.order['origin'][0])

    def test_flipped_mapping_preserves_y_and_negates_nonzero_z(self):
        f=self.f;f.order.update(map_perspective=1,map_perspective_value_name='Flipped')
        f.order.update(origin=[5.,2.,3.],target=[21.,2.,3.],target_bits=[mobile._bits(v)for v in[21.,2.,3.]])
        for row in f.poses:row['position'][1:]=[2.,3.]
        f.fresh_wire_target([-21.,2.,-3.])
        result=f.evaluate();self.assertEqual(result['fresh']['target'],[-21.,2.,-3.])
        self.assertTrue(result['fresh_motion']['passed'])

    def test_original_perspective_enum_and_typed_getter_proof_are_required(self):
        for changes in (dict(map_perspective=2),dict(map_perspective=True),dict(local_alliance=-1),
                        dict(map_perspective_source='army-parity'),dict(map_perspective_enum='Other.Perspective'),
                        dict(map_perspective_enum_matches_ctor=False),dict(map_perspective_normal=1),
                        dict(map_perspective_flipped=0),dict(map_perspective_value_name='Flipped')):
            with self.subTest(changes=changes):
                f=Fixture();f.order.update(changes)
                with self.assertRaisesRegex(AssertionError,'Perspective proof'):f.evaluate()

    def test_wrong_enum_or_unmapped_wire_target_cannot_match_original_body(self):
        f=self.f;f.order.update(map_perspective=1,map_perspective_value_name='Flipped')
        with self.assertRaisesRegex(AssertionError,'fixed-point target'):f.evaluate()
        f=Fixture();f.fresh_wire_target([-21.,0.,0.])
        with self.assertRaisesRegex(AssertionError,'fixed-point target'):f.evaluate()

    def test_normal_old19_wrong_direction_is_not_hidden_by_perspective_binding(self):
        f=self.f
        for row in f.poses[-2:]:row['position'][0]=4.8
        with self.assertRaisesRegex(AssertionError,'no NEW targetward motion'):f.evaluate()

    def test_fresh_duplicate_or_multi_action_body_is_not_single_command_evidence(self):
        f=self.f;f.bodies[self.f.match,1,3]=f.bodies[self.f.match,1,2]
        with self.assertRaises(AssertionError):f.evaluate()

    def test_escape_single_action_and_whole_observed_window_exclude_other_motion_causes(self):
        f=self.f;f.bodies[f.match,0,2]=encode_player_input(encode_identity(1,'Attacker'),[f.escape_action,b'other'])
        # The real escape checker alone allows this matching action in a batch;
        # the mobile causal join must independently reject the second action.
        with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.journal[178]['players'][1]=[move(11,[99.,0.,0.])]
        with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.bodies[f.match,1,2]=encode_player_input(encode_identity(2,'Victim'),[f.fresh_action,b'other'])
        with self.assertRaises(AssertionError):f.evaluate()

    def test_actual67_sender_and_unique_canonical_commit_required(self):
        for kind in ('phase','sender','journal'):
            with self.subTest(kind=kind):
                f=Fixture()
                if kind=='phase':f.commits[1]['frame']=184
                elif kind=='sender':f.order['tick_ms']=1600
                else:f.journal[182]['players'][1]=[f.fresh_action]
                with self.assertRaises(AssertionError):f.evaluate()

    def test_prior_motion_sparse_baseline_or_nonresponse_is_not_fresh_latency(self):
        for kind in ('moving','sparse','late','wrong_direction','clock','old_token'):
            with self.subTest(kind=kind):
                f=Fixture()
                if kind=='moving':f.poses[2]['position'][0]=4.7
                elif kind=='sparse':f.poses=f.poses[-3:]
                elif kind=='late':
                    for r in f.poses[-2:]:r.update(sampled_us=r['sampled_us']+300000,tick_ms=r['tick_ms']+300)
                elif kind=='wrong_direction':
                    for r in f.poses[-2:]:r['position'][0]=4.8
                elif kind=='clock':f.poses[-1]['sampled_us']=f.poses[-2]['sampled_us']
                else:f.poses[-1]['incarnation']=1
                with self.assertRaises(AssertionError):f.evaluate()

    def early_fresh(self):
        f=self.f;f.commits[1]['frame']=182
        f.journal[181]['players'][1]=[];f.journal[182]['players'][1]=[f.fresh_action]
        f.receipts[1]['frame']=182;f.receipts[1]['wire_sha256']=f.wires[182]=f.wires.pop(181)
        f.bridges[1]['frame']=182
        for row in f.worker[181:]:
            row['corrections']=2;row['replayed_frames_total']=13
        f.worker[181].update(confirmed_frontier=181,corrections_delta=1,replayed_frames_delta=3,tick_ms=1650)
        return f

    def test_fresh_early_empty_repair_needs_no_invented_postcanonical_replay(self):
        f=self.early_fresh();r=f.evaluate()
        self.assertEqual(r['fresh']['speculative_minus_canonical_frames'],-1)
        self.assertEqual(r['fresh_native_confirmation']['promotion_group_replayed_delta'],0)
        self.assertEqual(r['fresh_assignment_span']['frames_checked'],22)
        self.assertEqual((r['fresh_assignment_span']['first_frame'],r['fresh_assignment_span']['last_frame']),(181,202))
        self.assertFalse(r['fresh_repair_attribution_claim'])

    def test_fresh_wrong_assigned_state_rejected_even_when_canonical_plus_twenty_match(self):
        f=self.early_fresh();f.worker[181]['parsed_state_sha256']='0'*64
        with self.assertRaisesRegex(AssertionError,'assigned-to-canonical'):
            f.evaluate()

    def test_fresh_nonzero_phase_accepts_its_exact_positive_replay_plus_twenty(self):
        f=self.f;f.fresh_assigned=182
        for row in f.worker[181:]:
            row['corrections']=2;row['replayed_frames_total']=13
        f.worker[181].update(corrections_delta=1,replayed_frames_delta=3)
        r=f.evaluate()
        self.assertEqual(r['fresh']['speculative_minus_canonical_frames'],1)
        self.assertEqual(r['fresh_native_confirmation']['promotion_group_replayed_delta'],3)

    def test_bounded_schema_duplicate_events_and_nan_rejected(self):
        f=self.f;f.rows.insert(0,deepcopy(f.rows[0]))
        with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.poses[0]['position'][0]=float('nan')
        with self.assertRaises(AssertionError):f.evaluate()
        f=Fixture();f.rows[0]['world']=True
        with self.assertRaises(AssertionError):f.evaluate()


class GroupFixture:
    def __init__(self, user_edits=False):
        self.user_edits=user_edits;self.episodes=[];self.victim=[];self.attacker=[]
        for world in(1,2):
            f=Fixture();match=str(world)*32
            for row in [*f.rows,*f.poses,*f.receipts,*f.worker,f.order]:row['world']=world
            f.escape['world']=world
            for row in [*f.rows,*f.poses,*f.receipts,*f.bridges,*f.commits,f.order,f.escape]:row['match']=match
            f.bodies={(match,slot,seq):body for(_,slot,seq),body in f.bodies.items()}
            f.match=match
            if user_edits:
                for row in f.rows[3:]:row['group_ids']=[]
            ep=f.evaluate();self.episodes.append(ep)
            token=ep['rows'][0]['original_incarnation']
            def row(event,slot,frame,us,ids,confirmed,present,admitted):
                return dict(schema=1,event=event,world=world,match=match,slot=slot,frame=frame,tick_ms=us//1000,
                    sampled_us=us,entity=10 if slot==0 else 11,unit_type=1,army=slot,
                    incarnation=f.escape['incarnation']if slot==0 else token,confirmed_incarnation=confirmed,
                    native_identity_present=present,current_admitted=admitted,retained_group=4,
                    retained_ids=ids,retained_tracked_ids=[],operation=None,original_scope_player_initiated=None,
                    clear_callback=None,replace_callback=None,replace_source_count=None,replace_existing=None,physicalUI=False)
            victim=[row('setup',1,130,100010,[11],token,True,True),
                    row('before_user_edits'if user_edits else'before_provisional_hold',1,154,225000,[11],token,False,False)]
            if user_edits:
                edit=row('after_user_edits',1,154,225100,[],token,False,False)
                edit.update(operation='clear'if world==1 else'replace',original_scope_player_initiated=True)
                if world==1:edit['clear_callback']='Uncapped.ControlGroup.Clear'
                else:edit.update(replace_callback='Uncapped.ControlGroupPanel.AssignToControlGroup',replace_source_count=0,replace_existing=True)
                victim.append(edit)
            expected=[]if user_edits else[11]
            victim.extend([row('restored',1,163,350010,expected,token,True,True),
                           row('complete',1,260,5999990,expected,token,True,True)])
            a_token=f.escape['incarnation']
            attacker=[row('attacker_setup',0,130,100010,[10],a_token,True,True),
                      row('attacker_speculative_absence',0,154,240000,[10],a_token,False,False),
                      row('attacker_confirmed_purge',0,155,320000,[],0,False,False),
                      row('attacker_complete',0,220,4500000,[],0,False,False)]
            self.victim.extend(victim);self.attacker.extend(attacker)

    def evaluate(self):
        log=lambda rows:'\n'.join('MOBILE GROUP INTENT '+json.dumps(r)for r in rows)
        return mobile.evaluate_group_intent(log(self.victim),attacker_log=log(self.attacker),
            mobile_episodes=self.episodes,user_edits=self.user_edits)


class GroupIntentEvidenceTests(unittest.TestCase):
    def test_single_manual_group_preserved_both_rounds_and_true_attacker_death_purged(self):
        f=GroupFixture();r=f.evaluate()
        self.assertTrue(r['passed']);self.assertFalse(r['user_edits'])
        self.assertEqual(len(r['episodes']),2)
        self.assertTrue(all(ep['retained_group4_preserved']and ep['attacker_confirmed_numeric_membership_purged']for ep in r['episodes']))
        self.assertFalse(r['full_mobile_controls_accepted']);self.assertFalse(r['physicalUI'])
        self.assertTrue(r['requires_controller_full_closed_native_parity'])
        self.assertTrue(all(row['retained_group']==4 for ep in r['episodes']for row in ep['attacker_rows']))

    def test_unsupported_attacker_group7_is_not_accepted_as_the_separate_client_group4(self):
        f=GroupFixture();f.attacker[0]['retained_group']=7
        with self.assertRaisesRegex(AssertionError,'manual group differs'):f.evaluate()

    def test_original_clear_and_empty_replace_are_separate_actual_worlds_never_readded(self):
        f=GroupFixture(True);r=f.evaluate()
        self.assertTrue(r['passed']);self.assertEqual([e['original_user_operation']for e in r['episodes']],['clear','replace'])
        self.assertTrue(all(e['user_cancellation_respected']for e in r['episodes']))
        self.assertTrue(all(ep['group_intent_observation']['status']=='lost'for ep in f.episodes))

    def test_lost_preserved_group_or_readded_cancelled_group_cannot_pass(self):
        f=GroupFixture();f.victim[2]['retained_ids']=[]
        with self.assertRaises(AssertionError):f.evaluate()
        f=GroupFixture(True);f.victim[3]['retained_ids']=[11]
        with self.assertRaises(AssertionError):f.evaluate()

    def test_mobile_snapshot_and_group_observation_cannot_disagree(self):
        f=GroupFixture();f.episodes[0]['rows'][3]['group_ids']=[]
        with self.assertRaises(AssertionError):f.evaluate()

    def test_partial_or_failed_mobile_body_motion_replay_cannot_be_substituted(self):
        for kind in('partial','mobile','motion','replay','hash'):
            with self.subTest(kind=kind):
                f=GroupFixture()
                if kind=='partial':f.episodes.pop()
                elif kind=='mobile':f.episodes[0]['passed']=False
                elif kind=='motion':f.episodes[0]['fresh_motion']['passed']=False
                elif kind=='replay':f.episodes[0]['escape_native_replay']['promotion_group_replayed_delta']=0
                else:f.episodes[0]['fresh_assignment_span']['hashes_match']=False
                with self.assertRaises(AssertionError):f.evaluate()

    def test_wrong_clear_replace_callback_source_or_user_scope_is_rejected(self):
        for index,change in((2,dict(clear_callback=None)),(2,dict(original_scope_player_initiated=None)),
                           (7,dict(replace_source_count=1)),(7,dict(replace_existing=False)),
                           (7,dict(replace_callback='invented')),(7,dict(clear_callback='Uncapped.ControlGroup.Clear'))):
            with self.subTest(change=change):
                f=GroupFixture(True);f.victim[index].update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_round_specific_edit_and_actual_native_absence_are_required(self):
        f=GroupFixture(True);f.victim[2].update(operation='replace',clear_callback=None,
            replace_callback='Uncapped.ControlGroupPanel.AssignToControlGroup',replace_source_count=0,replace_existing=True)
        with self.assertRaises(AssertionError):f.evaluate()
        f=GroupFixture(True);f.victim[2]['native_identity_present']=True
        with self.assertRaises(AssertionError):f.evaluate()

    def test_provisional_victim_and_attacker_tokens_must_remain_exact_incarnation(self):
        for target in('victim','attacker'):
            with self.subTest(target=target):
                f=GroupFixture();getattr(f,target)[1]['confirmed_incarnation']=0
                with self.assertRaises(AssertionError):f.evaluate()

    def test_real_confirmed_death_must_purge_and_stay_purged(self):
        for index,change in((2,dict(confirmed_incarnation=4)),(2,dict(retained_ids=[10])),
                           (3,dict(retained_ids=[10])),(3,dict(current_admitted=True))):
            with self.subTest(change=change):
                f=GroupFixture();f.attacker[index].update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_native_authority_death_survival_evidence_is_required(self):
        f=GroupFixture();f.episodes[0]['native_authority_timeline'][23]['attacker']['current_damage']=50
        with self.assertRaises(AssertionError):f.evaluate()
        f=GroupFixture();f.episodes[0]['native_authority_timeline'][24]['victim']['current_damage']=100
        with self.assertRaises(AssertionError):f.evaluate()

    def test_no_invented_empty_tracked_set_or_physical_ui_claim(self):
        f=GroupFixture();f.attacker[2]['retained_tracked_ids']=[10]
        r=f.evaluate();self.assertEqual(r['episodes'][0]['attacker_tracked_ids_after_purge'][0],[10])
        self.assertFalse(r['episodes'][0]['full_mobile_controls_accepted'])
        f.attacker[2]['physicalUI']=True
        with self.assertRaises(AssertionError):f.evaluate()

    def test_extra_match_duplicate_event_wrong_world_and_malformed_flags_rejected(self):
        for kind in('match','duplicate','world','bool'):
            with self.subTest(kind=kind):
                f=GroupFixture()
                if kind=='match':f.victim[0]['match']='f'*32
                elif kind=='duplicate':f.victim.insert(0,deepcopy(f.victim[0]))
                elif kind=='world':f.attacker[0]['world']=99
                else:f.victim[0]['current_admitted']=1
                with self.assertRaises(AssertionError):f.evaluate()

    def test_second_attacker_world_cannot_reuse_first_even_if_both_captures_are_relabelled(self):
        f=GroupFixture();f.episodes[1]['escape']['order']['world']=1
        for row in f.attacker[4:]:row['world']=1
        with self.assertRaisesRegex(AssertionError,'attacker escape world reused'):f.evaluate()


class UICastFixture(Fixture):
    """Synthetic queue/normal-wire evidence, not a real cast execution."""
    def __init__(self,world=2,match='a'*32):
        super().__init__();self.match=match
        self.offset_us=0;self.prior_log=''
        for row in [*self.rows,*self.poses,*self.receipts,*self.worker,self.order]:row['world']=world
        self.escape['world']=world
        for row in [*self.rows,*self.receipts,*self.bridges,*self.commits,self.escape]:row['match']=match
        self.bodies={(match,slot,seq):body for(_,slot,seq),body in self.bodies.items()}
        self.set_wire([21.,0.,0.]);self.ui=[]
        self.rows[4]['event']='before_ui_cast';self.rows[5].update(event='original_ui_cast_queued',tick_ms=1495,sampled_us=1495000)
        for row in self.rows:
            if row['event']!='original_mobile_selection_established':row['selection_scope_player_initiated']=None
            if 145<=row['frame']<180:row['active_caster']='A100'
            if row['frame']>=180:row.update(casting_ids=[11],casting_references_victim=True)
        self.rows[4]['active_caster']='A100';self.rows[4].update(casting_ids=[],casting_references_victim=False)
        self.rows[5]['pending_commands']=1
        self.residue=dict(schema=1,event='preactivation',world=world,match=match,slot=1,entity=11,frame=130,tick_ms=99,sampled_us=99000,
            casting_set='2000',casting_ids=[],casting_count=0,casting_references_victim=False,typed_member11=False,typed_proof_error=None,
            casting_frame_collection='4000',current_frame_collection='4000',frame_owner_matches=True,active_caster='0',pending_commands=0,
            left_held=False,right_held=False,click_reference=0,prior_completed_world=0,prior_match=None,prior_normal_drain_complete=False,
            prior_next_sequence_before=None,prior_next_sequence_after=None,prior_complete_frame=None,policy_result='strict_empty',
            physicalUI=False,scope='inactive_scratch_only_not_admission')
        def row(event,frame,us):
            activated=event!='before_activation';pre=us<1494000;alive=event!='release_observed'
            target=us>=1492000;queued=us>=1494000;drained=us>=1510000
            current='A100'if activated and pre else'0';perspective=activated
            value=dict(schema=1,event=event,world=world,match=match,slot=1,entity=11,unit_type=1,army=1,frame=frame,
                tick_ms=us//1000,sampled_us=us,button_slot=4,config_id=88,ui_cast_type=5,ui_group_kind=2,smart_casting=False,
                retained_caster='A100'if activated else'0',retained_caster_class='Uncapped.TargetGroundOrUnitAbilityCaster'if activated else None,
                active_caster=current,active_caster_class='Uncapped.TargetGroundOrUnitAbilityCaster'if int(current,16)else None,
                same_retained=bool(int(current,16)),is_unit_selection_related=True if int(current,16)else None,
                source_set='1000',casting_set='2000',command_queue='3000',alias_storage_unchanged=True,
                source_ids=[11],source_count=1 if alive else 0,casting_ids=[11]if queued else[],casting_count=int(queued),
                pending_commands=int(queued and not drained and event!='snapshot'),activation_calls=int(activated),cast_calls=int(queued),drain_observed=drained,
                next_sequence_before_cast=2 if target else None,next_sequence_after_drain=3 if drained else None,cast_result=True if queued else None,
                origin=[5.,0.,0.]if target else None,origin_bits=[mobile._bits(v)for v in[5.,0.,0.]]if target else None,
                target=[21.,0.,0.]if target else None,target_bits=[mobile._bits(v)for v in[21.,0.,0.]]if target else None,
                origin_sampled_us=1491000 if target else None,minimap_call_begin_us=1492010 if queued else None,minimap_call_end_us=1493900 if queued else None,
                local_alliance=17 if perspective else None,map_perspective=0 if perspective else None,composite_map_perspective=0 if perspective else None,
                composite_queue_cast_before=False if perspective else None,perspective_observed_frame=(180 if target else 145)if perspective else None,
                map_perspective_source='Uncapped.Map.GetAlliancePerspective',composite_map_perspective_source='Uncapped.CompositeAbilityCaster.get_MapPerspective',
                map_perspective_enum='Uncapped.Map.Perspective',map_perspective_enum_matches_composite=True if perspective else None,
                map_perspective_normal=0,map_perspective_flipped=1,map_perspective_value_name='Normal'if perspective else None,
                selector_append=False,left_held=False,right_held=False,click_reference=0,native_identity_present=alive,
                native_state=None if not alive else 6 if event=='native_dead'else 1,current_actor='A0'if alive else'0',
                current_admitted=alive,original_incarnation=7,current_incarnation=7 if alive else 0,
                route='original_ui_minimap',original_callback='Uncapped.UnitSelector.ProcessActiveAbilityCaster_Minimap',original_callback_token=0x0600222a,
                originalCtor=False,extra_pop_calls=0,extra_to_proto_calls=0,manual_caster_set_calls=0,direct_factory_calls=0,physicalUI=False)
            if alive:value['current_actor']=self.rows[3]['current_actor']
            self.ui.append(value)
        for name,frame,us in [('before_activation',145,150000),('after_activation',145,151000),('snapshot',152,195000),
            ('native_dead',153,200001),('release_observed',154,220001),('restored',163,350001),('before_cast',180,1492000),
            ('after_cast_queued',180,1494000),('snapshot',181,1509000),('normal_drain_observed',181,1510000),('complete',260,5999999)]:row(name,frame,us)

    def set_wire(self,target,ability=88):
        self.fresh_action=move(11,target,ability);self.bodies[self.match,1,2]=encode_player_input(encode_identity(2,'Victim'),[self.fresh_action])
        self.journal[181]['players'][1]=[self.fresh_action]

    def log(self):
        items=[(r['sampled_us'],'MOBILE CORRECTION '+json.dumps(r))for r in self.rows]
        items.extend((r['sampled_us'],'MOBILE UI CAST '+json.dumps(r))for r in self.ui)
        items.append((self.residue['sampled_us'],'MOBILE UI RESIDUE '+json.dumps(self.residue)))
        body=self.bodies[self.match,1,2]
        offset=self.offset_us;tick=offset//1000
        items.extend([(1501000+offset,f'Movement local batch registered: sequence=2 speculativeFrame={self.fresh_assigned} tick={1501+tick} match={self.match}'),
            (1502000+offset,f'Original command batch submitted: match={self.match} sequence=2 actions=1 bytes={len(body)} body_sha256={mobile.digest(body)} sendTick={1502+tick} sourceNextFrame=181')])
        return self.prior_log+'\n'+'\n'.join(line for _,line in sorted(items))

    def incoming_residue(self):
        previous=UICastFixture(world=1,match='1'*32);self.prior_log=previous.log();offset=10000000;self.offset_us=offset
        for r in[*self.rows,*self.ui,self.residue]:
            r['sampled_us']+=offset;r['tick_ms']+=offset//1000
            for key in('origin_sampled_us','minimap_call_begin_us','minimap_call_end_us'):
                if key in r and r[key]is not None:r[key]+=offset
        for r in self.receipts:r['tick_ms']+=offset//1000
        for r in self.bridges:r['received_tick_ms']+=offset//1000
        for r in self.worker:r['tick_ms']+=offset//1000
        self.escape['tick_ms']+=offset//1000
        for key in('origin_sampled_us','sampled_us','enqueue_sampled_us'):self.escape[key]+=offset
        self.residue.update(casting_ids=[11],casting_count=1,casting_references_victim=True,typed_member11=True,
            prior_completed_world=1,prior_match=previous.match,prior_normal_drain_complete=True,prior_next_sequence_before=2,
            prior_next_sequence_after=3,prior_complete_frame=260,policy_result='prior_drained_residue')
        for r in self.rows:
            if r['frame']<=180:r.update(casting_ids=[11],casting_references_victim=True)
        for r in self.ui:
            if r['cast_calls']==0:r.update(casting_ids=[11],casting_count=1)
        return self

    def evaluate(self,**changes):
        args=dict(attacker_log=self.sender(0,self.escape,151,191+self.offset_us//1000),match=self.match,commits=self.commits,raw_bodies=self.bodies,journal=self.journal,
            bridge_frames=self.bridges,canonical_payloads=self.wires,canonical_states=self.hashes,native_states=self.native,worker_states=self.worker,
            escape_check=controller.actor_escape_evidence,join_check=controller.joined_worker_evidence,authority_rows=self.receipts)
        args.update(changes);return mobile.evaluate_ui_cast(self.log(),**args)


class UICastEvidenceTests(unittest.TestCase):
    def test_rematch_inactive11_is_bound_to_prior_normal_drain_and_current_frame_owner_without_same_storage_claim(self):
        f=UICastFixture(world=2,match='2'*32).incoming_residue();result=f.evaluate()['ui_command']['preactivation_residue']
        self.assertEqual(result['row']['casting_ids'],[11]);self.assertEqual(result['prior_drain']['next_after'],3)
        self.assertIn('no cross-world same-storage',result['scope'])
        # A current-world storage address need not equal a prior-world address.
        f.residue['casting_set']='5000'
        for r in f.ui:r['casting_set']='5000'
        self.assertTrue(f.evaluate()['passed'])

    def test_rematch_residue_rejects_missing_completed_drain_extra_ids_stale_owner_active_or_pending_input(self):
        for kind in('missingprior','priorsequence','priorcomplete','ids','typed','owner','active','queue','held','proofmissing'):
            with self.subTest(kind=kind):
                f=UICastFixture(world=2,match='2'*32).incoming_residue()
                if kind=='missingprior':f.prior_log=''
                elif kind=='priorsequence':f.residue['prior_next_sequence_after']=4
                elif kind=='priorcomplete':f.residue['prior_complete_frame']=261
                elif kind=='ids':f.residue['casting_ids']=[11,12]
                elif kind=='typed':f.residue['typed_member11']=None
                elif kind=='owner':f.residue['casting_frame_collection']='9999'
                elif kind=='active':f.residue['active_caster']='A100'
                elif kind=='queue':f.residue['pending_commands']=1
                elif kind=='held':f.residue['left_held']=True
                else:f.residue['typed_proof_error']='unknown original typed cache'
                with self.assertRaises(AssertionError):f.evaluate()

    def test_strict_empty_requires_original_typed_empty_and_residue_does_not_relax_old_move_or_lifetime(self):
        f=UICastFixture();f.residue['typed_member11']=True
        with self.assertRaises(AssertionError):f.evaluate()
        f=UICastFixture(world=1,match='1'*32);f.residue.update(casting_ids=[11],casting_count=1,typed_member11=True,policy_result='prior_drained_residue')
        with self.assertRaises(AssertionError):f.evaluate()
        f=UICastFixture(world=2,match='2'*32).incoming_residue()
        with self.assertRaises(AssertionError):mobile._snapshots(f.log(),f.match)
        old=Fixture();old.rows[0].update(casting_ids=[11],casting_references_victim=True)
        with self.assertRaises(AssertionError):old.evaluate()

    def test_original_ui_queue_serialize_and_authority_without_predicted_move_claim(self):
        f=UICastFixture();r=f.evaluate();ui=r['ui_command']
        self.assertTrue(r['passed']);self.assertFalse(r['movement_feel_exercised']);self.assertNotIn('fresh',r)
        self.assertFalse(ui['prediction_exercised']);self.assertFalse(ui['constructor_callback_claim'])
        self.assertEqual(ui['sequence'],2);self.assertEqual(ui['native_confirmation']['continuation_frames'],20)
        self.assertEqual(r['escape_native_replay']['promotion_group_replayed_delta'],10)
        self.assertEqual(r['rows'][-1]['casting_ids'],[11]);self.assertFalse(r['full_mobile_controls_accepted'])

    def test_opaque_registration_hint_is_reported_without_phase_or_preauthority_motion_claim(self):
        f=UICastFixture();f.fresh_assigned=190;r=f.evaluate()['ui_command']
        self.assertEqual(r['registration_minus_canonical_frames'],9);self.assertFalse(r['prediction_exercised'])
        with self.assertRaises(AssertionError):Fixture().evaluate(caster_lifetime=True)

    def test_flipped_composite_runtime_enum_maps_actual_wire_without_changing_unity_target(self):
        f=UICastFixture();f.set_wire([-21.,0.,0.])
        for r in f.ui:
            if r['map_perspective']is not None:r.update(map_perspective=1,composite_map_perspective=1,map_perspective_value_name='Flipped')
        result=f.evaluate()['ui_command'];self.assertEqual(result['protocol_target_expected'],[-21.,0.,-0.]);self.assertEqual(result['unity_target'],[21.,0.,0.])
        f.set_wire([21.,0.,0.])
        with self.assertRaisesRegex(AssertionError,'normal ToProto target'):f.evaluate()

    def test_precommand145_and180_composite_default_can_differ_from_map_but_body_must_match_actual_map(self):
        f=UICastFixture();f.set_wire([-21.,0.,0.])
        for row in f.ui:
            if row['map_perspective']is not None:
                row.update(map_perspective=1,composite_map_perspective=0,map_perspective_value_name='Flipped')
        result=f.evaluate()['ui_command']
        self.assertEqual(result['protocol_target_expected'],[-21.,0.,-0.])
        proof=result['original_ui_rows']
        self.assertEqual({r['perspective_observed_frame']for r in proof if r['map_perspective']is not None},{145,180})
        self.assertTrue(all(r['map_perspective_enum_matches_composite']for r in proof if r['map_perspective']is not None))
        f.set_wire([21.,0.,0.])
        with self.assertRaisesRegex(AssertionError,'normal ToProto target'):f.evaluate()
        f.set_wire([-21.,0.,0.])
        for row in f.ui:
            if row['composite_map_perspective']is not None:row['composite_map_perspective']=2
        with self.assertRaisesRegex(AssertionError,'map enum proof'):f.evaluate()

    def test_queue_true_alone_missing_drain_or_false_alias_cannot_prove_command_ownership(self):
        for change in(dict(pending_commands=0),dict(cast_result=False),dict(alias_storage_unchanged=False),dict(active_caster='A100'),dict(casting_ids=[])):
            with self.subTest(change=change):
                f=UICastFixture();next(r for r in f.ui if r['event']=='after_cast_queued').update(change)
                with self.assertRaises(AssertionError):f.evaluate()
        f=UICastFixture();f.ui=[r for r in f.ui if r['event']!='normal_drain_observed']
        with self.assertRaises(AssertionError):f.evaluate()

    def test_lazy_storage_and_ids_cannot_change_until_original_normal_serialize(self):
        for change in(dict(source_set='9999'),dict(casting_set='9999'),dict(command_queue='9999'),dict(source_ids=[]),dict(casting_ids=[])):
            with self.subTest(change=change):
                f=UICastFixture();next(r for r in f.ui if r['event']=='normal_drain_observed').update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_sequence_normal_body_and_canonical_commit_are_not_substituted(self):
        for kind in('sequence','wrongability','wiretarget','body','duplicate','canonical'):
            with self.subTest(kind=kind):
                f=UICastFixture()
                if kind=='sequence':f.ui[-2]['next_sequence_after_drain']=4
                elif kind=='wrongability':f.set_wire([21.,0.,0.],12)
                elif kind=='wiretarget':f.set_wire([22.,0.,0.])
                elif kind=='body':f.bodies[f.match,1,2]=encode_player_input(encode_identity(2,'Victim'),[f.fresh_action,f.fresh_action])
                elif kind=='duplicate':f.journal[182]['players'][1]=[f.fresh_action]
                else:f.commits[-1]['frame']=182
                with self.assertRaises(AssertionError):f.evaluate()

    def test_same_retained_class_current_source_and_no_extra_fixture_calls_mandatory(self):
        for change in(dict(retained_caster='B100'),dict(retained_caster_class='Wrong.Class'),dict(current_incarnation=8),dict(source_count=0),
                      dict(extra_pop_calls=1),dict(extra_to_proto_calls=1),dict(manual_caster_set_calls=1),dict(originalCtor=True),dict(selector_append=True),dict(composite_queue_cast_before=True)):
            with self.subTest(change=change):
                f=UICastFixture();next(r for r in f.ui if r['event']=='before_cast').update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_actual_origin_target_bits_map_provenance_and_call_clocks_required(self):
        for change in(dict(target_bits=[mobile._bits(22.),0,0]),dict(map_perspective_enum_matches_composite=False),
                      dict(composite_map_perspective_source='Uncapped.AbilityCaster.get_MapPerspective'),dict(map_perspective=1),dict(origin_sampled_us=1493000)):
            with self.subTest(change=change):
                f=UICastFixture();next(r for r in f.ui if r['event']=='before_cast').update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_pending_and100_exceptions_are_only_in_validated_ui_phase_old_modes_stay_strict(self):
        f=UICastFixture()
        with self.assertRaises(AssertionError):mobile._snapshots(f.log(),f.match)
        for kind in('beforequeue','afterdrain','postcaster','missingwitness'):
            with self.subTest(kind=kind):
                f=UICastFixture()
                if kind=='beforequeue':f.rows[1]['pending_commands']=1
                elif kind=='afterdrain':f.rows[-1]['pending_commands']=1
                elif kind=='postcaster':f.rows[-1]['active_caster']='A100'
                else:f.ui.pop()
                with self.assertRaises(AssertionError):f.evaluate()

    def test_real_escape_replay_wire_native_hash_and_ui_twenty_tail_stay_required(self):
        for kind in('escape','wire','hash','tail','death'):
            with self.subTest(kind=kind):
                f=UICastFixture()
                if kind=='escape':f.worker[151]['replayed_frames_delta']=0
                elif kind=='wire':f.bridges[-1]['payload_sha256']='0'*64
                elif kind=='hash':f.worker[181]['parsed_state_sha256']='0'*64
                elif kind=='tail':f.worker=[r for r in f.worker if r['frame']!=202]
                else:f.native[24]['attacker']={'id':10}
                with self.assertRaises(AssertionError):f.evaluate()

    def test_preserved_groups_can_use_explicit_ui_native_witness_but_not_fake_move_motion(self):
        base=GroupFixture();episodes=[UICastFixture(world=i,match=str(i)*32).evaluate()for i in(1,2)]
        text=lambda rows:'\n'.join('MOBILE GROUP INTENT '+json.dumps(r)for r in rows)
        args=dict(attacker_log=text(base.attacker),mobile_episodes=episodes)
        result=mobile.evaluate_group_intent(text(base.victim),ui_cast=True,**args)
        self.assertTrue(result['passed']);self.assertTrue(result['active_casting_exercised'])
        with self.assertRaises(AssertionError):mobile.evaluate_group_intent(text(base.victim),**args)
        episodes[0]['ui_command']['native_confirmation']['continuation_frames']=0
        with self.assertRaises(AssertionError):mobile.evaluate_group_intent(text(base.victim),ui_cast=True,**args)


class CasterLifetimeFixture:
    """Authored original-event observations; these are not native runtime proof."""
    def __init__(self, relation='same'):
        base=GroupFixture();self.episodes=base.episodes;self.groups=base.evaluate();self.rows=[];self.attacker=''
        for ep in self.episodes:
            ep['active_caster_exercised']=True
            world=ep['world'];offset=(world-1)*10000000
            if offset:
                for row in ep['rows']:row['sampled_us']+=offset;row['tick_ms']+=offset//1000
                for key in('origin_sampled_us','sampled_us','enqueue_sampled_us'):ep['fresh']['order'][key]+=offset
            self.rows.extend(self.make_rows(ep,relation))

    @staticmethod
    def make_rows(ep,relation='same'):
        source={r['event']:r for r in ep['rows'] if r['event']!='snapshot'}
        setup,dead,released,restored,before,complete=[source[k]for k in
            (mobile.EVENTS[0],mobile.EVENTS[1],mobile.EVENTS[2],mobile.EVENTS[3],mobile.EVENTS[4],mobile.EVENTS[-1])]
        world=ep['world'];offset=setup['sampled_us']-100000;token=setup['original_incarnation'];rows=[]
        def row(name,frame,us,active='A100',pop=0):
            is_released=name=='release_observed';is_dead=name=='native_dead';activated=name!='before_activation'
            item=dict(schema=1,event=name,world=world,match=ep['match'],slot=1,entity=11,unit_type=1,army=1,
                frame=frame,tick_ms=us//1000,sampled_us=us,button_slot=4,config_id=88,ui_cast_type=5,ui_group_kind=2,
                smart_casting=False,activated_caster='A100'if activated else'0',
                activated_caster_class='Original.ManagedCaster'if activated else None,active_caster=active,
                active_caster_class=('Original.ManagedCaster'if active=='A100'else'Other.ManagedCaster')if int(active,16)else None,
                active_relation='none'if not int(active,16)else'same'if active=='A100'else'replaced',
                is_unit_selection_related=True if int(active,16)else None,source_ids=[11],source_count=0 if is_released else 1,
                casting_ids=[]if name in('before_activation','before_fresh','complete')else[11],
                casting_count=0 if is_released or name in('before_activation','before_fresh','complete')else 1,
                pending_commands=0,left_held=False,right_held=False,click_reference=0,activation_calls=int(activated),
                explicit_pop_calls=pop,pop_reason=None,natural_clear_observed=False,first_natural_clear_frame=None,
                first_natural_clear_us=None,activation_info_type=1,activation_info_count=1,activation_info_from_hotkey=True,
                activation_info_held=False,native_identity_present=not is_released,native_state=None if is_released else 6 if is_dead else 1,
                current_actor='0'if is_released else restored['current_actor'],current_admitted=not is_released,
                original_incarnation=token,current_incarnation=0 if is_released else token,direct_factory_calls=0,cast_calls=0,physicalUI=False)
            rows.append(item);return item
        row('before_activation',145,offset+150000,'0');row('after_activation',145,offset+151000)
        if world==1:
            row('before_explicit_pop',145,offset+152000)
            row('after_explicit_pop',145,offset+153000,'0',1)['pop_reason']='explicit_cancel'
        current='0'if world==1 or relation=='none'else'B100'if relation=='replaced'else'A100'
        pop=int(world==1)
        row('snapshot',152,offset+195000,current,pop)
        row('native_dead',dead['frame'],dead['sampled_us']+1,current,pop)
        row('release_observed',released['frame'],released['sampled_us']+1,current,pop)
        row('restored_before_cleanup',restored['frame'],restored['sampled_us']+1,current,pop)
        if world==2:
            if current=='0':row('cleanup_skipped',restored['frame'],restored['sampled_us']+2,'0',0)
            else:
                row('before_explicit_pop',restored['frame'],restored['sampled_us']+2,current,0)
                row('after_explicit_pop',restored['frame'],restored['sampled_us']+3,'0',1)['pop_reason']='post_restore_cleanup'
        pop=rows[-1]['explicit_pop_calls']
        row('snapshot',170,offset+1000000,'0',pop)
        row('before_fresh',180,before['sampled_us']-1,'0',pop)
        row('complete',260,complete['sampled_us']-1,'0',pop)
        natural=None;last=0
        for r in rows:
            current=int(r['active_caster'],16)
            if r['activation_calls'] and r['explicit_pop_calls']==0 and last and not current and natural is None:
                natural=(r['frame'],r['sampled_us'])
            if natural:r.update(natural_clear_observed=True,first_natural_clear_frame=natural[0],first_natural_clear_us=natural[1])
            last=current
        return rows

    def log(self):
        return '\n'.join('MOBILE ACTIVE CASTER '+json.dumps(r)for r in self.rows)

    def evaluate(self):
        return mobile.evaluate_caster_lifetime(self.log(),attacker_log=self.attacker,mobile_episodes=self.episodes,group_intent=self.groups)


class CasterLifetimeEvidenceTests(unittest.TestCase):
    def test_same_none_and_replaced_are_observed_not_forced_to_one_hidden_lifetime(self):
        for relation in('same','none','replaced'):
            with self.subTest(relation=relation):
                result=CasterLifetimeFixture(relation).evaluate();a,b=result['episodes']
                self.assertTrue(result['passed']);self.assertTrue(result['activation_exercised']);self.assertFalse(result['cast_command_exercised'])
                self.assertEqual(a['fixture_explicit_pop_calls'],1);self.assertEqual(a['cleanup_reason'],'explicit_cancel')
                self.assertEqual(b['restored_relation'],relation);self.assertEqual(b['fixture_explicit_pop_calls'],int(relation!='none'))
                self.assertEqual(b['observed_pre_fixture_pop_clear'],relation=='none')
                self.assertFalse(b['clear_callback_or_cause_observed']);self.assertFalse(result['full_mobile_controls_accepted'])

    def test_unknown_real_managed_class_and_replacement_related_false_remain_truthful(self):
        f=CasterLifetimeFixture('replaced')
        for row in f.rows:
            if row['active_relation']=='replaced':row.update(is_unit_selection_related=False,active_caster_class='Original.OtherInterfaceCaster')
        self.assertTrue(f.evaluate()['passed'])

    def test_activation_requires_actual_positive100_related_hotkey_and_original_mapping(self):
        changes=(dict(active_caster='0',active_caster_class=None,is_unit_selection_related=None,active_relation='none'),
            dict(is_unit_selection_related=False),dict(activation_info_type=2),dict(ui_cast_type=2),dict(config_id=14),
            dict(button_slot=5),dict(activation_info_from_hotkey=False),dict(current_admitted=False))
        for change in changes:
            with self.subTest(change=change):
                f=CasterLifetimeFixture();next(r for r in f.rows if r['event']=='after_activation').update(change)
                with self.assertRaises(AssertionError):f.evaluate()
        f=CasterLifetimeFixture();f.rows[0]['source_count']=0
        with self.assertRaises(AssertionError):f.evaluate()

    def test_class_null_related_null_and_same_root_class_mismatch_rejected(self):
        for change in(dict(active_caster_class=None),dict(is_unit_selection_related=None),dict(activated_caster_class='Wrong.Class')):
            with self.subTest(change=change):
                f=CasterLifetimeFixture();f.rows[1].update(change)
                with self.assertRaises(AssertionError):f.evaluate()
        f=CasterLifetimeFixture();row=f.rows[-1];row['is_unit_selection_related']=False
        with self.assertRaises(AssertionError):f.evaluate()

    def test_missing_duplicate_or_second_activation_and_counter_lies_rejected(self):
        for kind in('missing','duplicate','activation','pop','fixture_factory','fixture_cast'):
            with self.subTest(kind=kind):
                f=CasterLifetimeFixture()
                if kind=='missing':f.rows=[r for r in f.rows if not(r['world']==2 and r['event']=='restored_before_cleanup')]
                elif kind=='duplicate':f.rows.insert(2,deepcopy(f.rows[1]))
                else:f.rows[1][{'activation':'activation_calls','pop':'explicit_pop_calls','fixture_factory':'direct_factory_calls','fixture_cast':'cast_calls'}[kind]]=2 if kind=='activation'else 1
                with self.assertRaises(AssertionError):f.evaluate()

    def test_first_observed_clear_must_be_actual_pre_fixture_pop_transition(self):
        for change in(dict(natural_clear_observed=True,first_natural_clear_frame=145,first_natural_clear_us=153000),
                      dict(first_natural_clear_frame=152),dict(first_natural_clear_us=1)):
            with self.subTest(change=change):
                f=CasterLifetimeFixture();f.rows[3].update(change)
                with self.assertRaises(AssertionError):f.evaluate()
        f=CasterLifetimeFixture('none')
        for r in f.rows:
            if r['world']==2:r.update(natural_clear_observed=False,first_natural_clear_frame=None,first_natural_clear_us=None)
        with self.assertRaises(AssertionError):f.evaluate()

    def test_explicit_pop_requires_current_nonnull_and_cannot_reappear_after_cleanup(self):
        f=CasterLifetimeFixture();f.rows[2].update(active_caster='0',active_relation='none',active_caster_class=None,is_unit_selection_related=None)
        with self.assertRaises(AssertionError):f.evaluate()
        f=CasterLifetimeFixture();next(r for r in f.rows if r['world']==1 and r['event']=='snapshot').update(
            active_caster='A100',active_caster_class='Original.ManagedCaster',active_relation='same',is_unit_selection_related=True)
        with self.assertRaises(AssertionError):f.evaluate()

    def test_null_cleanup_cannot_claim_pop_and_pop_must_target_observed_current_replacement(self):
        f=CasterLifetimeFixture('none');next(r for r in f.rows if r['event']=='cleanup_skipped')['explicit_pop_calls']=1
        with self.assertRaises(AssertionError):f.evaluate()
        f=CasterLifetimeFixture('replaced');r=next(r for r in f.rows if r['world']==2 and r['event']=='before_explicit_pop')
        r.update(active_caster='A100',active_caster_class='Original.ManagedCaster',active_relation='same')
        with self.assertRaises(AssertionError):f.evaluate()

    def test_observed98_after_pop_is_valid_until179_but_fresh180_must_be_empty(self):
        f=CasterLifetimeFixture();self.assertTrue(f.evaluate()['passed'])
        self.assertEqual(next(r for r in f.rows if r['event']=='after_explicit_pop')['casting_ids'],[11])
        for key,val in(('casting_ids',[11]),('active_caster','A100')):
            g=CasterLifetimeFixture();next(r for r in g.rows if r['event']=='before_fresh')[key]=val
            with self.assertRaises(AssertionError):g.evaluate()

    def test_guest_only_exact_two_worlds_clocks_native_lifecycle_and_base_proofs_required(self):
        for kind in('attacker','extra','regress','world','native','hash','replay','fresh','group'):
            with self.subTest(kind=kind):
                f=CasterLifetimeFixture()
                if kind=='attacker':f.attacker=f.log()
                elif kind=='extra':f.rows[0]['match']='f'*32
                elif kind=='regress':f.rows[-1]['sampled_us']=1
                elif kind=='world':f.rows[0]['world']=3
                elif kind=='native':next(r for r in f.rows if r['event']=='release_observed')['native_identity_present']=True
                elif kind=='hash':f.episodes[0]['fresh_assignment_span']['hashes_match']=False
                elif kind=='replay':f.episodes[0]['escape_native_replay']['promotion_group_replayed_delta']=0
                elif kind=='fresh':f.episodes[0]['fresh_motion']['passed']=False
                else:f.groups['episodes'][0]['retained_group4_preserved']=False
                with self.assertRaises(AssertionError):f.evaluate()

    def active_mobile(self):
        f=Fixture();ep=f.evaluate();life=CasterLifetimeFixture.make_rows(ep)
        for row in f.rows[1:4]:row.update(active_caster='A100',casting_ids=[11],casting_references_victim=True)
        # Actual98 truth persists after cleanup, but100 does not.
        extra=deepcopy(f.rows[3]);extra.update(event='snapshot',frame=170,tick_ms=1000,sampled_us=1000000,active_caster='0')
        f.rows.insert(4,extra)
        original=f.log
        def log():
            text=original();indexed=[];rest=[]
            for line in text.splitlines():
                if line.startswith('MOBILE CORRECTION '):
                    row=json.loads(line.split('MOBILE CORRECTION ',1)[1]);indexed.append((row['sampled_us'],line))
                else:rest.append(line)
            indexed.extend((r['sampled_us'],'MOBILE ACTIVE CASTER '+json.dumps(r))for r in life)
            return '\n'.join([line for _,line in sorted(indexed)]+rest)
        f.log=log;return f,life

    def test_default_snapshots_remain_strict_and_opt_scope_requires_complete_witness(self):
        f,life=self.active_mobile()
        with self.assertRaisesRegex(AssertionError,'unexercised caster'):f.evaluate()
        self.assertTrue(f.evaluate(caster_lifetime=True)['active_caster_exercised'])
        life.pop()
        with self.assertRaises(AssertionError):f.evaluate(caster_lifetime=True)

    def test_opt_mobile_scope_does_not_relax_postcleanup100_beforefresh98_or_queue(self):
        for kind in('postcleanup','fresh98','queue','phase','wire'):
            with self.subTest(kind=kind):
                f,life=self.active_mobile()
                if kind=='postcleanup':f.rows[4]['active_caster']='A100'
                elif kind=='fresh98':f.rows[5]['casting_ids']=[11]
                elif kind=='queue':f.rows[1]['pending_commands']=1
                elif kind=='phase':f.fresh_assigned=183
                else:f.bridges[0]['payload_sha256']='0'*64
                with self.assertRaises(AssertionError):f.evaluate(caster_lifetime=True)


class CasterSurveyFixture:
    def __init__(self):
        base=GroupFixture();self.episodes=base.episodes;self.groups=base.evaluate();self.rows=[];self.attacker=''
        for ep in self.episodes:
            world=ep['world'];offset=(world-1)*10000000;token=ep['rows'][0]['original_incarnation']
            if offset:
                for row in ep['rows']:row['sampled_us']+=offset;row['tick_ms']+=offset//1000
                for key in('origin_sampled_us','sampled_us','enqueue_sampled_us'):ep['fresh']['order'][key]+=offset
            self.rows.append(dict(schema=1,event='mapped_buttons',route='owned_active_buttons_original_getters',
                world=world,match=ep['match'],slot=1,entity=11,unit_type=1,army=1,frame=145,tick_ms=150+offset//1000,
                sample_begin_us=150000+offset,sample_end_us=150100+offset,incarnation=token,confirmed_incarnation=token,
                current_actual_entity=11,current_actual_type=1,current_actual_army=1,current_admitted=True,
                current_initialized=True,current_native_state=1,source_ids_before=[11],source_ids_after=[11],
                preview_ids_before=[],preview_ids_after=[],casting_ids_before=[],casting_ids_after=[],
                source_count_before=1,source_count_after=1,pending_before=0,pending_after=0,
                active_caster_before=None,active_caster_after=None,active_array_present=False,active_array_count=0,
                buttons=[],eligible_slots=[],settings_scope='AbilityGroup.SmartCasting',activation_performed=False,caster_class_observed=None))

    @staticmethod
    def button(slot=0,ability=12):
        return dict(index=0,present=True,button_class='Uncapped.AbilityButtonAction',slot=slot,valid_button=True,
            mapped_ids=[11],mapped_count=1,has_mapped_casters=True,group_present=True,group_class='Uncapped.AbilityGroup',
            group_unity_truth=True,panel_group_matches=True,group_kind=3,cast_type=4,cast_type_method_token=0x06000177,
            smart_casting=False,config_lookup_performed=True,config_present=True,config_id=ability,
            config_key_observation=dict(declaring_class='Uncapped.AbilityConfig',field_name='Key',field_offset=52,
                declared_class='Uncapped.IntKey`1',boxed_class='Uncapped.IntKey`1',declared_boxed_class_equal=True,
                value_size=4,getter_token=0x0600151a,getter_rva_guarded=False,field_token_source='static_original_metadata',
                closed_argument_source='original_AbilityConfig.Key_metadata'),candidate=True,candidate_reason='noninstant_ui_mapping_only')

    @staticmethod
    def null_button():
        row={key:None for key in CasterSurveyFixture.button()}
        row.update(index=0,present=False,config_lookup_performed=False,candidate=False,candidate_reason='null_button')
        return row

    @staticmethod
    def ineligible(row,reason='ineligible_mapping'):
        row.update(candidate=False,candidate_reason=reason);return row

    @staticmethod
    def skip_config(row):
        row.update(config_lookup_performed=False,config_present=None,config_id=None,config_key_observation=None)

    def buttons(self,world,rows):
        rows=deepcopy(rows)
        for index,row in enumerate(rows):row['index']=index
        self.rows[world-1].update(active_array_present=True,active_array_count=len(rows),buttons=rows,
            eligible_slots=[row['slot']for row in rows if row['candidate']])

    def evaluate(self):
        return mobile.evaluate_caster_survey('\n'.join('MOBILE CASTER SURVEY '+json.dumps(row)for row in self.rows),
            attacker_log=self.attacker,mobile_episodes=self.episodes,group_intent=self.groups)


class CasterSurveyEvidenceTests(unittest.TestCase):
    def test_complete_null_or_empty_active_arrays_are_valid_zero_candidate_observations(self):
        f=CasterSurveyFixture();f.rows[1]['active_array_present']=True;r=f.evaluate()
        self.assertTrue(r['passed']);self.assertEqual([e['eligible_candidate_count']for e in r['episodes']],[0,0])
        self.assertFalse(r['activation_exercised']);self.assertFalse(r['active_casting_exercised'])
        self.assertFalse(r['full_mobile_controls_accepted'])
        self.assertTrue(all(not e['caster_instance_type_qualified']and e['complete_active_array_recorded']for e in r['episodes']))

    def test_actual_slot_values_order_and_duplicates_are_preserved_not_array_indices(self):
        f=CasterSurveyFixture();first=f.button(7,12);second=f.button(7,14);second['cast_type_method_token']=0x06000193
        f.buttons(1,[first,second]);r=f.evaluate()['episodes'][0]
        self.assertEqual(r['eligible_slots'],[7,7]);self.assertEqual(r['eligible_config_ids'],[12,14])
        self.assertEqual([b['index']for b in r['row']['buttons']],[0,1]);self.assertFalse(r['activation_exercised'])

    def test_null_button_and_null_mapped_set_preserve_unknown_not_fake_false(self):
        f=CasterSurveyFixture();button=f.ineligible(f.button());button.update(mapped_ids=None,mapped_count=None,has_mapped_casters=None)
        f.skip_config(button);f.buttons(1,[f.null_button(),button]);self.assertTrue(f.evaluate()['passed'])
        f.rows[0]['buttons'][1]['has_mapped_casters']=False
        with self.assertRaisesRegex(AssertionError,'null mapped casters'):f.evaluate()

    def test_resolvable_count_zero_is_not_numeric_membership_or_a_config_lookup(self):
        f=CasterSurveyFixture();button=f.ineligible(f.button());button.update(mapped_count=0,has_mapped_casters=False)
        f.skip_config(button);f.buttons(1,[button]);self.assertEqual(f.evaluate()['episodes'][0]['eligible_candidate_count'],0)
        for change in(dict(has_mapped_casters=True),dict(mapped_count=2),dict(config_lookup_performed=True)):
            with self.subTest(change=change):
                g=CasterSurveyFixture();bad=deepcopy(button);bad.update(change);g.buttons(1,[bad])
                with self.assertRaises(AssertionError):g.evaluate()

    def test_group_absence_and_destroyed_unity_group_skip_unsafe_getters_honestly(self):
        for present in(False,True):
            with self.subTest(group_present=present):
                f=CasterSurveyFixture();button=f.ineligible(f.button());f.skip_config(button)
                button.update(group_present=present,group_unity_truth=False if present else None,
                    group_class='Uncapped.AbilityGroup'if present else None,group_kind=3 if present else None,
                    smart_casting=False if present else None,cast_type=None,cast_type_method_token=None)
                f.buttons(1,[button]);self.assertTrue(f.evaluate()['passed'])
                f.rows[0]['buttons'][0].update(cast_type=4,cast_type_method_token=0x06000177)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_supported_invalid_and_unsupported_slots_do_not_fake_panel_calls(self):
        f=CasterSurveyFixture();invalid=f.ineligible(f.button(0));invalid.update(valid_button=False,panel_group_matches=None)
        unsupported=f.ineligible(f.button(99),'unsupported_slot');unsupported.update(valid_button=None,panel_group_matches=None)
        f.buttons(1,[invalid,unsupported]);self.assertTrue(f.evaluate()['passed'])
        for key in('valid_button','panel_group_matches'):
            with self.subTest(key=key):
                g=CasterSurveyFixture();bad=deepcopy(unsupported);bad[key]=False;g.buttons(1,[bad])
                with self.assertRaisesRegex(AssertionError,'unsupported actual slot'):g.evaluate()

    def test_instant_smart_wrong_id_or_panel_mismatch_is_observed_but_not_a_candidate(self):
        variants=(dict(cast_type=2),dict(smart_casting=True),dict(config_id=99),dict(panel_group_matches=False),dict(mapped_ids=[5]))
        for change in variants:
            with self.subTest(change=change):
                f=CasterSurveyFixture();button=f.ineligible(f.button());button.update(change);f.buttons(1,[button])
                self.assertEqual(f.evaluate()['episodes'][0]['eligible_candidate_count'],0)
                f.rows[0]['buttons'][0].update(candidate=True,candidate_reason='noninstant_ui_mapping_only');f.rows[0]['eligible_slots']=[0]
                with self.assertRaisesRegex(AssertionError,'candidate classification'):f.evaluate()

    def test_group_kind_never_substitutes_for_actual_config_key_and_null_config_is_not_unlooked(self):
        f=CasterSurveyFixture();button=f.ineligible(f.button(2,99));button['group_kind']=12;f.buttons(1,[button])
        self.assertEqual(f.evaluate()['episodes'][0]['eligible_candidate_count'],0)
        button=f.ineligible(f.button());button.update(config_present=False,config_id=None,config_key_observation=None)
        f.buttons(1,[button]);self.assertTrue(f.evaluate()['passed'])
        f.rows[0]['buttons'][0]['config_present']=None
        with self.assertRaisesRegex(AssertionError,'presence is unobserved'):f.evaluate()

    def test_effective_virtual_getter_and_closed_boxed_key_provenance_are_required(self):
        for change in(dict(cast_type=1),dict(cast_type=11),dict(cast_type_method_token=0x06000178),dict(cast_type_method_token=True)):
            with self.subTest(change=change):
                f=CasterSurveyFixture();button=f.button();button.update(change);f.buttons(1,[button])
                with self.assertRaisesRegex(AssertionError,'virtual CastType'):f.evaluate()
        for change in(dict(boxed_class='Uncapped.IntKey`2'),dict(declared_boxed_class_equal=False),dict(field_offset=53),
                      dict(getter_token=0x06000001),dict(getter_rva_guarded=True),dict(field_token_source='runtime_field_get_token'),
                      dict(closed_argument_source='guessed_native_RVA'),dict(value_size=True)):
            with self.subTest(change=change):
                f=CasterSurveyFixture();button=f.button();button['config_key_observation'].update(change);f.buttons(1,[button])
                with self.assertRaisesRegex(AssertionError,'Key/get_ID provenance'):f.evaluate()

    def test_full_twelve_button_receipt_above8k_uses_only_survey64k_limit(self):
        f=CasterSurveyFixture();button=f.button(3);button['button_class']=button['group_class']='N'*250+'.'+'C'*250
        f.buttons(1,[deepcopy(button)for _ in range(12)])
        raw=json.dumps(f.rows[0]);self.assertGreater(len(raw),8192);self.assertLess(len(raw),65536)
        self.assertEqual(f.evaluate()['episodes'][0]['eligible_candidate_count'],12)
        with self.assertRaisesRegex(AssertionError,'diagnostic row exceeds bound'):
            mobile._rows('LEGACY '+raw,'LEGACY ',f.rows[0]['match'],1)
        padded=raw+' '*(65536-len(raw));self.assertEqual(mobile._caster_survey_json(padded),f.rows[0])
        with self.assertRaisesRegex(AssertionError,'64KiB'):mobile._caster_survey_json(padded+' ')

    def test_survey_json_duplicate_keys_depth_and_quoted_braces_are_bounded(self):
        f=CasterSurveyFixture();f.buttons(1,[f.button()]);raw=json.dumps(f.rows[0])
        with self.assertRaisesRegex(AssertionError,'duplicate diagnostic JSON key'):
            mobile._caster_survey_json(raw.replace('"schema": 1','"schema": 1, "schema": 1',1))
        with self.assertRaisesRegex(AssertionError,'duplicate diagnostic JSON key'):
            mobile._caster_survey_json(raw.replace('"field_name": "Key"','"field_name": "Key", "field_name": "Key"',1))
        with self.assertRaisesRegex(AssertionError,'depth4'):mobile._caster_survey_json('{"a":[{"b":[{}]}]}')
        f.rows[0]['buttons'][0]['button_class']='N.Quoted"{[\\]}'
        self.assertTrue(f.evaluate()['passed'])

    def test_complete_array_and_candidate_list_cannot_be_truncated_deduplicated_or_reindexed(self):
        for kind in('count','cap','array_missing','index','eligible_order','dedup','extra'):
            with self.subTest(kind=kind):
                f=CasterSurveyFixture();f.buttons(1,[f.button(7,12),f.button(2,14)])
                if kind=='count':f.rows[0]['active_array_count']=1
                elif kind=='cap':f.rows[0]['active_array_count']=13
                elif kind=='array_missing':f.rows[0]['active_array_present']=False
                elif kind=='index':f.rows[0]['buttons'][1]['index']=0
                elif kind=='eligible_order':f.rows[0]['eligible_slots']=[2,7]
                elif kind=='dedup':f.rows[0]['buttons'][1]['slot']=7;f.rows[0]['eligible_slots']=[7]
                else:f.rows[0]['buttons'][0]['slot_supported']=True
                with self.assertRaises(AssertionError):f.evaluate()

    def test_identity_owner_route_empty_queue_and_unchanged_selection_are_mandatory(self):
        for change in(dict(route='guessed_button_route'),dict(slot=0),dict(entity=10),dict(frame=146),dict(incarnation=99),
                      dict(current_actual_army=0),dict(current_admitted=False),dict(current_initialized=False),dict(current_native_state=6),
                      dict(source_count_after=0),dict(source_count_before=True),dict(source_ids_after=[]),dict(preview_ids_after=[11]),
                      dict(casting_ids_after=[11]),dict(pending_after=1),dict(active_caster_before='0'),dict(active_caster_after='123'),
                      dict(activation_performed=True),dict(caster_class_observed='TargetGroundAbilityCaster'),dict(settings_scope='global_setting_guess')):
            with self.subTest(change=change):
                f=CasterSurveyFixture();f.rows[0].update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_actual_qpc_bracket_and_both_matched_world_receipts_are_required(self):
        for kind in('missing','duplicate','world','match','before_setup','after_dead','no_duration','clock_bool','host'):
            with self.subTest(kind=kind):
                f=CasterSurveyFixture()
                if kind=='missing':f.rows.pop()
                elif kind=='duplicate':f.rows.append(deepcopy(f.rows[0]))
                elif kind=='world':f.rows[1]['world']=1
                elif kind=='match':f.rows[1]['match']=f.rows[0]['match']
                elif kind=='before_setup':f.rows[0].update(sample_begin_us=90000,sample_end_us=90100)
                elif kind=='after_dead':f.rows[0]['sample_end_us']=200000
                elif kind=='no_duration':f.rows[0]['sample_end_us']=f.rows[0]['sample_begin_us']
                elif kind=='clock_bool':f.rows[0]['sample_begin_us']=True
                else:f.attacker='MOBILE CASTER SURVEY '+json.dumps(f.rows[0])
                with self.assertRaises(AssertionError):f.evaluate()

    def test_value_only_survey_never_replaces_original_movement_native_or_group_proof(self):
        for kind in('mobile','motion','span','replay','tail','groups','edits','group_world','token'):
            with self.subTest(kind=kind):
                f=CasterSurveyFixture()
                if kind=='mobile':f.episodes[0]['passed']=False
                elif kind=='motion':f.episodes[0]['fresh_motion']['passed']=False
                elif kind=='span':f.episodes[0]['fresh_assignment_span']['hashes_match']=False
                elif kind=='replay':f.episodes[0]['escape_native_replay']['promotion_group_replayed_delta']=0
                elif kind=='tail':f.episodes[0]['escape_native_replay']['continuation_frames']=19
                elif kind=='groups':f.groups['passed']=False
                elif kind=='edits':f.groups['user_edits']=True
                elif kind=='group_world':f.groups['episodes'][0]['world']=999
                else:f.episodes[0]['fresh']['order']['incarnation']=99
                with self.assertRaises(AssertionError):f.evaluate()


class FocusFixture:
    def __init__(self):
        self.base=GroupFixture();self.episodes=self.base.episodes;self.groups=self.base.evaluate();self.rows=[]
        for ep in self.episodes:
            world=ep['world'];token=ep['rows'][0]['original_incarnation']
            offset=(world-1)*10000000
            if offset:
                for row in ep['rows']:
                    row['sampled_us']+=offset;row['tick_ms']+=offset//1000
                for key in('origin_sampled_us','sampled_us','enqueue_sampled_us'):ep['fresh']['order'][key]+=offset
            events=[('setup',130,100020),('restored',163,350020),('complete',260,5999990)]
            if world == 2:events[1:1]=[('before_cancel',154,225010),('after_cancel',154,225020)]
            for event,frame,us in events:
                us+=offset
                absent=event in('before_cancel','after_cancel');cancelled=world == 2 and event not in('setup','before_cancel')
                saved=world == 2 and event != 'setup'
                row=dict(schema=1,event=event,world=world,match=ep['match'],slot=1,entity=11,unit_type=1,army=1,
                    frame=frame,completed_frame=frame,tick_ms=us//1000,sampled_us=us,selector='00000300',
                    incarnation=token,confirmed_incarnation=token,current_incarnation=0 if absent else token,
                    retained_group=4,group_ids=[11],selected_ids=[11],preview_ids=[],casting_ids=[],
                    native_identity_present=not absent,current_admitted=not absent,current_actor='0'if absent else'000001A0',
                    current_actual_entity=None if absent else 11,current_actual_type=None if absent else 1,
                    current_actual_army=None if absent else 1,source_resolvable_count=0 if absent else 1,
                    focus_group=-1 if cancelled else 4,focus_actor='0'if cancelled else'000001A0',
                    pending_iteration=17 if saved else 0,pending_epoch=2 if saved else 0,pending_iterator='00000200'if saved else'0',
                    release_pending_baseline=15 if event != 'setup' else 0,
                    pending_commands=0,cancel_callback='Uncapped.UnitSelector.FocusControlGroupCancel'if event=='after_cancel'else None,
                    cancel_token='06002220'if event=='after_cancel'else None,physicalUI=False)
                self.rows.append(row)
        self.attacker='';self.products=[]
        self.build_products()

    def build_products(self):
        for ep in self.episodes:
            world=ep['world'];offset=(world-1)*10000000;iterator='00000201'if world==1 else'00000200'
            token=ep['rows'][0]['original_incarnation']
            def emit(event,stage,us,iteration=0,*,route='repeat',candidate=False,result=None,state=1,yield_bits=0xff800000):
                no_iterator=event=='request'or route=='initial'
                row=dict(schema=1,event_sequence=len(self.products)+1,event=event,stage=stage,route=route,
                    world=world,match=ep['match'],selector='00000300',iterator=None if no_iterator else iterator,
                    request_epoch=world,iteration=0 if no_iterator else iteration,group=4,
                    held_group=-1 if event=='cancel_observed'or stage in('cancel_delegate','original_false','world_retired')else 4,
                    tick_ms=(us+offset)//1000,sampled_us=us+offset,original_state=None if no_iterator else state,
                    yield_bits=None if no_iterator else yield_bits,original_result=result,source_ids=[11],logical_ids=[11],
                    actor='000001A0'if candidate else None,entity=11 if candidate else None,
                    unit_type=1 if candidate else None,army=1 if candidate else None,incarnation=token if candidate else None,
                    member=candidate,initialized=candidate,current_lease=candidate)
                self.products.append(row);return row
            def camera(iteration,us,route='repeat'):
                emit('camera','requested',us,iteration,route=route,candidate=True,state=-1)
                emit('camera','returned',us+1,iteration,route=route,candidate=True,state=-1)
            def positive(iteration,us,stage='delegate'):
                camera(iteration,us);emit('iteration',stage,us+2,iteration,candidate=True,result=True)
            emit('request','accepted_repeat',99970)
            camera(0,99971,'initial');emit('start','scheduling',99974,state=0,yield_bits=0)
            positive(1,99975);emit('scheduled','returned',99978,1)
            for ordinal in range(2,15):positive(ordinal,110000+(ordinal-2)*6000)
            for ordinal,us in((15,210000),(16,221000),(17,224000)):emit('iteration','waiting_absent',us,ordinal)
            if world==1:
                positive(18,350100,'refind');positive(19,6000010)
                emit('terminal','world_retired',7000000,19,state=-1)
            else:
                emit('cancel_observed','cancel_delegate',226000,18)
                emit('iteration','cancel_delegate',226010,18,result=True,state=2)
                emit('cancel_observed','cancel_delegate',230000,19,state=2)
                emit('iteration','cancel_delegate',230010,19,result=False,state=-1)
                emit('terminal','original_false',230011,19,result=False,state=-1)
                emit('terminal','world_retired',7000000,19,state=-1)

    def renumber(self):
        self.products.sort(key=lambda r:r['sampled_us'])
        for i,row in enumerate(self.products,1):row['event_sequence']=i

    def log(self):
        items=[]
        for ep in self.episodes:
            items.extend((row['sampled_us'],'MOBILE CORRECTION ',row)for row in ep['rows'])
        items.extend((row['sampled_us'],'MOBILE GROUP FOCUS ',row)for row in self.rows)
        items.extend((row['sampled_us'],'MOVEMENT FOCUS ',row)for row in self.products)
        return '\n'.join(prefix+json.dumps(row)for _,prefix,row in sorted(items,key=lambda item:item[0]))

    def evaluate(self):
        return mobile.evaluate_group_focus(self.log(),attacker_log=self.attacker,mobile_episodes=self.episodes,group_intent=self.groups)

    def product(self,world,event,stage=None,iteration=None):
        return next(row for row in self.products if row['world']==world and row['event']==event and
                    (stage is None or row['stage']==stage)and(iteration is None or row['iteration']==iteration))

    def fixture_rows(self,world):
        ep=self.episodes[world-1]
        return mobile._group_focus_fixture_rows('\n'.join('MOBILE GROUP FOCUS '+json.dumps(r)for r in self.rows),
            match=ep['match'],world=world,token=ep['rows'][0]['original_incarnation'])


class FocusNoStartFixture(FocusFixture):
    def __init__(self,pending=False):
        self.nonzero_pending=pending;self.requests=[]
        super().__init__()
        self.rows=[r for r in self.rows if r['event']in('setup','restored','complete')]

    def build_products(self):
        for ep in self.episodes:
            world=ep['world'];offset=(world-1)*10000000;active=2*world-1;new=active+1;iterator='201'if world==1 else'200';handle=100+world
            token=ep['rows'][0]['original_incarnation'];repeat_before=350020 if self.nonzero_pending else 350200
            def emit(event,stage,us,iteration=0,*,route='repeat',candidate=False,result=None,state=1,ready=True,epoch=None):
                initial=route=='initial';epoch=(active if epoch is None else epoch);installed=not initial or epoch==new
                row=dict(schema=1,event_sequence=len(self.products)+1,event=event,stage=stage,route=route,world=world,match=ep['match'],
                    selector='00000300',iterator=None if initial else iterator,request_epoch=epoch,iteration=0 if initial else iteration,
                    requested_group=4,active_epoch=active if installed else 0,active_iterator=iterator if installed else None,
                    active_handle=handle if installed and ready else None,group=4,held_group=-1 if event=='cancel_observed'or stage in('cancel_delegate','original_false','world_retired')else 4,
                    tick_ms=(us+offset)//1000,sampled_us=us+offset,original_state=None if initial else state,yield_bits=None if initial else 0xff800000,
                    original_result=result,source_ids=[11],logical_ids=[11],actor='000001A0'if candidate else None,entity=11 if candidate else None,
                    unit_type=1 if candidate else None,army=1 if candidate else None,incarnation=token if candidate else None,
                    member=candidate,initialized=candidate,current_lease=candidate)
                self.products.append(row);return row
            def camera(ordinal,us,route='repeat',ready=True,epoch=None):
                emit('camera','requested',us,ordinal,route=route,candidate=True,state=-1,ready=ready,epoch=epoch)
                emit('camera','returned',us+1,ordinal,route=route,candidate=True,state=-1,ready=ready,epoch=epoch)
            def positive(ordinal,us,stage='delegate',ready=True):
                camera(ordinal,us,ready=ready);emit('iteration',stage,us+2,ordinal,candidate=True,result=True,ready=ready)
            emit('request','accepted_repeat',99970,route='initial');camera(0,99971,'initial');emit('start','scheduling',99974,state=0,ready=False)
            positive(1,99975,ready=False);emit('scheduled','returned',99978,1)
            for ordinal in range(2,15):positive(ordinal,110000+(ordinal-2)*6000)
            for ordinal,us in((15,210000),(16,221000),(17,224000)):emit('iteration','waiting_absent',us,ordinal)
            if not self.nonzero_pending:positive(18,350100,'refind')
            emit('request','accepted_repeat',repeat_before+10,route='initial',epoch=new);camera(0,repeat_before+11,'initial',epoch=new)
            if self.nonzero_pending:positive(18,350100,'refind')
            positive(19,360000)
            if world==1:
                positive(20,6000010);emit('terminal','world_retired',7000000,20,state=-1)
            else:
                emit('cancel_observed','cancel_delegate',600100,20);emit('iteration','cancel_delegate',600110,20,result=True,state=2)
                emit('cancel_observed','cancel_delegate',650100,21,state=2);emit('iteration','cancel_delegate',650110,21,result=False,state=-1)
                emit('terminal','original_false',650111,21,result=False,state=-1)
            def fixture(event,frame,us):
                retired=world==2 and event=='complete';cancelled=world==2 and event in('after_cancel','complete')
                before=event=='before_repeat';has_request=not before and not retired
                ordinal=(17 if self.nonzero_pending else 18)if event in('before_repeat','after_repeat')else 19
                count=int(self.nonzero_pending and event in('before_repeat','after_repeat'))
                row=dict(schema=1,event=event,world=world,match=ep['match'],slot=1,entity=11,frame=frame,tick_ms=(us+offset)//1000,sampled_us=us+offset,
                    observer_active=not retired,observer_world=0 if retired else world,active_epoch=0 if retired else active,request_epoch=new if has_request else 0,
                    requested_group=4 if has_request else None,effective_group=4 if has_request else None,active_group=None if retired else 4,
                    iterator='0'if retired else iterator,handle=0 if retired else handle,selector_handle=handle,handle_ready=not retired,scheduling=False,ending=False,
                    iteration=0 if retired else ordinal,pending_iteration=17 if count else 0,pending_count=count,
                    pending_identities=[dict(entity=11,unit_type=1,army=1,incarnation=token)]if count else[],original_state=None if retired else 1,
                    yield_bits=None if retired else 0xff800000,held_group=-1 if cancelled else 4,source_ids=[]if retired else[11],logical_ids=[]if retired else[11],selected_ids=[11],
                    current_actor='000001A0',current_admitted=True,original_incarnation=token,current_incarnation=token,native_identity_present=True,
                    repeat_calls=0 if before else 1,cancel_calls=int(cancelled),original_callback=None if event=='complete'else
                    'Uncapped.UnitSelector.FocusControlGroupCancel'if'cancel'in event else'Uncapped.UnitSelector.FocusControlGroup',
                    original_token=None if event=='complete'else 0x06002220 if'cancel'in event else 0x06002221,physicalUI=False)
                self.requests.append(row)
            fixture('before_repeat',163,repeat_before);fixture('after_repeat',163,repeat_before+30)
            if world==2:fixture('before_cancel',170,600000);fixture('after_cancel',170,600010)
            fixture('complete',260,5999990)

    def log(self):
        items=[]
        for line in super().log().splitlines():
            prefix,raw=line.split(' {',1);row=json.loads('{'+raw);items.append((row['sampled_us'],line))
        items.extend((r['sampled_us'],'MOBILE FOCUS REQUEST '+json.dumps(r))for r in self.requests)
        return '\n'.join(line for _,line in sorted(items,key=lambda item:item[0]))

    def evaluate(self):
        return mobile.evaluate_group_focus(self.log(),attacker_log=self.attacker,mobile_episodes=self.episodes,group_intent=self.groups,no_start=True)


class FocusRestartFixture(FocusNoStartFixture):
    def __init__(self,equal_handles=False):
        self.equal_handles=equal_handles;super().__init__()

    def build_products(self):
        super().build_products();offset=10000000;epoch=5;iterator='400';old='200';handle=102 if self.equal_handles else 202
        self.products=[r for r in self.products if not(r['world']==2 and(r['event']=='cancel_observed'or r['stage']in('cancel_delegate','original_false')))]
        old_positive=deepcopy(next(r for r in self.products if r['world']==2 and r['event']=='iteration'and r['iteration']==19))
        def append(row,us):
            row.update(world=2,match='2'*32,tick_ms=(us+offset)//1000,sampled_us=us+offset);self.products.append(row)
        request=deepcopy(next(r for r in self.products if r['world']==2 and r['event']=='request'and r['request_epoch']==4));request['request_epoch']=epoch
        append(request,600020)
        for stage,us in(('requested',600021),('returned',600022)):
            r=deepcopy(next(x for x in self.products if x['world']==2 and x['event']=='camera'and x['route']=='initial'and x['request_epoch']==4 and x['stage']==stage));r['request_epoch']=epoch;append(r,us)
        terminal=deepcopy(old_positive);terminal.update(event='terminal',stage='superseded',actor=None,entity=None,unit_type=None,army=None,
            incarnation=None,member=False,initialized=False,current_lease=False,original_result=None)
        append(terminal,600025)
        start=deepcopy(next(r for r in self.products if r['world']==2 and r['event']=='start'))
        start.update(iterator=iterator,active_iterator=iterator,request_epoch=epoch,active_epoch=epoch,iteration=0,original_state=0,active_handle=None)
        append(start,600030)
        def positive(ordinal,us,ready=True):
            for stage,at in(('requested',us),('returned',us+1)):
                row=deepcopy(next(r for r in self.products if r['world']==2 and r['event']=='camera'and r['route']=='repeat'and r['stage']==stage))
                row.update(iterator=iterator,active_iterator=iterator,request_epoch=epoch,active_epoch=epoch,iteration=ordinal,active_handle=handle if ready else None)
                append(row,at)
            row=deepcopy(old_positive);row.update(iterator=iterator,active_iterator=iterator,request_epoch=epoch,active_epoch=epoch,iteration=ordinal,
                active_handle=handle if ready else None);append(row,us+2)
        positive(1,600040,False)
        scheduled=deepcopy(next(r for r in self.products if r['world']==2 and r['event']=='scheduled'))
        scheduled.update(iterator=iterator,active_iterator=iterator,request_epoch=epoch,active_epoch=epoch,iteration=1,active_handle=handle)
        append(scheduled,600050);positive(2,610000);positive(3,6000010)
        end=deepcopy(terminal);end.update(stage='world_retired',iterator=iterator,active_iterator=iterator,request_epoch=epoch,active_epoch=epoch,
            iteration=3,active_handle=handle);append(end,7000000)
        for row in self.requests:
            row.update(restart_calls=0,retired_iterator=None,old_iterator_weak_registered=False,restart_eligible=False)
            if row['world']==2 and row['event']in('before_cancel','after_cancel','complete'):row['restart_eligible']=True
            if row['world']==2 and row['event']=='complete':
                row.update(observer_active=True,observer_world=2,active_epoch=epoch,request_epoch=0,active_group=4,iterator=iterator,
                    handle=handle,selector_handle=handle,handle_ready=True,scheduling=False,ending=False,iteration=2,original_state=1,
                    yield_bits=0xff800000,held_group=4,source_ids=[11],logical_ids=[11],restart_calls=1,retired_iterator=old,old_iterator_weak_registered=True)
        restarted=deepcopy(next(r for r in self.requests if r['world']==2 and r['event']=='complete'))
        restarted.update(event='after_restart',frame=170,tick_ms=(600060+offset)//1000,sampled_us=600060+offset,iteration=1,
            original_callback='Uncapped.UnitSelector.FocusControlGroup',original_token=0x06002221)
        self.requests.append(restarted);self.renumber()

    def evaluate(self):
        return mobile.evaluate_group_focus(self.log(),attacker_log=self.attacker,mobile_episodes=self.episodes,group_intent=self.groups,no_start=True,restart=True)


class FocusRestartEvidenceTests(unittest.TestCase):
    def test_real_restart_supersedes_old_scope_and_sync_executes_new_scope_even_with_equal_handle_values(self):
        for equal in(False,True):
            with self.subTest(equal=equal):
                result=FocusRestartFixture(equal).evaluate();ep=result['episodes'][1]
                self.assertTrue(result['old_iterator_retirement_verified']);self.assertEqual(ep['restart_epoch'],5)
                self.assertNotEqual(ep['iterator'],ep['restart_iterator']);self.assertFalse(ep['handle_inequality_required'])
                self.assertFalse(ep['late_old_next_attempt_observed']);self.assertEqual(ep['retired_old_camera_calls'],0)

    def test_missing_eligibility_weak_registration_or_consumed_request_rejects(self):
        for event,change in(('before_cancel',dict(restart_eligible=False)),('after_restart',dict(old_iterator_weak_registered=False)),
                             ('after_restart',dict(request_epoch=5,requested_group=4,effective_group=4)),('after_restart',dict(retired_iterator='BEEF'))):
            with self.subTest(change=change):
                f=FocusRestartFixture();next(r for r in f.requests if r['world']==2 and r['event']==event).update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_old_terminal_must_precede_new_start_with_old_identity(self):
        for kind in('epoch','pointer','order'):
            with self.subTest(kind=kind):
                f=FocusRestartFixture();row=f.product(2,'terminal','superseded')
                if kind=='epoch':row.update(request_epoch=5,active_epoch=5)
                elif kind=='pointer':row.update(iterator='400',active_iterator='400')
                else:row['sampled_us']+=100;row['tick_ms']=row['sampled_us']//1000
                f.renumber()
                with self.assertRaises(AssertionError):f.evaluate()

    def test_new_start_needs_actual_synchronous_move_next_and_no_late_old_camera(self):
        f=FocusRestartFixture();row=next(r for r in f.products if r['world']==2 and r['event']=='scheduled'and r['request_epoch']==5)
        row['sampled_us']-=15;row['tick_ms']=row['sampled_us']//1000;f.renumber()
        with self.assertRaises(AssertionError):f.evaluate()
        f=FocusRestartFixture();row=next(r for r in f.products if r['world']==2 and r['event']=='camera'and r['route']=='repeat'and r['request_epoch']==5)
        row.update(request_epoch=3,active_epoch=3,iterator='200',active_iterator='200',active_handle=102)
        with self.assertRaises(AssertionError):f.evaluate()

    def test_restart_schema_is_opt_in_and_base35_controls_stay_unchanged(self):
        self.assertTrue(FocusNoStartFixture().evaluate()['passed']);self.assertTrue(FocusFixture().evaluate()['passed'])
        f=FocusRestartFixture()
        with self.assertRaises(AssertionError):mobile.evaluate_group_focus(f.log(),attacker_log=f.attacker,mobile_episodes=f.episodes,group_intent=f.groups,no_start=True)
        f.episodes[1]['fresh_assignment_span']['hashes_match']=False
        with self.assertRaises(AssertionError):f.evaluate()


class FocusNoStartEvidenceTests(unittest.TestCase):
    def test_two_initial_requests_one_active_iterator_and_original_cancel_with_zero_or_nonzero_pending(self):
        for pending in(False,True):
            with self.subTest(pending=pending):
                r=FocusNoStartFixture(pending).evaluate();self.assertTrue(r['passed']);self.assertTrue(r['request_active_scope_verified'])
                self.assertEqual([x['active_epoch']for x in r['episodes']],[1,3]);self.assertEqual([x['accepted_no_start_request_epoch']for x in r['episodes']],[2,4])
                self.assertTrue(all(x['nonzero_pending_preservation_exercised']==pending for x in r['episodes']))
                self.assertFalse(r['accepted_group_switch_exercised']);self.assertFalse(r['physicalUI'])

    def test_eager_active_epoch_iterator_handle_or_pending_mutation_is_rejected(self):
        for change in(dict(active_epoch=2),dict(iterator='BEEF'),dict(handle=999),dict(pending_iteration=0,pending_count=0,pending_identities=[])):
            with self.subTest(change=change):
                f=FocusNoStartFixture(True);next(r for r in f.requests if r['event']=='after_repeat').update(change)
                with self.assertRaises(AssertionError):f.evaluate()
        f=FocusNoStartFixture();row=f.product(1,'iteration',iteration=19);row.update(request_epoch=2,active_epoch=2)
        with self.assertRaises(AssertionError):f.evaluate()

    def test_phantom_start_missing_initial_return_and_epoch_pair_collision_rejected(self):
        for kind in('start','return','collision'):
            with self.subTest(kind=kind):
                f=FocusNoStartFixture();camera=next(r for r in f.products if r['world']==1 and r['event']=='camera'and r['route']=='initial'and r['request_epoch']==2)
                if kind=='start':
                    row=deepcopy(f.product(1,'start'));row.update(sampled_us=camera['sampled_us']+5,tick_ms=camera['tick_ms'],request_epoch=2,active_epoch=2);f.products.append(row)
                elif kind=='return':f.products.remove(next(r for r in f.products if r['world']==1 and r['event']=='camera'and r['route']=='initial'and r['request_epoch']==2 and r['stage']=='returned'))
                else:
                    for row in f.products:
                        if row['world']==1 and row['event']=='camera'and row['route']=='initial'and row['request_epoch']==2:row['request_epoch']=1
                f.renumber()
                with self.assertRaises(AssertionError):f.evaluate()

    def test_cancel_must_keep_old_scope_and_eventually_return_original_false_without_camera(self):
        f=FocusNoStartFixture();f.product(2,'iteration','cancel_delegate',21)['original_result']=True
        with self.assertRaises(AssertionError):f.evaluate()
        f=FocusNoStartFixture();row=next(r for r in f.products if r['world']==2 and r['event']=='camera'and r['route']=='repeat'and r['stage']=='returned')
        row['sampled_us']=10660000;row['tick_ms']=10660;f.renumber()
        with self.assertRaises(AssertionError):f.evaluate()

    def test_retired_complete_has_no_live_lease_and_old_v1_default_remains_strict(self):
        f=FocusNoStartFixture();end=next(r for r in f.requests if r['world']==2 and r['event']=='complete')
        self.assertNotEqual(end['selector_handle'],end['handle']);self.assertTrue(f.evaluate()['passed'])
        end['observer_active']=True
        with self.assertRaises(AssertionError):f.evaluate()
        self.assertTrue(FocusFixture().evaluate()['passed'])
        with self.assertRaises(AssertionError):mobile._group_focus_product_rows(FocusNoStartFixture().log(),matches=['1'*32,'2'*32])

    def test_void_focus_has_no_fabricated_bool_and_no_start_cannot_replace_native_motion_gates(self):
        f=FocusNoStartFixture();f.requests[1]['original_result']=True
        with self.assertRaises(AssertionError):f.evaluate()
        for key in('fresh_motion','fresh_assignment_span'):
            f=FocusNoStartFixture();f.episodes[0][key]['passed'if key=='fresh_motion'else'hashes_match']=False
            with self.assertRaises(AssertionError):f.evaluate()


class GroupFocusFixtureEvidenceTests(unittest.TestCase):
    def test_positive_held_fixture_and_actual_original_cancel_fixture_are_distinct(self):
        f=FocusFixture();positive=f.fixture_rows(1);cancel=f.fixture_rows(2)
        self.assertEqual([r['event']for r in positive],['setup','restored','complete'])
        self.assertEqual([r['event']for r in cancel],['setup','before_cancel','after_cancel','restored','complete'])
        self.assertTrue(all(r['focus_group']==4 for r in positive))
        self.assertEqual(cancel[1]['pending_iteration'],17);self.assertEqual(cancel[2]['pending_iterator'],'00000200')
        self.assertTrue(all(r['focus_group']==-1 and r['focus_actor']=='0'for r in cancel[2:]))

    def test_cancel_marker_requires_same_full_saved_pending_witness_and_original_callback(self):
        changes=(dict(pending_iteration=0),dict(pending_epoch=0),dict(pending_iterator='0'),dict(pending_iteration=18),
                 dict(release_pending_baseline=17),dict(release_pending_baseline=True),
                 dict(cancel_callback=None),dict(cancel_token='06002221'),dict(focus_group=4),dict(focus_actor='000001A0'))
        for change in changes:
            with self.subTest(change=change):
                f=FocusFixture();f.rows[5].update(change)
                with self.assertRaises(AssertionError):f.fixture_rows(2)

    def test_positive_must_preserve_intent_and_cancelled_world_must_not_restart(self):
        for index,change in((1,dict(focus_group=-1)),(2,dict(focus_actor='0')),(6,dict(focus_group=4)),
                            (6,dict(focus_actor='000001A0')),(0,dict(pending_iteration=1,pending_epoch=1,pending_iterator='123'))):
            with self.subTest(index=index,change=change):
                f=FocusFixture();f.rows[index].update(change)
                with self.assertRaises(AssertionError):f.fixture_rows(f.rows[index]['world'])

    def test_cancel_cannot_reuse_pending_ordinal_from_before_complete_physical_release(self):
        f=FocusFixture()
        for row in f.rows:
            if row['world']==2 and row['event']!='setup':row['release_pending_baseline']=17
        with self.assertRaisesRegex(AssertionError,'pending cancellation'):f.fixture_rows(2)

    def test_focus_fixture_native_identity_lease_group_schema_and_scope_are_strict(self):
        for index,change in((0,dict(current_actual_army=0)),(1,dict(current_incarnation=8)),(1,dict(current_admitted=False)),
                            (4,dict(native_identity_present=True)),(4,dict(current_actor='000001A0')),
                            (4,dict(group_ids=[])),(4,dict(pending_commands=1)),(4,dict(physicalUI=True)),
                            (4,dict(selector='0')),(4,dict(extra=True)),(4,dict(source_resolvable_count=True))):
            with self.subTest(index=index,change=change):
                f=FocusFixture();f.rows[index].update(change)
                with self.assertRaises(AssertionError):f.fixture_rows(f.rows[index]['world'])


class GroupFocusEvidenceTests(unittest.TestCase):
    def test_complete_original_iterator_camera_and_cancel_paths_both_worlds(self):
        f=FocusFixture();r=f.evaluate();self.assertTrue(r['passed'])
        hold,cancel=r['episodes'];self.assertEqual(hold['path'],'held_focus_continuity')
        self.assertEqual(cancel['path'],'original_pending_cancel_honored')
        self.assertEqual(hold['outer_iterations'],19);self.assertEqual(cancel['outer_iterations'],19)
        self.assertTrue(all(ep['all_camera_targets_current_member11'] and ep['pending_camera_calls']==0 and
                            ep['source_event_sequence_complete']for ep in r['episodes']))
        self.assertEqual(cancel['post_release_pending']['row']['iteration'],17)
        self.assertFalse(r['physicalUI']);self.assertFalse(r['accepted_group_switch_exercised'])
        self.assertFalse(r['active_casting_exercised']);self.assertFalse(r['full_mobile_controls_accepted'])

    def test_synchronous_first_move_next_can_precede_scheduler_return(self):
        f=FocusFixture()
        first=f.product(1,'iteration',iteration=1);scheduled=f.product(1,'scheduled')
        self.assertLess(first['event_sequence'],scheduled['event_sequence'])
        self.assertLess(f.product(1,'camera','returned',1)['event_sequence'],first['event_sequence'])
        self.assertTrue(f.evaluate()['passed'])

    def test_lifetime_event_sequence_and_checked_clocks_are_not_reset_or_fabricated(self):
        for change in(dict(event_sequence=1),dict(sampled_us=True),dict(tick_ms=-1)):
            with self.subTest(change=change):
                f=FocusFixture();f.product(2,'request').update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_admitted_own_hq_zero_outside_group11_is_not_the_intended_focus(self):
        for independent_membership in(False,True):
            with self.subTest(independent_membership=independent_membership):
                f=FocusFixture();r=f.product(1,'camera','requested',1)
                r.update(entity=0,unit_type=3,army=1,incarnation=1)
                if independent_membership:r.update(source_ids=[0,11],logical_ids=[0,11])
                with self.assertRaises(AssertionError):f.evaluate()

    def test_actual_camera_pair_and_void_receipts_cannot_be_invented(self):
        for kind in('missing_return','changed_actor','camera_bool','retired_false','original_false_null'):
            with self.subTest(kind=kind):
                f=FocusFixture()
                if kind=='missing_return':f.products.remove(f.product(1,'camera','returned',1));f.renumber()
                elif kind=='changed_actor':f.product(1,'camera','returned',1)['actor']='00000400'
                elif kind=='camera_bool':f.product(1,'camera','returned',1)['original_result']=True
                elif kind=='retired_false':f.product(1,'terminal','world_retired')['original_result']=False
                else:f.product(2,'terminal','original_false')['original_result']=None
                with self.assertRaises(AssertionError):f.evaluate()

    def test_all_outer_iterations_and_original_pending_bits_are_required(self):
        f=FocusFixture();f.products.remove(f.product(1,'iteration',iteration=16));f.renumber()
        with self.assertRaisesRegex(AssertionError,'iteration coverage'):f.evaluate()
        for change in(dict(original_state=0),dict(yield_bits=0),dict(original_result=True),dict(actor='123')):
            with self.subTest(change=change):
                f=FocusFixture();f.product(1,'iteration','waiting_absent',17).update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_saved_pending_must_be_latest_and_after_complete_physical_release(self):
        f=FocusFixture()
        for world in(1,2):
            for ordinal,us in((16,211000),(17,212000)):
                r=f.product(world,'iteration','waiting_absent',ordinal)
                r.update(sampled_us=us+(world-1)*10000000,tick_ms=(us+(world-1)*10000000)//1000)
        f.renumber()
        with self.assertRaisesRegex(AssertionError,'after complete physical release'):f.evaluate()
        f=FocusFixture()
        for row in f.rows:
            if row['world']==2 and row['event']!='setup':row['pending_iteration']=16
        with self.assertRaisesRegex(AssertionError,'latest post-release'):f.evaluate()

    def test_waiting_absent_iteration_can_never_forward_a_camera(self):
        f=FocusFixture()
        for stage,us in(('requested',223995),('returned',223996)):
            row=deepcopy(f.product(1,'camera',stage,1));row.update(iteration=17,sampled_us=us,tick_ms=us//1000)
            f.products.append(row)
        f.renumber()
        with self.assertRaises(AssertionError):f.evaluate()

    def test_same_epoch_must_resume_current_member_and_persist_without_silent_restart(self):
        for kind in('no_resume','epoch','iterator','start','held_switch','ending'):
            with self.subTest(kind=kind):
                f=FocusFixture()
                if kind=='no_resume':
                    f.products=[r for r in f.products if not(r['world']==1 and r['event']=='camera' and r['iteration']==18)]
                    f.renumber()
                elif kind=='epoch':f.product(1,'iteration',iteration=18)['request_epoch']=999
                elif kind=='iterator':f.product(1,'iteration',iteration=18)['iterator']='00000400'
                elif kind=='start':
                    row=deepcopy(f.product(1,'start'));row.update(sampled_us=400000,tick_ms=400)
                    f.products.append(row);f.renumber()
                elif kind=='held_switch':f.product(1,'iteration','waiting_absent',17)['held_group']=3
                else:
                    row=deepcopy(f.product(1,'cancel_observed'))if any(r['world']==1 and r['event']=='cancel_observed'for r in f.products)else deepcopy(f.product(2,'cancel_observed'))
                    row.update(event='ending_observed',stage='ending_delegate',world=1,match=f.episodes[0]['match'],
                        request_epoch=1,iterator='00000201',iteration=18,sampled_us=225000,tick_ms=225,held_group=4)
                    f.products.append(row);f.renumber()
                with self.assertRaises(AssertionError):f.evaluate()

    def test_original_cancel_allows_real_yield_but_requires_eventual_original_false_without_camera(self):
        f=FocusFixture()
        self.assertTrue(f.product(2,'iteration','cancel_delegate',18)['original_result'])
        self.assertFalse(f.product(2,'iteration','cancel_delegate',19)['original_result'])
        self.assertTrue(f.evaluate()['passed'])
        for kind in('unobserved','ignored','not_false','missing_false_receipt','camera','late'):
            with self.subTest(kind=kind):
                f=FocusFixture()
                if kind=='unobserved':f.products=[r for r in f.products if not(r['world']==2 and r['event']=='cancel_observed')];f.renumber()
                elif kind=='ignored':f.product(2,'cancel_observed',iteration=18)['held_group']=4
                elif kind=='not_false':f.product(2,'iteration','cancel_delegate',19)['original_result']=True
                elif kind=='missing_false_receipt':f.products.remove(f.product(2,'terminal','original_false'));f.renumber()
                elif kind=='camera':
                    for stage,us in(('requested',226001),('returned',226002)):
                        row=deepcopy(f.product(2,'camera',stage,1));row.update(iteration=18,sampled_us=us+10000000,tick_ms=(us+10000000)//1000)
                        f.products.append(row)
                    f.renumber()
                else:
                    for r in f.products:
                        if r['world']==2 and r['iteration']==19 and r['stage']!='world_retired':r['sampled_us']+=1500000;r['tick_ms']+=1500
                    f.renumber()
                with self.assertRaises(AssertionError):f.evaluate()

    def test_runtime_failure_is_not_a_successful_post_scope_retirement(self):
        f=FocusFixture();r=f.product(1,'terminal','world_retired');r['stage']='failed'
        with self.assertRaisesRegex(AssertionError,'runtime failure'):f.evaluate()

    def test_later_canonical_ending_is_not_mislabelled_original_user_cancel(self):
        f=FocusFixture();template=deepcopy(f.product(2,'cancel_observed',iteration=18))
        for ordinal,us,result in((20,6200000,True),(21,6300000,False)):
            row=deepcopy(template);row.update(world=1,match=f.episodes[0]['match'],request_epoch=1,iterator='00000201',
                iteration=ordinal,event='ending_observed',stage='ending_delegate',held_group=4,sampled_us=us,tick_ms=us//1000)
            f.products.append(row)
            row=deepcopy(row);row.update(event='iteration',original_result=result,sampled_us=us+10,original_state=2 if result else -1)
            f.products.append(row)
        row=deepcopy(f.product(2,'terminal','original_false'));row.update(world=1,match=f.episodes[0]['match'],
            request_epoch=1,iterator='00000201',iteration=21,sampled_us=6300011,tick_ms=6300)
        f.products.append(row);f.product(1,'terminal','world_retired')['iteration']=21;f.renumber()
        self.assertEqual(f.evaluate()['episodes'][0]['path'],'held_focus_continuity')

    def test_false_terminal_without_actual_false_iteration_cannot_fake_original_completion(self):
        f=FocusFixture();r=f.product(1,'terminal','world_retired');r.update(stage='original_false',original_result=False)
        with self.assertRaisesRegex(AssertionError,'last delegated receipt'):f.evaluate()

    def test_focus_trace_cannot_replace_mobile_motion_replay_hash_or_preserved_group_gates(self):
        for kind in('mobile','motion','hash','replay','tail','group','edits','token'):
            with self.subTest(kind=kind):
                f=FocusFixture()
                if kind=='mobile':f.episodes[0]['passed']=False
                elif kind=='motion':f.episodes[0]['fresh_motion']['passed']=False
                elif kind=='hash':f.episodes[0]['fresh_assignment_span']['hashes_match']=False
                elif kind=='replay':f.episodes[0]['escape_native_replay']['promotion_group_replayed_delta']=0
                elif kind=='tail':f.episodes[0]['escape_native_replay']['continuation_frames']=19
                elif kind=='group':f.groups['episodes'][0]['retained_group4_preserved']=False
                elif kind=='edits':f.groups['user_edits']=True
                else:f.episodes[0]['fresh']['order']['incarnation']=99
                with self.assertRaises(AssertionError):f.evaluate()

    def test_nullable_candidate_schema_owner_bounds_and_extra_host_rows_are_strict(self):
        for change in(dict(actor=None),dict(member=1),dict(initialized=False),dict(current_lease=False),
                      dict(selector='0'),dict(request_epoch=True),dict(yield_bits=2**32),dict(extra=1),dict(original_state=True)):
            with self.subTest(change=change):
                f=FocusFixture();f.product(1,'camera','requested',1).update(change)
                with self.assertRaises(AssertionError):f.evaluate()
        f=FocusFixture();f.attacker='MOVEMENT FOCUS '+json.dumps(f.products[0])
        with self.assertRaisesRegex(AssertionError,'attacker'):f.evaluate()


class RecallFixture:
    def __init__(self):
        self.base=GroupFixture();self.episodes=self.base.episodes;self.groups=self.base.evaluate()
        self.rows=[];self.attacker=''
        for ep in self.episodes:
            token=ep['rows'][0]['original_incarnation']
            for event,frame,us in (('before_absent_recall',154,220100),('focus_cancelled',154,220200),
                                  ('after_absent_recall',154,220300),('before_restored_recall',164,350100),
                                  ('after_restored_recall',164,350200),('complete',260,5999995)):
                present=event in('before_restored_recall','after_restored_recall','complete')
                row=dict(schema=1,event=event,world=ep['world'],match=ep['match'],slot=1,entity=11,unit_type=1,army=1,
                    frame=frame,completed_frame=frame,tick_ms=us//1000,sampled_us=us,incarnation=token,
                    confirmed_incarnation=token,current_incarnation=token if present else 0,retained_group=4,group_ids=[11],
                    selected_ids=[11]if event in('after_restored_recall','complete')else[],preview_ids=[],casting_ids=[],
                    native_identity_present=present,current_admitted=present,source_resolvable_count=1 if present else 0,
                    current_actor='000001A0'if present else'0',
                    current_actual_entity=11 if present else None,current_actual_type=1 if present else None,
                    current_actual_army=1 if present else None,focus_group=-1,pending_commands=0,
                    cancel_callback=None,cancel_token=None,actuate_callback=None,actuate_token=None,actuate_result=None,physicalUI=False)
                if event=='focus_cancelled':
                    row.update(cancel_callback='Uncapped.UnitSelector.FocusControlGroupCancel',cancel_token='06002220')
                if event in('after_absent_recall','after_restored_recall'):
                    row.update(actuate_callback='Uncapped.UnitSelector.ActuateControlGroup',actuate_token='0600220f',actuate_result=present)
                self.rows.append(row)

    def evaluate(self):
        return mobile.evaluate_group_recall('\n'.join('MOBILE GROUP RECALL '+json.dumps(r)for r in self.rows),
            attacker_log=self.attacker,mobile_episodes=self.episodes,group_intent=self.groups)


class GroupRecallEvidenceTests(unittest.TestCase):
    def test_original_recall_excludes_unavailable_unit_then_selects_restored_lease_both_worlds(self):
        f=RecallFixture();r=f.evaluate()
        self.assertTrue(r['passed']);self.assertEqual(len(r['episodes']),2)
        for ep in r['episodes']:
            self.assertTrue(ep['unavailable_original_recall_selection_empty'])
            self.assertTrue(ep['restored_original_recall_selected_current'])
            self.assertTrue(ep['retained_group4_preserved']);self.assertEqual(ep['same_confirmed_incarnation'],7)
            self.assertEqual(ep['absent_recall_classification'],'legal_absent_refusal')
            self.assertTrue(ep['legal_refusal_selection_unchanged']);self.assertFalse(ep['absent_empty_selection_branch_exercised'])
            self.assertEqual(ep['absent_selected_before'],[]);self.assertEqual(ep['restored_selected_after'],[11])
        self.assertFalse(r['physicalUI']);self.assertFalse(r['active_casting_exercised'])
        self.assertFalse(r['full_mobile_controls_accepted']);self.assertTrue(r['requires_controller_full_closed_native_parity'])

    def test_original_before_selection_truth_and_same_pointer_token_are_not_fabricated_transitions(self):
        f=RecallFixture()
        for row in f.rows[:3]:row['source_resolvable_count']=1
        f.rows[2]['actuate_result']=True
        f.rows[0]['selected_ids']=f.rows[1]['selected_ids']=[11];f.rows[3]['selected_ids']=[11]
        r=f.evaluate();self.assertEqual(r['episodes'][0]['absent_selected_before'],[11])
        self.assertEqual(r['episodes'][0]['absent_recall_classification'],'excluded_on_recall')
        self.assertTrue(r['episodes'][0]['absent_empty_selection_branch_exercised'])
        self.assertIsNone(r['episodes'][0]['legal_refusal_selection_unchanged'])
        self.assertEqual(r['episodes'][0]['restored_selected_before'],[11])
        self.assertEqual(r['episodes'][0]['rows'][3]['current_actor'],f.episodes[0]['rows'][0]['original_actor'])

    def test_original_callback_completion_result_tokens_and_cancel_state_are_required(self):
        for index,change in((1,dict(cancel_callback=None)),(1,dict(cancel_token='0600220f')),(1,dict(focus_group=4)),
                            (2,dict(actuate_callback=None)),(2,dict(actuate_result=True)),(2,dict(actuate_result=1)),
                            (4,dict(actuate_token='06002220')),(4,dict(actuate_result=None)),
                            (0,dict(cancel_callback='Uncapped.UnitSelector.FocusControlGroupCancel'))):
            with self.subTest(index=index,change=change):
                f=RecallFixture();f.rows[index].update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_retained_numeric_id_is_not_absent_native_admission_or_selection(self):
        for change in(dict(native_identity_present=True),dict(current_admitted=True),dict(current_actor='000001A0'),
                      dict(current_incarnation=7),dict(current_actual_entity=11),dict(selected_ids=[11]),dict(preview_ids=[11])):
            with self.subTest(change=change):
                f=RecallFixture();f.rows[2].update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_legal_absent_refusal_preserves_actual_nonempty_selector_scratch_without_inventing_filter(self):
        f=RecallFixture()
        for row in f.rows[:3]:row.update(selected_ids=[11],preview_ids=[11],casting_ids=[11])
        ep=f.evaluate()['episodes'][0]
        self.assertEqual(ep['absent_recall_classification'],'legal_absent_refusal')
        self.assertFalse(ep['unavailable_original_recall_selection_empty'])
        self.assertFalse(ep['absent_empty_selection_branch_exercised'])
        for key in ('selected_ids','preview_ids','casting_ids'):
            with self.subTest(key=key):
                g=RecallFixture();g.rows[2][key]=[11]
                with self.assertRaisesRegex(AssertionError,'Count0 refusal'):g.evaluate()

    def test_count_result_and_real_empty_branch_must_agree_and_restored_count_must_be_one(self):
        for kind in('count_mismatch','true_with_zero','false_with_one','one_selected','one_preview','restored_zero'):
            with self.subTest(kind=kind):
                f=RecallFixture()
                if kind=='count_mismatch':f.rows[2]['source_resolvable_count']=1
                elif kind=='true_with_zero':f.rows[2]['actuate_result']=True
                elif kind=='restored_zero':f.rows[3]['source_resolvable_count']=0
                else:
                    f.rows[1]['source_resolvable_count']=f.rows[2]['source_resolvable_count']=1
                    if kind!='false_with_one':f.rows[2]['actuate_result']=True
                    if kind=='one_selected':f.rows[2]['selected_ids']=[11]
                    if kind=='one_preview':f.rows[2]['preview_ids']=[11]
                with self.assertRaises(AssertionError):f.evaluate()

    def test_restored_recall_requires_actual_current_own_matching_admitted_lease(self):
        for change in(dict(native_identity_present=False),dict(current_admitted=False),dict(current_actor='0'),
                      dict(current_incarnation=8),dict(current_actual_entity=10),dict(current_actual_type=3),
                      dict(current_actual_army=0),dict(selected_ids=[])):
            with self.subTest(change=change):
                f=RecallFixture();f.rows[4].update(change)
                with self.assertRaisesRegex(AssertionError,'restored recall'):f.evaluate()

    def test_same_canonical_group_intent_cannot_be_lost_or_rebound_to_new_incarnation(self):
        for change in(dict(group_ids=[]),dict(group_ids=[10]),dict(confirmed_incarnation=8),
                      dict(incarnation=8),dict(retained_group=3)):
            with self.subTest(change=change):
                f=RecallFixture();f.rows[0].update(change)
                with self.assertRaises(AssertionError):f.evaluate()

    def test_both_rounds_exact_event_order_no_extra_match_host_or_duplicates(self):
        for kind in('missing','duplicate','extra_match','host','world','order'):
            with self.subTest(kind=kind):
                f=RecallFixture()
                if kind=='missing':f.rows.pop()
                elif kind=='duplicate':f.rows.append(deepcopy(f.rows[-1]))
                elif kind=='extra_match':f.rows[0]['match']='f'*32
                elif kind=='host':f.attacker='MOBILE GROUP RECALL '+json.dumps(f.rows[0])
                elif kind=='world':f.rows[0]['world']=999
                else:f.rows[1],f.rows[2]=f.rows[2],f.rows[1]
                with self.assertRaises(AssertionError):f.evaluate()

    def test_recall_must_run_in_actual_absent_and_restored_windows_before_fresh_input(self):
        for index,change in((0,dict(sampled_us=219999)),(2,dict(sampled_us=350000)),
                            (3,dict(sampled_us=349999)),(4,dict(sampled_us=1490000,tick_ms=1490)),
                            (5,dict(sampled_us=6000001)),(2,dict(frame=155))):
            with self.subTest(index=index,change=change):
                f=RecallFixture();f.rows[index].update(change)
                with self.assertRaises(AssertionError):f.evaluate()
        # Checked QPC floors can tie; source event order is retained explicitly.
        f=RecallFixture();f.rows[1]['sampled_us']=f.rows[0]['sampled_us']
        self.assertTrue(f.evaluate()['passed'])

    def test_recall_cannot_substitute_for_mobile_motion_native_confirmation_replay_or_group_proof(self):
        for kind in('mobile','motion','span','replay','tail','groups','edits','group_world','group_loss'):
            with self.subTest(kind=kind):
                f=RecallFixture()
                if kind=='mobile':f.episodes[0]['passed']=False
                elif kind=='motion':f.episodes[0]['fresh_motion']['passed']=False
                elif kind=='span':f.episodes[0]['fresh_assignment_span']['hashes_match']=False
                elif kind=='replay':f.episodes[0]['escape_native_replay']['promotion_group_replayed_delta']=0
                elif kind=='tail':f.episodes[0]['escape_native_replay']['continuation_frames']=19
                elif kind=='groups':f.groups['passed']=False
                elif kind=='edits':f.groups['user_edits']=True
                elif kind=='group_world':f.groups['episodes'][0]['world']=999
                else:f.groups['episodes'][0]['retained_group4_preserved']=False
                with self.assertRaises(AssertionError):f.evaluate()

    def test_nullable_types_finite_integer_bounds_observed_sets_and_physical_scope_are_strict(self):
        for change in(dict(current_actual_type=False),dict(native_identity_present=0),dict(completed_frame=-2),
                      dict(sampled_us=float('nan')),dict(pending_commands=-1),dict(pending_commands=1),
                      dict(source_resolvable_count=True),dict(source_resolvable_count=2),dict(selected_ids=[11,11]),
                      dict(casting_ids=[-1]),dict(current_actor=None),dict(physicalUI=True),dict(extra=True)):
            with self.subTest(change=change):
                f=RecallFixture();f.rows[0].update(change)
                with self.assertRaises(AssertionError):f.evaluate()


class RecoveryStallEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.matches=['a'*32,'b'*32]
        self.marker=dict(schema=1,event='main_thread_stall',world=2,match=self.matches[1],slot=1,frame=152,
            requested_ms=250,begin_us=1010000,end_us=1260000,presented_before=152,presented_after=152,
            completed_before=152,completed_after=153,qpc_scope='Sleep(250) only',physicalUI=False)
        self.snapshots=[dict(schema=1,event='snapshot',world=2,match=self.matches[1],entity=11,unit_type=1,army=1,
                             frame=f,sampled_us=us,physicalUI=False)for f,us in((152,1000000),(153,1300000))]
        self.modes=[dict(schema=1,event='queued_mode',world=2,match=self.matches[1],frame=f,active=active,
                         decision_us=us,queue_return_us=us+1000,target_assigned=f+3,native_dt_us=50000)
                    for f,active,us in((153,True,1270000),(174,False,2000000))]
        self.fresh=dict(schema=1,event='original_fresh_move',world=2,match=self.matches[1],entity=11,unit_type=1,army=1,
            frame=180,queueDelta=1,originalCtor=True,reselected_current=True,physicalUI=False,
            origin_sampled_us=2199000,sampled_us=2200000,enqueue_sampled_us=2201000)
        self.markers=[self.marker];self.attacker=''

    def evaluate(self):
        lines=[]
        for world,match in enumerate(self.matches,1):
            lines.append(f'Movement prediction ready: generation={world} match={match} world={world} slot=1 original=1')
            lines.extend('MOVEMENT RECOVERY '+json.dumps(r)for r in self.modes if r['world']==world)
        # World values outside the accepted BEGINs must not disappear in this fixture.
        lines.extend('MOVEMENT RECOVERY '+json.dumps(r)for r in self.modes if r['world']not in(1,2))
        log='\n'.join(lines)+'\n'+'\n'.join('MOBILE CORRECTION '+json.dumps(r)for r in self.snapshots)+'\n'+\
            '\n'.join('MOBILE RECOVERY STALL '+json.dumps(r)for r in self.markers)+'\nMOBILE ORDER '+json.dumps(self.fresh)
        return mobile.evaluate_recovery_stall(log,attacker_log=self.attacker,matches=self.matches)

    def test_exact_second_world_hold_between_actual_snapshots_and_inflight_completion(self):
        r=self.evaluate();self.assertTrue(r['passed']);self.assertEqual(r['actual_elapsed_ms'],250)
        self.assertEqual(r['world'],2);self.assertEqual(r['match'],self.matches[1])
        self.assertNotEqual(r['event']['completed_before'],r['event']['completed_after'])
        self.assertTrue(r['recovered_before_fresh_original_input'])
        self.assertTrue(r['recovery_entry']['active']);self.assertFalse(r['recovery_exit']['active'])
        self.assertFalse(r['body_phase_qualified_by_this_gate']);self.assertFalse(r['full_feature_accepted'])

    def test_missing_or_unclosed_recovery_mode_does_not_prove_recovery(self):
        for selected in((),(0,),(1,)):
            with self.subTest(selected=selected):
                self.setUp();self.modes=[self.modes[i]for i in selected]
                with self.assertRaises(AssertionError):self.evaluate()

    def test_recovery_must_enter_after_sleep_and_exit_before_actual_fresh_enqueue(self):
        for index,change in((0,dict(decision_us=1259999)),(0,dict(frame=152)),
                            (1,dict(queue_return_us=2200000)),(1,dict(decision_us=2200001,queue_return_us=2200002)),
                            (1,dict(frame=182))):
            with self.subTest(index=index,change=change):
                self.setUp();self.modes[index].update(change)
                with self.assertRaises(AssertionError):self.evaluate()
        # One unpresented native output can queue181 before original input180.
        self.setUp();self.modes[1]['frame']=181;self.assertTrue(self.evaluate()['passed'])

    def test_queued_mode_schema_clock_identity_and_alternation_are_strict(self):
        changes=(dict(active=1),dict(active=False),dict(schema=True),dict(native_dt_us=35000),
                 dict(target_assigned=True),dict(world=3),dict(match='c'*32),dict(frame=True),
                 dict(queue_return_us=1269999),dict(extra=1))
        for change in changes:
            with self.subTest(change=change):
                self.setUp();self.modes[0].update(change)
                with self.assertRaises(AssertionError):self.evaluate()
        self.setUp();self.modes.append(deepcopy(self.modes[-1]))
        with self.assertRaisesRegex(AssertionError,'alternate'):self.evaluate()
        self.setUp();self.modes[1]['frame']=153
        with self.assertRaisesRegex(AssertionError,'queue order'):self.evaluate()

    def test_before_hold_must_be_inactive_but_other_natural_recovery_chains_are_retained(self):
        old=deepcopy(self.modes)
        for r,f,active,us in zip(old,(140,142),(True,False),(800000,900000)):
            r.update(frame=f,active=active,decision_us=us,queue_return_us=us+1000)
        self.modes=old+self.modes
        self.assertTrue(self.evaluate()['passed'])
        self.modes.pop(1)
        with self.assertRaises(AssertionError):self.evaluate()
        self.setUp()
        first=[]
        for r in old:
            r=deepcopy(r);r.update(world=1,match=self.matches[0]);first.append(r)
        self.modes=first+self.modes
        ready=f'Movement prediction ready: generation=1 match={self.matches[0]} world=1 slot=0 original=1'
        self.attacker=ready+'\n'+'\n'.join('MOVEMENT RECOVERY '+json.dumps(r)for r in first)
        result=self.evaluate();self.assertEqual(len(result['victim_mode_changes'][1]),2)
        self.assertEqual(len(result['attacker_mode_changes'][1]),2)
        self.attacker=self.attacker.replace('slot=0','slot=1')
        with self.assertRaisesRegex(AssertionError,'BEGIN'):self.evaluate()

    def test_fresh_original_order_identity_source_and_clock_are_required(self):
        for change in(dict(world=1),dict(frame=181),dict(entity=10),dict(army=0),dict(unit_type=3),dict(queueDelta=0),
                      dict(originalCtor=False),dict(reselected_current=False),dict(physicalUI=True),
                      dict(sampled_us=1999999),dict(enqueue_sampled_us=2199999),dict(origin_sampled_us=True)):
            with self.subTest(change=change):
                self.setUp();self.fresh.update(change)
                with self.assertRaises(AssertionError):self.evaluate()

    def test_short_or_invalid_qpc_hold_is_rejected(self):
        for change in(dict(end_us=1259999),dict(end_us=1000000),dict(begin_us=True),dict(end_us=1260000.0)):
            with self.subTest(change=change):
                self.setUp();self.marker.update(change)
                with self.assertRaises(AssertionError):self.evaluate()

    def test_hold_before152_or_after153_cannot_be_claimed_in_correct_window(self):
        for change in(dict(begin_us=999999,end_us=1250000),dict(end_us=1300001)):
            with self.subTest(change=change):
                self.setUp();self.marker.update(change)
                with self.assertRaisesRegex(AssertionError,'normal152'):self.evaluate()

    def test_wrong_world_slot_match_frame_scope_or_requested_hold_is_rejected(self):
        for change in(dict(world=1),dict(slot=0),dict(match=self.matches[0]),dict(frame=153),dict(requested_ms=249),
                      dict(qpc_scope='includes owner queries'),dict(physicalUI=True)):
            with self.subTest(change=change):
                self.setUp();self.marker.update(change)
                with self.assertRaises(AssertionError):self.evaluate()

    def test_no_missing_extra_duplicate_or_host_hold(self):
        self.markers=[]
        with self.assertRaises(AssertionError):self.evaluate()
        self.setUp();self.markers.append(deepcopy(self.marker))
        with self.assertRaises(AssertionError):self.evaluate()
        self.setUp();self.attacker='MOBILE RECOVERY STALL '+json.dumps(self.marker)
        with self.assertRaisesRegex(AssertionError,'attacker'):self.evaluate()

    def test_snapshot_bracket_and_actual_begin_binding_must_be_unique_and_matching(self):
        self.snapshots.pop()
        with self.assertRaises(AssertionError):self.evaluate()
        self.setUp();self.snapshots.append(deepcopy(self.snapshots[0]))
        with self.assertRaises(AssertionError):self.evaluate()
        self.setUp();self.snapshots[0]['world']=1
        with self.assertRaises(AssertionError):self.evaluate()
        self.setUp();self.matches.reverse()
        with self.assertRaises(AssertionError):self.evaluate()

    def test_actual_presented_must_not_regress_or_skip_completed_may_advance(self):
        self.marker['presented_after']=153;self.assertTrue(self.evaluate()['passed'])
        for change in(dict(presented_after=151),dict(presented_after=154),dict(completed_after=151),dict(completed_before=-2)):
            with self.subTest(change=change):
                self.setUp();self.marker.update(change)
                with self.assertRaises(AssertionError):self.evaluate()


if __name__ == '__main__':
    unittest.main()
