import unittest

from server.protobuf_wire import (WireError, decode_varint, encode_varint,
                                  field_bytes, field_fixed32, field_packed_uint,
                                  field_uint, get_bytes, get_repeated_uint,
                                  get_uint, parse_fields, replace_fields)


class WireSupportTests(unittest.TestCase):
    def test_varint_uint64_boundaries(self):
        for value in (0, 127, 128, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            encoded = encode_varint(value)
            self.assertEqual(decode_varint(encoded), (value, len(encoded)))
        for malformed in (b"\x80", b"\xff" * 10, b"\x80" * 9 + b"\x02"):
            with self.assertRaises(WireError):
                decode_varint(malformed)

    def test_untouched_noncanonical_and_unknown_fields_preserved(self):
        unusual = b"\x08\x81\x00"  # Valid overlong encoding of field1=1.
        unknown = field_bytes(999, b"opaque\x00\xff")
        original = unusual + field_bytes(2, b"old") + unknown + field_bytes(2, b"again")
        edited = replace_fields(original, {2: [field_bytes(2, b"new")], 3: [field_uint(3, 7)]})
        self.assertEqual(edited, unusual + field_bytes(2, b"new") + unknown + field_uint(3, 7))
        self.assertEqual(replace_fields(original, {}), original)

    def test_repeated_packed_and_unpacked_order(self):
        data = field_uint(1, 7) + field_packed_uint(1, [0, 128]) + field_uint(1, 9)
        self.assertEqual(get_repeated_uint(data, 1), (7, 0, 128, 9))
        with self.assertRaises(WireError):
            get_repeated_uint(data, 1, max_values=3)

    def test_truncation_bad_tags_and_groups_rejected(self):
        for malformed in (b"\0", b"\x0a\x05abc", b"\x0d\x00", b"\x09\0\0", b"\x0b", b"\x0f"):
            with self.subTest(malformed=malformed), self.assertRaises(WireError):
                parse_fields(malformed)

    def test_duplicate_singular_and_wrong_wire_type_rejected(self):
        with self.assertRaises(WireError):
            get_uint(field_uint(1, 1) + field_uint(1, 2), 1)
        with self.assertRaises(WireError):
            get_bytes(field_uint(1, 1), 1)
        with self.assertRaises(WireError):
            get_uint(b"", 1, required=True)

    def test_replacement_requires_one_matching_field(self):
        for replacement in (field_uint(2, 1), field_uint(1, 1) + field_uint(1, 2), b""):
            with self.assertRaises(WireError):
                replace_fields(b"", {1: [replacement]})
        self.assertEqual(replace_fields(field_uint(1, 1), {1: []}), b"")

    def test_size_and_field_limits(self):
        with self.assertRaises(WireError):
            parse_fields(field_bytes(1, b"abc"), max_bytes=4)
        with self.assertRaises(WireError):
            parse_fields(field_uint(1, 1) * 2, max_fields=1)
        value = field_fixed32(2, 0x12345678)
        self.assertEqual(parse_fields(value)[0].value, b"\x78\x56\x34\x12")


if __name__ == "__main__":
    unittest.main()
