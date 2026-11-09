"""File-only PE derivation checks; never load either synthetic/native DLL."""
import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from client_patch.patcher.pe_imports import PEFormatError, pe_checksum
from tools.prepare_prediction_native import (
    HEAP_IAT_RVAS, _partition_heap_imports, derive_native, prepare_native,
)


def fixture():
    data = bytearray(0xE00)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3C, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 2, 0, 0, 0, 0xF0, 0x2022)
    opt = 0x98
    struct.pack_into('<H', data, opt, 0x20B)
    struct.pack_into('<I', data, opt + 8, 0x800)
    struct.pack_into('<Q', data, opt + 24, 0x180000000)
    struct.pack_into('<II', data, opt + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, opt + 56, 0x3000, 0x400)
    struct.pack_into('<I', data, opt + 108, 16)
    struct.pack_into('<II', data, opt + 120, 0x2000, 60)
    struct.pack_into('<II', data, opt + 112 + 12 * 8, 0x2200, 0xD0)
    for index, (name, rva, raw, size, flags) in enumerate((
        (b'.text', 0x1000, 0x400, 0x200, 0x60000020),
        (b'.rdata', 0x2000, 0x600, 0x800, 0x40000040),
    )):
        struct.pack_into('<8sIIIIIIHHI', data, 0x188 + index * 40,
                         name, size, rva, size, raw, 0, 0, 0, 0, flags)
    data[0x400:0x600] = bytes(range(256)) * 2
    names = ['GetProcessHeap', 'HeapAlloc', 'HeapFree', 'GetTickCount64',
             'HeapReAlloc', 'VirtualProtect', 'HeapSize', 'CloseHandle']
    cursor = 0x900
    for index, (dll, ilt, iat, exports, name_rva) in enumerate((
        ('KERNEL32.dll', 0x2180, 0x2200, names, 0x2100),
        ('USER32.dll', 0x2280, 0x22C0, ['MessageBoxW'], 0x2120),
    )):
        struct.pack_into('<5I', data, 0x600 + index * 20, ilt, 0, 0, name_rva, iat)
        encoded = dll.encode() + b'\0'
        data[name_rva - 0x2000 + 0x600:name_rva - 0x2000 + 0x600 + len(encoded)] = encoded
        for item, name in enumerate(exports):
            encoded = struct.pack('<H', item + 7) + name.encode() + b'\0'
            data[cursor:cursor + len(encoded)] = encoded
            hint_rva = cursor - 0x600 + 0x2000
            struct.pack_into('<Q', data, ilt - 0x2000 + 0x600 + item * 8, hint_rva)
            struct.pack_into('<Q', data, iat - 0x2000 + 0x600 + item * 8, hint_rva)
            cursor += (len(encoded) + 1) & ~1
    return bytes(data)


