"""Authored PE controls for movement-only relocated repeat-focus hooks."""
from contextlib import ExitStack
import copy
import hashlib
import struct
import unittest
from unittest.mock import patch

from client_patch.patcher import patch_client
from client_patch.patcher import prediction_actor_repair as actor
from client_patch.patcher import prediction_selection as selection


def fixture():
    data = bytearray(0xa00)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x8664, 2)
    struct.pack_into('<H', data, 0x94, 0xf0)
    opt = 0x98
    struct.pack_into('<H', data, opt, 0x20b)
    struct.pack_into('<Q', data, opt + 24, 0x180000000)
    for at, value in ((4, 0x200), (8, 0x400), (32, 0x1000), (36, 0x200),
                      (56, 0x5000), (60, 0x400), (108, 16)):
        struct.pack_into('<I', data, opt + at, value)
    struct.pack_into('<II', data, opt + 112 + 5 * 8, 0x4200, 16)
    for at, name, rva, size, raw, flags in (
            (0x188, b'.text', 0x1000, 0x200, 0x400, 0x60000020),
            (0x1b0, b'.rdata', 0x4000, 0x400, 0x600, 0x40000040)):
        struct.pack_into('<8sIIIIIIHHI', data, at, name, size, rva, size, raw, 0, 0, 0, 0, flags)
    data[0x400:0x402] = b'\xc3\xc3'
    data[0x620:0x625] = b'\xe8\x01\x02\x03\x04'
    data[0x630:0x633] = b'\x45\x33\xc0'
    data[0x640:0x646] = b'\x90' * 6
    struct.pack_into('<QQ', data, 0x690, 0x180001000, 0x180001001)
    struct.pack_into('<II4H', data, 0x800, 0x4000, 16, 0xa090, 0xa098, 0, 0)
    return bytes(data)


