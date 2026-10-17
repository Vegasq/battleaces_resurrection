"""Asset-free extractor tests: every byte below is synthesized by this project."""
import hashlib
import pathlib
import struct
import unittest
from unittest import mock

from tools import extract_descriptors as extractor


def varint(number):
    result = bytearray()
    while number >= 128:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)


def field(number, value):
    if isinstance(value, bytes):
        return varint(number * 8 + 2) + varint(len(value)) + value
    return varint(number * 8) + varint(value)


def synthetic_pe():
    """Minimal project-generated x64 PE with one chained unwind range."""
    data = bytearray(0x1200)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 1)
    struct.pack_into("<H", data, 0x94, 0xF0)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<Q", data, optional + 24, 0x140000000)
    struct.pack_into("<II", data, optional + 136, 0x1100, 24)
    section = optional + 0xF0
    struct.pack_into("<4I", data, section + 8, 0x1000, 0x1000, 0x1000, 0x200)
    struct.pack_into("<III", data, 0x300, 0x1200, 0x1210, 0x1300)
    struct.pack_into("<III", data, 0x30C, 0x1210, 0x1280, 0x1320)
    data[0x500] = 1  # UNWIND_INFO version 1, no chain.
    data[0x520] = 0x21  # Version 1, UNW_FLAG_CHAININFO.
    struct.pack_into("<III", data, 0x524, 0x1200, 0x1210, 0x1300)
    return data


class FakePE:
    def __init__(self, count=4):
        self.data = b"".join(struct.pack("<Q", (5 << 29) | (i << 1) | 1) for i in range(count))

    def offset(self, address, length=1):
        value = address - 0x5000
        extractor.require(0 <= value <= len(self.data) and length <= len(self.data) - value, "test bounds")
        return value


class FakeMetadata:
    literals = ("QUFB", "QkJC", "Q0ND", "RERE")

    def literal(self, index):
        return self.literals[index]


def synthetic_code(loads, *, concat=True, lea=False):
    code = bytearray()
    if lea:
        code += b"\x48\x8d\x0d" + struct.pack("<i", 0x5000 - (0x1000 + 7))
    for register, literal in loads:
        rex = 0x4C if register >= 8 else 0x48
        modrm = 5 | ((register & 7) << 3)
        code += bytes((rex, 0x8B, modrm)) + struct.pack("<i", 0x5000 + literal * 8 - (0x1000 + len(code) + 7))
    if concat:
        code += b"\xe8" + struct.pack("<i", 0x4000 - (0x1000 + len(code) + 5))
    return bytes(code)


class DescriptorExtractionTests(unittest.TestCase):
    def test_standard_descriptor_projection_from_synthetic_wire(self):
        member = field(1, b"value") + field(3, 1) + field(4, 1) + field(5, 5)
        message = field(1, b"Example") + field(2, member)
        source = field(1, b"synthetic_fixture.proto") + field(2, b"example") + field(4, message) + field(12, b"proto3")
        decoded = extractor.decode_descriptor(source)
        self.assertEqual(decoded["name"], "synthetic_fixture.proto")
        self.assertEqual(decoded["messages"][0]["fields"], [{"name": "value", "number": 1, "label": 1, "type": 5}])

    def test_unknown_options_are_omitted(self):
        source = field(1, b"synthetic.proto") + field(99, b"synthetic unknown data")
        self.assertEqual(extractor.decode_descriptor(source), {"name": "synthetic.proto"})

    def test_malformed_wire_rejected(self):
        cases = (b"\0", b"\x0a\x02x", b"\x08\x01", b"\x0a\x80", b"\x0b",
                 b"\x08" + b"\xff" * 9 + b"\x02", field(1, b"x") + field(1, b"y"))
        for source in cases:
            with self.subTest(source=source), self.assertRaises(extractor.ExtractionError):
                extractor.decode_descriptor(source)

    def test_array_literal_order_and_lea_initialization_exclusion(self):
        code = synthetic_code([(2, 0), (2, 1), (2, 2)], lea=True)
        self.assertEqual(extractor.ordered_fragments(code, 0x1000, FakePE(), FakeMetadata(), {0x4000: 1}),
                         ["QUFB", "QkJC", "Q0ND"])

    def test_register_concat_uses_argument_order_not_load_order(self):
        code = synthetic_code([(9, 3), (8, 2), (2, 1), (1, 0)])
        self.assertEqual(extractor.ordered_fragments(code, 0x1000, FakePE(), FakeMetadata(), {0x4000: 4}),
                         list(FakeMetadata.literals))

    def test_missing_concat_or_ambiguous_arguments_rejected(self):
        for code in (synthetic_code([(1, 0)], concat=False), synthetic_code([(1, 0), (1, 1)])):
            with self.subTest(code=code), self.assertRaises(extractor.ExtractionError):
                extractor.ordered_fragments(code, 0x1000, FakePE(), FakeMetadata(), {0x4000: 2})

    def test_chained_unwind_ranges_cover_whole_method(self):
        pe = extractor.PE(bytes(synthetic_pe()))
        self.assertEqual(pe.function_ends[0x140001200], 0x140001280)
        self.assertEqual(pe.offset(0x140001100, 24), 0x300)

    def test_malformed_pe_and_chained_cycle_rejected(self):
        broken = synthetic_pe()
        struct.pack_into("<III", broken, 0x524, 0x1210, 0x1280, 0x1320)
        for data in (b"not a PE", bytes(broken)):
            with self.subTest(size=len(data)), self.assertRaises(extractor.ExtractionError):
                extractor.PE(data)

    def test_hash_gate_rejects_other_build_before_parsing(self):
        with mock.patch.object(pathlib.Path, "read_bytes", return_value=b"synthetic file"):
            with self.assertRaisesRegex(extractor.ExtractionError, "unsupported original input"):
                extractor.checked_input("GameAssembly.dll", "0" * 64)
            self.assertEqual(extractor.checked_input("synthetic", hashlib.sha256(b"synthetic file").hexdigest()), b"synthetic file")

    def test_output_outside_ignored_local_rejected_before_reading_input(self):
        with self.assertRaisesRegex(extractor.ExtractionError, "ignored local"):
            extractor.extract("absent.dll", "absent.dat", extractor.ROOT / "tools/descriptors")


if __name__ == "__main__":
    unittest.main()
