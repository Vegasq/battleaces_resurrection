"""Asset-free patch safety tests, plus explicitly enabled read-only validation."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import unittest

from client_patch.patcher.telemetry import (
    COMPONENTS, RUNTIME_VALIDATED, Component, Patch, _apply_recipe, patch_component,
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

    def test_unknown_component_and_paths_are_rejected(self):
        for name in ("unknown.dll", "other/GameAssembly.dll", None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsupported"):
                patch_component(name, self.original)

    def test_only_reviewed_recipes_are_present(self):
        self.assertFalse(RUNTIME_VALIDATED)
        self.assertEqual(len(COMPONENTS["GameAssembly.dll"].patches), 42)
        self.assertEqual({p.rva for p in COMPONENTS["UnityPlayer.dll"].patches},
                         {0xC90C2A, 0x80366F, 0xC93D10})
        for component in COMPONENTS.values():
            self.assertEqual(len(component.original_sha256), 64)
            for patch in component.patches:
                self.assertEqual(len(patch.guard), 16)


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
