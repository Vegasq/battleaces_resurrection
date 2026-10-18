"""Bot ownership/frame boundary tests use authored fixtures; native checks opt in."""
import asyncio
import hashlib
import io
import os
from pathlib import Path
import struct
import unittest
from unittest import mock

from server import simulation_worker as ipc
from server.game_data import encode_frame, encode_player_input
from server.protobuf_wire import field_bytes, field_uint, get_repeated_bytes
from server.worker_ai import AISetup, BotRoster, WorkerAI, pack_inputs, unpack_inputs
from server.worker_client import SimulationWorker, WorkerError
from tests.synthetic import template as synthetic_template
from tests.test_dedicated_server import DedicatedFixture, wait_until
from server import dedicated_server as coordinator, protocol as p

ROOT = Path(__file__).resolve().parents[1]


def match_fixture():
    template = synthetic_template()
    return template.build_match([{'slot': 0, 'name': 'Human'},
                                 {'slot': 1, 'name': 'Bot', 'ai_profile_id': 58}], template.default_decks, seed=42)


class BotBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.match = match_fixture()
        self.roster = BotRoster(self.match.raw_game_data, {1: 58})

    def test_setup_is_frozen_and_matches_exact_game_data(self):
        bots = {1: 58}
        setup = AISetup(ROOT, bots); bots[1] = 62
        self.assertEqual(dict(AISetup.from_wire(setup.wire()).bots), {1: 58})
        for assignment in ({0: 58}, {1: 62}, {0: 58, 1: 58}, {}):
            with self.subTest(assignment=assignment), self.assertRaises(ValueError):
                BotRoster(self.match.raw_game_data, assignment)
        for value in ({'directory': str(ROOT), 'bots': {'01': 58}},
                      {'directory': str(ROOT), 'bots': {'1': True}},
                      {'directory': 'relative', 'bots': {'1': 58}}):
            with self.subTest(value=value), self.assertRaises(ValueError): AISetup.from_wire(value)

    def test_join_is_once_and_uses_frozen_deck_identity(self):
        first = self.roster.make_inputs(0, {})
        self.roster.check_inputs(first)
        self.assertEqual(get_repeated_bytes(first[1], 2), (field_bytes(3, field_uint(1, 1) +
                         field_bytes(2, self.match.deck_messages_by_slot[1])),))
        self.assertEqual(get_repeated_bytes(self.roster.make_inputs(1, {})[1], 2), ())

    def test_bot_packet_rejects_truncation_duplicates_trailing_and_size(self):
        inputs = self.roster.make_inputs(0, {})
        packet = pack_inputs(inputs)
        self.assertEqual(unpack_inputs(packet), inputs)
        for cut in range(len(packet)):
            with self.subTest(cut=cut), self.assertRaises(ValueError): unpack_inputs(packet[:cut])
        for malformed in (packet+b'x', b'\x02'+packet[1:]*2, b'\x00', b'\x05'):
            with self.subTest(malformed=malformed[:20]), self.assertRaises(ValueError): unpack_inputs(malformed)
        with self.assertRaises(ValueError): pack_inputs({1: b'x'*65537})

    def test_prepared_actions_cannot_be_omitted_changed_duplicated_or_impersonated(self):
        inputs = self.roster.make_inputs(0, {})
        canonical = encode_frame(0, {0: b'', **inputs})
        self.roster.check_frame(canonical, inputs)
        altered = encode_frame(0, {0: b'', 1: encode_player_input(self.match.identities_by_slot[1], [field_bytes(5, b'')])})
        for payload in (encode_frame(0, {0: b'', 1: b''}), altered, canonical+field_bytes(6, inputs[1]),
                        canonical+field_bytes(6, encode_player_input(b'invented', [field_bytes(5, b'')]))):
            with self.subTest(payload=payload[-20:]), self.assertRaises(ValueError):
                self.roster.check_frame(payload, inputs)
        empty = self.roster.make_inputs(1, {})
        self.roster.check_frame(encode_frame(1, {0: b'', **empty}), empty)

    def test_native_bot_cannot_create_join_debug_or_control_human_army(self):
        for kind in (2, 3, 4, 6):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.roster.make_inputs(5, {1: [field_bytes(kind, b'')]})
        with self.assertRaises(ValueError): self.roster.make_inputs(5, {0: []})
        with self.assertRaises(ValueError): self.roster.make_inputs(5, {1: [field_bytes(1, b'')]*129})


