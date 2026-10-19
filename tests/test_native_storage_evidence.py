"""Authored structural replay-evidence controls; no original game bytes."""
import unittest
import zlib

from server.protobuf_wire import field_bytes, field_uint
from tools.verify_native_storage import replay_evidence


def deflate(raw):
    writer = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return writer.compress(raw)+writer.flush()


class ReplayEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.game = field_bytes(1,b'authored nested game config')
        self.action = field_uint(1,42)
        self.replay = deflate(field_bytes(1,self.game)+field_bytes(2,self.action))

    def test_complete_deflate_replay_identifies_data_and_actions_without_claiming_playback(self):
        proof = replay_evidence(self.replay)
        self.assertEqual(proof['input_action_messages'],1)
        self.assertFalse(proof['native_playback'])
        self.assertEqual(proof['bytes'],len(self.replay))

    def test_truncation_trailing_bytes_concatenation_and_expansion_are_rejected(self):
        for raw in (self.replay[:-1],self.replay+b'junk',self.replay+self.replay,
                    deflate(b'x'*(16*1024*1024+1))):
            with self.subTest(bytes=len(raw)),self.assertRaises(AssertionError): replay_evidence(raw)

    def test_missing_data_actions_duplicate_data_and_malformed_nested_wire_are_rejected(self):
        cases = (field_bytes(1,self.game),field_bytes(2,self.action),
                 field_bytes(1,self.game)*2+field_bytes(2,self.action),
                 field_bytes(1,b'\x80')+field_bytes(2,self.action),
                 field_bytes(1,self.game)+field_bytes(2,b'\x80'),
                 field_bytes(1,self.game)+field_uint(2,42))
        for raw in cases:
            with self.subTest(raw=raw),self.assertRaises((AssertionError,ValueError)): replay_evidence(deflate(raw))
