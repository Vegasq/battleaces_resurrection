"""Authored public queue wire cases; no game-derived messages or assets."""
import struct
import unittest

from server import protocol as p, public_protocol as q


class PublicProtocolTests(unittest.TestCase):
    def test_queue_command_preserves_ticket_mode_deadline_and_deck(self):
        for mode in (1, 2, 5):
            for remaining in (0, 1, 29999, 30000):
                raw = q.command(q.ENTER, 7, 0x123456789abcdef0, mode=mode, wait_ms=remaining, deck=list(range(100, 108)))
                self.assertEqual(raw, struct.pack('<IHQBI8I', 7, 1, 0x123456789abcdef0, mode, remaining, *range(100, 108)))
                self.assertEqual(q.decode_command(q.ENTER, raw), dict(request=7, ticket=0x123456789abcdef0,
                    mode=mode, wait_ms=remaining, deck=list(range(100, 108))))

    def test_stale_reference_is_carried_by_ready_and_return(self):
        for kind in (q.READY, q.RETURN):
            raw = q.command(kind, 8, 9, match='authored_match')
            self.assertEqual(q.decode_command(kind, raw), dict(request=8, ticket=9, match='authored_match'))
        self.assertEqual(q.decode_command(q.CANCEL, q.command(q.CANCEL, 8, 9)), dict(request=8, ticket=9))

    def test_invalid_version_ticket_mode_deadline_and_trailing_fields_rejected(self):
        good = q.command(q.ENTER, 7, 9, mode=2, deck=range(8))
        bad = [good[:-1], good+b'x', bytes(4)+good[4:], good[:4]+b'\x02\x00'+good[6:],
               good[:6]+bytes(8)+good[14:], good[:14]+b'\x04'+good[15:],
               good[:15]+struct.pack('<I', 30001)+good[19:]]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(p.ProtocolError): q.decode_command(q.ENTER, raw)

    def test_assignment_binds_human_seat_and_team_topology(self):
        for mode, count, mask, slots in ((1, 2, 3, (0, 1)), (2, 4, 15, range(4)), (5, 4, 5, (0, 2))):
            for slot in slots:
                value = dict(generation=9, match='frozen', mode=mode, slot=slot, human_mask=mask, input_window=6, deck=list(range(8)))
                self.assertEqual(q.decode_assignment(q.assignment(**value)), value | {'count': count})
        for mode, slot, mask in ((1, 2, 4), (2, 3, 7), (5, 1, 7), (5, 0, 15), (5, 0, 0)):
            with self.assertRaises(p.ProtocolError): q.assignment(9, 'frozen', mode, slot, mask, 6, range(8))

    def test_state_and_timer_are_bound_to_the_same_ticket(self):
        self.assertEqual(q.decode_state(q.state(9, q.OFFERED, 5, 30000, 'offer', '')),
                         dict(ticket=9, phase=q.OFFERED, mode=5, elapsed_ms=30000, match='offer', reason=''))

    def test_two_and_four_input_frames_have_no_implicit_last_seat(self):
        for count in (2, 4):
            inputs = {slot: bytes([slot+1])*(slot+1) for slot in range(count)}
            wire = q.frame(17, inputs)
            expected = struct.pack('<IB', 17, count) + b''.join(struct.pack('<I', len(value))+value for value in inputs.values())
            self.assertEqual(wire, expected)
            self.assertEqual(q.decode_frame(wire, count), (17, inputs))
            for bad in (wire+b'x', wire[:-1], wire[:4]+b'\x03'+wire[5:], wire[:5]+bytes(4)+wire[9:],
                        wire[:5]+struct.pack('<I', p.MAX_INPUT+1)+wire[9:]):
                with self.subTest(bad=bad), self.assertRaises(p.ProtocolError): q.decode_frame(bad, count)
            with self.assertRaises(p.ProtocolError): q.decode_frame(wire, 6-count)

    def test_public_frame_sizes_and_contiguous_roster_are_bounded(self):
        for inputs in ({0: b'a'}, {0: b'a', 2: b'b'}, {0: b'a', 1: b''}, {0: b'a', 1: bytes(p.MAX_INPUT+1)}):
            with self.assertRaises(p.ProtocolError): q.frame(0, inputs)
        inputs = {i: bytes([i])*p.MAX_INPUT for i in range(4)}
        self.assertEqual(q.decode_frame(q.frame(0x7fffffff, inputs), 4), (0x7fffffff, inputs))
        with self.assertRaises(p.ProtocolError): q.frame(0x80000000, inputs)
