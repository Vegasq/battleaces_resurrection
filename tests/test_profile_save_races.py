"""Real sockets with bounded delayed storage; keep match/lobby/session ownership."""
import asyncio
import struct
import threading
from server import community_protocol as c,protocol as p,public_protocol as q
from server.bot_catalog import BotCatalog
from tests.synthetic import template as synthetic_template
from tests.test_bot_catalog import catalog_fixture
from tests import test_community as community_tests
from tests.test_dedicated_server import DedicatedFixture,wait_until
from tests import test_public_matchmaking as public_tests
import json


class ProfileSaveRaceTests(DedicatedFixture):
    online,command,invite_pair=community_tests.CommunityTests.online,community_tests.CommunityTests.command,community_tests.CommunityTests.invite_pair
    public_command=public_tests.PublicQueueTests.public_command

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # Two authored basic units are interchangeable; retain production deck
        # validation instead of reversing units into incompatible tech slots.
        for entity in (100,101):self.template.catalog[entity]['deck_slot_flags'] |= 3
        self.storage_entered,self.storage_release=threading.Event(),threading.Event()

    async def asyncTearDown(self):
        self.storage_release.set()
        await super().asyncTearDown()

    def delay(self,method='save'):
        original=getattr(self.server.profiles,method)
        def blocked(*args,**kwargs):
            self.storage_entered.set()
            if not self.storage_release.wait(3): raise TimeoutError('test storage gate')
            return original(*args,**kwargs)
        setattr(self.server.profiles,method,blocked)
        return original

    async def start_public(self):
        templates={1:self.template,2:synthetic_template(2),5:synthetic_template(5)}
        for item in templates.values():item.descriptors_path=self.template.descriptors_path
        (self.folder/'bot-catalog.json').write_text(json.dumps(catalog_fixture()))
        await self.start(templates=templates,bot_catalog=BotCatalog(self.folder,template=self.template),ai_factory=lambda *args:None)

    async def test_pending_guest_selection_refuses_start_and_does_not_block_refresh(self):
        await self.start()
        host,guest=await self.online(),await self.online()
        lobby=await self.invite_pair(host,guest)
        session=self.server.community.sessions[guest.profile];old=list(session.deck);deck=list(old);deck[0],deck[1]=deck[1],deck[0]
        self.delay()
        change=asyncio.create_task(self.command(guest,c.SET_DECK,p.deck_bytes(deck)))
        await wait_until(self.storage_entered.is_set)
        self.assertTrue(session.saving);self.assertEqual(session.deck,old);self.assertFalse(change.done())
        reason=await self.command(host,c.START,p.encode_string(lobby.id)+struct.pack('<Q',lobby.revision),ok=False)
        self.assertIn('saving',reason);self.assertEqual(lobby.phase,c.OPEN);self.assertFalse(self.workers)
        await self.command(host,c.REFRESH)
        self.storage_release.set();await change
        self.assertFalse(session.saving);self.assertEqual(session.deck,deck)
        self.assertEqual(self.server.profiles.load(guest.profile,old),deck)

    async def test_failed_public_save_has_no_ticket_and_preserves_previous_data(self):
        await self.start_public();peer=await self.online();peer.ticket=1
        await self.server.profile_io.save(peer.profile,peer.deck)
        path=self.server.profiles._path(peer.profile);before=path.read_bytes()
        original=self.server.profiles.save
        def denied(*args,**kwargs):raise PermissionError('fixture denied')
        self.server.profiles.save=denied
        deck=list(peer.deck);deck[0],deck[1]=deck[1],deck[0]
        reason=await self.public_command(peer,q.ENTER,mode=1,deck=deck,ok=False)
        session=self.server.community.sessions[peer.profile]
        self.assertIn('unavailable',reason);self.assertEqual(path.read_bytes(),before)
        self.assertNotIn(peer.profile,self.server.community.public.entries)
        self.assertEqual(session.last_public_ticket,0);self.assertFalse(session.saving)
        self.server.profiles.save=original
        await self.public_command(peer,q.ENTER,mode=1,deck=peer.deck)
        self.assertEqual(self.server.community.public.entries[peer.profile].ticket,1)

    async def test_shutdown_during_public_save_drains_without_late_ack_or_entry(self):
        await self.start_public();peer=await self.online();peer.ticket=1
        self.delay()
        enter=asyncio.create_task(self.public_command(peer,q.ENTER,mode=1,deck=peer.deck))
        await wait_until(self.storage_entered.is_set)
        session=self.server.community.sessions[peer.profile]
        self.assertTrue(session.saving);self.assertNotIn(peer.profile,self.server.community.public.entries)
        close=asyncio.create_task(self.server.close());await asyncio.sleep(.02)
        self.assertFalse(close.done());self.assertFalse(any(row['event']=='server_stopped' for row in self.events))
        self.storage_release.set();await close
        result=await asyncio.gather(enter,return_exceptions=True)
        self.assertIsInstance(result[0],AssertionError)
        self.assertNotIn(peer.profile,self.server.community.public.entries)
        self.assertFalse(self.server.profile_io.pending)
        self.assertFalse(any(kind==c.ACK and struct.unpack_from('<I',body)[0]==peer.request for kind,body in peer.observed))
        self.assertEqual(self.events[-1]['event'],'server_stopped')

    async def test_departed_lobby_cannot_receive_a_late_selection_commit(self):
        await self.start();host,guest=await self.online(),await self.online()
        lobby=await self.invite_pair(host,guest);session=self.server.community.sessions[guest.profile]
        before=list(session.deck);deck=list(before);deck[0],deck[1]=deck[1],deck[0];self.delay()
        change=asyncio.create_task(self.command(guest,c.SET_DECK,p.deck_bytes(deck),ok=False))
        await wait_until(self.storage_entered.is_set)
        self.server.community.remove_member(guest.profile,lobby)
        self.storage_release.set();reason=await change
        self.assertIn('lobby changed',reason);self.assertEqual(session.deck,before)
        self.assertIsNone(session.lobby);self.assertFalse(session.saving);self.assertFalse(self.workers)

    async def test_pending_profile_load_reserves_duplicate_identity(self):
        await self.start();self.delay('load_state')
        first=asyncio.create_task(self.online('pending_identity'))
        await wait_until(self.storage_entered.is_set)
        with self.assertRaises(AssertionError):await self.online('pending_identity')
        self.storage_release.set();peer=await first
        self.assertEqual(self.server.community.sessions[peer.profile].peer.profile_id,peer.profile)
        self.assertEqual(len(self.server.community.sessions),1)

    async def test_simultaneous_legacy_loads_reserve_distinct_auto_seats(self):
        await self.start();self.delay('load_state')
        first=asyncio.create_task(self.connect('pending_seats'))
        await wait_until(self.storage_entered.is_set)
        second=asyncio.create_task(self.connect('pending_seats'))
        await wait_until(lambda:self.server.rooms['pending_seats'].joining=={0,1})
        with self.assertRaises(AssertionError):await self.connect('pending_seats')
        self.storage_release.set();a,b=await asyncio.gather(first,second)
        self.assertEqual((a.slot,b.slot),(0,1));self.assertFalse(self.server.rooms['pending_seats'].joining)

    async def test_legacy_ready_cannot_start_while_an_already_ready_deck_is_saving(self):
        await self.start();first,second=await self.connect('legacy_save'),await self.connect('legacy_save')
        room=self.server.rooms['legacy_save'];deck=list(first.deck);deck[0],deck[1]=deck[1],deck[0]
        await first.send(p.LOBBY_READY,b'\x01');await wait_until(lambda:room.ready=={0})
        self.delay();await first.send(p.SET_DECK,p.deck_bytes(deck))
        await wait_until(self.storage_entered.is_set)
        await second.send(p.LOBBY_READY,b'\x01');await wait_until(lambda:room.ready=={0,1})
        self.assertEqual(room.state,'lobby');self.assertFalse(self.workers)
        self.storage_release.set();await wait_until(lambda:not room.saving_decks)
        self.assertEqual(room.decks[0],deck);self.assertEqual(room.ready,{1})
        await first.send(p.LOBBY_READY,b'\x01')
        await asyncio.gather(first.receive(p.BOOTSTRAP),second.receive(p.BOOTSTRAP))
        self.assertEqual(room.state,'loading');self.assertEqual(len(self.workers),1)

    async def test_pending_public_save_is_not_invitable_or_an_early_queue_entry(self):
        await self.start_public();host,player=await self.online(),await self.online();player.ticket=1
        await self.command(host,c.CREATE,b'\x01');self.delay()
        enter=asyncio.create_task(self.public_command(player,q.ENTER,mode=1,deck=player.deck))
        await wait_until(self.storage_entered.is_set)
        row=next(row for row in self.server.community.directory_rows if row[0]==player.profile)
        self.assertEqual(row[2:],(c.UNAVAILABLE,False))
        self.assertNotIn(player.profile,self.server.community.public.entries)
        await self.command(host,c.INVITE,p.encode_string(player.profile),ok=False)
        self.assertFalse(self.server.community.invites)
        self.storage_release.set();await enter
        self.assertIn(player.profile,self.server.community.public.entries)


if __name__=='__main__':
    import unittest
    unittest.main()
