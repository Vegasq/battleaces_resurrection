"""Authored actual-record controls; no game, native worker, build or installation."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import test_prediction_input_delay_controller as delay_tests
from tools import prediction_visual_correction as visual
from tools import prediction_correction_motion as motion
from tools import verify_prediction_multiplayer as controller


def authored(world=1, flipped=False, late_correction=False):
    """Two observed repairs during forward motion, with immutable native endpoints.

    Raw speed is6.3units/sec; two losses1.25/.5units cause visible backtracking.
    Their combined finite-decay maximum speed is below forward motion. This is
    a deliberately easy independent control, not a simulation of actual74.
    """
    binding = dict(world=world, match=str(world)*32, entity=74, unit_type=1, army=0, incarnation=75)
    native = []; episodes = []; publications = []; records = []
    corrections = {535: -1.25, 537: -.5}
    if late_correction:
        corrections[649] = -.125
    pulses = []; previous_x = 99.685; shift = 0.; previous_write = False
    for frame in range(400, 651):
        timestamp = world*20_000_000+(frame-400)*50_000
        if frame in corrections:
            delta = corrections[frame]; shift += delta
            old = native[-1]
            before = dict(old, event='before_restore_cached_head', record=len(native),
                          cached_from_record=old['record'], revision=len(pulses)+1)
            native.append(before)
            after = dict(old, event='after_replay_same_head', record=len(native),
                position=motion.vec([previous_x+delta, 0, 0]), query_begin_us=timestamp-300,
                query_end_us=timestamp-200, revision=len(pulses)+1)
            native.append(after)
            episodes.append(dict(physical_head=frame-1, before_record=before['record'],
                after_record=after['record'], revision=len(pulses)+1, qualified=True))
            pulse = dict(schema=1, event='correction', **binding, frame=frame, head=frame-1,
                revision=len(pulses)+1, lease=10+world, publication_us=timestamp, duration_us=900000,
                admission=0, flipped=flipped, native_delta=[delta, 0, 0],
                mapped_delta=[-delta if flipped else delta, 0, 0])
            records.append(pulse); pulses.append(pulse)
        x = motion.vec([100+(frame-400)*.315+shift, 0, 0])[0]
        native.append(dict(world=world, frame=frame, status='present', event='native_position',
            record=len(native), position=[x, 0., 0.], revision=len(pulses),
            query_begin_us=timestamp-100, query_end_us=timestamp-50))
        publications.append(dict(frame=frame, qpc_us=timestamp+10))
        sign = -1 if flipped else 1
        a, b = motion.vec([sign*previous_x, 0, 0]), motion.vec([sign*x, 0, 0])
        for alpha, lag in ((0., 100), (1., 40000)):
            now = timestamp+lag
            raw = list(a if alpha == 0 else b)
            active = [c for c in pulses if now-c['publication_us'] < 900000]
            # Independent Hermite endpoint interpolation: h00(0)=1,h00(1)=0,
            # zero endpoint slopes. No production Policy import or shared oracle.
            offset = 0.
            for c in active:
                t = (now-c['publication_us'])/900000
                hermite = (2*t**3-3*t**2+1)
                offset -= c['mapped_delta'][0]*hermite*(alpha if frame == c['frame'] else 1.)
            displayed = motion.vec([raw[0]+offset, 0, 0])
            wrote = offset != 0 or previous_write
            previous_write = offset != 0
            records.append(dict(schema=1, event='visual_pose', **binding, frame=frame,
                lease=10+world, publication_us=timestamp, sampled_us=now, alpha=alpha,
                elapsed=0. if alpha == 0 else .05, step=0. if alpha == 0 else .05,
                flipped=flipped, pulses=len(active), wrote=wrote, **{'from':a, 'to':b},
                raw=raw, displayed=displayed, output=list(displayed), transform=list(displayed)))
        previous_x = x
    order = dict(ordinal=2, **binding, originalCtor=True, physicalUI=False,
        enqueue_sampled_us=world*20_000_000+130*50_000, origin=[0, 0, 0],
        target=[-48 if flipped else 48, 0, 0])
    command = dict(ordinal=2, assigned_frame=531, canonical_frame=536,
        original_order=order, sequence=4, action_sha256='a'*64)
    return dict(binding=binding, records=records, native=native, episodes=episodes,
        publications=publications, command=command,
        next_order=dict(ordinal=3, enqueue_sampled_us=world*20_000_000+160*50_000))


def evaluate(data):
    data = deepcopy(data)
    data['records'] = visual.rows('\n'.join('[1] '+visual.PREFIX+json.dumps(r) for r in data['records']))
    return visual.evaluate_world(**data)


class VisualRecordTests(unittest.TestCase):
    def test_frontend_query_records_have_a_separate_parser(self):
        record=authored()['records'][0]
        line=visual.PREFIX+json.dumps(record)
        expected=visual.rows(line)
        self.assertEqual(visual.rows(line+'\nPREDICTION VISUAL INPUT {"schema":1}\n'),expected)
        with self.assertRaises(ValueError):
            visual.rows(line+'\nPREDICTION VISUAL UNKNOWN {}\n')

    def test_two_worlds_native_repair_raw_backtrack_reduced_and_tail_observed(self):
        for world, flipped in ((1, False), (2, True)):
            result = evaluate(authored(world, flipped))
            self.assertTrue(result['passed'])
            self.assertGreater(result['raw_backtrack']['amount'], .9)
            self.assertLess(result['displayed_backtrack']['amount'], .05)
            self.assertGreaterEqual(result['tail']['duration_us'], 150000)
            self.assertTrue(result['tail']['raw_equal'])
            self.assertEqual(result['poses'], 502)
            self.assertEqual([r['native_delta'] for r in result['corrections']], [[-1.25, 0., 0.], [-.5, 0., 0.]])

    def test_delta_is_same_head_not_publication_step_or_wrong_perspective(self):
        for key, delta in (('native_delta', [-.935, 0, 0]), ('mapped_delta', [1.25, 0, 0])):
            data = authored(); next(r for r in data['records'] if r['event']=='correction')[key] = delta
            with self.subTest(key=key), self.assertRaisesRegex(AssertionError, 'delta'):
                evaluate(data)

    def test_clock_and_original_alpha_are_observed_not_inferred(self):
        changes = [dict(alpha=.5), dict(elapsed=.01), dict(step=.1), dict(publication_us=1),
                   dict(sampled_us=1)]
        for change in changes:
            data = authored(); data['records'][11].update(change)
            with self.subTest(change=change), self.assertRaises(AssertionError):
                evaluate(data)

    def test_actual_raw_shared_output_and_transform_each_are_mandatory(self):
        for key in ('from', 'to', 'raw', 'displayed', 'output', 'transform'):
            data = authored(); row = next(r for r in data['records'] if r['event']=='visual_pose' and r['frame']==538)
            row[key] = [row[key][0]+.02, 0, 0]
            with self.subTest(key=key), self.assertRaises(AssertionError):
                evaluate(data)

    def test_overlapping_pulses_must_not_restart_the_older_decay(self):
        data = authored()
        row = next(r for r in data['records'] if r['event']=='visual_pose' and r['frame']==539)
        # A restart at the second publication would retain too much old offset.
        for field in ('displayed', 'output', 'transform'):
            row[field] = [row[field][0]+.10, 0, 0]
        with self.assertRaisesRegex(AssertionError, 'independent cubic'):
            evaluate(data)

    def test_admission_capacity_distance_and_missing_correction_do_not_pass(self):
        for admission in (1, 5, 6):
            data = authored(); next(r for r in data['records'] if r['event']=='correction')['admission']=admission
            with self.subTest(admission=admission), self.assertRaisesRegex(AssertionError, 'refused'):
                evaluate(data)
        data = authored(); data['records'] = [r for r in data['records'] if not (r['event']=='correction' and r['frame']==535)]
        with self.assertRaisesRegex(AssertionError, 'missing, extra'):
            evaluate(data)

    def test_changed_actor_incarnation_lease_world_or_native_endpoints_refuses(self):
        for key in ('world', 'entity', 'unit_type', 'army', 'incarnation', 'lease'):
            data = authored(); data['records'][100][key] += 1
            with self.subTest(key=key), self.assertRaises(AssertionError):
                evaluate(data)
        data = authored(); data['native'][100]['position'][0] += .01
        with self.assertRaisesRegex(AssertionError, 'native publication'):
            evaluate(data)

    def test_no_raw_change_after_expiry_or_diagnostic_truncation(self):
        data = authored()
        for field in ('displayed', 'output', 'transform'):
            data['records'][-1][field][0] += .01
        with self.assertRaises(AssertionError):
            evaluate(data)
        data = authored(); data['records'] = data['records'][:-2]
        with self.assertRaisesRegex(AssertionError, '400..650'):
            evaluate(data)

    def test_last_late_pulse_cannot_claim_a_tail_from_earlier_pulses(self):
        with self.assertRaisesRegex(AssertionError, 'expiry plus150ms'):
            evaluate(authored(late_correction=True))

    def test_late_metadata_after_first_join_does_not_retroactively_qualify(self):
        data = authored()
        index = next(i for i, r in enumerate(data['records']) if r['event']=='correction')
        data['records'][index:index+2] = reversed(data['records'][index:index+2])
        with self.assertRaises(AssertionError):
            evaluate(data)

    def test_turn3_boundary_cannot_be_used_to_claim_a_turn2_benefit(self):
        data = authored(); data['next_order']['enqueue_sampled_us'] = data['command']['original_order']['enqueue_sampled_us']+100000
        with self.assertRaisesRegex(AssertionError, 'turn2-before-turn3'):
            evaluate(data)

    def test_raw_positive_control_and_display_threshold_fail_closed(self):
        data = authored()
        data['command']['original_order']['target'] = [0, 0, 48]
        with self.assertRaisesRegex(AssertionError, 'large raw backtrack'):
            evaluate(data)
        # Actual measurements must meet the threshold even when every policy
        # equation passes. This assertion exercises the measured-result gate.
        with patch.object(visual, 'backtrack', side_effect=[dict(amount=1.), dict(amount=.36)]):
            with self.assertRaisesRegex(AssertionError, 'below0.35'):
                evaluate(authored())

    def test_duplicate_json_nonfinite_values_and_consumer_failure_refuse(self):
        row = authored()['records'][0]
        text = json.dumps(row)
        for raw in (text.replace('"schema": 1', '"schema": 1, "schema": 1'),
                    text.replace('"alpha": 0.0', '"alpha": NaN'),
                    text.replace('"frame": 400', '"frame": true')):
            with self.subTest(raw=raw[:50]), self.assertRaises(AssertionError):
                visual.rows(visual.PREFIX+raw)
        with self.assertRaisesRegex(AssertionError, 'consumer failure'):
            visual.rows('Prediction visual correction failed: actual exception')

    def test_native_pair_missing_or_wrong_cache_and_sample_pulse_count_refuse(self):
        for mutation in (lambda d: d['episodes'][0].update(qualified=False),
                         lambda d: d['native'][d['episodes'][0]['before_record']].update(cached_from_record=1),
                         lambda d: next(r for r in d['records'] if r['event']=='visual_pose' and r['frame']==538).update(pulses=1)):
            data = authored(); mutation(data)
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                evaluate(data)


class VisualPlanTests(unittest.TestCase):
    def setUp(self):
        self.fixture = delay_tests.InputDelayPreparationTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.args = self.fixture.args
        self.args.visual_correction = True
        base = self.fixture.fixture
        helper = base.game/'BattleAcesOffline.dll'
        helper.write_bytes(helper.read_bytes()+b''.join(flag.encode('utf-16-le') for flag in
            ('-prediction-visual-correction', '-prediction-visual-observe', '-prediction-presentation-stages')))
        self.args.expected_helper_sha256 = controller.sha(helper)
        for path in (base.game/'.battleaces-resurrection/patch-manifest.json', self.args.helper_build_receipt):
            value = json.loads(path.read_text()); value['helper_sha256'] = self.args.expected_helper_sha256
            path.write_text(json.dumps(value))

    def test_explicit_plan_freezes_both_clients_subject_only_observer(self):
        before = self.fixture.fixture.snapshot_game()
        plan = controller.prepare(self.args)
        self.assertIs(plan['visual_correction'], True)
        self.assertEqual(plan, controller.verify_prepared(self.args.output))
        self.assertEqual(before, self.fixture.fixture.snapshot_game())
        for slot in (0, 1):
            args = controller.command_extra(plan, slot, self.args.output/'run')
            self.assertEqual(args.count('-prediction-visual-correction'), 1)
            self.assertEqual(args.count('-prediction-presentation-stages'), 1)
            self.assertEqual(args.count('-prediction-visual-observe'), 1 if slot==0 else 0)
            self.assertEqual(args.count('-prediction-movement-observe-position=74:1:0:400:650'), 1 if slot==0 else 0)

    def test_default_argv_and_plan_are_unchanged(self):
        self.args.visual_correction = False
        plan = controller.prepare(self.args)
        self.assertNotIn('visual_correction', plan)
        for slot in (0, 1):
            self.assertFalse(any('visual-' in arg for arg in controller.command_extra(plan,slot,self.args.output/'run')))
            self.assertNotIn('-prediction-presentation-stages', controller.command_extra(plan,slot,self.args.output/'run'))

    def test_wrong_boolean_delay_and_fixture_refuse_before_output_creation(self):
        for changed in (dict(visual_correction=1), dict(visual_correction='true'),
                        dict(transition_input_delay_ms=None), dict(native_position_trace='74:1:0:400:640'),
                        dict(move_slot=1), dict(frames=600), dict(rtt_ms=(475,130)),
                        dict(terminal_timeline=True), dict(mobile_focus=True)):
            args = deepcopy(self.args); vars(args).update(changed)
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                controller.prepare(args)
            self.assertFalse(self.args.output.exists())

    def test_prepared_option_or_fixture_mutation_refuses_verification_and_argv(self):
        plan = controller.prepare(self.args)
        for changed in (dict(visual_correction=1), dict(frames=651), dict(expected_matches=1),
                        dict(transition_input_delay=None), dict(changing_pose_clock=None)):
            value = dict(plan, **changed); (self.args.output/'invocation.json').write_text(json.dumps(value))
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                controller.verify_prepared(self.args.output)
            with self.assertRaises(AssertionError):
                controller.command_extra(value,0,self.args.output/'run')

    def test_helper_export_and_both_utf16_flags_required(self):
        markers = [b'OfflinePredictionVisualJoin\0', '-prediction-visual-correction'.encode('utf-16-le'),
                   '-prediction-visual-observe'.encode('utf-16-le'),
                   '-prediction-presentation-stages'.encode('utf-16-le')]
        visual.helper(True, b''.join(markers))
        for marker in markers:
            with self.assertRaisesRegex(AssertionError, 'helper lacks'):
                visual.helper(True, b''.join(m for m in markers if m != marker))
        visual.helper(False, b'MZ')

    def test_cli_boolean_opt_in_defaults_false(self):
        argv = []
        for name in ('game','assets','output','python','module-root','heap-helper','cooperative','helper-build-receipt'):
            argv += ['--'+name, 'authored']
        argv += ['--expected-helper-sha256','1'*64,'--expected-gameassembly-sha256','2'*64]
        with patch.object(controller,'prepare',return_value=dict(output='authored',scenario='movement')) as prepare, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(controller.main(argv+['--visual-correction']),0)
            self.assertIs(prepare.call_args.args[0].visual_correction,True)
            self.assertEqual(controller.main(argv),0)
            self.assertIs(prepare.call_args.args[0].visual_correction,False)


class ParentGateTests(unittest.TestCase):
    def test_complete_unchanged_parent_required_even_with_visual_positive_control(self):
        sources = {'bound-source.py':'a'*64}
        plan = dict(source_sha256=sources)
        report = dict(passed=True, source_unchanged=True, files_unchanged=True,
            forced_cleanup=False, cleanup_errors=[], source_sha256_at_start=sources,
            source_sha256_at_finish=sources)
        with patch.object(visual.input_delay,'gate',return_value=True):
            visual.parent_gate(plan,report)
            for change in (dict(passed=False), dict(source_unchanged=False), dict(files_unchanged=False),
                           dict(forced_cleanup=True), dict(cleanup_errors=['not natural']),
                           dict(source_sha256_at_finish={'changed.py':'b'*64})):
                with self.subTest(change=change), self.assertRaisesRegex(AssertionError,'full original'):
                    visual.parent_gate(plan,dict(report,**change))
        with patch.object(visual.input_delay,'gate',return_value=False):
            with self.assertRaisesRegex(AssertionError,'full original'):
                visual.parent_gate(plan,report)

    def test_visual_result_never_overrides_failed_native_wire_or_lifecycle_parent(self):
        report = dict(passed=False, source_unchanged=True, files_unchanged=True,
                      forced_cleanup=False, cleanup_errors=[])
        with patch.object(visual.input_delay,'gate',return_value=True):
            with self.assertRaisesRegex(AssertionError,'full original'):
                visual.parent_gate({},report)
        with patch.object(visual,'analyze',return_value=dict(passed=True)):
            visual.finalize(dict(visual_correction=True),report,Path('unused'))
        self.assertIs(report['passed'],False)

    def test_unqualified_visual_failure_is_retained_and_closes_parent_pass(self):
        report = dict(passed=True)
        with patch.object(visual,'analyze',side_effect=AssertionError('tail absent')):
            visual.finalize(dict(visual_correction=True),report,Path('unused'))
        self.assertFalse(report['passed'])
        self.assertIn('tail absent',report['visual_correction']['error'])
        self.assertTrue(report['visual_correction']['parent_gates_passed'])

    def test_default_finalizer_does_nothing(self):
        report = dict(passed=True)
        with patch.object(visual,'analyze',side_effect=AssertionError('must not analyze')):
            visual.finalize({},report,Path('unused'))
        self.assertEqual(report,dict(passed=True))


if __name__ == '__main__':
    unittest.main()
