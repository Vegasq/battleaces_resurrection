"""File-only explicit mobile-held preparation and final-gate controls."""
from copy import deepcopy
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from tests import test_prediction_mobile_controller as base_controller
from tools import verify_prediction_multiplayer as controller


class MobileHeldControllerTests(unittest.TestCase):
    def setUp(self):
        self.base=base_controller.MobilePreparationTests('test_mobile_prepare_is_explicit650_and_issues_no_game_process')
        self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.args=self.base.args;self.args.mobile_held_click=True

    def marker(self):
        f=self.base.fixture;helper=f.game/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+'-prediction-mobile-held-click-smoke'.encode('utf-16-le'))
        self.args.expected_helper_sha256=controller.sha(helper)
        for path in (f.game/'.battleaces-resurrection/patch-manifest.json',f.args.helper_build_receipt):
            row=json.loads(path.read_text());row['helper_sha256']=controller.sha(helper);path.write_text(json.dumps(row))

    def test_explicit_scope_requires_separate_installed_marker_without_any_process(self):
        with patch.object(controller.subprocess,'Popen',side_effect=AssertionError('Native forbidden')):
            with self.assertRaisesRegex(AssertionError,'helper lacks explicit'):controller.prepare(self.args)
            self.marker();plan=controller.prepare(self.args);controller.verify_prepared(self.args.output)
        self.assertTrue(plan['mobile_held_click']);self.assertTrue(plan['generic_movement_not_exercised'])
        for slot in (0,1):
            extra=controller.command_extra(plan,slot,self.args.output/'run')
            self.assertEqual(extra.count('-prediction-mobile-held-click-smoke'),1)
            self.assertIn('-prediction-mobile-correction-smoke',extra)
            self.assertNotIn('-prediction-movement-smoke',extra)
            self.assertFalse(any(flag in extra for flag in ('-prediction-held-click-smoke',
                '-prediction-mobile-group-intent-smoke','-prediction-mobile-ui-cast-smoke')))
        changed=deepcopy(plan);changed['mobile_held_click']=1
        (self.args.output/'invocation.json').write_text(json.dumps(changed))
        with self.assertRaisesRegex(AssertionError,'must be Boolean'):controller.verify_prepared(self.args.output)

    def test_every_other_fixture_and_wrong_mobile_scope_refuses_before_preparation(self):
        changes=[{key:True}for key in controller.MOBILE_HELD_EXCLUSIONS]
        changes += [dict(mobile_held_click=1),dict(scenario='movement'),dict(mobile_correction=False),
            dict(frames=600),dict(lifecycle='prefix'),dict(move_slot=1),dict(rtt_ms=[475,130]),
            dict(native_position_trace='11:1:1:130:260')]
        for change in changes:
            with self.subTest(change=change):
                args=deepcopy(self.args)
                for key,value in change.items():setattr(args,key,value)
                with self.assertRaises(AssertionError):controller.prepare(args)
                self.assertFalse(args.output.exists())

    def test_prepared_and_argv_scope_revalidation_reject_option_injection(self):
        self.marker();plan=controller.prepare(self.args)
        for change in (dict(mobile_ui_cast=True),dict(held_click=True),dict(actor_mirror=True),dict(mobile_held_click='true')):
            altered=dict(plan,**change)
            with self.subTest(change=change),self.assertRaises(AssertionError):
                controller.command_extra(altered,0,self.args.output/'run')

    def test_cli_parses_explicit_flag_only(self):
        seen=[];argv=['--scenario','mobile','--mobile-correction','--mobile-held-click']
        for name in ('game','assets','output','python','module-root','heap-helper','cooperative','helper-build-receipt'):
            argv+=['--'+name,'authored']
        argv+=['--expected-helper-sha256','1'*64,'--expected-gameassembly-sha256','2'*64]
        with (patch.object(controller,'prepare',side_effect=lambda args:seen.append(args)or dict(output='authored',scenario='mobile')),
                contextlib.redirect_stdout(io.StringIO())):
            controller.main(argv)
        self.assertTrue(seen[0].mobile_held_click);self.assertFalse(seen[0].held_click)
        self.assertFalse(seen[0].mobile_group_intent)


class MobileHeldFinalGateTests(unittest.TestCase):
    def fixture(self):
        f=base_controller.MobileStateFixture()
        f.plan.update(mobile_held_click=True,move_slot=0,rtt_ms=[130,475],native_position_trace=None)
        for i,ep in enumerate(f.report['mobile_correction']['episodes']):
            ep['mobile_held_click']=dict(passed=True,evidence_schema=3,world=ep['world'],match=ep['match'],balanced_original_input=True,
                release_while_absent=i==1,rows=[dict(source='authored held row')])
        f.report['mobile_held_click']=dict(passed=True,evidence_schema=3,natural_removal_empty_preview_held_accepted=False,
            selection_writes=0,history_writes=0,physicalUI=False,
            episodes=[deepcopy(ep['mobile_held_click'])for ep in f.report['mobile_correction']['episodes']])
        f.report['mobile_held_click_witness_passed']=True
        return f

    def test_both_bound_witnesses_required_in_addition_to_all_original_closed_state_gates(self):
        f=self.fixture();self.assertTrue(controller.mobile_final_gate(f.plan,f.finalize()))
        changes=('witness','missing_world','wrong_match','wrong_world','wrong_outcome','writes','row_binding','native_hash','force','old_schema','broad_claim')
        for change in changes:
            f=self.fixture();r=f.report
            if change=='witness':r['mobile_held_click_witness_passed']=False
            elif change=='missing_world':r['mobile_held_click']['episodes'].pop()
            elif change=='wrong_match':r['mobile_held_click']['episodes'][1]['match']='c'*32
            elif change=='wrong_world':r['mobile_held_click']['episodes'][1]['world']=999
            elif change=='wrong_outcome':r['mobile_held_click']['episodes'][1]['release_while_absent']=False
            elif change=='writes':r['mobile_held_click']['selection_writes']=1
            elif change=='row_binding':r['mobile_held_click']['episodes'][0]['rows']=[]
            elif change=='native_hash':f.workers[0][10]['parsed_state_sha256']='0'*64
            elif change=='old_schema':r['mobile_held_click']['evidence_schema']=1
            elif change=='broad_claim':r['mobile_held_click']['natural_removal_empty_preview_held_accepted']=True
            else:r['forced_cleanup']=True
            with self.subTest(change=change):
                if change=='force':f.finalize()
                else:
                    with self.assertRaises(AssertionError):f.finalize()
                self.assertFalse(controller.mobile_final_gate(f.plan,r))


if __name__=='__main__':unittest.main()
