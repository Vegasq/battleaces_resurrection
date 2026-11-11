"""File-only queued-orders controller handoff; native execution is forbidden."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_prediction_close_formation_controller as close_tests
from tools import prediction_close_formation_fixture as fixture
from tools import verify_prediction_multiplayer as controller


FLAG = '-prediction-queued-orders-smoke'
MARKER = b'BA_RESURRECTION_PREDICTION_QUEUED_ORDERS_V1'
OBSERVER = '-prediction-movement-observe-cohort='
SPEC = '1:1:280:420:8'


class QueuedOrdersControllerTests(unittest.TestCase):
    def setUp(self):
        # Reuse the isolated source/assets/receipt fixture and its cleanup-safe
        # refusal of subprocess.Popen. This class does not inherit its tests.
        self.preparation = close_tests.CloseFormationControllerTests()
        self.preparation.setUp()
        self.addCleanup(self.preparation.doCleanups)
        self.args = self.preparation.args
        self.args.scenario = 'queued-orders'
        self.runtime_capabilities()

    def runtime_capabilities(self, *, marker=True, smoke=True, observer=True):
        data = self.preparation.helper_base + (MARKER if marker else b'')
        data += b''.join(flag.encode('utf-16-le') for enabled, flag in
                         ((smoke, FLAG), (observer, OBSERVER)) if enabled)
        self.preparation.helper.write_bytes(data)
        self.args.expected_helper_sha256 = controller.sha(self.preparation.helper)
        for path in (self.preparation.fixture.game / '.battleaces-resurrection/patch-manifest.json',
                     self.args.helper_build_receipt):
            receipt = json.loads(path.read_text())
            receipt['helper_sha256'] = self.args.expected_helper_sha256
            path.write_text(json.dumps(receipt))

    def test_prepare_and_verify_freeze_distinct_queued_contract(self):
        self.args.rtt_ms = (130.0, 475.0)
        before = self.preparation.fixture.snapshot_game()
        plan = controller.prepare(self.args)
        self.assertEqual(controller.verify_prepared(self.args.output), plan)
        self.assertEqual(plan['scenario'], 'queued-orders')
        self.assertIs(plan['queued_orders'], True)
        self.assertEqual(plan['queued_orders_fixture'], fixture.metadata())
        self.assertEqual(plan['queued_orders_scope'], controller.queued_orders_evidence.scope(plan))
        self.assertTrue(plan['queued_orders_scope'])
        self.assertEqual(plan['native_cohort_spec'], SPEC)
        self.assertEqual((plan['frames'], plan['expected_matches'], plan['lifecycle'],
                          plan['surrender_frame'], plan['move_slot'], plan['rtt_ms']),
                         (650, 2, 'natural', 700, 0, [130.0, 475.0]))
        self.assertIs(plan['generic_movement_not_exercised'], True)
        self.assertIs(plan['native_executed'], False)
        self.assertIs(plan['full_feature_accepted'], False)
        self.assertFalse(plan.get('close_formation'))
        self.assertIsNone(plan.get('actor_fixture'))
        self.assertEqual(before, self.preparation.fixture.snapshot_game())

    def test_both_clients_use_queued_smoke_but_only_guest_observes_extended_window(self):
        plan = controller.prepare(self.args)
        for slot, role in enumerate(('host', 'guest')):
            with self.subTest(slot=slot):
                flags = controller.command_extra(plan, slot, self.args.output / 'run')
                self.assertEqual(flags.count(FLAG), 1)
                self.assertIn('-community-match-' + role + '-smoke', flags)
                self.assertEqual([flag for flag in flags if flag.startswith(OBSERVER)],
                                 [OBSERVER + SPEC] if slot else [])
                self.assertEqual(flags.count('-frame-timing-worlds=2'), 1)
                for expected in ('-frame-timing-frames=650', '-dedicated-surrender-frame=700',
                                 '-native-quit-gate-smoke', '-community-match-leave-quit-smoke'):
                    self.assertIn(expected, flags)
                self.assertFalse(any(flag.startswith(('-prediction-close-formation-',
                    '-prediction-mobile-', '-prediction-actor-', '-prediction-cohort-',
                    '-prediction-movement-smoke')) for flag in flags))

    def test_missing_producer_schema_flag_or_cohort_forwarder_refuses_preparation(self):
        for missing in ('marker', 'smoke', 'observer'):
            with self.subTest(missing=missing):
                self.runtime_capabilities(**{missing: False})
                with self.assertRaises(AssertionError):
                    controller.prepare(self.args)
                self.assertFalse(self.args.output.exists())

    def test_prepared_contract_tampering_refuses_both_verification_and_argv(self):
        plan = controller.prepare(self.args)
        changes = [dict(queued_orders=False), dict(scenario='close-formation'),
                   dict(native_cohort_spec=close_tests.COHORT_SPEC),
                   dict(queued_orders_scope='unbound scope'), dict(surrender_frame=699),
                   dict(close_formation=True), dict(actor_correction=True),
                   dict(queued_orders_fixture=dict(fixture.metadata(), unit_type=2))]
        incomplete = deepcopy(plan)
        del incomplete['queued_orders']
        variants = [incomplete] + [dict(deepcopy(plan), **changed) for changed in changes]
        path = self.args.output / 'invocation.json'
        for variant in variants:
            with self.subTest(variant={k: v for k, v in variant.items() if plan.get(k) != v}):
                path.write_text(json.dumps(variant))
                with self.assertRaises(AssertionError):
                    controller.verify_prepared(self.args.output)
                for slot in (0, 1):
                    with self.assertRaises(AssertionError):
                        controller.command_extra(variant, slot, self.args.output / 'run')
        path.write_text(json.dumps(plan))
        self.assertEqual(controller.verify_prepared(self.args.output), plan)

    def test_incompatible_prepare_options_refuse_before_creating_output(self):
        for changed in (dict(actor_correction=True), dict(mobile_correction=True),
                        dict(frames=600), dict(lifecycle='prefix')):
            args = deepcopy(self.args)
            vars(args).update(changed)
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                controller.prepare(args)
            self.assertFalse(self.args.output.exists())

    def test_cli_accepts_named_scenario_and_real_float_rtts_without_other_modes(self):
        argv = ['--scenario', 'queued-orders', '--rtt-ms', '130', '475']
        for name in ('game', 'assets', 'output', 'python', 'module-root', 'heap-helper',
                     'cooperative', 'helper-build-receipt'):
            argv += ['--' + name, 'authored']
        argv += ['--expected-helper-sha256', '1' * 64, '--expected-gameassembly-sha256', '2' * 64]
        with (patch.object(controller, 'prepare', return_value=dict(output='authored', scenario='queued-orders')) as prepare,
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(controller.main(argv), 0)
        args = prepare.call_args.args[0]
        self.assertEqual(args.scenario, 'queued-orders')
        self.assertEqual(args.rtt_ms, [130.0, 475.0])
        self.assertTrue(all(type(value) is float for value in args.rtt_ms))
        self.assertFalse(any(getattr(args, name, False) for name in
            ('actor_correction', 'mobile_correction', 'multi_unit_move', 'cohort_survivor',
             'changing_rtt', 'transition_orders')))

    def test_existing_close_and_startup_do_not_inherit_queued_handoff(self):
        self.preparation.markers(close_tests.CLOSE_FLAG, OBSERVER)
        for scenario in ('close-formation', 'startup'):
            self.args.scenario = scenario
            self.args.output = self.preparation.fixture.root / 'local' / scenario
            plan = controller.prepare(self.args)
            self.assertFalse(plan.get('queued_orders'))
            self.assertIsNone(plan.get('queued_orders_fixture'))
            for slot in (0, 1):
                flags = controller.command_extra(plan, slot, self.args.output / 'run')
                self.assertNotIn(FLAG, flags)
                if scenario == 'close-formation':
                    self.assertIn(close_tests.CLOSE_FLAG, flags)
                    self.assertEqual([f for f in flags if f.startswith(OBSERVER)],
                                     [OBSERVER + close_tests.COHORT_SPEC] if slot else [])
                else:
                    self.assertEqual((plan['frames'], plan['surrender_frame']), (200, 260))
                    self.assertFalse(any(f.startswith(OBSERVER) for f in flags))


class QueuedOrdersTemplateTests(unittest.TestCase):
    def test_queued_runtime_failure_is_rejected_before_other_log_claims(self):
        with self.assertRaisesRegex(AssertionError, 'native movement/lifecycle failure'):
            controller.native_evidence('Queued orders smoke failed: reason=authored failure',
                matches=[], slot=1, profile='authored', natural=False)

    def test_queued_and_close_route_to_same_ordinary_fixture_with_inert_default(self):
        base, transformed = object(), object()
        assets = Path('authored-assets')
        with patch.object(fixture, 'make_template', return_value=transformed) as make:
            self.assertIs(controller.match_template(base, assets, actor_correction=False,
                                                   queued_orders=True), transformed)
            self.assertIs(controller.match_template(base, assets, actor_correction=False,
                                                   close_formation=True), transformed)
            self.assertEqual(make.call_count, 2)
            self.assertEqual(make.call_args_list, [unittest.mock.call(base, assets)] * 2)
            self.assertIs(controller.match_template(base, assets, actor_correction=False), base)
            self.assertIs(controller.match_template(base, assets, actor_correction=False,
                                                   queued_orders=False), base)
            self.assertEqual(make.call_count, 2)

    def test_mixed_or_nonboolean_template_selection_refuses_before_transformation(self):
        for changed in (dict(close_formation=True), dict(actor_correction=True),
                        dict(mobile_correction=True), dict(actor_mirror=True),
                        dict(cohort_survivor=True), dict(queued_orders=1)):
            options = dict(dict(actor_correction=False, queued_orders=True), **changed)
            with self.subTest(changed=changed), patch.object(fixture, 'make_template') as make:
                with self.assertRaises(AssertionError):
                    controller.match_template(object(), Path('authored-assets'), **options)
                make.assert_not_called()


if __name__ == '__main__':
    unittest.main()
