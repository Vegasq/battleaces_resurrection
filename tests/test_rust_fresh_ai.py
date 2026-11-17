"""Authored fresh-AI verifier controls; never launch or load original code."""
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

from server.native_simulation import decode_snapshot
from server.protobuf_wire import field_bytes, field_uint
from tests.synthetic import snapshot
from tests.test_large_army_benchmark import configured
from tools import verify_rust_fresh_ai as f


class AuthoredWorker:
    def __init__(self, source, identity, *, wrong_bot=False, wrong_state=False, hang=False, dirty_exit=False):
        self.source, self.frame, self.pid, self.native_pid = source, -1, 123, 123
        self.closed, self.failure, self._test_backend = False, None, False
        self.wrong_bot, self.wrong_state, self.hang, self.dirty_exit = wrong_bot, wrong_state, hang, dirty_exit
        self.game_data_sha256 = source['reference']['bootstrap_sha256']
        self.dll_sha256 = source['reference']['simulation_sha256']
        self.ai_info, self.decoder_info = source['ai'], identity
        self.runtime_info = dict(os_name='nt', platform='win32', pointer_bits=64, implementation='cpython',
                                 python_version='authored Python', executable='authored.exe')
        self.process = SimpleNamespace(poll=lambda: (1 if self.dirty_exit else 0) if self.closed else None)
        self._stderr_thread = SimpleNamespace(is_alive=lambda: not self.closed)
        self._io = SimpleNamespace(_threads=[self._stderr_thread])
        self.backend_statistics = None
        self.events, self.steps = [], []

    async def bot_inputs(self, frame):
        self.events.append(('bot', frame))
        if self.hang:
            await asyncio.Event().wait()
        value = dict(self.source['bots'][frame])
        if self.wrong_bot and frame == 1:
            value[1] = f.encode_player_input(self.source['roster'].identities[1], [field_bytes(5, b'changed')])
        return value

    async def process_frame(self, payload, *, dt_ms):
        self.frame += 1
        self.events.append(('step', self.frame))
        self.steps.append((payload, dt_ms))
        state = decode_snapshot(snapshot(self.frame), include_entities=True)
        if self.wrong_state and self.frame == 1:
            state['resources'][0]['primary'] += 1
        return SimpleNamespace(frame=self.frame, state=state)

    async def close(self):
        self.closed = True


class FreshAITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(f, 'ROOT', self.root))
        self.stack.enter_context(mock.patch.object(f.sys, 'platform', 'win32'))
        self.stack.enter_context(mock.patch.object(f.c, 'verify_assets'))
        self.sources = {'authored/source.py': 'stable'}
        self.source_mock = self.stack.enter_context(mock.patch.object(f, 'source_hashes', return_value=self.sources))
        self.backend_mock = self.stack.enter_context(mock.patch.object(f.b, 'select_backend', return_value=None))
        self.stack.enter_context(mock.patch.object(f.b, 'backend_identity', return_value={'kind': 'authored'}))
        self.assets, self.journal, self.corpus = (self.root / 'local' / name for name in ('assets', 'journal', 'corpus'))
        for path in (self.assets, self.journal, self.corpus):
            path.mkdir(parents=True)
        for name, raw in (('asset-manifest.json', b'{}'), ('Simulation.dll', b'authored simulation'),
                          ('aiprogram.dll', b'authored AI'), ('ai-rules.json', b'{}')):
            (self.assets / name).write_bytes(raw)
        _, match, spec = configured(opponent='ai')
        self.roster = f.BotRoster(match.raw_game_data, {1: 58})
        self.bot_frames, self.payloads, rows = [], [], []
        for frame in range(6):
            decisions = {1: [field_bytes(5, field_uint(1, frame))]} if frame in (1, 4) else {}
            bots = self.roster.make_inputs(frame, decisions)
            self.bot_frames.append(bots)
            bodies = {0: f.encode_player_input(self.roster.identities[0]), **bots}
            payload = f.encode_frame(frame, bodies)
            self.payloads.append(payload)
            rows.append(dict(frame=frame, phase=f.c.PHASES[frame // 2], input_sha256=f.b.digest(payload),
                state_sha256=f.b.state_digest(decode_snapshot(snapshot(frame), include_entities=True))))
        inputs = b''.join(struct.pack('<I', len(payload)) + payload for payload in self.payloads)
        ai = dict(bots={'1': 58}, dll_sha256=f.b.digest((self.assets / 'aiprogram.dll').read_bytes()),
                  manifest_sha256=f.b.digest((self.assets / 'ai-rules.json').read_bytes()))
        report = dict(passed=True, native_qualified=True, source_unchanged=True, source_at_start=self.sources,
            source_at_finish=self.sources, frames=len(rows), ai=ai, workload=spec,
            asset_manifest_sha256=f.b.digest((self.assets / 'asset-manifest.json').read_bytes()),
            simulation_sha256=f.b.digest((self.assets / 'Simulation.dll').read_bytes()),
            bootstrap_sha256=f.b.digest(match.raw_game_data), input_journal_sha256=f.b.digest(inputs))
        (self.journal / 'benchmark.json').write_text(json.dumps(report), encoding='utf-8')
        (self.journal / 'bootstrap.pb.gz').write_bytes(gzip.compress(match.raw_game_data))
        (self.journal / 'frames.bin').write_bytes(inputs)
        (self.journal / 'frames.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        loaded = f.c.load_reference(SimpleNamespace(assets=self.assets, journal=self.journal))
        manifest = dict(schema=1, passed=True, native_qualified=True, source_unchanged=True, reference_unchanged=True,
            source_at_start=self.sources, source_at_finish=self.sources, reference=loaded[-1], verified_frames=len(rows),
            cleanup=dict(exit_code=0, failure=None, stderr_thread_closed=True, io_threads_closed=True))
        (self.corpus / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        library = self.root / 'local' / 'decoder.dll'
        library.write_bytes(b'MZ authored identity, never loaded')
        self.args = SimpleNamespace(corpus=self.corpus, assets=None, journal=None, library=library,
            library_sha256=f.b.digest(library.read_bytes()), output=self.root / 'local' / 'output', timeout_seconds=10,
            wine_executable=None, windows_python=None, wine_prefix_template=None, wine_cgroup_parent=None)
        self.source = f.load_inputs(self.args, {})
        self.workers, self.worker_options, self.failure_options = [], [], {}
        self.worker_hook, self.after_close = None, None
        self.create_mock = self.stack.enter_context(mock.patch.object(f.SimulationWorker, 'create', side_effect=self.create_worker))

    async def create_worker(self, data, dll, **options):
        kind = 'rust' if options.get('snapshot_decoder_library') else 'python'
        worker = AuthoredWorker(self.source, f.decoder_identity(self.args, kind, options['backend']), **self.failure_options)
        if self.worker_hook:
            self.worker_hook(worker, kind)
        if self.after_close:
            original = worker.close

            async def close():
                await original()
                self.after_close(worker, kind)

            worker.close = close
        self.workers.append(worker)
        self.worker_options.append(options)
        self.assertEqual(data, self.source['data'])
        self.assertEqual(options['ai'].bots, {1: 58})
        return worker

    def run_proof(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = asyncio.run(f.run(self.args))
        return code, json.loads((self.args.output / 'verification.json').read_text(encoding='utf-8'))

    def test_fresh_decisions_precede_every_exact_recorded_step_in_both_arms(self):
        code, report = self.run_proof()
        self.assertEqual(code, 0)
        self.assertTrue(report['passed'] and report['source_unchanged'] and report['inputs_unchanged'])
        self.assertEqual(len(self.workers), 2)
        for worker, arm in zip(self.workers, report['arms']):
            self.assertTrue(worker.closed)
            self.assertEqual(worker.events, [(kind, frame) for frame in range(6) for kind in ('bot', 'step')])
            self.assertEqual(worker.steps, [(payload, 50) for payload in self.payloads])
            self.assertEqual(arm['prepared_frames'], 6)
            self.assertEqual(arm['verified_frames'], 6)
            self.assertEqual(arm['expected_bot_journal_sha256'], arm['actual_bot_journal_sha256'])
        self.assertFalse(report['performance_acceptance_evaluated'])

    def test_omitted_empty_bot_body_is_reconstructed_without_inventing_actions(self):
        self.assertFalse(f.get_repeated_bytes(self.bot_frames[2][1], 2))
        self.assertEqual(f.recorded_bodies(self.payloads[2], self.roster, 2), self.bot_frames[2])
        changed = self.payloads[2] + field_bytes(6, self.bot_frames[2][1])
        with self.assertRaisesRegex(ValueError, 'not canonical'):
            f.recorded_bodies(changed, self.roster, 2)

    def test_different_fresh_decisions_stop_before_stepping_that_frame(self):
        self.failure_options['wrong_bot'] = True
        code, report = self.run_proof()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.workers), 1)
        self.assertEqual(len(self.workers[0].steps), 1)
        self.assertTrue(self.workers[0].closed)
        self.assertIn('fresh AI decisions differ', report['arms'][0]['error'])
        self.assertNotEqual(report['arms'][0]['current_expected_bot_sha256'], report['arms'][0]['current_actual_bot_sha256'])

    def test_observable_state_mismatch_and_cleanup_failure_cannot_qualify(self):
        for index, failure in enumerate(('wrong_state', 'dirty_exit')):
            with self.subTest(failure=failure):
                self.args.output = self.root / 'local' / f'failure-{index}'
                self.failure_options = {failure: True}
                code, report = self.run_proof()
                self.assertEqual(code, 1)
                self.assertFalse(report['arms'][0]['native_qualified'])
                self.assertTrue(self.workers[-1].closed)

    def test_wrong_ai_and_decoder_identity_are_refused_before_bot_rpc(self):
        for index, field in enumerate(('ai_info', 'decoder_info')):
            with self.subTest(field=field):
                self.args.output = self.root / 'local' / f'identity-{index}'
                self.worker_hook = lambda worker, kind: setattr(worker, field, {})
                code, report = self.run_proof()
                self.assertEqual(code, 1)
                self.assertFalse(self.workers[-1].events)
                self.assertTrue(self.workers[-1].closed)

    def test_timeout_closes_worker_and_preserves_report(self):
        self.failure_options['hang'] = True
        original = asyncio.timeout
        with mock.patch.object(f.asyncio, 'timeout', side_effect=lambda _: original(.01)):
            code, report = self.run_proof()
        self.assertEqual(code, 1)
        self.assertTrue(self.workers[0].closed)
        self.assertIn('TimeoutError', report['arms'][0]['error'])

    def test_journal_drift_after_last_arm_is_detected(self):
        def change(worker, kind):
            if kind == 'rust':
                path = self.journal / 'frames.jsonl'
                path.write_bytes(path.read_bytes() + b'\n')

        self.after_close = change
        code, report = self.run_proof()
        self.assertEqual(code, 1)
        self.assertFalse(report['inputs_unchanged'])

    def test_source_disappearance_preserves_failed_final_report(self):
        self.source_mock.side_effect = [self.sources, FileNotFoundError('source disappeared')]
        code, report = self.run_proof()
        self.assertEqual(code, 1)
        self.assertFalse(report['source_unchanged'])
        self.assertTrue(report['stability_errors'])

    def test_bad_expected_library_hash_refuses_before_create(self):
        self.args.library_sha256 = '0' * 64
        code, report = self.run_proof()
        self.assertEqual(code, 1)
        self.create_mock.assert_not_called()

    def test_explicit_relocation_keeps_original_journal_binding(self):
        manifest_path = self.corpus / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['reference'].update(assets='unavailable-original-assets', journal='unavailable-original-journal')
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        self.args.assets, self.args.journal = self.assets, self.journal
        code, report = self.run_proof()
        self.assertEqual(code, 0)
        self.assertEqual(report['captured_paths']['assets'], 'unavailable-original-assets')
        self.assertEqual(report['reference']['assets'], str(self.assets))

    def test_wine_backend_uses_translated_decoder_identity_and_owned_cleanup_gate(self):
        backend = SimpleNamespace(translate_path=lambda path: 'Z:\\authored\\decoder.dll')
        self.backend_mock.return_value = backend
        self.args.wine_executable, self.args.windows_python, self.args.wine_prefix_template = (
            self.root / name for name in ('wine', 'python.exe', 'prefix'))

        def owned_stats(worker, kind):
            worker.backend_statistics = dict(cleanup_complete=True, prefix_removed=True, cgroup_removed=True,
                                             exit_code=0, native_exit_code=0)

        self.worker_hook = owned_stats
        with mock.patch.object(f.sys, 'platform', 'linux'):
            code, report = self.run_proof()
        self.assertEqual(code, 0)
        self.assertEqual(report['arms'][1]['snapshot_decoder']['library_path'], 'Z:\\authored\\decoder.dll')
        self.assertTrue(all(options['backend'] is backend for options in self.worker_options))

    def test_partial_wine_options_and_existing_outputs_are_rejected(self):
        self.args.wine_executable = self.root / 'wine'
        with self.assertRaisesRegex(ValueError, 'supplied together'):
            f.validate_args(self.args)
        self.args.wine_executable = None
        self.args.output = self.corpus
        with self.assertRaisesRegex(ValueError, 'fresh private output'):
            f.validate_args(self.args)


if __name__ == '__main__':
    unittest.main()
