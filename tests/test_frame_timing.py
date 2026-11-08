import unittest

from tools.frame_timing import matches, measure, qualify


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


if __name__ == "__main__":
    unittest.main()
