"""Compatibility packet and evidence controls; no native processes."""
import copy
import unittest

from server import protocol as p, community_protocol as community
from tools.verify_compatibility import CASES, hello, check_journal


class CompatibilityControls(unittest.TestCase):
    def test_each_fault_reaches_its_intended_decoder_guard(self):
        for case, reason in CASES.items():
            with self.subTest(case=case):
                kind, body = hello(case, 'compatibility_profile')
                decoder = community.decode_hello if kind == community.HELLO else p.decode_hello
                with self.assertRaises(ValueError) as raised:
                    decoder(body)
                self.assertEqual(str(raised.exception), reason)

    def test_one_field_mutation_preserves_every_other_byte(self):
        for case in CASES:
            with self.subTest(case=case):
                kind, body = hello(case, 'compatibility_profile')
                original = (community.hello('compatibility_profile', 'Compatibility', version=2)
                            if kind == community.HELLO else
                            p.hello(0, 'compatibility_profile', 'Compatibility', 'compatibility'))
                self.assertEqual(len(body), len(original))
                self.assertEqual(sum(a != b for a, b in zip(body, original)), 1)
                (community.decode_hello if kind == community.HELLO else p.decode_hello)(original)

    def setUp(self):
        self.failures = [dict(case=case, connection=str(i)) for i, case in enumerate(CASES)]
        self.frames = [dict(sha256=str(i)) for i in range(40)]
        self.rows = [dict(event='protocol_error', connection=r['connection'], reason=CASES[r['case']])
                     for r in self.failures]
        self.rows += [dict(event='frame_queued', match='healthy', frame=i, frame_payload_sha256=str(i))
                      for i in range(40)]

    def check(self, rows):
        check_journal(rows, self.failures, 'healthy', self.frames)

    def test_complete_journal(self):
        self.check(self.rows)

    def test_wrong_rejection_or_connection_fails(self):
        for field in ('reason', 'connection'):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = 'wrong'
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.check(rows)

    def test_missing_duplicate_or_changed_frame_fails(self):
        rows = copy.deepcopy(self.rows)
        rows[-1]['frame_payload_sha256'] = 'wrong'
        for invalid in (rows, self.rows[:-1], self.rows + [self.rows[-1]], self.rows[1:]):
            with self.assertRaises(AssertionError):
                self.check(invalid)

    def test_healthy_abort_failure_or_completion_fails(self):
        for event in ('match_aborted', 'simulation_error', 'match_completed'):
            with self.subTest(event=event), self.assertRaises(AssertionError):
                self.check(self.rows + [dict(event=event, match='healthy')])


if __name__ == '__main__':
    unittest.main()
