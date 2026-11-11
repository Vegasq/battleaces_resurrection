"""Negotiated public solo AI with TLS clients and explicitly synthetic workers.

These exercise server arbitration and exact AI-byte ownership, not native tactics.
"""
import asyncio
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
from unittest import mock
import uuid

from server import admission, command_scheduling as wire, dedicated_server as coordinator
from server import community_protocol as c, protocol as p, public_protocol as q, tls_transport as tls
from server.bot_catalog import BotCatalog
from server.game_data import decode_identity, encode_frame, encode_player_input
from server.protobuf_wire import field_bytes, get_bytes, get_repeated_bytes, parse_fields
from server.worker_ai import BotRoster
from tests import test_command_scheduling_experiment as arrival, test_input_validation as authored
from tests.synthetic import template as synthetic_template
from tests.test_bot_catalog import catalog_fixture
from tests.test_dedicated_server import DedicatedFixture, wait_until
from tests import test_public_matchmaking as public_tests
from tests.test_tls_transport import generate_test_pki, remove_test_pki


class PredictionPublicAITests(DedicatedFixture):
    command = arrival.ArrivalNetworkTests.command
    online = arrival.ArrivalNetworkTests.online
    public_command = public_tests.PublicQueueTests.public_command
    queue = public_tests.PublicQueueTests.queue
    advance = public_tests.PublicQueueTests.advance
    offer = public_tests.PublicQueueTests.offer
    accept = public_tests.PublicQueueTests.accept

    @classmethod
    def setUpClass(cls):
        cls.pki_folder = Path(__file__).resolve().parents[1] / 'local' / ('public-arrival-pki-' + uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.pki_folder)

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.pki_folder)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        directory = Path(self.template.descriptors_path)
        (directory / 'authored.proto.json').unlink()
        arrival.schema(directory)
        self.template.entity_abilities = {100: {7}}
        self.templates = {1: self.template, 2: synthetic_template(2), 5: synthetic_template(5)}
        for template in self.templates.values():
            template.descriptors_path = directory
        (self.folder / 'bot-catalog.json').write_text(json.dumps(catalog_fixture()), encoding='utf-8')
        self.catalog = BotCatalog(self.folder, template=self.template)
        self.now = 1000.0

    async def start_public(self, **kwargs):
        await self.start(templates=self.templates, bot_catalog=self.catalog, ai_factory=self.ai_factory,
                         tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']),
                         admission=admission.AdmissionController(None, rc_open=True),
                         experimental_command_scheduling=True, **kwargs)
        self.public = self.server.community.public
        self.public.clock = lambda: self.now

    async def ai_factory(self, data, bots):
        worker = await self.factory(data)
        roster = BotRoster(data, bots)
        worker.prepared_inputs, worker.accepted_inputs = {}, {}
        async def inputs(frame):
            # Authored AI UI action demonstrates a nonempty decision after Join.
            result = roster.make_inputs(frame, {1: [field_bytes(5, b'')]} if frame == 1 else {})
            worker.prepared_inputs[frame] = result
            return result
        worker.bot_inputs = inputs
        original = worker.process_frame
        async def record(actions, dt_ms=None):
            frame = worker.frame + 1
            roster.check_frame(actions, worker.prepared_inputs[frame])
            result = await original(actions, dt_ms)
            worker.accepted_inputs[result.frame] = actions
            return result
        worker.process_frame = record
        return worker

    async def solo(self, **kwargs):
        await self.start_public(**kwargs)
        peer = await self.online(negotiate=True)
        await self.queue(peer)
        self.advance(30)
        room = await self.accept([peer])
        await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
        await peer.receive(p.START)
        return room, peer

    async def frame(self, peer, room):
        payload = await peer.receive(q.FRAME)
        return q.decode_frame(payload, len(room.slots))

    async def test_cohorts_never_mix_or_pair_experimental_humans_and_keep_deadline(self):
        await self.start_public()
        ordinary = [await self.online(), await self.online()]
        experimental = [await self.online(negotiate=True), await self.online(negotiate=True)]
        await self.queue(ordinary[0])
        for peer in experimental:
            await self.queue(peer)
        self.assertTrue(all(entry.offer is None for entry in self.public.entries.values()))
        await self.queue(ordinary[1])
        ordinary_offer = self.offer(ordinary[0])
        self.assertIs(self.offer(ordinary[1]), ordinary_offer)
        self.assertEqual({entry.profile for entry in ordinary_offer.entries}, {peer.profile for peer in ordinary})
        self.advance(29.999)
        self.assertTrue(all(self.public.entries[peer.profile].offer is None for peer in experimental))
        self.advance(.001)
        self.assertEqual(len({self.offer(peer).id for peer in experimental}), 2)
        for peer in experimental:
            entry = self.public.entries[peer.profile]
            self.assertEqual(self.offer(peer).entries, (entry,))
            self.assertEqual((entry.entered, entry.deadline), (1000.0, 1030.0))
            with self.assertRaises(FrozenInstanceError):
                entry.cohort.command_scheduling = False
        self.assertEqual(self.workers, [])  # Offer never manufactures a ready human.

    async def test_ordinary_2vai_still_searches_for_real_companion(self):
        await self.start_public()
        first, second = await self.online(), await self.online()
        await self.queue(first, mode=5)
        self.advance(5)
        self.assertIsNone(self.public.entries[first.profile].offer)
        await self.queue(second, mode=5)
        offer = self.offer(first)
        self.assertIs(self.offer(second), offer)
        self.assertEqual(len(offer.entries), 2)
        room = await self.accept([first, second])
        self.assertFalse(room.command_scheduling)
        self.assertEqual(set(room.peers), {0, 2})
        self.assertEqual(set(room.bots), {1, 3})

    async def test_negotiated_team_modes_and_spoofed_tls_are_rejected_before_save(self):
        await self.start_public()
        peer = await self.online(negotiate=True)
        for mode in (2, 5):
            reason = await self.public_command(peer, q.ENTER, ticket=1, mode=mode, deck=peer.deck, ok=False)
            self.assertIn('solo', reason)
        session = self.server.community.sessions[peer.profile]
        session.peer.authenticated_tls = False
        with self.assertRaisesRegex(ValueError, 'TLS'):
            await self.public.apply(session, q.ENTER, dict(ticket=1, mode=1, deck=peer.deck, wait_ms=0), self.now)
        self.assertEqual(session.last_public_ticket, 0)
        self.assertFalse(self.public.busy(peer.profile))
        self.assertEqual(self.workers, [])

    async def test_admission_cannot_change_during_profile_save_or_before_launch(self):
        await self.start_public()
        peer = await self.online(negotiate=True)
        session = self.server.community.sessions[peer.profile]
        original = self.server.community.save_loadout
        async def changed(*args):
            await original(*args)
            session.peer.command_scheduling = False
        with mock.patch.object(self.server.community, 'save_loadout', changed):
            reason = await self.public_command(peer, q.ENTER, ticket=1, mode=1, deck=peer.deck, ok=False)
        self.assertIn('admission', reason)
        self.assertEqual(session.last_public_ticket, 0)
        session.peer.command_scheduling = True
        await self.queue(peer, wait_ms=0)
        entry = self.public.entries[peer.profile]
        session.peer.command_scheduling = False
        await self.public_command(peer, q.READY, match=self.offer(peer).id)
        await wait_until(lambda: not self.public.busy(peer.profile))
        self.assertTrue(entry.cohort.command_scheduling)
        self.assertEqual(self.workers, [])

    async def test_public_solo_real_human_startup_exact_bot_join_merge_and_scheduled_order(self):
        room, peer = await self.solo()
        self.assertTrue(room.command_scheduling)
        self.assertEqual((set(room.peers), set(room.bots)), ({0}, {1}))
        self.assertEqual(peer.assignment['human_mask'], 1)
        self.assertEqual(room.command_scheduler.slots, {0})
        self.assertEqual(decode_identity(room.match.identities_by_slot[0])['ai_profile_id'], 0)
        self.assertEqual(decode_identity(room.match.identities_by_slot[1])['ai_profile_id'], room.bots[1].choice.profile)
        await peer.send(wire.HEARTBEAT, wire.heartbeat(room.match_id, -1))
        await asyncio.sleep(.06)
        self.assertEqual(room.frame, 0)
        self.assertEqual(room.sim.prepared_inputs, {})
        await peer.send(wire.BATCH, wire.batch(room.match_id, 1, arrival.join_body(room.match, 0)))
        number, inputs = await self.frame(peer, room)
        self.assertEqual(number, 0)
        self.assertEqual(set(inputs), {0, 1})
        self.assertEqual(inputs[1], room.sim.prepared_inputs[0][1])
        self.assertEqual([parse_fields(action)[0].number for action in get_repeated_bytes(inputs[1], 2)], [3])
        deadline = room.command_startup_deadline
        await peer.send(wire.HEARTBEAT, wire.heartbeat(room.match_id, 0))
        await asyncio.sleep(.06)
        self.assertEqual(room.frame, 1)
        self.assertEqual(room.command_ready, set())
        self.assertEqual(room.command_startup_deadline, deadline)
        room.entity_history[42] = (0, 100)
        action = authored.execute([authored.group((42,))])
        body = encode_player_input(room.match.identities_by_slot[0], [action])
        await peer.send(wire.BATCH, wire.batch(room.match_id, 2, body))
        await wait_until(lambda: room.command_scheduler.next_sequence[0] == 3)
        await peer.send(wire.READY, wire.ready(room.match_id))
        number, inputs = await self.frame(peer, room)
        self.assertEqual(number, 1)
        self.assertEqual(inputs[0], body)
        self.assertEqual(inputs[1], room.sim.prepared_inputs[1][1])
        self.assertEqual([parse_fields(a)[0].number for a in get_repeated_bytes(inputs[1], 2)], [5])
        self.assertEqual(room.sim.accepted_inputs[1], encode_frame(1, inputs))
        for _ in range(2):
            number, inputs = await self.frame(peer, room)
            self.assertFalse(get_repeated_bytes(inputs[1], 2))
            self.assertEqual(get_bytes(inputs[1], 1), room.match.identities_by_slot[1])
            self.assertEqual(room.sim.accepted_inputs[number], encode_frame(number, inputs))
        self.assertEqual(room.command_ready, {0})
        committed = [row for row in self.events if row['event'] == 'command_batch_committed']
        self.assertEqual([(row['slot'], row['sequence']) for row in committed], [(0, 1), (0, 2)])
        with self.assertRaises(p.ProtocolError):
            await room.on_message(room.peers[0], wire.BATCH, wire.batch(room.match_id, 3, arrival.join_body(room.match, 0)))
        with self.assertRaises(ValueError):
            await room.on_message(room.peers[0], wire.BATCH,
                                  wire.batch(room.match_id, 3, encode_player_input(room.match.identities_by_slot[1])))
        self.assertEqual(room.command_scheduler.next_sequence[0], 3)

    async def test_public_solo_ready_deadline_is_not_extended_by_heartbeats(self):
        room, peer = await self.solo(input_timeout=.2)
        await peer.send(wire.BATCH, wire.batch(room.match_id, 1, arrival.join_body(room.match, 0)))
        await self.frame(peer, room)
        deadline = room.command_startup_deadline
        for _ in range(7):
            await asyncio.sleep(.04)
            await peer.send(wire.HEARTBEAT, wire.heartbeat(room.match_id, 0))
        self.assertEqual(room.state, 'closed')
        self.assertEqual(room.frame, 1)
        self.assertEqual(room.command_startup_deadline, deadline)
        self.assertTrue(any(row['event'] == 'match_aborted' and row['reason'] == 'startup presentation readiness stalled'
                            for row in self.events))

    async def test_room_gate_rejects_public_human_pairs_wrong_bot_seat_and_unnegotiated_peer(self):
        await self.start_public()
        client = await self.online(negotiate=True)
        peer = self.server.community.sessions[client.profile].peer
        choice = self.catalog.choose(1, role='opponents')
        bot = coordinator.BotSeat(1, choice.profile, choice.name, choice.deck.units, choice)
        invalid = [dict(bots=(), feedback_peers={0: peer, 1: peer}),
                   dict(bots=[coordinator.BotSeat(0, choice.profile, choice.name, choice.deck.units, choice)],
                        feedback_peers={1: peer}),
                   dict(mode=2, bots=[bot], feedback_peers={0: peer, 2: peer, 3: peer})]
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(p.ProtocolError):
                coordinator.Room(self.server, 'refused', public_match='a'*32, command_scheduling=True, **options)
        peer.command_scheduling = False
        with self.assertRaises(p.ProtocolError):
            coordinator.Room(self.server, 'refused', public_match='b'*32, bots=[bot],
                             feedback_peers={0: peer}, command_scheduling=True)
        self.assertEqual(self.workers, [])
