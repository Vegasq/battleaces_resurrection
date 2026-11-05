"""Opt-in retained actual-game evidence controls; never launch a game."""
import copy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import verify_ads_game as game


@unittest.skipUnless(os.environ.get('BA_ADS_GAME'), 'Set BA_ADS_GAME to retained game182 evidence')
class AdsGameEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(os.environ['BA_ADS_GAME']).resolve()
        self.original = game.read

    def test_retained_game_and_natural_lifetime(self):
        result = game.review(self.folder)
        self.assertTrue(result['passed'])
        self.assertEqual(result['natural_exit'], 0)
        self.assertTrue(result['practice']['native_continue'])
        self.assertFalse(result['producer_resolved'])
        self.assertFalse(result['full_privacy_qualified'])

    def reject(self, filename, mutate):
        value = copy.deepcopy(self.original(self.folder, filename)); mutate(value)
        def read(folder, name):
            return value if name == filename else self.original(folder, name)
        with patch.object(game, 'read', side_effect=read), self.assertRaises((ValueError, AssertionError)):
            game.review(self.folder)

    def test_bad_owner_and_job_evidence_rejected(self):
        for mutate in (
            lambda r: r.update(passed=False),
            lambda r: r['launch'].update(forced_cleanup=True),
            lambda r: r['launch'].update(owned_process_reaped=False),
            lambda r: r['tracker']['final_accounting'].update(active=1),
            lambda r: r['tracker']['final_accounting'].update(total=10),
            lambda r: r['practice'].update(native_continue=False),
        ):
            with self.subTest(mutate=mutate): self.reject('verification.json', mutate)

    def test_provider_identity_loss_and_error_rejected(self):
        for mutate in (
            lambda r: r.update(isError=True),
            lambda r: r['structuredContent']['parameters'].update(session_id='foreign'),
            lambda r: r['structuredContent']['normalized_result'].update(pid=1),
            lambda r: r['structuredContent']['normalized_result'].update(messages_truncated=True),
            lambda r: r['structuredContent']['normalized_result']['messages'][-1].update(script_id='foreign'),
            lambda r: r['structuredContent']['normalized_result']['messages'].pop(),
            lambda r: r['structuredContent']['normalized_result']['messages'][0].update(type='error'),
        ):
            with self.subTest(mutate=mutate): self.reject('rea-final.json', mutate)

    def test_load_release_and_detach_evidence_rejected(self):
        self.reject('rea-load.json', lambda r: r['structuredContent']['normalized_result'].update(source_sha256='0'*64))
        self.reject('release.json', lambda r: r.update(pid=1))
        self.reject('rea-close.json', lambda r: r.update(isError=True))


if __name__ == '__main__': unittest.main()
