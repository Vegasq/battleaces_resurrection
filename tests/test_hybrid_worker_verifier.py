"""Authored verifier controls only; these never qualify native Wine or DLLs."""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from server.game_data import canonical_gzip
from tools import verify_hybrid_workers as verifier


class HybridVerifierControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ba-hybrid-verifier-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.recording = self.root/'recording'; self.recording.mkdir()
        self.manifest = 'a'*64
        self.raw = b'authored parser fixture, not native GameData'
        self.rows, journal = [], bytearray()
        for frame in range(40):
            payload = f'authored frame {frame}'.encode()
            journal.extend(struct.pack('<I', len(payload))+payload)
            self.rows.append(dict(frame=frame, input_sha256=hashlib.sha256(payload).hexdigest(), state_sha256='b'*64))
        (self.recording/'bootstrap.pb.gz').write_bytes(canonical_gzip(self.raw))
        (self.recording/'frames.bin').write_bytes(journal)
        self.report = dict(passed=True, native_qualified=True, frames=40,
            scope='AUTHORED PARSER FIXTURE ONLY; no native execution', asset_manifest_sha256=self.manifest,
            simulation_sha256=verifier.SUPPORTED_DLL_SHA256, bootstrap_sha256=hashlib.sha256(self.raw).hexdigest(),
            input_journal_sha256=hashlib.sha256(journal).hexdigest(), source_at_start={'authored': 'c'*64})
        self.write_rows(); self.write_report()

    def write_report(self):
        (self.recording/'benchmark.json').write_text(json.dumps(self.report), encoding='utf-8')

    def write_rows(self):
        (self.recording/'frames.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in self.rows), encoding='utf-8')

    def load(self):
        return verifier.load_recording(self.recording, self.manifest)

    def test_complete_recording_binds_all_inputs_without_claiming_native_execution(self):
        data, frames, rows, record = self.load()
        self.assertEqual(data, self.raw)
        self.assertEqual((len(frames), len(rows), record['frames']), (40, 40, 40))
        self.assertEqual(frames[20], b'authored frame 20')
        self.assertEqual(set(record['files_sha256']), set(verifier.RECORD_FILES))
        self.assertNotIn('native_qualified', record)
        self.assertIn('not regenerated', record['scope'])

    def test_unqualified_short_or_different_runtime_recordings_are_rejected(self):
        original = copy.deepcopy(self.report)
        for key, value, message in (('passed', False, 'completed native'), ('native_qualified', False, 'completed native'),
                ('passed', 1, 'completed native'), ('frames', 39, 'at least40'), ('frames', True, 'at least40'),
                ('asset_manifest_sha256', 'c'*64, 'manifest differs'), ('simulation_sha256', 'd'*64, 'simulation identity')):
            with self.subTest(field=key, value=value):
                self.report = original | {key: value}; self.write_report()
                with self.assertRaisesRegex(ValueError, message):
                    self.load()

    def test_bootstrap_and_input_journal_corruption_are_rejected(self):
        self.report['bootstrap_sha256'] = '0'*64; self.write_report()
        with self.assertRaisesRegex(ValueError, 'bootstrap digest'):
            self.load()
        self.report['bootstrap_sha256'] = hashlib.sha256(self.raw).hexdigest(); self.write_report()
        with (self.recording/'frames.bin').open('ab') as stream:
            stream.write(b'tampered')
        with self.assertRaisesRegex(ValueError, 'journal digest'):
            self.load()

    def test_frame_reordering_bad_input_hash_and_bad_state_hash_are_rejected(self):
        original = copy.deepcopy(self.rows)
        for key, value, message in (('frame', 9, 'not sequential'), ('input_sha256', '0'*64, 'input digest'),
                                    ('state_sha256', 'invalid', 'hashes are invalid')):
            with self.subTest(field=key):
                self.rows = copy.deepcopy(original); self.rows[10][key] = value; self.write_rows()
                with self.assertRaisesRegex(ValueError, message):
                    self.load()

    def test_extra_or_truncated_rows_are_not_silently_ignored(self):
        self.rows.append(self.rows[-1]); self.write_rows()
        with self.assertRaisesRegex(ValueError, 'trailing frames'):
            self.load()
        self.rows = self.rows[:39]; self.write_rows()
        with self.assertRaisesRegex(ValueError, 'missing/oversized'):
            self.load()

    def test_recorded_state_mismatch_is_rejected(self):
        payload = b'authored input'
        state = dict(frame=3, resources={'0': {'primary': 10}}, raw_sha256='nonsemantic')
        expected = dict(frame=3, input_sha256=hashlib.sha256(payload).hexdigest(), state_sha256=verifier.state_digest(state))
        verifier.check_record(3, payload, state | {'raw_sha256': 'different allocation'}, expected)
        with self.assertRaisesRegex(ValueError, 'observable native state differs'):
            verifier.check_record(3, payload, state | {'resources': {'0': {'primary': 11}}}, expected)

    def test_scoped_member_admission_rejects_coordinator_guardians_and_invalid_lists(self):
        self.assertEqual(verifier.parse_members(b'101\n102\n'), [101, 102])
        verifier.validate_members([101, 102], coordinator_pid=1, guardian_pids=(2, 3))
        for values in ([1, 101], [2, 101], [3, 101]):
            with self.assertRaisesRegex(ValueError, 'refusing to freeze'):
                verifier.validate_members(values, coordinator_pid=1, guardian_pids=(2, 3))
        for raw in (b'', b'-1\n', b'0\n', b'10\n10\n', b'x\n', b'1\n'*257):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                verifier.parse_members(raw)

    def test_freeze_requires_explicit_kernel_confirmation(self):
        self.assertEqual(verifier.parse_events(b'populated 1\nfrozen 1\n')['frozen'], '1')
        for raw in (b'populated 1\n', b'populated 1\nfrozen true\n',
                    b'populated 1\nfrozen 0\nfrozen 1\n', b'populated 1 extra\nfrozen 1\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                verifier.parse_events(raw)

    def test_freeze_write_uses_only_retained_directory_descriptor_and_no_follow(self):
        scope = object.__new__(verifier.VictimScope); scope.fd = 55
        with mock.patch.object(verifier.os, 'O_NOFOLLOW', 0x20000, create=True), \
                mock.patch.object(verifier.os, 'open', return_value=71) as opening, \
                mock.patch.object(verifier.os, 'write', return_value=1) as writing, \
                mock.patch.object(verifier.os, 'close') as closing:
            scope.write_freeze(True)
            opening.assert_called_once_with('cgroup.freeze', os.O_WRONLY | 0x20000, dir_fd=55)
            writing.assert_called_once_with(71, b'1')
            closing.assert_called_once_with(71)
        scope.fd = None
        with self.assertRaisesRegex(ValueError, 'handle is closed'):
            scope.write_freeze(True)

    def test_forced_victim_cleanup_cannot_qualify_as_natural_survivor_exit(self):
        record = dict(guardian_exit_code=125, failure='WorkerTimeout',
            backend_statistics=dict(cleanup_complete=True, cgroup_removed=True, prefix_removed=True, native_exit_code=-9),
            stderr_thread_closed=True, io_threads_closed=True, owner_thread_closed=True,
            private_cgroup_absent=True, private_scratch_absent=True)
        verifier.require_cleanup(record, natural=False)
        with self.assertRaisesRegex(ValueError, 'exit naturally'):
            verifier.require_cleanup(record, natural=True)
        changed = copy.deepcopy(record); changed['io_threads_closed'] = False
        with self.assertRaisesRegex(ValueError, 'survived cleanup'):
            verifier.require_cleanup(changed, natural=False)
        changed = copy.deepcopy(record); changed['backend_statistics']['cleanup_complete'] = False
        with self.assertRaisesRegex(ValueError, 'complete owned cleanup'):
            verifier.require_cleanup(changed, natural=False)

    def test_output_must_be_new_ignored_and_separate_from_recording_assets_template(self):
        assets, template = self.root/'assets', self.root/'template'
        assets.mkdir(); template.mkdir(); (self.root/'local').mkdir()
        args = SimpleNamespace(assets=assets, replay=self.recording, output=self.root/'local/new',
            wine=self.root/'wine', windows_python=self.root/'python.exe', prefix_template=template, cgroup_parent=None)
        with mock.patch.object(verifier, 'ROOT', self.root):
            verifier.validate_paths(args)
            for output in (self.root/'outside', self.root/'local', self.recording/'child'):
                args.output = output
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'new ignored'):
                    verifier.validate_paths(args)
            args.output = self.root/'local/new'
            args.assets = self.root/'local';
            with self.assertRaisesRegex(ValueError, 'separate'):
                verifier.validate_paths(args)

    def test_template_symlink_is_rejected_before_resolution_hides_it(self):
        args = SimpleNamespace(assets=self.root/'assets', replay=self.recording, output=self.root/'local/new',
            wine=self.root/'wine', windows_python=self.root/'python.exe',
            prefix_template=self.root/'linked-template', cgroup_parent=None)
        lexical_template = args.prefix_template
        with mock.patch.object(Path, 'is_symlink', autospec=True,
                               side_effect=lambda path: path == lexical_template):
            with self.assertRaisesRegex(ValueError, 'prefix template may not be a symlink'):
                verifier.validate_paths(args)
        self.assertEqual(args.prefix_template, lexical_template)


if __name__ == '__main__':
    unittest.main()
