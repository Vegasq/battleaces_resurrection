import unittest
from server.game_data import (GameDataError, canonical_gzip, decode_deck,
                              decode_identity, decompress_game_data)
from server.protobuf_wire import get_bytes, get_repeated_bytes, get_uint
from tests.synthetic import template


class MatchConstructionTests(unittest.TestCase):
    def setUp(self):
        self.template = template()
        self.roster = [{'slot': 0, 'player_id': 101, 'name': 'Alice'},
                       {'slot': 1, 'player_id': 202, 'name': 'Bob'}]

    def test_seed_identity_and_decks_are_server_owned(self):
        match = self.template.build_match(self.roster, self.template.default_decks, seed=999)
        self.assertEqual(get_uint(match.game_config, 38), 999)
        self.assertEqual(decompress_game_data(match.gzip_game_data), match.raw_game_data)
        for slot, army in enumerate(get_repeated_bytes(match.game_config, 2)):
            identity = decode_identity(get_repeated_bytes(army, 2)[0])
            self.assertEqual(identity['player_id'], self.roster[slot]['player_id'])
            self.assertEqual(decode_deck(get_bytes(army, 3))['units'], tuple(range(100, 108)))

    def test_invalid_decks_rejected(self):
        good = list(self.template.default_decks[0])
        cases = [good[:-1], good + [999], [True] + good[1:], [999] + good[1:],
                 [good[1], good[0]] + good[2:], [good[0]] * 8]
        for deck in cases:
            with self.subTest(deck=deck), self.assertRaises(GameDataError):
                self.template.validate_deck(deck)

    def test_roster_duplicate_ids_and_invalid_slots_rejected(self):
        for changed in ({'slot': 0}, {'player_id': 101}, {'army_id': 0}):
            roster = [self.roster[0], dict(self.roster[1], **changed)]
            with self.assertRaises(GameDataError):
                self.template.build_match(roster, self.template.default_decks)

    def test_gzip_truncated_concatenated_and_oversized_data_rejected(self):
        good = canonical_gzip(b'synthetic')
        for invalid in (good[:-1], good + good, b'not gzip'):
            with self.assertRaises(GameDataError):
                decompress_game_data(invalid)

    def test_restricting_catalog_cannot_invalidate_existing_default(self):
        before = self.template.allowed_entity_ids
        with self.assertRaises(GameDataError):
            self.template.set_allowed_entity_ids(before - {100})
        self.assertEqual(self.template.allowed_entity_ids, before)
