"""Authored PE-only regression cases; no DLL loads or native execution."""
import copy
from contextlib import ExitStack, contextmanager
import hashlib
import struct
import unittest
from unittest.mock import patch

from client_patch.patcher.pe_imports import PEFormatError, pe_checksum
from tests.test_prepare_prediction_native import fixture
from tools import prediction_crt_attach as target
from tools.prepare_prediction_native import _Image, _partition_heap_imports


def digest(data):
    return hashlib.sha256(data).hexdigest()


def original_fixture():
    data = bytearray(fixture())
    data[0x500:0x500 + len(target.ATTACH_BODY)] = target.ATTACH_BODY
    struct.pack_into('<I', data, 0x98 + 64, pe_checksum(data, 0x98 + 64))
    return bytes(data)


@contextmanager
def accepted_fixture(original=None):
    """Permit a synthetic original and its real import transform, never a DLL."""
    original = original_fixture() if original is None else original
    derived, manifest = _partition_heap_imports(original)
    with ExitStack() as stack:
        stack.enter_context(patch.object(target, 'SUPPORTED_ORIGINAL_SHA256', digest(original)))
        stack.enter_context(patch.object(target, 'ATTACH_RVA', 0x1100))
        stack.enter_context(patch('tools.prepare_prediction_native.SUPPORTED_ORIGINAL_SHA256', digest(original)))
        stack.enter_context(patch('tools.prepare_prediction_native.HEAP_IAT_RVAS', manifest['heap_iat_rvas']))
        yield original, derived, manifest


