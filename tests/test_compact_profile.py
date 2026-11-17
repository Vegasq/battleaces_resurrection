"""Authored projection-profiler controls; no original assets or native DLLs."""
import copy
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server import rust_snapshot_decoder as rust, simulation_worker as ipc, native_simulation as native
from server.native_simulation import decode_snapshot
from server.protobuf_wire import field_uint, field_bytes
from tests.snapshot_decoder_fixtures import make_snapshot, _build
from tests.test_rust_worker_decoder import AuthoredLibrary, Export
from tests import test_summarize_worker_timing as summary_fixtures
from tools import profile_worker_timing as p, summarize_worker_timing as s


class ProjectionLibrary(AuthoredLibrary):
    def __init__(self):
        super().__init__()
        self.ba_snapshot_decoder_projection_version = Export(lambda: 1)
        self.ba_decode_snapshot_v2 = Export(self.decode_v2)

    def decode_v2(self, data, size, viewer, mode, result):
        raw = ctypes.string_at(data, size)
        self.output = json.dumps(decode_snapshot(raw, viewer, mode=('summary', 'full', 'ownership')[mode])).encode()
        return self.decode(data, size, viewer, False, result)


class CompactInstrumentationTests(unittest.TestCase):
    def test_v2_and_legacy_use_one_shared_ffi_metric_each_and_restore_on_exception(self):
        library = ProjectionLibrary()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()/'authored.dll'; path.write_bytes(b'fixture')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            recorder = p.Recorder()
            recorder.current = dict(metrics={})
            with patch.object(ctypes, 'CDLL', return_value=library):
                with self.assertRaisesRegex(ValueError, 'restore'):
                    with p.instrumentation(recorder):
                        decoder = rust.RustSnapshotDecoder(path, digest)
                        info = dict(decoder.info)
                        for mode in ('summary', 'full', 'ownership'):
                            before = recorder.current['metrics'].get('rust.ffi.decode', {}).get('calls', 0)
                            decoder.decode(make_snapshot(3), mode=mode)
                            self.assertEqual(recorder.current['metrics']['rust.ffi.decode']['calls'], before+1)
                        library.output = None
                        decoder.decode(make_snapshot(3), include_entities=True)
                        self.assertEqual(recorder.current['metrics']['rust.ffi.decode']['calls'], 4)
                        self.assertEqual(recorder.decoder_info, info)
                        self.assertEqual(recorder.decoder_projection_version, 1)
                        self.assertEqual(recorder.ffi_decode_exports, ['_decode', '_decode_v2'])
                        raise ValueError('restore')
            self.assertIs(decoder._decode, library.ba_decode_snapshot)
            self.assertIs(decoder._decode_v2, library.ba_decode_snapshot_v2)
            self.assertIs(decoder._free, library.ba_free_buffer)

    def test_create_negotiation_is_captured_without_changing_protocol(self):
        selected = dict(version=1, step_mode='ownership')
        frame = field_uint(1, 0) + field_uint(2, 20) + field_uint(3, 50)
        request = b''.join((ipc.encode_message(ipc.CREATE, 1, -1, dict(state_projection=selected), b'fixture'),
                            ipc.encode_message(ipc.STEP, 2, 0, dict(dt_ms=50), frame),
                            ipc.encode_message(ipc.CLOSE, 3, 0)))
        ordinary, observed = io.BytesIO(), io.BytesIO()
        self.assertEqual(ipc.serve(io.BytesIO(request), ordinary, test_backend=True), 0)
        recorder = p.Recorder()
        with p.instrumentation(recorder):
            self.assertEqual(ipc.serve(io.BytesIO(request), observed, test_backend=True), 0)
        self.assertEqual(ordinary.getvalue(), observed.getvalue())
        self.assertEqual(recorder.state_projection_requested, selected)
        self.assertEqual(recorder.state_projection, selected)
        self.assertEqual(recorder.state_projection_modes, ['summary', 'full', 'ownership'])
        self.assertEqual(recorder.records[0]['metrics']['ipc.decode_metadata']['calls'], 1)
        self.assertEqual(recorder.records[1]['metrics']['ipc.decode_metadata']['calls'], 1)

    def test_actual_projection_source_is_in_inventory(self):
        self.assertIn('server/state_projection.py', p.source_hashes())