class WorkerAIPipeTests(unittest.TestCase):
    """Exercise the real private request loop without loading any native DLL."""
    def run_pipe(self, operations):
        match = match_fixture()
        closed, instances = [], []

        class Sim(ipc.SyntheticSimulation):
            def __init__(self, data, path=None): super().__init__(data)
            def close(self): closed.append('simulation')

        def create(simulation, data, setup):
            ai = WorkerAI.__new__(WorkerAI)
            BotRoster.__init__(ai, data, setup.bots)
            ai.simulation, ai.prepared, ai.prepared_frame = simulation, None, None
            ai.info = {'bots': {'1': 58}}
            ai.native = mock.Mock()
            ai.native.commands.return_value = {}
            ai.native.close.side_effect = lambda: closed.append('ai')
            instances.append(ai)
            return ai

        messages = [(ipc.CREATE, -1, {'ai': AISetup(ROOT, {1: 58}).wire()}, match.raw_game_data)] + operations
        source = io.BytesIO(b''.join(ipc.encode_message(op, i+1, frame, metadata, payload)
                                    for i, (op, frame, metadata, payload) in enumerate(messages)))
        sink = io.BytesIO()
        with mock.patch('server.native_simulation.NativeSimulation', Sim), mock.patch('server.worker_ai.WorkerAI', create):
            code = ipc.serve(source, sink)
        sink.seek(0); replies = []
        while (message := ipc.read_message(sink)) is not None: replies.append(message)
        self.assertEqual(closed, ['ai', 'simulation'])
        return code, replies, instances[0]

    def test_prepare_step_and_close_preserve_exact_frame_bytes(self):
        match = match_fixture()
        inputs = BotRoster(match.raw_game_data, {1: 58}).make_inputs(0, {})
        actions = encode_frame(0, {0: b'', **inputs})
        code, replies, ai = self.run_pipe([(ipc.BOT_INPUT, 0, {}, b''),
            (ipc.STEP, 0, {'dt_ms': 50}, actions), (ipc.CLOSE, 0, {}, b'')])
        self.assertEqual(code, 0)
        self.assertEqual(unpack_inputs(replies[1][5]), inputs)
        self.assertEqual(replies[2][4]['input_sha256'], hashlib.sha256(actions).hexdigest())
        self.assertEqual(ai.simulation.frame, 0)
        self.assertIsNone(ai.prepared)
        ai.native.commands.assert_called_once_with()

    def test_missing_or_duplicate_prepare_and_changed_frame_are_terminal(self):
        empty = encode_frame(0, {0: b'', 1: b''})
        cases = [[(ipc.STEP, 0, {'dt_ms': 50}, empty)],
                 [(ipc.BOT_INPUT, 0, {}, b''), (ipc.BOT_INPUT, 0, {}, b'')],
                 [(ipc.BOT_INPUT, 0, {}, b''), (ipc.STEP, 0, {'dt_ms': 50}, empty)],
                 [(ipc.BOT_INPUT, 1, {}, b'')]]
        for operations in cases:
            with self.subTest(operations=operations):
                code, replies, ai = self.run_pipe(operations)
                self.assertEqual(code, 2)
                self.assertEqual(replies[-1][1], ipc.ERROR)
                self.assertEqual(ai.simulation.frame, -1)

    def test_state_query_does_not_consume_prepared_inputs(self):
        code, replies, ai = self.run_pipe([(ipc.BOT_INPUT, 0, {}, b''),
            (ipc.STATE, -1, {}, b''), (ipc.CLOSE, -1, {}, b'')])
        self.assertEqual(code, 0)
        self.assertEqual(replies[2][4]['state']['frame'], -1)
        ai.native.commands.assert_called_once_with()


