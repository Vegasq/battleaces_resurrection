"""Authored observations for pure joins; no device/native/game execution."""
from copy import deepcopy
import json
import struct
import unittest
from unittest.mock import patch

from tools import prediction_expired_click_evidence as evidence
from tools import verify_prediction_multiplayer as verifier


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def fixture():
    records, episodes = [], []
    for index, match in enumerate(('a' * 32, 'b' * 32)):
        world, update_base, time_base = index + 1, index * 1000, index * 50
        actor = [dict(schema=1, event=event, world=world, match=match, entity=5, army=1, unit_type=3,
            frame=frame, tick_ms=1000 + index * 10000 + frame, original_actor='100',
            current_actor='100' if n < 2 else '200', original_focus_supported=False,
            original_group_supported=False, focus_retained_at_death=False, physicalUI=False)
            for n, (event, frame) in enumerate(zip(evidence.ACTOR_EVENTS, (130,155,161,163)))]
        episodes.append(dict(match=match, passed=True, rows=actor))
        frames = (120,121,122,123,129,129,130,155,161,164)
        updates = (100,101,102,103,112,112,113,150,160,164)
        times = (8,8.1,8.2,8.25,8.75,8.75,8.8,10,10.3,10.5)
        for n, event in enumerate(evidence.PHASES):
            if n in (6,7,8,9):
                records.append(('ACTOR CORRECTION ', actor[n - 6]))
            row = dict(schema=1, event=event, sequence=n + 1, world=world, match=match, slot=1, entity=5,
                frame=frames[n], update=update_base + updates[n], update_scope='original_frontend_callback',
                input_sequence=(0,1,2,3,3,3,3,3,3,3)[n], selector='AA', action='BB', control='CC', device='DD',
                input_source='bound_existing_mouse',ownership_scope='borrowed_current' if n < 5 else 'retained_scalar',
                owned_button=n == 2 if n < 5 else None, input_closed=n >= 5,
                click_id=5 if n >= 2 else 2**32 - 1, mode=1 if n == 2 else 0,
                primary=n == 2, context=False, drag=False,
                now_bits=bits(time_base + times[n]), last_up_bits=bits(time_base + 8.25 if n >= 3 else 0),
                window_bits=bits(0.25), originalClockSingle=True, physicalUI=False)
            records.append((evidence.PREFIX, row))
    return records, episodes


def render(records):
    return '\n'.join('[1000] ' + prefix + json.dumps(row, separators=(',', ':')) for prefix, row in records)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.records, self.episodes = fixture()

    def run_evidence(self):
        return evidence.evaluate(render(self.records), actor_episodes=self.episodes, expected_matches=['a' * 32,'b' * 32])

    def click(self, phase, world=1):
        return next(row for prefix, row in self.records if prefix == evidence.PREFIX and
                    row['event'] == phase and row['world'] == world)

    def test_both_owned_histories_join_full_actor_proofs_without_physical_claim(self):
        result = self.run_evidence()
        self.assertTrue(result['passed'])
        self.assertFalse(result['physical_input_exercised'] or result['inputsystem_update_serial_observed'])
        self.assertEqual([row['world'] for row in result['episodes']], [1,2])
        self.assertEqual(result['episodes'][0]['expired_elapsed_seconds'], 0.5)
        self.assertTrue(all(row['history_unchanged'] for row in result['episodes']))
        self.assertTrue(all(row['bound_existing_process_device_exercised'] and
            not row['owned_virtual_device_exercised'] and not row['native_device_removed'] for row in result['episodes']))

    def test_missing_duplicate_and_reordered_phase_refuse(self):
        original = deepcopy(self.records)
        for change in ('missing','duplicate','reorder'):
            self.records = deepcopy(original)
            index = next(i for i, (prefix, row) in enumerate(self.records) if prefix == evidence.PREFIX and row['event'] == 'pressed')
            if change == 'missing': self.records.pop(index)
            if change == 'duplicate': self.records.insert(index, deepcopy(self.records[index]))
            if change == 'reorder': self.records[index], self.records[index + 1] = self.records[index + 1], self.records[index]
            with self.subTest(change=change), self.assertRaises(AssertionError): self.run_evidence()

    def test_queue_sequence_alone_cannot_substitute_for_actual_button_and_selector_observation(self):
        original = deepcopy(self.records)
        for phase, key, value in (('pressed','owned_button',False),('pressed','primary',False),
                ('released','primary',True),('pressed','update',101),('released','update_scope','InputSystem.Update')):
            self.records = deepcopy(original);self.click(phase)[key] = value
            with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError): self.run_evidence()

    def test_exact_single_expiry_equality_and_invalid_bits_refuse(self):
        original = deepcopy(self.records)
        for value in (bits(8.5), 0x7f800000, 0x7fc00000, True):
            self.records = deepcopy(original);self.click('expired_before_setup')['now_bits'] = value
            with self.subTest(value=value), self.assertRaises(AssertionError): self.run_evidence()

    def test_history_change_and_device_identity_or_liveness_forgery_refuse(self):
        original = deepcopy(self.records)
        for phase, key, value in (('after_setup','last_up_bits',bits(8)),('hq_restored','click_id',2**32 - 1),
                ('released','device','EE'),('input_closed','owned_button',False),('complete','ownership_scope','current'),
                ('focused','mode',True),('focused','input_source','added_virtual_mouse')):
            self.records = deepcopy(original);self.click(phase)[key] = value
            with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError): self.run_evidence()

    def test_missing_or_wrong_full_actor_proof_cannot_be_replaced_by_click_rows(self):
        self.episodes[1]['passed'] = False
        with self.assertRaisesRegex(AssertionError, 'both full'): self.run_evidence()
        self.episodes[1]['passed'] = True;self.episodes[1]['rows'][2] = dict(self.episodes[1]['rows'][2], frame=162)
        with self.assertRaisesRegex(AssertionError, 'same retained source'): self.run_evidence()

    def test_click_frame_and_source_order_must_match_actual_actor_episode(self):
        self.click('dead_hq_retained')['frame'] = 156
        with self.assertRaisesRegex(AssertionError, 'source/frame'): self.run_evidence()
        self.records, self.episodes = fixture()
        actor_index = next(i for i, (prefix, _) in enumerate(self.records) if prefix == 'ACTOR CORRECTION ')
        actor = self.records.pop(actor_index);self.records.insert(actor_index + 1, actor)
        with self.assertRaisesRegex(AssertionError, 'source/frame'): self.run_evidence()

    def test_duplicate_json_keys_unknown_fields_and_crossworld_callback_regression_refuse(self):
        text = render(self.records).replace('"schema":1', '"schema":1,"schema":1', 1)
        with self.assertRaisesRegex(AssertionError, 'duplicate JSON'):
            evidence.evaluate(text, actor_episodes=self.episodes, expected_matches=['a' * 32,'b' * 32])
        self.click('complete')['unobserved_cleanup'] = True
        with self.assertRaises(AssertionError): self.run_evidence()
        self.records, self.episodes = fixture();self.click('focused',2)['update'] = 99
        with self.assertRaisesRegex(AssertionError, 'across matches'): self.run_evidence()


