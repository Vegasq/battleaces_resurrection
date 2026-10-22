"""Authored catalog IDs and real mixed-version community sockets only."""
from dataclasses import replace
import struct
import unittest

from server import community_protocol as c, protocol as p, loadout_protocol as full
from tests import test_match_cosmetics as fixtures
from tests.test_dedicated_server import DedicatedFixture, wait_until


def decode(payload):
    r = c.Reader(payload)
    assert r.number('H') == 1
    catalog = bytes(r.number('B') for _ in range(32)).hex()
    revision, count = r.number('Q'), r.number('H')
    rows = {r.key(): (r.text(), r.number('B'), r.flag(), r.number('I')) for _ in range(count)}
    r.end()
    return catalog, revision, rows


class DirectoryPortraitWireTests(unittest.TestCase):
    def test_v1_bytes_and_hello_stay_exact_and_v2_is_explicit(self):
        rows = (('a', 'Alpha', 0, True),)
        expected = struct.pack('<QH', 7, 1)+p.encode_string('a')+p.encode_string('Alpha')+b'\x00\x01'
        self.assertEqual(c.directory(7, rows), expected)
        for version in (1, 2):
            hello = c.hello('a', 'Alpha', version=version)
            self.assertEqual(c.decode_hello(hello), ('a', 'Alpha'))
            self.assertEqual(c.hello_version(hello), version)
        for payload in (b'', b'\x01', b'\x03\x00'):
            with self.assertRaises(p.ProtocolError): c.decode_hello(payload)

    def test_max_directory_fits_native_bound_and_no_catalog_cannot_claim_portrait(self):
        rows = tuple((f'{i:048}', '\U0001f3ae'*32, 0, True) for i in range(c.MAX_PLAYERS))
        body = c.directory_portraits(1, rows, 'ab'*32, {row[0]:901 for row in rows})
        self.assertLessEqual(len(body), 32768)
        self.assertEqual(len(decode(body)[2]), c.MAX_PLAYERS)
        for portrait in (-1, True, 2**32):
            with self.assertRaises(p.ProtocolError): c.directory_portraits(1, rows[:1], 'ab'*32, {rows[0][0]:portrait})
        with self.assertRaises(p.ProtocolError): c.directory_portraits(1, rows[:1], '0'*64, {rows[0][0]:901})


class DirectoryPortraitSocketTests(DedicatedFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.book, self.changed = fixtures.selections()
    online = fixtures.CoordinatorCosmeticTests.online
    command = fixtures.CoordinatorCosmeticTests.command
    async def test_mixed_clients_selected_portrait_live_update_reject_and_departure(self):
        await self.start(cosmetic_catalog=self.book)
        self.server.profiles.save('alpha', self.template.default_decks[0], cosmetics=self.changed)
        alpha = await self.online('alpha', version=2)
        legacy = await self.online('legacy')
        def latest():
            packets = [v for k,v in alpha.observed if k == c.DIRECTORY_PORTRAITS]
            return decode(packets[-1]) if packets else None
        await wait_until(lambda: latest() and 'legacy' in latest()[2])
        catalog, revision, rows = latest()
        self.assertEqual(catalog, self.book.sha256)
        self.assertEqual(rows['alpha'][3], self.changed.portrait)
        self.assertEqual(rows['legacy'][3], self.book.normalize_local().portrait)
        self.assertFalse(any(k == c.DIRECTORY for k,v in alpha.observed))
        self.assertFalse(any(k == c.DIRECTORY_PORTRAITS for k,v in legacy.observed))
        # Connected selection, not changed-on-disk profile or a forged derived ID.
        self.server.profiles.save('alpha', alpha.deck, cosmetics=self.book.normalize_local())
        session = self.server.community.sessions['alpha']
        session.cosmetics = replace(session.cosmetics, portrait=0xffffffff)
        await self.command(alpha, c.REFRESH)
        self.assertEqual(latest()[2]['alpha'][3], self.changed.portrait)
        default = self.book.normalize_local()
        await self.command(alpha, full.SET_LOADOUT, full.set_loadout(1, alpha.deck, default)[4:])
        await wait_until(lambda: latest()[2]['alpha'][3] == default.portrait)
        self.assertGreater(latest()[1], revision)
        stable = latest()[1]
        invalid = full.Selection('0'*64, default.slots)
        await self.command(alpha, full.SET_LOADOUT, struct.pack('<H', 1)+p.deck_bytes(alpha.deck)+full.encode(invalid), ok=False)
        self.assertEqual(latest()[1], stable)
        self.assertEqual(latest()[2]['alpha'][3], default.portrait)
        await legacy.close()
        await wait_until(lambda: 'legacy' not in latest()[2])
