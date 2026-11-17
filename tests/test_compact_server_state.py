"""Authored compact session, IPC and Room controls; no original game runtime."""
import asyncio
import copy
import hashlib
import io
import json
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from server import simulation_worker as ipc
from server import worker_client as client
from server.dedicated_server import Room
from server.native_simulation import decode_snapshot
from server.state_projection import STATE_MODES
from tests.snapshot_decoder_fixtures import _build, _changed
from tests.test_dedicated_server import DedicatedFixture
from tests.test_simulation_worker import frame


def projection(mode):
    return {"version": 1, "step_mode": mode}


class ProjectionProtocolTests(unittest.TestCase):
    def run_packets(self, packets, **kwargs):
        sink = io.BytesIO()
        result = ipc.serve(io.BytesIO(b"".join(packets)), sink, **kwargs)
        sink.seek(0)
        replies = []
        while reply := ipc.read_message(sink):
            replies.append(reply)
        return result, replies

    def test_native_explicit_initial_state_step_overrides_and_legacy_query(self):
        raw, meta = _build(4)
        native = Mock(frame=-1, game_data_sha256=hashlib.sha256(b"authored").hexdigest(), dll_sha256="authored")
        def state(viewer=31, **kwargs):
            snapshot = _changed(raw, meta["root_fields"][0], "I", native.frame & 0xffffffff)
            return decode_snapshot(snapshot, viewer, **kwargs)
        native.state.side_effect = state
        def process(*args, **kwargs):
            native.frame += 1
            return 0
        native.process_frame.side_effect = process
        for mode in STATE_MODES:
            native.frame = -1
            packets = [ipc.encode_message(ipc.CREATE, 1, -1, {"state_projection": projection(mode)}, b"authored"),
                       ipc.encode_message(ipc.STATE, 2, -1, {"viewer": 31, "mode": mode}),
                       ipc.encode_message(ipc.STEP, 3, 0, {"dt_ms": 50}, frame(0)),
                       ipc.encode_message(ipc.STATE, 4, 0, {"viewer": 1, "mode": "full"}),
                       ipc.encode_message(ipc.STATE, 5, 0, {"viewer": 31, "include_entities": True}),
                       ipc.encode_message(ipc.CLOSE, 6, 0)]
            with patch("server.native_simulation.NativeSimulation", return_value=native):
                result, replies = self.run_packets(packets)
            self.assertEqual(result, 0)
            self.assertEqual(replies[0][4]["state_projection"], projection(mode))
            self.assertEqual(replies[0][4]["state_projection_modes"], list(STATE_MODES))
            self.assertEqual(replies[1][4]["state"]["frame"], 0xffffffff)
            self.assertEqual(replies[2][4]["state_mode"], mode)
            self.assertEqual(replies[3][4]["state_mode"], "full")
            self.assertEqual(replies[3][4]["state"]["viewer"], 1)
            self.assertEqual(set(replies[4][4]), {"state"})
            self.assertEqual(replies[2][4]["state"]["frame"], 0)

    def test_create_projection_refuses_before_native_world_creation(self):
        invalid = [None, {}, {"version": True, "step_mode": "full"},
                   {"version": 2, "step_mode": "ownership"}, projection(None),
                   projection("bad"), {**projection("full"), "extra": 0}]
        with patch("server.native_simulation.NativeSimulation") as native:
            for value in invalid:
                packet = ipc.encode_message(ipc.CREATE, 1, -1, {"state_projection": value}, b"authored")
                result, replies = self.run_packets([packet])
                self.assertEqual(result, 2)
                self.assertEqual(replies[0][1], ipc.ERROR)
            native.assert_not_called()

    def test_explicit_old_rust_capability_refuses_before_native_world_creation(self):
        decoder = Mock(projection_version=None)
        packet = ipc.encode_message(ipc.CREATE, 1, -1, {"state_projection": projection("full")}, b"authored")
        with patch("server.native_simulation.NativeSimulation") as native, \
             patch("server.rust_snapshot_decoder.RustSnapshotDecoder", return_value=decoder), \
             patch.object(ipc, "os", SimpleNamespace(name="nt", getpid=lambda: 3)):
            result, replies = self.run_packets([packet], snapshot_decoder_library="explicit", snapshot_decoder_sha256="hash")
        self.assertEqual(result, 2)
        native.assert_not_called()
        decoder.decode.assert_not_called()

    def test_explicit_step_refuses_malformed_output_without_ack_and_closes_world(self):
        native = Mock(frame=-1, game_data_sha256=hashlib.sha256(b"authored").hexdigest(), dll_sha256="authored")
        def process(*args, **kwargs):
            native.frame = 0
            return 0
        native.process_frame.side_effect = process
        native.state.return_value = {"frame": 0, "ownership": []}
        packets = [ipc.encode_message(ipc.CREATE, 1, -1, {"state_projection": projection("ownership")}, b"authored"),
                   ipc.encode_message(ipc.STEP, 2, 0, {"dt_ms": 50}, frame(0))]
        with patch("server.native_simulation.NativeSimulation", return_value=native):
            result, replies = self.run_packets(packets)
        self.assertEqual(result, 2)
        self.assertEqual(replies[-1][1], ipc.ERROR)
        self.assertNotIn("state", replies[-1][4])
        native.close.assert_called_once()

    def test_explicit_state_mixed_unknown_and_unnegotiated_metadata_refuse(self):
        for selection, metadata in [(None, {"mode": "full"}),
                                    ("ownership", {"mode": "ownership", "include_entities": False}),
                                    ("ownership", {"mode": "summary", "extra": 1}),
                                    ("ownership", {"mode": None}), ("ownership", {"mode": "other"}),
                                    ("ownership", {"viewer": True, "mode": "full"}),
                                    ("ownership", {"viewer": 32, "mode": "full"}),
                                    ("ownership", {"include_entities": 1})]:
            create = {} if selection is None else {"state_projection": projection(selection)}
            packets = [ipc.encode_message(ipc.CREATE, 1, -1, create, b"authored"),
                       ipc.encode_message(ipc.STATE, 2, -1, metadata)]
            result, replies = self.run_packets(packets, test_backend=True)
            self.assertEqual(result, 2)
            self.assertEqual(replies[-1][1], ipc.ERROR)

    def test_duplicate_ipc_keys_are_refused_before_information_is_lost(self):
        for raw in (b'{"x":1,"x":1}', b'{"x":{"mode":"full","mode":"ownership"}}',
                    b'{"resources":{"0":{},"0":{}}}'):
            with self.assertRaises(ipc.ProtocolError):
                ipc.decode_metadata(raw)

    def test_actual_header_byte_counters_preserve_whitespace_and_payload_size(self):
        metadata = b'{  "state" : {}  }'
        payload = b"authored-binary"
        packet = ipc.HEADER.pack(ipc.MAGIC, ipc.VERSION, ipc.SNAPSHOT | ipc.RESPONSE,
                                 0, 7, len(metadata), -1, len(payload)) + metadata + payload
        worker = object.__new__(client.SimulationWorker)
        worker.process = SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(packet))
        response, actual = worker._wire_exchange(b"request", ipc.SNAPSHOT, 7, -1)
        self.assertEqual(response, {"state": {}})
        self.assertEqual(actual, payload)
        self.assertEqual(worker.last_response_bytes, len(packet))
        self.assertEqual(worker.last_response_metadata_bytes, len(metadata))
        self.assertEqual(worker.last_response_payload_bytes, len(payload))


class CompactClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_explicit_mode_initial_step_override_and_default_query(self):
        for mode in STATE_MODES:
            worker = await client.SimulationWorker.create(b"authored", _test_backend=True, state_mode=mode)
            try:
                self.assertEqual(worker.state_mode, mode)
                self.assertEqual(worker.projection_version, 1)
                self.assertEqual(worker.state_projection_info, projection(mode))
                self.assertEqual(worker.state_projection_modes, list(STATE_MODES))
                initial = await worker.state(mode=mode)
                self.assertEqual(initial["frame"], -1)
                self.assertIsNone(worker.last_state)
                result = await worker.process_frame(frame(0))
                self.assertEqual(result.state["frame"], 0)
                self.assertEqual("entities" in result.state, mode == "full")
                self.assertEqual("ownership" in result.state, mode == "ownership")
                self.assertIn("entities", await worker.state(1, mode="full"))
                self.assertEqual(worker.state_mode, mode)
                self.assertEqual(worker.last_state, result.state)
                self.assertNotIn("ownership", await worker.state())
                self.assertNotIn("entities", await worker.state())
                self.assertIn("entities", await worker.state(include_entities=True))
                self.assertGreater(worker.last_response_bytes, ipc.HEADER.size)
            finally:
                await worker.close()
            self.assertEqual(worker.process.poll(), 0)
            self.assertFalse(worker._stderr_thread.is_alive())

    async def test_invalid_local_selection_and_explicit_legacy_query_never_spawn_or_exchange(self):
        with patch.object(client.subprocess, "Popen") as spawn:
            for mode in (True, 0, [], "other"):
                with self.assertRaises(ValueError):
                    await client.SimulationWorker.create(b"authored", _test_backend=True, state_mode=mode)
            spawn.assert_not_called()
        worker = await client.SimulationWorker.create(b"authored", _test_backend=True)
        try:
            self.assertIsNone(worker.state_mode)
            self.assertIsNone(worker.projection_version)
            with patch.object(worker, "_exchange", new=AsyncMock()) as exchange:
                for kwargs in ({"mode": "full"}, {"viewer": True}, {"include_entities": 1},
                               {"mode": "ownership", "include_entities": False}):
                    with self.assertRaises(ValueError):
                        await worker.state(**kwargs)
                exchange.assert_not_awaited()
        finally:
            await worker.close()

    async def test_spoofed_create_echo_version_and_capabilities_abort(self):
        mutations = [lambda r: r.pop("state_projection"),
                     lambda r: r["state_projection"].update(version=True),
                     lambda r: r["state_projection"].update(version=2),
                     lambda r: r["state_projection"].update(step_mode="full"),
                     lambda r: r["state_projection"].update(extra=1),
                     lambda r: r.pop("state_projection_modes"),
                     lambda r: r.update(state_projection_modes=["ownership", "full", "summary"])]
        for mutate in mutations:
            class Tampered(client.SimulationWorker):
                def _wire_exchange(self, *args):
                    response, payload = super()._wire_exchange(*args)
                    if args[1] == ipc.CREATE:
                        mutate(response)
                    return response, payload
            with self.subTest(mutation=mutate), self.assertRaises(client.WorkerError):
                await Tampered.create(b"authored", _test_backend=True, state_mode="ownership")

    async def test_spoofed_step_envelope_schema_digest_frame_never_advances_bookkeeping(self):
        mutations = [lambda r: r.pop("state_mode"), lambda r: r.update(state_mode="full"),
                     lambda r: r.update(state_projection_version=True),
                     lambda r: r.update(state_projection_version=2),
                     lambda r: r.update(input_sha256="0"*64),
                     lambda r: r["state"].update(frame=4),
                     lambda r: r["state"].update(viewer=0),
                     lambda r: r["state"].update(entities=[]),
                     lambda r: r["state"].pop("ownership"),
                     lambda r: r["state"].update(ownership=[{"id": 0, "army": False, "type": 1}]),
                     lambda r: r["state"].update(game_data_sha256="0"*64),
                     lambda r: r["state"].update(raw_sha256="0"*64)]
        for mutate in mutations:
            worker = await client.SimulationWorker.create(b"authored", _test_backend=True, state_mode="ownership")
            original = worker._exchange
            async def exchange(*args, **kwargs):
                response, payload = await original(*args, **kwargs)
                mutate(response)
                return response, payload
            worker._exchange = exchange
            with self.subTest(mutation=mutate), self.assertRaises(client.WorkerError):
                await worker.process_frame(frame(0))
            self.assertEqual(worker.frame, -1)
            self.assertIsNone(worker.last_state)
            self.assertIsNotNone(worker.process.poll())
            self.assertTrue(worker.closed)

    async def test_bad_state_override_envelope_and_payload_use_terminal_cleanup(self):
        for change in ("mode", "version", "viewer", "payload"):
            worker = await client.SimulationWorker.create(b"authored", _test_backend=True, state_mode="ownership")
            original = worker._exchange
            async def exchange(*args, **kwargs):
                response, payload = await original(*args, **kwargs)
                if change == "mode": response["state_mode"] = "ownership"
                if change == "version": response["state_projection_version"] = True
                if change == "viewer": response["state"]["viewer"] = 2
                if change == "payload": payload = b"unexpected"
                return response, payload
            worker._exchange = exchange
            with self.subTest(change=change), self.assertRaises(client.WorkerError):
                await worker.state(1, mode="full")
            self.assertEqual(worker.frame, -1)
            self.assertIsNone(worker.last_state)
            self.assertIsNotNone(worker.process.poll())

    async def test_compact_cancellation_reaps_and_preserves_uncommitted_frame(self):
        worker = await client.SimulationWorker.create(b"authored", _test_backend=True, state_mode="ownership")
        await worker._test_control("hang_next_step")
        pending = asyncio.create_task(worker.process_frame(frame(0)))
        await asyncio.sleep(.03)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(worker.frame, -1)
        self.assertIsNone(worker.last_state)
        self.assertFalse(worker._stderr_thread.is_alive())
        self.assertIsNotNone(worker.process.poll())


