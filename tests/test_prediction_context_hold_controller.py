"""Pure Hold preparation and final-gate controls; no native process."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from tests import test_prediction_context_move_controller as context_controller
from tools import verify_prediction_multiplayer as controller


class ContextHoldControllerTests(unittest.TestCase):
    def setUp(self):
        self.base=context_controller.ContextMovePreparationTests('test_marker_scope_and_both_argv_require_explicit_context_option')
        self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.args=self.base.args;self.args.mobile_context_hold=True

    def test_hold_requires_both_explicit_flags_helper_marker_and_exact_original_scope(self):
        self.base.marker()
        with patch.object(controller.subprocess,'Popen',side_effect=AssertionError('Native forbidden')):
            with self.assertRaisesRegex(AssertionError,'helper lacks explicit'):controller.prepare(self.args)
            self.assertFalse(self.args.output.exists())
            fixture=self.base.base.fixture;helper=fixture.game/'BattleAcesOffline.dll'
            helper.write_bytes(helper.read_bytes()+'-prediction-mobile-context-hold-smoke'.encode('utf-16-le'))
            self.args.expected_helper_sha256=controller.sha(helper)
            for path in (fixture.game/'.battleaces-resurrection/patch-manifest.json',fixture.args.helper_build_receipt):
                row=json.loads(path.read_text());row['helper_sha256']=controller.sha(helper);path.write_text(json.dumps(row))
            plan=controller.prepare(self.args);controller.verify_prepared(self.args.output)
        self.assertTrue(plan['mobile_context_hold'])
        for slot in (0,1):
            flags=controller.command_extra(plan,slot,self.args.output/'run')
            self.assertEqual(flags.count('-prediction-mobile-context-hold-smoke'),1)
            self.assertEqual(flags.count('-prediction-mobile-context-move-smoke'),1)
        for changes in (dict(mobile_context_move=False),dict(mobile_context_hold=1),dict(mobile_held_click=True),
                dict(frames=600),dict(rtt_ms=[475,130]),dict(move_slot=1)):
            with self.subTest(changes=changes),self.assertRaises(AssertionError):
                controller.command_extra(dict(plan,**changes),0,self.args.output/'run')

    def test_hold_does_not_sneak_into_plain_context_defaults(self):
        self.args.mobile_context_hold=False;self.base.marker();plan=controller.prepare(self.args)
        self.assertNotIn('mobile_context_hold',plan)
        self.assertNotIn('-prediction-mobile-context-hold-smoke',controller.command_extra(plan,0,self.args.output/'run'))

    def test_final_gate_requires_stop_native_continuations_and_exact_episode_binding(self):
        row=dict(passed=True,scope='context',world=1,match='a'*32,rows=[{}, {}, {}],stop=dict(passed=True),
            native_confirmation=dict(continuation_frames=20),normal_serialization_only=True,originalCtor=False,
            binding=dict(ability=14,instant=True))
        other=dict(deepcopy(row),world=2,match='b'*32)
        report=dict(mobile_context_hold_witness_passed=True,mobile_context_hold=dict(passed=True,evidence_schema=1,scope='context',
            originalCtor=False,physicalUI=False,selection_writes=0,history_writes=0,episodes=[row,other]),
            mobile_correction=dict(episodes=[dict(world=x['world'],match=x['match'],mobile_context_hold=deepcopy(x)) for x in (row,other)]))
        with patch.object(controller,'mobile_context_move_gate',return_value=True):
            self.assertTrue(controller.mobile_context_hold_gate(report))
            for change in ('stop','continuation','unbound'):
                altered=deepcopy(report)
                if change=='stop':altered['mobile_context_hold']['episodes'][0]['stop']['passed']=False
                elif change=='continuation':altered['mobile_context_hold']['episodes'][0]['native_confirmation']['continuation_frames']=0
                else:altered['mobile_correction']['episodes'][0]['mobile_context_hold']['rows']=[]
                with self.subTest(change=change):self.assertFalse(controller.mobile_context_hold_gate(altered))

    def test_standalone_requires_its_own_marker_and_excludes_both_context_modes(self):
        self.args.mobile_context_move=False;self.args.mobile_context_hold=False;self.args.mobile_original_hold=True
        self.base.marker();fixture=self.base.base.fixture;helper=fixture.game/'BattleAcesOffline.dll'
        with self.assertRaisesRegex(AssertionError,'helper lacks explicit'):controller.prepare(self.args)
        self.assertFalse(self.args.output.exists())
        helper.write_bytes(helper.read_bytes()+'-prediction-mobile-original-hold-smoke'.encode('utf-16-le'))
        self.args.expected_helper_sha256=controller.sha(helper)
        for path in (fixture.game/'.battleaces-resurrection/patch-manifest.json',fixture.args.helper_build_receipt):
            row=json.loads(path.read_text());row['helper_sha256']=controller.sha(helper);path.write_text(json.dumps(row))
        with patch.object(controller.subprocess,'Popen',side_effect=AssertionError('Native forbidden')):
            plan=controller.prepare(self.args);controller.verify_prepared(self.args.output)
        self.assertTrue(plan['mobile_original_hold'])
        for slot in (0,1):
            flags=controller.command_extra(plan,slot,self.args.output/'run')
            self.assertIn('-prediction-mobile-original-hold-smoke',flags)
            self.assertNotIn('-prediction-mobile-context-move-smoke',flags)
            self.assertNotIn('-prediction-mobile-context-hold-smoke',flags)
        for changes in [dict(mobile_original_hold=1)]+[{k:True}for k in controller.MOBILE_ORIGINAL_HOLD_EXCLUSIONS]:
            with self.subTest(changes=changes),self.assertRaises(AssertionError):
                controller.command_extra(dict(plan,**changes),0,self.args.output/'run')

    def test_standalone_final_gate_cannot_make_a_context_claim(self):
        row=dict(passed=True,scope='scripted_move_original_button',world=1,match='a'*32,rows=[{}, {}, {}],stop=dict(passed=True),
            native_confirmation=dict(continuation_frames=20),normal_serialization_only=True,originalCtor=False,
            binding=dict(ability=14,instant=True))
        rows=[row,dict(deepcopy(row),world=2,match='b'*32)]
        report=dict(mobile_original_hold_witness_passed=True,mobile_original_hold=dict(passed=True,evidence_schema=1,
            scope='scripted_move_original_button',originalCtor=False,physicalUI=False,selection_writes=0,history_writes=0,episodes=rows),
            mobile_correction=dict(episodes=[dict(world=x['world'],match=x['match'],mobile_original_hold=deepcopy(x),
                fresh=dict(order=dict(originalCtor=True,frame=180))) for x in rows]))
        self.assertTrue(controller.mobile_original_hold_gate(report));self.assertFalse(controller.mobile_context_hold_gate(report))
        report['mobile_context_move_witness_passed']=True
        self.assertFalse(controller.mobile_original_hold_gate(report))


if __name__=='__main__':unittest.main()
