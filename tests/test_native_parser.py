import struct
import unittest
from server.native_simulation import canonical_snapshot, SnapshotFormatError, _protobuf_header
from server.protobuf_wire import field_uint
from tests.synthetic import snapshot


class NativeParserTests(unittest.TestCase):
    def test_synthetic_resources_and_native_result_fields(self):
        result = canonical_snapshot(snapshot(123, winner=1, complete=True))
        self.assertEqual(result['frame'], 123)
        self.assertEqual(result['resources'][0]['primary'], 1000)
        self.assertEqual(result['resources'][1]['primary'], 1001)
        self.assertEqual(result['counts']['resources'], 2)
        self.assertEqual(result['game_state'], {'complete': True, 'game_over_frame': 123,
                         'winning_alliance': 1, 'army_conceded_flag': 0,
                         'game_over_checksum': 123456789})

    def test_every_truncated_prefix_rejected(self):
        raw = snapshot()
        for length in range(len(raw) - 7):
            with self.subTest(length=length), self.assertRaises((SnapshotFormatError, struct.error)):
                canonical_snapshot(raw[:length])

    def test_input_step_and_overflow_checked(self):
        self.assertEqual(_protobuf_header(field_uint(3, 50)), (0, 50))
        for raw in (b'', b'\x18\x80', field_uint(3, 1001),
                    field_uint(1, 0x80000000) + field_uint(3, 50)):
            with self.assertRaises(ValueError):
                _protobuf_header(raw)
