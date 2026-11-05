"""Reject false static input/output bindings; no original native code executes."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import review_identity_config as gate


@unittest.skipUnless(os.environ.get('BA_IDENTITY_CONFIG_EVIDENCE'), 'retained evidence is opt-in')
class IdentityConfigEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.original = self.root.parent.parent / 'BattleAcesBeta_untouched'
        self.installed = self.root / 'local/r171g'
        self.evidence = Path(os.environ['BA_IDENTITY_CONFIG_EVIDENCE']).resolve()
        self.notification = self.root / 'local/privacy197-runtime-sink01/verification03.json'

    def review(self):
        return gate.review(self.original, self.installed, self.evidence, self.notification)

    def test_input_retention_with_activation_and_advertising_still_unknown(self):
        result = self.review()
        self.assertTrue(result['passed'])
        self.assertTrue(result['parsed_input_retained'])
        self.assertTrue(result['queued_callback_reads_current_token'])
        self.assertEqual(result['token_field'], 'Main+190')
        self.assertEqual(result['effective_change_field'], 'Main+1138')
        for name in ('entry_activation_resolved', 'input_transport_resolved', 'advertising_producer_resolved',
                     'runtime_observed', 'missing_member_clears_token', 'string_only_validation'):
            self.assertIs(result[name], False)

    def test_different_configuration_key_rejected(self):
        with patch.dict(gate.LITERALS, {0x1a2ad94: 'advertisingId'}):
            with self.assertRaisesRegex(ValueError, 'Configuration name differs'):
                self.review()

    def test_swapped_copy_destination_rejected(self):
        original_read = Path.read_bytes
        target = self.evidence / 'unity-ac4ad0.asm'
        def read(path):
            raw = original_read(path)
            return raw.replace(b'mov\trcx, r14', b'mov\trdx, r14') if path == target else raw
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(ValueError, 'Semantic anchor differs'):
                self.review()

    def test_missing_value_write_instruction_rejected(self):
        original_read = Path.read_bytes
        target = self.evidence / 'unity-c416b0.asm'
        def read(path):
            raw = original_read(path)
            return b'\n'.join(line for line in raw.split(b'\n') if not line.startswith(b'180c41791:')) if path == target else raw
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(ValueError, 'complete and contiguous'):
                self.review()


if __name__ == '__main__':
    unittest.main()
