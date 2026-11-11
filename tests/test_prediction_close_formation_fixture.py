"""Authored protobuf contracts only; no native/client or shipped assets needed."""
import hashlib
import math
from pathlib import Path
import unittest

from server.game_data import GameDataError, GameTemplate, decompress_game_data
from server.cosmetics import CosmeticCatalog
from server.protobuf_wire import (field_bytes, field_packed_uint, field_uint, get_bytes,
                                  get_repeated_bytes, get_uint, parse_fields, replace_fields,
                                  signed64)
from tests import test_prediction_actor_fixture as authored
from tests.test_cosmetics import catalog_fixture as cosmetic_fixture, encode
from tests.synthetic import template
from tools import prediction_actor_fixture as previous
from tools import prediction_close_formation_fixture as fixture


Q32 = 2**32


class CloseFormationFixtureTests(unittest.TestCase):
    def setUp(self):
        self.source = authored.ActorFixtureTests()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.assets, self.roster = self.source.assets, self.source.roster
        definitions = []
        for entity in get_repeated_bytes(self.source.base.game_config, 1):
            if get_uint(entity, 1) == 1:
                entity = replace_fields(entity, {
                    2: [field_uint(2, fixture.UNIT_RADIUS_RAW)],
                    8: [field_bytes(8, field_uint(1, 4) + field_uint(2, 600*Q32) + field_uint(3, 123)),
                        field_bytes(8, field_uint(2, 27058294784))]})
            definitions.append(entity)
        global_config = replace_fields(self.source.base.global_config, {4: [field_uint(4, 2147483640)]})
        config = replace_fields(self.source.base.game_config, {
            1: [field_bytes(1, entity) for entity in definitions], 3: [field_bytes(3, global_config)]})
        self.base = self.source.load(replace_fields(self.source.base.raw_game_data,
            {1: [field_bytes(1, config)]}) + field_uint(9, 987))
        self.decks = {slot: (1, *range(101, 108)) for slot in (0, 1)}

    def changed(self, *, definitions=None, global_config=None, initial=None):
        changes = {}
        if definitions is not None:
            changes[1] = [field_bytes(1, entity) for entity in definitions]
        if global_config is not None:
            changes[3] = [field_bytes(3, global_config)]
        config = replace_fields(self.base.game_config, changes)
        changes = {1: [field_bytes(1, config)]}
        if initial is not None:
            changes[2] = [field_bytes(2, action) for action in initial]
        return self.source.load(replace_fields(self.base.raw_game_data, changes))

    def test_only_five_initial_actions_are_appended_all_other_wire_bytes_preserved(self):
        before = self.base.raw_game_data
        result = fixture.make_template(self.base, self.assets)
        self.assertIsInstance(result, fixture.CloseFormationFixtureTemplate)
        self.assertEqual(result.game_config, self.base.game_config)
        self.assertEqual(result.global_config, self.base.global_config)
        self.assertEqual([field.raw for field in parse_fields(result.raw_game_data) if field.number != 2],
                         [field.raw for field in parse_fields(before) if field.number != 2])
        initial = get_repeated_bytes(result.raw_game_data, 2)
        self.assertEqual(len(initial), 15)
        self.assertEqual(initial[:10], get_repeated_bytes(before, 2))
        self.assertEqual(self.base.raw_game_data, before)
        self.assertEqual(result.default_decks, self.base.default_decks)
        self.assertEqual(result.allowed_entity_ids, self.base.allowed_entity_ids)

    def test_actual_initial_order_positions_armies_and_original_rotations(self):
        result = fixture.make_template(self.base, self.assets)
        appended = get_repeated_bytes(result.raw_game_data, 2)[10:]
        expected = [(0, (60., 0., 60.)), (1, (-81., 0., -61.)), (1, (-81., 0., -59.)),
                    (1, (-79., 0., -61.)), (1, (-79., 0., -59.))]
        for action, (army, point) in zip(appended, expected):
            entity = get_bytes(action, 2, required=True)
            self.assertEqual((get_uint(entity, 1), get_uint(entity, 2)), (1, army))
            self.assertEqual(previous._position(get_bytes(entity, 3, required=True)), point)
            self.assertEqual(any(field.number == 2 for field in parse_fields(entity)), bool(army))
            rotation = get_bytes(entity, 4, required=True)
            self.assertEqual([field.number for field in parse_fields(rotation)], [2, 4])
            self.assertEqual(signed64(get_uint(rotation, 2)), int((1 if army == 0 else -1)*math.sqrt(.5)*Q32))
            self.assertEqual(get_uint(rotation, 4), int(math.sqrt(.5)*Q32))

    def test_normal_builder_still_owns_seed_roster_decks_compression_and_hashes(self):
        result = fixture.make_template(self.base, self.assets)
        before = (list(map(dict, self.roster)), dict(self.decks))
        match = result.build_match(self.roster, self.decks, 999, 'authored-close', game_mode=1)
        ordinary = self.base.build_match(self.roster, self.decks, fixture.SEED, 'authored-close', game_mode=1)
        self.assertEqual(match.seed, 20261113)
        self.assertEqual(match.game_config, ordinary.game_config)
        self.assertEqual(dict(match.decks_by_slot), self.decks)
        self.assertEqual(match.identities_by_slot, ordinary.identities_by_slot)
        self.assertEqual([player.name for player in match.roster], [player['name'] for player in self.roster])
        self.assertEqual(get_repeated_bytes(match.raw_game_data, 2), get_repeated_bytes(result.raw_game_data, 2))
        self.assertEqual(decompress_game_data(match.gzip_game_data), match.raw_game_data)
        self.assertEqual(hashlib.sha256(match.raw_game_data).hexdigest(), match.raw_sha256)
        self.assertEqual(hashlib.sha256(match.gzip_game_data).hexdigest(), match.sha256)
        self.assertEqual((self.roster, self.decks), before)

    def test_frozen_cosmetics_and_entitlement_bytes_match_the_ordinary_builder(self):
        book = CosmeticCatalog.from_bytes(encode(cosmetic_fixture()))
        selected = {slot: book.normalize_local() for slot in (0, 1)}
        kwargs = dict(human_cosmetics=selected, cosmetic_catalog=book)
        result = fixture.make_template(self.base, self.assets)
        match = result.build_match(self.roster, self.decks, game_name='authored-appearance', **kwargs)
        ordinary = self.base.build_match(self.roster, self.decks, fixture.SEED, 'authored-appearance', **kwargs)
        self.assertEqual(match.game_config, ordinary.game_config)
        self.assertEqual(match.cosmetics_by_slot, ordinary.cosmetics_by_slot)
        self.assertEqual(match.armies_by_slot, ordinary.armies_by_slot)
        self.assertEqual(match.deck_messages_by_slot, ordinary.deck_messages_by_slot)
        selected.clear()
        self.assertEqual(len(match.cosmetics_by_slot), 2)

    def test_composed_or_reboxed_transformed_input_refuses(self):
        variants = [fixture.make_template(self.base, self.assets), previous.make_template(self.base, self.assets),
                    previous.make_mobile_template(self.base, self.assets)]
        for prior in variants:
            with self.subTest(prior=type(prior).__name__), self.assertRaises(GameDataError):
                fixture.make_template(prior, self.assets)
            with self.subTest(reboxed=type(prior).__name__), self.assertRaises(GameDataError):
                fixture.make_template(self.source.load(prior.raw_game_data), self.assets)

    def test_changed_original_initial_list_and_wrong_topology_refuse(self):
        initial = get_repeated_bytes(self.base.raw_game_data, 2)
        for changed in (initial[:-1], [*initial, initial[-1]], [*initial[:5], initial[0], *initial[6:]]):
            with self.subTest(size=len(changed)), self.assertRaises(GameDataError):
                fixture.make_template(self.changed(initial=changed), self.assets)
        with self.assertRaises(GameDataError):
            fixture.make_template(template(2), self.assets)
        with self.assertRaises(GameDataError):
            fixture.make_template(object(), self.assets)

    def test_missing_or_changed_normal_properties_refuse_without_rewriting(self):
        for mode in ('radius', 'health', 'speed', 'duplicate-health', 'ability'):
            definitions = []
            for entity in get_repeated_bytes(self.base.game_config, 1):
                if get_uint(entity, 1) == 1:
                    attributes = list(get_repeated_bytes(entity, 8))
                    if mode == 'radius':
                        entity = replace_fields(entity, {2: [field_uint(2, Q32)]})
                    if mode in ('health', 'speed'):
                        number = 0 if mode == 'health' else 1
                        attributes[number] = replace_fields(attributes[number], {2: [field_uint(2, Q32)]})
                        entity = replace_fields(entity, {8: [field_bytes(8, attribute) for attribute in attributes]})
                    if mode == 'duplicate-health':
                        entity = replace_fields(entity, {8: [field_bytes(8, attribute) for attribute in (*attributes, attributes[0])]})
                    if mode == 'ability':
                        entity = replace_fields(entity, {7: [field_packed_uint(7, (14, 88))]})
                definitions.append(entity)
            with self.subTest(mode=mode), self.assertRaises(GameDataError):
                fixture.make_template(self.changed(definitions=definitions), self.assets)
        for number, value in ((4, 7*Q32), (27, 5*Q32), (29, 0)):
            changed = replace_fields(self.base.global_config, {number: [field_uint(number, value)]})
            with self.subTest(global_field=number), self.assertRaises(GameDataError):
                fixture.make_template(self.changed(global_config=changed), self.assets)

    def test_both_legal_chosen_decks_and_two_humans_are_required_not_forced(self):
        result = fixture.make_template(self.base, self.assets)
        for slot in (0, 1):
            chosen = dict(self.decks)
            chosen[slot] = self.base.default_decks[slot]
            with self.subTest(slot=slot), self.assertRaisesRegex(GameDataError, 'both human slots'):
                result.build_match(self.roster, chosen)
            self.assertNotIn(1, chosen[slot])
        for roster in ([self.roster[0], dict(self.roster[1], ai_profile_id=1)],
                       [dict(player, army_id=1-player['army_id']) for player in self.roster]):
            with self.assertRaisesRegex(GameDataError, 'two human slots'):
                result.build_match(roster, self.decks)
        for mode in (2, 4, 5):
            with self.subTest(mode=mode), self.assertRaisesRegex(GameDataError, 'Custom1v1'):
                result.build_match(self.roster, self.decks, game_mode=mode)

    def test_metadata_is_deeply_detached_and_marks_timings_as_planned(self):
        meta = fixture.metadata()
        self.assertEqual(meta['guest_ids'], [11, 12, 13, 14])
        self.assertEqual((meta['approach_canonical_frame'], meta['fresh_canonical_frame'], meta['remote_canonical_frame']), (181, 301, 321))
        self.assertEqual(meta['seed'], 20261113)
        self.assertEqual(meta['unit_radius_raw'], 3435973888)
        self.assertEqual(meta['observation_last_frame'], 360)
        self.assertTrue(meta['timings_are_planned_control'])
        self.assertFalse(meta['runtime_validated'])
        self.assertFalse(meta['collision_solver_qualified'])
        meta['initial_guests'][0][0] = 999
        meta['guest_ids'].clear()
        meta['fresh_unity_offset'][2] = 1
        fresh = fixture.metadata()
        self.assertEqual(fresh['initial_guests'][0], [-81., 0., -61.])
        self.assertEqual(fresh['guest_ids'], [11, 12, 13, 14])
        self.assertEqual(fresh['fresh_unity_offset'], [0., 0., 16.])
        with self.assertRaises(TypeError):
            fixture.METADATA['seed'] = 0

    def test_missing_asset_roots_refuse(self):
        with self.assertRaises(GameDataError):
            fixture.make_template(self.base, Path(self.assets)/'absent')


if __name__ == '__main__':
    unittest.main()
