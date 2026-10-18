"""Authored fixtures for selection, team topology and frozen bot modifiers."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
import uuid

from server.bot_catalog import BotCatalog, Q32, cosmetic_keys
from server.game_data import GameDataError, GameTemplate, decode_frame, encode_deck, encode_frame, encode_player_input
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_bytes, get_repeated_bytes, get_uint, replace_fields
from tests.synthetic import template


def catalog_fixture():
    """Invented names, unit/cosmetic/profile IDs; no installed asset rows."""
    message = encode_deck(tuple(range(100, 108)))
    random = dict(kind=2, reference=201, name='', portrait=0, banner=0, deck_hex=message.hex())
    character = dict(kind=1, reference=301, name='Fixture Character A', portrait=901, banner=902,
                     deck_hex=(message + field_bytes(3, field_packed_uint(3, (901, 902, 903)))).hex())
    profiles = [dict(profile=501, mode=1, decks=[random]), dict(profile=503, mode=1, decks=[random]),
                dict(profile=502, mode=2, decks=[random]),
                dict(profile=504, mode=4, decks=[dict(random, kind=0, reference=0)]),
                dict(profile=505, mode=5, decks=[character, dict(character, reference=302, name='Fixture Character B')])]
    modes = [dict(mode=mode, opponents=[dict(profile=profile, weight=1)], teammates=[])
             for mode, profile in ((1, 501), (2, 502), (4, 504), (5, 505))]
    modes[0]['opponents'] = [dict(profile=501, weight=2), dict(profile=503, weight=1)]
    modes[1]['teammates'] = [dict(profile=502, weight=1)]
    return dict(schema=1, build=37822, names_language='en', character_names_language='exporting_client_locale',
                names=['Fixture Alpha', 'Fixture Beta', '', 'Invalid\nName'], portraits=[901], banners=[902],
                cosmetic_ids=[901, 902, 903], profiles=profiles, modes=modes,
                strengths=[dict(profile=17, resource_q=Q32-123, damage_q=Q32-456, health_q=Q32-789),
                           dict(profile=18, resource_q=Q32, damage_q=Q32, health_q=Q32),
                           dict(profile=19, resource_q=Q32, damage_q=Q32+123, health_q=Q32+456)])


class BotCatalogTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(__file__).resolve().parents[1]/'local/test-bot-catalog'
        self.directory = self.base/uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.data = catalog_fixture()
        self.write()

    def tearDown(self):
        target = self.directory.resolve()
        self.assertEqual(target.parent, self.base.resolve())
        self.assertEqual(len(target.name), 32)
        shutil.rmtree(target)

    def write(self):
        (self.directory/'bot-catalog.json').write_text(json.dumps(self.data), encoding='utf-8')

    def load(self):
        return BotCatalog(self.directory, template=template())

    def test_weighted_compatible_profile_random_name_and_independent_strength(self):
        book = self.load()
        first = book.choose(1, randbelow=lambda bound: 0)
        last = book.choose(1, randbelow=lambda bound: bound-1)
        self.assertEqual((first.profile, first.name, first.difficulty), (501, 'Fixture Alpha', 'easy'))
        self.assertEqual((last.profile, last.name, last.difficulty), (503, 'Fixture Beta', 'hard'))
        self.assertIn(first.deck, book.profiles[first.profile][1])
        self.assertEqual(cosmetic_keys(first.deck_message, book.cosmetic_ids), (901, 902))
        selected = book.choose(1, excluded_names=[first.name], difficulty='normal', randbelow=lambda bound: 0)
        self.assertEqual(selected.name, 'Fixture Beta')
        self.assertEqual(selected.strength, (Q32, Q32, Q32))

    def test_mode5_character_appearance_and_explicit_team_ally_policy(self):
        book = self.load()
        enemy = book.choose(5, difficulty='normal', randbelow=lambda bound: 0)
        self.assertEqual((enemy.profile, enemy.source_mode, enemy.name), (505, 5, 'Fixture Character A'))
        self.assertEqual(enemy.deck_message, enemy.deck.message)
        self.assertEqual(cosmetic_keys(enemy.deck_message, book.cosmetic_ids), (901, 902, 903))
        other = book.choose(5, excluded_names=[enemy.name], randbelow=lambda bound: 0)
        self.assertEqual(other.name, 'Fixture Character B')
        ally = book.choose(5, role='teammates', randbelow=lambda bound: 0)
        self.assertEqual((ally.profile, ally.source_mode), (502, 2))
        with self.assertRaisesRegex(ValueError, 'no distinct character'):
            book.choose(5, excluded_names=[enemy.name, other.name])

    def test_rule_mode_and_enable_must_match_catalog(self):
        entries = {p['profile']: dict(enabled=True, mode=p['mode']) for p in self.data['profiles']}
        rules = SimpleNamespace(entries=entries)
        BotCatalog(self.directory, rules=rules)
        entries[501]['enabled'] = False
        with self.assertRaisesRegex(ValueError, 'rule profile mismatch'):
            BotCatalog(self.directory, rules=rules)

    def test_malformed_export_is_rejected_before_selection(self):
        pristine = copy.deepcopy(self.data)
        mutations = [
            lambda d: d['profiles'][0]['decks'][0].update(deck_hex='00'),
            lambda d: d['profiles'][0]['decks'][0].update(deck_hex=encode_deck((100,)*8).hex()),
            lambda d: d['profiles'][0]['decks'][0].update(kind=True),
            lambda d: d['modes'][0]['opponents'][0].update(weight=0),
            lambda d: d['modes'][0]['opponents'][0].update(profile=999),
            lambda d: d['strengths'][1].update(resource_q=Q32+1),
            lambda d: d['profiles'][-1]['decks'][0].update(portrait=999),
            lambda d: d['cosmetic_ids'].remove(903),
        ]
        for mutate in mutations:
            self.data = copy.deepcopy(pristine); mutate(self.data); self.write()
            with self.subTest(mutation=mutate), self.assertRaises(ValueError): self.load()
        (self.directory/'bot-catalog.json').write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.load()

    def test_cosmetic_field3_cannot_be_replaced_with_field2(self):
        bad = encode_deck(tuple(range(100, 108))) + field_bytes(3, field_packed_uint(2, (901, 902)))
        with self.assertRaisesRegex(ValueError, 'unsupported bot cosmetic'):
            cosmetic_keys(bad, frozenset((901, 902)))

    def team_choices(self):
        book = self.load()
        first = book.choose(5, difficulty='easy', randbelow=lambda bound: 0)
        ally = book.choose(5, role='teammates', difficulty='normal', randbelow=lambda bound: 0)
        other = book.choose(5, excluded_names=[first.name], difficulty='hard', randbelow=lambda bound: 0)
        return {1: first, 2: ally, 3: other}

    def team_match(self, source=None, choices=None):
        source = source or template(5)
        choices = self.team_choices() if choices is None else choices
        roster = [dict(slot=slot, player_id=1000+slot, army_id=slot,
                       name=choices[slot].name if slot in choices else 'Fixture Human',
                       ai_profile_id=choices[slot].profile if slot in choices else 0) for slot in range(4)]
        return source.build_match(roster, source.default_decks, seed=77, game_mode=5, bot_choices=choices)

    def test_team_uses_one_config_with_frozen_identity_decks_cosmetics_and_alliances(self):
        source, choices = template(2), self.team_choices()
        match = self.team_match(source, choices)
        self.assertEqual(get_uint(match.game_config, 36), 5)
        self.assertEqual([get_uint(a, 4) for a in get_repeated_bytes(match.game_config, 2)], [0, 1, 0, 1])
        for slot, bot in choices.items():
            self.assertEqual(match.deck_messages_by_slot[slot], bot.deck_message)
            self.assertEqual(get_uint(match.armies_by_slot[slot], 5), bot.banner)
            self.assertEqual(get_uint(match.armies_by_slot[slot], 6), bot.portrait)
            self.assertEqual(match.roster[slot].name, bot.name)
        with self.assertRaisesRegex(GameDataError, 'frozen bot identity'):
            stale = dict(choices)
            stale[1] = replace(choices[1], source_mode=1)
            self.team_match(source, stale)

    def test_strength_composes_q32_exactly_preserves_human_and_existing_buffs(self):
        source = template(5)
        baseline = Q32+3
        original = {}
        for army, data in source.armies.items():
            modifiers = field_uint(1, baseline) + field_bytes(2, field_uint(1, 100+army))
            original[army] = modifiers
            source.armies[army] = replace_fields(data, {7: [field_bytes(7, modifiers)]})
        source.game_config += field_bytes(5, field_uint(1, 200))
        choices = self.team_choices()
        match = self.team_match(source, choices)
        self.assertEqual(get_bytes(match.armies_by_slot[0], 7), original[0])
        self.assertEqual(get_bytes(match.armies_by_slot[2], 7), original[2])
        keys = {200}
        for army, data in match.armies_by_slot.items():
            modifiers = get_bytes(data, 7)
            buffs = get_repeated_bytes(modifiers, 2)
            self.assertEqual(buffs[0], get_repeated_bytes(original[army], 2)[0])
            for buff in buffs:
                key = get_uint(buff, 1); self.assertNotIn(key, keys); keys.add(key)
            if army in (1, 3):
                strength = choices[army].strength
                self.assertEqual(get_uint(modifiers, 1), (baseline*strength[0]) >> 32)
                attributes = get_repeated_bytes(buffs[-1], 2)
                self.assertEqual([get_uint(a, 1) for a in attributes], [1, 1])
                self.assertEqual([(get_uint(get_bytes(a, 2), 1), get_uint(get_bytes(a, 2), 2)) for a in attributes],
                                 [(1, strength[1]), (4, strength[2])])


class TeamFrameTests(unittest.TestCase):
    def test_four_inputs_keep_canonical_order_and_reject_partial_topology(self):
        source = template(2)
        match = source.build_match([dict(slot=i) for i in range(4)], source.default_decks, seed=1)
        bodies = {slot: encode_player_input(match.identities_by_slot[slot], [field_bytes(5, field_bytes(1, b''))])
                  for slot in reversed(range(4))}
        self.assertEqual(decode_frame(encode_frame(0, bodies))['players'], tuple(bodies[i] for i in range(4)))
        for bad in ({0: b'', 1: b'', 2: b''}, {0: b'', 1: b'', 2: b'', 4: b''}):
            with self.assertRaises(GameDataError): encode_frame(0, bad)

    def test_mode_and_alliance_mismatch_cannot_construct_a_team_template(self):
        source = template(2)
        config = replace_fields(source.game_config, {36: [field_uint(36, 1)]})
        with self.assertRaisesRegex(GameDataError, 'army count'):
            GameTemplate(field_bytes(1, config), catalog_path=None)
        armies = [replace_fields(a, {4: [field_uint(4, i)]}) for i, a in enumerate(source.armies.values())]
        config = replace_fields(source.game_config, {2: [field_bytes(2, a) for a in armies]})
        with self.assertRaisesRegex(GameDataError, 'alliance topology'):
            GameTemplate(field_bytes(1, config), catalog_path=None)
