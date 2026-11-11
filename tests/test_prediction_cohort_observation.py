"""Authored decoded-state/worker checks; no original DLL or game execution."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from client_patch.prediction_worker import __main__ as main
from client_patch.prediction_worker.observation import (
    CanonicalStateObserver, CohortTraceSpec, ObservationError, PositionTraceSpec,
    parse_cohort_trace_spec,
)
from server.native_simulation import decode_snapshot
from tests import test_prediction_state_observation as fixtures


def entity(identifier=11, *, army=1, unit_type=1, position=None):
    return dict(id=identifier, army=army, type=unit_type,
                position=[1.5, -0.0, -2.25] if position is None else position)


def actual(frame, entities):
    return dict(frame=frame, viewer=31, entities=entities)


def context(frame, *, stage='ordinary', head=None, at=100, tick=1000, **changes):
    return dict(dict(stage=stage, head=frame-1 if head is None else head,
                     confirmed=-1, received=-1, corrections=0, replayed_frames=0,
                     query_begin_us=at, query_end_us=at+4,
                     query_begin_tick_ms=tick, query_end_tick_ms=tick+1), **changes)


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


class CohortObserverTests(TestCase):
    def observer(self, *, spec=None, **options):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'canonical-state.jsonl'
        observer = CanonicalStateObserver(path, tick=lambda: 900,
            cohort_trace=CohortTraceSpec(1, 1, 420, 520, 8) if spec is None else spec, **options)
        self.addCleanup(observer.close); observer.begin_world(7)
        return observer, path.with_name('native-cohort-positions.jsonl')

    def test_unknown_birth_id_sorted_census_and_float_bits_are_actual_copies(self):
        observer, path = self.observer()
        first = actual(420, [entity(), entity(9, army=0)])
        observer.record(7, 420, first, context=context(420))
        born = actual(421, [entity(9001, position=[3., 0., 4.]), entity(), entity(8, unit_type=6)])
        observer.record(7, 421, born, context=context(421, at=110, tick=1002))
        born['entities'][0]['position'][0] = 99.
        observer.finish_world(7)
        one, two = rows(path)
        self.assertEqual([e['id'] for e in one['entities']], [11])
        self.assertEqual([e['id'] for e in two['entities']], [11, 9001])
        self.assertEqual(two['entities'][1]['position'], [3., 0., 4.])
        self.assertEqual(one['entities'][0]['position_bits'], [0x3fc00000, 0x80000000, 0xc0100000])
        self.assertEqual((one['count'], two['count'], two['event']), (1, 2, 'native_cohort_positions'))
        self.assertEqual(two['cohort_spec'], dict(type=1, army=1, first_frame=420, last_frame=520, max_entities=8))
        self.assertNotIn('incarnation', one); self.assertNotIn('watched_identity', one)

    def test_cached_before_restore_and_after_same_head_copy_the_whole_cohort(self):
        observer, path = self.observer()
        for frame in (420, 421):
            observer.record(7, frame, actual(frame, [entity(), entity(999, position=[float(frame), 0., 0.])]),
                            context=context(frame, at=100+(frame-420)*10, tick=1000+(frame-420)*2))
        observer.invalidate_after(7, 419)
        for frame in (420, 421):
            observer.record(7, frame, actual(frame, [entity(position=[-1., 0., 0.]), entity(999, position=[-float(frame), 0., 0.])]),
                            context=context(frame, stage='replay', head=421, at=200+(frame-420)*10,
                                            tick=1010+(frame-420)*2, replayed_frames=frame-420))
        observer.finish_world(7)
        result = rows(path)
        before, = [row for row in result if row['event'] == 'before_restore_cached_head']
        after, = [row for row in result if row['event'] == 'after_replay_same_head']
        self.assertEqual((before['frame'], after['frame'], after['revision']), (421, 421, 1))
        self.assertEqual((before['query_revision'], after['query_revision']), (0, 1))
        self.assertEqual(before['entities'], result[before['cached_from_record']]['entities'])
        self.assertEqual(before['entities'][1]['position'], [421., 0., 0.])
        self.assertEqual(after['entities'][1]['position'], [-421., 0., 0.])
        self.assertEqual((before['query_begin_tick_ms'], before['query_end_tick_ms']), (1002, 1003))
        self.assertEqual((after['query_begin_tick_ms'], after['query_end_tick_ms']), (1012, 1013))
        self.assertEqual((before['checkpoint_base'], after['first_divergent_frame']), (419, 420))

    def test_incomplete_ambiguous_invalid_and_oversize_census_fail_before_append(self):
        invalid = [
            [dict(id=11, army=1, type=1)], [dict(id=11, army=1, position=[0., 0., 0.])],
            [dict(id=11, type=1, position=[0., 0., 0.])], [dict(id=11, position=[0., 0., 0.])],
            [entity(), entity()], [entity(), entity(11, army=0)], [entity(True)],
            [entity(army=True)], [entity(unit_type=-1)], [entity(position=[1., 2.])],
            [entity(position=[float('nan'), 0., 0.])], [entity(position=[1e300, 0., 0.])],
            [entity(position=[0.1, 0., 0.])], [entity(i) for i in range(9)],
        ]
        for entities in invalid:
            with self.subTest(entities=entities):
                observer, path = self.observer()
                with self.assertRaises(ObservationError):
                    observer.record(7, 420, actual(420, entities), context=context(420))
                self.assertEqual((observer._cohorts.total, observer.pending, path.read_bytes()), (0, {}, b''))

    def test_empty_is_truthful_and_unrelated_known_identity_can_be_partial(self):
        observer, path = self.observer()
        observer.record(7, 420, actual(420, [dict(id=1, type=2), dict(id=2, army=0)]), context=context(420))
        observer.finish_world(7)
        row, = rows(path)
        self.assertEqual((row['status'], row['count'], row['entities']), ('empty', 0, []))

    def test_window_missing_cache_and_row_budget_never_invent_positions(self):
        observer, path = self.observer(max_cohort_records=2)
        observer.record(7, 419, actual(419, []), context=None)
        observer.invalidate_after(7, 418)
        observer.record(7, 420, actual(420, [entity()]), context=context(420))
        with self.assertRaisesRegex(ObservationError, 'row budget'):
            observer.record(7, 421, actual(421, [entity()]), context=context(421, at=110, tick=1002))
        observer.close()
        empty, valid = rows(path)
        self.assertEqual((empty['status'], empty['count'], empty['entities']), ('outside_window', 0, []))
        self.assertIsNone(empty['query_begin_tick_ms']); self.assertIsNone(empty['query_revision'])
        self.assertEqual(valid['count'], 1)

    def test_clock_context_world_and_lifecycle_are_strict_and_rematch_resets_revision(self):
        observer, path = self.observer()
        observer.record(7, 420, actual(420, [entity()]), context=context(420))
        for changed in (dict(query_begin_tick_ms=999), dict(query_end_tick_ms=999),
                        dict(query_begin_tick_ms=True), dict(query_begin_us=99), dict(head=418)):
            with self.subTest(changed=changed), self.assertRaises(ObservationError):
                observer.record(7, 421, actual(421, [entity()]),
                                context=context(421, at=110, tick=1002, **changed))
        observer.invalidate_after(7, 419); observer.finish_world(7); observer.begin_world(8)
        with self.assertRaises(ObservationError):
            observer.record(7, 420, actual(420, [entity()]), context=context(420, at=200, tick=1010))
        observer.record(8, 420, actual(420, [entity(1001)]), context=context(420, at=200, tick=1010))
        observer.finish_world(8)
        self.assertEqual((rows(path)[-1]['world'], rows(path)[-1]['revision']), (8, 0))

    def test_simultaneous_single_trace_preserves_its_exact_schema_and_canonical_output(self):
        cohort, cohort_path = self.observer(position_trace=PositionTraceSpec(11, 1, 1, 420, 520))
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        plain_path = Path(folder.name) / 'canonical-state.jsonl'
        plain = CanonicalStateObserver(plain_path, tick=lambda: 900,
                                       position_trace=PositionTraceSpec(11, 1, 1, 420, 520))
        self.addCleanup(plain.close); plain.begin_world(7)
        for frame in (420, 421):
            state = actual(frame, [entity(), entity(234)])
            ctx = context(frame, at=100+(frame-420)*10, tick=1000+(frame-420)*2)
            cohort.record(7, frame, state, context=ctx)
            plain.record(7, frame, state, context={k: v for k, v in ctx.items() if not k.endswith('_tick_ms')})
        for observer in (cohort, plain): observer.invalidate_after(7, 419); observer.finish_world(7)
        self.assertEqual(rows(cohort_path.with_name('native-positions.jsonl')), rows(plain_path.with_name('native-positions.jsonl')))
        self.assertEqual(cohort_path.with_name('canonical-state.jsonl').read_bytes(), plain_path.read_bytes())

    def test_existing_cohort_file_is_not_overwritten_and_partial_construction_closes_other_streams(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'canonical-state.jsonl'
        cohort = path.with_name('native-cohort-positions.jsonl'); cohort.write_bytes(b'preserve\n')
        opened, original = [], Path.open
        def capture(target, *args, **options):
            stream = original(target, *args, **options); opened.append(stream); return stream
        with patch.object(Path, 'open', capture), self.assertRaises(FileExistsError):
            CanonicalStateObserver(path, tick=lambda: 0,
                                   position_trace=PositionTraceSpec(11, 1, 1, 0, 1),
                                   cohort_trace=CohortTraceSpec(1, 1, 0, 1, 8))
        self.assertEqual(cohort.read_bytes(), b'preserve\n')
        self.assertEqual(len(opened), 2); self.assertTrue(all(stream.closed for stream in opened))

    def test_failed_cohort_flush_is_not_retried_and_all_sibling_streams_close(self):
        observer, _ = self.observer(position_trace=PositionTraceSpec(11, 1, 1, 420, 520))
        observer.record(7, 420, actual(420, [entity()]), context=context(420))
        observer._cohorts.stream.close()
        class Broken:
            writes = 0
            closed = False
            def write(self, data): self.writes += 1; raise OSError('authored cohort write failure')
            def flush(self): raise AssertionError('failed trace must not retry')
            def close(self): self.closed = True
        broken = Broken(); observer._cohorts.stream = broken
        with self.assertRaisesRegex(OSError, 'cohort write failure'): observer.finish_world(7)
        observer.close()
        self.assertEqual(broken.writes, 1)
        self.assertTrue(broken.closed and observer.closed and observer.stream.closed and observer._positions.closed)


class CohortCliTests(TestCase):
    args = ['--original-dll', 'original', '--heap-helper', 'heap', '--cooperative', 'coop', '--data-dir', '.']

    def test_canonical_cli_and_immutable_bounds(self):
        self.assertEqual(parse_cohort_trace_spec('1:1:420:520:8'), CohortTraceSpec(1, 1, 420, 520, 8))
        invalid = ('', '1:1:420:520', '1:1:420:520:8:9', '0:1:420:520:8', '1:1:420:520:0',
                   '1:1:420:520:9', '1:1:520:420:8', '1:1:0:4096:8', '1:1:0:2147483648:8',
                   '1:4294967296:0:1:8', '01:1:0:1:8', '1:+1:0:1:8', '١:1:0:1:8', '1:1:0:1:8 ')
        for value in invalid:
            with self.subTest(value=value), patch.object(main.NativeSession, 'open') as opened, \
                    patch('server.simulation_worker.isolate_protocol_stdout') as isolate, \
                    patch.object(main.sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
                main.main(self.args + ['--movement-observe', '--movement-observe-cohort=' + value])
            opened.assert_not_called(); isolate.assert_not_called()
        for fields in ((True, 1, 0, 1, 8), (1, True, 0, 1, 8), (1, 1, False, 1, 8), (1, 1, 0, 1, True)):
            with self.subTest(fields=fields), self.assertRaises(ObservationError): CohortTraceSpec(*fields)

    def test_cli_requires_observer_before_load_and_forwards_both_independent_specs(self):
        with patch.object(main.NativeSession, 'open') as opened, \
                patch('server.simulation_worker.isolate_protocol_stdout') as isolate, \
                patch.object(main.sys, 'stderr', io.StringIO()), self.assertRaises(SystemExit):
            main.main(self.args + ['--movement-observe-cohort=1:1:420:520:8'])
        opened.assert_not_called(); isolate.assert_not_called()
        calls = []
        class Session:
            def enable_movement_observation(self, path, **options): calls.append((path, options))
        with patch.object(main.NativeSession, 'open', return_value=Session()), \
                patch.object(main, 'run_streams', return_value=0), \
                patch('server.simulation_worker.isolate_protocol_stdout', return_value=io.BytesIO()):
            self.assertEqual(main.main(self.args + ['--movement-observe', '--movement-observe-cohort=1:1:420:520:8',
                                                   '--movement-observe-position=11:1:1:420:520']), 0)
        self.assertEqual(calls[0][1], dict(cohort_trace=CohortTraceSpec(1, 1, 420, 520, 8),
                                          position_trace=PositionTraceSpec(11, 1, 1, 420, 520)))


class CohortNativeBoundaryTests(TestCase):
    dispatch = fixtures.NativeBoundaryTests.dispatch
    authority = fixtures.NativeBoundaryTests.authority
    process = fixtures.NativeBoundaryTests.process
    step = fixtures.NativeBoundaryTests.step
    query = fixtures.NativeBoundaryTests.query
    advance = fixtures.NativeBoundaryTests.advance

    @staticmethod
    def decode(*args, **options):
        # The shared fake ABI intentionally has only identity buffers. Add
        # authored decoded positions here, rather than accepting missing poses.
        state = decode_snapshot(*args, **options)
        for item in state['entities']:
            item['position'] = [float(item['id']), 0., 0.]
        return state

    def setup_worker(self, *, first=0, last=4, ledger=True, both=False):
        original = CanonicalStateObserver
        def observer(path):
            return original(path, cohort_trace=CohortTraceSpec(75, 0, first, last, 8),
                            position_trace=PositionTraceSpec(42, 75, 0, first, last) if both else None)
        with patch('client_patch.prediction_worker.observation.CanonicalStateObserver', side_effect=observer):
            fixtures.NativeBoundaryTests.setup_worker(self, ledger=ledger)
        decoder = patch('server.native_simulation.decode_snapshot', side_effect=self.decode)
        decoder.start(); self.addCleanup(decoder.stop)

    def test_both_ids_share_one_existing_query_decode_and_clock_bracket(self):
        self.setup_worker(both=True); self.authority(0); decoded = []
        def decode(*args, **options):
            state = self.decode(*args, **options)
            state['entities'].append(entity(9876, army=0, unit_type=75, position=[3., 0., 4.]))
            decoded.append(state); return state
        ticks = iter([100, 101, 102])  # begin, end, existing canonical promotion
        self.session.movement_observer.tick = lambda: next(ticks)
        with patch('server.native_simulation.decode_snapshot', side_effect=decode) as capture, \
                patch('client_patch.prediction_worker.native.time.perf_counter_ns', side_effect=[1000123, 1020456]):
            self.advance(0)
        capture.assert_called_once(); self.assertEqual(self.raw.queries, [(0, 31), (0, 0)])
        decoded[0]['entities'].clear(); self.session.close()
        row, = rows(self.path.with_name('native-cohort-positions.jsonl'))
        self.assertEqual([e['id'] for e in row['entities']], [42, 9876])
        self.assertEqual((row['query_begin_us'], row['query_end_us']), (1000, 1020))
        self.assertEqual((row['query_begin_tick_ms'], row['query_end_tick_ms']), (100, 101))
        single, = rows(self.path.with_name('native-positions.jsonl'))
        self.assertEqual((single['query_begin_us'], single['query_end_us']), (1000, 1020))
        self.assertNotIn('query_begin_tick_ms', single)

    def test_repair_same_head_uses_existing_replay_queries_only(self):
        self.setup_worker(); self.authority(0)
        for frame in range(4): self.advance(frame)
        before = len(self.raw.queries)
        self.authority(1, remote=[fixtures.MOVE]); self.process(4)
        self.assertEqual(self.raw.queries[before:], [(1, 31), (1, 0), (2, 31), (3, 31)])
        self.step(); self.session.close()
        result = rows(self.path.with_name('native-cohort-positions.jsonl'))
        pre, = [r for r in result if r['event'] == 'before_restore_cached_head']
        post, = [r for r in result if r['event'] == 'after_replay_same_head']
        self.assertEqual((pre['frame'], post['frame'], post['head']), (3, 3, 3))
        self.assertEqual((pre['count'], post['count']), (2, 1))
        self.assertEqual([e['id'] for e in pre['entities']], [42, 79])
        self.assertEqual([e['id'] for e in post['entities']], [42])

    def test_outside_window_or_no_ledger_add_no_query_or_qpc_sampling(self):
        for options in (dict(first=10, last=11), dict(ledger=False)):
            with self.subTest(options=options):
                self.setup_worker(**options)
                if options.get('ledger', True): self.authority(0)
                with patch('client_patch.prediction_worker.native.time.perf_counter_ns',
                           side_effect=AssertionError('cohort clock outside active existing-query path')):
                    self.advance(0)
                self.assertEqual(self.raw.queries, [(0, 31), (0, 0)] if options.get('ledger', True) else [(0, 0)])
                self.session.close()
                self.assertEqual(rows(self.path.with_name('native-cohort-positions.jsonl')), [])