class CompactProfileValidationTests(unittest.TestCase):
    def fixture(self, mode='ownership'):
        factory = summary_fixtures.SummaryTests()
        factory.profile, factory.report, factory.rows = factory.fixture()
        profile, report, rows = factory.rust_fixture()
        selected = dict(version=1, step_mode=mode)
        modes = ['summary', 'full', 'ownership']
        profile.update(state_projection_requested=copy.deepcopy(selected), state_projection=copy.deepcopy(selected),
                       state_projection_modes=list(modes), snapshot_decoder_projection_version=1,
                       rust_ffi_decode_exports=['_decode', '_decode_v2'])
        report.update(state_projection=copy.deepcopy(selected), state_projection_modes=list(modes))
        for row in profile['records']:
            if row['operation'] == 'STEP':
                row['metrics']['worker.validate_state'] = dict(calls=1, wall_ns=100, thread_cpu_ns=20,
                                                              process_cpu_ns=40, max_wall_ns=100)
        sources = dict(profile['source_sha256'], **{'server/state_projection.py': 'a'*64})
        profile['source_sha256'] = sources
        report.update(source_at_start=sources, source_at_finish=sources, worker_profile_sha256='b'*64)
        return profile, dict(report=report, rows=rows, payload_lengths=[2]*len(rows))

    def test_each_explicit_mode_retains_exact_decoder_identity(self):
        for mode in ('summary', 'full', 'ownership'):
            with self.subTest(mode=mode):
                profile, benchmark = self.fixture(mode)
                identity = dict(profile['snapshot_decoder'])
                self.assertEqual(len(s.validate_profile(profile, benchmark, 'b'*64)), 5)
                self.assertEqual(profile['snapshot_decoder'], identity)

    def test_projection_spoofs_uncovered_v2_and_missing_sources_fail_closed(self):
        for mutation in ('request', 'echo', 'version_bool', 'missing', 'modes', 'decoder_version',
                         'decoder_bool', 'v2_uncovered', 'source', 'ffi_calls'):
            with self.subTest(mutation=mutation):
                profile, benchmark = self.fixture()
                if mutation == 'request': profile['state_projection_requested']['step_mode'] = 'full'
                elif mutation == 'echo': profile['state_projection']['step_mode'] = 'full'
                elif mutation == 'version_bool': profile['state_projection']['version'] = True
                elif mutation == 'missing': del profile['state_projection_requested']
                elif mutation == 'modes': profile['state_projection_modes'] = ['ownership']
                elif mutation == 'decoder_version': profile['snapshot_decoder_projection_version'] = 2
                elif mutation == 'decoder_bool': profile['snapshot_decoder_projection_version'] = True
                elif mutation == 'v2_uncovered': profile['rust_ffi_decode_exports'] = ['_decode']
                elif mutation == 'source':
                    del benchmark['report']['source_at_start']['server/state_projection.py']
                else: profile['records'][1]['metrics']['rust.ffi.decode']['calls'] = 2
                with self.assertRaises(ValueError):
                    s.validate_profile(profile, benchmark, 'b'*64)

    def test_legacy_cannot_hide_explicit_handshake(self):
        profile, benchmark = self.fixture()
        del benchmark['report']['state_projection']
        del benchmark['report']['state_projection_modes']
        with self.assertRaisesRegex(ValueError, 'unexpected profile projection'):
            s.validate_profile(profile, benchmark, 'b'*64)

    def add_queries(self, profile, benchmark):
        queries = []
        selected = benchmark['report']['state_projection']['step_mode']
        for mode in (selected, 'full'):
            row = copy.deepcopy(profile['records'][1])
            state_keys = {'frame', 'viewer', 'local_alliance', 'canonical_fnv1a64', 'raw_sha256',
                          'byte_count', 'counts', 'resources', 'game_state'}
            if mode != 'summary':
                state_keys.add('entities' if mode == 'full' else 'ownership')
            row.update(operation='STATE', frame=-1, request_payload_bytes=0, response_payload_bytes=0,
                state_query=dict(viewer=31, mode=mode), state_reply=dict(
                    keys=['state', 'state_mode', 'state_projection_version'], state_mode=mode,
                    state_projection_version=1, state_frame=0xffffffff, state_viewer=31,
                    state_keys=sorted(state_keys)))
            for name in ('sim.SimProcessMsg', 'sim.SimStep', 'simulation.process_frame'):
                del row['metrics'][name]
            queries.append(row)
        profile['records'][1:1] = queries
        for index, row in enumerate(profile['records'], 1):
            row['request_id'] = index

    def test_initial_selected_and_full_queries_are_separate_from_step_categories(self):
        for mode in ('summary', 'full', 'ownership'):
            profile, benchmark = self.fixture(mode)
            self.add_queries(profile, benchmark)
            records = s.validate_profile(profile, benchmark, 'b'*64)
            phases = s.summarize_phases(records, benchmark['rows'])
            self.assertEqual(len(records), 7)
            self.assertTrue(all(phase['operations']['STEP']['requests'] == 1 for phase in phases.values()))
            self.assertAlmostEqual(phases['combat']['categories']['worker_state_validation']['mean_ms_per_frame'], .0001)

    def test_initial_state_coverage_and_identity_cannot_be_loosened(self):
        for mutation in ('legacy', 'missing_query', 'late_query', 'request_gap', 'frame', 'viewer', 'mode',
                         'extra_key', 'response_mode', 'response_version', 'response_frame', 'response_keys',
                         'response_payload', 'bool_payload', 'rust_count', 'missing_worker_metric', 'third_query'):
            with self.subTest(mutation=mutation):
                profile, benchmark = self.fixture()
                self.add_queries(profile, benchmark)
                row = profile['records'][1]
                if mutation == 'legacy':
                    benchmark['report'].pop('state_projection')
                    benchmark['report'].pop('state_projection_modes')
                    profile.update(state_projection=None, state_projection_requested=None, state_projection_modes=None)
                elif mutation == 'missing_query': profile['records'].pop(2)
                elif mutation == 'late_query': profile['records'][2], profile['records'][3] = profile['records'][3], profile['records'][2]
                elif mutation == 'request_gap': row['request_id'] = 99
                elif mutation == 'frame': row['frame'] = 0
                elif mutation == 'viewer': row['state_query']['viewer'] = 0
                elif mutation == 'mode': row['state_query']['mode'] = 'full'
                elif mutation == 'extra_key': row['state_query']['include_entities'] = False
                elif mutation == 'response_mode': row['state_reply']['state_mode'] = 'full'
                elif mutation == 'response_version': row['state_reply']['state_projection_version'] = True
                elif mutation == 'response_frame': row['state_reply']['state_frame'] = -1
                elif mutation == 'response_keys': row['state_reply']['state_keys'].append('entities')
                elif mutation == 'response_payload': row['response_payload_bytes'] = 1
                elif mutation == 'bool_payload': row['request_payload_bytes'] = False
                elif mutation == 'rust_count': row['metrics']['rust.validate']['calls'] = 2
                elif mutation == 'third_query': profile['records'].insert(3, copy.deepcopy(profile['records'][2]))
                else: del row['metrics']['worker.validate_state']
                if mutation in ('missing_query', 'late_query', 'third_query'):
                    for index, record in enumerate(profile['records'], 1):
                        record['request_id'] = index
                with self.assertRaises(ValueError):
                    s.validate_profile(profile, benchmark, 'b'*64)


