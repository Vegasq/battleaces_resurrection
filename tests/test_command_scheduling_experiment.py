"""Opt-in arrival commands: strict validation, startup barrier and immutable frame sealing."""
import asyncio
import copy
import hashlib
import importlib
import json
from pathlib import Path
import secrets
import struct
import tempfile
import unittest
from unittest import mock
import uuid

from server import admission, community_protocol as c, protocol as p, public_protocol as q, tls_transport as tls
from server.game_data import InputError, InputValidation, encode_player_input
from server.protobuf_wire import field_bytes, field_uint, get_repeated_bytes
from tests import test_community as community_fixture, test_input_validation as authored
from tests.synthetic import template
from tests.test_dedicated_server import DedicatedFixture, TestPeer, wait_until
from tests.test_tls_transport import generate_test_pki, remove_test_pki

ROOT = Path(__file__).resolve().parents[1]


def schema(directory):
    messages = copy.deepcopy(authored.GAME)
    action, = [item for item in messages if item['name'] == 'InputAction']
    action['fields'].append(authored.field('join_army', 3, 11, message='.game_pb.JoinArmy', oneof=0))
    messages.extend([
        authored.message('JoinArmy', authored.field('army_id', 1, 13),
                         authored.field('deck', 2, 11, message='.game_pb.Deck'),
                         authored.field('banner', 3, 13), authored.field('portrait', 4, 13)),
        authored.message('Deck', authored.field('units', 1, 13, repeated=True),
                         authored.field('groups', 2, 13, repeated=True)),
    ])
    for package, items in [('common_pb', authored.COMMON), ('game_pb', messages)]:
        (directory / (package + '.proto.json')).write_text(json.dumps(dict(package=package, messages=items)))


def join_body(match, slot):
    action = field_bytes(3, field_uint(1, slot) + field_bytes(2, match.deck_messages_by_slot[slot]))
    return encode_player_input(match.identities_by_slot[slot], [action])


class ArrivalSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module('server.command_scheduling')
        self.directory = tempfile.TemporaryDirectory(prefix='ba-arrival-schema-')
        self.addCleanup(self.directory.cleanup)
        directory = Path(self.directory.name); schema(directory)
        self.template = template(); self.template.descriptors_path = directory
        self.template.entity_abilities = {100: {7}}
        self.match = self.template.build_match([dict(slot=i, player_id=i+1, name='Player '+str(i)) for i in (0, 1)],
                                               self.template.default_decks, seed=17)
        self.owners = {42: (0, 100), 43: (0, 100), 90: (1, 100)}
        self.validation = InputValidation(self.match, self.template, entity_lookup=self.owners.get)
        self.scheduler = self.api.ArrivalScheduler(self.validation, (0, 1))

    def body(self, ids=(42,), count=1):
        return encode_player_input(self.match.identities_by_slot[0],
                                   [authored.execute([authored.group(ids)])] * count)

    def bootstrap(self):
        for slot in (0, 1): self.scheduler.accept(slot, 1, join_body(self.match, slot))
        self.assertIsNotNone(self.scheduler.seal(0)); self.scheduler.commit(0)

    def test_codec_exact_headers_versions_match_identity_and_limits(self):
        identity = 'a' * 32
        packet = self.api.batch(identity, 1, b'body')
        self.assertEqual(packet[:41], b'\x01' + identity.encode() + struct.pack('<Q', 1))
        self.assertEqual(self.api.decode_batch(packet), (identity, 1, b'body'))
        self.assertEqual(self.api.decode_heartbeat(self.api.heartbeat(identity, -1)), (identity, -1))
        self.assertEqual(len(self.api.heartbeat(identity, 23)), 37)
        self.assertEqual(self.api.ready(identity), b'\x01' + identity.encode())
        self.assertEqual(self.api.decode_ready(self.api.ready(identity)), identity)
        for raw in (packet[:40], b'\x02' + packet[1:], b'\x01' + b'A'*32 + packet[33:],
                    packet[:33] + bytes(8), packet + b'x' * 65536):
            with self.subTest(raw_size=len(raw)), self.assertRaises(p.ProtocolError): self.api.decode_batch(raw)
        for raw in (b'', self.api.heartbeat(identity, -1) + b'x', b'\x02' + self.api.heartbeat(identity, 0)[1:]):
            with self.assertRaises(p.ProtocolError): self.api.decode_heartbeat(raw)
        for raw in (b'', b'\x01' + b'a'*31, b'\x01' + b'a'*33, b'\x02' + b'a'*32, b'\x01' + b'A'*32):
            with self.assertRaises(p.ProtocolError): self.api.decode_ready(raw)

    def test_every_human_must_send_its_valid_join_before_any_idle_frame(self):
        self.assertIsNone(self.scheduler.seal(0))
        with self.assertRaisesRegex(p.ProtocolError, 'JoinArmy'): self.scheduler.accept(0, 1, b'')
        with self.assertRaisesRegex(p.ProtocolError, 'JoinArmy'): self.scheduler.accept(0, 1, self.body())
        self.scheduler.accept(0, 1, join_body(self.match, 0))
        self.assertIsNone(self.scheduler.seal(0))
        self.scheduler.accept(1, 1, join_body(self.match, 1))
        first = self.scheduler.seal(0)
        self.assertEqual([len(get_repeated_bytes(first.inputs[slot], 2)) for slot in (0, 1)], [1, 1])
        with self.assertRaises(TypeError): first.inputs[0] = b''

    def test_no_join_fabrication_duplicates_or_late_join(self):
        duplicate = encode_player_input(self.match.identities_by_slot[0], get_repeated_bytes(join_body(self.match, 0), 2) * 2)
        with self.assertRaisesRegex(p.ProtocolError, 'JoinArmy'): self.scheduler.accept(0, 1, duplicate)
        self.bootstrap()
        with self.assertRaisesRegex(p.ProtocolError, 'JoinArmy'): self.scheduler.accept(0, 2, join_body(self.match, 0))

    def test_sequence_is_contiguous_and_invalid_batch_never_mutates_it(self):
        self.bootstrap()
        for sequence in (1, 3, True):
            with self.assertRaises(p.ProtocolError): self.scheduler.accept(0, sequence, self.body())
        with self.assertRaisesRegex(InputError, 'not owned'): self.scheduler.accept(0, 2, self.body((90,)))
        self.assertEqual(self.scheduler.next_sequence[0], 2)
        accepted = self.scheduler.accept(0, 2, self.body())
        self.assertEqual(accepted.body_sha256, hashlib.sha256(self.body()).hexdigest())

    def test_identical_orders_are_retained_and_batches_keep_fifo_order(self):
        self.bootstrap()
        for sequence, ids in ((2, (42,)), (3, (42,)), (4, (43,))): self.scheduler.accept(0, sequence, self.body(ids))
        sealed = self.scheduler.seal(1)
        expected = [authored.execute([authored.group(ids)]) for ids in ((42,), (42,), (43,))]
        self.assertEqual(get_repeated_bytes(sealed.inputs[0], 2), tuple(expected))
        self.assertEqual([batch.sequence for batch in self.scheduler.commit(1)], [2, 3, 4])

    def test_arrival_during_inflight_frame_is_not_retrospective_or_lost(self):
        self.bootstrap(); self.scheduler.accept(0, 2, self.body())
        sealed = self.scheduler.seal(1)
        self.scheduler.accept(0, 3, self.body((43,)))
        self.assertEqual(self.scheduler.next_frame, 2)
        with self.assertRaises(p.ProtocolError): self.scheduler.seal(2)
        self.assertEqual([batch.sequence for batch in self.scheduler.commit(1)], [2])
        following = self.scheduler.seal(2)
        self.assertNotEqual(sealed.inputs[0], following.inputs[0])
        self.assertEqual([batch.sequence for batch in self.scheduler.commit(2)], [3])

    def test_validated_empty_selection_noop_is_preserved_as_a_sequence_disposition(self):
        self.bootstrap(); self.scheduler.accept(0, 2, self.body(()))
        frame = self.scheduler.seal(1)
        self.assertEqual(get_repeated_bytes(frame.inputs[0], 2), ())
        batch, = self.scheduler.commit(1)
        self.assertEqual((batch.sequence, batch.action_count), (2, 0))

    def test_whole_batch_packing_never_splits_or_exceeds_action_limit(self):
        self.bootstrap()
        self.scheduler.accept(0, 2, self.body(count=200)); self.scheduler.accept(0, 3, self.body(count=100))
        first = self.scheduler.seal(1)
        self.assertEqual(len(get_repeated_bytes(first.inputs[0], 2)), 200)
        self.assertEqual([batch.sequence for batch in self.scheduler.commit(1)], [2])
        second = self.scheduler.seal(2)
        self.assertEqual(len(get_repeated_bytes(second.inputs[0], 2)), 100)
        self.assertEqual([batch.sequence for batch in self.scheduler.commit(2)], [3])

    def test_queue_overflow_and_seal_revalidation_fail_before_partial_mutation(self):
        self.scheduler = self.api.ArrivalScheduler(self.validation, (0, 1), max_queued_batches=2)
        self.scheduler.accept(0, 1, join_body(self.match, 0)); self.scheduler.accept(0, 2, self.body())
        with self.assertRaisesRegex(p.ProtocolError, 'capacity'): self.scheduler.accept(0, 3, self.body())
        self.assertEqual(self.scheduler.next_sequence[0], 3)
        self.assertEqual(self.scheduler.queued_sequences[0], (1, 2))
        self.scheduler.accept(1, 1, join_body(self.match, 1))
        self.owners[42] = (1, 100)
        with self.assertRaises(InputError): self.scheduler.seal(0)
        self.assertEqual(self.scheduler.next_frame, 0)
        self.assertEqual(self.scheduler.queued_sequences[0], (1, 2))

    def test_byte_budget_boundary_is_atomic_and_whole_batches_never_exceed_frame_bytes(self):
        initial = join_body(self.match, 0)
        exact = self.api.ArrivalScheduler(self.validation, (0, 1), max_queued_bytes=len(initial))
        exact.accept(0, 1, initial)
        with self.assertRaisesRegex(p.ProtocolError, 'capacity'): exact.accept(0, 2, self.body())
        self.assertEqual(exact.queued_sequences[0], (1,))
        too_small = self.api.ArrivalScheduler(self.validation, (0, 1), max_queued_bytes=len(initial)-1)
        with self.assertRaisesRegex(p.ProtocolError, 'capacity'): too_small.accept(0, 1, initial)
        self.assertEqual(too_small.next_sequence[0], 1); self.assertEqual(too_small.joined, set())
        self.bootstrap()
        ids = tuple(range(100000, 104096))
        self.owners.update({entity: (0, 100) for entity in ids})
        body = self.body(ids, count=4)
        self.assertLess(len(body), 65536); self.assertGreater(len(body)*2, 65536)
        self.scheduler.accept(0, 2, body); self.scheduler.accept(0, 3, body)
        for frame, sequence in ((1, 2), (2, 3)):
            sealed = self.scheduler.seal(frame)
            self.assertLessEqual(len(sealed.inputs[0]), 65536)
            self.assertEqual(get_repeated_bytes(sealed.inputs[0], 2), get_repeated_bytes(body, 2))
            self.assertEqual([item.sequence for item in self.scheduler.commit(frame)], [sequence])

    def test_identity_ability_ownership_debug_and_action_limits_remain_strict(self):
        self.bootstrap()
        bad = [encode_player_input(self.match.identities_by_slot[1], [authored.execute([authored.group((42,))])]),
               encode_player_input(self.match.identities_by_slot[0], [authored.execute([authored.group((42,), ability=999)])]),
               self.body((90,)), self.body(count=257), self.body() + field_uint(3, 1), b'\x00']
        for body in bad:
            with self.subTest(size=len(body)), self.assertRaises(InputError): self.scheduler.accept(0, 2, body)
            self.assertEqual(self.scheduler.next_sequence[0], 2)
            self.assertEqual(self.scheduler.queued_sequences[0], ())


