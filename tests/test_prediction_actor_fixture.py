"""Authored bootstrap controls; no proprietary assets or native code required."""
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from server.game_data import GameDataError, GameTemplate, decompress_game_data
from server.protobuf_wire import (field_bytes, field_packed_uint, field_uint,
                                  get_bytes, get_repeated_bytes, get_uint,
                                  parse_fields, replace_fields, signed64)
from tests.synthetic import template
from tools import prediction_actor_fixture as fixture


Q32 = 2**32


class ActorFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.assets = Path(temporary.name)
        (self.assets / 'descriptors').mkdir()
        original = template()
        core = field_uint(1, 3) + field_bytes(8, field_uint(1, 4) + field_uint(2, 900 * Q32))
        gunbot = field_uint(1, 1) + field_packed_uint(7, (12, 14, 88)) + field_uint(21, 1)
        global_config = (original.global_config + field_uint(4, Q32 // 2) + field_uint(22, 10 * Q32)
                         + field_uint(27, 6 * Q32) + field_uint(29, 21474836400))
        config = replace_fields(original.game_config, {
            1: [field_bytes(1, raw) for raw in (*get_repeated_bytes(original.game_config, 1), core, gunbot)],
            3: [field_bytes(3, global_config)],
        })
        initial = []
        for index in range(10):
            position = fixture._CORE_POSITION if index == 5 else (20.0, 0.0, 30.0)
            create = (field_uint(1, 3 if index in (0, 5) else 19)
                      + field_uint(2, index // 5) + field_bytes(3, fixture._position_bytes(position)))
            initial.append(field_bytes(2, create))
        raw = field_bytes(1, config) + b''.join(field_bytes(2, action) for action in initial)
        runtime = {'slot_flags': list(original.slot_flags), 'units': [
            dict(id=entity, menu_slot_flags=mask, release_deck_playable=True,
                 menu_entity_present=True, name=f'Authored {entity}')
            for entity, mask in [(1, 1), *zip(range(100, 108), original.slot_flags)]],
            'premade_decks': [dict(name='Starter', units=list(range(100, 108)))]}
        (self.assets / 'unit-catalog.json').write_text(json.dumps(runtime), encoding='utf-8')
        self.base = self.load(raw)
        self.roster = [dict(slot=s, army_id=s, player_id=s + 1, name=f'Authored {s}') for s in (0, 1)]
        self.decks = {0: (1, *range(101, 108)), 1: tuple(range(100, 108))}

    def load(self, raw):
        return GameTemplate(raw, catalog_path=self.assets / 'unit-catalog.json',
                            descriptors_path=self.assets / 'descriptors')

    def replace_config(self, changes):
        config = replace_fields(self.base.game_config, changes)
        return self.load(replace_fields(self.base.raw_game_data, {1: [field_bytes(1, config)]}))

    def test_transforms_only_separate_fixture_and_preserves_startup(self):
        before = (self.base.raw_game_data, dict(self.base.default_decks), self.base.allowed_entity_ids)
        result = fixture.make_template(self.base, self.assets)
        self.assertIsInstance(result, fixture.ActorFixtureTemplate)
        self.assertEqual(before, (self.base.raw_game_data, self.base.default_decks, self.base.allowed_entity_ids))
        self.assertEqual(result.default_decks, self.base.default_decks)
        self.assertEqual(result.allowed_entity_ids, self.base.allowed_entity_ids)
        self.assertEqual(get_uint(result.global_config, 4), 7 * Q32)
        self.assertFalse(any(field.number == 22 for field in parse_fields(result.global_config)))
        for number in (24, 27, 29):
            self.assertEqual([field.raw for field in parse_fields(result.global_config) if field.number == number],
                             [field.raw for field in parse_fields(self.base.global_config) if field.number == number])
        definitions = get_repeated_bytes(result.game_config, 1)
        core = next(raw for raw in definitions if get_uint(raw, 1) == 3)
        self.assertEqual(get_uint(get_repeated_bytes(core, 8)[0], 2), 100 * Q32)
        for original, transformed in zip(get_repeated_bytes(self.base.game_config, 1), definitions):
            if get_uint(original, 1) != 3:
                self.assertEqual(original, transformed)

    def test_append_preserves_initial_actions_and_exact_position_rotation(self):
        result = fixture.make_template(self.base, self.assets)
        actions = get_repeated_bytes(result.raw_game_data, 2)
        self.assertEqual(actions[:-1], get_repeated_bytes(self.base.raw_game_data, 2))
        self.assertEqual(len(actions), 11)
        create = get_bytes(actions[-1], 2)
        self.assertEqual(get_uint(create, 1), 1)
        self.assertFalse(any(field.number == 2 for field in parse_fields(create)))
        self.assertEqual(fixture._position(get_bytes(create, 3)), (-99.77999877929688, 0.0, -80.8499984741211))
        rotation = get_bytes(create, 4)
        self.assertEqual(signed64(get_uint(rotation, 2)), int(-math.sqrt(.5) * Q32))
        self.assertEqual(get_uint(rotation, 4), int(math.sqrt(.5) * Q32))

    def test_build_match_freezes_only_fixture_seed_without_forcing_either_deck(self):
        result = fixture.make_template(self.base, self.assets)
        decks_before = dict(self.decks)
        # DedicatedServer supplies its seed as a positional argument.
        match = result.build_match(self.roster, self.decks, 987654321, 'authored-fixture', game_mode=1)
        self.assertEqual(match.seed, 20261110)
        self.assertEqual(get_uint(match.game_config, 38), match.seed)
        self.assertEqual(dict(match.decks_by_slot), decks_before)
        self.assertEqual(self.decks, decks_before)
        self.assertEqual(self.base.build_match(self.roster, self.decks, 123).seed, 123)
        self.assertEqual(decompress_game_data(match.gzip_game_data), match.raw_game_data)
        self.assertEqual(get_bytes(match.raw_game_data, 1), match.game_config)
        self.assertEqual(hashlib.sha256(match.raw_game_data).hexdigest(), match.raw_sha256)
        self.assertEqual(hashlib.sha256(match.gzip_game_data).hexdigest(), match.sha256)
        self.assertEqual(get_repeated_bytes(match.raw_game_data, 2), get_repeated_bytes(result.raw_game_data, 2))

    def test_missing_gunbot_refuses_instead_of_changing_deck(self):
        result = fixture.make_template(self.base, self.assets)
        original = dict(self.base.default_decks)
        with self.assertRaisesRegex(GameDataError, 'slot0.*Gunbot1'):
            result.build_match(self.roster, original)
        self.assertEqual(original, self.base.default_decks)

    def test_metadata_is_fixed_and_returned_description_cannot_mutate_it(self):
        description = fixture.metadata()
        self.assertEqual(description['victim_slot'], 1)
        self.assertEqual(description['victim_core_id'], 5)
        self.assertEqual(description['attacker_slot'], 0)
        self.assertEqual(description['attacker_id'], 10)
        self.assertEqual(description['selection_frame'], 130)
        self.assertEqual(description['escape_physical_frame'], 152)
        self.assertEqual(description['expected_canonical_frame'], 153)
        self.assertEqual(description['safe_canonical_frames'], [152, 153, 154])
        self.assertEqual(description['baseline_death_frame'], 155)
        description['target'][0] = 0
        self.assertEqual(fixture.metadata()['target'][0], -69.77999877929688)
        with self.assertRaises(TypeError):
            fixture.METADATA['seed'] = 0

    def test_unsupported_topology_repeated_application_and_roster_refuse(self):
        result = fixture.make_template(self.base, self.assets)
        with self.assertRaisesRegex(GameDataError, 'already transformed'):
            fixture.make_template(result, self.assets)
        with self.assertRaisesRegex(GameDataError, 'Custom1v1'):
            result.build_match(self.roster, self.decks, game_mode=4)
        swapped = [dict(player, army_id=1-player['army_id']) for player in self.roster]
        ai = [dict(self.roster[0], ai_profile_id=1), self.roster[1]]
        for roster in (swapped, ai):
            with self.subTest(roster=roster), self.assertRaisesRegex(GameDataError, 'two human slots'):
                result.build_match(roster, self.decks)
        with self.assertRaisesRegex(GameDataError, 'two-army map'):
            fixture.make_template(template(2), self.assets)

    def test_changed_source_startup_or_initial_entities_refuse(self):
        global_config = replace_fields(self.base.global_config, {27: [field_uint(27, 0)]})
        changed = self.replace_config({3: [field_bytes(3, global_config)]})
        with self.assertRaisesRegex(GameDataError, 'startup differs'):
            fixture.make_template(changed, self.assets)
        initial = get_repeated_bytes(self.base.raw_game_data, 2)
        for actions in (initial[:-1], (*initial, initial[-1]), (*initial[:5], initial[0], *initial[6:])):
            changed = self.load(replace_fields(self.base.raw_game_data, {
                2: [field_bytes(2, action) for action in actions]}))
            with self.subTest(count=len(actions)), self.assertRaises(GameDataError):
                fixture.make_template(changed, self.assets)

    def test_missing_core_health_or_movement_metadata_refuse(self):
        definitions = get_repeated_bytes(self.base.game_config, 1)
        for missing in ('health', 'movement'):
            changed = []
            for entity in definitions:
                if missing == 'health' and get_uint(entity, 1) == 3:
                    entity = replace_fields(entity, {8: []})
                if missing == 'movement' and get_uint(entity, 1) == 1:
                    entity = replace_fields(entity, {7: [field_packed_uint(7, (14, 88))]})
                changed.append(entity)
            altered = self.replace_config({1: [field_bytes(1, entity) for entity in changed]})
            with self.subTest(missing=missing), self.assertRaises(GameDataError):
                fixture.make_template(altered, self.assets)


if __name__ == '__main__':
    unittest.main()
