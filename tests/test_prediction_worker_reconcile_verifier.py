"""Authored coordinator checks only; no native worker/library is started."""
import contextlib
import copy
import importlib
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server.game_data import encode_frame


class PredictionWorkerReconcileVerifierTests(unittest.TestCase):
    def setUp(self):
        self.tool = importlib.import_module('tools.verify_prediction_worker_reconcile')

    def test_journal_is_exact_contiguous_and_bounded(self):
        frames = [encode_frame(number, {0: b'', 1: b''}) for number in range(3)]
        raw = b''.join(struct.pack('<I', len(item)) + item for item in frames)
        self.assertEqual(self.tool.read_journal(io.BytesIO(raw), count=3), frames)
        for bad in (raw[:-1], raw + b'x', struct.pack('<I', 0), struct.pack('<I', 2*1024*1024+1),
                    struct.pack('<I', len(frames[1])) + frames[1]):
            with self.subTest(length=len(bad)), self.assertRaises(AssertionError):
                self.tool.read_journal(io.BytesIO(bad), count=3)

    def test_make_pair_requires_success_and_exact_bytes_before_decoding(self):
        raw = b'12345678'
        valid = struct.pack('<IiI', len(raw), 0, len(raw)) + raw
        self.assertEqual(self.tool.decode_pair(0, valid), raw)
        for code, bad in ((1, valid), (0, valid + b'x'), (0, valid[:-1]),
                          (0, struct.pack('<IiI', 8, 7, 0)),
                          (0, struct.pack('<IiI', 16*1024*1024+1, 0, 0))):
            with self.subTest(code=code, size=len(bad)), self.assertRaises(AssertionError):
                self.tool.decode_pair(code, bad)

    def test_metrics_reject_truncation_and_unknown_flags(self):
        raw = struct.pack('<iiiI8Q', 5, 7, 5, 0, 3, 1, 2, 1, 8, 6, 8, 100)
        value = self.tool.decode_metrics(raw)
        self.assertEqual((value['confirmed_frame'], value['predicted_frame'], value['replayed_frames']), (5, 7, 8))
        self.assertTrue(self.tool.decode_metrics(struct.pack('<iiiI8Q', 5, 7, 5, 8, *range(8)))['terminal_admitted'])
        for bad in (raw[:-1], raw + b'x', struct.pack('<iiiI8Q', 5, 7, 5, 16, *range(8))):
            with self.assertRaises(AssertionError):
                self.tool.decode_metrics(bad)

    def test_observation_checks_all_state_entity_modes_and_charge_vectors(self):
        expected = dict(frame=7, state={'frame': 7, 'resources': [[1]], 'entities': [{'id': 1, 'type': 75, 'army': 0}]},
                        entity_states={'1': 4}, ability_charges={'0': [], '1': []})
        actual = {name: copy.deepcopy(expected[name]) for name in ('state', 'entity_states', 'ability_charges')}
        self.tool.compare_observation(actual, expected, 7)
        for field in ('state', 'entity_states', 'ability_charges'):
            bad = copy.deepcopy(actual)
            bad[field] = {'changed': True}
            with self.subTest(field=field), self.assertRaises(AssertionError):
                self.tool.compare_observation(bad, expected, 7)
        with self.assertRaises(AssertionError):
            self.tool.compare_observation(actual, expected, 8)

    def test_enqueue_audit_detects_native_calls_restores_captures_and_drops(self):
        raw = encode_frame(0, {0: b'', 1: b''})
        for changed in (None, 'native_calls', 'captures', 'restores', 'drops'):
            state = dict(native_calls=5, captures=3, restores=0, drops=1)
            calls = []
            def dispatch(opcode, body):
                calls.append((opcode, body))
                if changed:
                    state[changed] += 1
                return 0, b''
            if changed is None:
                result = self.tool.audit_enqueue(dispatch, lambda: dict(state), 9, [raw])
                self.assertEqual(result['frames'], [0])
                self.assertEqual(calls, [(65, struct.pack('<Q', 9) + raw)])
            else:
                with self.subTest(changed=changed), self.assertRaises(AssertionError):
                    self.tool.audit_enqueue(dispatch, lambda: dict(state), 9, [raw])

    def test_import_closure_includes_relative_and_function_local_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'pkg').mkdir()
            (root/'pkg/__init__.py').write_text('')
            (root/'pkg/main.py').write_text('from . import child\ndef f():\n from pkg.more import value\n')
            (root/'pkg/child.py').write_text('import json\n')
            (root/'pkg/more.py').write_text('value=1\n')
            files = self.tool.source_closure(root, ['pkg/main.py'])
            self.assertEqual(set(files), {'pkg/__init__.py', 'pkg/main.py', 'pkg/child.py', 'pkg/more.py'})

    def test_source_snapshot_preserves_bytes_and_detects_later_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'pkg').mkdir()
            (root/'pkg/a.py').write_bytes(b'value=1\n')
            snapshot = root/'snapshot'
            manifest = self.tool.snapshot_files(root, snapshot, ['pkg/a.py'])
            self.tool.verify_files(snapshot, manifest)
            self.assertEqual((snapshot/'pkg/a.py').read_bytes(), b'value=1\n')
            (snapshot/'pkg/a.py').write_bytes(b'value=2\n')
            with self.assertRaises(AssertionError):
                self.tool.verify_files(snapshot, manifest)

    def test_prepare_only_never_reaches_native_run_or_popen(self):
        invocation = {'command': ['authored-not-executed'], 'output': 'authored'}
        with patch.object(self.tool, 'prepare', return_value=invocation) as prepare, \
             patch.object(self.tool, 'run_prepared', side_effect=AssertionError('native launched')), \
             patch.object(self.tool.subprocess, 'Popen', side_effect=AssertionError('process started')), \
             patch('sys.argv', ['verifier', '--prepare-only', '--output', 'authored', '--original-dll', 'a',
                                '--heap-helper', 'b', '--cooperative', 'c', '--baseline', 'd']), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.tool.main(), 0)
        self.assertEqual(prepare.call_count, 1)
        self.assertFalse(json.loads(output.getvalue())['native_executed'])

    def test_coordinator_starts_with_view_warmup_then_prime_not_process_or_step(self):
        from client_patch.prediction_worker.wire import Op
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            state = dict(captures=0, flags=0)
            def dispatch(command):
                calls.append((command.opcode, command.args))
                if command.opcode == Op.CREATE_WORLD:
                    return 0, struct.pack('<Q', 3)
                if command.opcode == Op.MAKE_FRAME:
                    return 0, struct.pack('<IiI', 8, 0, 8) + b'12345678'
                if command.opcode == Op.PREDICTION_BEGIN:
                    state['captures'] = 1
                    return 0, b''
                if command.opcode == Op.PREDICTION_METRICS:
                    return 0, struct.pack('<iiiI8Q', -1, -1, -1, state['flags'], state['captures'], *([0]*7))
                raise AssertionError('unexpected startup opcode')
            session = SimpleNamespace(api=SimpleNamespace(call=lambda *args: 0),
                                      dispatch=dispatch, drain_logs=lambda: [])
            coordinator = self.tool.Coordinator(session, Path(directory), [])
            try:
                self.assertEqual(coordinator.create(b'authored-bootstrap'), 3)
                self.assertEqual([op for op, _ in calls], [5, 9, 9, 9, 64, 66])
                self.assertEqual([args[1] for op, args in calls if op == 9], [31, 0, 1])
                for flag in (2, 4, 8):
                    state['flags'] = flag
                    with self.subTest(flag=flag), self.assertRaises(AssertionError):
                        coordinator.metrics(3)
            finally:
                coordinator.close_observers()

    def test_retirement_refuses_saved_pages_tokens_or_incomplete_cleanup(self):
        for bad in (None, 'pages', 'tokens', 'cleanup'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                result = dict(closed=False, cleanup_complete=False)
                adapter = SimpleNamespace(tokens={1: 'binding'})
                prediction = SimpleNamespace(metrics=result)
                worlds, predictions = {3: 33}, {3: prediction}
                def dispatch(command):
                    if command.opcode == 66:
                        return 0, struct.pack('<iiiI8Q', 7, 7, 7, 0, *([0]*8))
                    if command.opcode == 6:
                        result.update(closed=True, cleanup_complete=bad != 'cleanup')
                        if bad != 'tokens':
                            adapter.tokens.clear()
                        worlds.clear(); predictions.clear()
                        return 0, b''
                    raise AssertionError('unexpected retirement opcode')
                session = SimpleNamespace(api=SimpleNamespace(call=lambda *args: 0), dispatch=dispatch,
                    drain_logs=lambda: [], predictions=predictions, worlds=worlds,
                    prediction_adapters={3: adapter}, arena=SimpleNamespace(healthy=lambda: dict(saved_bytes=int(bad == 'pages'))),
                    retired_cooperative=SimpleNamespace(stats=lambda: dict(error=0)))
                coordinator = self.tool.Coordinator(session, Path(directory), [])
                try:
                    if bad:
                        with self.assertRaises(AssertionError):
                            coordinator.retire(3)
                    else:
                        self.assertTrue(coordinator.retire(3)['metrics_after']['cleanup_complete'])
                finally:
                    coordinator.close_observers()

    def test_parent_acceptance_allows_extra_unattributed_inactive_job_process(self):
        report = dict(errors=[], forced_cleanup=False, reaped=True, retained_handle_closed=True,
                      exit_code=0, assigned_before_resume=True, pinned_inputs_unchanged=True,
                      child=dict(passed=True), job_before_close=dict(total=2, active=0, terminated=0))
        self.assertTrue(self.tool.parent_accepts(report))
        attribution = self.tool.job_attribution(report['job_before_close'])
        self.assertEqual(attribution['unattributed_extra_processes'], 1)
        self.assertEqual(attribution['attribution'], 'unattributed')
        report['job_before_close']['total'] = 1
        self.assertTrue(self.tool.parent_accepts(report))
        self.assertEqual(self.tool.job_attribution(report['job_before_close'])['unattributed_extra_processes'], 0)

    def test_parent_acceptance_rejects_live_terminated_empty_or_invalid_job_counts(self):
        base = dict(errors=[], forced_cleanup=False, reaped=True, retained_handle_closed=True,
                    exit_code=0, assigned_before_resume=True, pinned_inputs_unchanged=True, child=dict(passed=True))
        for job in (dict(total=2, active=1, terminated=0), dict(total=2, active=0, terminated=1),
                    dict(total=0, active=0, terminated=0), dict(total=True, active=0, terminated=0),
                    dict(total=2, active=False, terminated=0), dict(total=2, active=0), None):
            with self.subTest(job=job):
                self.assertFalse(self.tool.parent_accepts(dict(base, job_before_close=job)))

    def test_parent_acceptance_keeps_all_other_failure_gates(self):
        base = dict(errors=[], forced_cleanup=False, reaped=True, retained_handle_closed=True,
                    exit_code=0, assigned_before_resume=True, pinned_inputs_unchanged=True,
                    child=dict(passed=True), job_before_close=dict(total=2, active=0, terminated=0))
        for key, value in (('errors', ['failure']), ('forced_cleanup', True), ('reaped', False),
                           ('retained_handle_closed', False), ('exit_code', 7), ('assigned_before_resume', False),
                           ('pinned_inputs_unchanged', False), ('child', dict(passed=False))):
            with self.subTest(key=key):
                self.assertFalse(self.tool.parent_accepts(dict(base, **{key: value})))

    def test_reanalysis_cli_never_selects_prepare_or_native_runner(self):
        with patch.object(self.tool, 'reanalyze', return_value=dict(passed=True)) as reanalyze, \
             patch.object(self.tool, 'prepare', side_effect=AssertionError('prepared new run')), \
             patch.object(self.tool, 'run_prepared', side_effect=AssertionError('native launched')), \
             patch.object(self.tool.subprocess, 'Popen', side_effect=AssertionError('process started')), \
             patch('sys.argv', ['verifier', '--reanalyze', '--output', 'authored']), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.tool.main(), 0)
        reanalyze.assert_called_once_with(Path('authored'))
        self.assertFalse(json.loads(output.getvalue())['native_executed'])


if __name__ == '__main__':
    unittest.main()
