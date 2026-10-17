import unittest
from server.verify_dedicated_run import scope_match_log


class ClientEvidenceTests(unittest.TestCase):
    def test_rematch_logs_never_mix_same_frame_from_other_session(self):
        first, second = 'a' * 32, 'b' * 32
        lines = ['Dedicated lobby welcome slot 0; saved deck received',
                 f'Dedicated session 1 joined match={first} assignedSeat=0',
                 'LAN received frame 0, first world', 'Dedicated match ended: first',
                 f'Dedicated session reset: match={first}',
                 'Dedicated lobby welcome slot 1; saved deck received',
                 f'Dedicated session 2 joined match={second} assignedSeat=1',
                 'LAN received frame 0, second world', 'Dedicated match ended: second']
        selected, slot, warning = scope_match_log(lines, first, 1)
        self.assertEqual((slot, warning), (0, None))
        self.assertIn('LAN received frame 0, first world', selected)
        self.assertNotIn('LAN received frame 0, second world', selected)
        selected, slot, warning = scope_match_log(lines, second, 0)
        self.assertEqual((slot, warning), (1, None))
        self.assertNotIn('LAN received frame 0, first world', selected)

    def test_missing_and_duplicate_session_cannot_be_attributed(self):
        marker = f'Dedicated session 1 joined match={"a" * 32} assignedSeat=0'
        for lines, chosen in (([marker], 'b' * 32), ([marker, marker], 'a' * 32)):
            selected, _, warning = scope_match_log(lines, chosen, 0)
            self.assertEqual(selected, [])
            self.assertTrue(warning)

    def test_legacy_single_match_welcome_overrides_launch_order(self):
        lines = ['Dedicated lobby welcome slot 1; saved deck received', 'LAN received frame 0']
        self.assertEqual(scope_match_log(lines, 'a' * 32, 0), (lines, 1, None))
        self.assertTrue(scope_match_log(lines + lines, 'a' * 32, 0)[2])