def layout(data):
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    opt = pe + 24
    count = struct.unpack_from('<H', data, pe + 6)[0]
    table = opt + struct.unpack_from('<H', data, pe + 20)[0]
    sections = [struct.unpack_from('<8sIIIIIIHHI', data, table + index * 40)
                for index in range(count)]
    def mapped(rva):
        for section in sections:
            if section[2] <= rva < section[2] + section[3]:
                return section[4] + rva - section[2]
        raise AssertionError(hex(rva))
    def string(rva):
        offset = mapped(rva)
        return data[offset:data.index(b'\0', offset)].decode('ascii')
    imports = []
    rva, size = struct.unpack_from('<II', data, opt + 120)
    for index in range(size // 20):
        offset = mapped(rva + index * 20)
        row = struct.unpack_from('<5I', data, offset)
        if not any(row):
            break
        ilt, _, _, name, iat = row
        symbols = []
        while True:
            value = struct.unpack_from('<Q', data, mapped(ilt + len(symbols) * 8))[0]
            if not value:
                break
            symbol = value if value >> 63 else string(value + 2)
            hint = None if value >> 63 else struct.unpack_from('<H', data, mapped(value))[0]
            symbols.append((symbol, hint, iat + len(symbols) * 8))
        imports.append((string(name), row, symbols))
    return opt, table, sections, imports, mapped


class PredictionNativePreparationTests(unittest.TestCase):
    def test_partition_preserves_every_original_iat_slot_and_symbol(self):
        original = fixture()
        derived, manifest = _partition_heap_imports(original)
        _, _, _, before, mapped_before = layout(original)
        _, _, _, after, mapped_after = layout(derived)
        expected = [symbol for row in before for symbol in row[2]]
        actual = [symbol for row in after for symbol in row[2]]
        self.assertEqual(actual, expected)
        self.assertEqual([row[0] for row in after],
                         ['KERNEL32.dll', 'BAHeap.dll', 'KERNEL32.dll', 'BAHeap.dll',
                          'KERNEL32.dll', 'BAHeap.dll', 'KERNEL32.dll', 'USER32.dll'])
        for dll, _, symbols in after:
            for name, _, iat in symbols:
                self.assertEqual(dll == 'BAHeap.dll', name in HEAP_IAT_RVAS)
                self.assertEqual(derived[mapped_after(iat):mapped_after(iat) + 8],
                                 original[mapped_before(iat):mapped_before(iat) + 8])
        # The complete old sections, old descriptors, INTs and terminators survive.
        self.assertEqual(derived[0x400:len(original)], original[0x400:])
        self.assertEqual(len(manifest['ranges']), 7)

    def test_independent_null_terminated_ints_and_readonly_section(self):
        original = fixture()
        derived, manifest = _partition_heap_imports(original)
        opt, table, sections, imports, mapped = layout(derived)
        for _, row, symbols in imports[:-1]:
            self.assertEqual(struct.unpack_from('<Q', derived,
                             mapped(row[0] + len(symbols) * 8))[0], 0)
            self.assertGreaterEqual(row[0], sections[-1][2])
        self.assertEqual(sections[-1][-1], 0x40000040)
        self.assertEqual(derived[table:table + 80], original[table:table + 80])
        self.assertEqual(struct.unpack_from('<I', derived, opt + 64)[0],
                         pe_checksum(derived, opt + 64))
        before_dirs, after_dirs = manifest['directories_before'], manifest['directories_after']
        self.assertNotEqual(before_dirs['1'], after_dirs['1'])
        self.assertEqual({k: v for k, v in before_dirs.items() if k != '1'},
                         {k: v for k, v in after_dirs.items() if k != '1'})

    def test_manifest_patches_reconstruct_derived_bytes(self):
        original = fixture()
        derived, manifest = _partition_heap_imports(original)
        reconstructed = bytearray(original)
        for patch in manifest['byte_patches']:
            offset = patch['offset']
            before, after = bytes.fromhex(patch['before_hex']), bytes.fromhex(patch['after_hex'])
            self.assertEqual(reconstructed[offset:offset + len(before)], before)
            reconstructed[offset:offset + len(before)] = after
        self.assertEqual(bytes(reconstructed), derived)
        self.assertEqual(manifest['original_sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(manifest['derived_sha256'], hashlib.sha256(derived).hexdigest())

    def test_nonheap_ordinal_is_preserved(self):
        original = bytearray(fixture())
        ordinal = (1 << 63) | 17
        for offset in (0x780, 0x800):
            struct.pack_into('<Q', original, offset, ordinal)
        derived, _ = _partition_heap_imports(bytes(original))
        imports = layout(derived)[3]
        self.assertEqual(imports[0][2][0], (ordinal, None, 0x2200))

    def test_missing_or_duplicate_heap_name_refused(self):
        original = fixture()
        for replacement in (b'HeapSizX', b'HeapFree'):
            with self.subTest(replacement=replacement):
                changed = original.replace(b'HeapSize', replacement)
                with self.assertRaisesRegex(PEFormatError, 'exactly once'):
                    _partition_heap_imports(changed)

    def test_mismatched_or_unterminated_thunks_refused(self):
        original = fixture()
        changed = bytearray(original)
        struct.pack_into('<Q', changed, 0x808, 0x2FFF)
        with self.assertRaisesRegex(PEFormatError, 'IAT'):
            _partition_heap_imports(bytes(changed))
        changed = bytearray(original)
        struct.pack_into('<I', changed, 0x600, 0x27F8)
        struct.pack_into('<Q', changed, 0xDF8, 0x2300)
        struct.pack_into('<Q', changed, 0x800, 0x2300)
        with self.assertRaisesRegex(PEFormatError, 'file-backed'):
            _partition_heap_imports(bytes(changed))

    def test_conservative_pe_refusals_retained(self):
        original = fixture()
        cases = [original + b'overlay']
        signed = bytearray(original)
        struct.pack_into('<II', signed, 0x98 + 112 + 4 * 8, 0xD00, 16)
        cases.append(bytes(signed))
        no_room = bytearray(original)
        no_room[0x1D8] = 1
        cases.append(bytes(no_room))
        for changed in cases:
            with self.subTest(case=changed[-12:]), self.assertRaises(PEFormatError):
                _partition_heap_imports(changed)

    def test_public_derivation_requires_exact_original_sha_before_pe_parsing(self):
        for data in (b'', fixture()):
            with self.subTest(size=len(data)), self.assertRaisesRegex(ValueError, 'SHA256'):
                derive_native(data)

    def test_output_outside_private_local_tree_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'Simulation.dll'
            with self.assertRaisesRegex(ValueError, 'local'):
                prepare_native(Path(directory) / 'missing.dll', output)
            self.assertFalse(output.exists())

    def test_file_api_preserves_source_and_refuses_existing_or_wrong_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local').mkdir()
            source = root / 'original.dll'
            source.write_bytes(fixture())
            existing = root / 'local/existing.dll'
            existing.write_bytes(b'keep-existing-output')
            with patch('tools.prepare_prediction_native.ROOT', root):
                with self.assertRaises(FileExistsError):
                    prepare_native(source, existing)
                self.assertEqual(existing.read_bytes(), b'keep-existing-output')
                output = root / 'local/new/Simulation.dll'
                with self.assertRaisesRegex(ValueError, 'SHA256'):
                    prepare_native(source, output)
                self.assertFalse(output.exists())
                self.assertFalse(output.parent.exists())
            self.assertEqual(source.read_bytes(), fixture())


if __name__ == '__main__':
    unittest.main()
