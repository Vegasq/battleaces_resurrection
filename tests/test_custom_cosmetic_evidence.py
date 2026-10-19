"""Authored native-log fixtures: match identity must survive abort/rematch gaps."""
import json
import unittest

from server.cosmetics import CosmeticCatalog
from tests.test_cosmetics import catalog_fixture, encode
from tools.verify_custom_match import remote_cosmetic_snapshots


class CustomCosmeticEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.book = CosmeticCatalog.from_bytes(encode(catalog_fixture()))
        self.selection = self.book.normalize_local()
        self.profile = 'cosmeticstest_authored'

    def row(self, match, army=0, *, profile=None, portrait=None):
        value = dict(schema=1, build=37822, profile=profile or self.profile,
                     catalog_sha256=self.book.sha256, slots=self.selection.slots)
        return (f'[1] REMOTE COSMETICS SimPlayer passed: match={match} army={army} '
                f'portrait={self.selection.portrait if portrait is None else portrait} banner={self.selection.banner} '
                'slots=17 orderedDeck=1 completeMap=1\n'
                '[2] REMOTE COSMETICS frozen snapshot: '+json.dumps(value)+'\n')

    def test_completed_matches_keep_ids_when_aborted_assignment_has_no_native_snapshot(self):
        ids = ['b'*32, 'c'*32]
        rows = remote_cosmetic_snapshots('loading assignment a aborted\n'+''.join(self.row(key) for key in ids),
                                        self.book, self.profile, 0)
        self.assertEqual(rows, [(key, self.selection) for key in ids])

    def test_rejects_missing_duplicate_or_wrong_identity_readbacks(self):
        good = self.row('b'*32)
        bad = (good.splitlines()[0], '\n'.join(good.splitlines()[1:]), good+good,
               self.row('b'*32, army=1), self.row('b'*32, profile='cosmeticstest_other'),
               self.row('b'*32, portrait=self.selection.portrait+1))
        for log in bad:
            with self.subTest(log=log[:100]), self.assertRaises(AssertionError):
                remote_cosmetic_snapshots(log, self.book, self.profile, 0)


if __name__ == '__main__': unittest.main()
