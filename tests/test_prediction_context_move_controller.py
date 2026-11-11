"""File-only explicit context Move preparation; no native process is launched."""
from copy import deepcopy
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from tests import test_prediction_mobile_controller as base_controller
from tools import verify_prediction_multiplayer as controller


class ContextMovePreparationTests(unittest.TestCase):
    def setUp(self):
        self.base = base_controller.MobilePreparationTests('test_mobile_prepare_is_explicit650_and_issues_no_game_process')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.args = self.base.args
        self.args.mobile_context_move = True

    def marker(self):
        fixture = self.base.fixture
        helper = fixture.game / 'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes() + '-prediction-mobile-context-move-smoke'.encode('utf-16-le'))
        self.args.expected_helper_sha256 = controller.sha(helper)
        for path in (fixture.game / '.battleaces-resurrection/patch-manifest.json', fixture.args.helper_build_receipt):
            row = json.loads(path.read_text())
            row['helper_sha256'] = controller.sha(helper)
            path.write_text(json.dumps(row))

    def test_marker_scope_and_both_argv_require_explicit_context_option(self):
        with patch.object(controller.subprocess, 'Popen', side_effect=AssertionError('Native forbidden')):
            with self.assertRaisesRegex(AssertionError, 'helper lacks explicit'):
                controller.prepare(self.args)
            self.assertFalse(self.args.output.exists())
            self.marker()
            plan = controller.prepare(self.args)
            controller.verify_prepared(self.args.output)
        self.assertTrue(plan['mobile_context_move'])
        self.assertTrue(plan['generic_movement_not_exercised'])
        self.assertFalse(plan['native_executed'])
        self.assertFalse(plan['full_feature_accepted'])
        for slot in (0, 1):
            flags = controller.command_extra(plan, slot, self.args.output / 'run')
            self.assertEqual(flags.count('-prediction-mobile-context-move-smoke'), 1)
            self.assertIn('-prediction-mobile-correction-smoke', flags)
            self.assertNotIn('-prediction-movement-smoke', flags)
            self.assertNotIn('-prediction-mobile-held-click-smoke', flags)
            self.assertNotIn('-prediction-held-click-smoke', flags)
            self.assertNotIn('-prediction-mobile-group-intent-smoke', flags)

    def test_all_other_modes_and_wrong_scope_refuse_before_output_creation(self):
        changes = [{key: True} for key in controller.MOBILE_CONTEXT_EXCLUSIONS]
        changes += [dict(mobile_context_move=1), dict(scenario='movement'), dict(mobile_correction=False),
                    dict(frames=600), dict(lifecycle='prefix'), dict(move_slot=1), dict(rtt_ms=[475, 130]),
                    dict(native_position_trace='11:1:1:130:260')]
        for change in changes:
            with self.subTest(change=change):
                args = deepcopy(self.args)
                for key, value in change.items():
                    setattr(args, key, value)
                with self.assertRaises(AssertionError):
                    controller.prepare(args)
                self.assertFalse(args.output.exists())

    def test_prepared_plan_and_argv_revalidate_typed_exclusive_options(self):
        self.marker()
        plan = controller.prepare(self.args)
        changes = [{key: True} for key in controller.MOBILE_CONTEXT_EXCLUSIONS]
        changes += [dict(mobile_context_move='true'), dict(expected_matches=1), dict(frames=True),
                    dict(move_slot=False), dict(mobile_correction=False), dict(native_position_trace='11:1:1:130:260')]
        for change in changes:
            altered = dict(plan, **change)
            with self.subTest(change=change):
                with self.assertRaises(AssertionError):
                    controller.command_extra(altered, 0, self.args.output / 'run')
                (self.args.output / 'invocation.json').write_text(json.dumps(altered))
                with self.assertRaises(AssertionError):
                    controller.verify_prepared(self.args.output)

    def test_cli_context_flag_does_not_enable_any_other_fixture(self):
        seen = []
        argv = ['--scenario', 'mobile', '--mobile-correction', '--mobile-context-move']
        for name in ('game', 'assets', 'output', 'python', 'module-root', 'heap-helper', 'cooperative', 'helper-build-receipt'):
            argv += ['--' + name, 'authored']
        argv += ['--expected-helper-sha256', '1' * 64, '--expected-gameassembly-sha256', '2' * 64]
        with (patch.object(controller, 'prepare', side_effect=lambda args: seen.append(args) or dict(output='authored', scenario='mobile')),
              contextlib.redirect_stdout(io.StringIO())):
            controller.main(argv)
        self.assertTrue(seen[0].mobile_context_move)
        self.assertTrue(seen[0].mobile_correction)
        self.assertTrue(all(not getattr(seen[0], key, False) for key in controller.MOBILE_CONTEXT_EXCLUSIONS))

    def test_new_mode_remains_absent_from_ordinary_mobile_defaults(self):
        self.args.mobile_context_move = False
        plan = controller.prepare(self.args)
        self.assertNotIn('mobile_context_move', plan)
        for slot in (0, 1):
            self.assertNotIn('-prediction-mobile-context-move-smoke',
                             controller.command_extra(plan, slot, self.args.output / 'run'))


if __name__ == '__main__':
    unittest.main()
