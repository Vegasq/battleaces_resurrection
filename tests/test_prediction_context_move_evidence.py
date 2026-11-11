"""Small pure context/wire corruption controls; no native target is loaded."""
from copy import deepcopy
import json
import unittest

from server.game_data import encode_identity, encode_player_input
from tests.test_prediction_mobile_evidence import Fixture, move
from tools import prediction_context_move_evidence as context
from tools import prediction_mobile_evidence as mobile
from tools import verify_prediction_multiplayer as controller


class ContextMoveEvidenceTests(unittest.TestCase):
    def witness(self):
        f=Fixture()
        normal=dict(sequence=2,source_next_frame=181,tick_ms=1500)
        order=dict(f.order,command='cad',originalCtor=False,normal_sequence=2)
        return f,dict(match=f.match,serialized=normal,order=order)

    def test_hash_is_derived_from_the_normal_body_without_rewriting_the_order(self):
        f,w=self.witness();before=deepcopy(w)
        result=context.fresh_order(w,f.bodies)
        self.assertEqual(result['action_sha256'],mobile.digest(f.fresh_action))
        self.assertEqual(result['normal_sequence'],2)
        self.assertEqual(w,before)
        result['normal_serialization']['tick_ms']=1500
        self.assertEqual(mobile._fresh_binding(f.log(),result,match=f.match,commits=f.commits,
            raw_bodies=f.bodies,journal=f.journal)['sequence'],2)

    def test_missing_wrong_source_wrong_ability_or_multiple_actions_cannot_supply_the_hash(self):
        for change in ('missing','entity','ability','multiple'):
            f,w=self.witness()
            if change=='missing':f.bodies.pop((f.match,1,2))
            else:
                actions=[move(12 if change=='entity' else 11,[21.,0.,0.],13 if change=='ability' else 12)]
                if change=='multiple':actions*=2
                f.bodies[f.match,1,2]=encode_player_input(encode_identity(2,'Victim'),actions)
            with self.subTest(change=change),self.assertRaises(AssertionError):
                context.fresh_order(w,f.bodies)

    def test_normal_body_still_requires_original_target_bits_and_sender_sequence(self):
        for change in ('target','sequence','source_frame'):
            f,w=self.witness();order=context.fresh_order(w,f.bodies)
            if change=='target':order['target_bits'][0]=0
            elif change=='sequence':order['normal_sequence']=3
            else:order['normal_serialization']['source_next_frame']=182
            with self.subTest(change=change),self.assertRaises(AssertionError):
                mobile._fresh_binding(f.log(),order,match=f.match,commits=f.commits,
                    raw_bodies=f.bodies,journal=f.journal)

    def test_post_down_observation_scope_is_bounded_by_actual_callback_and_completion(self):
        w=dict(callbacks=[{},dict(sampled_us=100,frame=186)],events=dict(complete=dict(sampled_us=200,frame=260)))
        self.assertTrue(context.post_down_scope(w,dict(sampled_us=150,frame=187)))
        for row in (dict(sampled_us=99,frame=187),dict(sampled_us=201,frame=260),dict(sampled_us=150,frame=185)):
            self.assertFalse(context.post_down_scope(w,row))

    def test_strict_prefix_refuses_duplicate_keys_old_schema_and_missing_episode(self):
        row=dict(schema=1,world=1,match='a'*32,frame=186,tick_ms=1,sampled_us=1,physicalUI=False)
        fields=set(row)
        self.assertEqual(context._rows('CONTEXT ORDER '+json.dumps(row),'CONTEXT ORDER ',fields,1)[0][1],row)
        for log in ('CONTEXT ORDER '+json.dumps(dict(row,schema=2)),
                'CONTEXT ORDER '+json.dumps(row).replace('"schema": 1','"schema": 1,"schema": 1')):
            with self.assertRaises(AssertionError):context._rows(log,'CONTEXT ORDER ',fields,1)
        with self.assertRaises(AssertionError):context.records('',row['match'])

    def test_final_gate_cannot_accept_an_unbound_context_claim(self):
        self.assertFalse(controller.mobile_context_move_gate(dict(mobile_context_move_witness_passed=True,
            mobile_context_move=dict(passed=True,evidence_schema=1,episodes=[]))))


if __name__=='__main__':unittest.main()
