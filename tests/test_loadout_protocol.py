"""Authored full-loadout packets and real socket transaction/freeze failures."""
from dataclasses import replace
import struct
from unittest import mock
import unittest

from server import community_protocol as c, public_protocol as q, protocol as p, loadout_protocol as full
from tests import test_match_cosmetics as match_fixtures
selections, assert_selection = match_fixtures.selections, match_fixtures.assert_selection


class LoadoutProtocolTests(unittest.TestCase):
    def setUp(self): self.book, self.changed = selections()

    def test_explicit_full_packets_remain_bounded_and_legacy_rejects_extra_fields(self):
        deck = list(range(100,108))
        publication = full.set_loadout(5, deck, self.changed)
        self.assertEqual(len(publication), 206)
        decoded = c.decode_command(full.SET_LOADOUT, publication)
        self.assertEqual(decoded['cosmetics'].validate(self.book), self.changed)
        self.assertEqual(decoded['deck'], deck)
        queue = q.command(full.ENTER_LOADOUT, 6, 123, mode=5, deck=deck, cosmetics=self.changed)
        self.assertEqual(len(queue), 219)
        self.assertEqual(q.decode_command(full.ENTER_LOADOUT, queue)['cosmetics'].validate(self.book), self.changed)
        for kind, data in ((c.SET_DECK, publication), (q.ENTER, queue)):
            with self.assertRaises(p.ProtocolError): c.decode_command(kind, data)
        assignment = q.assignment(123, 'match', 5, 0, 1, 6, deck, cosmetics=self.changed)
        self.assertEqual(q.decode_assignment(assignment, complete=True)['cosmetics'].validate(self.book), self.changed)
        with self.assertRaises(p.ProtocolError): q.decode_assignment(assignment)

    def test_truncation_versions_duplicates_and_trailing_data_fail_closed(self):
        payload = full.set_loadout(1, list(range(100,108)), self.changed)
        for length in range(len(payload)):
            with self.subTest(length=length), self.assertRaises(p.ProtocolError):
                c.decode_command(full.SET_LOADOUT, payload[:length])
        for bad in (payload+b'x', payload[:4]+b'\2\0'+payload[6:]):
            with self.assertRaises(p.ProtocolError): c.decode_command(full.SET_LOADOUT, bad)
        for offset in (0,4):
            bad=bytearray(payload);bad[38+32+8+offset:38+32+12+offset]=bad[38+32+offset:38+32+4+offset]
            with self.assertRaises(p.ProtocolError): c.decode_command(full.SET_LOADOUT, bad)
        wrong_order = full.Selection(self.changed.catalog_sha256, tuple(reversed(self.changed.slots)))
        with self.assertRaises(p.ProtocolError): wrong_order.validate(self.book)


class FullLoadoutSessionTests(match_fixtures.CoordinatorCosmeticTests):
    async def publish(self, peer, selection=None, *, deck=None, ok=True):
        raw=full.set_loadout(peer.request+1, deck or peer.deck, selection or self.changed)
        return await self.command(peer, full.SET_LOADOUT, raw[4:], ok=ok)

    async def test_atomic_publication_and_custom_member_snapshots_keep_full_slots(self):
        await self.start_cosmetics()
        a,b=await self.online('alpha'),await self.online('beta')
        await self.publish(a)
        saved=self.server.profiles.load_state('alpha', [])
        self.assertEqual(saved.cosmetics,self.changed)
        session=self.server.community.sessions['alpha']
        self.assertTrue(session.full_loadout)
        lobby=await self.invite_pair(a,b)
        body=next(body for kind,body in reversed(a.observed) if kind==full.LOBBY_LOADOUT)
        r=c.Reader(body);self.assertEqual(r.number('H'),1)
        r.number('Q');r.number('B');r.number('I')
        for _ in range(4):r.text()
        self.assertEqual(r.number('B'),2)
        snapshots={}
        for _ in range(2):
            identity=r.key();r.deck();snapshots[identity]=full.decode(r).validate(self.book);r.flag();r.flag()
        r.end();self.assertEqual(snapshots['alpha'],self.changed)
        self.assertEqual(snapshots['beta'],self.book.normalize_local())
        self.assertTrue(any(kind==c.LOBBY for kind,_ in b.observed))
        room=await self.start_pair(lobby,(a,b));assert_selection(self,room.match,0,self.changed)
        before=(self.folder/'profiles/alpha.json').read_bytes()
        await self.publish(a,self.book.normalize_local(),ok=False)
        self.assertEqual((self.folder/'profiles/alpha.json').read_bytes(),before)

    async def test_missing_server_catalog_rejects_without_upgrading_or_saving(self):
        await self.start()
        a=await self.online('unsupported')
        await self.publish(a,ok=False)
        session=self.server.community.sessions[a.profile]
        self.assertFalse(session.full_loadout)
        self.assertIsNone(session.cosmetics)
        self.assertFalse((self.server.profiles.path/'unsupported.json').exists())

    async def test_rejected_catalog_category_or_disk_write_preserves_session_and_file(self):
        await self.start_cosmetics()
        a=await self.online('atomic')
        await self.publish(a)
        session=self.server.community.sessions['atomic']
        path=self.server.profiles.path/'atomic.json'
        before=path.read_bytes()
        wrong=replace(self.changed,catalog_sha256='0'*64)
        await self.publish(a,wrong,ok=False)
        self.assertEqual(session.cosmetics,self.changed)
        pairs=list(self.changed.slots);pairs[0]=(pairs[0][0],0xffffffff)
        await self.publish(a,replace(self.changed,slots=tuple(pairs)),ok=False)
        with mock.patch('server.profiles.os.replace',side_effect=OSError('authored disk fault')):
            await self.publish(a,self.book.normalize_local(),ok=False)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(session.cosmetics,self.changed)
        self.assertEqual(session.deck,a.deck)
        self.assertFalse(self.server.community.public.busy('atomic'))

    async def test_public_assignment_binds_original_full_intent_despite_later_session_change(self):
        await self.start_cosmetics(public=True)
        a,b=await self.online('queued_a'),await self.online('queued_b')
        for peer in (a,b):
            peer.ticket=1
            await self.public_command(peer,full.ENTER_LOADOUT,mode=1,deck=peer.deck,cosmetics=self.changed)
        self.server.community.sessions[a.profile].cosmetics=self.book.normalize_local()
        offer=self.offer(a)
        for peer in (a,b):await self.public_command(peer,q.READY,match=offer.id)
        for peer in (a,b):
            assignment=q.decode_assignment(await peer.receive(full.MATCH_LOADOUT),complete=True)
            self.assertEqual(assignment['cosmetics'].validate(self.book),self.changed)
            peer.slot=assignment['slot'];peer.bootstrap=await peer.receive(p.BOOTSTRAP)
        room=offer.room
        assert_selection(self,room.match,a.slot,self.changed)
        self.assertEqual(room.full_loadout_seats,{0,1})
        await self.play_frames(room,(a,b),count=2)


if __name__=='__main__':unittest.main()
