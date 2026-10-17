import asyncio
import struct
import unittest
from server import protocol as p


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_framing_roundtrip(self):
        reader = asyncio.StreamReader()
        reader.feed_data(p.encode(p.HELLO, p.hello(0, 'alice', 'Alice', 'room')))
        kind, payload = await p.receive(reader)
        self.assertEqual(kind, p.HELLO)
        self.assertEqual(p.decode_hello(payload), (0, 'alice', 'Alice', 'room'))

    async def test_size_rejected_before_body_read(self):
        for size in (0, p.MAX_BODY + 1, 0xffffffff):
            reader = asyncio.StreamReader()
            reader.feed_data(struct.pack('<I', size))
            with self.assertRaises(p.ProtocolError):
                await p.receive(reader)

    async def test_bad_build_slot_names_and_trailing_data_rejected(self):
        hello = p.hello(0, 'alice', 'Alice')
        cases = [hello + b'x', hello[:2] + b'\x02' + hello[3:],
                 hello[:3] + bytes(32) + hello[35:], p.hello(0, '../alice', 'Alice')]
        for raw in cases:
            with self.assertRaises(p.ProtocolError):
                p.decode_hello(raw)

    def test_old_protocol_rejected_with_upgrade_reason(self):
        old = struct.pack('<H', 2) + p.hello(0, 'alice', 'Alice')[2:]
        with self.assertRaisesRegex(p.ProtocolError, 'update client and server together'):
            p.decode_hello(old)

    def test_welcome_layout_and_all_supported_windows(self):
        deck = [1, 7, 12, 32, 48, 73, 100, 0xffffffff]
        for slot in (0, 1):
            for window in range(2, 13):
                wire = struct.pack('<BB8I', slot, window, *deck)
                self.assertEqual(p.welcome(slot, window, deck), wire)
                self.assertEqual(p.decode_welcome(wire), (slot, window, deck))

    def test_old_truncated_extra_or_invalid_welcome_rejected(self):
        good = struct.pack('<BB8I', 0, 6, *range(8))
        cases = [good[:1] + good[2:], good[:-1], good + b'x', b'', b'\x02' + good[1:]]
        cases += [good[:1] + bytes([window]) + good[2:] for window in (0, 1, 13, 255)]
        for wire in cases:
            with self.subTest(wire=wire), self.assertRaises(p.ProtocolError):
                p.decode_welcome(wire)
