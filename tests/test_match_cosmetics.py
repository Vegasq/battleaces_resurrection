"""Synthetic frozen human loadouts, native wire fields and queue ownership."""
import json
from dataclasses import replace
import unittest

from server import community_protocol as c, protocol as p
from server.bot_catalog import BotCatalog
from server.cosmetics import CosmeticCatalog
from server.game_data import encode_deck, decode_deck
from server.protobuf_wire import get_bytes, get_uint
from tests.synthetic import template as synthetic_template
from tests.test_cosmetics import catalog_fixture as cosmetic_fixture, encode
from tests.test_bot_catalog import catalog_fixture as bot_fixture
from tests.test_dedicated_server import DedicatedFixture
from tests import test_community as community_tests, test_public_matchmaking as public_tests


def selections():
    book = CosmeticCatalog.from_bytes(encode(cosmetic_fixture()))
    pairs = list(book.normalize_local().slots)
    for index in (4, 5, 12, 13): pairs[index] = (pairs[index][0], pairs[index][1]+10000)
    a, b = pairs[8], pairs[11];pairs[8], pairs[11] = (a[0], b[1]), (b[0], a[1])
    return book, book.validate_selection(pairs)


def bot_data(book):
    data = bot_fixture();snapshot = book.normalize_local()
    data.update(cosmetic_ids=list(book.items), portraits=[snapshot.portrait], banners=[snapshot.banner])
    for profile in data['profiles']:
        for deck in profile['decks']:
            if deck['kind'] == 1:
                deck.update(portrait=snapshot.portrait, banner=snapshot.banner,
                            deck_hex=(encode_deck(tuple(range(100, 108)))+snapshot.deck_entitlement).hex())
    return data


def assert_selection(test, match, slot, snapshot):
    test.assertEqual(match.cosmetics_by_slot[slot], snapshot)
    army = match.armies_by_slot[slot]
    test.assertEqual((get_uint(army, 5), get_uint(army, 6)), (snapshot.banner, snapshot.portrait))
    test.assertEqual(decode_deck(get_bytes(army, 3))['entitlements'], (snapshot.entitlement,))
    test.assertEqual(match.deck_messages_by_slot[slot], get_bytes(army, 3))


class MatchCosmeticTests(unittest.TestCase):
    def setUp(self):
        self.book, self.changed = selections()
        self.template = synthetic_template()
        self.roster = [dict(slot=0, player_id=101, name='First'), dict(slot=1, player_id=202, name='Second')]

    def test_full_human_appearance_and_ordered_entitlements_are_frozen_in_every_copy(self):
        selected = {0:self.changed, 1:self.book.normalize_local()}
        match = self.template.build_match(self.roster, self.template.default_decks,
            human_cosmetics=selected, cosmetic_catalog=self.book)
        for slot, snapshot in selected.items(): assert_selection(self, match, slot, snapshot)
        selected[0] = self.book.normalize_local()
        assert_selection(self, match, 0, self.changed)
        with self.assertRaises(TypeError): match.cosmetics_by_slot[0] = selected[0]
        self.assertEqual(len(match.cosmetics_by_slot[0].slots), 17)
        self.assertNotEqual(self.changed.keys, tuple(sorted(self.changed.keys)))

    def test_forged_derived_metadata_cannot_override_validated_native_slots(self):
        forged = replace(self.changed, portrait=0xffffffff, banner=0xffffffff, entitlement=b'forged', keys=(1,))
        match = self.template.build_match(self.roster, self.template.default_decks,
            human_cosmetics={0:forged, 1:self.book.normalize_local()}, cosmetic_catalog=self.book)
        assert_selection(self, match, 0, self.changed)

    def test_missing_extra_foreign_catalog_and_invalid_slots_fail_before_construction(self):
        bad_pairs = list(self.changed.slots);bad_pairs[0] = (bad_pairs[0][0], 50002)
        for selected, book in (({0:self.changed}, self.book),
                ({0:self.changed, 1:self.changed, 2:self.changed}, self.book),
                ({0:replace(self.changed, catalog_sha256='0'*64), 1:self.changed}, self.book),
                ({0:replace(self.changed, slots=tuple(bad_pairs)), 1:self.changed}, self.book),
                ({0:self.changed, 1:self.changed}, None), (None, self.book)):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                self.template.build_match(self.roster, self.template.default_decks,
                    human_cosmetics=selected, cosmetic_catalog=book)


