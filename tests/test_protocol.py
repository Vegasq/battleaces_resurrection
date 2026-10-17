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
