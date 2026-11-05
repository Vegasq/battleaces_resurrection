"""Evidence controls for map-loader ownership; never execute native code."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import review_map_loading as gate


@unittest.skipUnless(os.environ.get('BA_MAP_LOADING_EVIDENCE'), 'retained evidence is opt-in')
class MapLoadingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.original = self.root.parent.parent / 'BattleAcesBeta_untouched'
        self.installed = self.root / 'local/r171g'
        self.evidence = Path(os.environ['BA_MAP_LOADING_EVIDENCE']).resolve()

    def review(self):
        return gate.review(self.original, self.installed, self.evidence)

    def changed_evidence(self, transform, message):
        original_read = Path.read_bytes
        target = self.evidence / 'game-3dbb660.asm'
        def read(path):
            raw = original_read(path)
            return transform(raw) if path == target else raw
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(ValueError, message):
                self.review()

    def test_binding_does_not_claim_cancellation_or_runtime_recovery(self):
        result = self.review()
        self.assertTrue(result['passed'])
        self.assertEqual(result['instructions'], 953)
        self.assertEqual(len(result['bodies']), 4)
        self.assertEqual(result['dispose']['bytes'], 'c20000')
        self.assertIs(result['cancellation_proved'], False)
        self.assertIs(result['runtime_recovery_proved'], False)

    def test_missing_instruction_rejected(self):
        self.changed_evidence(
            lambda raw: b'\n'.join(line for line in raw.split(b'\n')
                                   if not line.startswith(b'183dbb6b2:')),
            'complete and contiguous')

    def test_changed_instruction_bytes_rejected(self):
        self.changed_evidence(
            lambda raw: raw.replace(b'183dbb6b2: 48 89 58 18', b'183dbb6b2: 48 89 58 20'),
            'differs from original bytes')

    def test_mislabelled_capture_rejected(self):
        self.changed_evidence(
            lambda raw: raw.replace(b'qword ptr [rax + 0x18], rbx',
                                    b'qword ptr [rax + 0x18], rsi'),
            'semantic anchor differs')


if __name__ == '__main__':
    unittest.main()
