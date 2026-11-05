"""Opt-in retained-original negative controls; never execute a native DLL."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import review_particle_rng as gate


@unittest.skipUnless(os.environ.get('BA_PARTICLE_RNG_EVIDENCE'), 'retained native evidence is opt-in')
class ParticleEvidenceControls(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.original = root.parent.parent / 'BattleAcesBeta_untouched/UnityPlayer.dll'
        self.installed = root / 'local/r171g/UnityPlayer.dll'
        self.evidence = Path(os.environ['BA_PARTICLE_RNG_EVIDENCE']).resolve()

    def review(self):
        return gate.review(self.original, self.installed, self.evidence)

    def test_retained_binding_and_scope(self):
        report = self.review()
        self.assertTrue(report['particle_auto_seed_consumer_bound'])
        self.assertEqual(len(report['roots']), 10)
        self.assertFalse(report['advertising_producer_resolved'])
        self.assertFalse(report['full_privacy_qualified'])
        self.assertFalse(report['all_owner_consumers_proved'])

    def test_wrong_named_registration_rejected(self):
        with patch.dict(gate.BINDINGS, {8: (0x2482e0, 'UnityEngine.ParticleSystem::set_randomSeed')}):
            with self.assertRaisesRegex(ValueError, 'Registered name differs'):
                self.review()

    def test_altered_dispatch_text_rejected(self):
        target = self.evidence / 'unity-fd4b10.asm'
        original_read = Path.read_bytes
        def read(path):
            data = original_read(path)
            return data.replace(b'mov\trdx, rsi', b'mov\trdx, rdi') if path == target else data
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(ValueError, 'Semantic anchor differs'):
                self.review()

    def test_missing_instruction_rejected(self):
        target = self.evidence / 'unity-d66880.asm'
        original_read = Path.read_bytes
        def read(path):
            data = original_read(path)
            return b'\n'.join(line for line in data.split(b'\n') if not line.startswith(b'180d66979:')) if path == target else data
        with patch.object(Path, 'read_bytes', read):
            with self.assertRaisesRegex(ValueError, 'complete and contiguous'):
                self.review()


if __name__ == '__main__':
    unittest.main()
