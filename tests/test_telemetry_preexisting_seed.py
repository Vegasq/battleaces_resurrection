"""Owned prelaunch queue seeding and retention checks."""
from pathlib import Path
import tempfile
import unittest

from tools.telemetry_preexisting_seed import seed, snapshot


ROOT = Path(__file__).resolve().parents[1] / 'local'


class PreexistingSeedTests(unittest.TestCase):
    def test_new_owned_profile_only_and_identity_retained(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='privacy502-seed-test-') as directory:
            game=Path(directory)
            (game/'.battleaces-resurrection/profiles').mkdir(parents=True)
            root,before=seed(game,'nativestest_preexisting_test')
            self.assertEqual(snapshot(root),before)
            with self.assertRaisesRegex(ValueError,'new'):
                seed(game,'nativestest_preexisting_test')
            file=root/'Events/authored-event-120.event'
            file.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'bytes differ'):
                snapshot(root)


if __name__ == '__main__':
    unittest.main()
