"""Real TLS public arrival scheduling with supervised authored worker processes.

These exercise protocol, authoritative human/bot ownership and lifecycle;
native AI behavior and visible movement require the separate runtime verifier.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import unittest
from unittest import mock
import uuid

from server import admission, command_scheduling as wire, community_protocol as c
from server import protocol as p, public_protocol as q, tls_transport as tls
from server.bot_catalog import BotCatalog
from server.game_data import encode_frame, encode_player_input
from server.protobuf_wire import get_repeated_bytes, parse_fields
from tests import test_community as community_tests
from tests import test_public_matchmaking as public_tests
from tests import test_input_validation as authored
from tests.synthetic import template as synthetic_template
from tests.test_bot_catalog import catalog_fixture
from tests.test_command_scheduling_experiment import join_body, schema
from tests.test_dedicated_server import DedicatedFixture, TestPeer, wait_until
from tests.test_tls_transport import generate_test_pki, remove_test_pki

ROOT = Path(__file__).resolve().parents[1]


class ServerAICommandSchedulingTests(DedicatedFixture):
    command = community_tests.CommunityTests.command
    ai_factory = public_tests.PublicQueueTests.ai_factory
    public_command = public_tests.PublicQueueTests.public_command
    queue = public_tests.PublicQueueTests.queue
    advance = public_tests.PublicQueueTests.advance
    offer = public_tests.PublicQueueTests.offer
    accept = public_tests.PublicQueueTests.accept
    play_frames = public_tests.PublicQueueTests.play_frames

    @classmethod
    def setUpClass(cls):
        cls.pki_folder = ROOT/'local'/('arrival-ai-pki-' + uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.pki_folder)

    @classmethod
    def tearDownClass(cls): remove_test_pki(cls.pki_folder)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        directory = Path(self.template.descriptors_path)
        (directory/'authored.proto.json').unlink()
        schema(directory)
        self.template.entity_abilities = {100: {7}}
        self.templates = {1: self.template, 2: synthetic_template(2), 5: synthetic_template(5)}
        for template in self.templates.values(): template.descriptors_path = directory
        data = catalog_fixture()
        data['names'] = ['Fixture Alpha', 'Fixture Beta', 'Fixture Gamma', 'Fixture Delta']
        (self.folder/'bot-catalog.json').write_text(json.dumps(data))
        self.catalog = BotCatalog(self.folder, template=self.template)
        self.now = 1000.0

    async def start_public(self, enabled=True, admission_burst=8, **kwargs):
        await self.start(templates=self.templates, bot_catalog=self.catalog, ai_factory=self.ai_factory,
                         tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']),
                         admission=admission.AdmissionController(None, rc_open=True, burst=admission_burst),
                         experimental_command_scheduling=enabled, **kwargs)
        self.public = self.server.community.public
        self.public.clock = lambda: self.now

    async def online(self, version=2):
        reader, writer = await tls.open_verified_connection(*self.address[:2], tls.rc_client_context('127.0.0.1'))
        profile = await admission.authenticate_client(reader, writer, 'ba1_'+secrets.token_urlsafe(32), rc_open=True)
        peer = TestPeer(reader, writer); self.clients.append(peer)
        peer.profile, peer.request = profile, 0
        await peer.send(c.HELLO, c.hello(profile, 'AI scheduling test'))
        reply = c.Reader(await peer.receive(c.WELCOME))
        reply.number('H'); reply.number('H'); reply.key(); peer.deck = reply.deck(); reply.end()
        if version:
            await peer.send(wire.NEGOTIATE, bytes([version]))
            self.assertEqual(await peer.receive(wire.ACK), bytes([version]))
        return peer

    async def solo(self, **kwargs):
        await self.start_public(**kwargs)
        peer = await self.online()
        await self.queue(peer, wait_ms=0)
        room = await self.accept([peer])
        await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        await peer.receive(p.START)
        return room, peer

    async def start_ticks(self, room, peer, ready=True):
        return await self.start_arrival_ticks(room, [peer], ready=ready)

    async def start_arrival_ticks(self, room, peers, ready=True):
        for peer in peers:
            await peer.send(wire.BATCH, wire.batch(room.match_id, 1, join_body(room.match, peer.slot)))
        frames = [await peer.receive(q.FRAME) for peer in peers]
        self.assertEqual(len(set(frames)), 1)
        frame, inputs = q.decode_frame(frames[0], len(room.slots))
        self.assertEqual(frame, 0)
        self.assertEqual(set(inputs), room.slots)
        for peer in peers: self.assertEqual(inputs[peer.slot], join_body(room.match, peer.slot))
        for slot in room.slots:
            self.assertEqual(parse_fields(get_repeated_bytes(inputs[slot], 2)[0])[0].number, 3)
        if room.bots: self.assertEqual(room.sim.accepted_inputs[0], encode_frame(0, inputs))
        if ready:
            for peer in peers: await peer.send(wire.READY, wire.ready(room.match_id))

    async def test_version_two_acknowledges_public_capability_and_legacy_stays_custom_only(self):
        await self.start_public()
        modern, legacy = await self.online(), await self.online(version=1)
        self.assertTrue(self.server.community.sessions[modern.profile].peer.command_scheduling_public)
        self.assertFalse(self.server.community.sessions[legacy.profile].peer.command_scheduling_public)
        legacy.ticket = 1
        reason = await self.public_command(legacy, q.ENTER, mode=1, deck=legacy.deck, wait_ms=0, ok=False)
        self.assertIn('Custom', reason)
        self.assertFalse(self.workers)

    async def test_disabled_server_rejects_new_negotiation(self):
        await self.start_public(enabled=False)
        peer = await self.online(version=None)
        await peer.send(wire.NEGOTIATE, b'\x02')
        self.assertIn(b'disabled', await peer.receive(p.ERROR))
        self.assertFalse(self.workers)

    async def test_supported_public_rosters_use_arrival_with_humans_and_worker_owned_bots(self):
        # Fifteen distinct test players share one loopback address in this one
        # fixture. Do not make roster coverage depend on the wall-clock refill
        # of the separate admission rate-limit policy (default burst is eight).
        await self.start_public(admission_burst=15)
        for mode, humans in ((1, 2), (2, 1), (2, 2), (2, 3), (2, 4), (5, 1), (5, 2)):
            with self.subTest(mode=mode, humans=humans):
                peers = [await self.online() for _ in range(humans)]
                for peer in peers: await self.queue(peer, mode=mode)
                if humans < len(q.MODES[mode][1]): self.advance(30)
                room = await self.accept(peers)
                self.assertTrue(room.command_scheduling)
                self.assertEqual(len(room.peers), humans)
                self.assertEqual(set(room.bots), room.slots - room.peers.keys())
                self.assertEqual(room.command_scheduler.slots, room.peers.keys())
                for peer in peers: await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
                for peer in peers: await peer.receive(p.START)
                await self.start_arrival_ticks(room, peers)
                await wait_until(lambda: room.frame >= 3)
                self.assertEqual(room.command_ready, room.peers.keys())
                for number in (1, 2):
                    frames = [await peer.receive(q.FRAME) for peer in peers]
                    self.assertEqual(len(set(frames)), 1)
                    frame, inputs = q.decode_frame(frames[0], len(room.slots))
                    self.assertEqual(frame, number)
                    if room.bots: self.assertEqual(room.sim.accepted_inputs[number], encode_frame(number, inputs))
                await room.finish('authored result', result={'complete': True})
                for peer in peers: await self.public_command(peer, q.RETURN, match=room.match_id)

    async def test_solo_fallback_waits_full_thirty_seconds_before_selecting_arrival_ai(self):
        await self.start_public()
        peer = await self.online()
        await self.queue(peer)
        self.assertFalse(self.public.offers)
        self.advance(29.999); self.assertFalse(self.public.offers)
        self.advance(.001)
        self.assertEqual(len(self.offer(peer).entries), 1)
        self.assertFalse(self.workers)
        room = await self.accept([peer])
        self.assertTrue(room.command_scheduling)
        self.assertEqual(set(room.bots), {1})

    async def test_buffered_and_arrival_cohorts_do_not_mix_and_each_keeps_exact_deadline(self):
        await self.start_public()
        for mode in (1, 2, 5):
            with self.subTest(mode=mode):
                first, second = await self.online(), await self.online(version=None)
                await self.queue(first, mode=mode); await self.queue(second, mode=mode)
                self.assertIsNone(self.public.entries[first.profile].offer)
                self.assertIsNone(self.public.entries[second.profile].offer)
                self.advance(29.999)
                self.assertIsNone(self.public.entries[first.profile].offer)
                self.assertIsNone(self.public.entries[second.profile].offer)
                self.advance(.001)
                self.assertNotEqual(self.offer(first).id, self.offer(second).id)
                self.assertEqual(len(self.offer(first).entries), 1)
                self.assertEqual(len(self.offer(second).entries), 1)
                self.assertTrue(self.offer(first).entries[0].command_scheduling)
                self.assertFalse(self.offer(second).entries[0].command_scheduling)
                await self.public_command(first, q.CANCEL)
                await self.public_command(second, q.CANCEL)
        self.assertFalse(self.workers)

    async def test_two_new_clients_match_before_deadline_using_arrival_input(self):
        await self.start_public()
        peers = [await self.online(), await self.online()]
        for peer in peers: await self.queue(peer)
        room = await self.accept(peers)
        self.assertTrue(room.command_scheduling); self.assertFalse(room.bots)
        for peer in peers: await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        for peer in peers: await peer.receive(p.START)
        await self.start_arrival_ticks(room, peers)
        await wait_until(lambda: room.frame >= 3)

    async def test_solo_human_join_bot_frame_zero_and_one_human_ready_gate_idle_progress(self):
        room, peer = await self.solo()
        self.assertTrue(room.command_scheduling)
        self.assertEqual(set(room.peers), {0}); self.assertEqual(set(room.bots), {1})
        self.assertEqual(room.command_scheduler.slots, {0})
        await asyncio.sleep(.06); self.assertEqual(room.frame, 0)
        await self.start_ticks(room, peer, ready=False)
        await asyncio.sleep(.07); self.assertEqual(room.frame, 1)
        await peer.send(wire.HEARTBEAT, wire.heartbeat(room.match_id, 0))
        await peer.send(wire.READY, wire.ready(room.match_id))
        await wait_until(lambda: room.frame >= 4)
        self.assertEqual(room.command_ready, {0})
        self.assertEqual(len([row for row in self.events if row['event'] == 'command_batch_committed']), 1)
        for number in range(1, 4):
            received = await peer.receive(q.FRAME)
            frame, inputs = q.decode_frame(received, 2)
            self.assertEqual(frame, number)
            self.assertEqual(room.sim.accepted_inputs[number], encode_frame(number, inputs))
        self.assertFalse(any(kind == p.FRAME for kind, _ in peer.observed))

    async def test_heartbeat_does_not_extend_missing_ready_deadline(self):
        room, peer = await self.solo(input_timeout=.2)
        await self.start_ticks(room, peer, ready=False)
        for _ in range(7):
            await asyncio.sleep(.04)
            await peer.send(wire.HEARTBEAT, wire.heartbeat(room.match_id, 0))
        self.assertEqual(room.state, 'closed'); self.assertEqual(room.frame, 1)
        self.assertTrue(any(row['event'] == 'match_aborted' and row['reason'] == 'startup presentation readiness stalled'
                            for row in self.events))

    async def test_result_return_requeues_fresh_match_with_clean_command_state(self):
        room, peer = await self.solo()
        await self.start_ticks(room, peer)
        await wait_until(lambda: room.frame >= 3)
        await peer.send(wire.HEARTBEAT, wire.heartbeat(room.match_id, 1))
        await wait_until(lambda: room.peers[0].command_last_applied == 1)
        await room.finish('authored result', result={'complete': True})
        await self.public_command(peer, q.RETURN, match=room.match_id)
        await self.queue(peer, ticket=2, wait_ms=0)
        following = await self.accept([peer])
        self.assertNotEqual(room.match_id, following.match_id)
        self.assertTrue(following.command_scheduling)
        self.assertEqual(following.command_scheduler.next_sequence, {0: 1})
        self.assertEqual(following.command_ready, set())
        await peer.send(wire.HEARTBEAT, wire.heartbeat(following.match_id, -1))
        await wait_until(lambda: following.peers[0].command_last_applied == -1)

    async def test_ordinary_solo_ai_still_uses_numbered_buffered_input(self):
        await self.start_public()
        peer = await self.online(version=None)
        await self.queue(peer, wait_ms=0)
        room = await self.accept([peer])
        self.assertFalse(room.command_scheduling)
        await self.play_frames(room, [peer])

    async def test_human_cannot_submit_bot_identity_and_failed_batch_does_not_consume_sequence(self):
        room, peer = await self.solo()
        with self.assertRaises(ValueError):
            await room.on_message(room.peers[0], wire.BATCH,
                                  wire.batch(room.match_id, 1, join_body(room.match, 1)))
        self.assertEqual(room.command_scheduler.next_sequence, {0: 1})
        self.assertEqual(room.command_scheduler.joined, set())
        await self.start_ticks(room, peer)
        await wait_until(lambda: room.frame >= 2)

    async def test_batch_during_bot_preparation_is_committed_in_next_frame_once(self):
        room, peer = await self.solo()
        entered, release = asyncio.Event(), asyncio.Event()
        original = room.sim.bot_inputs

        async def held_bot(frame):
            if frame == 1:
                entered.set(); await release.wait()
            return await original(frame)

        with mock.patch.object(room.sim, 'bot_inputs', held_bot):
            try:
                await self.start_ticks(room, peer)
                await asyncio.wait_for(entered.wait(), 2)
                room.entity_history[42] = (0, 100)
                body = encode_player_input(room.match.identities_by_slot[0], [authored.execute([authored.group((42,))])])
                await peer.send(wire.BATCH, wire.batch(room.match_id, 2, body))
                await wait_until(lambda: any(row['event'] == 'command_batch_accepted' and row['sequence'] == 2 for row in self.events))
                accepted = next(row for row in self.events if row['event'] == 'command_batch_accepted' and row['sequence'] == 2)
                self.assertEqual(accepted['earliest_frame'], 2)
            finally: release.set()
            await wait_until(lambda: any(row['event'] == 'command_batch_committed' and row['sequence'] == 2 for row in self.events))
        committed = [row for row in self.events if row['event'] == 'command_batch_committed' and row['sequence'] == 2]
        self.assertEqual(len(committed), 1)
        self.assertEqual(committed[0]['frame'], 2)
        self.assertEqual(committed[0]['body_sha256'], accepted['body_sha256'])

    async def test_disconnect_aborts_match_and_reaps_the_owned_worker(self):
        room, peer = await self.solo()
        worker = room.sim
        await self.start_ticks(room, peer)
        await wait_until(lambda: room.frame >= 2)
        await peer.close()
        await wait_until(lambda: room.state == 'closed' and worker.closed and
                         peer.profile not in self.server.community.sessions)
        self.assertFalse(self.public.entries); self.assertFalse(self.public.offers)
        self.assertEqual(self.server.room_count(), 0)
        self.assertIsNotNone(worker.process.poll())


if __name__ == '__main__': unittest.main()
