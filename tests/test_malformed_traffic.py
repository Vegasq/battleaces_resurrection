"""Negative evidence controls for the finite active-match diagnostic."""
import asyncio
import copy
import struct
import unittest

from server import protocol as p
from server.game_data import decode_player_input, encode_identity
from server.protobuf_wire import WireError, parse_fields
from tools.verify_malformed_traffic import packet, check_journal


class PacketControls(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_mismatch_changes_one_digest_byte_only(self):
        digest = bytes(range(32))
        reader = asyncio.StreamReader()
        reader.feed_data(packet('bootstrap_mismatch', digest))
        kind, payload = await p.receive(reader)
        self.assertEqual(kind, p.LOADED)
        self.assertEqual(len(payload), 32)
        self.assertEqual(sum(a != b for a, b in zip(digest, payload)), 1)
        self.assertEqual(payload[1:], digest[1:])
        with self.assertRaises(AssertionError):
            packet('bootstrap_mismatch', digest[:-1])

    async def test_oversized_header_rejected_without_body(self):
        reader = asyncio.StreamReader()
        reader.feed_data(packet('oversized_header', b'other'))
        # No EOF or body supplied: waiting for either must fail this test.
        with self.assertRaisesRegex(p.ProtocolError, 'packet size limit'):
            await asyncio.wait_for(p.receive(reader), .2)

    async def test_truncated_protobuf_inside_valid_frame(self):
        reader = asyncio.StreamReader()
        reader.feed_data(packet('truncated_input', b'other'))
        kind, payload = await p.receive(reader)
        self.assertEqual((kind, struct.unpack_from('<I', payload)[0]), (p.INPUT, 10))
        with self.assertRaisesRegex(WireError, 'truncated varint'):
            parse_fields(payload[4:])

    async def test_foreign_identity_is_valid_protobuf(self):
        reader = asyncio.StreamReader()
        reader.feed_data(packet('foreign_identity', encode_identity(42, 'Other Player')))
        kind, payload = await p.receive(reader)
        self.assertEqual((kind, struct.unpack_from('<I', payload)[0]), (p.INPUT, 10))
        self.assertEqual(decode_player_input(payload[4:])['identity']['player_id'], 42)


class JournalControls(unittest.TestCase):
    def setUp(self):
        self.frames = [dict(sha256='frame-' + str(n)) for n in range(40)]
        self.rows = [dict(event='frame_queued', match='bad', frame=n) for n in range(10)]
        self.rows += [dict(event='match_aborted', match='bad', result=None, next_frame=10),
                      dict(event='protocol_error', connection='bad-connection', reason='packet size limit')]
        self.rows += [dict(event='frame_queued', match='good', frame=n, frame_payload_sha256=f['sha256'])
                      for n, f in enumerate(self.frames)]

    def check(self, rows):
        check_journal(rows, 'bad', 'good', self.frames, 'packet size limit', 'bad-connection')

    def test_complete_control(self):
        self.check(self.rows)

    def test_rejects_bad_frame_winner_or_worker_failure(self):
        mutations = [dict(event='frame_queued', match='bad', frame=10),
                     dict(event='simulation_error', match='bad'),
                     dict(event='match_completed', match='bad')]
        for row in mutations:
            with self.subTest(event=row['event']), self.assertRaises(AssertionError):
                self.check(self.rows + [row])
        rows = copy.deepcopy(self.rows)
        rows[10]['result'] = {'winner': 0}
        with self.assertRaises(AssertionError):
            self.check(rows)

    def test_rejects_wrong_connection_or_rejection(self):
        for field, value in (('connection', 'innocent'), ('reason', 'simulation error')):
            rows = copy.deepcopy(self.rows)
            rows[11][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.check(rows)

    def test_rejects_healthy_gap_or_changed_payload(self):
        rows = copy.deepcopy(self.rows)
        rows[-1]['frame_payload_sha256'] = 'changed'
        for broken in (rows, self.rows[:-1]):
            with self.assertRaises(AssertionError):
                self.check(broken)


class LoadingJournalControls(unittest.TestCase):
    def setUp(self):
        self.frames = [dict(sha256='frame-' + str(n)) for n in range(40)]
        self.rows = [dict(event='world_loaded', match='bad', slot=0),
                     dict(event='match_aborted', match='bad', result=None, next_frame=0, reason='player disconnected'),
                     dict(event='protocol_error', connection='bad-connection', reason='bootstrap acknowledgement mismatch')]
        self.rows += [dict(event='frame_queued', match='good', frame=n, frame_payload_sha256=f['sha256'])
                      for n, f in enumerate(self.frames)]

    def check(self, rows):
        check_journal(rows, 'bad', 'good', self.frames, 'bootstrap acknowledgement mismatch',
                      'bad-connection', frames_before=0)

    def test_loading_abort_control(self):
        self.check(self.rows)

    def test_rejects_start_frame_completion_or_second_loaded_peer(self):
        extra = [dict(event='match_started', match='bad'),
                 dict(event='frame_queued', match='bad', frame=0),
                 dict(event='native_game_over', match='bad'),
                 dict(event='world_loaded', match='bad', slot=1)]
        for row in extra:
            with self.subTest(event=row['event']), self.assertRaises(AssertionError):
                self.check(self.rows + [row])

    def test_rejects_wrong_survivor_or_abort_boundary(self):
        for index, field, value in ((0, 'slot', 1), (1, 'next_frame', 1),
                                    (1, 'result', {'winner': 0}), (1, 'reason', 'world loading timeout')):
            rows = copy.deepcopy(self.rows)
            rows[index][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.check(rows)


if __name__ == '__main__':
    unittest.main()