class PredictionFocusPatchTests(unittest.TestCase):
    def setUp(self):
        self.original = fixture()
        self.sha = hashlib.sha256(self.original).hexdigest()
        self.pointer = dict(name='AuthoredRepeatNext', rva=0x4090, offset=0x690,
                            before=self.original[0x690:0x698].hex(), target_rva=0x1000,
                            relocation_block_offset=0x800,
                            relocation_block_before=self.original[0x800:0x808].hex(),
                            relocation_entry_offset=0x808,
                            relocation_entry_before='90a0')
        self.quit = dict(self.pointer, name='AuthoredQuit', rva=0x4098, offset=0x698,
                         before=self.original[0x698:0x6a0].hex(), target_rva=0x1001,
                         relocation_entry_offset=0x80a, relocation_entry_before='98a0')
        self.call = dict(name='AuthoredChooser', rva=0x4020, offset=0x620, before='e801020304')
        self.byte_patch = dict(name='Authored repeat argument', rva=0x4030, offset=0x630,
                               before='4533c0', after='4588f0')
        self.ordinary = dict(name='AuthoredOrdinary', rva=0x4040, offset=0x640, before='90' * 6)

    def recipe(self, *, quit_hooks=None):
        stack = ExitStack()
        stack.enter_context(patch.object(actor, 'TAIL_HOOKS', []))
        for module in (actor, selection):
            stack.enter_context(patch.object(module, 'SUPPORTED_ORIGINAL_SHA256', self.sha))
            stack.enter_context(patch.object(module, 'CALL_HOOKS', [self.call]))
            stack.enter_context(patch.object(module, 'POINTER_HOOKS', [self.pointer]))
            stack.enter_context(patch.object(module, 'PATCHES', [self.byte_patch]))
            stack.enter_context(patch.object(module, 'BODY_GUARDS', []))
        stack.enter_context(patch.object(patch_client, 'ORIGINAL_SHA256', self.sha))
        for name in ('PATCHES', 'HOOKS', 'TAIL_HOOKS', 'CALL_HOOKS', 'COMMUNITY_CALL_HOOKS',
                     'COMMUNITY_TAIL_HOOKS', 'COSMETIC_PATCHES', 'COSMETIC_CALL_HOOKS',
                     'COSMETIC_TAIL_HOOKS', 'QUIT_CALL_HOOKS', 'DLSS_PRIVACY_PATCHES'):
            stack.enter_context(patch.object(patch_client, name, []))
        stack.enter_context(patch.object(patch_client, 'QUIT_POINTER_HOOKS', quit_hooks or []))
        stack.enter_context(patch.object(patch_client, 'HOOKS', [self.ordinary]))
        stack.enter_context(patch.object(patch_client.prediction_worker_patch, 'CALL_HOOKS', []))
        stack.enter_context(patch.object(patch_client.telemetry, 'patch_component', side_effect=lambda _, data: data))
        return stack

    def test_pointer_guard_pins_mapping_original_target_and_unique_pe_dir64(self):
        result = actor.validate_pointer_hooks(self.original, [self.pointer])
        self.assertEqual(result[0]['image_base'], 0x180000000)
        self.assertEqual(result[0]['relocation_directory_rva'], 0x4200)
        self.assertEqual(result[0]['relocation_directory_size'], 16)
        self.assertEqual(self.original, fixture())

    def test_wrong_slot_target_or_relocation_descriptors_refuse(self):
        changes = (dict(offset=0x691), dict(rva=0x4091), dict(rva=0x5000),
                   dict(target_rva=0x1001), dict(target_rva=0x5000), dict(before='00' * 8),
                   dict(relocation_block_offset=0x801), dict(relocation_entry_offset=0x800),
                   dict(relocation_entry_offset=0x809), dict(relocation_entry_offset=0x810),
                   dict(relocation_block_before='00' * 8), dict(relocation_entry_before='0000'))
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                actor.validate_pointer_hooks(self.original, [dict(self.pointer, **change)])

    def test_wrong_relocation_type_page_duplicate_or_truncated_directory_refuse(self):
        mutations = ((0x808, '<H', 0x3090), (0x800, '<I', 0x5000),
                     (0x80a, '<H', 0xa090), (0x804, '<I', 18),
                     (0x98 + 112 + 5 * 8 + 4, '<I', 10), (0x98 + 108, '<I', 5))
        for at, fmt, value in mutations:
            data = bytearray(self.original); struct.pack_into(fmt, data, at, value)
            hook = dict(self.pointer, relocation_block_before=data[0x800:0x808].hex(),
                        relocation_entry_before=data[0x808:0x80a].hex())
            with self.subTest(at=at, value=value), self.assertRaises(ValueError):
                actor.validate_pointer_hooks(bytes(data), [hook])

    def test_relocation_block_must_be_actual_directory_boundary(self):
        data = bytearray(self.original)
        data[0x820:0x830] = data[0x800:0x810]
        hook = dict(self.pointer, relocation_block_offset=0x820, relocation_entry_offset=0x828)
        with self.assertRaisesRegex(ValueError, 'not in the PE directory'):
            actor.validate_pointer_hooks(bytes(data), [hook])

    def test_all_pointer_guards_precede_transform_or_import_publication(self):
        with self.recipe(), patch.object(actor, 'POINTER_HOOKS', [dict(self.pointer, offset=0x691)]), \
                patch.object(patch_client.telemetry, 'patch_component') as transform, \
                patch.object(patch_client, 'extend_imports_with_thunks') as imports:
            with self.assertRaises(ValueError):
                patch_client.build_patch(self.original, community=True, prediction_worker=True, prediction_movement=True)
            transform.assert_not_called(); imports.assert_not_called()

    def test_default_worker_and_quit_lists_remain_isolated(self):
        quit_hooks = [copy.deepcopy(self.quit)]
        with self.recipe(quit_hooks=quit_hooks):
            ordinary = patch_client.build_patch(self.original)
            worker = patch_client.build_patch(self.original, community=True, prediction_worker=True)
            candidate = patch_client.build_patch(self.original, community=True, prediction_worker=True,
                                                   prediction_movement=True, quit_diagnostics=True)
            self.assertEqual(quit_hooks, [self.quit])
            after = patch_client.build_patch(self.original)
        self.assertEqual(ordinary, worker); self.assertEqual(ordinary, after)
        self.assertEqual(ordinary[0x690:0x6a0], self.original[0x690:0x6a0])
        self.assertEqual(ordinary[0x630:0x633], b'\x45\x33\xc0')
        self.assertEqual(candidate[0x630:0x633], b'\x45\x88\xf0')
        self.assertEqual(candidate[0x800:0x810], self.original[0x800:0x810])

    def test_real_pe_thunk_and_iat_binding_are_constructed_for_pointer_export(self):
        with self.recipe():
            candidate = patch_client.build_patch(self.original, community=True,
                                                  prediction_worker=True, prediction_movement=True)
        base = 0x180000000
        thunk = struct.unpack_from('<Q', candidate, 0x690)[0] - base
        raw = actor.rva_to_offset(candidate, thunk, 6)
        self.assertEqual(candidate[raw:raw + 2], b'\xff\x25')
        iat = thunk + 6 + struct.unpack_from('<i', candidate, raw + 2)[0]
        name_rva = struct.unpack_from('<Q', candidate, actor.rva_to_offset(candidate, iat, 8))[0]
        name_offset = actor.rva_to_offset(candidate, name_rva, 2)
        self.assertEqual(candidate[name_offset + 2:name_offset + 2 + len(self.pointer['name']) + 1],
                         self.pointer['name'].encode() + b'\0')
        # The loader adds the original DIR64 delta to the preferred thunk VA.
        loaded_base = 0x7ff000000000
        self.assertEqual(struct.unpack_from('<Q', candidate, 0x690)[0] + loaded_base - base,
                         loaded_base + thunk)

    def test_argument_patch_guard_is_independent_of_file_hash(self):
        for change in (dict(offset=0x631), dict(rva=0x5000), dict(before='000000'), dict(after='45')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                actor.validate_byte_patches(self.original, [dict(self.byte_patch, **change)])

    def test_real_import_builder_refuses_missing_unmapped_or_cross_boundary_iat(self):
        for iat in (0, 0x5000, 0x43fc):
            data = bytearray(self.original)
            struct.pack_into('<II', data, 0x98 + 112 + 8, 0x4140, 40)
            struct.pack_into('<5I', data, 0x740, 0x41a0, 0, 0, 0x41c0, iat)
            data[0x7c0:0x7cd] = b'authored.dll\0'
            with self.subTest(iat=iat), self.assertRaisesRegex(ValueError, 'Incomplete import|not file-backed'):
                patch_client.extend_imports_with_thunks(bytes(data), 'BattleAcesOffline.dll',
                                                       ['AuthoredRepeatNext'], thunk_exports=['AuthoredRepeatNext'])

    def test_shipped_focus_sites_preserve_original_body_and_argument_abi(self):
        focus_pointers = [row for row in selection.POINTER_HOOKS
                          if row['name'] == 'OfflinePredictionRepeatFocusNext']
        self.assertEqual(len(focus_pointers), 1)
        pointer = focus_pointers[0]
        self.assertEqual((pointer['rva'], pointer['target_rva'], pointer['before']),
                         (0x6d4dc48, 0x3bf9de0, 'e09dbf8301000000'))
        calls = {row['rva']: row for row in selection.CALL_HOOKS}
        for site, target in ((0x3bfa10b, 0x3c646a0), (0x3bf306c, 0x3bf1650), (0x3bf322b, 0x32f97f0),
                             (0x3bf315d, 0x3e9e310), (0x3bfa027, 0x3e9e310)):
            raw = bytes.fromhex(calls[site]['before'])
            self.assertEqual(site + 5 + struct.unpack_from('<i', raw, 1)[0], target)
        self.assertEqual(selection.PATCHES[0]['before'], '4533c0')
        self.assertEqual(selection.PATCHES[0]['after'], '4588f0')
        self.assertNotIn(0x3bf9de0, {row['rva'] for row in selection.CALL_HOOKS})


if __name__ == '__main__':
    unittest.main()
