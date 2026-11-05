"""Reject misleading scheduler evidence without executing the game."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import review_loading_scheduler as gate


@unittest.skipUnless(os.environ.get('BA_LOADING_SCHEDULER_EVIDENCE'), 'retained evidence is opt-in')
class LoadingSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.original = self.root.parent.parent/'BattleAcesBeta_untouched'
        self.installed = self.root/'local/r171g'
        self.evidence = Path(os.environ['BA_LOADING_SCHEDULER_EVIDENCE']).resolve()

    def review(self):
        return gate.review(self.original,self.installed,self.evidence)

    def test_owner_bound_without_scene_cancellation_claim(self):
        result = self.review()
        self.assertTrue(result['passed'])
        self.assertEqual(result['scheduler_owner'],'MEC.Timing.UpdateProcesses')
        self.assertEqual(sum(b['full_body'] for b in result['bodies']),6)
        self.assertEqual(result['instructions'],587)
        for key in ('scene_cancellation_proved','callback_suppression_proved','runtime_recovery_proved'):
            self.assertIs(result[key],False)

    def test_different_kill_overload_rejected(self):
        with patch.dict(gate.METHODS,{0xdb:('KillCoroutines',0x3303860,['tag'])}):
            with self.assertRaisesRegex(ValueError,'method overload binding differs'):
                self.review()

    def test_missing_array_store_rejected(self):
        read = Path.read_bytes
        target = self.evidence/'game-10110.asm'
        def changed(path):
            raw = read(path)
            return b'\n'.join(line for line in raw.split(b'\n')
                              if not line.startswith(b'18001012b:')) if path == target else raw
        with patch.object(Path,'read_bytes',changed):
            with self.assertRaisesRegex(ValueError,'complete and contiguous'):
                self.review()

    def test_non_null_array_argument_rejected(self):
        read = Path.read_bytes
        target = self.evidence/'game-330dcc0.asm'
        def changed(path):
            raw = read(path)
            return raw.replace(b'xor\tr8d, r8d',b'xor\tr9d, r9d') if path == target else raw
        with patch.object(Path,'read_bytes',changed):
            with self.assertRaisesRegex(ValueError,'semantic anchor differs'):
                self.review()


if __name__ == '__main__':
    unittest.main()
