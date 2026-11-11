"""Pure preparation and synthetic-controller handoff for the input-delay probe."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests import test_prediction_multiplayer_verifier as existing
from tools import prediction_input_delay as evidence
from tools import verify_prediction_multiplayer as controller


SETTINGS = dict(direction='client_to_server', extra_ms=100, duration_ms=250)
TRACE = '74:1:0:400:650'


class InputDelayPreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = existing.PreparationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.args = self.fixture.args
        self.args.scenario = 'movement'
        self.args.changing_rtt = self.args.transition_orders = True
        self.args.native_position_trace = TRACE
        self.args.transition_input_delay_ms = 100
        self.args.rtt_ms = (130.0, 475.0)
        forbidden = patch.object(controller.subprocess, 'Popen', side_effect=AssertionError('Native forbidden'))
        self.addCleanup(forbidden.stop)
        forbidden.start()

    def test_prepare_freezes_exact_traced_delay_and_verifies_without_launch(self):
        before = self.fixture.snapshot_game()
        plan = controller.prepare(self.args)
        self.assertEqual(controller.verify_prepared(self.args.output), plan)
        self.assertEqual(plan['transition_input_delay'], SETTINGS)
        self.assertEqual((plan['scenario'], plan['lifecycle'], plan['frames'],
                          plan['expected_matches'], plan['move_slot'], plan['rtt_ms']),
                         ('movement', 'natural', 650, 2, 0, [130.0, 475.0]))
        self.assertEqual(plan['native_position_trace'], TRACE)
        self.assertEqual((plan['transition_phase_source'], plan['changing_pose_clock'],
                          plan['publication_source']), ('decision', 'sampled_us', 'post-original-qpc'))
        self.assertIs(plan['native_executed'], False)
        self.assertIs(plan['full_feature_accepted'], False)
        self.assertEqual(before, self.fixture.snapshot_game())
        ordinary = deepcopy(plan)
        del ordinary['transition_input_delay']
        for slot in (0, 1):
            # This option changes the controller-owned relay, not client argv.
            self.assertEqual(controller.command_extra(plan, slot, self.args.output / 'run'),
                             controller.command_extra(ordinary, slot, self.args.output / 'run'))

    def test_wrong_delay_or_route_refuses_before_output_creation(self):
        for changed in (dict(transition_input_delay_ms=99), dict(transition_input_delay_ms=True),
                        dict(transition_input_delay_ms='100'), dict(scenario='startup'),
                        dict(lifecycle='prefix'), dict(frames=600), dict(move_slot=1),
                        dict(changing_rtt=False), dict(transition_orders=False),
                        dict(native_position_trace='12:75:0:400:650'),
                        dict(rtt_ms=(475, 130)), dict(actor_correction=True)):
            args = deepcopy(self.args)
            vars(args).update(changed)
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                controller.prepare(args)
            self.assertFalse(self.args.output.exists())

    def test_prepared_delay_and_measurement_contract_mutations_refuse_verification(self):
        plan = controller.prepare(self.args)
        changes = [dict(transition_input_delay=None),
                   dict(transition_input_delay=dict(SETTINGS, direction='server_to_client')),
                   dict(transition_input_delay=dict(SETTINGS, extra_ms=101)),
                   dict(transition_input_delay=dict(SETTINGS, duration_ms=250.0)),
                   dict(transition_input_delay=dict(SETTINGS, unexpected=True)),
                   dict(native_position_trace='74:1:0:400:640'),
                   dict(transition_phase_source='pacer_wait'), dict(changing_pose_clock=None),
                   dict(publication_source=None), dict(expected_matches=1),
                   dict(transition_orders=False), dict(queued_orders=True)]
        path = self.args.output / 'invocation.json'
        for changed in changes:
            with self.subTest(changed=changed):
                path.write_text(json.dumps(dict(deepcopy(plan), **changed)))
                with self.assertRaises(AssertionError):
                    controller.verify_prepared(self.args.output)
        path.write_text(json.dumps(plan))
        self.assertEqual(controller.verify_prepared(self.args.output), plan)

    def test_option_absent_preserves_traced_movement_and_startup_plans(self):
        del self.args.transition_input_delay_ms
        traced = controller.prepare(self.args)
        self.assertNotIn('transition_input_delay', traced)
        self.assertEqual(traced['native_position_trace'], TRACE)
        self.args.output = self.fixture.root / 'local/startup'
        self.args.scenario = 'startup'
        self.args.changing_rtt = self.args.transition_orders = False
        self.args.native_position_trace = None
        startup = controller.prepare(self.args)
        self.assertNotIn('transition_input_delay', startup)
        self.assertEqual((startup['frames'], startup['surrender_frame']), (200, 260))

    def test_cli_parses_explicit_integer_and_defaults_to_no_delay(self):
        argv = []
        for name in ('game', 'assets', 'output', 'python', 'module-root', 'heap-helper',
                     'cooperative', 'helper-build-receipt'):
            argv += ['--' + name, 'authored']
        argv += ['--expected-helper-sha256', '1' * 64, '--expected-gameassembly-sha256', '2' * 64]
        with (patch.object(controller, 'prepare', return_value=dict(output='authored', scenario='movement')) as prepare,
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(controller.main(argv + ['--scenario', 'movement', '--changing-rtt',
                '--transition-orders', '--native-position-trace', TRACE, '--transition-input-delay-ms', '100']), 0)
            parsed = prepare.call_args.args[0]
            self.assertEqual(parsed.transition_input_delay_ms, 100)
            self.assertIs(type(parsed.transition_input_delay_ms), int)
            self.assertEqual(parsed.native_position_trace, TRACE)
            self.assertTrue(parsed.changing_rtt and parsed.transition_orders)
            self.assertEqual(controller.main(argv), 0)
            self.assertIsNone(prepare.call_args.args[0].transition_input_delay_ms)


class InputDelayOrderingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve()
        self.events = []
        self.fixture = existing.ChangingRttControllerTests()
        self.fixture.setUp()
        self.fixture.relay.changes.clear()
        old_setter = self.fixture.relay.set_rtt_ms

        def set_rtt(value, *, tick):
            self.events.append(('rtt', value))
            return old_setter(value, tick=tick)

        def set_delay(direction, extra_ms, duration_ms, *, tick):
            self.events.append(('delay', direction, extra_ms, duration_ms))
            return dict(window_id=1, direction=direction, extra_ms=float(extra_ms),
                        duration_ms=float(duration_ms), effective_tick_ms=tick(),
                        effective_perf_counter_ns=self.fixture.clock * 1_000_000)

        self.fixture.relay.set_rtt_ms = set_rtt
        self.fixture.relay.set_directional_delay = Mock(side_effect=set_delay)
        publish = controller.publish_transition_gate

        def gate(directory, command, ordinal, tick, perf):
            self.events.append(('gate', ordinal))
            return publish(directory, command, ordinal, tick, perf)

        patched = patch.object(controller, 'publish_transition_gate', side_effect=gate)
        self.addCleanup(patched.stop)
        patched.start()

    def begin(self, settings=SETTINGS):
        f = self.fixture
        f.control = controller.ChangingRttController(lambda: f.clock, lambda: f.clock * 1_000_000,
            require_sampled_us=True, transition_gates=self.folder, phase_source='decision',
            directional_delay=deepcopy(settings))
        f.control.begin(f.match, f.relay)
        return f

    def update(self, tick):
        for row in self.fixture.rows:
            if row['event'] == 'transform':
                row['sampled_us'] = row['tick_ms'] * 1000
        self.fixture.update(tick)

    def test_delay_is_armed_once_after_actual_fall_setter_before_turn2_file(self):
        f = self.begin()
        self.update(1700)
        f.fall_ready()
        self.update(5699)
        f.relay.set_directional_delay.assert_not_called()
        self.assertFalse(list(self.folder.iterdir()))
        self.update(5700)
        self.assertEqual(self.events, [('rtt', 130), ('rtt', 475), ('rtt', 130),
                                      ('delay', 'client_to_server', 100, 250), ('gate', 2)])
        call = f.relay.set_directional_delay.call_args
        self.assertEqual({k: v for k, v in call.kwargs.items() if k != 'tick'}, SETTINGS)
        self.assertEqual(call.kwargs['tick'](), 5700)
        state = f.control.worlds[-1]
        self.assertEqual(state['input_delay']['effective_tick_ms'], 5700)
        self.assertGreaterEqual(state['turn2_gate']['requested_perf_counter_ns'],
                                state['input_delay']['effective_perf_counter_ns'])
        self.assertEqual(Path(state['turn2_gate']['path']).read_text(),
                         'BA_MOVEMENT_TURN_V1 ' + f.match + ' 7 91 1 1 2\n')
        self.update(5800)
        f.relay.set_directional_delay.assert_called_once()
        self.assertEqual(len(list(self.folder.iterdir())), 1)
        snapshot = f.control.snapshot()
        self.assertEqual(snapshot['transition_input_delay'], SETTINGS)
        snapshot['transition_input_delay']['extra_ms'] = 999
        self.assertEqual(f.control.snapshot()['transition_input_delay'], SETTINGS)

    def test_delay_failure_cannot_publish_the_turn2_gate(self):
        f = self.begin()
        f.relay.set_directional_delay.side_effect = ValueError('authored directional refusal')
        self.update(1700)
        f.fall_ready()
        with self.assertRaisesRegex(ValueError, 'authored directional refusal'):
            self.update(5700)
        self.assertEqual(f.relay.changes, [130, 475, 130])
        self.assertNotIn('turn2_gate', f.control.worlds[-1])
        self.assertFalse(list(self.folder.iterdir()))

    def test_missing_acquisition_never_arms_delay_or_creates_gate(self):
        f = self.begin()
        self.update(1700)
        f.fall_ready()
        f.rtt = f.sample(1, 1800)
        self.update(5700)
        self.update(7701)
        self.assertEqual(f.control.worlds[-1]['stage'], 'failed')
        f.relay.set_directional_delay.assert_not_called()
        self.assertFalse(list(self.folder.iterdir()))

    def test_no_delay_preserves_existing_setter_order_and_snapshot_shape(self):
        f = self.begin(None)
        self.update(1700)
        f.fall_ready()
        self.update(5700)
        self.assertEqual(self.events, [('rtt', 130), ('rtt', 475), ('rtt', 130), ('gate', 2)])
        f.relay.set_directional_delay.assert_not_called()
        self.assertNotIn('input_delay', f.control.worlds[-1])
        self.assertEqual(set(f.control.snapshot()),
                         {'schema', 'worlds', 'require_sampled_us', 'phase_source', 'transition_orders', 'scope'})

    def test_controller_rejects_delay_without_gate_or_with_changed_settings(self):
        with self.assertRaisesRegex(AssertionError, 'transition gates'):
            controller.ChangingRttController(lambda: 0, directional_delay=deepcopy(SETTINGS))
        for settings in (dict(SETTINGS, direction='server_to_client'),
                         dict(SETTINGS, duration_ms=True), dict(SETTINGS, extra_ms=99)):
            with self.subTest(settings=settings), self.assertRaises(AssertionError):
                controller.ChangingRttController(lambda: 0, transition_gates=self.folder,
                                                 directional_delay=settings)
        self.fixture.relay.set_directional_delay.assert_not_called()


class InputDelaySchedulingEvidenceTests(unittest.TestCase):
    def fixture(self):
        plan = dict(scenario='movement', lifecycle='natural', frames=650, expected_matches=2,
            move_slot=0, rtt_ms=[130.0, 475.0], changing_rtt=True, transition_orders=True,
            native_position_trace=TRACE, transition_phase_source='decision',
            changing_pose_clock='sampled_us', publication_source='post-original-qpc',
            transition_input_delay=deepcopy(SETTINGS))
        report = dict(changing_rtt_control=dict(transition_input_delay=deepcopy(SETTINGS), worlds=[]),
            transition_orders=dict(passed=True, episodes=[]), native_position_trace=dict(passed=True),
            changing_rtt_smoothness_passed=True)
        metadata = dict(directional_delays=[], directions={})
        for index, start in enumerate((10, 20), 1):
            window = dict(window_id=index, direction='client_to_server', extra_ms=100.0, duration_ms=250.0,
                requested_tick_ms=start * 1000, effective_tick_ms=start * 1000,
                requested_perf_counter_ns=start * 10**9, effective_perf_counter_ns=start * 10**9 + 1000,
                start_loop=float(start), end_loop=start + .250)
            metadata['directional_delays'].append(window)
            match = ('a' if index == 1 else 'b') * 32
            report['changing_rtt_control']['worlds'].append(dict(match=match, world=index, stage='complete',
                input_delay=window, fall=dict(effective_perf_counter_ns=start * 10**9 - 1_000_000),
                turn2_gate=dict(requested_perf_counter_ns=start * 10**9 + 2_000_000,
                                published_perf_counter_ns=start * 10**9 + 3_000_000)))
            order = dict(sequence=3, action_sha256=('c' if index == 1 else 'd') * 64,
                assigned_frame=531, canonical_frame=532, native67_tick_ms=start * 1000 + 21,
                native72_send_tick_ms=start * 1000 + 22,
                original_order=dict(ordinal=2, world=index, match=match,
                                    enqueue_sampled_us=start * 1_000_000 + 20_000))
            report['transition_orders']['episodes'].append(dict(match=match, orders=[order]))
        # Explicit expected deadlines: an old high-RTT chunk leaves base debt;
        # two subsequent reads share that base and each receives only100ms.
        # A later delayed chunk leaves final-deadline debt after expiry; only
        # the final read has recovered to its ordinary base deadline.
        schedule = [(9.90, 475, 10.1375, 10.1375, None),
                    (10.01, 130, 10.1375, 10.2375, 1),
                    (10.03, 130, 10.1375, 10.2375, 1),
                    (10.24, 130, 10.3050, 10.4050, 1),
                    (10.26, 130, 10.3250, 10.4050, None),
                    (10.40, 130, 10.4650, 10.4650, None)]
        for direction in ('client_to_server', 'server_to_client'):
            rows = []
            for offset in (0, 10):
                for received, rtt, base, final, window_id in schedule:
                    due = (final if direction == 'client_to_server' else base) + offset
                    row = dict(connection=1, chunk=len(rows) + 1, revision=2,
                        configured_rtt_ms=rtt, received_loop=received + offset, due_loop=due,
                        byte_count=64, forwarded_loop=due + .001, drained_loop=due + .002,
                        held_ms=(due + .001 - received - offset) * 1000)
                    if direction == 'client_to_server' and rows:
                        row.update(base_due_loop=base + offset, final_due_loop=due,
                            directional_extra_ms=100.0 if window_id else 0.0,
                            directional_window_id=(window_id + offset // 10) if window_id else None)
                    rows.append(row)
            metadata['directions'][direction] = dict(seen=len(rows), dropped=0, rows=rows)
        return plan, report, metadata

    def test_two_watermark_schedule_preserves_fifo_without_accumulating_per_chunk(self):
        plan, report, metadata = self.fixture()
        proof = evidence.evaluate(plan, report, metadata)
        self.assertIs(proof['passed'], True)
        self.assertIs(proof['tls_chunk_to_command_mapping_claimed'], False)
        self.assertEqual([w['affected_chunks'] for w in proof['worlds']], [[2, 3, 4], [8, 9, 10]])
        self.assertEqual([w['post_enqueue_affected_chunks'] for w in proof['worlds']], [[3, 4], [9, 10]])
        self.assertEqual([w['recovered_chunk'] for w in proof['worlds']], [6, 12])
        report['transition_input_delay'] = proof
        self.assertTrue(evidence.gate(plan, json.loads(json.dumps(report))))

    def test_masked_cumulative_or_reordered_deadline_is_not_a100ms_delivery_proof(self):
        for changed_due in (10.175, 10.3375, 10.20):
            plan, report, metadata = self.fixture()
            row = metadata['directions']['client_to_server']['rows'][2]
            row.update(due_loop=changed_due, final_due_loop=changed_due,
                forwarded_loop=changed_due + .001, drained_loop=changed_due + .002,
                held_ms=(changed_due + .001 - row['received_loop']) * 1000)
            with self.subTest(changed_due=changed_due), self.assertRaises(AssertionError):
                evidence.evaluate(plan, report, metadata)

    def test_other_direction_or_existing_queued_chunk_cannot_gain_delay_fields(self):
        for direction, index in (('server_to_client', 2), ('client_to_server', 0)):
            plan, report, metadata = self.fixture()
            row = metadata['directions'][direction]['rows'][index]
            row.update(base_due_loop=row['due_loop'], final_due_loop=row['due_loop'],
                       directional_extra_ms=0.0, directional_window_id=None)
            with self.subTest(direction=direction), self.assertRaises(AssertionError):
                evidence.evaluate(plan, report, metadata)

    def test_missing_dropped_or_undelivered_held_rows_fail(self):
        for fault in ('missing_direction', 'missing_row', 'dropped', 'not_forwarded', 'not_drained'):
            plan, report, metadata = self.fixture()
            bucket = metadata['directions']['client_to_server']
            if fault == 'missing_direction':
                del metadata['directions']['server_to_client']
            elif fault == 'missing_row':
                bucket['rows'].pop(2)
            elif fault == 'dropped':
                bucket['dropped'] = 1
            elif fault == 'not_forwarded':
                bucket['rows'][2].update(forwarded_loop=None, drained_loop=None, held_ms=None)
            else:
                bucket['rows'][2]['drained_loop'] = None
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                evidence.evaluate(plan, report, metadata)

    def test_window_needs_a_post_enqueue_held_read_and_an_actually_delivered_recovery(self):
        for fault in ('post_enqueue_missing', 'late_enqueue', 'late67', 'recovery_not_delivered'):
            plan, report, metadata = self.fixture()
            order = report['transition_orders']['episodes'][1]['orders'][0]
            if fault == 'post_enqueue_missing':
                order['original_order']['enqueue_sampled_us'] = 20_245_000
                order.update(native67_tick_ms=20246, native72_send_tick_ms=20247)
            elif fault == 'late_enqueue':
                order['original_order']['enqueue_sampled_us'] = 20_251_000
            elif fault == 'late67':
                order.update(native67_tick_ms=20251, native72_send_tick_ms=20252)
            else:
                metadata['directions']['client_to_server']['rows'][-1].update(
                    forwarded_loop=None, drained_loop=None, held_ms=None)
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                evidence.evaluate(plan, report, metadata)

    def test_persistent_proof_cannot_omit_required_window_or_command_binding(self):
        plan, report, metadata = self.fixture()
        report['transition_input_delay'] = evidence.evaluate(plan, report, metadata)
        for field in ('world', 'assigned_frame', 'canonical_frame', 'affected_chunks',
                      'post_enqueue_affected_chunks', 'recovered_chunk'):
            bad = deepcopy(report)
            del bad['transition_input_delay']['worlds'][0][field]
            with self.subTest(field=field):
                self.assertFalse(evidence.gate(plan, bad))
        for field in SETTINGS:
            bad = deepcopy(report)
            del bad['transition_input_delay']['worlds'][0]['window'][field]
            with self.subTest(window_field=field):
                self.assertFalse(evidence.gate(plan, bad))

    def test_default_finalizer_reads_nothing_and_preserves_report(self):
        report = dict(passed=False, sentinel='unchanged')
        before = deepcopy(report)
        with patch.object(Path, 'read_text', side_effect=AssertionError('default must not read')):
            evidence.finalize({}, report, Path('nonexistent'))
        self.assertEqual(report, before)
        self.assertTrue(evidence.gate({}, report))

    def test_selected_finalizer_keeps_malformed_evidence_inside_failure_report(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            path = run / 'shaper-delay-0.json'
            for fault in ('missing', 'invalid_json', 'missing_fields', 'nonfinite', 'overflow'):
                plan, report, metadata = self.fixture()
                if path.exists():
                    path.unlink()
                if fault == 'invalid_json':
                    path.write_text('{')
                elif fault == 'missing_fields':
                    path.write_text('{}')
                elif fault in ('nonfinite', 'overflow'):
                    metadata['directional_delays'][0]['extra_ms'] = float('inf') if fault == 'nonfinite' else 10**1000
                    path.write_text(json.dumps(metadata))
                with self.subTest(fault=fault):
                    evidence.finalize(plan, report, run)
                    self.assertIs(report['transition_input_delay']['passed'], False)
                    self.assertIn('error', report)
                    self.assertFalse(evidence.gate(plan, report))


if __name__ == '__main__':
    unittest.main()
