"""Authenticated feedback freezes per-human input leads within existing protocol bounds."""
import asyncio
import json
import math
from pathlib import Path
import secrets
import struct
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

from server import admission, community_protocol as c, dedicated_server as coordinator
from server import protocol as p, public_protocol as q, tls_transport as tls
from server.bot_catalog import BotCatalog
from tests.synthetic import template as synthetic_template
from tests.test_bot_catalog import catalog_fixture
from tests import test_community as community_fixture, test_public_matchmaking as public_fixture
from tests.test_dedicated_server import DedicatedFixture, TestPeer
from tests.test_tls_transport import generate_test_pki, remove_test_pki

ROOT = Path(__file__).resolve().parents[1]


class LatencyPolicyTests(unittest.TestCase):
    def test_configured_minimum_and_wire_bounds(self):
        from server.latency_policy import select_input_window
        for minimum in range(2, 13):
            self.assertEqual(select_input_window(minimum, []), minimum)
            self.assertEqual(select_input_window(minimum, [0, 25]), max(minimum, 3))
            self.assertEqual(select_input_window(minimum, [10000]), 12)
        for invalid in (True, False, None, 1, 13, 6.0, '6'):
            with self.subTest(minimum=invalid), self.assertRaises(p.ProtocolError):
                select_input_window(invalid, [425])

    def test_low_feedback_stays_six_and_asymmetric_feedback_selects_eleven(self):
        from server.latency_policy import select_input_window
        self.assertEqual(select_input_window(6, [20, 45]), 6)
        self.assertEqual(select_input_window(6, [20, 425]), 11)
        self.assertEqual(select_input_window(6, [400]), 10)
        self.assertEqual(select_input_window(6, [400.001]), 11)
        self.assertEqual(select_input_window(12, [425]), 12)

    def test_invalid_or_unmeasured_samples_do_not_invent_latency(self):
        from server.latency_policy import select_input_window
        invalid = [None, True, False, '425', {}, [], -1, math.nan, math.inf, -math.inf]
        self.assertEqual(select_input_window(6, invalid), 6)
        self.assertEqual(select_input_window(2, invalid), 2)
        self.assertEqual(select_input_window(6, [*invalid, 425]), 11)

    def test_per_slot_windows_keep_known_feedback_local_and_unknown_conservative(self):
        from server.latency_policy import select_input_windows
        self.assertEqual(select_input_windows(6, {0: 25, 1: 425}), {0: 6, 1: 11})
        self.assertEqual(select_input_windows(6, {0: None, 1: 425}), {0: 11, 1: 11})
        self.assertEqual(select_input_windows(6, {0: None, 1: math.nan, 2: True, 3: '425'}),
                         {0: 6, 1: 6, 2: 6, 3: 6})
        self.assertEqual(select_input_windows(6, {0: 25, 1: 425, 2: None, 3: -1}),
                         {0: 6, 1: 11, 2: 11, 3: 11})
        self.assertEqual(select_input_windows(12, {0: 25, 1: 425}), {0: 12, 1: 12})
        with self.assertRaises(p.ProtocolError): select_input_windows(True, {0: 425})


