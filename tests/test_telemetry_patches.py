"""Asset-free patch safety tests, plus explicitly enabled read-only validation."""
from dataclasses import replace
import hashlib
import ctypes
import os
import platform
from pathlib import Path, PurePosixPath
import struct
import unittest

from client_patch.patcher.telemetry import (
    CEF_COMPONENT_PATH, CEF_HANDLER_COMPONENT_PATH, COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED,
    Component, Patch, _apply_recipe, patch_component,
)


class TelemetryPatchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.original = bytes(range(64))
        self.first = Patch("synthetic first", 8, 8, self.original[8:24], b"AB")
        self.second = Patch("synthetic second", 40, 40, self.original[40:56], b"CD")
        self.recipe = Component(hashlib.sha256(self.original).hexdigest(),
                                (self.second, self.first))

    def test_only_replacement_bytes_change_and_input_is_immutable(self):
        patched = _apply_recipe(self.original, self.recipe)
        self.assertEqual(self.original, bytes(range(64)))
        self.assertEqual(len(patched), len(self.original))
        changed = {i for i, (a, b) in enumerate(zip(self.original, patched)) if a != b}
        self.assertEqual(changed, {8, 9, 40, 41})
        self.assertEqual(patched[8:10], b"AB")
        self.assertEqual(patched[40:42], b"CD")

    def test_hash_rejects_corruption_outside_guards(self):
        corrupted = self.original[:-1] + b"x"
        with self.assertRaisesRegex(ValueError, "SHA256"):
            _apply_recipe(corrupted, self.recipe)

    def test_guard_rejects_corruption_even_with_matching_hash(self):
        corrupted = self.original[:42] + b"x" + self.original[43:]
        recipe = replace(self.recipe, original_sha256=hashlib.sha256(corrupted).hexdigest())
        with self.assertRaisesRegex(ValueError, "Original bytes mismatch"):
            _apply_recipe(corrupted, recipe)
        self.assertEqual(corrupted[8:10], self.original[8:10])

    def test_overlapping_guards_are_rejected(self):
        overlap = Patch("overlap", 16, 16, self.original[16:32], b"Z")
        recipe = replace(self.recipe, patches=(self.first, overlap))
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            _apply_recipe(self.original, recipe)

    def test_duplicate_patch_is_rejected(self):
        recipe = replace(self.recipe, patches=(self.first, self.first))
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            _apply_recipe(self.original, recipe)

    def test_adjacent_guards_are_allowed(self):
        adjacent = Patch("adjacent", 24, 24, self.original[24:40], b"Z")
        patched = _apply_recipe(self.original, replace(self.recipe, patches=(self.first, adjacent)))
        self.assertEqual(patched[24:25], b"Z")

    def test_invalid_bounds_or_lengths_are_rejected(self):
        invalid = (
            replace(self.first, offset=-1),
            replace(self.first, offset=True),
            replace(self.first, offset=None),
            replace(self.first, offset="8"),
            replace(self.first, offset=60),
            replace(self.first, guard=b""),
            replace(self.first, replacement=b""),
            replace(self.first, replacement=bytes(17)),
            replace(self.first, guard=bytes(33)),
        )
        for patch in invalid:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                _apply_recipe(self.original, replace(self.recipe, patches=(patch,)))

    def test_mutable_input_is_rejected(self):
        with self.assertRaises(TypeError):
            _apply_recipe(bytearray(self.original), self.recipe)

    def test_already_modified_input_is_rejected(self):
        patched = _apply_recipe(self.original, self.recipe)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            _apply_recipe(patched, self.recipe)

    def test_supported_originals_remain_hash_gated(self):
        for name in COMPONENTS:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "SHA256"):
                patch_component(name, b"MZ" + bytes(64))

    def test_unknown_components_and_path_aliases_are_rejected(self):
        for name in ("unknown.dll", "other/GameAssembly.dll", "chrome_elf.dll", "libcef.dll",
                     "../" + CEF_HANDLER_COMPONENT_PATH,
                     "./" + CEF_COMPONENT_PATH, "../" + CEF_COMPONENT_PATH,
                     "/" + CEF_COMPONENT_PATH, CEF_COMPONENT_PATH.replace("/", "\\"), None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsupported"):
                patch_component(name, self.original)

    def test_only_reviewed_recipes_are_present(self):
        self.assertFalse(RUNTIME_VALIDATED)
        self.assertEqual(RECIPE_VERSION, 10)
        self.assertEqual(len(COMPONENTS["GameAssembly.dll"].patches), 42)
        self.assertEqual({p.rva for p in COMPONENTS["UnityPlayer.dll"].patches},
                         {0xC90C2A, 0x80366F, 0xC93D10, 0xD84EC6, 0xD84E3E,
                          0x292110, 0xC8C5F3, 0xC66C20, 0xC2F570, 0xC333DA,
                          0x2078B0, 0xC2F3FC, 0x207A60, 0xC381D0, 0xC37400,
                          0xC33440, 0x1FD3A0, 0x1FDA50, 0xC392C0, 0xC2E240, 0xC40840, 0x20C560,
                          0xC2F790, 0xC2FC09, 0xC3016B, 0xC30273, 0xC3A5D0,
                          0xC39D14, 0xC3A2A5, 0xC41F0C, 0xC32468, 0x2048A0, 0x204CB0})
        self.assertEqual(len(COMPONENTS), 4)
        self.assertEqual([p.rva for p in COMPONENTS[CEF_COMPONENT_PATH].patches], [0x323A0])
        self.assertEqual([p.rva for p in COMPONENTS[CEF_HANDLER_COMPONENT_PATH].patches], [0x17403D0])
        for name, component in COMPONENTS.items():
            path = PurePosixPath(name)
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
            self.assertEqual(str(path), name)
            self.assertEqual(len(component.original_sha256), 64)
            end = 0
            for patch in sorted(component.patches, key=lambda item: item.offset):
                self.assertIn(len(patch.guard), (15, 16, 32))
                self.assertLessEqual(len(patch.replacement), len(patch.guard))
                self.assertGreaterEqual(patch.offset, end)
                end = patch.offset + len(patch.guard)

    def test_internal_append_guards_preserve_drain_and_payload_lifecycle(self):
        patches={p.rva:p for p in COMPONENTS['UnityPlayer.dll'].patches}
        for rva in (0xc392c0,0xc2e240):
            self.assertEqual(patches[rva].replacement,b'\x31\xc0\xc3')
        # Do not solve collection by skipping release/state progress or by
        # returning from a constructor whose initialized fields callers destroy.
        for first,last in ((0xc3a680,0xc3b1e7),(0xc49110,0xc49dc0)):
            self.assertFalse(any(first<=rva<last for rva in patches))
        for shared in (0x154920,0x155710,0xc65160,0x9fb910,0xc4df10,0xc300f0):self.assertNotIn(shared,patches)

    def test_configuration_redirect_preserves_original_tail_and_existing_sentinel_path(self):
        patches={p.rva:p for p in COMPONENTS['UnityPlayer.dll'].patches}
        prepare=patches[0xc2f790]
        self.assertEqual(prepare.replacement[:1],b'\xe9')
        self.assertEqual(prepare.rva+5+struct.unpack_from('<i',prepare.replacement,1)[0],0xc300f0)
        query=patches[0xc2fc09]
        self.assertEqual(query.guard[0],0xe8)
        self.assertEqual(query.rva+5+struct.unpack_from('<i',query.guard,1)[0],0x9fb910)
        self.assertEqual(query.guard[5:7],b'\xeb\x07')
        self.assertEqual(query.replacement[:1],b'\xe9')
        self.assertEqual(query.rva+5+struct.unpack_from('<i',query.replacement,1)[0],query.rva+7)
        self.assertEqual(query.guard[7:10],b'\x48\x8d\x05')

    def test_ads_payload_branches_retain_state_progress_and_register_restore_targets(self):
        patches={p.rva:p for p in COMPONENTS['UnityPlayer.dll'].patches}
        for site,target in ((0xc3016b,0xc30223),(0xc30273,0xc3077c)):
            patch=patches[site]
            self.assertEqual(patch.replacement[:1],b'\xe9')
            self.assertEqual(site+5+struct.unpack_from('<i',patch.replacement,1)[0],target)
        # No edits to dirty reset,conditional recursive drain or the saved-register
        # restore. Shared serializers/constructors retain their existing exclusions.
        for first,last in ((0xc300f0,0xc3016b),(0xc30223,0xc30273),(0xc3077c,0xc307b6)):
            self.assertFalse(any(first<=rva<last for rva in patches))
        self.assertEqual(patches[0xc3a5d0].replacement,b'\xc3')

    def test_cache_guards_only_remove_serializer_call_and_select_original_query_fallback(self):
        patches={p.rva:p for p in COMPONENTS['UnityPlayer.dll'].patches}
        for site in (0xc39d14,0xc3a2a5,0xc41f0c):
            patch=patches[site]
            self.assertEqual(patch.guard[0],0xe8)
            self.assertEqual(site+5+struct.unpack_from('<i',patch.guard,1)[0],0xc4e140)
            self.assertEqual(patch.replacement,b'\x90'*5)
        query=patches[0xc32468]
        self.assertEqual(query.rva+5+struct.unpack_from('<i',query.guard,1)[0],0x9fb910)
        self.assertEqual(query.guard[5:10],bytes.fromhex('eb07488d05'))
        self.assertEqual(query.rva+5+struct.unpack_from('<i',query.replacement,1)[0],0xc3246f)
        for shared in (0xc4e140,0xc4d8b0,0xc39ce0,0xc3a250,0xc41ec0,0xc32430):
            self.assertNotIn(shared,patches)

    def test_registration_skips_keep_existing_branch_destinations(self):
        patches = {p.rva: p for p in COMPONENTS["UnityPlayer.dll"].patches}
        for rva in (0x80366F, 0xD84EC6, 0xC8C5F3):
            with self.subTest(rva=hex(rva)):
                patch = patches[rva]
                self.assertEqual(patch.guard[:2], b"\x0f\x85")
                self.assertEqual(patch.replacement[:1], b"\xe9")
                self.assertEqual(patch.replacement[5:], b"\x90")
                before = rva + 6 + struct.unpack_from("<i", patch.guard, 2)[0]
                after = rva + 5 + struct.unpack_from("<i", patch.replacement, 1)[0]
                self.assertEqual(after, before)

    def test_disabled_defaults_preserve_constructor_instructions(self):
        patches = {p.rva: p for p in COMPONENTS["UnityPlayer.dll"].patches}
        # Only the true immediate changes; object addresses and other defaults stay.
        for rva, changed_index in ((0xD84E3E, 4), (0xC333DA, 7), (0xC2F3FC, 6)):
            with self.subTest(rva=hex(rva)):
                patch = patches[rva]
                before = patch.guard[:len(patch.replacement)]
                changes = [(i, a, b) for i, (a, b) in
                           enumerate(zip(before, patch.replacement)) if a != b]
                self.assertEqual(changes, [(changed_index, 1, 0)])

    def test_every_release_guard_is_checked_before_mutation(self):
        # Compact synthetic image tests every shipped guard, including bytes after
        # short RET/XOR replacements, without needing or bundling game files.
        for name, component in COMPONENTS.items():
            image = bytearray(32 * len(component.patches))
            patches = []
            for i, patch in enumerate(component.patches):
                offset = 32 * i
                image[offset:offset + len(patch.guard)] = patch.guard
                patches.append(replace(patch, offset=offset))
            for patch in patches:
                with self.subTest(component=name, patch=patch.label):
                    corrupted = bytearray(image)
                    corrupted[patch.offset + len(patch.guard) - 1] ^= 1
                    original = bytes(corrupted)
                    recipe = Component(hashlib.sha256(original).hexdigest(), tuple(patches))
                    with self.assertRaisesRegex(ValueError, "Original bytes mismatch"):
                        _apply_recipe(original, recipe)
                    self.assertEqual(bytes(corrupted), original)


@unittest.skipUnless(os.environ.get("BA_TELEMETRY_ORIGINAL_DIR"),
                     "Set BA_TELEMETRY_ORIGINAL_DIR for optional local originals; no runtime test")
class TelemetryOriginalTests(unittest.TestCase):
    def test_local_originals_and_unrelated_bytes(self):
        directory = Path(os.environ["BA_TELEMETRY_ORIGINAL_DIR"])
        for name, component in COMPONENTS.items():
            with self.subTest(component=name):
                original = (directory / name).read_bytes()
                patched = patch_component(name, original)
                self.assertEqual(len(patched), len(original))
                cursor = 0
                for patch in sorted(component.patches, key=lambda item: item.offset):
                    self.assertEqual(patched[cursor:patch.offset], original[cursor:patch.offset])
                    cursor = patch.offset + len(patch.replacement)
                    self.assertEqual(patched[patch.offset:cursor], patch.replacement)
                self.assertEqual(patched[cursor:], original[cursor:])
                self.assertEqual(hashlib.sha256(original).hexdigest(), component.original_sha256)


@unittest.skipUnless(os.name == 'nt' and struct.calcsize('P') == 8
                     and platform.machine().lower() in ('amd64', 'x86_64'),
                     'Authored replacement execution requires Windows x64')
class TelemetryReplacementExecutionTests(unittest.TestCase):
    """Execute only our authored replacement bytes, never any original game code."""
    def executable(self, code, result, *arguments):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.VirtualAlloc.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong)
        kernel.VirtualAlloc.restype = ctypes.c_void_p
        kernel.VirtualProtect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong))
        kernel.VirtualFree.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong)
        kernel.FlushInstructionCache.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        address = kernel.VirtualAlloc(None, len(code), 0x3000, 0x04)
        self.assertTrue(address, ctypes.get_last_error())
        self.addCleanup(lambda: kernel.VirtualFree(address, 0, 0x8000))
        ctypes.memmove(address, code, len(code))
        previous = ctypes.c_ulong()
        self.assertTrue(kernel.VirtualProtect(address, len(code), 0x20, ctypes.byref(previous)))
        self.assertTrue(kernel.FlushInstructionCache(kernel.GetCurrentProcess(), address, len(code)))
        return ctypes.WINFUNCTYPE(result, *arguments)(address)

    def test_device_guard_only_resets_completed_marker_and_returns(self):
        patch = next(p for p in COMPONENTS['UnityPlayer.dll'].patches if p.rva == 0xc40840)
        invoke = self.executable(patch.replacement, None, ctypes.c_void_p, ctypes.c_ubyte)
        for marker in (0, 1, 2, 3, 0xffffffff):
            for flag in (0, 1):
                with self.subTest(marker=marker, flag=flag):
                    before = bytearray(b'\xa5' * 0x1660)
                    struct.pack_into('<I', before, 0x1490, marker)
                    buffer = (ctypes.c_ubyte * len(before)).from_buffer_copy(before)
                    invoke(ctypes.addressof(buffer), flag)
                    expected = bytearray(before)
                    if marker == 2:
                        struct.pack_into('<I', expected, 0x1490, 0)
                    self.assertEqual(bytes(buffer), bytes(expected))

    def test_identity_setters_do_not_dereference_borrowed_managed_inputs(self):
        patches={p.rva:p for p in COMPONENTS['UnityPlayer.dll'].patches}
        for shared in (0x207990,0x1fdb90,0xc33490,0xc307c0,0x4b2e30,0x15b680):
            self.assertNotIn(shared,patches)
        for rva in (0x2048a0,0x204cb0):
            patch=patches[rva];self.assertEqual(patch.replacement,b'\xc3')
            invoke=self.executable(patch.replacement,None,ctypes.c_void_p)
            invoke(None);invoke(1);invoke(0xffffffffffffffff)


    def test_handler_guard_returns_handled_zero_without_reading_arguments(self):
        patch, = COMPONENTS[CEF_HANDLER_COMPONENT_PATH].patches
        invoke = self.executable(patch.replacement, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        self.assertEqual(invoke(0, None, None), 0)
        self.assertEqual(invoke(123, ctypes.c_void_p(1), ctypes.c_void_p(1)), 0)

    def test_queue_event_guard_returns_false_before_reading_borrowed_inputs(self):
        patch = next(p for p in COMPONENTS['UnityPlayer.dll'].patches if p.rva == 0x20c560)
        invoke = self.executable(patch.replacement, ctypes.c_ubyte,
                                 ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p)
        self.assertEqual(invoke(None,None,0,None),0)
        self.assertEqual(invoke(1,1,0xffffffff,1),0)

    def test_configuration_tail_branch_preserves_borrowed_argument_registers(self):
        patch=next(p for p in COMPONENTS['UnityPlayer.dll'].patches if p.rva==0xc2f790)
        target=5+struct.unpack_from('<i',patch.replacement,1)[0]
        # Authored callee writes RDX/R8/R9 to our output,then returns directly to
        # Python. No original collector,serializer,query or state code executes.
        callee=bytes.fromhex('4889114c8941084c894910c3')
        code=patch.replacement+b'\x90'*(target-len(patch.replacement))+callee
        invoke=self.executable(code,None,ctypes.c_void_p,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint64)
        output=(ctypes.c_uint64*3)()
        expected=(0x0123456789abcdef,0xfedcba9876543210,0x1122334455667788)
        invoke(ctypes.addressof(output),*expected)
        self.assertEqual(tuple(output),expected)

    def test_query_branch_reaches_existing_fallback_location(self):
        for site in (0xc2fc09,0xc32468):
            patch=next(p for p in COMPONENTS['UnityPlayer.dll'].patches if p.rva==site)
            target=5+struct.unpack_from('<i',patch.replacement,1)[0]
            # Authored target returns123;no original game instruction executes.
            code=patch.replacement+b'\x90'*(target-len(patch.replacement))+bytes.fromhex('b87b000000c3')
            self.assertEqual(self.executable(code,ctypes.c_int)(),123)

    def test_cache_call_skips_preserve_empty_outputs_and_continue_to_progress(self):
        patches={p.rva:p for p in COMPONENTS['UnityPlayer.dll'].patches}
        # Authored continuation increments RCX counter;authored serializer at32
        # writes RDX output. A CALL reversal proves the stand-in can detect writes.
        for site in (0xc39d14,0xc3a2a5,0xc41f0c):
            for revert,expected in ((False,0),(True,1)):
                head=bytes.fromhex('e81b000000') if revert else patches[site].replacement
                code=head+bytes.fromhex('48ff01c3')+b'\x90'*23+bytes.fromhex('48c70201000000c3')
                progress=ctypes.c_uint64();output=ctypes.c_uint64()
                self.executable(code,None,ctypes.c_void_p,ctypes.c_void_p)(ctypes.addressof(progress),ctypes.addressof(output))
                self.assertEqual((progress.value,output.value),(1,expected))

    def test_paired_ads_branches_skip_local_regions_but_execute_progress_standin(self):
        patches={p.rva:p for p in COMPONENTS['UnityPlayer.dll'].patches}
        start=0xc3016b;second=0xc30273-start;progress=0xc30223-start;end=0xc3077c-start
        code=bytearray(b'\x90'*(end+1))
        code[:5]=patches[start].replacement
        code[second:second+5]=patches[start+second].replacement
        # Authored stand-ins touch separate counters for skipped construction,
        # retained progress,and skipped destruction. No original instructions,
        # collector,stack frame,serializer or native state is executed here.
        code[5:13]=bytes.fromhex('48c7410801000000')
        code[progress:progress+3]=bytes.fromhex('48ff01')
        code[second+5:second+13]=bytes.fromhex('48c7411001000000')
        code[end]=0xc3
        for disabled,expected in ((None,(1,0,0)),(0,(1,1,0)),(second,(1,0,1))):
            trial=bytearray(code)
            if disabled is not None:trial[disabled:disabled+5]=b'\x90'*5
            output=(ctypes.c_uint64*3)()
            self.executable(bytes(trial),None,ctypes.c_void_p)(ctypes.addressof(output))
            self.assertEqual(tuple(output),expected)

    def test_base_configuration_guard_does_not_read_caller_outputs(self):
        patch=next(p for p in COMPONENTS['UnityPlayer.dll'].patches if p.rva==0xc3a5d0)
        invoke=self.executable(patch.replacement,None,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)
        invoke(None,None,None)
        invoke(1,1,1)


if __name__ == "__main__":
    unittest.main()
