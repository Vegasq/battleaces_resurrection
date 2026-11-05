"""Negative evidence controls for default loading-timeout qualification."""
import copy
import unittest

from tools.verify_loading_recovery import check_journal


class LoadingJournalControls(unittest.TestCase):
    def setUp(self):
        self.frames = [dict(sha256='frame-' + str(n)) for n in range(3)]
        self.rows = [dict(event='world_loaded', match='loading', slot=0),
                     dict(event='match_aborted', match='loading', result=None,
                          next_frame=0, reason='world loading timeout')]
        self.rows += [dict(event='frame_queued', match='healthy', frame=n,
                           frame_payload_sha256=frame['sha256']) for n, frame in enumerate(self.frames)]

    def check(self, rows):
        check_journal(rows, 'loading', 'healthy', self.frames)

    def test_accepts_timeout_without_start_or_result(self):
        self.check(self.rows)

    def test_rejects_unloaded_start_step_failure_or_winner(self):
        for event in ('match_started', 'frame_queued', 'simulation_error', 'native_game_over'):
            with self.subTest(event=event), self.assertRaises(AssertionError):
                self.check(self.rows + [dict(event=event, match='loading')])
        for field, value in (('result', {'winner': 1}), ('next_frame', 1), ('reason', 'player disconnected')):
            rows = copy.deepcopy(self.rows)
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.check(rows)

    def test_rejects_late_loaded_mutation_or_disconnect(self):
        for row in (dict(event='world_loaded', match='loading', slot=1),
                    dict(event='protocol_error', connection='late-player')):
            with self.subTest(event=row['event']), self.assertRaises(AssertionError):
                self.check(self.rows + [row])

    def test_rejects_missing_or_duplicate_abort(self):
        for rows in (self.rows[:1] + self.rows[2:], self.rows + [self.rows[1]]):
            with self.assertRaises(AssertionError):
                self.check(rows)

    def test_rejects_healthy_gap_or_different_data(self):
        rows = copy.deepcopy(self.rows)
        rows[-1]['frame_payload_sha256'] = 'changed'
        for broken in (rows, self.rows[:-1]):
            with self.assertRaises(AssertionError):
                self.check(broken)


if __name__ == '__main__':
    unittest.main()
