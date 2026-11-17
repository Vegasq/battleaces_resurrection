"""Authored projection/ABI boundary controls; no original runtime or assets."""
import copy
import ctypes as C
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from server.native_simulation import decode_snapshot, NativeSimulation, SnapshotFormatError
from server import rust_snapshot_decoder as rust
from server.state_projection import STATE_MODES, resolve_mode, validate_state
from tests.snapshot_decoder_fixtures import _build, _changed, invalid_cases, json_refusal_cases
from tests.test_rust_worker_decoder import AuthoredLibrary, Export


class PythonProjectionTests(unittest.TestCase):
    def test_all_modes_equal_independent_full_projection_for_partial_and_unsorted_components(self):
        for kwargs in ({}, {"sparse": True}, {"reordered": True},
                       {"components": ("army", "position")}, {"components": ()}):
            raw, _ = _build(8, **kwargs)
            full = decode_snapshot(raw, mode="full")
            expected = [{k: e[k] for k in ("id", "army", "type")} for e in full["entities"]
                        if "army" in e and "type" in e]
            summary = {k: v for k, v in full.items() if k != "entities"}
            self.assertEqual(decode_snapshot(raw, mode="summary"), summary)
            self.assertEqual(decode_snapshot(raw, mode="ownership"), {**summary, "ownership": expected})
            self.assertEqual(decode_snapshot(raw, include_entities=True), full)
            self.assertEqual(decode_snapshot(raw), summary)

    def test_explicit_modes_all_reject_nonfinite_while_legacy_paths_are_preserved(self):
        for case in json_refusal_cases():
            for mode in STATE_MODES:
                with self.subTest(case=case["name"], mode=mode), self.assertRaises(SnapshotFormatError):
                    decode_snapshot(case["raw"], mode=mode)
            self.assertNotIn("entities", decode_snapshot(case["raw"]))
            self.assertIn("entities", decode_snapshot(case["raw"], include_entities=True))

    def test_every_mode_scans_malformed_omitted_components(self):
        for case in invalid_cases():
            for mode in STATE_MODES:
                with self.subTest(case=case["name"], mode=mode), self.assertRaises(SnapshotFormatError):
                    decode_snapshot(case["raw"], mode=mode)

    def test_selection_refusal_happens_before_native_acquisition(self):
        simulation = object.__new__(NativeSimulation)
        simulation.snapshot_bytes = Mock(side_effect=AssertionError("native called"))
        for kwargs in ({"mode": "other"}, {"mode": False}, {"mode": []},
                       {"mode": "full", "include_entities": False},
                       {"mode": "ownership", "include_entities": True}, {"include_entities": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                simulation.state(**kwargs)
        simulation.snapshot_bytes.assert_not_called()

    def test_complete_intersection_never_invents_missing_pairs(self):
        raw, meta = _build(3)
        army = meta["components"]["army"]
        unit_type = meta["components"]["type"]
        raw = _changed(raw, army["ids"] + 4, "I", 0)
        raw = _changed(raw, unit_type["ids"] + 4, "I", 0xffffffff)
        records = decode_snapshot(raw, mode="ownership")["ownership"]
        self.assertEqual([e["id"] for e in records], [101, 102])


class AdapterProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name).resolve() / "authored.dll"
        self.path.write_bytes(b"authored nonexecutable test library")
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.library = AuthoredLibrary()
        self.library.ba_snapshot_decoder_projection_version = Export(lambda: 1)
        self.v2_calls = []
        def v2(data, size, viewer, mode, result):
            self.v2_calls.append(mode)
            if self.library.output is None:
                self.library.output = json.dumps(decode_snapshot(C.string_at(data, size), viewer,
                                                    mode=STATE_MODES[mode])).encode()
                try:
                    return self.library.decode(data, size, viewer, False, result)
                finally:
                    self.library.output = None
            return self.library.decode(data, size, viewer, False, result)
        self.library.ba_decode_snapshot_v2 = Export(v2)
        self.loader = patch.object(rust.C, "CDLL", return_value=self.library).start()
        self.addCleanup(self.loader.stop)
        self.raw = _build(8, sparse=True)[0]

    def make(self):
        return rust.RustSnapshotDecoder(self.path, self.sha)

    def test_explicit_modes_use_v2_keep_info_exact_and_free_once(self):
        decoder = self.make()
        old_info = dict(decoder.info)
        self.assertEqual(decoder.projection_version, 1)
        for mode in STATE_MODES:
            self.assertEqual(decoder.decode(self.raw, mode=mode), decode_snapshot(self.raw, mode=mode))
        self.assertEqual(self.v2_calls, [0, 1, 2])
        self.assertEqual(len(self.library.freed), 3)
        self.assertEqual(decoder.info, old_info)
        self.assertEqual(set(old_info), {"implementation", "abi_version", "library_path", "library_sha256"})
        decoder.decode(self.raw)
        decoder.decode(self.raw, include_entities=True)
        self.assertEqual(self.v2_calls, [0, 1, 2])

    def test_missing_either_export_is_legacy_only_and_never_falls_back(self):
        for missing in ("ba_snapshot_decoder_projection_version", "ba_decode_snapshot_v2"):
            export = getattr(self.library, missing)
            delattr(self.library, missing)
            decoder = self.make()
            self.assertIsNone(decoder.projection_version)
            before = self.library.calls
            for mode in STATE_MODES:
                with self.assertRaisesRegex(rust.RustDecoderError, "capability"):
                    decoder.decode(self.raw, mode=mode)
            self.assertEqual(before, self.library.calls)
            decoder.decode(self.raw)
            setattr(self.library, missing, export)

    def test_present_wrong_projection_version_always_refuses(self):
        for version in (0, 2, 0xffffffff):
            self.library.ba_snapshot_decoder_projection_version = Export(lambda: version)
            with self.assertRaisesRegex(rust.RustDecoderError, "projection version"):
                self.make()
        self.assertEqual(self.library.calls, 0)

    def test_unknown_and_mixed_selection_refused_before_ffi(self):
        decoder = self.make()
        for kwargs in ({"mode": "bad"}, {"mode": 1}, {"mode": []},
                       {"mode": "ownership", "include_entities": False}, {"include_entities": 0}):
            with self.assertRaises(rust.RustDecoderError):
                decoder.decode(self.raw, **kwargs)
        self.assertEqual(self.library.calls, 0)

    def test_ownership_wrong_shapes_refuse_and_release_allocation(self):
        state = json.loads(json.dumps(decode_snapshot(self.raw, mode="ownership")))
        variants = []
        for change in ({"ownership": [] , "entities": []}, {"ownership": [{}]},
                       {"ownership": [{"id": 0, "army": 0}]},
                       {"ownership": [{"id": 0, "army": False, "type": 1}]},
                       {"ownership": [{"id": 2, "army": 0, "type": 1}, {"id": 1, "army": 0, "type": 1}]},
                       {"ownership": [{"id": 1, "army": 0, "type": 1}]*2},
                       {"ownership": [{"id": i, "army": 0, "type": 1} for i in range(9)]},
                       {"raw_sha256": "bad"}, {"byte_count": True}, {"resources": {"00": {}}}):
            variants.append(json.dumps({**copy.deepcopy(state), **change}).encode())
        variants.extend((b'{"x":1,"x":2}', b'{"x":NaN}', b"[]"))
        decoder = self.make()
        for encoded in variants:
            self.library.output = encoded
            before = len(self.library.freed)
            with self.subTest(encoded=encoded[:100]), self.assertRaises(rust.RustDecoderError):
                decoder.decode(self.raw, mode="ownership")
            self.assertEqual(len(self.library.freed), before + 1)

    def test_full_and_summary_reject_other_mode_shapes_and_malformed_components(self):
        full = json.loads(json.dumps(decode_snapshot(self.raw, mode="full")))
        variants = [dict(full, ownership=[]), {**full, "entities": full["entities"][::-1]},
                    {**full, "entities": [{"id": 1, "max_health": 2}]},
                    {**full, "entities": [{"id": 1, "position": [1, 2, 3]}]},
                    {**full, "counts": {**full["counts"], "army": 99}}]
        decoder = self.make()
        for variant in variants:
            self.library.output = json.dumps(variant).encode()
            with self.assertRaises(rust.RustDecoderError):
                decoder.decode(self.raw, mode="full")
        self.library.output = json.dumps(full).encode()
        with self.assertRaises(rust.RustDecoderError):
            decoder.decode(self.raw, mode="summary")

    def test_coordinator_validation_normalizes_canonical_ids_without_raw_digest_claim(self):
        wire = json.loads(json.dumps(decode_snapshot(self.raw, mode="ownership")))
        wire["raw_sha256"] = "1" * 64
        self.assertEqual(validate_state(wire, 31, "ownership", wire=True)["raw_sha256"], "1"*64)
        self.assertTrue(all(type(k) is int for k in wire["resources"]))


if __name__ == "__main__":
    unittest.main()
