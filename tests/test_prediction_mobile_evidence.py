"""Authored retained-evidence controls; no native DLL/process is used."""
from copy import deepcopy
import json
import struct
import unittest

from server.game_data import encode_identity, encode_player_input
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint
from tools import prediction_mobile_evidence as mobile
from tools import verify_prediction_multiplayer as controller


def move(entity, target):
    position = b''.join(field_uint(n, int(v * 2**32) & (2**64-1)) for n, v in enumerate(target, 1))
    group = field_uint(1, 1) + field_uint(2, 12) + field_packed_uint(3, [entity])
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
