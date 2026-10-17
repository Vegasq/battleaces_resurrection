"""Asset-free patch safety tests, plus explicitly enabled read-only validation."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path, PurePosixPath
import struct
import unittest

from client_patch.patcher.telemetry import (
    CEF_COMPONENT_PATH, COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED,
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
        for name in ("unknown.dll", "other/GameAssembly.dll", "chrome_elf.dll",
                     "./" + CEF_COMPONENT_PATH, "../" + CEF_COMPONENT_PATH,
                     "/" + CEF_COMPONENT_PATH, CEF_COMPONENT_PATH.replace("/", "\\"), None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsupported"):
                patch_component(name, self.original)

    def test_only_reviewed_recipes_are_present(self):
        self.assertFalse(RUNTIME_VALIDATED)
        self.assertEqual(RECIPE_VERSION, 2)
        self.assertEqual(len(COMPONENTS["GameAssembly.dll"].patches), 42)
        self.assertEqual({p.rva for p in COMPONENTS["UnityPlayer.dll"].patches},
                         {0xC90C2A, 0x80366F, 0xC93D10, 0xD84EC6, 0xD84E3E,
                          0x292110, 0xC8C5F3, 0xC66C20, 0xC2F570, 0xC333DA,
                          0x2078B0, 0xC2F3FC, 0x207A60, 0xC381D0, 0xC37400,
                          0xC33440})
        self.assertEqual(len(COMPONENTS), 3)
        self.assertEqual([p.rva for p in COMPONENTS[CEF_COMPONENT_PATH].patches], [0x323A0])
        for name, component in COMPONENTS.items():
            path = PurePosixPath(name)
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
            self.assertEqual(str(path), name)
            self.assertEqual(len(component.original_sha256), 64)
            end = 0
            for patch in sorted(component.patches, key=lambda item: item.offset):
                self.assertIn(len(patch.guard), (15, 16))
                self.assertLessEqual(len(patch.replacement), len(patch.guard))
                self.assertGreaterEqual(patch.offset, end)
                end = patch.offset + len(patch.guard)

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


if __name__ == "__main__":
    unittest.main()
