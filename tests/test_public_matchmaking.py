"""Real loopback queues and supervised synthetic workers, with an injected clock.

These prove protocol/arbitration, not native AI tactics or graphical team play.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
from types import SimpleNamespace
import unittest
import uuid

from server import protocol as p, public_protocol as q, community_protocol as c
from server.bot_catalog import BotCatalog
from server.game_data import encode_frame, encode_player_input
from server.protobuf_wire import get_bytes, get_repeated_bytes, get_uint
from server.worker_ai import BotRoster
from tests.synthetic import template as synthetic_template
from tests.test_bot_catalog import catalog_fixture
from tests import test_community as community_tests
from tests.test_dedicated_server import DedicatedFixture, wait_until


class PublicQueueTests(DedicatedFixture):
    online, command = community_tests.CommunityTests.online, community_tests.CommunityTests.command

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.now = 1000.0
        self.templates = {1: self.template, 2: synthetic_template(2), 5: synthetic_template(5)}
        for template in self.templates.values(): template.descriptors_path = self.template.descriptors_path
        data = catalog_fixture()
        data['names'] = ['Fixture Alpha', 'Fixture Beta', 'Fixture Gamma', 'Fixture Delta']
        (self.folder/'bot-catalog.json').write_text(json.dumps(data), encoding='utf-8')
        self.catalog = BotCatalog(self.folder, template=self.template)

    async def start_public(self, **kwargs):
        await self.start(templates=self.templates, bot_catalog=self.catalog,
                         ai_factory=kwargs.pop('ai_factory', self.ai_factory), **kwargs)
        self.public = self.server.community.public
        self.public.clock = lambda: self.now

    async def ai_factory(self, data, bots):
        worker = await self.factory(data)
        roster = BotRoster(data, bots)
        async def inputs(frame): return roster.make_inputs(frame, {})
        worker.bot_inputs = inputs
        worker.accepted_inputs = {}
        original = worker.process_frame
        async def record(actions, dt_ms=None):
            result = await original(actions, dt_ms)
            worker.accepted_inputs[result.frame] = actions
            return result
        worker.process_frame = record
        return worker

    async def public_command(self, peer, kind, ticket=None, *, ok=True, **kwargs):
        body = q.command(kind, peer.request+1, peer.ticket if ticket is None else ticket, **kwargs)
        return await self.command(peer, kind, body[4:], ok=ok)

    async def queue(self, peer, mode=1, ticket=1, wait_ms=30000):
        peer.ticket = ticket
        await self.public_command(peer, q.ENTER, mode=mode, deck=peer.deck, wait_ms=wait_ms)

    def advance(self, seconds):
        self.now += seconds
        self.public.maintain()

    def offer(self, peer):
        return self.public.offers[self.public.entries[peer.profile].offer]

    async def accept(self, peers):
        offer = self.offer(peers[0])
        for peer in peers:
            self.assertIs(self.offer(peer), offer)
            await self.public_command(peer, q.READY, match=offer.id)
        for peer in peers:
            peer.assignment = q.decode_assignment(await peer.receive(q.MATCH))
            peer.slot = peer.assignment['slot']
            self.assertEqual(peer.assignment['generation'], peer.ticket)
            self.assertEqual(peer.assignment['match'], offer.id)
            peer.bootstrap = await peer.receive(p.BOOTSTRAP)
        self.assertEqual(len({peer.bootstrap for peer in peers}), 1)
        return offer.room

    async def play_frames(self, room, peers, count=3):
        for peer in peers: await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        for peer in peers: await peer.receive(p.START)
        for number in range(count):
            for peer in peers: await peer.send(p.INPUT, struct.pack('<I', number))
            received = [await peer.receive(q.FRAME) for peer in peers]
            self.assertEqual(len(set(received)), 1)
            frame, inputs = q.decode_frame(received[0], len(room.slots))
            self.assertEqual(frame, number)
            self.assertEqual(set(inputs), room.slots)
            for peer in peers:
                self.assertEqual(inputs[peer.slot], encode_player_input(room.match.identities_by_slot[peer.slot]))
            if room.bots:
                self.assertEqual(room.sim.accepted_inputs[number], encode_frame(number, inputs))
        self.assertFalse(any(kind == p.FRAME for peer in peers for kind, _ in peer.observed))

    async def test_full_1v1_commits_once_after_both_acknowledgements_and_can_queue_again(self):
        await self.start_public()
        peers = [await self.online('full_a'), await self.online('full_b')]
        for peer in peers: await self.queue(peer)
        offer = self.offer(peers[0])
        self.assertEqual(self.workers, [])
        await self.public_command(peers[0], q.READY, match=offer.id)
        self.assertEqual(self.workers, [])
        await self.public_command(peers[0], q.READY, match=offer.id, ok=False)
        await self.public_command(peers[1], q.READY, match=offer.id)
        for peer in peers:
            peer.assignment = q.decode_assignment(await peer.receive(q.MATCH))
            peer.slot = peer.assignment['slot']
            peer.bootstrap = await peer.receive(p.BOOTSTRAP)
        room = offer.room
        self.assertEqual(len(self.workers), 1)
        await self.public_command(peers[0], q.CANCEL, ok=False)
        await self.play_frames(room, peers)
        await room.finish('authored result', result={'complete': True})
        self.assertEqual(self.server.room_count(), 0)


        for peer in peers:
            await self.public_command(peer, q.RETURN, match=offer.id)
            self.assertFalse(self.public.busy(peer.profile))
            await self.queue(peer, ticket=2)
        self.assertNotEqual(self.offer(peers[0]).id, offer.id)
        self.assertEqual(len(self.workers), 1)  # New proposal is not a second worker yet.

    async def test_30_second_boundary_fills_one_authoritative_1v1_with_a_frozen_bot(self):
        await self.start_public()
        peer = await self.online('solo')
        await self.queue(peer)
        self.advance(29.999)
        self.assertIsNone(self.public.entries[peer.profile].offer)
        self.assertFalse(self.workers)
        self.advance(.001)
        room = await self.accept([peer])
        self.assertEqual(set(room.peers), {0})
        self.assertEqual(set(room.bots), {1})
        choice = room.bots[1].choice
        self.assertEqual(get_bytes(room.match.armies_by_slot[1], 3), choice.deck_message)
        self.assertEqual(get_uint(room.match.armies_by_slot[1], 6), choice.portrait)
        self.assertEqual(peer.assignment['human_mask'], 1)
        await self.play_frames(room, [peer])

    async def test_partial_2v2_groups_stay_together_in_four_army_frames(self):
        await self.start_public()
        for humans in (1, 2, 3):
            with self.subTest(humans=humans):
                peers = [await self.online(f'team_{humans}_{i}') for i in range(humans)]
                for peer in peers: await self.queue(peer, mode=2)
                self.advance(30)
                room = await self.accept(peers)
                self.assertEqual(set(room.peers), set(range(humans)))
                self.assertEqual(set(room.bots), set(range(humans, 4)))
                self.assertEqual([get_uint(room.match.armies_by_slot[i], 4) for i in range(4)], [0, 1, 0, 1])
                await self.play_frames(room, peers)
                await room.finish('authored result', result={'complete': True})
                for peer in peers: await self.public_command(peer, q.RETURN, match=room.match_id)

    async def test_four_humans_match_before_timeout_without_bots(self):
        await self.start_public()
        peers = [await self.online(f'four_{i}') for i in range(4)]
        for peer in peers: await self.queue(peer, mode=2)
        self.assertEqual(self.now, 1000)
        room = await self.accept(peers)
        self.assertEqual(set(room.peers), {0, 1, 2, 3})
        self.assertEqual(dict(room.bots), {})
        self.assertTrue(all(peer.assignment['human_mask'] == 15 for peer in peers))
        await self.play_frames(room, peers)

    async def test_2vai_uses_human_allies_zero_two_and_original_opponent_pool(self):
        await self.start_public()
        for humans in (1, 2):
            with self.subTest(humans=humans):
                peers = [await self.online(f'coop_{humans}_{i}') for i in range(humans)]
                for peer in peers: await self.queue(peer, mode=5)
                if humans == 1: self.advance(30)
                room = await self.accept(peers)
                self.assertEqual(set(room.peers), {0} if humans == 1 else {0, 2})
                self.assertEqual([room.bots[i].choice.source_mode for i in (1, 3)], [5, 5])
                if humans == 1: self.assertEqual(room.bots[2].choice.source_mode, 2)
                await self.play_frames(room, peers)
                await room.finish('authored result', result={'complete': True})
                for peer in peers: await self.public_command(peer, q.RETURN, match=room.match_id)

    async def test_cancelled_ticket_and_old_offer_cannot_start_a_new_search(self):
        await self.start_public()
        a, b = await self.online('cancel_a'), await self.online('cancel_b')
        await self.queue(a); await self.queue(b)
        old = self.offer(a).id
        await self.public_command(a, q.READY, match=old)
        await self.public_command(b, q.CANCEL)
        self.assertFalse(self.public.busy(b.profile))
        self.assertIsNone(self.public.entries[a.profile].offer)
        await self.queue(b, ticket=2)
        new = self.offer(a).id
        self.assertNotEqual(old, new)
        await self.public_command(a, q.READY, match=old, ok=False)
        await self.public_command(b, q.CANCEL, ticket=1, ok=False)
        self.assertEqual(self.offer(b).id, new)
        self.assertFalse(self.workers)
        await self.public_command(b, q.CANCEL)
        await self.public_command(b, q.ENTER, ticket=2, mode=1, deck=b.deck, ok=False)

    async def test_partial_offer_expiry_preserves_acknowledged_human_deadline(self):
        await self.start_public()
        a, b = await self.online('expiry_a'), await self.online('expiry_b')
        await self.queue(a, mode=2); await self.queue(b, mode=2)
        self.advance(30)
        old = self.offer(a).id
        await self.public_command(a, q.READY, match=old)
        self.advance(10)
        self.assertFalse(self.public.busy(b.profile))
        new = self.offer(a)
        self.assertNotEqual(new.id, old)
        self.assertEqual(new.entries, (self.public.entries[a.profile],))
        self.assertEqual(new.entries[0].deadline, 1030)
        await self.public_command(a, q.READY, match=old, ok=False)
        self.assertFalse(self.workers)
        room = await self.accept([a])
        self.assertEqual(len(room.bots), 3)

    async def test_public_search_blocks_custom_practice_and_deck_changes(self):
        await self.start_public()
        a, b = await self.online('busy_a'), await self.online('busy_b')
        await self.command(b, c.CREATE, b'\x01')
        await self.queue(a)
        for kind, body in ((c.CREATE, b'\x01'), (c.PRACTICE, b'\x01'), (c.SET_DECK, p.deck_bytes(a.deck))):
            await self.command(a, kind, body, ok=False)
        await self.command(b, c.INVITE, p.encode_string(a.profile), ok=False)
        row = next(row for row in self.server.community.directory_rows if row[0] == a.profile)
        self.assertEqual(row[2:], (c.UNAVAILABLE, False))
        await self.public_command(a, q.CANCEL)
        self.assertEqual(len(self.server.community.lobbies), 1)
        self.assertFalse(self.workers)

    async def test_ready_at_expiry_retires_all_missing_players_before_maintenance(self):
        await self.start_public()
        peers = [await self.online('late_' + str(i)) for i in range(3)]
        for peer in peers: await self.queue(peer, mode=2)
        self.advance(30)
        old = self.offer(peers[0])
        await self.public_command(peers[0], q.READY, match=old.id)
        # Do not call maintain: the packet handler must enforce this boundary.
        self.now += 10
        await self.public_command(peers[1], q.READY, match=old.id, ok=False)
        self.assertEqual(set(self.public.entries), {peers[0].profile})
        self.assertNotIn(old.id, self.public.offers)
        self.assertFalse(self.workers)

    async def test_public_proposal_reserves_capacity_and_cancel_releases_it(self):
        await self.start_public(max_rooms=1)
        a, b, host = [await self.online('capacity_' + str(i)) for i in range(3)]
        await self.queue(a); await self.queue(b)
        self.assertEqual(self.server.room_count(), 1)
        self.assertFalse(self.workers)
        await self.command(host, c.CREATE, b'\x01', ok=False)
        await self.public_command(b, q.CANCEL)
        self.assertEqual(self.server.room_count(), 0)
        await self.command(host, c.CREATE, b'\x01')
        self.advance(30)
        self.assertFalse(self.public.busy(a.profile))
        self.assertEqual(self.server.room_count(), 1)
        self.assertFalse(self.workers)

    async def test_worker_cannot_replace_human_input_with_bot_input(self):
        async def corrupt(data, bots):
            worker = await self.ai_factory(data, bots)
            original = worker.bot_inputs
            async def inputs(frame): return (await original(frame)) | {0: b'forged human input'}
            worker.bot_inputs = inputs
            return worker
        await self.start_public(ai_factory=corrupt)
        peer = await self.online('corrupt_bot_roster')
        await self.queue(peer, wait_ms=0)
        room = await self.accept([peer])
        await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        await peer.receive(p.START)
        await peer.send(p.INPUT, struct.pack('<I', 0))
        await wait_until(lambda: room.state == 'closed')
        self.assertFalse(self.workers[0].accepted_inputs)
        self.assertFalse(any(kind == q.FRAME for kind, _ in peer.observed))
        await self.public_command(peer, q.RETURN, match=room.match_id)
        self.assertFalse(self.public.busy(peer.profile))

    async def test_journal_setup_failure_before_assignment_retires_prepared_worker(self):
        await self.start_public(data_dir=self.folder/'blocked-evidence')
        self.server.data_dir.mkdir()
        (self.server.data_dir/'matches').write_text('authored path collision')
        peer = await self.online('journal_failure')
        await self.queue(peer, wait_ms=0)
        offer = self.offer(peer)
        await self.public_command(peer, q.READY, match=offer.id)
        await wait_until(lambda: bool(self.workers) and self.workers[0].closed)
        self.assertFalse(self.public.busy(peer.profile))
        self.assertIsNone(self.server.community.sessions[peer.profile].peer.room)
        self.assertFalse(any(kind in (q.MATCH, p.BOOTSTRAP) for kind, _ in peer.observed))
        self.assertEqual(self.server.room_count(), 0)

    async def test_partial_assignment_failure_keeps_abort_identity_until_each_return(self):
        await self.start_public()
        a, b = await self.online('send_a'), await self.online('send_b')
        await self.queue(a); await self.queue(b)
        offer = self.offer(a)
        server_peer = self.server.community.sessions[b.profile].peer
        original_send = server_peer.send
        def failed_assignment(kind, payload=b''):
            if kind == q.MATCH: raise RuntimeError('authored assignment delivery failure')
            return original_send(kind, payload)
        server_peer.send = failed_assignment
        for peer in (a, b): await self.public_command(peer, q.READY, match=offer.id)
        assignment = q.decode_assignment(await a.receive(q.MATCH))
        self.assertEqual(assignment['match'], offer.id)
        await wait_until(lambda: offer.phase == q.RESULTS)
        self.assertEqual(self.server.room_count(), 0)
        for peer in (a, b):
            self.assertTrue(self.public.busy(peer.profile))
            self.assertFalse(any(kind == p.BOOTSTRAP for kind, _ in peer.observed))
            await self.public_command(peer, q.RETURN, match=offer.id)
            self.assertIsNone(self.server.community.sessions[peer.profile].peer.room)
        self.assertFalse(self.public.offers)

    async def test_worker_setup_failure_retires_every_ticket_without_bootstrap(self):
        async def failed(data, bots): raise RuntimeError('authored worker failure')
        await self.start_public(ai_factory=failed)
        peer = await self.online('failure')
        await self.queue(peer, wait_ms=0)
        offer = self.offer(peer)
        await self.public_command(peer, q.READY, match=offer.id)
        await wait_until(lambda: not self.public.busy(peer.profile))
        self.assertIsNone(self.server.community.sessions[peer.profile].peer.room)
        self.assertFalse(any(kind in (q.MATCH, p.BOOTSTRAP) for kind, _ in peer.observed))
        self.assertEqual(self.server.room_count(), 0)
        await self.queue(peer, ticket=2)

    async def test_disconnect_during_worker_creation_reaps_late_worker_and_never_publishes_start(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(data, bots):
            entered.set()
            await release.wait()
            return await self.ai_factory(data, bots)
        await self.start_public(ai_factory=delayed)
        peer = await self.online('disconnect')
        await self.queue(peer, wait_ms=0)
        offer = self.offer(peer)
        await self.public_command(peer, q.READY, match=offer.id)
        await asyncio.wait_for(entered.wait(), 2)
        await peer.close()
        await wait_until(lambda: not self.public.busy(peer.profile))
        release.set()
        await wait_until(lambda: bool(self.workers) and all(worker.closed for worker in self.workers))
        self.assertFalse(any(kind in (q.MATCH, p.BOOTSTRAP) for kind, _ in peer.observed))
        self.assertEqual(self.server.room_count(), 0)


@unittest.skipUnless(os.name == 'nt' and os.environ.get('BA_RUN_NATIVE_WORKER_TESTS') == '1',
                     'native public snapshots require explicit Windows opt-in')
class NativePublicSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_armies_use_two_native_alliance_views_in_room_diagnostics(self):
        from server.dedicated_server import Room
        from server.game_data import GameTemplate
        from server.native_simulation import canonical_snapshot
        from server.worker_client import SimulationWorker
        root = Path(__file__).resolve().parents[1]
        assets = Path(os.environ.get('BA_WORKER_TEST_ASSETS', root/'local/assets/team-bot-export02')).resolve()
        if not (assets/'map-2vai.pb.gz').is_file(): self.skipTest('imported original team map required')
        template = GameTemplate.load(assets/'map-2vai.pb.gz', catalog_path=assets/'unit-catalog.json',
                                     descriptors_path=assets/'descriptors')
        match = template.build_match([dict(slot=i, name='Snapshot fixture ' + str(i)) for i in range(4)],
                                     template.default_decks, seed=31286)
        folder = root/'local/test-runs'/('public-snapshot-' + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        worker, views, events = None, [], []
        try:
            worker = await SimulationWorker.create(match.raw_game_data, assets/'Simulation.dll', working_directory=folder)
            await worker.process_frame(encode_frame(0, {slot: encode_player_input(match.identities_by_slot[slot]) for slot in range(4)}))
            async def snapshot(alliance):
                raw = await worker.snapshot(alliance)
                parsed = canonical_snapshot(raw, alliance)
                self.assertEqual(parsed['local_alliance'], alliance)
                views.append(alliance)
                return raw
            room = SimpleNamespace(sim=SimpleNamespace(snapshot=snapshot), template=template, state='running',
                frame=0, server=SimpleNamespace(data_dir=None), event=lambda event, **fields: events.append((event, fields)))
            await Room.record_snapshot(room)
            self.assertEqual(views, [0, 1])
            self.assertEqual([fields['viewer'] for _, fields in events], [0, 1])
        finally:
            if worker is not None: await worker.close()
            folder.resolve().relative_to((root/'local/test-runs').resolve())
            self.assertTrue(folder.name.startswith('public-snapshot-'))
            shutil.rmtree(folder)
        self.assertEqual(worker.process.poll(), 0)
