"""Authored verifier controls; no original DLL, simulation or AI is executed."""
import asyncio
import contextlib
import copy
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from server.game_data import InputError, InputValidation, encode_player_input
from tests import test_input_validation as commands
from tests.synthetic import template
from tests import snapshot_decoder_fixtures as snapshots
from tools import verify_compact_worker as v


def full(frame=0, entities=None):
    return dict(frame=frame, viewer=31, local_alliance=0, canonical_fnv1a64='0'*16,
        raw_sha256='a'*64, byte_count=100, counts=dict(army=1, type=1, health=1, position=1, resources=0),
        resources={}, game_state=dict(complete=False, game_over_frame=-1, winning_alliance=0,
            army_conceded_flag=0, game_over_checksum=0),
        entities=copy.deepcopy([dict(id=42, army=0, type=100, max_health=10, current_damage=0,
                                   position=[0.0, -0.0, 0.0])] if entities is None else entities))


class ProjectionTests(unittest.TestCase):
    def test_intersection_order_boundaries_and_partial_records(self):
        source = full(entities=[dict(id=0, army=0), dict(id=1, type=100),
            dict(id=2, position=[1., 2., 3.]), dict(id=3, army=1, type=101),
            dict(id=0xffffffff, army=0, type=100)])
        projected = v.projection(source)
        self.assertEqual(projected['ownership'], [dict(id=3, army=1, type=101),
                                                 dict(id=0xffffffff, army=0, type=100)])
        self.assertEqual(set(projected), v.COMMON | {'ownership'})
        self.assertEqual({key: projected[key] for key in v.COMMON}, {key: source[key] for key in v.COMMON})

    def test_every_common_field_is_compared_including_raw_hash(self):
        expected = v.projection(full())
        for key in v.COMMON:
            altered = copy.deepcopy(expected)
            altered[key] = None
            with self.subTest(key=key), self.assertRaises(ValueError):
                v.compare_projection(altered, expected)

    def test_schema_and_incomplete_ownership_are_not_normalized(self):
        expected = v.projection(full())
        for key, value in [('entities', []), ('ownership', [])]:
            altered = copy.deepcopy(expected)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                v.compare_projection(altered, expected)

    def test_projection_refuses_unsorted_or_duplicate_reference_ids(self):
        for records in ([dict(id=2), dict(id=1)], [dict(id=1), dict(id=1)], [dict(id=True)]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                v.projection(full(entities=records))

    def test_full_digest_still_covers_health_position_and_entities(self):
        source = full()
        for key, value in [('position', [1., 0., 0.]), ('current_damage', 1), ('army', 1), ('type', 101)]:
            changed = copy.deepcopy(source)
            changed['entities'][0][key] = value
            self.assertNotEqual(v.b.state_digest(changed), v.b.state_digest(source))


class HistoryAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.descriptors = Path(directory.name)
        for package, messages in [('common_pb', commands.COMMON), ('game_pb', commands.GAME)]:
            (cls.descriptors/(package+'.proto.json')).write_text(json.dumps(dict(package=package, messages=messages)),
                                                               encoding='utf-8')

    def test_identical_command_acceptance_after_every_history_transition(self):
        game = template()
        game.descriptors_path = self.descriptors
        game.entity_abilities = {100: {7}, 101: {8}}
        match = game.build_match([dict(slot=i, player_id=i+1, name=f'Player{i}') for i in (0, 1)],
                                 game.default_decks, seed=1)
        histories = ({}, {})
        validators = [InputValidation(match, game, entity_lookup=history.get) for history in histories]
        sequence = [
            [dict(id=42, army=0, type=100), dict(id=90, army=1, type=100)],
            [],  # Death preserves delayed-command ownership.
            [dict(id=42, army=1), dict(id=43, type=100)],  # Never manufacture a pair.
            [dict(id=42, type=101), dict(id=43, army=0)],
            [dict(id=42, army=1, type=100)],  # Complete owner change.
            [dict(id=42, army=0, type=101)],  # Reused ID/type change.
        ]
        expected_owned = [(0, 100), (0, 100), (0, 100), (0, 100), (1, 100), (0, 101)]
        cases = [([commands.group([42])], True), ([commands.group([99])], False),
            ([commands.group(), commands.group([90])], False),
            ([commands.group([42, 42])], False),
            ([commands.group([42], entity_type=101, ability=8)], False),
            ([commands.group()], True)]
        for frame, (records, owner) in enumerate(zip(sequence, expected_owned)):
            state = full(frame, records)
            v.update_history(histories[0], state, 'full')
            v.update_history(histories[1], v.projection(state), 'ownership')
            self.assertEqual(histories[0], histories[1])
            self.assertEqual(histories[0][42], owner)
            self.assertNotIn(43, histories[0])
            for groups, originally_valid in cases:
                blob = encode_player_input(match.identities_by_slot[0], [commands.execute(groups)])
                results = []
                for validator in validators:
                    try:
                        results.append(('accepted', validator.validate_player_input(0, blob)))
                    except InputError as error:
                        results.append(('refused', str(error)))
                self.assertEqual(results[0], results[1])
                if frame < 4:
                    self.assertEqual(results[0][0] == 'accepted', originally_valid)


class ArmTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.args = SimpleNamespace(output=self.root, assets=self.root/'assets', journal=self.root/'journal',
            library=self.root/'decoder.dll', library_sha256='b'*64, timeout_seconds=30)
        self.payloads = [bytes([frame+1]) for frame in range(3)]
        states = [full(frame) for frame in range(3)]
        self.source = dict(data=b'bootstrap', setup=None, payloads=self.payloads,
            inputs=b''.join(struct.pack('<I', len(p))+p for p in self.payloads),
            rows=[dict(frame=i, phase=v.c.PHASES[i], input_sha256=v.b.digest(p), state_sha256=v.b.state_digest(states[i]))
                  for i, p in enumerate(self.payloads)],
            reference=dict(bootstrap_sha256='c'*64, simulation_sha256='d'*64, asset_manifest_sha256='e'*64,
                journal_files={'frames.bin': 'f'*64}, workload={'authored': True}, journal_source_hashes={'old': '0'*64}))
        self.states = states
        for state in self.states:
            state['resources'] = {0: {'primary': 1}}
        for row, state in zip(self.source['rows'], self.states):
            row['state_sha256'] = v.b.state_digest(state)
        self.created = []
        self.mutate = None
        self.closed = 0
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(v, 'sources', return_value={'authored': 'a'*64}))
        self.stack.enter_context(mock.patch.object(v, 'memory_sample', return_value={'available': False, 'reason': 'authored'}))
        self.stack.enter_context(mock.patch.object(v.b, 'backend_identity', return_value={'kind': 'windows-worker'}))
        self.stack.enter_context(mock.patch.object(v.SimulationWorker, 'create', side_effect=self.create))

    async def create(self, data, dll, **kwargs):
        self.created.append(kwargs)
        test, mode = self, kwargs['state_mode']
        class Worker:
            state_mode, projection_version = mode, 1
            pid, native_pid = 123, 123
            _test_backend, failure, ai_info, backend_statistics = False, None, None, None
            game_data_sha256, dll_sha256 = 'c'*64, 'd'*64
            runtime_info = dict(os_name='nt', platform='win32', pointer_bits=64, implementation='cpython',
                                executable='authored-python.exe', python_version='3.12')
            decoder_info = v.ai.decoder_identity(test.args, 'rust', None)
            state_projection_info = {'version': 1, 'step_mode': mode}
            state_projection_modes = ['summary', 'full', 'ownership']
            process = SimpleNamespace(poll=lambda: 0)
            _stderr_thread = SimpleNamespace(is_alive=lambda: False)
            _io = SimpleNamespace(_threads=[])
            last_response_bytes = 200
            async def state(self, viewer, *, mode):
                value = full(0xffffffff)
                return value if mode == 'full' else v.projection(value)
            async def process_frame(self, payload, dt_ms):
                frame = payload[0]-1
                value = copy.deepcopy(test.states[frame])
                if mode == 'ownership':
                    value = v.projection(value)
                if test.mutate:
                    test.mutate(value, frame, mode)
                return SimpleNamespace(frame=frame, state=value)
            async def close(self):
                test.closed += 1
        return Worker()

    def arm(self, mode, name):
        return asyncio.run(v.run_arm(self.args, self.source, None, mode, self.root/name,
                                      self.root/'reference.jsonl'))

    def test_every_frame_full_digest_and_independent_projection(self):
        first = self.arm('full', 'full')
        second = self.arm('ownership', 'ownership')
        self.assertTrue(first['passed'], first.get('error'))
        self.assertTrue(second['passed'], second.get('error'))
        self.assertEqual(self.closed, 2)
        self.assertEqual(first['frames'], 3)
        self.assertEqual(second['phases']['combat']['reply_bytes']['mean'], 200)
        self.assertEqual([row['state_mode'] for row in self.created], ['full', 'ownership'])
        reference = [json.loads(line) for line in (self.root/'reference.jsonl').read_text().splitlines()]
        self.assertEqual(len(reference), 4)
        self.assertEqual(reference[0]['frame'], -1)
        self.assertEqual(reference[-1]['full_state_sha256'], self.source['rows'][-1]['state_sha256'])

    def test_ownership_failure_retains_partial_report_and_closes(self):
        self.assertTrue(self.arm('full', 'full')['passed'])
        def corrupt(value, frame, mode):
            if mode == 'ownership' and frame == 1:
                value['canonical_fnv1a64'] = '1'*16
        self.mutate = corrupt
        result = self.arm('ownership', 'bad')
        self.assertFalse(result['passed'])
        self.assertIn('value differs', result['error'])
        self.assertEqual(result['frames'], 1)
        self.assertEqual(self.closed, 2)
        self.assertTrue((self.root/'bad'/'benchmark.json').exists())

    def test_cross_buffer_raw_differences_are_retained_not_hidden(self):
        self.assertTrue(self.arm('full', 'full')['passed'])
        def change_raw(value, frame, mode):
            value['raw_sha256'] = '0'*64
        self.mutate = change_raw
        result = self.arm('ownership', 'other-raw')
        self.assertTrue(result['passed'], result.get('error'))
        rows = [json.loads(line) for line in (self.root/'other-raw'/'frames.jsonl').read_text().splitlines()]
        self.assertTrue(all(not row['raw_hash_equal'] and row['raw_sha256'] == '0'*64
                            and row['reference_raw_sha256'] == 'a'*64 for row in rows))

    def test_retained_full_digest_cannot_be_relaxed(self):
        self.states[1]['entities'][0]['position'][0] = 2.
        result = self.arm('full', 'bad')
        self.assertFalse(result['passed'])
        self.assertIn('observable native state differs', result['error'])
        self.assertEqual(self.closed, 1)

    def test_missing_response_bytes_refuses_qualification(self):
        original = self.create
        async def create(*args, **kwargs):
            worker = await original(*args, **kwargs)
            worker.last_response_bytes = None
            return worker
        with mock.patch.object(v.SimulationWorker, 'create', side_effect=create):
            result = self.arm('full', 'bad')
        self.assertFalse(result['passed'])
        self.assertIn('response bytes unavailable', result['error'])

    def test_changed_source_refuses_arm(self):
        with mock.patch.object(v, 'sources', side_effect=[{'a': 'a'*64}, {'a': 'b'*64}]):
            result = self.arm('full', 'changed')
        self.assertFalse(result['passed'])
        self.assertFalse(result['source_unchanged'])

    def test_fresh_ai_mismatch_closes_worker(self):
        self.source.update(setup=object(), bots=[{1: b'expected'}]*3,
                           roster=SimpleNamespace(bots=[1], check_inputs=lambda value: None))
        original = self.create
        async def create(*args, **kwargs):
            worker = await original(*args, **kwargs)
            async def bot_inputs(frame):
                return {1: b'wrong'}
            worker.bot_inputs = bot_inputs
            return worker
        with mock.patch.object(v.SimulationWorker, 'create', side_effect=create):
            result = self.arm('full', 'bad-ai')
        self.assertFalse(result['passed'])
        self.assertIn('fresh original AI bytes differ', result['error'])
        self.assertEqual(self.closed, 1)

    def test_cleanup_failure_is_not_native_qualification(self):
        original = self.create
        async def create(*args, **kwargs):
            worker = await original(*args, **kwargs)
            worker.failure = 'authored terminal failure'
            return worker
        with mock.patch.object(v.SimulationWorker, 'create', side_effect=create):
            result = self.arm('full', 'bad-cleanup')
        self.assertFalse(result['passed'])
        self.assertFalse(result['native_qualified'])
        self.assertIn('cleanup', result['error'])

    def test_actual_create_claims_cannot_be_fabricated(self):
        original = self.create
        async def create(*args, **kwargs):
            worker = await original(*args, **kwargs)
            worker.state_projection_modes = ['ownership', 'full', 'summary']
            return worker
        with mock.patch.object(v.SimulationWorker, 'create', side_effect=create):
            result = self.arm('full', 'bad-create')
        self.assertFalse(result['passed'])
        self.assertIn('actual CREATE projection claims differ', result['error'])


class SameRawTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.library = self.root/'authored-library.dll'
        self.library.write_bytes(b'MZ authored bytes; never loaded')
        self.args = SimpleNamespace(library=self.library, library_sha256=v.b.digest(self.library.read_bytes()),
                                    corpus=[self.root], assets=self.root)
        raw, meta = snapshots._build(4, sparse=True, reordered=True)
        raw = bytearray(raw)
        struct.pack_into('<I', raw, meta['root_fields'][0], 0)
        self.raw = bytes(raw)
        from server.native_simulation import decode_snapshot
        self.decode = decode_snapshot
        state = self.decode(self.raw, 31, mode='full')
        self.reference = dict(assets=str(self.root), journal=str(self.root), journal_files={},
            simulation_sha256='d'*64, asset_manifest_sha256='e'*64)
        full_sha = v.c.write_json(self.root/'full.json', state)
        summary_sha = v.c.write_json(self.root/'summary.json', {key: state[key] for key in v.COMMON})
        (self.root/'raw.snapshot').write_bytes(self.raw)
        entry = dict(frame=0, viewer=31, phase='combat', include_entities=True,
            snapshot_file='raw.snapshot', snapshot_sha256=v.b.digest(self.raw), bytes=len(self.raw),
            expected_file='full.json', expected_sha256=full_sha, expected_summary_file='summary.json',
            expected_summary_sha256=summary_sha, observable_state_sha256=v.b.state_digest(state))
        self.manifest = dict(schema=1, passed=True, native_qualified=True, source_unchanged=True,
            reference_unchanged=True, source_at_start={'old': 'a'*64}, source_at_finish={'old': 'a'*64},
            cleanup=dict(exit_code=0, failure=None, stderr_thread_closed=True, io_threads_closed=True),
            reference=self.reference, verified_frames=1, selection=[0], viewer_frames=[], snapshots=[entry])
        v.c.write_json(self.root/'manifest.json', self.manifest)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(v, 'sources', return_value={'authored': 'a'*64}))
        self.stack.enter_context(mock.patch.object(v.c, 'load_reference', return_value=(b'', b'',
            [dict(phase='combat', state_sha256=v.b.state_digest(state))], [0], set(), self.reference)))
        self.mutate = None
        test = self
        class Decoder:
            projection_version = 1
            info = {'library_sha256': test.args.library_sha256}
            def decode(self, raw, viewer, *, mode):
                value = test.decode(raw, viewer, mode=mode)
                if test.mutate:
                    test.mutate(mode, value)
                return value
        self.decoder = Decoder()

    def test_all_modes_same_raw_and_independent_projection(self):
        bindings = {}
        report = v.validate_corpora(self.args, bindings, decoder=self.decoder)
        self.assertTrue(report['passed'])
        self.assertTrue(report['inputs_unchanged'])
        self.assertEqual(report['corpora'][0]['snapshots'], 1)
        self.assertEqual(bindings[str(self.root/'raw.snapshot')]['sha256'], v.b.digest(self.raw))

    def test_same_raw_hash_difference_is_always_refused(self):
        def corrupt(mode, state):
            if mode == 'ownership':
                state['raw_sha256'] = '0'*64
        self.mutate = corrupt
        with self.assertRaisesRegex(ValueError, 'raw_sha256'):
            v.validate_corpora(self.args, {}, decoder=self.decoder)

    def test_ownership_omission_refused_independently(self):
        def corrupt(mode, state):
            if mode == 'ownership':
                state['ownership'] = []
        self.mutate = corrupt
        with self.assertRaises(ValueError):
            v.validate_corpora(self.args, {}, decoder=self.decoder)

    def test_raw_file_change_refused(self):
        (self.root/'raw.snapshot').write_bytes(self.raw+b'changed')
        with self.assertRaisesRegex(ValueError, 'digest differs'):
            v.validate_corpora(self.args, {}, decoder=self.decoder)