class PredictionCrtAttachTests(unittest.TestCase):
    def test_two_calls_only_and_valid_checksum_inputs_unmodified(self):
        with accepted_fixture() as (_, derived, manifest):
            before = copy.deepcopy(manifest)
            result, updated = target.defer_crt_thread_attach(derived, manifest)
            self.assertEqual(manifest, before)
            self.assertEqual(digest(derived), before['derived_sha256'])
            expected = bytearray(derived)
            for relative, call in target.CALLS:
                self.assertEqual(derived[0x500 + relative:0x500 + relative + 5], call)
                expected[0x500 + relative:0x500 + relative + 5] = target.RETURN_TRUE
            struct.pack_into('<I', expected, 0x98 + 64, pe_checksum(expected, 0x98 + 64))
            self.assertEqual(result, bytes(expected))
            self.assertEqual(_Image(result).u32(0x98 + 64), pe_checksum(result, 0x98 + 64))
            self.assertEqual(updated['derived_sha256'], digest(result))
            self.assertFalse(updated['crt_thread_attach_deferral']['runtime_qualified'])

    def test_manifest_retains_old_claims_only_under_earlier_derivation(self):
        with accepted_fixture() as (original, derived, manifest):
            manifest['caller_annotation'] = {'retained': True}
            result, updated = target.defer_crt_thread_attach(derived, manifest)
            self.assertEqual(updated['import_derivation'], manifest)
            self.assertEqual(updated['caller_annotation'], manifest['caller_annotation'])
            self.assertIsNot(updated['import_derivation'], manifest)
            self.assertFalse(updated['original_sections_preserved'])
            self.assertEqual([s['name'] for s in updated['preserved_original_sections']], ['.rdata'])
            self.assertEqual([s['name'] for s in updated['modified_original_sections']], ['.text'])
            section = updated['modified_original_sections'][0]
            self.assertEqual(section['original_sha256'], digest(original[0x400:0x600]))
            self.assertEqual(section['derived_sha256'], digest(result[0x400:0x600]))
            rebuilt = bytearray(original)
            for entry in updated['byte_patches']:
                start = entry['offset']
                before, after = (bytes.fromhex(entry[key]) for key in ('before_hex', 'after_hex'))
                self.assertEqual(rebuilt[start:start + len(before)], before)
                rebuilt[start:start + len(before)] = after
            self.assertEqual(bytes(rebuilt), result)
            self.assertEqual(updated['derived_size'], len(result))
            self.assertTrue(updated['original_iat_bytes_preserved'])

    def test_wrong_current_hash_rejected_atomically(self):
        with accepted_fixture() as (_, derived, manifest):
            manifest['derived_sha256'] = '0' * 64
            before = copy.deepcopy(manifest)
            with self.assertRaisesRegex(PEFormatError, 'Current derived SHA256'):
                target.defer_crt_thread_attach(derived, manifest)
            self.assertEqual(manifest, before)

    def test_wrong_original_hash_rejected(self):
        with accepted_fixture() as (_, derived, manifest):
            manifest['original_sha256'] = '0' * 64
            with self.assertRaisesRegex(PEFormatError, 'Unsupported original'):
                target.defer_crt_thread_attach(derived, manifest)

    def test_unrelated_edit_with_rewritten_current_hash_cannot_pass(self):
        with accepted_fixture() as (_, derived, manifest):
            changed = bytearray(derived)
            changed[0x420] ^= 1
            manifest['derived_sha256'] = digest(changed)
            with self.assertRaisesRegex(PEFormatError, 'Reconstructed original SHA256'):
                target.defer_crt_thread_attach(bytes(changed), manifest)

    def test_each_wrong_call_rejected_before_any_output_or_manifest_mutation(self):
        for relative, _ in target.CALLS:
            original = bytearray(original_fixture())
            original[0x500 + relative + 1] ^= 1
            with self.subTest(relative=relative), accepted_fixture(bytes(original)) as (_, derived, manifest):
                before = copy.deepcopy(manifest)
                with self.assertRaisesRegex(PEFormatError, 'Complete CRT thread-attach body guard'):
                    target.defer_crt_thread_attach(derived, manifest)
                self.assertEqual(manifest, before)

    def test_surrounding_body_guard_includes_epilogue(self):
        original = bytearray(original_fixture())
        original[0x500 + len(target.ATTACH_BODY) - 1] ^= 1
        with accepted_fixture(bytes(original)) as (_, derived, manifest):
            with self.assertRaisesRegex(PEFormatError, 'Complete CRT thread-attach body guard'):
                target.defer_crt_thread_attach(derived, manifest)

    def test_manifest_cannot_invent_preserved_sections_or_heap_import_claims(self):
        for field, value in (('preserved_original_sections', []), ('original_iat_bytes_preserved', False),
                             ('heap_iat_rvas', {}), ('loader_qualified', True)):
            with self.subTest(field=field), accepted_fixture() as (_, derived, manifest):
                manifest[field] = value
                with self.assertRaisesRegex(PEFormatError, 'metadata differs'):
                    target.defer_crt_thread_attach(derived, manifest)

    def test_invalid_journal_offsets_hex_and_append_are_atomic(self):
        with accepted_fixture() as (_, derived, manifest):
            cases = []
            for update in ({'offset': -1}, {'after_hex': 'zz'}, {'before_hex': '00' * 99}):
                changed = copy.deepcopy(manifest)
                changed['byte_patches'][0].update(update)
                cases.append(changed)
            changed = copy.deepcopy(manifest)
            changed['byte_patches'][-1]['after_hex'] = changed['byte_patches'][-1]['after_hex'][:-2]
            cases.append(changed)
            for changed in cases:
                before = copy.deepcopy(changed)
                with self.subTest(patch=changed['byte_patches'][0]), self.assertRaises(ValueError):
                    target.defer_crt_thread_attach(derived, changed)
                self.assertEqual(changed, before)

    def test_second_application_fails_closed(self):
        with accepted_fixture() as (_, derived, manifest):
            result, updated = target.defer_crt_thread_attach(derived, manifest)
            before = copy.deepcopy(updated)
            with self.assertRaisesRegex(PEFormatError, 'exact private import derivation'):
                target.defer_crt_thread_attach(result, updated)
            self.assertEqual(updated, before)

    def test_unrecognized_actual_original_rejected_without_fixture_override(self):
        derived, manifest = _partition_heap_imports(original_fixture())
        with self.assertRaisesRegex(PEFormatError, 'Unsupported original'):
            target.defer_crt_thread_attach(derived, manifest)


if __name__ == '__main__':
    unittest.main()
