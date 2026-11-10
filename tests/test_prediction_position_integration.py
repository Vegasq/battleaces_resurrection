"""Authored CLI/worker boundary checks; no original DLL or game is loaded."""
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from client_patch.prediction_worker import __main__ as main
from client_patch.prediction_worker.observation import CanonicalStateObserver, PositionTraceSpec
from server.native_simulation import decode_snapshot
from tests import test_prediction_state_observation as fixtures


class PositionCliTests(TestCase):
    args = ['--original-dll', 'original', '--heap-helper', 'heap', '--cooperative', 'coop', '--data-dir', '.']

    def test_explicit_option_forwards_an_immutable_identity_and_window(self):
        events = []
        class Session:
            def enable_movement_observation(self, path, *, position_trace):
                events.append((path, position_trace))
        with patch.object(main.NativeSession, 'open', return_value=Session()) as opened, \
                patch.object(main, 'run_streams', return_value=0) as streams, \
                patch('server.simulation_worker.isolate_protocol_stdout', return_value=io.BytesIO()):
            self.assertEqual(main.main(self.args + ['--movement-observe', '--movement-observe-position',
                                                   '4294967295:1:0:0:4095']), 0)
        opened.assert_called_once(); streams.assert_called_once()
        self.assertEqual(events, [(Path('.').resolve() / 'canonical-state.jsonl',
                                   PositionTraceSpec(4294967295, 1, 0, 0, 4095))])

    def test_bad_specs_fail_before_protocol_isolation_or_native_open(self):
        invalid = ('', '42:1:0:0', '42:1:0:0:1:2', '42:0:0:0:1', '-1:1:0:0:1',
                   '42:1:-1:0:1', '42:1:0:1:0', '42:1:0:0:4096',
                   '4294967296:1:0:0:1', '42:4294967296:0:0:1',
                   '42:1:4294967296:0:1', '42:1:0:0:2147483648',
                   '042:1:0:0:1', '42:+1:0:0:1', '42:1:0:0:1 ',
                   '\u0664\u0662:1:0:0:1', '9'*65)
        for value in invalid:
            with self.subTest(value=value), patch.object(main.NativeSession, 'open') as opened, \
                    patch('server.simulation_worker.isolate_protocol_stdout') as isolate, \
                    patch.object(main.sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
                main.main(self.args + ['--movement-observe', '--movement-observe-position=' + value])
            self.assertEqual(error.exception.code, 2)
            opened.assert_not_called(); isolate.assert_not_called()

    def test_position_option_requires_existing_state_observer_before_any_native_load(self):
        with patch.object(main.NativeSession, 'open') as opened, \
                patch('server.simulation_worker.isolate_protocol_stdout') as isolate, \
                patch.object(main.sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit) as error:
            main.main(self.args + ['--movement-observe-position', '42:1:0:0:1'])
        self.assertEqual(error.exception.code, 2)
        opened.assert_not_called(); isolate.assert_not_called()

    def test_position_file_refusal_closes_the_opened_owner(self):
        events = []
        class Session:
            def enable_movement_observation(self, path, *, position_trace):
                events.append('enable'); raise FileExistsError('preserved position trace')
            def close(self): events.append('close')
        with patch.object(main.NativeSession, 'open', return_value=Session()), \
                patch.object(main, 'run_streams') as streams, \
                patch('server.simulation_worker.isolate_protocol_stdout', return_value=io.BytesIO()), \
                patch.object(main.sys, 'stderr', io.StringIO()):
            self.assertEqual(main.main(self.args + ['--movement-observe', '--movement-observe-position',
                                                   '42:75:0:0:3']), 1)
        self.assertEqual(events, ['enable', 'close']); streams.assert_not_called()


class PositionNativeBoundaryTests(TestCase):
    # Reuse the established authored ABI fixture without inheriting/rerunning
    # its existing tests. SnapshotHeap is a Python stand-in, not Simulation.dll.
    dispatch = fixtures.NativeBoundaryTests.dispatch
    authority = fixtures.NativeBoundaryTests.authority
    process = fixtures.NativeBoundaryTests.process
    step = fixtures.NativeBoundaryTests.step
    query = fixtures.NativeBoundaryTests.query
    advance = fixtures.NativeBoundaryTests.advance

    def setup_worker(self, spec=None, **kwargs):
        constructor = CanonicalStateObserver
        if spec is not None:
            with patch('client_patch.prediction_worker.observation.CanonicalStateObserver',
                       side_effect=lambda path: constructor(path, position_trace=spec)):
                fixtures.NativeBoundaryTests.setup_worker(self, **kwargs)
        else:
            fixtures.NativeBoundaryTests.setup_worker(self, **kwargs)

    def position_rows(self):
        return [json.loads(line) for line in self.path.with_name('native-positions.jsonl').read_text().splitlines()]

    def test_native_enable_forwards_position_spec_before_init(self):
        raw = fixtures.NativeFixture()
        session = fixtures.NativeSession(raw, arena=fixtures.SnapshotHeap(raw))
        self.addCleanup(session.close)
        spec = PositionTraceSpec(42, 75, 0, 0, 3)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'canonical-state.jsonl'
            with patch('client_patch.prediction_worker.observation.windows_tick', return_value=lambda: 900):
                session.enable_movement_observation(path, position_trace=spec)
            self.assertIs(session.movement_observer.position_trace, spec)
            self.assertEqual(path.with_name('native-positions.jsonl').read_bytes(), b'')
            self.assertEqual(raw.queries, [])
            session.close()

    def test_default_and_outside_window_have_no_position_clocks_or_new_queries(self):
        for spec in (None, PositionTraceSpec(42, 75, 0, 10, 11)):
            with self.subTest(spec=spec):
                self.setup_worker(spec); self.authority(0)
                with patch('client_patch.prediction_worker.native.time.perf_counter_ns',
                           side_effect=AssertionError('position clock outside explicit window')):
                    self.advance(0)
                self.assertEqual(self.raw.queries, [(0, 31), (0, 0)])
                if spec is None:
                    self.assertFalse(self.path.with_name('native-positions.jsonl').exists())
                self.session.close()

    def test_position_option_with_no_ledger_remains_query_and_clock_free(self):
        self.setup_worker(PositionTraceSpec(42, 75, 0, 0, 3), ledger=False)
        with patch('client_patch.prediction_worker.native.time.perf_counter_ns',
                   side_effect=AssertionError('no-ledger position clock')):
            self.advance(0)
        self.assertEqual(self.raw.queries, [(0, 0)])
        self.session.close(); self.assertEqual(self.position_rows(), [])

    def test_same_decoded_query_is_copied_and_not_flushed_until_retirement(self):
        self.setup_worker(PositionTraceSpec(42, 75, 0, 0, 3)); self.authority(0)
        decoded = []
        def decode(*args, **kwargs):
            state = decode_snapshot(*args, **kwargs)
            next(entity for entity in state['entities'] if entity['id'] == 42)['position'] = [-0.0, 2.0, 3.0]
            decoded.append(state)
            return state
        with patch('server.native_simulation.decode_snapshot', side_effect=decode) as capture, \
                patch('client_patch.prediction_worker.native.time.perf_counter_ns', side_effect=[1000123, 1020456]):
            self.advance(0)
        capture.assert_called_once()
        self.assertEqual(self.raw.queries, [(0, 31), (0, 0)])
        self.assertEqual(self.position_rows(), [])
        decoded[0]['entities'].clear()  # The trace must already own scalar copies.
        self.session.close()
        row, = self.position_rows()
        self.assertEqual((row['frame'], row['stage'], row['head'], row['confirmed'], row['received']),
                         (0, 'ordinary', -1, -1, 0))
        self.assertEqual((row['query_begin_us'], row['query_end_us']), (1000, 1020))
        self.assertEqual(row['position_bits'], [0x80000000, 0x40000000, 0x40400000])

    def test_replay_context_and_cached_same_physical_head_use_no_extra_query(self):
        self.setup_worker(PositionTraceSpec(42, 75, 0, 0, 4)); self.authority(0)
        for frame in range(4): self.advance(frame)
        before = len(self.raw.queries)
        self.authority(1, remote=[fixtures.MOVE]); self.process(4)
        self.assertEqual(self.raw.queries[before:], [(1, 31), (1, 0), (2, 31), (3, 31)])
        self.step(); self.session.close()
        rows = self.position_rows()
        pre, = [row for row in rows if row['event'] == 'before_restore_cached_head']
        post, = [row for row in rows if row['event'] == 'after_replay_same_head']
        self.assertEqual((pre['frame'], post['frame'], pre['checkpoint_base'], pre['first_divergent_frame']), (3, 3, 0, 1))
        self.assertEqual((pre['revision'], post['revision']), (1, 1))
        self.assertEqual(post['stage'], 'replay')
        self.assertEqual((post['head'], post['received'], post['corrections'], post['replayed_frames']), (3, 1, 0, 2))
        self.assertLessEqual(pre['query_end_us'], post['query_begin_us'])
        last = rows[-1]
        self.assertEqual((last['frame'], last['stage'], last['corrections'], last['replayed_frames']), (4, 'ordinary', 1, 3))
