"""Authored option/plan controls only; no Timeline getter, DLL, game or worker."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests import test_prediction_actor_mirror as mirror_tests
from tools import verify_prediction_multiplayer as verifier


class TerminalTimelinePlanTests(unittest.TestCase):
    def setUp(self):
        self.host=mirror_tests.MirrorVerifierTests();self.host.setUp();self.addCleanup(self.host.doCleanups)

    def enable(self,marker=True):
        args=self.host.enable();args.terminal_timeline=True
        if marker:
            helper=self.host.host.game/'BattleAcesOffline.dll'
            helper.write_bytes(helper.read_bytes()+'-prediction-terminal-timeline-smoke'.encode('utf-16-le'))
            args.expected_helper_sha256=verifier.sha(helper)
            for path in (self.host.host.game/'.battleaces-resurrection/patch-manifest.json',args.helper_build_receipt):
                value=json.loads(path.read_text());value['helper_sha256']=args.expected_helper_sha256;path.write_text(json.dumps(value))
        return args

    def test_explicit_preparation_pins_flag_and_sends_to_both_clients_without_execution(self):
        args=self.enable();before=self.host.host.snapshot_game()
        with patch.object(verifier.subprocess,'Popen',side_effect=AssertionError('must not spawn')):
            plan=verifier.prepare(args)
        self.assertIs(plan['terminal_timeline'],True)
        self.assertEqual(plan['rtt_ms'],[475,130]);self.assertEqual(plan['frames'],650)
        self.assertFalse(plan['full_feature_accepted'] or plan['native_executed'])
        self.assertEqual(verifier.verify_prepared(args.output),plan)
        self.assertEqual(before,self.host.host.snapshot_game())
        for index in (0,1):
            extra=verifier.command_extra(plan,index,args.output/'run')
            self.assertEqual(extra.count('-prediction-terminal-timeline-smoke'),1)
            self.assertIn('-prediction-held-click-smoke',extra);self.assertIn('-prediction-actor-mirror-smoke',extra)

    def test_absent_and_false_default_do_not_add_invocation_key_or_flag(self):
        args=self.host.enable();args.terminal_timeline=False
        plan=verifier.prepare(args)
        self.assertNotIn('terminal_timeline',plan)
        for index in (0,1):self.assertNotIn('-prediction-terminal-timeline-smoke',verifier.command_extra(plan,index,args.output/'run'))
        verifier.validate_terminal_timeline_plan({});verifier.validate_terminal_timeline_plan(dict(terminal_timeline=False))

    def test_missing_helper_marker_refuses_before_output(self):
        args=self.enable(False)
        with self.assertRaisesRegex(AssertionError,'helper lacks explicit -prediction-terminal-timeline-smoke'):
            verifier.prepare(args)
        self.assertFalse(args.output.exists())

    def test_prepare_rejects_nonboolean_option_before_writing(self):
        args=self.enable()
        for value in (1,0,'true',None,[],{}):
            args.terminal_timeline=value
            with self.subTest(value=value),self.assertRaisesRegex(AssertionError,'Boolean'):verifier.prepare(args)
            self.assertFalse(args.output.exists())

    def test_scope_reuses_exact_mirror_plan_without_widening_any_fixture(self):
        plan=dict(terminal_timeline=True,actor_mirror=True,held_click=True,actor_correction=True,
            scenario='movement',lifecycle='natural',frames=650,expected_matches=2,move_slot=0,rtt_ms=[475,130])
        verifier.validate_terminal_timeline_plan(plan)
        for key,value in (('actor_mirror',False),('held_click',False),('actor_correction',False),
                ('scenario','startup'),('lifecycle','prefix'),('frames',600),('expected_matches',1),
                ('rtt_ms',[130,475]),('move_slot',1),('expired_click',True),('mobile_correction',True),
                ('changing_rtt',True),('transition_orders',True)):
            changed=dict(plan);changed[key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):verifier.validate_terminal_timeline_plan(changed)

    def test_plain_prepare_cannot_enable_terminal_diagnostics_without_mirror_and_held(self):
        args=self.enable();args.actor_mirror=False;args.held_click=False;args.rtt_ms=(130,475)
        with self.assertRaisesRegex(AssertionError,'terminal timeline requires'):verifier.prepare(args)
        self.assertFalse(args.output.exists())

    def test_prepared_plan_tamper_and_command_path_refuse(self):
        args=self.enable();plan=verifier.prepare(args);path=args.output/'invocation.json'
        for key,value in (('terminal_timeline','true'),('terminal_timeline',1),('actor_mirror',False),
                ('held_click',False),('frames',600),('expected_matches',1)):
            changed=deepcopy(plan);changed[key]=value;path.write_text(json.dumps(changed))
            with self.subTest(key=key,value=value),self.assertRaises(AssertionError):verifier.verify_prepared(args.output)
            for index in (0,1):
                with self.subTest(key=key,index=index),self.assertRaises(AssertionError):
                    verifier.command_extra(changed,index,args.output/'run')

    def test_cli_flag_is_explicit_boolean_and_cannot_publish_acceptance(self):
        base=[];root=self.host.host.root
        for name in ('game','assets','output','python','module-root','heap-helper','cooperative','helper-build-receipt'):
            base+=['--'+name,str(root/name)]
        base+=['--expected-helper-sha256','a'*64,'--expected-gameassembly-sha256','b'*64]
        with patch.object(verifier,'prepare',return_value=dict(output='owned',scenario='movement')) as prepared,patch('builtins.print'):
            verifier.main(base+['--scenario','movement','--actor-correction','--held-click','--actor-mirror','--terminal-timeline'])
            self.assertIs(prepared.call_args[0][0].terminal_timeline,True)
            verifier.main(base);self.assertIs(prepared.call_args[0][0].terminal_timeline,False)
        args=self.enable();plan=verifier.prepare(args)
        self.assertFalse(verifier.held_click_final_gate(plan,dict(held_click_witness_passed=False)))


class UnityFatalLogTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.run=Path(self.temporary.name)

    def test_exact_marker_is_decisive_and_normal_text_remains_allowed(self):
        self.assertFalse(verifier.unity_fatal_seen(''))
        self.assertFalse(verifier.unity_fatal_seen('Registering exceptions\nNormal\nGAME CLIENT RESTART REQUIRED'))
        self.assertFalse(verifier.unity_fatal_seen(verifier.UNITY_FATAL_MARKER.lower()))
        self.assertTrue(verifier.unity_fatal_seen('before\n'+verifier.UNITY_FATAL_MARKER+'\nafter'))

    def test_absent_or_normal_owned_files_do_not_fail(self):
        for index in (0,1):
            verifier.check_owned_unity_log(self.run,index)
            (self.run/f'game-{index}.log').write_text('Original startup and normal log text')
            verifier.check_owned_unity_log(self.run,index)

    def test_each_client_checks_only_its_owned_unity_path(self):
        (self.run/'game-1.log').write_text(verifier.UNITY_FATAL_MARKER)
        (self.run/'native-0.log').write_text(verifier.UNITY_FATAL_MARKER)
        verifier.check_owned_unity_log(self.run,0)
        with self.assertRaisesRegex(AssertionError,'game-1.log.*Unity fatal marker'):
            verifier.check_owned_unity_log(self.run,1)
        (self.run/'game-0.log').write_text(verifier.UNITY_FATAL_MARKER)
        with self.assertRaisesRegex(AssertionError,'game-0.log.*Unity fatal marker'):
            verifier.check_owned_unity_log(self.run,0)

    def test_partial_utf8_and_unterminated_fatal_line_are_not_skipped(self):
        (self.run/'game-0.log').write_bytes(b'normal\xff\n'+verifier.UNITY_FATAL_MARKER.encode()+b'\xe2')
        with self.assertRaisesRegex(AssertionError,'Unity fatal marker'):
            verifier.check_owned_unity_log(self.run,0)

    def test_client_indices_cannot_select_another_path(self):
        for index in (-1,2,True,'0',None):
            with self.subTest(index=index),self.assertRaisesRegex(AssertionError,'client index'):
                verifier.check_owned_unity_log(self.run,index)


if __name__=='__main__':unittest.main()
