"""File-only close-formation controller handoff; no native game is launched."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_prediction_multiplayer_verifier as preparation
from tools import prediction_actor_fixture as actor_fixture
from tools import prediction_close_formation_fixture as close_fixture
from tools import verify_prediction_multiplayer as controller


CLOSE_FLAG = '-prediction-close-formation-smoke'
COHORT_FLAG = '-prediction-movement-observe-cohort='
COHORT_SPEC = '1:1:130:360:8'


class CloseFormationControllerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = preparation.PreparationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.args = self.fixture.args
        self.args.scenario = 'close-formation'
        self.helper = self.fixture.game / 'BattleAcesOffline.dll'
        self.helper_base = self.helper.read_bytes()
        self.markers(CLOSE_FLAG, COHORT_FLAG)
        no_native = patch.object(controller.subprocess, 'Popen', side_effect=AssertionError('Native forbidden'))
        self.addCleanup(no_native.stop)
        no_native.start()

    def markers(self, *flags):
        self.helper.write_bytes(self.helper_base + b''.join(flag.encode('utf-16-le') for flag in flags))
        self.args.expected_helper_sha256 = controller.sha(self.helper)
        for path in (self.fixture.game / '.battleaces-resurrection/patch-manifest.json',
                     self.args.helper_build_receipt):
            receipt = json.loads(path.read_text())
            receipt['helper_sha256'] = self.args.expected_helper_sha256
            path.write_text(json.dumps(receipt))

    def test_prepare_freezes_ordinary_fixture_and_two_round_contract_without_launch(self):
        before = self.fixture.snapshot_game()
        with patch.object(controller.subprocess, 'Popen', side_effect=AssertionError('Native forbidden')):
            plan = controller.prepare(self.args)
            self.assertEqual(controller.verify_prepared(self.args.output), plan)
        self.assertEqual(plan['scenario'], 'close-formation')
        self.assertIs(plan['close_formation'], True)
        self.assertEqual(plan['close_formation_fixture'], close_fixture.metadata())
        self.assertEqual(plan['native_cohort_spec'], COHORT_SPEC)
        self.assertIs(plan['generic_movement_not_exercised'], True)
        self.assertEqual((plan['lifecycle'], plan['frames'], plan['expected_matches'],
                          plan['move_slot'], plan['rtt_ms'], plan['surrender_frame']),
                         ('natural', 650, 2, 0, [130, 475], 700))
        self.assertIsNone(plan.get('actor_fixture'))
        self.assertFalse(plan.get('actor_correction'))
        self.assertFalse(plan.get('mobile_correction'))
        self.assertIs(plan['native_executed'], False)
        self.assertIs(plan['full_feature_accepted'], False)
        self.assertEqual(before, self.fixture.snapshot_game())

    def test_each_client_gets_only_its_close_handoff_and_guest_owns_cohort_trace(self):
        plan = controller.prepare(self.args)
        for slot in (0, 1):
            with self.subTest(slot=slot):
                flags = controller.command_extra(plan, slot, self.args.output / 'run')
                self.assertEqual(flags.count(CLOSE_FLAG), 1)
                self.assertEqual([flag for flag in flags if flag.startswith(COHORT_FLAG)],
                                 [COHORT_FLAG + COHORT_SPEC] if slot == 1 else [])
                self.assertEqual(flags.count('-frame-timing-worlds=2'), 1)
                self.assertIn('-dedicated-surrender-frame=700', flags)
                self.assertIn('-frame-timing-frames=650', flags)
                self.assertIn('-community-match-leave-quit-smoke', flags)
                self.assertIn('-native-quit-gate-smoke', flags)
                self.assertFalse(any(flag.startswith(('-prediction-mobile-', '-prediction-actor-',
                    '-prediction-cohort-', '-prediction-movement-smoke')) for flag in flags))

    def test_missing_smoke_or_observer_marker_refuses_before_output_creation(self):
        for absent in (CLOSE_FLAG, COHORT_FLAG):
            with self.subTest(absent=absent):
                self.markers(*(flag for flag in (CLOSE_FLAG, COHORT_FLAG) if flag != absent))
                with self.assertRaisesRegex(AssertionError, 'helper lacks'):
                    controller.prepare(self.args)
                self.assertFalse(self.args.output.exists())

    def test_prepare_rejects_changed_lifecycle_or_conflicting_fixture_before_writes(self):
        for changes in (dict(frames=600), dict(lifecycle='prefix'), dict(move_slot=1),
                        dict(rtt_ms=(475, 130)), dict(actor_correction=True), dict(mobile_correction=True)):
            args = deepcopy(self.args)
            for key, value in changes.items():
                setattr(args, key, value)
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                controller.prepare(args)
            self.assertFalse(args.output.exists())

    def test_prepared_file_and_command_handoff_both_refuse_missing_or_changed_close_inputs(self):
        plan = controller.prepare(self.args)
        altered = []
        for missing in ('close_formation', 'close_formation_fixture', 'native_cohort_spec',
                        'generic_movement_not_exercised'):
            value = deepcopy(plan)
            value.pop(missing)
            altered.append(('missing ' + missing, value))
        for key, value in (('close_formation', 1), ('expected_matches', 1),
                           ('native_cohort_spec', '1:1:130:220:8'), ('surrender_frame', 260),
                           ('scenario', 'startup'), ('mobile_correction', True)):
            altered.append((key, dict(plan, **{key: value})))
        changed_metadata = deepcopy(plan)
        changed_metadata['close_formation_fixture']['guest_ids'] = [11, 12]
        altered.append(('fixture members', changed_metadata))
        invocation = self.args.output / 'invocation.json'
        for label, changed in altered:
            with self.subTest(change=label):
                for slot in (0, 1):
                    with self.assertRaises(AssertionError):
                        controller.command_extra(changed, slot, self.args.output / 'run')
                invocation.write_text(json.dumps(changed))
                with self.assertRaises(AssertionError):
                    controller.verify_prepared(self.args.output)
        invocation.write_text(json.dumps(plan))
        self.assertEqual(controller.verify_prepared(self.args.output), plan)

    def test_cli_selects_close_scenario_without_turning_on_other_fixture_flags(self):
        argv = ['--scenario', 'close-formation']
        for name in ('game', 'assets', 'output', 'python', 'module-root', 'heap-helper',
                     'cooperative', 'helper-build-receipt'):
            argv += ['--' + name, 'authored']
        argv += ['--expected-helper-sha256', '1' * 64, '--expected-gameassembly-sha256', '2' * 64]
        with (patch.object(controller, 'prepare', return_value=dict(output='authored', scenario='close-formation')) as prepare,
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(controller.main(argv), 0)
        args = prepare.call_args.args[0]
        self.assertEqual(args.scenario, 'close-formation')
        self.assertEqual((args.lifecycle, args.frames, args.move_slot, tuple(args.rtt_ms)),
                         ('natural', None, 0, (130, 475)))
        self.assertFalse(any(getattr(args, flag, False) for flag in ('actor_correction',
            'mobile_correction', 'cohort_survivor', 'multi_unit_move', 'changing_rtt', 'transition_orders')))

    def test_existing_startup_argv_and_movement_roles_are_preserved(self):
        self.args.scenario = 'startup'
        plan = controller.prepare(self.args)
        run = self.args.output / 'run'
        for slot, role in enumerate(('host', 'guest')):
            expected = [f'-community-match-{role}-smoke', '-lan-smoke', '-dedicated-surrender-smoke',
                '-dedicated-surrender-frame=260', '-prediction-movement-experimental', '-frame-timing',
                '-frame-timing-frames=200', '-lan-audit',
                '-prediction-worker-python=' + plan['files']['python']['path'],
                '-prediction-worker-module-root=' + plan['worker_module_root'],
                '-prediction-worker-heap-helper=' + plan['files']['heap_helper']['path'],
                '-prediction-worker-cooperative=' + plan['files']['cooperative']['path'],
                '-prediction-worker-data-dir=' + str(run / f'worker-data-{slot}'),
                '-native-quit-smoke', '-native-quit-mode=confirm', '-native-quit-gate-smoke',
                '-community-match-leave-quit-smoke']
            self.assertEqual(controller.command_extra(plan, slot, run), expected)
        self.assertFalse(plan.get('close_formation'))
        self.assertIsNone(plan.get('close_formation_fixture'))
        self.assertNotIn('native_cohort_spec', plan)
        self.args.scenario = 'movement'
        self.args.move_slot = 1
        self.args.output = self.fixture.root / 'local/ordinary-movement'
        movement = controller.prepare(self.args)
        for slot in (0, 1):
            flags = controller.command_extra(movement, slot, run)
            self.assertIn('-prediction-movement-smoke-slot=' + str(slot), flags)
            self.assertIn('-prediction-movement-smoke-start-frame=' + str(440 if slot == 1 else 460), flags)
            self.assertNotIn(CLOSE_FLAG, flags)
            self.assertFalse(any(flag.startswith(COHORT_FLAG) for flag in flags))


class CloseFormationTemplateRoutingTests(unittest.TestCase):
    def test_close_native_failure_is_rejected_before_other_log_claims(self):
        with self.assertRaisesRegex(AssertionError, 'native movement/lifecycle failure'):
            controller.native_evidence('Close formation smoke failed: reason=authored failure',
                matches=[], slot=1, profile='authored', natural=False)

    def test_explicit_close_routes_only_ordinary_close_template_and_defaults_stay_unchanged(self):
        base, product, actor = object(), object(), object()
        assets = Path('authored-assets')
        with (patch.object(close_fixture, 'make_template', return_value=product) as make_close,
              patch.object(actor_fixture, 'make_template', return_value=actor) as make_actor):
            self.assertIs(controller.match_template(base, assets, actor_correction=False,
                                                   close_formation=True), product)
            make_close.assert_called_once_with(base, assets)
            make_actor.assert_not_called()
            self.assertIs(controller.match_template(base, assets, actor_correction=False), base)
            self.assertIs(controller.match_template(base, assets, actor_correction=False,
                                                   close_formation=False), base)
            self.assertIs(controller.match_template(base, assets, actor_correction=True), actor)
            make_actor.assert_called_once_with(base, assets)
            self.assertEqual(make_close.call_count, 1)

    def test_mixed_templates_refuse_before_any_close_transformation(self):
        for changed in (dict(actor_correction=True), dict(mobile_correction=True),
                        dict(actor_mirror=True), dict(cohort_survivor=True)):
            options = dict(dict(actor_correction=False, close_formation=True), **changed)
            with self.subTest(changed=changed), patch.object(close_fixture, 'make_template') as make:
                with self.assertRaises(AssertionError):
                    controller.match_template(object(), Path('authored-assets'), **options)
                make.assert_not_called()


if __name__ == '__main__':
    unittest.main()
