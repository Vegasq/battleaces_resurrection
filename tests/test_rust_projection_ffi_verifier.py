"""Authored FFI-verifier refusal controls; never load a library or original data."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from server.native_simulation import decode_snapshot, SnapshotFormatError
from server.rust_snapshot_decoder import RustDecoderError
from tools import verify_rust_ffi as t


class AuthoredDecoder:
    projection_version = 1

    def __init__(self, mutate=None, refusal_status=2):
        self.mutate, self.refusal_status, self.calls = mutate, refusal_status, []

    def decode(self, raw, viewer, *, mode):
        self.calls.append(mode)
        try:
            state = decode_snapshot(raw, viewer, mode=mode)
        except SnapshotFormatError as error:
            raise RustDecoderError(f'Rust snapshot decoder failed, status{self.refusal_status}') from error
        if self.mutate:
            self.mutate(state, mode)
        return state


class ProjectionFFIVerifierTests(unittest.TestCase):
    def test_complete_three_mode_parity_and_native_nonfinite_status_counts(self):
        decoder = AuthoredDecoder()
        report = t.verify_projection(decoder)
        self.assertEqual(report['valid_cases'], 31)
        self.assertEqual(report['mode_comparisons'], 93)
        self.assertEqual(report['nonfinite_refused'], 9)
        self.assertEqual(report['legacy_only_nonfinite_cases'], ['nonfinite_bits_without_entities'])
        self.assertTrue(report['same_raw_all_nine_common_fields'])
        self.assertEqual(len(decoder.calls), 102)

    def test_missing_wrong_and_boolean_projection_versions_refuse_before_decode(self):
        for version in (None, 0, 2, True):
            decoder = AuthoredDecoder()
            decoder.projection_version = version
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'projection version1 required'):
                t.verify_projection(decoder)
            self.assertFalse(decoder.calls)

    def test_every_common_field_is_independently_compared_on_identical_raw_input(self):
        for key in t.COMMON:
            def mutate(state, mode, key=key):
                if mode == 'summary':
                    state[key] = None
            with self.subTest(key=key), self.assertRaises(ValueError):
                t.verify_projection(AuthoredDecoder(mutate))

    def test_ownership_omission_and_full_component_changes_are_not_normalized(self):
        for target in ('ownership', 'full'):
            def mutate(state, mode):
                if mode == target:
                    if mode == 'ownership':
                        state['ownership'] = []
                    else:
                        state['entities'][0]['army'] = 99
            with self.subTest(target=target), self.assertRaises(ValueError):
                t.verify_projection(AuthoredDecoder(mutate))

    def test_json_or_adapter_refusal_cannot_replace_native_scan_status(self):
        for status in (1, 3, 4):
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'native SNAPSHOT status2'):
                t.verify_projection(AuthoredDecoder(refusal_status=status))

    def test_accepted_nonfinite_projection_is_not_a_refusal(self):
        decoder = AuthoredDecoder()
        original = decoder.decode
        def decode(raw, viewer, *, mode):
            try:
                return original(raw, viewer, mode=mode)
            except RustDecoderError:
                return {'accepted': True}
        decoder.decode = decode
        with self.assertRaisesRegex(ValueError, 'projection nonfinite refusal missing'):
            t.verify_projection(decoder)


class CLICompatibilityTests(unittest.TestCase):
    def exercise(self, require_projection=False, *, source_change=False, library_change=False):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            path = Path(temporary)/'authored-never-loaded.so'
            path.write_bytes(b'authored library identity')
            decoder = Mock()
            decoder.decode.return_value = {'authored': True}
            stack.enter_context(patch.object(t, 'RustSnapshotDecoder', return_value=decoder))
            stack.enter_context(patch.object(t, 'sources', side_effect=[{'s': 'a'*64}, {'s': ('b' if source_change else 'a')*64}]))
            stack.enter_context(patch.object(t.v.fixtures, 'valid_cases', return_value=[dict(raw=b'fixture', viewer=31, include_entities=True)]))
            stack.enter_context(patch.object(t.v.fixtures, 'invalid_cases', return_value=[]))
            stack.enter_context(patch.object(t.v.fixtures, 'json_refusal_cases', return_value=[]))
            stack.enter_context(patch.object(t.v.fixtures, 'make_snapshot', return_value=b'fixture'))
            stack.enter_context(patch.object(t.v, 'decode_snapshot', return_value={'authored': True}))
            projection = stack.enter_context(patch.object(t, 'verify_projection', return_value={'version': 1}))
            if library_change:
                def decode(*args, **kwargs):
                    path.write_bytes(b'changed library')
                    return {'authored': True}
                decoder.decode.side_effect = decode
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                t.main(['--library', str(path)] + (['--require-projection'] if require_projection else []))
            return json.loads(output.getvalue()), projection.call_count, decoder.decode.call_count

    def test_default_keeps_legacy_behavior_and_thousand_free_cycles(self):
        report, projection_calls, decode_calls = self.exercise()
        self.assertNotIn('projection', report)
        self.assertEqual(projection_calls, 0)
        self.assertEqual(report['ownership_cycles'], 1000)
        self.assertEqual(decode_calls, 1001)

    def test_explicit_flag_requires_projection_helper_and_preserves_legacy_cycles(self):
        report, projection_calls, decode_calls = self.exercise(True)
        self.assertEqual(report['projection'], {'version': 1})
        self.assertEqual(projection_calls, 1)
        self.assertEqual(decode_calls, 1001)

    def test_source_or_library_mutation_refuses_even_with_projection_enabled(self):
        for mutation in ('source_change', 'library_change'):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'source/library changed'):
                self.exercise(True, **{mutation: True})


if __name__ == '__main__':
    unittest.main()
