"""Negative evidence controls for the committed Custom ownership diagnostic."""
import unittest

from tools.verify_custom_ownership import check_journal


def journal():
    return [
        {'event': 'match_started', 'match': 'first'},
        *({'event': 'frame_queued', 'match': 'first', 'frame': n} for n in range(160)),
        {'event': 'match_completed', 'match': 'first'},
        {'event': 'match_started', 'match': 'second'},
        *({'event': 'frame_queued', 'match': 'second', 'frame': n} for n in range(10)),
    ]


class CustomOwnershipEvidenceTests(unittest.TestCase):
    def test_completion_then_replacement_accepted(self):
        check_journal(journal(), 'first', 160, 'second')

    def test_error_or_abort_cannot_count_as_command_refusal(self):
        for event in ('protocol_error', 'simulation_error', 'match_aborted'):
            with self.subTest(event=event), self.assertRaisesRegex(AssertionError, 'disrupted'):
                check_journal(journal() + [{'event': event, 'match': 'first'}], 'first', 160, 'second')

    def test_lost_or_duplicate_frames_rejected(self):
        rows = journal()
        for changed in (rows[:1] + rows[2:], rows + [rows[-1]]):
            with self.assertRaisesRegex(AssertionError, 'frame sequence'):
                check_journal(changed, 'first', 160, 'second')

    def test_duplicate_start_or_stale_completion_rejected(self):
        for event, message in (('match_started', 'start count'), ('match_completed', 'completion count')):
            with self.subTest(event=event), self.assertRaisesRegex(AssertionError, message):
                check_journal(journal() + [{'event': event, 'match': 'second'}], 'first', 160, 'second')


if __name__ == '__main__':
    unittest.main()