class AdaptiveCustomWindowTests(DedicatedFixture):
    online = community_fixture.CommunityTests.online
    command = community_fixture.CommunityTests.command
    invite_pair = community_fixture.CommunityTests.invite_pair
    start_pair = community_fixture.CommunityTests.start_pair

    async def test_asymmetric_custom_window_is_frozen_before_either_welcome(self):
        await self.start(input_window=6, data_dir=self.folder / 'journal')
        peers = [await self.online('custom_low'), await self.online('custom_high')]
        for peer, feedback in zip(peers, (25, 425)):
            self.server.community.sessions[peer.profile].peer.feedback_ms = feedback
        lobby = await self.invite_pair(*peers)
        join = coordinator.Room.join

        async def mutate_after_first_welcome(room, peer, slot, *args, **kwargs):
            await join(room, peer, slot, *args, **kwargs)
            if slot == 0:
                self.server.input_window = 2
                self.server.community.sessions[peers[1].profile].peer.feedback_ms = 0

        with mock.patch.object(coordinator.Room, 'join', mutate_after_first_welcome):
            room = await self.start_pair(lobby, peers)
        self.assertEqual(room.input_window, 11)
        windows = [p.decode_welcome(payload)[1] for peer in peers for kind, payload in peer.observed
                   if kind == p.WELCOME]
        self.assertEqual(windows, [6, 11])
        self.assertEqual(dict(room.input_windows), {0: 6, 1: 11})
        with self.assertRaises(TypeError): room.input_windows[0] = 12
        event, = [row for row in self.events if row['event'] == 'input_window_selected']
        self.assertEqual(event['configured_input_window'], 6)
        self.assertEqual(event['input_window'], 11)
        self.assertEqual(event['feedback_ms'], {0: 25.0, 1: 425.0})
        self.assertEqual(event['input_windows'], {0: 6, 1: 11})
        self.assertIs(event['adaptive'], True)
        metadata = json.loads((self.folder / 'journal/matches' / room.match_id / 'match.json').read_text())
        self.assertEqual(metadata['input_windows'], {'0': 6, '1': 11})
        created, = [row for row in self.events if row['event'] == 'match_created']
        self.assertEqual(created['input_windows'], {0: 6, 1: 11})

    async def test_internal_fixed_policy_control_keeps_six_for_high_feedback(self):
        await self.start(input_window=6, adaptive_input_window=False)
        peers = [await self.online('fixed_low'), await self.online('fixed_high')]
        for peer in peers:
            self.server.community.sessions[peer.profile].peer.feedback_ms = 425
        room = await self.start_pair(await self.invite_pair(*peers), peers)
        self.assertEqual(room.input_window, 6)
        self.assertEqual(dict(room.input_windows), {0: 6, 1: 6})
        event, = [row for row in self.events if row['event'] == 'input_window_selected']
        self.assertIs(event['adaptive'], False)

    async def test_unmeasured_custom_peers_keep_configured_window(self):
        await self.start(input_window=6, adaptive_input_window=True)
        peers = [await self.online('unmeasured_a'), await self.online('unmeasured_b')]
        self.assertTrue(all(self.server.community.sessions[peer.profile].peer.feedback_ms is None for peer in peers))
        room = await self.start_pair(await self.invite_pair(*peers), peers)
        self.assertEqual(room.input_window, 6)
        self.assertEqual(dict(room.input_windows), {0: 6, 1: 6})

    async def test_direct_legacy_welcomes_keep_the_first_room_window(self):
        await self.start(input_window=2, adaptive_input_window=True)
        first = await self.connect('legacy_frozen', profile='legacy_a')
        next(peer for peer in self.server.peers if peer.profile_id == 'legacy_a').feedback_ms = 425
        self.server.input_window = 12
        second = await self.connect('legacy_frozen', profile='legacy_b')
        fresh = await self.connect('legacy_new', profile='legacy_c')
        self.assertEqual((first.input_window, second.input_window, fresh.input_window), (2, 2, 12))
        self.assertEqual(dict(self.server.rooms['legacy_frozen'].input_windows), {0: 2, 1: 2})

    async def test_each_human_has_its_own_strict_negotiated_future_bound(self):
        await self.start(input_window=6)
        clients = [await self.online('bounded_fast'), await self.online('bounded_slow')]
        for client, sample in zip(clients, (25, 425)):
            self.server.community.sessions[client.profile].peer.feedback_ms = sample
        room = await self.start_pair(await self.invite_pair(*clients), clients)
        fast, slow = room.peers[0], room.peers[1]
        for frame in range(6): await room.on_message(fast, p.INPUT, struct.pack('<I', frame))
        with self.assertRaisesRegex(p.ProtocolError, 'within lookahead'):
            await room.on_message(fast, p.INPUT, struct.pack('<I', 6))
        self.assertEqual(fast.next_input, 6)
        for frame in range(11): await room.on_message(slow, p.INPUT, struct.pack('<I', frame))
        self.assertEqual(slow.next_input, 11)
        self.assertEqual(set(room.pending[10]), {1})
        with self.assertRaisesRegex(p.ProtocolError, 'within lookahead'):
            await room.on_message(slow, p.INPUT, struct.pack('<I', 11))
        self.assertEqual(room.frame, 0)

    async def test_mixed_negotiated_leads_progress_contiguously_with_shared_frame_bytes(self):
        await self.start(input_window=6)
        clients = [await self.online('progress_fast'), await self.online('progress_slow')]
        for client, sample in zip(clients, (25, 425)):
            self.server.community.sessions[client.profile].peer.feedback_ms = sample
        room = await self.start_pair(await self.invite_pair(*clients), clients)
        windows = [p.decode_welcome(payload)[1] for client in clients for kind, payload in client.observed
                   if kind == p.WELCOME]
        self.assertEqual(windows, [6, 11])
        for client, window in zip(clients, windows):
            for frame in range(window): await client.send(p.INPUT, struct.pack('<I', frame))
        for frame in range(24):
            packets = await asyncio.gather(*(client.receive(p.FRAME) for client in clients))
            self.assertEqual(packets[0], packets[1])
            self.assertEqual(struct.unpack_from('<I', packets[0])[0], frame)
            for client, window in zip(clients, windows):
                await client.send(p.INPUT, struct.pack('<I', frame + window))
        self.assertGreaterEqual(room.frame, 24)

    async def test_internal_policy_switch_rejects_non_booleans(self):
        for invalid in (None, 0, 1, 'false'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'adaptive_input_window'):
                await self.start(adaptive_input_window=invalid)