class ControllerGateTests(unittest.TestCase):
    def setUp(self):
        self.records, self.episodes = fixture()
        self.plan = dict(expired_click=True, actor_correction=True, scenario='movement', lifecycle='natural',
            frames=650, expected_matches=2, move_slot=0, rtt_ms=[130,475])
        self.contexts = [dict(log=render(self.records), match=row['match']) for row in self.episodes]
        self.report = dict(matches=[dict(match=row['match']) for row in self.episodes], actor_correction=dict(passed=True))

    def test_two_real_actor_checker_calls_and_additive_final_gate(self):
        returns = [{key:value for key,value in row.items() if key != 'match'} for row in self.episodes]
        with patch.object(verifier, 'actor_correction_evidence', side_effect=returns) as actor:
            verifier.finalize_expired_click_observation(self.report, self.plan, contexts=self.contexts, worker_states=['actual rows'])
        self.assertEqual([call.kwargs['match'] for call in actor.call_args_list], ['a' * 32,'b' * 32])
        self.assertTrue(verifier.expired_click_final_gate(self.plan,self.report))
        self.report['expired_click_witness_passed'] = False
        self.assertFalse(verifier.expired_click_final_gate(self.plan,self.report))
        self.assertTrue(verifier.expired_click_final_gate({},{}))

    def test_primary_actor_failure_and_second_actor_failure_remain_fatal(self):
        self.report['actor_correction']['passed'] = False
        with patch.object(verifier, 'actor_correction_evidence') as actor, self.assertRaises(AssertionError):
            verifier.finalize_expired_click_observation(self.report,self.plan,contexts=self.contexts,worker_states=[])
        actor.assert_not_called();self.assertFalse(self.report['expired_click_witness_passed'])
        self.report['actor_correction']['passed'] = True
        returns = [{key:value for key,value in row.items() if key != 'match'} for row in self.episodes]
        returns[1]['passed'] = False
        with patch.object(verifier, 'actor_correction_evidence', side_effect=returns), self.assertRaises(AssertionError):
            verifier.finalize_expired_click_observation(self.report,self.plan,contexts=self.contexts,worker_states=[])

    def test_typed_plan_scope_is_rechecked_at_later_boundaries(self):
        for key,value in (('expired_click',1),('actor_correction',False),('frames',600),('rtt_ms',[475,130]),
                          ('mobile_correction',True),('changing_rtt',True),('expected_matches',1),('move_slot',1)):
            plan = dict(self.plan, **{key:value})
            with self.subTest(key=key), self.assertRaises(AssertionError): verifier.validate_expired_click_plan(plan)


if __name__ == '__main__':
    unittest.main()
