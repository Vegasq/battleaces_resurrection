import io
import unittest
from unittest.mock import patch

from tools.frame_timing import matches, measure, qualify, read_trace


def row(ms, event, frame=-1, presented=-1, queued=0):
    return dict(ms=ms, event=event, update=0, frame=frame, sim=frame,
                presented=presented, queued=queued)


class FrameTimingTest(unittest.TestCase):
    def test_smooth_offline_views(self):
        rows = [row(50*i, "view", presented=i) for i in range(12, 112)]
        result = measure(rows)
        self.assertEqual(result["skipped_presented_updates"], 0)
        self.assertEqual(result["gaps_over_100_ms"], 0)
        self.assertEqual(result["p95_gap_ms"], 50)
        self.assertEqual(result["min_gap_ms"], 50)
        self.assertEqual(result["p05_gap_ms"], 50)
        self.assertEqual(result["gaps_under_25_ms"], 0)

    def test_repeated_same_frame_views_do_not_create_short_gaps(self):
        rows = [row(0, "view", presented=11), row(0, "view", presented=11),
                row(10, "view", presented=11), row(50, "view", presented=12),
                row(50, "view", presented=12), row(100, "view", presented=13)]
        result = measure(rows)
        self.assertEqual(result["presented_changes"], 3)
        self.assertEqual(result["min_gap_ms"], 50)
        self.assertEqual(result["gaps_under_25_ms"], 0)

    def test_short_gap_threshold_excludes_exactly_half_a_tick(self):
        rows = [row(0, "view", presented=11), row(24, "view", presented=12),
                row(49, "view", presented=13), row(99, "view", presented=14)]
        result = measure(rows)
        self.assertEqual(result["min_gap_ms"], 24)
        self.assertEqual(result["p05_gap_ms"], 24)
        self.assertEqual(result["gaps_under_25_ms"], 1)
        self.assertEqual(result["max_gap_ms"], 50)

    def test_single_counter_observation_has_no_intervals(self):
        result = measure([row(0, "view", presented=11)])
        self.assertIsNone(result["min_gap_ms"])
        self.assertIsNone(result["p05_gap_ms"])
        self.assertIsNone(result["max_gap_ms"])
        self.assertEqual(result["gaps_under_25_ms"], 0)

    def test_qpc_distinguishes_advances_with_the_same_coarse_timestamp(self):
        rows = [dict(row(100, "view", presented=11), qpc_us=900000000000),
                dict(row(100, "view", presented=12), qpc_us=900000001125),
                dict(row(150, "view", presented=13), qpc_us=900000050000)]
        result = measure(rows)
        self.assertEqual(result["timestamp_source"], "qpc_us")
        self.assertEqual(result["min_gap_ms"], 1.125)
        self.assertEqual(result["max_gap_ms"], 48.875)
        self.assertEqual(result["p05_gap_ms"], 1.125)
        self.assertEqual(result["effective_presented_hz"], 40)

    def test_qpc_classifies_short_gaps_at_microsecond_boundary(self):
        rows = [dict(row(ms, "view", presented=i+11), qpc_us=qpc)
                for i, (ms, qpc) in enumerate(((0, 1000000), (31, 1024999),
                                              (47, 1049999), (78, 1075000)))]
        result = measure(rows)
        self.assertEqual(result["min_gap_ms"], 24.999)
        self.assertEqual(result["max_gap_ms"], 25.001)
        self.assertEqual(result["gaps_under_25_ms"], 1)

    def test_qpc_classifies_a_pause_above_100_ms_without_coarse_rounding(self):
        rows = [dict(row(0, "view", presented=11), qpc_us=1000000),
                dict(row(100, "view", presented=12), qpc_us=1100001)]
        result = measure(rows)
        self.assertEqual(result["max_gap_ms"], 100.001)
        self.assertEqual(result["gaps_over_100_ms"], 1)

    def test_missing_optional_qpc_uses_coarse_clock_for_the_whole_match(self):
        rows = [dict(row(0, "view", presented=11), qpc_us=1000000),
                dict(row(50, "view", presented=12), qpc_us=None),
                dict(row(100, "view", presented=13), qpc_us=1005000)]
        result = measure(rows)
        self.assertEqual(result["timestamp_source"], "ms")
        self.assertEqual(result["min_gap_ms"], 50)
        self.assertEqual(result["effective_presented_hz"], 20)

    def test_nonmonotonic_qpc_is_invalid_even_with_monotonic_coarse_ms(self):
        rows = [dict(row(0, "view", presented=11), qpc_us=1000001),
                dict(row(50, "view", presented=12), qpc_us=1000000)]
        with self.assertRaisesRegex(ValueError, "nonmonotonic presentation"):
            measure(rows)

    def test_trace_reader_accepts_old_and_optional_qpc_columns(self):
        header = "ms\tevent\tupdate\tframe\tsim\tpresented\tqueued"
        legacy = header + "\n0\tview\t0\t-1\t0\t11\t0\n50\tview\t1\t-1\t1\t12\t0\n"
        with patch("tools.frame_timing.Path.open", return_value=io.StringIO(legacy)):
            result = measure(read_trace("old.tsv"))
        self.assertEqual(result["timestamp_source"], "ms")
        self.assertEqual(result["min_gap_ms"], 50)
        precise = header + "\tqpc_us\n0\tview\t0\t-1\t0\t11\t0\t1000000\n50\tview\t1\t-1\t1\t12\t0\t1050123\n"
        with patch("tools.frame_timing.Path.open", return_value=io.StringIO(precise)):
            result = measure(read_trace("new.tsv"))
        self.assertEqual(result["timestamp_source"], "qpc_us")
        self.assertEqual(result["min_gap_ms"], 50.123)
        missing = precise.replace("1050123", "")
        with patch("tools.frame_timing.Path.open", return_value=io.StringIO(missing)):
            result = measure(read_trace("missing.tsv"))
        self.assertEqual(result["timestamp_source"], "ms")
        self.assertEqual(result["min_gap_ms"], 50)

    def test_network_burst_is_a_visible_skip(self):
        rows = [row(0, "apply", frame=0), row(0, "arrival", frame=0, queued=1)]
        rows += [row(50, "view", presented=11), row(100, "view", presented=12),
                 row(150, "view", presented=12), row(200, "view", presented=15)]
        result = measure(rows)
        self.assertEqual(result["skipped_presented_updates"], 1)
        self.assertEqual(result["skipped_presented_frames"], 2)
        self.assertEqual(result["gaps_over_100_ms"], 0)

    def test_each_match_has_its_own_frame_sequence(self):
        rows = [row(0, "arrival", frame=0), row(1, "apply", frame=0),
                row(100, "arrival", frame=0), row(101, "apply", frame=0)]
        self.assertEqual(len(matches(rows)), 2)
        self.assertEqual([measure(part)["applied_frames"] for part in matches(rows)], [1, 1])

    def test_missing_authoritative_frame_is_invalid(self):
        with self.assertRaisesRegex(ValueError, "noncontiguous apply"):
            measure([row(0, "apply", frame=0), row(50, "apply", frame=2)])

    @staticmethod
    def completed_trace(step_ms=50):
        return [event for i in range(620)
                for event in (row(step_ms*i, "arrival", frame=i),
                              row(step_ms*i, "apply", frame=i),
                              row(step_ms*i, "view", presented=i))]

    def test_complete_paced_match_passes(self):
        self.assertTrue(qualify(self.completed_trace(), [620])["passed"])

    def test_no_skips_does_not_excuse_slow_motion(self):
        result = qualify(self.completed_trace(step_ms=75), [620])
        self.assertFalse(result["passed"])
        self.assertTrue(any("below 19 Hz" in error for error in result["errors"]))

    def test_no_skips_does_not_excuse_fast_forward(self):
        result = qualify(self.completed_trace(step_ms=25), [620])
        self.assertFalse(result["passed"])
        self.assertTrue(any("exceeds 21 Hz" in error for error in result["errors"]))

    def test_missing_final_view_fails(self):
        result = qualify(self.completed_trace()[:-1], [620])
        self.assertFalse(result["passed"])
        self.assertTrue(any("did not cover" in error for error in result["errors"]))

    def test_missing_match_and_shifted_authoritative_sequence_fail(self):
        rows = self.completed_trace()
        self.assertFalse(qualify(rows, [620, 620])["passed"])
        for event in rows:
            if event["event"] != "view":
                event["frame"] += 100
        self.assertFalse(qualify(rows, [620])["passed"])

    def test_burst_skipping_two_frames_fails_even_as_one_jump(self):
        rows = [event for event in self.completed_trace()
                if event["event"] != "view" or event["presented"] not in (50, 51)]
        result = qualify(rows, [620])
        self.assertFalse(result["passed"])
        self.assertEqual(result["matches"][0]["skipped_presented_frames"], 2)

    def starvation_then_catchup_trace(self):
        rows = self.completed_trace()
        # Frames100..102 all arrive/apply/present at5100ms:150ms after99.
        # No frame numbers disappear and the full-match average remains20Hz.
        for event in rows:
            frame = event["presented"] if event["event"] == "view" else event["frame"]
            if frame in (100, 101):
                event["ms"] = 5100
        return rows

    def test_starvation_then_bunched_progress_needs_optional_short_gap_gate(self):
        rows = self.starvation_then_catchup_trace()
        ordinary = qualify(rows, [620])
        self.assertTrue(ordinary["passed"])
        measured = ordinary["matches"][0]
        self.assertEqual(measured["skipped_presented_frames"], 0)
        self.assertEqual(measured["p95_gap_ms"], 50)
        self.assertEqual(measured["effective_presented_hz"], 20)
        self.assertEqual(measured["min_gap_ms"], 0)
        self.assertEqual(measured["gaps_under_25_ms"], 2)
        self.assertTrue(qualify(rows, [620], max_short_gaps=2)["passed"])
        strict = qualify(rows, [620], max_short_gaps=1)
        self.assertFalse(strict["passed"])
        self.assertTrue(any("under 25 ms exceed 1" in error for error in strict["errors"]))

    def test_optional_maximum_gap_catches_a_rare_pause(self):
        rows = self.starvation_then_catchup_trace()
        self.assertTrue(qualify(rows, [620], max_gap_ms=150)["passed"])
        strict = qualify(rows, [620], max_gap_ms=100)
        self.assertFalse(strict["passed"])
        self.assertEqual(strict["matches"][0]["max_gap_ms"], 150)
        self.assertTrue(any("maximum presentation gap exceeds 100" in error
                            for error in strict["errors"]))


if __name__ == "__main__":
    unittest.main()
