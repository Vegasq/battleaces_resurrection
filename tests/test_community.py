"""Community sessions exercised through real sockets and supervised test workers."""
import asyncio
import hashlib
import struct
import uuid

from server import community_protocol as c, protocol as p
from tests.test_dedicated_server import DedicatedFixture, TestPeer, wait_until


def roster(payload):
    r = c.Reader(payload)
    revision, count = r.number('Q'), r.number('H')
    rows = {r.key(): (r.text(), r.number('B'), r.flag()) for _ in range(count)}
    r.end()
    return revision, rows


class CommunityTests(DedicatedFixture):
    async def test_practice_reserves_presence_and_cancels_pending_invites(self):
        await self.start()
        host, player = await self.online('practice_host'), await self.online('practice_player')
        lobby_id = await self.command(host, c.CREATE, b'\x01')
        invite = await self.command(host, c.INVITE, p.encode_string(player.profile))
        await self.command(player, c.PRACTICE, b'\x01')
        session = self.server.community.sessions[player.profile]
        self.assertTrue(session.practicing)
        self.assertIsNone(session.lobby)
        self.assertNotIn(invite, self.server.community.invites)
        row = next(row for row in self.server.community.directory_rows if row[0] == player.profile)
        self.assertEqual(row[2:], (c.UNAVAILABLE, False))
        await self.command(host, c.INVITE, p.encode_string(player.profile), ok=False)
        await self.command(player, c.REPLY, p.encode_string(invite) + b'\x01', ok=False)
        await self.command(player, c.CREATE, b'\x01', ok=False)
        await self.command(player, c.PRACTICE, b'\x01')  # Retry cannot create a room/worker.
        self.assertEqual(len(self.server.community.lobbies), 1)
        await self.command(player, c.PRACTICE, b'\x00')
        self.assertFalse(session.practicing)
        invite = await self.command(host, c.INVITE, p.encode_string(player.profile))
        self.assertEqual(await self.command(player, c.REPLY, p.encode_string(invite) + b'\x01'), lobby_id)
        await self.command(player, c.PRACTICE, b'\x01', ok=False)
        self.assertFalse(session.practicing)

    async def test_practice_flag_is_bounded(self):
        for body in (b'', b'\x02', b'\x01\x00'):
            with self.assertRaises(p.ProtocolError):
                c.decode_command(c.PRACTICE, struct.pack('<I', 1) + body)

    async def online(self, profile=None, name=None):
        profile = profile or 'p_' + uuid.uuid4().hex
        reader, writer = await asyncio.open_connection(*self.address[:2])
        peer = TestPeer(reader, writer)
        peer.profile, peer.request = profile, 0
        self.clients.append(peer)
        await peer.send(c.HELLO, c.hello(profile, name or ('Player ' + profile[:8])))
        data = c.Reader(await peer.receive(c.WELCOME))
        self.assertEqual((data.number('H'), data.number('H')), (c.VERSION, p.VERSION))
        self.assertEqual(data.key(), profile)
        peer.deck = data.deck()
        data.end()
        return peer

    async def command(self, peer, kind, body=b'', *, ok=True):
        peer.request += 1
        await peer.send(kind, struct.pack('<I', peer.request) + body)
        reply = c.Reader(await peer.receive(c.ACK))
        self.assertEqual(reply.number('I'), peer.request)
        self.assertEqual(reply.number('B'), kind)
        accepted, reason, identity = reply.flag(), reply.text(), reply.text()
        reply.end()
        self.assertEqual(accepted, ok, reason)
        return identity if ok else reason

    async def invite_pair(self, first, second):
        identity = await self.command(first, c.CREATE, b'\x01')
        invite = await self.command(first, c.INVITE, p.encode_string(second.profile))
        self.assertEqual(await self.command(second, c.REPLY, p.encode_string(invite) + b'\x01'), identity)
        return self.server.community.lobbies[identity]

    async def start_pair(self, lobby, peers):
        host = next(peer for peer in peers if peer.profile == lobby.host)
        guest = next(peer for peer in peers if peer is not host)
        await self.command(host, c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision))
        self.assertEqual(lobby.phase, c.STARTING)
        self.assertIsNone(lobby.room)
        await self.command(guest, c.READY, p.encode_string(lobby.id) + struct.pack('<IB', lobby.epoch, 1))
        for peer in peers:
            peer.slot, _, peer.deck = p.decode_welcome(await peer.receive(p.WELCOME))
            peer.bootstrap = await peer.receive(p.BOOTSTRAP)
        self.assertEqual(peers[0].bootstrap, peers[1].bootstrap)
        await asyncio.gather(*(peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest()) for peer in peers))
        await asyncio.gather(*(peer.receive(p.START) for peer in peers))
        self.assertEqual(lobby.phase, c.RUNNING)
        return lobby.room

    async def return_pair(self, lobby, peers, match):
        for peer in peers:
            await self.command(peer, c.RETURN, p.encode_string(match))
        self.assertEqual(lobby.phase, c.OPEN)
        self.assertTrue(all(self.server.community.sessions[peer.profile].peer.room is None for peer in peers))

    async def test_directory_has_all_connected_players_without_allocating_seats(self):
        await self.start()
        alpha = await self.online('alice', 'Alice')
        beta = await self.online('bob', 'Bob')
        self.assertEqual(self.server.rooms, {})
        self.assertTrue(all(session.peer.slot is None for session in self.server.community.sessions.values()))
        legacy = await self.connect('ordinary', profile='legacy')
        await wait_until(lambda: any(k == c.DIRECTORY and 'legacy' in roster(v)[1] for k, v in alpha.observed))
        rows = roster([v for k, v in alpha.observed if k == c.DIRECTORY][-1])[1]
        self.assertEqual(rows['alice'], ('Alice', c.AVAILABLE, True))
        self.assertEqual(rows['bob'], ('Bob', c.AVAILABLE, True))
        self.assertEqual(rows['legacy'][1:], (c.IN_LOBBY, False))
        await beta.close()
        await wait_until(lambda: 'bob' not in self.server.community.sessions)
        await wait_until(lambda: 'bob' not in roster([v for k, v in alpha.observed if k == c.DIRECTORY][-1])[1])

    async def test_targeted_invite_host_start_changed_deck_and_two_same_socket_matches(self):
        await self.start()
        first, second, unrelated = await self.online(), await self.online(), await self.online()
        identity = await self.command(first, c.CREATE, b'\x01')
        invite = await self.command(first, c.INVITE, p.encode_string(second.profile))
        await self.command(unrelated, c.REPLY, p.encode_string(invite) + b'\x01', ok=False)
        await self.command(second, c.REPLY, p.encode_string(invite) + b'\x01')
        lobby = self.server.community.lobbies[identity]
        self.assertEqual(self.workers, [])
        self.assertIsNone(self.server.community.sessions[unrelated.profile].lobby)
        await self.command(second, c.START, p.encode_string(identity) + struct.pack('<Q', lobby.revision), ok=False)
        deck = list(self.template.default_decks[1])
        await self.command(first, c.SET_DECK, p.deck_bytes(deck))
        await self.start_pair(lobby, (first, second))
        self.assertEqual(lobby.room.decks[0], deck)
        match1 = lobby.match_id
        await self.complete(lobby.room.name, (first, second))
        self.assertEqual(lobby.phase, c.RESULTS)
        await self.return_pair(lobby, (first, second), match1)
        await self.start_pair(lobby, (first, second))
        self.assertNotEqual(lobby.match_id, match1)
        self.assertEqual(lobby.room.frame, 0)
        match2 = lobby.match_id
        await self.complete(lobby.room.name, (first, second))
        await self.return_pair(lobby, (first, second), match2)
        self.assertEqual(len(self.workers), 2)
        self.assertFalse(any(k in (p.WELCOME, p.BOOTSTRAP, p.START) for k, _ in unrelated.observed))

    async def test_simultaneous_invites_accept_only_one_lobby_and_cancel_others(self):
        await self.start()
        a, b, target = await self.online(), await self.online(), await self.online()
        first = await self.command(a, c.CREATE, b'\x01')
        second = await self.command(b, c.CREATE, b'\x01')
        ia = await self.command(a, c.INVITE, p.encode_string(target.profile))
        ib = await self.command(b, c.INVITE, p.encode_string(target.profile))
        await self.command(target, c.REPLY, p.encode_string(ia) + b'\x01')
        await self.command(target, c.REPLY, p.encode_string(ib) + b'\x01', ok=False)
        self.assertEqual(self.server.community.sessions[target.profile].lobby, first)
        self.assertEqual(self.server.community.lobbies[second].members, [b.profile])
        self.assertEqual(self.server.community.invites, {})

    async def test_decline_cancel_expiry_and_busy_self_invite_keep_sessions_usable(self):
        await self.start()
        a, b = await self.online(), await self.online()
        lobby_id = await self.command(a, c.CREATE, b'\x01')
        await self.command(a, c.INVITE, p.encode_string(a.profile), ok=False)
        invite = await self.command(a, c.INVITE, p.encode_string(b.profile))
        await self.command(b, c.REPLY, p.encode_string(invite) + b'\x00')
        self.assertFalse(self.server.community.invites)
        invite = await self.command(a, c.INVITE, p.encode_string(b.profile))
        await self.command(b, c.CANCEL, p.encode_string(invite), ok=False)
        await self.command(a, c.CANCEL, p.encode_string(invite))
        self.server.community.invite_timeout = 0.05
        invite = await self.command(a, c.INVITE, p.encode_string(b.profile))
        await wait_until(lambda: invite not in self.server.community.invites)
        await self.command(b, c.REPLY, p.encode_string(invite) + b'\x01', ok=False)
        await self.command(b, c.CREATE, b'\x01')
        await self.command(a, c.INVITE, p.encode_string(b.profile), ok=False)
        self.assertEqual(self.server.community.lobbies[lobby_id].members, [a.profile])

    async def test_stale_revision_epoch_and_start_timeout_do_not_create_workers(self):
        await self.start()
        a, b = await self.online(), await self.online()
        lobby = await self.invite_pair(a, b)
        await self.command(a, c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision - 1), ok=False)
        self.server.community.start_timeout = 0.05
        await self.command(a, c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision))
        epoch = lobby.epoch
        await wait_until(lambda: lobby.phase == c.OPEN)
        await self.command(b, c.READY, p.encode_string(lobby.id) + struct.pack('<IB', epoch, 1), ok=False)
        self.assertEqual(self.workers, [])
        self.server.community.start_timeout = 10
        await self.command(a, c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision))
        await self.command(b, c.READY, p.encode_string(lobby.id) + struct.pack('<IB', epoch, 1), ok=False)
        await self.command(b, c.READY, p.encode_string(lobby.id) + struct.pack('<IB', lobby.epoch, 0))
        self.assertEqual(lobby.phase, c.OPEN)

    async def test_host_leave_transfers_host_and_invalidates_pending_start(self):
        await self.start()
        a, b = await self.online(), await self.online()
        lobby = await self.invite_pair(a, b)
        await self.command(a, c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision))
        await self.command(a, c.LEAVE, p.encode_string(lobby.id))
        self.assertEqual((lobby.host, lobby.phase, lobby.members), (b.profile, c.OPEN, [b.profile]))
        self.assertIsNone(self.server.community.sessions[a.profile].lobby)
        await self.command(b, c.INVITE, p.encode_string(a.profile))

    async def test_disconnect_during_match_aborts_only_match_and_survivor_returns(self):
        await self.start()
        a, b, elsewhere = await self.online(), await self.online(), await self.online()
        lobby = await self.invite_pair(a, b)
        room = await self.start_pair(lobby, (a, b))
        match = room.match_id
        await a.close()
        data = c.Reader(await b.receive(c.ABORTED))
        self.assertEqual(data.key(), match)
        self.assertIn('disconnected', data.text())
        data.end()
        self.assertEqual(lobby.host, b.profile)
        await self.command(b, c.RETURN, p.encode_string(match))
        self.assertEqual((lobby.phase, lobby.members), (c.OPEN, [b.profile]))
        await self.command(elsewhere, c.REFRESH)
        await wait_until(lambda: all(w.process.poll() is not None for w in self.workers))

    async def test_worker_failure_does_not_disconnect_directory_or_other_match(self):
        await self.start(max_rooms=2)
        a, b, d, e = await self.online(), await self.online(), await self.online(), await self.online()
        first, second = await self.invite_pair(a, b), await self.invite_pair(d, e)
        await self.start_pair(first, (a, b))
        await self.start_pair(second, (d, e))
        match = first.match_id
        await first.room.sim._test_control('crash_next_step')
        await asyncio.gather(*(peer.send(p.INPUT, struct.pack('<I', 0)) for peer in (a, b)))
        await asyncio.gather(*(peer.receive(c.ABORTED) for peer in (a, b)))
        # Bytes already sent before the abort may arrive after its notification.
        # The retired match must not turn these into a durable-session failure.
        for peer in (a, b):
            await peer.send(p.INPUT, struct.pack('<I', 1))
            await peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest())
            await self.command(peer, c.REFRESH)
        await self.command(a, c.RETURN, p.encode_string('stale_match'), ok=False)
        await self.advance((d, e), 0)
        await self.return_pair(first, (a, b), match)
        await self.command(a, c.REFRESH)
        self.assertEqual(second.phase, c.RUNNING)

    async def test_room_capacity_counts_open_custom_lobbies_and_legacy_cannot_join_match(self):
        await self.start(max_rooms=1)
        a, b, outsider = await self.online(), await self.online(), await self.online()
        lobby = await self.invite_pair(a, b)
        await self.command(outsider, c.CREATE, b'\x01', ok=False)
        room = await self.start_pair(lobby, (a, b))
        intruder = await self.connect(room.name, welcome=False)
        self.assertIn(b'accepted invitation', await intruder.receive(p.ERROR))
        self.assertEqual(set(room.peers), {0, 1})

    async def test_invalid_control_frames_disconnect_only_sender(self):
        await self.start()
        healthy = await self.online()
        for body in (b'', struct.pack('<I', 1), struct.pack('<IB', 1, 1) + b'extra'):
            bad = await self.online()
            await bad.send(c.CREATE, body)
            await bad.receive(p.ERROR)
            await wait_until(lambda: bad.profile not in self.server.community.sessions)
        await self.command(healthy, c.REFRESH)

    async def test_duplicate_request_and_rate_flood_are_bounded(self):
        await self.start()
        duplicate = await self.online()
        await self.command(duplicate, c.REFRESH)
        await duplicate.send(c.REFRESH, struct.pack('<I', duplicate.request))
        self.assertIn(b'IDs must increase', await duplicate.receive(p.ERROR))
        flood = await self.online()
        for request in range(1, 25):
            await flood.send(c.REFRESH, struct.pack('<I', request))
        self.assertIn(b'rate exceeded', await flood.receive(p.ERROR))
        await wait_until(lambda: flood.profile not in self.server.community.sessions)

    async def test_custom_lobby_idle_expiry_releases_capacity(self):
        await self.start(lobby_timeout=0.05, max_rooms=1)
        a = await self.online()
        identity = await self.command(a, c.CREATE, b'\x01')
        await wait_until(lambda: identity not in self.server.community.lobbies)
        self.assertIsNone(self.server.community.sessions[a.profile].lobby)
        await self.command(a, c.CREATE, b'\x01')

    async def test_disconnect_during_setup_reaps_late_worker_without_bootstrap(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(data):
            worker = await self.factory(data)
            entered.set()
            try:
                await release.wait()
                return worker
            except BaseException:
                await worker.close()
                raise

        await self.start(sim_factory=delayed)
        a, b = await self.online(), await self.online()
        lobby = await self.invite_pair(a, b)
        await self.command(a, c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision))
        await self.command(b, c.READY, p.encode_string(lobby.id) + struct.pack('<IB', lobby.epoch, 1))
        await asyncio.wait_for(entered.wait(), 3)
        await a.close()
        packet = c.Reader(await b.receive(c.ABORTED))
        match = packet.key()
        await self.command(b, c.RETURN, p.encode_string(match))
        release.set()
        await wait_until(lambda: not self.server.community.launches)
        self.assertEqual(lobby.phase, c.OPEN)
        self.assertTrue(all(w.process.poll() is not None for w in self.workers))
        self.assertFalse(any(kind == p.BOOTSTRAP for kind, _ in b.observed))

    async def test_failed_worker_creation_returns_both_players_to_reusable_lobby(self):
        async def failed(data):
            raise RuntimeError('synthetic startup failure')

        await self.start(sim_factory=failed)
        a, b = await self.online(), await self.online()
        lobby = await self.invite_pair(a, b)
        await self.command(a, c.START, p.encode_string(lobby.id) + struct.pack('<Q', lobby.revision))
        await self.command(b, c.READY, p.encode_string(lobby.id) + struct.pack('<IB', lobby.epoch, 1))
        await asyncio.gather(*(peer.receive(c.ABORTED) for peer in (a, b)))
        match = lobby.match_id
        await self.return_pair(lobby, (a, b), match)
        self.assertEqual(self.server.rooms, {})
        self.assertFalse(self.workers)

    async def test_wrong_control_version_and_match_packets_before_admission_are_rejected(self):
        await self.start()
        reader, writer = await asyncio.open_connection(*self.address[:2])
        peer = TestPeer(reader, writer)
        self.clients.append(peer)
        await peer.send(c.HELLO, b'\x02\x00' + c.hello('new-player', 'Player')[2:])
        self.assertIn(b'unsupported community', await peer.receive(p.ERROR))
        other = await self.online()
        await other.send(p.INPUT, struct.pack('<I', 0))
        self.assertIn(b'without an assigned match', await other.receive(p.ERROR))
        self.assertEqual(self.server.rooms, {})