class AdaptivePublicWindowTests(DedicatedFixture):
    online = community_fixture.CommunityTests.online
    command = community_fixture.CommunityTests.command
    ai_factory = public_fixture.PublicQueueTests.ai_factory
    public_command = public_fixture.PublicQueueTests.public_command
    queue = public_fixture.PublicQueueTests.queue
    advance = public_fixture.PublicQueueTests.advance
    offer = public_fixture.PublicQueueTests.offer
    accept = public_fixture.PublicQueueTests.accept

    async def start_public(self):
        templates = {1: self.template, 2: synthetic_template(2), 5: synthetic_template(5)}
        for template in templates.values(): template.descriptors_path = self.template.descriptors_path
        data = catalog_fixture()
        data['names'] = ['Latency Alpha', 'Latency Beta', 'Latency Gamma', 'Latency Delta']
        (self.folder / 'bot-catalog.json').write_text(json.dumps(data))
        catalog = BotCatalog(self.folder, template=self.template)
        await self.start(templates=templates, bot_catalog=catalog, ai_factory=self.ai_factory)
        self.public = self.server.community.public
        self.now = 1000.0
        self.public.clock = lambda: self.now

    async def match(self, mode, samples):
        await self.start_public()
        peers = [await self.online('public_' + str(index)) for index in range(len(samples))]
        for peer, feedback in zip(peers, samples):
            self.server.community.sessions[peer.profile].peer.feedback_ms = feedback
            await self.queue(peer, mode=mode)
        if len(peers) < len(q.MODES[mode][1]): self.advance(30.1)
        room = await self.accept(peers)
        return room, peers

    async def test_low_feedback_public_assignments_keep_six(self):
        room, peers = await self.match(1, (20, 45))
        self.assertEqual(room.input_window, 6)
        self.assertEqual([peer.assignment['input_window'] for peer in peers], [6, 6])

    async def test_asymmetric_public_assignments_freeze_each_own_window(self):
        room, peers = await self.match(1, (25, 425))
        self.assertEqual([peer.assignment['input_window'] for peer in peers], [6, 11])
        self.server.input_window = 2
        for peer in room.peers.values(): peer.feedback_ms = 0
        self.assertEqual(room.input_window, 11)
        self.assertEqual(dict(room.input_windows), {0: 6, 1: 11})

    async def test_two_humans_and_ai_adapt_without_treating_bots_as_measured_peers(self):
        room, peers = await self.match(5, (25, 425))
        self.assertEqual(set(room.bots), {1, 3})
        self.assertEqual([peer.assignment['input_window'] for peer in peers], [6, 11])
        event, = [row for row in self.events if row['event'] == 'input_window_selected']
        self.assertEqual(event['feedback_ms'], {0: 25.0, 2: 425.0})
        self.assertEqual(event['input_windows'], {0: 6, 2: 11})

    async def test_unknown_public_feedback_uses_the_known_peer_conservative_window(self):
        room, peers = await self.match(1, (None, 425))
        self.assertEqual([peer.assignment['input_window'] for peer in peers], [11, 11])
        self.assertEqual(dict(room.input_windows), {0: 11, 1: 11})


class AuthenticatedFeedbackMeasurementTests(DedicatedFixture):
    @classmethod
    def setUpClass(cls):
        cls.pki_folder = ROOT / 'local' / ('latency-policy-pki-' + uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.pki_folder)

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.pki_folder)

    async def test_actual_tls_sample_starts_after_auth_ok_and_binds_valid_hello(self):
        gate = admission.AdmissionController(None, rc_open=True)
        await self.start(tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']), admission=gate)
        clock = 10.0
        authenticate = gate.authenticate

        async def authentication_work(reader, writer):
            nonlocal clock
            clock = 100.0  # Arbitrary authentication work must not enter the sample.
            profile = await authenticate(reader, writer)
            clock = 200.0
            return profile

        fake_time = SimpleNamespace(perf_counter=lambda: clock)
        token = 'ba1_' + secrets.token_urlsafe(32)
        with mock.patch.object(gate, 'authenticate', authentication_work), mock.patch.object(coordinator, 'time', fake_time):
            reader, writer = await tls.open_verified_connection(*self.address[:2], tls.rc_client_context('127.0.0.1'))
            profile = await admission.authenticate_client(reader, writer, token, rc_open=True)
            peer = TestPeer(reader, writer); self.clients.append(peer)
            clock = 200.425
            await peer.send(c.HELLO, c.hello(profile, 'Measured player'))
            await peer.receive(c.WELCOME)
            measured = self.server.community.sessions[profile].peer.feedback_ms
        self.assertAlmostEqual(measured, 425.0)
        self.assertNotIn(token, str(self.events))

    async def test_identity_mismatch_never_creates_a_measured_sample(self):
        gate = admission.AdmissionController(None, rc_open=True)
        await self.start(tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']), admission=gate)
        reader, writer = await tls.open_verified_connection(*self.address[:2], tls.rc_client_context('127.0.0.1'))
        await admission.authenticate_client(reader, writer, 'ba1_' + secrets.token_urlsafe(32), rc_open=True)
        server_peer, = self.server.peers
        peer = TestPeer(reader, writer); self.clients.append(peer)
        await peer.send(c.HELLO, c.hello('wrong_identity', 'Rejected player'))
        await peer.receive(p.ERROR)
        self.assertIsNone(server_peer.feedback_ms)
        self.assertFalse(self.server.community.sessions)
