"""Loopback lifecycle tests with actual, explicitly synthetic worker processes.

The minimal descriptor schema below is authored for these tests. It accepts only
canonical player identities and empty action lists; production validation is used.
No game-derived assets or fixture bytes are required.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import struct
import unittest
from unittest import mock
import uuid

from server import dedicated_server as coordinator
from server import protocol as p
from server.profiles import ProfileStore
from server.worker_client import SimulationWorker
from server import simulation_worker as ipc
from tests.synthetic import template as synthetic_template

ROOT = Path(__file__).resolve().parents[1]


def test_descriptor():
    def scalar(number, kind):
        return {"number": number, "name": f"synthetic_field_{number}", "type": kind, "label": 1}
    def message(number, name):
        return dict(scalar(number, 11), type_name=".game_pb." + name)
    return {"name": "authored_worker_test.proto", "package": "game_pb", "messages": [
        {"name": "InputActionsByPlayer", "fields": [message(1, "SyntheticIdentity")]},
        {"name": "SyntheticIdentity", "fields": [message(1, "SyntheticNamedUser"), scalar(2, 13)]},
        {"name": "SyntheticNamedUser", "fields": [message(1, "SyntheticHandle"), scalar(2, 9), scalar(4, 9)]},
        {"name": "SyntheticHandle", "fields": [scalar(1, 4), scalar(2, 8)]},
    ]}


async def wait_until(predicate, timeout=3):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(wait(), timeout)


class TestPeer:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.incoming = asyncio.Queue()
        self.observed = []
        self.slot = None
        self.input_window = None
        self.deck = None
        self.bootstrap = None
        self.pump = asyncio.create_task(self.read_loop())

    async def read_loop(self):
        try:
            while True:
                message = await p.receive(self.reader)
                self.observed.append(message)
                self.incoming.put_nowait(message)
        except (asyncio.IncompleteReadError, OSError):
            self.incoming.put_nowait((None, b""))

    async def send(self, kind, payload=b""):
        self.writer.write(p.encode(kind, payload))
        await self.writer.drain()

    async def receive(self, kind, timeout=3):
        async def find():
            while True:
                actual, payload = await self.incoming.get()
                if actual == kind: return payload
                if actual is None or actual == p.ERROR:
                    raise AssertionError(f"expected message {kind}, got {actual}: {payload!r}")
        return await asyncio.wait_for(find(), timeout)

    async def close(self):
        self.writer.close()
        try: await asyncio.wait_for(self.writer.wait_closed(), 1)
        except (OSError, TimeoutError): pass
        if not self.pump.done():
            self.pump.cancel()
        await asyncio.gather(self.pump, return_exceptions=True)


class DedicatedLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = ROOT / "local/test-runs" / ("coordinator-" + uuid.uuid4().hex)
        self.folder.mkdir(parents=True)
        descriptors = self.folder / "authored-schema"
        descriptors.mkdir()
        (descriptors / "authored.proto.json").write_text(json.dumps(test_descriptor()))
        self.template = synthetic_template()
        self.template.descriptors_path = descriptors
        self.workers, self.clients, self.events = [], [], []
        self.server = None

    async def factory(self, data):
        worker = await SimulationWorker.create(data, _test_backend=True, request_timeout=0.3)
        self.workers.append(worker)
        return worker

    async def start(self, **kwargs):
        profiles = ProfileStore(self.folder / "profiles", self.template)
        self.server = coordinator.DedicatedServer(self.template, profiles,
            sim_factory=kwargs.pop("sim_factory", self.factory),
            audit=lambda event, **fields: self.events.append(dict(event=event, **fields)),
            audit_state=False, **kwargs)
        self.address = await self.server.start("127.0.0.1", 0)

    async def connect(self, room, *, profile=None, slot=p.AUTO_SEAT, welcome=True):
        reader, writer = await asyncio.open_connection(*self.address[:2])
        peer = TestPeer(reader, writer)
        self.clients.append(peer)
        await peer.send(p.HELLO, p.hello(slot, profile or "p_" + uuid.uuid4().hex, "Synthetic player", room))
        if welcome:
            response = await peer.receive(p.WELCOME)
            peer.slot, peer.input_window, peer.deck = p.decode_welcome(response)
        return peer

    async def pair(self, room, *, loaded=True):
        first, second = await self.connect(room), await self.connect(room)
        self.assertEqual((first.slot, second.slot), (0, 1))
        await asyncio.gather(first.send(p.LOBBY_READY, b"\x01"), second.send(p.LOBBY_READY, b"\x01"))
        first.bootstrap, second.bootstrap = await asyncio.gather(first.receive(p.BOOTSTRAP), second.receive(p.BOOTSTRAP))
        self.assertEqual(first.bootstrap, second.bootstrap)
        if loaded:
            await asyncio.gather(*(peer.send(p.LOADED, hashlib.sha256(peer.bootstrap).digest()) for peer in (first, second)))
            await asyncio.gather(first.receive(p.START), second.receive(p.START))
        return first, second

    async def advance(self, peers, number):
        await asyncio.gather(*(peer.send(p.INPUT, struct.pack("<I", number)) for peer in peers))
        frames = await asyncio.gather(*(peer.receive(p.FRAME) for peer in peers))
        self.assertEqual(frames[0], frames[1])
        self.assertEqual(struct.unpack_from("<I", frames[0])[0], number)

    async def complete(self, name, peers):
        room = self.server.rooms[name]
        worker = room.sim
        await worker._test_control("complete_next_step")
        for number in range(20):
            await self.advance(peers, number)
        results = await asyncio.gather(*(peer.receive(p.MATCH_END) for peer in peers))
        self.assertEqual(results[0], results[1])
        self.assertTrue(json.loads(results[0])["result"]["complete"])
        await wait_until(lambda: any(row["event"] == "worker_released" and row["worker_pid"] == worker.pid
                                    for row in self.events))
        self.assertEqual(worker.process.poll(), 0)
        return room, worker

    async def asyncTearDown(self):
        if self.server is not None:
            await asyncio.wait_for(self.server.close(), 5)
        await asyncio.gather(*(peer.close() for peer in self.clients))
        await asyncio.gather(*(worker.close() for worker in self.workers))
        for worker in self.workers:
            self.assertIsNotNone(worker.process.poll(), f"worker {worker.pid} leaked")
        # Delete only this uniquely created test directory after checking its root.
        target = self.folder.resolve()
        target.relative_to((ROOT / "local/test-runs").resolve())
        self.assertTrue(target.name.startswith("coordinator-"))
        shutil.rmtree(target)

    async def test_two_network_rooms_crash_isolated_and_no_failed_frame_published(self):
        await self.start(max_rooms=2)
        alpha, beta = await asyncio.gather(self.pair("alpha"), self.pair("beta"))
        failed = self.server.rooms["alpha"].sim
        healthy = self.server.rooms["beta"].sim
        self.assertNotEqual(failed.pid, healthy.pid)
        await failed._test_control("crash_next_step")
        await asyncio.gather(*(peer.send(p.INPUT, struct.pack("<I", 0)) for peer in alpha))
        await self.advance(beta, 0)
        errors = await asyncio.gather(*(peer.receive(p.ERROR) for peer in alpha))
        self.assertTrue(all(b"simulation error" in error for error in errors))
        self.assertFalse(any(kind == p.FRAME for peer in alpha for kind, body in peer.observed))
        self.assertFalse(any(e["event"] == "frame_queued" and e["room"] == "alpha" for e in self.events))
        await self.advance(beta, 1)
        self.assertEqual(healthy.frame, 1)
        self.assertIsNotNone(failed.process.poll())
        self.assertNotIn("alpha", self.server.rooms)

    async def test_welcome_freezes_same_window_for_both_seats(self):
        await self.start(input_window=2)
        first = await self.connect("frozen")
        self.server.input_window = 12  # Only newly created rooms may observe a setting change.
        second = await self.connect("frozen")
        fresh = await self.connect("new_room")
        self.assertEqual((first.input_window, second.input_window, fresh.input_window), (2, 2, 12))
        self.assertEqual(first.deck, list(self.template.default_decks[0]))
        self.assertEqual(second.deck, list(self.template.default_decks[1]))
        self.assertEqual(self.server.rooms["frozen"].input_window, 2)

    async def test_stalled_peer_cannot_accumulate_more_than_negotiated_window(self):
        await self.start()
        for window in (2, 6, 12):
            with self.subTest(window=window):
                self.server.input_window = window
                name = "bounded_" + str(window)
                peers = await self.pair(name)
                room = self.server.rooms[name]
                for frame in range(window):
                    await peers[0].send(p.INPUT, struct.pack('<I', frame))
                await wait_until(lambda: len(room.pending) == window)
                self.assertEqual(room.frame, 0)
                self.assertEqual(set(room.pending), set(range(window)))
                self.assertTrue(all(set(inputs) == {0} for inputs in room.pending.values()))
                await peers[0].send(p.INPUT, struct.pack('<I', window))
                self.assertIn(b'within lookahead', await peers[0].receive(p.ERROR))
                await wait_until(lambda: name not in self.server.rooms)
                self.assertFalse(any(kind == p.FRAME for peer in peers for kind, _ in peer.observed))

    async def test_negotiated_minimum_and_maximum_windows_progress_contiguously(self):
        await self.start()
        for window in (2, 12):
            with self.subTest(window=window):
                self.server.input_window = window
                peers = await self.pair("progress_" + str(window))
                for frame in range(window):
                    await asyncio.gather(*(peer.send(p.INPUT, struct.pack('<I', frame)) for peer in peers))
                for frame in range(window):
                    received = await asyncio.gather(*(peer.receive(p.FRAME) for peer in peers))
                    self.assertEqual(received[0], received[1])
                    self.assertEqual(struct.unpack_from('<I', received[0])[0], frame)
                await self.advance(peers, window)
                await asyncio.gather(*(peer.close() for peer in peers))

    async def test_old_protocol_rejected_before_room_allocation(self):
        await self.start()
        reader, writer = await asyncio.open_connection(*self.address[:2])
        peer = TestPeer(reader, writer)
        self.clients.append(peer)
        old = struct.pack('<H', 2) + p.hello(p.AUTO_SEAT, 'old_client', 'Old client')[2:]
        await peer.send(p.HELLO, old)
        self.assertIn(b'update client and server together', await peer.receive(p.ERROR))
        self.assertEqual(self.server.rooms, {})
        self.assertEqual(self.workers, [])

    async def test_invalid_window_configuration_rejected_before_listen(self):
        for value in (False, True, 0, 1, 13, -1, 6.0, '6', None):
            with self.subTest(value=value), self.assertRaises(p.ProtocolError):
                await self.start(input_window=value)
        self.assertIsNone(self.server)

    async def test_lobby_expiry_releases_name_and_connections(self):
        await self.start(lobby_timeout=0.12)
        peer = await self.connect("idle")
        self.assertIn(b"idle timeout", await peer.receive(p.ERROR))
        await wait_until(lambda: "idle" not in self.server.rooms)
        replacement = await self.connect("idle")
        self.assertEqual(replacement.slot, 0)
        self.assertEqual(self.workers, [])

    async def test_loading_expiry_releases_worker(self):
        await self.start(loading_timeout=0.12)
        peers = await self.pair("loading", loaded=False)
        worker = self.server.rooms["loading"].sim
        errors = await asyncio.gather(*(peer.receive(p.ERROR) for peer in peers))
        self.assertTrue(all(b"loading timeout" in error for error in errors))
        await wait_until(lambda: worker.process.poll() is not None)
        self.assertIsNotNone(worker.process.poll())
        self.assertNotIn("loading", self.server.rooms)

    async def test_input_expiry_releases_worker(self):
        await self.start(input_timeout=0.12)
        peers = await self.pair("stalled")
        worker = self.server.rooms["stalled"].sim
        errors = await asyncio.gather(*(peer.receive(p.ERROR) for peer in peers))
        self.assertTrue(all(b"input stalled" in error for error in errors))
        await wait_until(lambda: worker.process.poll() is not None)
        self.assertIsNotNone(worker.process.poll())
        self.assertFalse(any(kind == p.FRAME for peer in peers for kind, body in peer.observed))

    async def test_shutdown_during_worker_create_cancels_and_reaps_preparing_child(self):
        entered, release = asyncio.Event(), asyncio.Event()
        created = []
        original = SimulationWorker._exchange
        async def delayed(worker, operation, *args, **kwargs):
            result = await original(worker, operation, *args, **kwargs)
            if operation == ipc.CREATE:
                created.append(worker)
                entered.set()
                await release.wait()
            return result
        await self.start()
        with mock.patch.object(SimulationWorker, "_exchange", delayed):
            first, second = await self.connect("prepare"), await self.connect("prepare")
            await asyncio.gather(first.send(p.LOBBY_READY, b"\x01"), second.send(p.LOBBY_READY, b"\x01"))
            await asyncio.wait_for(entered.wait(), 3)
            self.assertEqual(self.server.rooms["prepare"].state, "preparing")
            try:
                await asyncio.wait_for(self.server.close(), 3)
                self.assertTrue(created)
                self.assertTrue(all(worker.process.poll() is not None for worker in created))
                self.assertEqual(self.server.rooms, {})
            finally:
                release.set()
                await asyncio.gather(*(worker.close() for worker in created))

    async def test_completed_room_name_reused_while_old_result_peer_remains(self):
        await self.start(max_rooms=1)
        with mock.patch.object(coordinator, "TICK", 0.001):
            old_peers = await self.pair("reuse")
            old_room, worker = await self.complete("reuse", old_peers)
        self.assertIn(old_room, self.server.retired)
        self.assertNotIn("reuse", self.server.rooms)
        await old_peers[0].close()
        fresh = await self.pair("reuse")
        new_room = self.server.rooms["reuse"]
        self.assertIsNot(old_room, new_room)
        await old_peers[1].close()
        await wait_until(lambda: old_room not in self.server.retired)
        self.assertIs(self.server.rooms["reuse"], new_room)
        await self.advance(fresh, 0)

    async def test_completed_result_socket_expiry(self):
        await self.start(completed_timeout=0.12)
        with mock.patch.object(coordinator, "TICK", 0.001):
            peers = await self.pair("result")
            room, worker = await self.complete("result", peers)
        await asyncio.gather(*(peer.receive(None) for peer in peers))
        self.assertTrue(all(kind != p.ERROR for peer in peers for kind, _ in peer.observed))
        self.assertNotIn(room, self.server.retired)
        self.assertIsNotNone(worker.process.poll())

    async def test_room_name_reusable_during_slow_completed_worker_close(self):
        await self.start(max_rooms=1)
        entered, release = asyncio.Event(), asyncio.Event()
        with mock.patch.object(coordinator, "TICK", 0.001):
            peers = await self.pair("closing_result")
            room = self.server.rooms["closing_result"]
            worker = room.sim
            original_close = worker.close
            async def delayed_close():
                entered.set()
                try:
                    await release.wait()
                finally:
                    await original_close()
            worker.close = delayed_close
            await worker._test_control("complete_next_step")
            try:
                for number in range(20):
                    await self.advance(peers, number)
                await asyncio.wait_for(entered.wait(), 2)
                await peers[0].close()  # Leave while the other peer is still on results.
                replacement = await self.connect("closing_result")
                self.assertEqual(replacement.slot, 0)
                self.assertIsNot(self.server.rooms["closing_result"], room)
                self.assertIn(room, self.server.retired)
                fresh_room = self.server.rooms["closing_result"]
                await peers[1].close()  # Last old peer cancels its room task.
                await wait_until(lambda: room not in self.server.retired)
                self.assertIsNone(worker.process.poll())  # Destructor is still held.
                self.assertTrue(self.server.worker_cleanup)
                self.assertIs(self.server.rooms["closing_result"], fresh_room)
            finally:
                release.set()
                worker.close = original_close
            await wait_until(lambda: any(row["event"] == "worker_released" and row["worker_pid"] == worker.pid
                                        for row in self.events))
            self.assertEqual(worker.process.poll(), 0)
            self.assertIs(self.server.rooms["closing_result"], fresh_room)

    async def test_capacity_and_global_profile_identity_are_enforced(self):
        await self.start(max_rooms=1)
        await self.connect("occupied", profile="same_profile")
        duplicate = await self.connect("occupied", profile="same_profile", welcome=False)
        self.assertIn(b"profile already connected", await duplicate.receive(p.ERROR))
        another = await self.connect("other", welcome=False)
        self.assertIn(b"capacity", await another.receive(p.ERROR))
        self.assertEqual(set(self.server.rooms), {"occupied"})

    async def test_twenty_sequential_completed_matches_release_every_worker(self):
        await self.start(max_rooms=1)
        with mock.patch.object(coordinator, "TICK", 0.001):
            for cycle in range(20):
                with self.subTest(cycle=cycle):
                    peers = await self.pair("sequential")
                    room, worker = await self.complete("sequential", peers)
                    await asyncio.gather(*(peer.close() for peer in peers))
                    await wait_until(lambda: room not in self.server.retired)
                    self.assertEqual(self.server.rooms, {})
                    self.assertEqual(worker.process.poll(), 0)
        self.assertEqual(len(self.workers), 20)
        self.assertEqual(sum(e["event"] == "worker_released" for e in self.events), 20)
        self.assertEqual(sum(e["event"] == "match_completed" for e in self.events), 20)
        self.assertFalse(any(e["event"] in ("simulation_error", "connection_error") for e in self.events))


if __name__ == "__main__":
    unittest.main()