class OrchestrationTests(unittest.TestCase):
    create = ArmTests.create

    def setUp(self):
        ArmTests.setUp(self)
        self.args = v.arguments(['--assets', str(self.root/'assets'), '--journal', str(self.root/'journal'),
            '--library', str(self.root/'decoder.dll'), '--library-sha256', 'b'*64,
            '--output', str(self.root/'local'/'run'), '--corpus', str(self.root/'corpus')])
        self.args.assets.mkdir()
        self.args.journal.mkdir()
        self.args.corpus[0].mkdir()
        self.args.library.write_bytes(b'MZ authored; never loaded')
        self.args.library_sha256 = v.b.digest(self.args.library.read_bytes())
        self.source['baseline_inputs_sha256'] = '1'*64
        self.stack.enter_context(mock.patch.object(v, 'ROOT', self.root))
        self.stack.enter_context(mock.patch.object(v.sys, 'platform', 'win32'))
        self.stack.enter_context(mock.patch.object(v, 'load_inputs', return_value=self.source))
        self.stack.enter_context(mock.patch.object(v.c, 'check_stability'))
        self.stack.enter_context(mock.patch.object(v.b, 'select_backend', return_value=None))
        self.stack.enter_context(mock.patch.object(v, 'validate_corpora', return_value=dict(schema=1, passed=True,
            inputs_unchanged=True, corpora=[dict(reference=self.source['reference'])])))

    def test_three_pairs_alternate_and_keep_primary_arms_unprofiled(self):
        self.assertEqual(asyncio.run(v.run(self.args)), 0)
        self.assertEqual([row['state_mode'] for row in self.created],
                         ['full', 'ownership', 'ownership', 'full', 'full', 'ownership'])
        report = json.loads((self.args.output/'verification.json').read_text())
        self.assertEqual(len(report['pairs']), 3)
        self.assertTrue(report['inputs_library_and_evidence_unchanged'])
        self.assertFalse(report['room_lifecycle_exercised'])
        self.assertTrue(all(not row[mode]['profiled'] for row in report['pairs'] for mode in ('full', 'ownership')))

    def test_library_mutation_after_arm_is_refused(self):
        original = self.create
        async def create(*args, **kwargs):
            worker = await original(*args, **kwargs)
            if len(self.created) == 6:
                self.args.library.write_bytes(b'MZ changed')
            return worker
        with mock.patch.object(v.SimulationWorker, 'create', side_effect=create):
            self.assertEqual(asyncio.run(v.run(self.args)), 1)
        report = json.loads((self.args.output/'verification.json').read_text())
        self.assertFalse(report['inputs_library_and_evidence_unchanged'])

    def test_existing_output_is_preserved(self):
        self.args.output.mkdir(parents=True)
        marker = self.args.output/'preserve'
        marker.write_bytes(b'old failed evidence')
        with self.assertRaisesRegex(ValueError, 'fresh private output'):
            asyncio.run(v.run(self.args))
        self.assertEqual(marker.read_bytes(), b'old failed evidence')

    def test_non_three_pairs_are_refused(self):
        self.args.pairs = 2
        with self.assertRaisesRegex(ValueError, 'three alternating'):
            v.validate_args(self.args)


class PerformanceGateTests(unittest.TestCase):
    def pairs(self, compact_mean=8., compact_p95=11.):
        return [dict(pair=i+1, full={'phases': {phase: {'timings_ms': {'step_rpc_ms': {'mean': 10., 'p95': 10.}}}
                        for phase in ('movement', 'combat')}},
                    ownership={'phases': {phase: {'timings_ms': {'step_rpc_ms': {'mean': compact_mean, 'p95': compact_p95}}}
                        for phase in ('movement', 'combat')}}) for i in range(3)]

    def test_repeated_mean_improvement_and_absolute_p95_tolerance(self):
        self.assertTrue(v.performance_summary(self.pairs())['passed'])

    def test_p95_regression_and_single_pair_mean_regression_remain_failures(self):
        self.assertFalse(v.performance_summary(self.pairs(compact_p95=11.01))['passed'])
        pairs = self.pairs()
        pairs[1]['ownership']['phases']['combat']['timings_ms']['step_rpc_ms']['mean'] = 10.
        self.assertFalse(v.performance_summary(pairs)['passed'])

    def test_missing_repetitions_never_qualify(self):
        self.assertFalse(v.performance_summary(self.pairs()[:2])['passed'])


if __name__ == '__main__':
    unittest.main()
