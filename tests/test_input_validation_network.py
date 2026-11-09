"""Actual loopback coordinator regression with an explicit synthetic worker."""
import asyncio
import json
from pathlib import Path
import struct

from server import protocol as p
from server.game_data import InputValidation, encode_player_input
from server.protobuf_wire import get_repeated_bytes
from tests.test_dedicated_server import DedicatedFixture
from tests.test_input_validation import COMMON, GAME, execute, group


class EmptySelectionNetworkTests(DedicatedFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        descriptors = Path(self.template.descriptors_path)
        old = descriptors / 'authored.proto.json'
        self.assertTrue(old.resolve().is_relative_to(self.folder.resolve()))
        old.unlink()  # Only the descriptor just created by this owned fixture.
        for package, messages in [('common_pb', COMMON), ('game_pb', GAME)]:
            (descriptors / (package + '.proto.json')).write_text(
                json.dumps(dict(package=package, messages=messages)), encoding='utf-8')
        self.template.entity_abilities[100] = {7}

    async def test_empty_selection_bursts_keep_both_peers_and_worker_advancing(self):
        await self.start(input_window=6)
        peers = await self.pair('empty_selection_bursts')
        room = self.server.rooms['empty_selection_bursts']
        self.assertIs(type(room.validation), InputValidation)
        self.assertEqual(room.validation.entity_lookup(0), (0, 1))
        worker = room.sim
        total, bursts = 20, {8, 12}

        async def send_input(frame):
            payloads = [struct.pack('<I', frame) for _ in peers]
            if frame in bursts:
                # Both absent and explicitly empty packed lists can be emitted
                # by lazy selection serialization. Sixteen orders match the
                # observed burst size; neither form should close a peer.
                action = execute([group(explicit_empty=frame == 12)], queued=True)
                body = encode_player_input(room.match.identities_by_slot[0], [action] * 16)
                payloads[0] += body
            await asyncio.gather(*(peer.send(p.INPUT, payload)
                                   for peer, payload in zip(peers, payloads)))

        for frame in range(peers[0].input_window):
            await send_input(frame)
        observed = []
        for frame in range(total):
            payloads = await asyncio.gather(*(peer.receive(p.FRAME) for peer in peers))
            self.assertEqual(payloads[0], payloads[1])
            number, first_size = struct.unpack_from('<II', payloads[0])
            self.assertEqual(number, frame)
            first = payloads[0][8:8 + first_size]
            second = payloads[0][8 + first_size:]
            self.assertEqual(first, encode_player_input(room.match.identities_by_slot[0]))
            self.assertEqual(second, encode_player_input(room.match.identities_by_slot[1]))
            self.assertEqual(get_repeated_bytes(first, 2), ())
            observed.append(number)
            future = frame + peers[0].input_window
            if future < total:
                await send_input(future)

        self.assertEqual(observed, list(range(total)))
        self.assertEqual(room.state, 'running')
        self.assertEqual(room.frame, total)
        self.assertTrue(all(not peer.closed for peer in room.peers.values()))
        self.assertTrue(all(not peer.writer.is_closing() for peer in peers))
        self.assertTrue(all(not any(kind == p.ERROR for kind, _ in peer.observed) for peer in peers))
        self.assertFalse(any(event['event'] in ('protocol_error', 'match_aborted') for event in self.events))
        state = await worker.state(31, include_entities=True)
        self.assertTrue(state['synthetic_test_backend'])
        self.assertEqual(state['frame'], total - 1)
        self.assertEqual(worker.frame, total - 1)
        self.assertIsNone(worker.process.poll())