class MixedRoomTests(DedicatedFixture):
    """Real loopback room/worker lifetime with explicitly synthetic bot decisions."""
    async def ai_factory(self, data, bots):
        worker = await self.factory(data)
        roster = BotRoster(data, bots)
        async def inputs(frame):
            return roster.make_inputs(frame, {1: [field_bytes(5, b'')]} if frame == 1 else {})
        worker.bot_inputs = inputs
        worker.accepted_inputs = {}
        process_frame = worker.process_frame
        async def record(actions, dt_ms=None):
            result = await process_frame(actions, dt_ms)
            worker.accepted_inputs[result.frame] = actions
            return result
        worker.process_frame = record
        return worker

    async def mixed(self):
        await self.start(ai_factory=self.ai_factory)
        bot = coordinator.BotSeat(1, 58, 'Authored test bot', self.template.default_decks[1])
        room = coordinator.Room(self.server, 'mixed', bots=[bot])
        self.server.rooms[room.name] = room
        peer = await self.connect(room.name)
        self.assertEqual(peer.slot, 0)
        await peer.send(p.LOBBY_READY, b'\x01')
        bootstrap = await peer.receive(p.BOOTSTRAP)
        await peer.send(p.LOADED, hashlib.sha256(bootstrap).digest())
        await peer.receive(p.START)
        return room, peer

    async def test_one_human_load_and_input_produce_complete_shared_frames(self):
        room, peer = await self.mixed()
        for number in range(3):
            await peer.send(p.INPUT, struct.pack('<I', number))
            payload = await peer.receive(p.FRAME)
            frame, length = struct.unpack_from('<II', payload)
            self.assertEqual(frame, number)
            human, bot = payload[8:8+length], payload[8+length:]
            self.assertEqual(human, encode_player_input(room.match.identities_by_slot[0]))
            self.assertEqual(len(get_repeated_bytes(bot, 2)), int(number < 2))
            self.assertEqual(room.sim.accepted_inputs[number], encode_frame(number, {0: human, 1: bot}))
        await peer.close()
        await wait_until(lambda: room.sim is None and all(worker.closed for worker in self.workers))

    async def test_bot_seat_cannot_be_taken_and_custom_cannot_enable_bots(self):
        room, peer = await self.mixed()
        intruder = await self.connect(room.name, slot=1, welcome=False)
        self.assertIn(b'unavailable', await intruder.receive(p.ERROR))
        self.assertEqual(set(room.peers), {0})
        with self.assertRaisesRegex(ValueError, 'Custom'):
            coordinator.Room(self.server, 'custom', community_lobby='authored', bots=room.bots.values())

    async def test_bot_prepare_failure_publishes_no_frame_and_reaps_worker(self):
        room, peer = await self.mixed()
        async def failed(frame): raise WorkerError('authored AI failure')
        room.sim.bot_inputs = failed
        await peer.send(p.INPUT, struct.pack('<I', 0))
        await wait_until(lambda: room.state == 'closed' and all(worker.closed for worker in self.workers))
        self.assertFalse(any(kind == p.FRAME for kind, _ in peer.observed))


@unittest.skipUnless(os.name == 'nt' and os.environ.get('BA_RUN_NATIVE_WORKER_TESTS') == '1',
                     'native AI IPC requires explicit Windows opt-in')
class NativeAIWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_decisions_replay_identically_and_remain_outside_parent(self):
        from server.game_data import GameTemplate
        import ctypes
        assets = Path(os.environ.get('BA_WORKER_TEST_ASSETS', ROOT/'local/assets/ai-export02')).resolve()
        if not (assets/'ai-rules.json').is_file(): self.skipTest('imported AI rules required')
        template = GameTemplate.load(assets/'map-1v1.pb.gz', catalog_path=assets/'unit-catalog.json',
                                     descriptors_path=assets/'descriptors')
        match = template.build_match([{'slot': a, 'name': f'IPC bot {a}', 'ai_profile_id': 58} for a in (0, 1)],
                                     template.default_decks, seed=862431)
        ai = replay = None
        commands = 0
        try:
            ai = await SimulationWorker.create(match.raw_game_data, assets/'Simulation.dll', ai=AISetup(assets, {0: 58, 1: 58}))
            replay = await SimulationWorker.create(match.raw_game_data, assets/'Simulation.dll')
            with self.assertRaisesRegex(ValueError, 'prepare'): await ai.process_frame(encode_frame(0, {0: b'', 1: b''}))
            for frame in range(601):
                inputs = await ai.bot_inputs(frame)
                if frame == 0:
                    with self.assertRaises(ValueError): await ai.bot_inputs(frame)
                    with self.assertRaisesRegex(ValueError, 'omitted'):
                        await ai.process_frame(encode_frame(frame, {0: b'', 1: b''}))
                commands += sum(len(get_repeated_bytes(body, 2)) for body in inputs.values())
                payload = encode_frame(frame, inputs)
                results = await asyncio.gather(ai.process_frame(payload), replay.process_frame(payload))
                self.assertEqual(results[0].state['canonical_fnv1a64'], results[1].state['canonical_fnv1a64'])
            self.assertGreater(commands, 2, 'AI must generate commands beyond initial joins')
            getmodule = ctypes.WinDLL('kernel32').GetModuleHandleW
            getmodule.argtypes = [ctypes.c_wchar_p]; getmodule.restype = ctypes.c_void_p
            for name in ('Simulation.dll', 'aiprogram.dll'): self.assertFalse(getmodule(name))
        finally:
            await asyncio.gather(*(worker.close() for worker in (ai, replay) if worker is not None))
        self.assertEqual([ai.process.poll(), replay.process.poll()], [0, 0])


if __name__ == '__main__': unittest.main()