class RoomHistoryTests(unittest.TestCase):
    def room(self, mode):
        room = object.__new__(Room)
        room.sim = SimpleNamespace(state_mode=mode)
        room.entity_history = {}
        return room

    def state(self, records, mode):
        state = decode_snapshot(_build(0, resource_armies=())[0], mode=mode)
        key = "ownership" if mode == "ownership" else "entities"
        state[key] = records
        for name in ("army", "type", "health", "position"):
            state["counts"][name] = sum(name in r if name != "health" else "max_health" in r for r in records)
        return state

    def test_full_and_ownership_preserve_death_creation_and_changed_pairs(self):
        for mode in ("full", "ownership"):
            room = self.room(mode)
            room.refresh_native_state(self.state([{"id": 1, "army": 0, "type": 75}], mode))
            room.refresh_native_state(self.state([], mode))
            self.assertEqual(room.entity_history, {1: (0, 75)})
            room.refresh_native_state(self.state([{"id": 2, "army": 1, "type": 2}], mode))
            self.assertEqual(room.entity_history, {1: (0, 75), 2: (1, 2)})
            room.refresh_native_state(self.state([{"id": 1, "army": 1, "type": 2}], mode))
            self.assertEqual(room.entity_history, {1: (1, 2), 2: (1, 2)})

    def test_partial_current_records_do_not_combine_with_past_or_each_other(self):
        room = self.room("full")
        for records in ([{"id": 1, "army": 0, "type": 75}],
                        [{"id": 1, "army": 1}, {"id": 2, "army": 0}],
                        [{"id": 1, "type": 2}, {"id": 2, "type": 75}]):
            room.refresh_native_state(self.state(records, "full"))
        self.assertEqual(room.entity_history, {1: (0, 75)})

    def test_summary_missing_projection_or_wrong_shape_refuses_without_history_change(self):
        for mode, state in [("summary", {}), ("ownership", {"entities": []}),
                            ("full", {"ownership": []}), (None, {}),
                            ("ownership", self.state([{"id": 1, "army": 0}], "ownership"))]:
            room = self.room(mode)
            room.entity_history = {1: (0, 75)}
            with self.assertRaises(ValueError):
                room.refresh_native_state(state)
            self.assertEqual(room.entity_history, {1: (0, 75)})


class CompactRoomNetworkTests(DedicatedFixture):
    async def factory(self, data):
        worker = await client.SimulationWorker.create(data, _test_backend=True, state_mode="ownership")
        self.workers.append(worker)
        return worker

    async def test_initial_history_is_ready_before_first_command_and_step_remains_compact(self):
        await self.start()
        peers = await self.pair("compact_room")
        room = self.server.rooms["compact_room"]
        self.assertEqual(room.sim.frame, -1)
        self.assertEqual(room.validation.entity_lookup(0), (0, 1))
        self.assertEqual(room.entity_history, {0: (0, 1)})
        await self.advance(peers, 0)
        self.assertIn("ownership", room.sim.last_state)
        self.assertNotIn("entities", room.sim.last_state)
        self.assertEqual(room.entity_history, {0: (0, 1)})
        self.assertIn("entities", await room.sim.state(include_entities=True))


if __name__ == "__main__":
    unittest.main()
