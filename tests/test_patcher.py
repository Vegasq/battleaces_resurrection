import unittest
from client_patch.patcher.patch_client import build_patch, install


class PatcherSafetyTests(unittest.TestCase):
    def test_unsupported_original_rejected_before_pe_processing(self):
        for original in (b'', b'MZ' + bytes(256)):
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                build_patch(original)

    def test_named_recovery_copy_cannot_be_patched(self):
        with self.assertRaisesRegex(ValueError, 'read-only'):
            install('BattleAcesBeta_untouched')
