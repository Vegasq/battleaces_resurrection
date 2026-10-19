"""Full server profile persistence using authored unit/cosmetic catalogs only."""
import copy
from dataclasses import FrozenInstanceError, replace
import json
import unittest
from unittest import mock

from server.cosmetics import CosmeticCatalog
from server.profiles import ProfileStore, parse_profile_state, profile_bytes
from tests.synthetic import template
from tests.test_cosmetics import catalog_fixture, encode
from tests.test_credentials import private_test_folder, remove_test_folder


class CosmeticProfileTests(unittest.TestCase):
    def setUp(self):
        self.folder = private_test_folder('cosmetic-profiles-')
        self.template = template()
        self.catalog = CosmeticCatalog.from_bytes(encode(catalog_fixture()))
        self.store = ProfileStore(self.folder, self.template, catalog=self.catalog)
        pairs = list(self.catalog.normalize_local().slots)
        # Include slots beyond the original twelve-field loadout, and a swap.
        for index in (0, 4, 12, 13): pairs[index] = (pairs[index][0], pairs[index][1]+10000)
        left, right = pairs[8], pairs[11]
        pairs[8], pairs[11] = (left[0], right[1]), (right[0], left[1])
        self.selection = self.catalog.validate_selection(pairs)
        self.deck = self.template.default_decks[0]

    def tearDown(self): remove_test_folder(self.folder)

    def test_full_map_and_deck_survive_restart_and_legacy_deck_only_updates(self):
        self.store.save('player_a', self.deck, cosmetics=self.selection)
        state = ProfileStore(self.folder, self.template, catalog=self.catalog).load_state('player_a', [])
        self.assertEqual(state.cosmetics, self.selection)
        self.assertEqual(state.deck, self.deck)
        self.assertEqual(len(state.cosmetics.slots), 17)
        with self.assertRaises(FrozenInstanceError): state.deck = ()
        self.store.save('player_a', self.template.default_decks[1])
        self.assertEqual(self.store.load_state('player_a', []).cosmetics, self.selection)
        self.store.save('player_b', self.deck)
        self.assertEqual(self.store.load_state('player_b', []).cosmetics, self.catalog.normalize_local())
        self.assertEqual(self.store.load_state('player_a', []).cosmetics, self.selection)
        saved = json.loads((self.folder/'player_a.json').read_bytes())
        self.assertEqual(saved['schema'], 2)
        self.assertEqual(saved['cosmetics']['slots'], [list(pair) for pair in self.selection.slots])

    def test_legacy_profile_loads_defaults_without_rewrite_then_migrates_on_save(self):
        old = ProfileStore(self.folder, self.template)
        old.save('legacy', self.deck)
        before = (self.folder/'legacy.json').read_bytes()
        state = self.store.load_state('legacy', [])
        self.assertEqual(state.cosmetics, self.catalog.normalize_local())
        self.assertEqual((self.folder/'legacy.json').read_bytes(), before)
        self.store.save('legacy', self.deck)
        self.assertEqual(json.loads((self.folder/'legacy.json').read_bytes())['schema'], 2)
        with self.assertRaisesRegex(ValueError, 'catalog required'): old.load('legacy', [])
        with self.assertRaises(ValueError): old.save('legacy', self.deck)

    def test_invalid_complete_selection_never_replaces_the_saved_record(self):
        self.store.save('player_a', self.deck, cosmetics=self.selection)
        before = (self.folder/'player_a.json').read_bytes()
        cases = [self.selection.slots[:-1], [(slot, 0) for slot, item in self.selection.slots],
                 replace(self.selection, catalog_sha256='0'*64)]
        duplicate = list(self.selection.slots);duplicate[1] = (duplicate[1][0], duplicate[0][1]);cases.append(duplicate)
        wrong = list(self.selection.slots);wrong[0] = (wrong[0][0], 60002);cases.append(wrong)
        for selection in cases:
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.store.save('player_a', self.deck, cosmetics=selection)
            self.assertEqual((self.folder/'player_a.json').read_bytes(), before)
        self.assertEqual(list(self.folder.glob('*.tmp')), [])

    def test_forged_snapshot_derived_fields_are_rebuilt_from_validated_slots(self):
        forged = replace(self.selection, keys=(0xffffffff,), portrait=0xffffffff, banner=0xffffffff, entitlement=b'forged')
        self.store.save('player_a', self.deck, cosmetics=forged)
        self.assertEqual(self.store.load_state('player_a', []).cosmetics, self.selection)

    def test_corrupt_wrong_catalog_or_duplicate_slot_file_is_retained_on_read_and_save(self):
        good = json.loads(profile_bytes('player_a', self.deck, self.template, catalog=self.catalog, cosmetics=self.selection))
        mutations = []
        bad = copy.deepcopy(good);bad['cosmetics']['catalog_sha256'] = '0'*64;mutations.append(bad)
        bad = copy.deepcopy(good);bad['cosmetics']['slots'][1][0] = bad['cosmetics']['slots'][0][0];mutations.append(bad)
        bad = copy.deepcopy(good);bad['cosmetics']['slots'].pop();mutations.append(bad)
        bad = copy.deepcopy(good);bad['cosmetics']['unknown'] = 1;mutations.append(bad)
        bad = copy.deepcopy(good);bad['schema'] = True;mutations.append(bad)
        bad = copy.deepcopy(good);bad['cosmetics']['slots'][0][1] = True;mutations.append(bad)
        for value in mutations:
            raw = json.dumps(value).encode();(self.folder/'player_a.json').write_bytes(raw)
            for operation in (lambda: self.store.load_state('player_a', []),
                              lambda: self.store.save('player_a', self.deck),
                              lambda: self.store.save('player_a', self.deck, cosmetics=self.selection)):
                with self.assertRaises(ValueError): operation()
                self.assertEqual((self.folder/'player_a.json').read_bytes(), raw)
        raw = profile_bytes('player_a', self.deck, self.template, catalog=self.catalog, cosmetics=self.selection)
        for bad in (raw[:-3], raw[:-2]+b',"schema":2}\n', b'x'*4097):
            with self.assertRaises(ValueError): parse_profile_state(bad, 'player_a', self.template, catalog=self.catalog)

    def test_failed_flush_or_replace_preserves_both_deck_and_cosmetics(self):
        self.store.save('player_a', self.deck, cosmetics=self.selection)
        previous = (self.folder/'player_a.json').read_bytes()
        for operation in ('fsync', 'replace'):
            with mock.patch('server.profiles.os.'+operation, side_effect=OSError('authored disk fault')):
                with self.assertRaises(OSError):
                    self.store.save('player_a', self.template.default_decks[1], cosmetics=self.catalog.normalize_local())
            self.assertEqual((self.folder/'player_a.json').read_bytes(), previous)
            self.assertEqual(list(self.folder.glob('*.tmp')), [])


if __name__ == '__main__': unittest.main()
