"""Authored exporter controls; no original snapshots, assets or DLL launch."""
import asyncio
import contextlib
import gzip
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tests.synthetic import snapshot
from tools import capture_snapshot_corpus as c


class FakeWorker:
    def __init__(self, data, dll, *, wrong_state=False, wrong_snapshot=False, hang=False, dirty_exit=False):
        self.pid, self.frame, self.failure = 123, -1, None
        self.game_data_sha256, self.dll_sha256 = c.digest(data), c.digest(dll)
        self._test_backend = False
        self.wrong_state, self.wrong_snapshot, self.hang = wrong_state, wrong_snapshot, hang
        self.closed, self.dirty_exit, self.inputs = False, dirty_exit, []
        self.process = SimpleNamespace(poll=lambda: (1 if dirty_exit else 0) if self.closed else None)
        self._stderr_thread = SimpleNamespace(is_alive=lambda: not self.closed)
        self._io = SimpleNamespace(_threads=[self._stderr_thread])

    async def process_frame(self, payload, *, dt_ms):
        if self.hang:
            await asyncio.Event().wait()
        self.frame += 1
        self.inputs.append((payload, dt_ms))
        state = await self.state(viewer=31, include_entities=True)
        if self.wrong_state:
            state['resources'][0]['primary'] += 1
        return SimpleNamespace(frame=self.frame, state=state)

    async def state(self, viewer=31, *, include_entities=False):
        return c.decode_snapshot(snapshot(self.frame), viewer=viewer, include_entities=include_entities)

    async def snapshot(self, viewer=31):
        return snapshot(self.frame + int(self.wrong_snapshot))

    async def close(self):
        self.closed = True


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.assets, self.journal = self.root / 'assets', self.root / 'journal'
        self.assets.mkdir()
        self.journal.mkdir()
        self.data, self.dll, self.manifest = b'authored bootstrap', b'authored DLL identity', b'{}'
        (self.assets / 'Simulation.dll').write_bytes(self.dll)
        (self.assets / 'asset-manifest.json').write_bytes(self.manifest)
        self.payloads = [bytes([index + 1]) for index in range(9)]
        self.rows = [dict(frame=index, phase=c.PHASES[index // 3], input_sha256=c.digest(payload),
                          state_sha256=c.benchmark.state_digest(c.decode_snapshot(snapshot(index), include_entities=True)))
                     for index, payload in enumerate(self.payloads)]
        raw_inputs = b''.join(struct.pack('<I', len(payload)) + payload for payload in self.payloads)
        self.reference = dict(passed=True, native_qualified=True, source_unchanged=True,
                              source_at_start={'authored': 'source'}, source_at_finish={'authored': 'source'},
                              frames=len(self.rows), asset_manifest_sha256=c.digest(self.manifest),
                              simulation_sha256=c.digest(self.dll), bootstrap_sha256=c.digest(self.data),
                              input_journal_sha256=c.digest(raw_inputs), workload={'opponent': 'ai'})
        (self.journal / 'benchmark.json').write_text(json.dumps(self.reference), encoding='utf-8')
        (self.journal / 'bootstrap.pb.gz').write_bytes(gzip.compress(self.data))
        (self.journal / 'frames.bin').write_bytes(raw_inputs)
        self.write_rows()
        self.args = SimpleNamespace(assets=self.assets, journal=self.journal,
                                    output=self.root / 'local' / 'capture', timeout_seconds=10)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch.object(c, 'ROOT', self.root))
        self.patches.enter_context(mock.patch.object(c.sys, 'platform', 'win32'))
        self.assets_mock = self.patches.enter_context(mock.patch.object(c, 'verify_assets'))
        self.source_mock = self.patches.enter_context(mock.patch.object(c, 'source_hashes', return_value={'fixture': 'stable'}))

    def write_rows(self):
        (self.journal / 'frames.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in self.rows), encoding='utf-8')

    def run_capture(self, worker=None):
        worker = worker or FakeWorker(self.data, self.dll)
        with mock.patch.object(c.SimulationWorker, 'create', new_callable=mock.AsyncMock, return_value=worker) as create:
            with contextlib.redirect_stdout(io.StringIO()):
                result = asyncio.run(c.run(self.args))
        report = json.loads((self.args.output / 'manifest.json').read_text(encoding='utf-8'))
        return result, report, worker, create

    def test_phase_samples_are_bounded_and_include_phase_ends(self):
        rows = [dict(frame=i, phase=c.PHASES[i // 20]) for i in range(60)]
        selected, viewers = c.select_frames(rows)
        self.assertEqual(selected, [0, 10, 19, 20, 30, 39, 40, 50, 59])
        self.assertEqual(viewers, {19, 39, 59})
        self.assertEqual(c.select_frames([dict(frame=i, phase=p) for i, p in enumerate(c.PHASES)]),
                         ([0, 1, 2], {0, 1, 2}))
        for key, value in (('frame', 1), ('frame', False), ('phase', 'unknown')):
            invalid = [dict(row) for row in rows]
            invalid[0][key] = value
            with self.assertRaises(ValueError):
                c.select_frames(invalid)
        rows[-1]['phase'] = 'setup'
        with self.assertRaisesRegex(ValueError, 'backwards'):
            c.select_frames(rows)

    def test_private_fresh_output_and_bounded_timeout_required(self):
        original = self.args.output
        for output in (self.root / 'elsewhere', self.root / 'local', self.assets, self.journal):
            self.args.output = output
            with self.assertRaises(ValueError):
                c.validate_args(self.args)
        self.args.output = original
        for timeout in (0, 9, 901, float('nan'), float('inf')):
            self.args.timeout_seconds = timeout
            with self.assertRaisesRegex(ValueError, 'timeout'):
                c.validate_args(self.args)
        self.args.timeout_seconds = 10
        c.validate_args(self.args)
        self.args.output.mkdir(parents=True)
        sentinel = self.args.output / 'preserve.txt'
        sentinel.write_text('original', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            c.validate_args(self.args)
        self.assertEqual(sentinel.read_text(), 'original')

    def test_success_binds_exact_bytes_full_and_summary_to_all_verified_frames(self):
        result, report, worker, create = self.run_capture()
        self.assertEqual(result, 0)
        self.assertTrue(report['passed'] and report['native_qualified'] and report['reference_unchanged'])
        self.assertEqual(report['verified_frames'], 9)
        self.assertEqual(len(report['snapshots']), 15)
        self.assertEqual(worker.inputs, [(payload, 50) for payload in self.payloads])
        self.assertTrue(worker.closed)
        self.assertNotIn('ai', create.call_args.kwargs)
        self.assertNotIn('_test_backend', create.call_args.kwargs)
        for item in report['snapshots']:
            raw = (self.args.output / item['snapshot_file']).read_bytes()
            self.assertEqual(c.digest(raw), item['snapshot_sha256'])
            self.assertEqual(len(raw), item['bytes'])
            for file_key, hash_key, entities in (('expected_file', 'expected_sha256', True),
                                                  ('expected_summary_file', 'expected_summary_sha256', False)):
                expected = (self.args.output / item[file_key]).read_bytes()
                self.assertEqual(c.digest(expected), item[hash_key])
                decoded = c.decode_snapshot(raw, viewer=item['viewer'], include_entities=entities)
                self.assertEqual(json.loads(expected), json.loads(json.dumps(decoded)))

    def test_corrupt_journal_is_preserved_and_refused_before_worker_creation(self):
        path = self.journal / 'frames.bin'
        path.write_bytes(path.read_bytes() + b'extra')
        result, report, worker, create = self.run_capture()
        self.assertEqual(result, 1)
        self.assertIn('input journal digest differs', report['error'])
        create.assert_not_called()
        self.assertEqual(report['verified_frames'], 0)
        self.assertTrue(path.read_bytes().endswith(b'extra'))

    def test_bootstrap_expansion_is_bounded_before_worker_creation(self):
        with mock.patch.object(c, 'MAX_BOOTSTRAP', len(self.data) - 1):
            result, report, worker, create = self.run_capture()
        self.assertEqual(result, 1)
        self.assertIn('reference bootstrap differs', report['error'])
        create.assert_not_called()

    def test_every_reference_state_is_checked_not_only_selected_frames(self):
        self.rows[1]['state_sha256'] = 'incorrect'
        self.write_rows()
        with mock.patch.object(c, 'select_frames', return_value=([0, 2, 8], {2, 5, 8})):
            result, report, worker, create = self.run_capture()
        self.assertEqual(result, 1)
        self.assertEqual(report['verified_frames'], 1)
        self.assertIn('observable native state differs', report['error'])
        self.assertTrue(worker.closed)
        self.assertTrue((self.args.output / report['snapshots'][0]['snapshot_file']).exists())

    def test_snapshot_disagreement_cannot_qualify(self):
        result, report, worker, create = self.run_capture(FakeWorker(self.data, self.dll, wrong_snapshot=True))
        self.assertEqual(result, 1)
        self.assertIn('snapshot frame differs', report['error'])
        self.assertTrue(worker.closed)
        self.assertEqual((self.args.output / 'f000000-v31.snapshot').read_bytes(), snapshot(1))

    def test_timeout_closes_owned_worker_and_retains_failed_manifest(self):
        timeout = asyncio.timeout
        with mock.patch.object(c.asyncio, 'timeout', side_effect=lambda _: timeout(.01)):
            result, report, worker, create = self.run_capture(FakeWorker(self.data, self.dll, hang=True))
        self.assertEqual(result, 1)
        self.assertIn('TimeoutError', report['error'])
        self.assertTrue(worker.closed)
        self.assertFalse(report['native_qualified'])

    def test_cleanup_failure_cannot_qualify_successful_replay(self):
        result, report, worker, create = self.run_capture(FakeWorker(self.data, self.dll, dirty_exit=True))
        self.assertEqual(result, 1)
        self.assertEqual(report['verified_frames'], 9)
        self.assertFalse(report['passed'] or report['native_qualified'])
        self.assertEqual(report['cleanup']['exit_code'], 1)

    def test_source_drift_cannot_qualify(self):
        self.source_mock.side_effect = [{'fixture': 'before'}, {'fixture': 'after'}]
        result, report, worker, create = self.run_capture()
        self.assertEqual(result, 1)
        self.assertFalse(report['source_unchanged'])
        self.assertIn('source changed', report['stability_error'])

    def test_journal_drift_cannot_qualify(self):
        worker = FakeWorker(self.data, self.dll)
        close = worker.close

        async def close_and_change_fixture():
            await close()
            path = self.journal / 'frames.jsonl'
            path.write_bytes(path.read_bytes() + b'\n')

        worker.close = close_and_change_fixture
        result, report, worker, create = self.run_capture(worker)
        self.assertEqual(result, 1)
        self.assertIn('journal changed', report['stability_error'])

    def test_worker_identity_is_bound_to_loaded_reference(self):
        worker = FakeWorker(self.data, self.dll)
        worker.dll_sha256 = 'other'
        result, report, worker, create = self.run_capture(worker)
        self.assertEqual(result, 1)
        self.assertIn('worker identity differs', report['error'])
        self.assertTrue(worker.closed)


if __name__ == '__main__':
    unittest.main()
