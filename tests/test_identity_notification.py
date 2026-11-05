"""Retained static evidence controls; no original native code is executed."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import review_identity_notification as gate


@unittest.skipUnless(os.environ.get('BA_IDENTITY_NOTIFICATION_EVIDENCE'), 'retained evidence is opt-in')
class NotificationEvidenceTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.original = root.parent.parent / 'BattleAcesBeta_untouched'
        self.installed = root / 'local/r171g'
        self.evidence = Path(os.environ['BA_IDENTITY_NOTIFICATION_EVIDENCE']).resolve()

    def review(self):
        return gate.review(self.original, self.installed, self.evidence)

    def test_named_sink_and_timer_with_explicit_unknowns(self):
        result = self.review()
        self.assertTrue(result['passed'])
        self.assertEqual(result['timing_import']['name'], 'QueryPerformanceFrequency')
        self.assertEqual(result['managed_rva'], '0x53d7a00')
        for key in ('advertising_producer_resolved', 'subscriber_set_resolved', 'runtime_observed'):
            self.assertFalse(result[key])

    def test_different_event_name_rejected(self):
        with patch.dict(gate.LITERALS, {0x19b3118: 'CallSessionStateChanged'}):
            with self.assertRaisesRegex(ValueError, 'Bound name differs'):
                self.review()

    def test_missing_dispatch_instruction_rejected(self):
        original_read = Path.read_bytes
        target = self.evidence / 'unity-80bc90.asm'
        def read(path):
            data = original_read(path)
            return b'\n'.join(line for line in data.split(b'\n') if not line.startswith(b'18080bd22:')) if path == target else data
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(ValueError, 'complete and contiguous'):
                self.review()

    def test_changed_argument_receiver_rejected(self):
        original_read = Path.read_bytes
        target = self.evidence / 'unity-c308c0.asm'
        def read(path):
            data = original_read(path)
            return data.replace(b'add\trbx, 0x190', b'add\trbx, 0x1498') if path == target else data
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(ValueError, 'Anchor differs'):
                self.review()


if __name__ == '__main__':
    unittest.main()
