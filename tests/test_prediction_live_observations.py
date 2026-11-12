"""Incremental native observations preserve full-parser cross-record rules."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import verify_prediction_multiplayer as v
from tests import test_prediction_multiplayer_verifier as existing


class LiveObservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = existing.ChangingRttControllerTests()
        self.fixture.setUp()
        self.cache = None
        self.log = ''
        self.options = (self.fixture.match, 7, False, 'decision', True)

    def append(self, text, *, options=None):
        self.log += text
        decoded, cache = v.decode_changing_rtt_incremental(self.log, *(options or self.options), self.cache)
        self.cache = cache
        return decoded

    @staticmethod
    def feel(row):
        return 'MOVEMENT FEEL ' + json.dumps(row) + '\n'

    @staticmethod
    def phases(rows):
        return existing.DecisionPhaseTests.log(rows)

    def turn(self, **changes):
        return dict(dict(self.fixture.command(), ordinal=2, move_id=2, origin=[20,0,0], target=[-28,0,0],
            motion_from=[19,0,0], sampled_us=5800000, motion_from_sampled_us=5700000,
            enqueue_sampled_us=5800001, tick_ms=5800, presented_frame=532, completed_frame=532,
            physical_frame=532, originalCtor=True, physicalUI=False, queueDelta=1, action_sha256='b'*64), **changes)

    def turn_text(self, **changes):
        return 'MOVEMENT TURN ' + json.dumps(self.turn(**changes)) + '\n'

    def test_cumulative_results_equal_original_full_decoder_each_append(self):
        chunks = [self.feel(row) for row in self.fixture.rows]
        chunks += [self.fixture.sample(1, 1800, raw=475, estimate=475), self.turn_text(),
                   self.phases([existing.DecisionPhaseTests.row(6000)]),
                   self.phases([existing.DecisionPhaseTests.row(6600,552,551)])]
        for chunk in chunks:
            actual = self.append(chunk)
            self.assertEqual(actual, v.decode_changing_rtt(self.log, *self.options))

    def test_cached_records_not_json_decoded_when_only_rtt_appends(self):
        self.append(self.feel(self.fixture.rows[0]) + self.phases([existing.DecisionPhaseTests.row()]))
        with mock.patch.object(v.json, 'loads', wraps=json.loads) as loads:
            self.append(self.fixture.sample(1, 1800, raw=130, estimate=130))
        self.assertEqual(loads.call_count, 0)

    def test_truncation_and_rewrite_refused_without_mutating_prior_cache(self):
        self.append(self.feel(self.fixture.rows[0]))
        original = deepcopy(self.cache)
        for changed in (self.log[:-1], self.log.replace('MOVEMENT','REPLACED',1), 'changed\n'+self.log):
            with self.subTest(changed=changed[:20]), self.assertRaisesRegex(AssertionError,'truncated or rewritten'):
                v.decode_changing_rtt_incremental(changed,*self.options,self.cache)
            self.assertEqual(self.cache,original)

    def test_new_world_does_not_allow_old_log_prefix_to_disappear(self):
        self.append(self.feel(self.fixture.rows[0]))
        with self.assertRaisesRegex(AssertionError,'truncated or rewritten'):
            v.decode_changing_rtt_incremental('', 'b'*32,8,False,'decision',True,self.cache)

    def test_incomplete_line_refused_and_real_reader_retains_only_completed_prefix(self):
        line=self.feel(self.fixture.rows[0])
        with self.assertRaisesRegex(AssertionError,'complete lines'):
            self.append(line[:-1])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'native.log'
            path.write_bytes(b'ordinary\n'+line[:-2].encode())
            first=v.read_fresh_native_log(path)
            self.assertEqual(first,'ordinary\n')
            _,cache=v.decode_changing_rtt_incremental(first,*self.options)
            path.write_bytes(b'ordinary\n'+line.encode())
            with mock.patch.object(v.json,'loads',wraps=json.loads) as loads:
                result,_=v.decode_changing_rtt_incremental(v.read_fresh_native_log(path),*self.options,cache)
            self.assertEqual(loads.call_count,1)
            self.assertEqual(result,v.decode_changing_rtt(v.read_fresh_native_log(path),*self.options))

    def test_duplicate_command_cross_chunk_remains_error(self):
        self.append(self.feel(self.fixture.command()))
        with self.assertRaisesRegex(AssertionError,'duplicated subject Move'):
            self.append(self.feel(self.fixture.command()))

    def test_malformed_new_feel_json_remains_error(self):
        self.append(self.feel(self.fixture.rows[0]))
        with self.assertRaises(json.JSONDecodeError):
            self.append('MOVEMENT FEEL {broken}\n')

    def test_pose_order_and_mixed_clock_cross_chunk_remain_errors(self):
        for changed in (dict(tick_ms=1500),dict(presented_frame=430),dict(sampled_us=1)):
            with self.subTest(changed=changed):
                self.cache=None;self.log=''
                self.append(self.feel(self.fixture.pose(1700,1,450)))
                row=self.fixture.pose(1800,2,451);row.update(changed)
                with self.assertRaises(AssertionError):self.append(self.feel(row))

    def test_duplicate_rtt_request_across_chunks_remains_error(self):
        sample=self.fixture.sample(1,1800,raw=130,estimate=130)
        self.append(sample)
        with self.assertRaisesRegex(AssertionError,'duplicate own RTT refresh request'):self.append(sample)

    def test_rtt_ack_joins_prior_chunk_and_rejects_mismatched_send(self):
        sample=self.fixture.sample(1,1800,raw=130,estimate=130)
        sent,ack=sample.splitlines(True)
        self.append(sent)
        result=self.append(ack)
        self.assertEqual(result['samples'],v.refresh_round_trips(sample))
        self.cache=None;self.log='';self.append(sent)
        with self.assertRaisesRegex(AssertionError,'unique matching'):
            self.append(ack.replace('sent_us=1800000','sent_us=1800001'))

    def test_duplicate_transition_across_chunks_remains_deferred_error(self):
        self.append(self.turn_text())
        result=self.append(self.turn_text())
        self.assertIsInstance(result['turn_error'],AssertionError)
        self.assertIn('duplicate transition order',str(result['turn_error']))

    def test_malformed_transition_deferred_until_transition_decoding_selected(self):
        inactive=(*self.options[:-1],False)
        first=self.append('MOVEMENT TURN {broken}\n',options=inactive)
        self.assertIsNone(first['turn_error'])
        second=self.append('')
        self.assertIsInstance(second['turn_error'],json.JSONDecodeError)

    def test_phase_clock_and_throttle_across_chunks_remain_deferred_errors(self):
        for row in (existing.DecisionPhaseTests.row(6000),existing.DecisionPhaseTests.row(6009),
                    existing.DecisionPhaseTests.row(6020,decision_us=5999000),
                    existing.DecisionPhaseTests.row(6020,tick_ms=5999)):
            with self.subTest(row=row):
                self.cache=None;self.log=''
                self.append(self.turn_text()+self.phases([existing.DecisionPhaseTests.row()]))
                result=self.append(self.phases([row]))
                self.assertIsInstance(result['turn_error'],AssertionError)
                self.assertIn('clock/throttle',str(result['turn_error']))

    def test_phase_world_bound_applies_across_chunks(self):
        self.append(self.turn_text()+self.phases([existing.DecisionPhaseTests.row()]))
        self.append(self.phases([existing.DecisionPhaseTests.row(1000,world=8,match='b'*32)]))
        result=self.append(self.phases([existing.DecisionPhaseTests.row(2000,world=9,match='c'*32)]))
        self.assertIn('world/count',str(result['turn_error']))

    def test_phase_count_bound_applies_across_chunks(self):
        self.append(self.turn_text()+self.phases([existing.DecisionPhaseTests.row(6000+i*10) for i in range(4096)]))
        result=self.append(self.phases([existing.DecisionPhaseTests.row(46960)]))
        self.assertIn('world/count',str(result['turn_error']))

    def test_decision_error_does_not_replace_pacer_wait_source(self):
        text=self.turn_text()+'MOVEMENT PHASE {broken}\n'
        result=self.append(text,options=(*self.options[:3],'pacer_wait',True))
        self.assertIsNone(result['turn_error'])
        self.assertIsInstance(self.append('')['turn_error'],json.JSONDecodeError)

    def test_duplicate_pacing_start_across_chunks_keeps_original_error(self):
        self.options=(*self.options[:3],'pacer_wait',True)
        start=f'Movement pacing START: match={self.fixture.match} world=7 waitSteadyFrame=1\n'
        self.append(self.turn_text()+start)
        result=self.append(start)
        self.assertIn('duplicate current-match pacing START',str(result['turn_error']))

    def test_prior_cache_is_unchanged_when_new_observations_are_returned(self):
        self.append(self.turn_text()+self.phases([existing.DecisionPhaseTests.row()]))
        old=self.cache;before=deepcopy(old)
        self.append(self.phases([existing.DecisionPhaseTests.row(6020)]))
        self.assertEqual(old,before)
        self.assertIsNot(old,self.cache)


class NativeStatusTests(unittest.TestCase):
    def test_all_original_failure_markers_are_retained_after_append(self):
        for marker in v.NATIVE_FAILURE_MARKERS:
            with self.subTest(marker=marker):
                state=v.update_native_status('ordinary\n')
                state=v.update_native_status(state['log']+marker+'\n',state)
                self.assertTrue(state['failed'])
                self.assertTrue(v.update_native_status(state['log']+'ordinary\n',state)['failed'])

    def test_lifecycle_markers_accumulate_and_rewrite_is_refused(self):
        state=v.update_native_status(v.COMPLETE+'\n')
        self.assertTrue(state['complete']);self.assertFalse(state['left'])
        state=v.update_native_status(state['log']+'COMMUNITY MATCH SMOKE post-match leave passed: role=guest\n',state)
        self.assertTrue(state['complete'] and state['guest_left'] and state['left'])
        with self.assertRaisesRegex(AssertionError,'truncated or rewritten'):v.update_native_status('',state)


if __name__=='__main__':unittest.main()