class NativeStubServeProfileTests(unittest.TestCase):
    """Real serve/state/process_frame + authored runtime/FFI, never a native DLL."""
    def exercise(self, kind, mode):
        import contextlib
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name).resolve()/'authored.dll'
        path.write_bytes(b'authored; never executed')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        selected = dict(version=1, step_mode=mode)
        game_data = field_bytes(1, b'authored config')
        messages = [ipc.encode_message(ipc.CREATE, 1, -1, dict(state_projection=selected), game_data)]
        payload_lengths = []
        for request_id, query_mode in enumerate((mode, 'full'), 2):
            messages.append(ipc.encode_message(ipc.STATE, request_id, -1, dict(viewer=31, mode=query_mode)))
        for frame in range(3):
            payload = field_uint(1, frame) + field_uint(2, 20) + field_uint(3, 50)
            payload_lengths.append(len(payload))
            messages.append(ipc.encode_message(ipc.STEP, frame+4, frame, dict(dt_ms=50), payload))
        messages.append(ipc.encode_message(ipc.CLOSE, 7, 2))
        def initialize(runtime, path):
            runtime.path, runtime.world_count, runtime.frame = path, 0, -1
            runtime.logs = []
        def call(runtime, name, *args):
            if name == 'SimCreateWorld':
                ctypes.cast(args[2], ctypes.POINTER(ctypes.c_uint64)).contents.value = 1
            elif name == 'SimStep':
                runtime.frame += 1
            elif name == 'SimMakeSimFrame':
                raw, metadata = _build(4)
                raw = bytearray(raw)
                struct.pack_into('<I', raw, metadata['root_fields'][0], runtime.frame & 0xffffffff)
                runtime.raw = bytes(raw)
                ctypes.cast(args[2], ctypes.POINTER(ctypes.c_uint32)).contents.value = len(runtime.raw)
            elif name == 'SimGetSimFrameBuffer':
                ctypes.memmove(args[1], runtime.raw, len(runtime.raw))
        recorder, sink = p.Recorder(), io.BytesIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(native, '_runtime', None))
            stack.enter_context(patch.object(native._Runtime, '__init__', initialize))
            stack.enter_context(patch.object(native._Runtime, 'call', call))
            stack.enter_context(patch.object(native._Runtime, 'close', lambda runtime: None))
            stack.enter_context(patch.object(ipc, 'os', SimpleNamespace(name='nt', getpid=os.getpid)))
            stack.enter_context(patch.object(ctypes, 'CDLL', return_value=ProjectionLibrary()))
            with p.instrumentation(recorder):
                code = ipc.serve(io.BytesIO(b''.join(messages)), sink,
                    snapshot_decoder_library=path if kind == 'rust' else None,
                    snapshot_decoder_sha256=digest if kind == 'rust' else None)
        self.assertEqual(code, 0, sink.getvalue())
        self.assertEqual([row['operation'] for row in recorder.records], ['CREATE', 'STATE', 'STATE', 'STEP', 'STEP', 'STEP', 'CLOSE'])
        for row in recorder.records[1:-1]:
            metrics = row['metrics']
            self.assertEqual(metrics['worker.validate_state']['calls'], 1)
            if kind == 'rust':
                self.assertEqual(metrics['rust.validate']['calls'], 1)
                self.assertEqual(metrics['rust.ffi.decode']['calls'], 1)
                self.assertEqual(metrics['rust.decode']['calls'], 1)
            else:
                self.assertFalse(any(name.startswith('rust.') for name in metrics))
            leaves = s.leaf_categories(metrics)
            self.assertEqual(leaves['worker_state_validation'], metrics['worker.validate_state']['wall_ns'])
            self.assertLessEqual(sum(leaves.values()), row['active_wall_ns'])
        self.assertEqual(recorder.records[1]['state_query'], dict(viewer=31, mode=mode))
        self.assertEqual(recorder.records[2]['state_reply']['state_mode'], 'full')
        self.assertEqual(recorder.records[2]['state_reply']['state_frame'], 0xffffffff)
        # Feed the actual serve records into the strict summarizer as well.
        # Platform/path claims below are authored Windows protocol identities;
        # only the runtime and ctypes exports are stubbed in this test.
        _, report, rows = summary_fixtures.SummaryTests().fixture()
        hashes = p.source_hashes(rust_decoder=kind == 'rust')
        identity = dict(recorder.decoder_info) if kind == 'rust' else {'implementation': 'python'}
        if kind == 'rust':
            identity['library_path'] = 'C:\\authored\\decoder.dll'
        report.update(worker_pid=os.getpid(), snapshot_decoder=identity, source_at_start=hashes, source_at_finish=hashes,
            worker_profile_sha256='b'*64, state_projection=selected, state_projection_modes=list(recorder.state_projection_modes),
            worker_runtime=dict(platform='win32', os_name='nt', pointer_bits=64, implementation='cpython',
                                python_version='authored', executable='C:\\authored\\python.exe'))
        profile = dict(schema=1, completed=True, exit_code=code, failure=None, pid=os.getpid(), dropped_records=0,
            synthetic_test_backend=False, records=recorder.records, source_sha256=hashes, source_unchanged=True,
            snapshot_decoder=identity, snapshot_decoder_requested=dict(identity),
            snapshot_decoder_library_unchanged=True if kind == 'rust' else None,
            snapshot_decoder_projection_version=recorder.decoder_projection_version,
            rust_ffi_decode_exports=recorder.ffi_decode_exports,
            state_projection_requested=recorder.state_projection_requested, state_projection=recorder.state_projection,
            state_projection_modes=recorder.state_projection_modes,
            metric_parents=dict(s.RUST_METRIC_PARENTS) if kind == 'rust' else {})
        validated = s.validate_profile(profile, dict(report=report, rows=rows, payload_lengths=payload_lengths), 'b'*64)
        self.assertEqual(len(validated), 7)
        phases = s.summarize_phases(validated, rows)
        self.assertEqual(phases['combat']['operations']['STEP']['requests'], 1)

    def test_rust_full_and_ownership_and_python_explicit_paths_keep_disjoint_validation(self):
        for kind, mode in (('rust', 'full'), ('rust', 'ownership'), ('python', 'full'), ('python', 'ownership')):
            with self.subTest(kind=kind, mode=mode):
                self.exercise(kind, mode)


if __name__ == '__main__':
    unittest.main()