class CoordinatorCosmeticTests(DedicatedFixture):
    online, command = community_tests.CommunityTests.online, community_tests.CommunityTests.command
    invite_pair, start_pair, return_pair = community_tests.CommunityTests.invite_pair, community_tests.CommunityTests.start_pair, community_tests.CommunityTests.return_pair
    queue, advance_queue = public_tests.PublicQueueTests.queue, public_tests.PublicQueueTests.advance
    public_command, offer, accept = public_tests.PublicQueueTests.public_command, public_tests.PublicQueueTests.offer, public_tests.PublicQueueTests.accept
    ai_factory, play_frames = public_tests.PublicQueueTests.ai_factory, public_tests.PublicQueueTests.play_frames

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.book, self.changed = selections()
        self.now = 1000.0
        self.templates = {1:self.template, 2:synthetic_template(2), 5:synthetic_template(5)}
        for value in self.templates.values(): value.descriptors_path = self.template.descriptors_path
        (self.folder/'bot-catalog.json').write_text(json.dumps(bot_data(self.book)))
        self.bots = BotCatalog(self.folder, template=self.template)

    async def start_cosmetics(self, *, public=False):
        await self.start(cosmetic_catalog=self.book, templates=self.templates, bot_catalog=self.bots,
                         ai_factory=self.ai_factory if public else None)
        self.public = self.server.community.public
        self.public.clock = lambda:self.now

    async def test_custom_uses_selected_session_loadout_without_reloading_changed_disk_state(self):
        await self.start_cosmetics()
        self.server.profiles.save('alpha', self.template.default_decks[0], cosmetics=self.changed)
        a, b = await self.online('alpha'), await self.online('beta')
        lobby = await self.invite_pair(a, b)
        # A later disk update must not replace a connected player's selection.
        self.server.profiles.save('alpha', self.template.default_decks[0], cosmetics=self.book.normalize_local())
        room = await self.start_pair(lobby, (a, b))
        assert_selection(self, room.match, 0, self.changed)
        assert_selection(self, room.match, 1, self.book.normalize_local())
        await self.command(a, c.SET_DECK, p.deck_bytes(a.deck), ok=False)
        await self.complete(room.name, (a, b))
        await self.return_pair(lobby, (a, b), lobby.match_id)
        second = await self.start_pair(lobby, (a, b))
        assert_selection(self, second.match, 0, self.changed)
        self.assertIsNot(second.match, room.match)

    async def test_public_queue_freezes_selection_before_waiting_and_commit(self):
        await self.start_cosmetics(public=True)
        self.server.profiles.save('alpha', self.template.default_decks[0], cosmetics=self.changed)
        a, b = await self.online('alpha'), await self.online('beta')
        await self.queue(a)
        entry = self.public.entries['alpha']
        self.assertEqual(entry.cosmetics, self.changed)
        self.server.community.sessions['alpha'].cosmetics = self.book.normalize_local()
        self.server.profiles.save('alpha', self.template.default_decks[0], cosmetics=self.book.normalize_local())
        await self.queue(b)
        room = await self.accept((a, b))
        assert_selection(self, room.match, 0, self.changed)
        assert_selection(self, room.match, 1, self.book.normalize_local())
        await self.play_frames(room, (a, b), count=2)

    async def test_partial_2vai_keeps_human_selection_and_independent_original_bot_decks(self):
        await self.start_cosmetics(public=True)
        self.server.profiles.save('alpha', self.template.default_decks[0], cosmetics=self.changed)
        a = await self.online('alpha')
        await self.queue(a, mode=5)
        self.advance_queue(30)
        room = await self.accept((a,))
        self.assertEqual(set(room.match.cosmetics_by_slot), {a.slot})
        assert_selection(self, room.match, a.slot, self.changed)
        for slot, bot in room.bots.items():
            self.assertEqual(room.match.deck_messages_by_slot[slot], bot.choice.deck_message)
            self.assertEqual(get_uint(room.match.armies_by_slot[slot], 5), bot.choice.banner)
            self.assertEqual(get_uint(room.match.armies_by_slot[slot], 6), bot.choice.portrait)
        await self.play_frames(room, (a,), count=2)


if __name__ == '__main__': unittest.main()