class ArrivalNetworkTests(DedicatedFixture):
    command = community_fixture.CommunityTests.command
    invite_pair = community_fixture.CommunityTests.invite_pair
    start_pair = community_fixture.CommunityTests.start_pair

    @classmethod
    def setUpClass(cls):
        cls.pki_folder = ROOT / 'local' / ('arrival-pki-' + uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.pki_folder)

    @classmethod
    def tearDownClass(cls): remove_test_pki(cls.pki_folder)

    async def asyncSetUp(self):
        await super().asyncSetUp()
        directory = Path(self.template.descriptors_path)
        (directory / 'authored.proto.json').unlink()
        schema(directory)
        self.template.entity_abilities = {100: {7}}

    async def start_experiment(self, enabled=True, **kwargs):
        gate = admission.AdmissionController(None, rc_open=True)
        await self.start(tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']), admission=gate,
                         experimental_command_scheduling=enabled, **kwargs)

    async def online(self, *, negotiate=False):
        reader, writer = await tls.open_verified_connection(*self.address[:2], tls.rc_client_context('127.0.0.1'))
        profile = await admission.authenticate_client(reader, writer, 'ba1_' + secrets.token_urlsafe(32), rc_open=True)
        peer = TestPeer(reader, writer); self.clients.append(peer)
        peer.profile, peer.request = profile, 0
        await peer.send(c.HELLO, c.hello(profile, 'Experimental player'))
        value = c.Reader(await peer.receive(c.WELCOME))
        value.number('H'); value.number('H'); value.key(); peer.deck = value.deck(); value.end()
        if negotiate:
            await peer.send(70, b'\x01'); self.assertEqual(await peer.receive(71), b'\x01')
        return peer

    async def experimental_pair(self, **kwargs):
        await self.start_experiment(**kwargs)
        peers = [await self.online(negotiate=True), await self.online(negotiate=True)]
        room = await self.start_pair(await self.invite_pair(*peers), peers)
        return room, peers

    async def send_joins(self, room, peers, *, auto_ready=True):
        api = importlib.import_module('server.command_scheduling')
        for peer in peers: await peer.send(72, api.batch(room.match_id, 1, join_body(room.match, peer.slot)))
        if auto_ready:
            await wait_until(lambda: room.frame >= 1)
            for peer in peers: await peer.send(74, api.ready(room.match_id))

    async def test_disabled_server_rejects_negotiation_before_any_worker(self):
        await self.start_experiment(enabled=False)
        peer = await self.online()
        await peer.send(70, b'\x01')
        self.assertIn(b'disabled', await peer.receive(p.ERROR)); self.assertEqual(self.workers, [])

    async def test_feature_defaults_off_and_rejects_nonboolean_constructor_flags(self):
        await self.start()
        self.assertIs(self.server.experimental_command_scheduling, False)
        for invalid in (None, 0, 1, 'false'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'experimental_command_scheduling'):
                type(self.server)(self.template, self.server.profiles, experimental_command_scheduling=invalid)

    async def test_plaintext_peer_cannot_spoof_experimental_negotiation(self):
        await self.start(experimental_command_scheduling=True)
        peer = await community_fixture.CommunityTests.online(self)
        server_peer = self.server.community.sessions[peer.profile].peer
        await peer.send(70, b'\x01')
        self.assertIn(b'authenticated TLS', await peer.receive(p.ERROR))
        self.assertIs(server_peer.command_scheduling, False); self.assertEqual(self.workers, [])

    async def test_bad_version_renegotiation_and_negotiation_after_lobby_fail_closed(self):
        await self.start_experiment()
        bad_version = await self.online()
        await bad_version.send(70, b'\x02'); await bad_version.receive(p.ERROR)
        repeated = await self.online(negotiate=True)
        await repeated.send(70, b'\x01'); await repeated.receive(p.ERROR)
        in_lobby = await self.online()
        await self.command(in_lobby, c.CREATE, b'\x01')
        await in_lobby.send(70, b'\x01'); await in_lobby.receive(p.ERROR)
        self.assertEqual(self.workers, [])

    async def test_authenticated_idle_negotiation_ack_and_public_guard(self):
        await self.start_experiment()
        peer = await self.online(negotiate=True)
        self.assertTrue(self.server.community.sessions[peer.profile].peer.command_scheduling)
        body = q.command(q.ENTER, peer.request+1, 1, mode=2, deck=peer.deck)
        self.assertIn('solo', await self.command(peer, q.ENTER, body[4:], ok=False))
        self.assertEqual(self.workers, [])

    async def test_mixed_custom_start_fails_before_worker(self):
        await self.start_experiment()
        peers = [await self.online(negotiate=True), await self.online()]
        lobby = await self.invite_pair(*peers)
        reason = await self.command(peers[0], c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision), ok=False)
        self.assertIn('experimental', reason); self.assertEqual(self.workers, [])

    async def test_join_barrier_idle_frames_and_active_wrong_match_rejection(self):
        room, peers = await self.experimental_pair()
        api = importlib.import_module('server.command_scheduling')
        await peers[0].send(72, api.batch(room.match_id, 1, join_body(room.match, peers[0].slot)))
        await asyncio.sleep(.08); self.assertEqual(room.frame, 0)
        await peers[1].send(72, api.batch(room.match_id, 1, join_body(room.match, peers[1].slot)))
        await wait_until(lambda: room.frame >= 1)
        for peer in peers: await peer.send(74, api.ready(room.match_id))
        await wait_until(lambda: room.frame >= 3)
        self.assertTrue(room.command_scheduling)
        self.assertEqual(len([row for row in self.events if row['event'] == 'command_batch_committed']), 2)
        server_peer = room.peers[0]
        with self.assertRaises(p.ProtocolError):
            await room.on_message(server_peer, 73, api.heartbeat('f'*32, -1))
        with self.assertRaises(p.ProtocolError):
            await room.on_message(server_peer, 73, api.heartbeat(room.match_id, room.frame))
        with self.assertRaises(p.ProtocolError):
            await room.on_message(server_peer, 72, api.batch('f'*32, 2, b''))
        await room.finish('authored end')
        await room.on_message(server_peer, 72, b'inflight bytes ignored after completion')
        await room.on_message(server_peer, 74, b'inflight ready ignored after completion')

    async def test_normal_numbered_input_is_rejected_in_experimental_room(self):
        room, peers = await self.experimental_pair()
        await peers[0].send(p.INPUT, struct.pack('<I', 0))
        self.assertIn(b'arrival', await peers[0].receive(p.ERROR))
        self.assertEqual(room.frame, 0)

    async def test_experimental_batch_is_rejected_in_normal_room(self):
        await self.start_experiment()
        peers = [await self.online(), await self.online()]
        room = await self.start_pair(await self.invite_pair(*peers), peers)
        api = importlib.import_module('server.command_scheduling')
        await peers[0].send(72, api.batch(room.match_id, 1, join_body(room.match, peers[0].slot)))
        self.assertIn(b'not negotiated', await peers[0].receive(p.ERROR))

    async def test_heartbeats_cannot_hide_missing_initial_join(self):
        room, peers = await self.experimental_pair(input_timeout=.3)
        api = importlib.import_module('server.command_scheduling')
        await peers[0].send(72, api.batch(room.match_id, 1, join_body(room.match, peers[0].slot)))
        for _ in range(8):
            await asyncio.sleep(.05)
            for peer in peers: await peer.send(73, api.heartbeat(room.match_id, -1))
        self.assertEqual(room.state, 'closed'); self.assertEqual(room.frame, 0)
        self.assertTrue(any(row['event'] == 'match_aborted' and row['reason'] == 'initial JoinArmy stalled' for row in self.events))

    async def test_explicit_abort_retains_uncommitted_queue_disposition_without_fabricating_commit(self):
        room, peers = await self.experimental_pair()
        api = importlib.import_module('server.command_scheduling')
        room.entity_history[42] = (0, 100)
        await peers[0].send(72, api.batch(room.match_id, 1, join_body(room.match, peers[0].slot)))
        body = encode_player_input(room.match.identities_by_slot[0], [authored.execute([authored.group((42,))])])
        await peers[0].send(72, api.batch(room.match_id, 2, body))
        await wait_until(lambda: any(row['event'] == 'command_batch_accepted' and row['sequence'] == 2 for row in self.events))
        await room.finish('authored explicit abort', aborted=True)
        self.assertEqual(room.command_scheduler.queued_sequences[peers[0].slot], (1, 2))
        self.assertFalse(any(row['event'] == 'command_batch_committed' for row in self.events))
        self.assertTrue(any(row['event'] == 'match_aborted' and row['reason'] == 'authored explicit abort' for row in self.events))
        await room.on_message(room.peers[peers[0].slot], 72, b'late completion bytes')

    async def test_same_connection_rematch_accepts_initial_heartbeat_during_loading(self):
        room, peers = await self.experimental_pair()
        api = importlib.import_module('server.command_scheduling')
        await self.send_joins(room, peers)
        await wait_until(lambda: room.frame >= 3)
        await peers[0].send(73, api.heartbeat(room.match_id, 1))
        await wait_until(lambda: room.peers[0].command_last_applied == 1)
        lobby = self.server.community.lobbies[room.community_lobby]
        await room.finish('authored complete')
        for peer in peers: await self.command(peer, c.RETURN, p.encode_string(room.match_id))
        await self.command(peers[0], c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision))
        await self.command(peers[1], c.READY, p.encode_string(lobby.id) + struct.pack('<IB', lobby.epoch, 1))
        await wait_until(lambda: lobby.room is not None and lobby.room.state == 'loading')
        following = lobby.room
        self.assertNotEqual(following.match_id, room.match_id)
        await following.on_message(following.peers[0], 73, api.heartbeat(following.match_id, -1))
        self.assertEqual(following.peers[0].command_last_applied, -1)
        self.assertEqual(following.command_scheduler.next_sequence[0], 1)
        self.assertEqual(following.command_ready, set())
        self.assertIsNone(following.command_startup_deadline)

    async def test_startup_frame_zero_waits_for_both_presentations_and_rebases_steady_clock(self):
        room, peers = await self.experimental_pair()
        api = importlib.import_module('server.command_scheduling')
        await self.send_joins(room, peers, auto_ready=False)
        await wait_until(lambda: room.frame >= 1)
        await asyncio.sleep(.08)
        self.assertEqual(room.frame, 1)
        deadline = room.command_startup_deadline
        await peers[0].send(74, api.ready(room.match_id))
        await wait_until(lambda: room.command_ready == {0})
        for peer in peers: await peer.send(73, api.heartbeat(room.match_id, 0))
        await asyncio.sleep(.06)
        self.assertEqual(room.frame, 1); self.assertEqual(room.command_startup_deadline, deadline)
        await peers[1].send(74, api.ready(room.match_id))
        await wait_until(lambda: room.command_startup_deadline is None)
        released, = [row for row in self.events if row['event'] == 'command_startup_released']
        self.assertAlmostEqual(released['next_tick'] - released['rebased_at'], .05)
        self.assertEqual(room.command_ready, {0, 1})
        await wait_until(lambda: room.frame >= 3)
        release_index = next(index for index, row in enumerate(self.events) if row['event'] == 'command_startup_released')
        frame_one = next(index for index, row in enumerate(self.events) if row['event'] == 'frame_queued' and row['frame'] == 1)
        self.assertLess(release_index, frame_one)

    async def test_startup_ready_rejects_early_duplicate_wrong_match_and_stale_messages(self):
        room, peers = await self.experimental_pair()
        api = importlib.import_module('server.command_scheduling')
        first, second = room.peers[0], room.peers[1]
        with self.assertRaises(p.ProtocolError): await room.on_message(first, 74, api.ready(room.match_id))
        await self.send_joins(room, peers, auto_ready=False)
        await wait_until(lambda: room.frame == 1)
        with self.assertRaises(p.ProtocolError): await room.on_message(first, 74, api.ready('f'*32))
        await room.on_message(first, 74, api.ready(room.match_id))
        with self.assertRaises(p.ProtocolError): await room.on_message(first, 74, api.ready(room.match_id))
        await room.on_message(second, 74, api.ready(room.match_id))
        with self.assertRaises(p.ProtocolError): await room.on_message(second, 74, api.ready(room.match_id))
        await wait_until(lambda: room.frame >= 2)
        with self.assertRaises(p.ProtocolError): await room.on_message(first, 74, api.ready(room.match_id))

    async def test_startup_readiness_deadline_is_fixed_despite_heartbeats(self):
        room, peers = await self.experimental_pair(input_timeout=.2)
        api = importlib.import_module('server.command_scheduling')
        await self.send_joins(room, peers, auto_ready=False)
        await wait_until(lambda: room.frame == 1)
        deadline = room.command_startup_deadline
        await peers[0].send(74, api.ready(room.match_id))
        for _ in range(7):
            await asyncio.sleep(.04)
            for peer in peers: await peer.send(73, api.heartbeat(room.match_id, 0))
        self.assertEqual(room.state, 'closed'); self.assertEqual(room.frame, 1)
        self.assertEqual(room.command_startup_deadline, deadline)
        self.assertTrue(any(row['event'] == 'match_aborted' and row['reason'] == 'startup presentation readiness stalled'
                            for row in self.events))

    async def test_legacy_room_cannot_acknowledge_experimental_startup(self):
        await self.start_experiment()
        peers = [await self.online(), await self.online()]
        room = await self.start_pair(await self.invite_pair(*peers), peers)
        api = importlib.import_module('server.command_scheduling')
        with self.assertRaises(p.ProtocolError): await room.on_message(room.peers[0], 74, api.ready(room.match_id))

    async def test_heartbeat_keeps_idle_match_alive_then_missing_activity_aborts(self):
        room, peers = await self.experimental_pair(input_timeout=.2)
        api = importlib.import_module('server.command_scheduling')
        await self.send_joins(room, peers)
        for _ in range(6):
            await asyncio.sleep(.05)
            for peer in peers: await peer.send(73, api.heartbeat(room.match_id, -1))
        self.assertEqual(room.state, 'running'); self.assertGreater(room.frame, 2)
        await wait_until(lambda: room.state == 'closed', timeout=1)

    async def test_batch_received_during_real_worker_await_commits_only_in_next_frame(self):
        room, peers = await self.experimental_pair()
        api = importlib.import_module('server.command_scheduling')
        entered, release = asyncio.Event(), asyncio.Event()
        original = room.sim.process_frame

        async def hold(actions, **kwargs):
            if room.frame == 1:
                entered.set(); await release.wait()
            return await original(actions, **kwargs)

        with mock.patch.object(room.sim, 'process_frame', hold):
            try:
                await self.send_joins(room, peers)
                await asyncio.wait_for(entered.wait(), 2)
                room.entity_history[42] = (0, 100)
                body = encode_player_input(room.match.identities_by_slot[0], [authored.execute([authored.group((42,))])])
                await peers[0].send(72, api.batch(room.match_id, 2, body))
                await wait_until(lambda: any(row['event'] == 'command_batch_accepted' and row['sequence'] == 2 for row in self.events))
                accepted = next(row for row in self.events if row['event'] == 'command_batch_accepted' and row['sequence'] == 2)
                self.assertEqual(accepted['earliest_frame'], 2)
            finally: release.set()
            await wait_until(lambda: any(row['event'] == 'command_batch_committed' and row['sequence'] == 2 for row in self.events))
        committed = next(row for row in self.events if row['event'] == 'command_batch_committed' and row['sequence'] == 2)
        self.assertGreaterEqual(committed['frame'], 2)
        self.assertEqual(committed['body_sha256'], accepted['body_sha256'])
