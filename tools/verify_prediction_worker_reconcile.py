"""Owned headless qualification of the product worker checkpoint coordinator.

Default/--prepare-only copies and hashes source, native artifacts and the retained
1200-frame original combat reference. It loads no DLL and starts no process.
--run-prepared explicitly runs one suspended, retained-handle Job child. Three
sequential worlds exercise actual NativeSession.dispatch and original native
calls: canonical parity, then two divergent eight-frame movement corrections.
The final replay-head observer is verifier instrumentation, timed separately.
Parsed state/continuation parity does not establish all hidden native state,
Unity rendering, command admission, terminal draining or client prediction.
"""
from __future__ import annotations

import argparse
import ast
import ctypes as C
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORIGINAL_SHA = '107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb'
FRAME_COUNT, MAX_FRAME_BYTES, MAX_BUFFER = 1200, 2 * 1024 * 1024, 16 * 1024 * 1024
METRICS = struct.Struct('<iiiI8Q')
SOURCE_SEEDS = (
    'tools/verify_prediction_worker_reconcile.py', 'tools/verify_prediction_client_worker.py',
    'tools/verify_prediction_combat_fixture.py', 'tools/verify_movement_prediction.py',
    'client_patch/prediction_worker/native.py', 'client_patch/prediction_worker/checkpoint.py',
    'client_patch/prediction_worker/prediction.py', 'client_patch/prediction_worker/presentation.py',
)
NATIVE_SOURCES = (
    'client_patch/checkpoint/arena.cpp', 'client_patch/checkpoint/build.ps1',
    'client_patch/checkpoint/page_checkpoint.hpp', 'client_patch/checkpoint/thread_state.hpp',
    'client_patch/checkpoint/cooperative.cpp', 'client_patch/checkpoint/build-cooperative.ps1',
)


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def sha(path):
    return digest(Path(path).read_bytes())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def normalized(value):
    return json.loads(json.dumps(value, allow_nan=False))


def frame_number(raw):
    from client_patch.prediction_worker.prediction import frame_number as decode
    return decode(raw)


def read_journal(stream, *, count=FRAME_COUNT):
    frames = []
    for number in range(count):
        header = stream.read(4)
        require(len(header) == 4, 'truncated canonical journal length')
        size, = struct.unpack('<I', header)
        require(1 <= size <= MAX_FRAME_BYTES, 'canonical journal frame size outside bound')
        raw = stream.read(size)
        require(len(raw) == size, 'truncated canonical journal body')
        require(frame_number(raw) == number, 'canonical journal is not contiguous from0')
        frames.append(raw)
    require(stream.read(1) == b'', 'trailing canonical journal bytes')
    return frames


def decode_pair(code, data):
    require(code == 0 and len(data) >= 12, 'native MakeFrame failed/truncated')
    size, get_code, length = struct.unpack_from('<IiI', data)
    require(get_code == 0 and 8 <= size <= MAX_BUFFER and length == size and len(data) == 12 + size,
            'native Make/GetFrame result or byte count mismatch')
    return data[12:]


def decode_metrics(data):
    require(len(data) == METRICS.size, 'prediction metrics ABI length mismatch')
    confirmed, predicted, received, flags, *values = METRICS.unpack(data)
    require(flags & ~15 == 0, 'unknown prediction metrics flags')
    names = ('captures', 'restores', 'drops', 'corrections', 'replayed_frames',
             'matched_frames', 'peak_ahead', 'max_reconcile_us')
    return dict(zip(names, values), confirmed_frame=confirmed, predicted_frame=predicted,
                received_frame=received, prepared=bool(flags & 1), failed=bool(flags & 2),
                closed=bool(flags & 4), terminal_admitted=bool(flags & 8))


def compare_observation(actual, expected, frame):
    require(expected.get('frame') == frame and isinstance(actual.get('state'), dict) and
            actual['state'].get('frame') == frame,
            'observation/reference frame identity mismatch')
    for field in ('state', 'entity_states', 'ability_charges'):
        require(normalized(actual[field]) == normalized(expected[field]),
                'parsed ' + field + ' differs at frame' + str(frame))


def audit_enqueue(dispatch, snapshot, world, raws):
    before = snapshot()
    frames = []
    for raw in raws:
        code, data = dispatch(65, struct.pack('<Q', world) + raw)
        require(code == 0 and data == b'', 'authority control failed')
        frames.append(frame_number(raw))
    after = snapshot()
    require(before == after, 'authority enqueue performed native/checkpoint work')
    return dict(frames=frames, before=before, after=after)


def source_closure(root, seeds):
    """Resolve local AST imports, including relative/function-local imports."""
    root = Path(root)
    pending, found = list(seeds), set()

    def add_module(parts):
        for length in range(1, len(parts) + 1):
            package = Path(*parts[:length]) / '__init__.py'
            if (root / package).is_file():
                pending.append(package.as_posix())
        if parts:
            candidate = Path(*parts).with_suffix('.py')
            if (root / candidate).is_file():
                pending.append(candidate.as_posix())

    while pending:
        name = Path(pending.pop()).as_posix()
        if name in found:
            continue
        path = root / name
        require(path.is_file() and not path.is_symlink(), 'missing/nonregular source: ' + name)
        found.add(name)
        parts = list(Path(name).with_suffix('').parts)
        package = parts[:-1]
        add_module(package)
        if path.suffix != '.py':
            continue
        for node in ast.walk(ast.parse(path.read_bytes(), filename=name)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    add_module(alias.name.split('.'))
            elif isinstance(node, ast.ImportFrom):
                prefix = package[:len(package) - node.level + 1] if node.level else []
                base = prefix + (node.module.split('.') if node.module else [])
                add_module(base)
                for alias in node.names:
                    if alias.name != '*':
                        add_module(base + alias.name.split('.'))
    return sorted(found)


def snapshot_files(root, destination, names):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    manifest = {}
    total = 0
    for name in sorted(set(names)):
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'unsafe snapshot relative path')
        path = root / relative
        require(path.is_file() and not path.is_symlink(), 'snapshot input is not a regular file')
        total += path.stat().st_size
        require(len(manifest) < 4096 and total <= 512 * 1024 * 1024, 'snapshot exceeds file/byte budget')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(path.read_bytes())
        manifest[relative.as_posix()] = sha(target)
        require(sha(path) == manifest[relative.as_posix()], 'source changed during snapshot')
    return manifest


def verify_files(root, manifest):
    for name, expected in manifest.items():
        path = Path(root) / name
        require(path.is_file() and not path.is_symlink() and sha(path) == expected,
                'pinned file changed/missing: ' + str(path))


def read_reference(folder, frames):
    report = json.loads((folder / 'baseline/report.json').read_text(encoding='utf-8'))
    require(report.get('passed') is True and report.get('frame_count') == FRAME_COUNT and
            report.get('simulation_sha256') == ORIGINAL_SHA, 'retained original combat reference failed/identity mismatch')
    require(sha(folder / 'shared/bootstrap.pb') == report['bootstrap_sha256'] and
            sha(folder / 'shared/canonical-frames.bin') == report['canonical_journal_sha256'],
            'retained canonical/bootstrap hash mismatch')
    path = folder / 'baseline/states.jsonl'
    require(path.stat().st_size <= 128 * 1024 * 1024, 'reference observations exceed bound')
    rows = []
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream):
            require(number < len(frames) and len(line) <= 2 * 1024 * 1024, 'reference observation count/line limit')
            row = json.loads(line)
            require(row['frame'] == number and row['state']['frame'] == number and
                    row['input_sha256'] == digest(frames[number]) and row['state_sha256'] == digest(row['state']),
                    'reference row frame/input/state hash mismatch')
            require(not row['state']['game_state']['complete'], 'reference is outside nonterminal combat scope')
            for field in ('entity_states', 'ability_charges'):
                require(isinstance(row[field], dict), 'reference observation schema mismatch')
            rows.append(row)
    require(len(rows) == len(frames) == FRAME_COUNT, 'reference must cover all1200 frames')
    return rows


def validate_helper(path, *, arena):
    receipt_path = path.with_name('build.json')
    require(path.is_file() and path.stat().st_size <= 64 * 1024 * 1024 and
            receipt_path.stat().st_size <= 65536, 'helper/receipt exceeds bound')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
    require(receipt.get('experimental') is True and receipt.get('dll_sha256') == sha(path), 'helper build identity mismatch')
    checks = {'source_sha256': 'client_patch/checkpoint/arena.cpp' if arena else 'client_patch/checkpoint/cooperative.cpp'}
    if arena:
        require(path.name.casefold() == 'baheap.dll' and receipt.get('root_bindings_abi') == 1 and
                receipt.get('root_bindings_words') == 7, 'prediction requires root-guard helper09 ABI')
        checks.update(page_source_sha256='client_patch/checkpoint/page_checkpoint.hpp',
                      root_source_sha256='client_patch/checkpoint/thread_state.hpp',
                      build_script_sha256='client_patch/checkpoint/build.ps1')
    for key, name in checks.items():
        require(receipt.get(key) == sha(ROOT / name), 'helper receipt/source mismatch: ' + name)
    return receipt


def prepare(args):
    output = args.output.resolve()
    require(output.is_relative_to(ROOT / 'local') and not output.exists(), 'output must be a fresh repository local directory')
    require(30 <= args.timeout <= 180, 'owned runtime deadline must be30..180s')
    original, heap, coop = (Path(path).resolve(strict=True) for path in
                            (args.original_dll, args.heap_helper, args.cooperative))
    require(sha(original) == ORIGINAL_SHA, 'exact original Simulation.dll SHA required')
    heap_receipt, coop_receipt = validate_helper(heap, arena=True), validate_helper(coop, arena=False)
    baseline = args.baseline.resolve(strict=True)
    with (baseline / 'shared/canonical-frames.bin').open('rb') as stream:
        frames = read_journal(stream)
    read_reference(baseline, frames)
    assets = (args.assets or original.parent).resolve(strict=True)
    require(sha(assets / 'Simulation.dll') == ORIGINAL_SHA, 'asset copy has a different native DLL')
    from tools.verify_movement_prediction import fixture
    _, match, _ = fixture(assets)
    require(match.raw_game_data == (baseline / 'shared/bootstrap.pb').read_bytes(),
            'reconstructed fixture differs from retained bootstrap')
    interpreter = args.python.resolve(strict=True)
    output.mkdir(parents=True)
    (output / 'child').mkdir()
    sources = source_closure(ROOT, SOURCE_SEEDS) + list(NATIVE_SOURCES)
    source_manifest = snapshot_files(ROOT, output / 'source', sources)
    inputs = {}
    asset_names = [path.relative_to(assets).as_posix() for path in assets.rglob('*') if path.is_file()]
    require(not any(path.is_symlink() for path in assets.rglob('*')), 'asset tree contains a link')
    inputs['assets'] = snapshot_files(assets, output / 'inputs/assets', asset_names)
    reference_names = ('baseline/report.json', 'baseline/states.jsonl', 'shared/canonical-frames.bin', 'shared/bootstrap.pb')
    inputs['baseline'] = snapshot_files(baseline, output / 'inputs/baseline', reference_names)
    inputs['heap'] = snapshot_files(heap.parent, output / 'inputs/heap', (heap.name, 'build.json'))
    inputs['cooperative'] = snapshot_files(coop.parent, output / 'inputs/cooperative', (coop.name, 'build.json'))
    bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.verify_prediction_worker_reconcile',run_name='__main__')"
    command = [str(interpreter), '-I', '-S', '-B', '-u', '-c', bootstrap, str(output / 'source'),
               '--child', '--output', str(output)]
    invocation = dict(scope=__doc__, output=str(output), source_root=str(ROOT), source_sha256=source_manifest,
        input_sha256=inputs, input_origins=dict(assets=str(assets), baseline=str(baseline),
            heap=str(heap.parent), cooperative=str(coop.parent)),
        helper_receipts=dict(heap=heap_receipt, cooperative=coop_receipt),
        python=dict(path=str(interpreter), sha256=sha(interpreter)),
        heap_name=heap.name, cooperative_name=coop.name, command=command, timeout=args.timeout,
        native_executed=False, observations='all parsed state, sparse entity states, allied charge vectors; no hidden-state claim')
    write(output / 'invocation.json', invocation)
    verify_prepared(invocation)
    return invocation


def verify_prepared(invocation):
    output = Path(invocation['output'])
    verify_files(output / 'source', invocation['source_sha256'])
    verify_files(invocation['source_root'], invocation['source_sha256'])
    for group, manifest in invocation['input_sha256'].items():
        verify_files(output / 'inputs' / group, manifest)
        verify_files(invocation['input_origins'][group], manifest)
    require(sha(invocation['python']['path']) == invocation['python']['sha256'], 'Python interpreter changed')


class Coordinator:
    """Verifier observer around the unchanged product dispatcher; no fake world."""
    def __init__(self, session, output, reference):
        from client_patch.prediction_worker import wire
        self.session, self.output, self.reference, self.wire = session, output, reference, wire
        self.request_id, self.native_calls, self.phase = 0, 0, 'startup'
        self.frame, self.raw_streams, self.observations = -1, {}, {}
        self.last_process = None
        self.native_seconds, self.observer_seconds = 0.0, 0.0
        self.trace = (output / 'native-calls.jsonl').open('x', encoding='utf-8')
        self.original_call = session.api.call

        def counted(name, *args):
            row = dict(index=self.native_calls, phase=self.phase, frame=self.frame, name=name)
            if name == 'SimProcessMsg':
                raw = C.string_at(args[1], args[2])
                row.update(input_frame=frame_number(raw), input_sha256=digest(raw))
                self.last_process = dict(frame=row['input_frame'], sha256=row['input_sha256'])
            self.native_calls += 1
            started = time.perf_counter()
            try:
                result = self.original_call(name, *args)
                row['result'] = int(result)
                return result
            except BaseException as error:
                row['error'] = repr(error)
                raise
            finally:
                elapsed = time.perf_counter() - started
                self.native_seconds += elapsed
                row['seconds'] = elapsed
                self.trace.write(json.dumps(row, allow_nan=False) + '\n')
                if self.native_calls % 100 == 0:
                    self.trace.flush()

        session.api.call = counted

    def dispatch(self, opcode, body=b''):
        self.request_id += 1
        command = self.wire.decode_request(self.wire.Packet(opcode, self.request_id, body))
        result = self.session.dispatch(command)
        logs = self.session.drain_logs()
        if logs:
            with (self.output / 'native-logs.jsonl').open('a', encoding='utf-8') as stream:
                for kind, text in logs:
                    stream.write(json.dumps(dict(request=self.request_id, kind=kind,
                        text=text.decode('utf-8', errors='strict')), allow_nan=False) + '\n')
        return result

    def success(self, opcode, body=b''):
        code, data = self.dispatch(opcode, body)
        require(code == 0, 'native worker opcode' + str(opcode) + ' failed: ' + str(code))
        return data

    def metrics(self, world):
        result = decode_metrics(self.success(66, struct.pack('<Q', world)))
        require(not result['failed'] and not result['closed'] and not result['terminal_admitted'],
                'prediction became terminal/outside nonterminal reference scope')
        return result

    def snapshot(self, world):
        stats = self.metrics(world)
        return dict(native_calls=self.native_calls, **{name: stats[name] for name in ('captures', 'restores', 'drops')})

    def enqueue(self, world, raws):
        return audit_enqueue(self.dispatch, lambda: self.snapshot(world), world, raws)

    def create(self, bootstrap):
        raw = self.success(5, bootstrap)
        require(len(raw) == 8, 'CreateWorld returned invalid worker ID')
        world, = struct.unpack('<Q', raw)
        require(world > 0, 'CreateWorld returned null worker ID')
        # Warm the ordinary native view scratch before taking the initial full
        # checkpoint. BEGIN itself still precedes every native ProcessMsg/Step.
        for viewer in (31, 0, 1):
            decode_pair(*self.dispatch(9, struct.pack('<QII', world, viewer, 0)))
        self.success(64, struct.pack('<QII', world, 12, 16 * 1024 * 1024))
        require(self.metrics(world)['captures'] == 1, 'BEGIN did not prime the initial checkpoint')
        return world

    def process(self, world, raw):
        self.frame = frame_number(raw)
        self.success(7, struct.pack('<Q', world) + raw)

    def step(self, world):
        data = self.success(8, struct.pack('<QIi', world, 50, -1))
        require(len(data) == 4, 'Step time response ABI mismatch')
        return struct.unpack('<i', data)[0]

    def observe(self, world, frame, phase):
        from server.native_simulation import decode_snapshot
        from tools.verify_prediction_combat_fixture import entity_states
        from tools.verify_movement_prediction import decode_cooldowns
        started = time.perf_counter()
        raw = {viewer: decode_pair(*self.dispatch(9, struct.pack('<QII', world, viewer, 0)))
               for viewer in (31, 0, 1)}
        state = decode_snapshot(raw[31], 31, include_entities=True)
        state.pop('raw_sha256', None)
        result = normalized(dict(state=state, entity_states=entity_states(raw[31]),
            ability_charges={str(viewer): decode_cooldowns(raw[viewer]) for viewer in (0, 1)}))
        require(state['frame'] == frame, 'native observation has wrong physical frame')
        for viewer, body in raw.items():
            key = (phase, viewer)
            if key not in self.raw_streams:
                path = self.output / phase / ('view' + str(viewer) + '.bin')
                path.parent.mkdir(parents=True, exist_ok=True)
                self.raw_streams[key] = path.open('xb')
                self.raw_streams[key].write(b'BASNP001')
            self.raw_streams[key].write(struct.pack('<II', frame, len(body)) + body)
        if phase not in self.observations:
            self.observations[phase] = (self.output / phase / 'states.jsonl').open('x', encoding='utf-8')
        self.observations[phase].write(json.dumps(dict(frame=frame, **result,
            raw_sha256={str(viewer): digest(body) for viewer, body in raw.items()}),
            sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
        self.observer_seconds += time.perf_counter() - started
        return result

    def advance(self, world, raw, *, authority, observe=None):
        if authority:
            self.enqueue(world, [raw])
        self.process(world, raw)
        self.step(world)
        frame = frame_number(raw)
        if observe:
            result = self.observe(world, frame, observe)
            if authority:
                compare_observation(result, self.reference[frame], frame)
            return result
        return None

    def retire(self, world):
        prediction = self.session.predictions[world]
        adapter = self.session.prediction_adapters[world]
        before = self.metrics(world)
        self.success(6, struct.pack('<Q', world))
        after = prediction.metrics
        require(after['closed'] and after['cleanup_complete'] and not adapter.tokens and
                world not in self.session.worlds and world not in self.session.predictions,
                'world retirement retained native prediction/checkpoint ownership')
        guard = self.session.arena.healthy()
        require(guard['saved_bytes'] == 0, 'world retirement retained checkpoint pages')
        return dict(world=world, metrics_before=before, metrics_after=after, arena_after=guard,
                    cooperative=self.session.retired_cooperative.stats())

    def close_observers(self):
        errors = []
        self.session.api.call = self.original_call
        for stream in [self.trace, *self.raw_streams.values(), *self.observations.values()]:
            try:
                stream.close()
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError('verifier observation cleanup failed: ' + '; '.join(errors))


def choose_divergence(template, match, crab, reference, history):
    from tools.verify_prediction_combat_fixture import owned_crabs
    from tools.verify_movement_prediction import canonical_frame, move_action
    head = history + 7
    expected = {row['id']: row for row in owned_crabs(reference[head]['state'], crab, 0)
                if reference[head]['entity_states'].get(str(row['id'])) != 6}
    choices = [row for row in owned_crabs(reference[history - 1]['state'], crab, 0)
               if row['id'] in expected and reference[history - 1]['entity_states'].get(str(row['id'])) != 6]
    require(choices, 'divergence fixture has no confirmed living Crab across the tail')
    unit = min(choices, key=lambda row: row['id'])
    x, y, z = unit['position']
    future = expected[unit['id']]['position']
    dx, dz = x - future[0], z - future[2]
    length = math.hypot(dx, dz)
    dx, dz = (dx / length, dz / length) if length > .001 else (1.0, 0.0)
    target = [x + 24 * dx, y, z + 24 * dz]
    raw = canonical_frame(template, match, history, {0: [move_action(unit, target)]}, reference[history - 1]['state'])
    return raw, dict(entity=unit['id'], type=unit['type'], army=unit['army'], target=target)


def correction_case(coordinator, bootstrap, frames, reference, template, match, crab, history):
    c = coordinator
    head, prefix = history + 7, 'correction' + str(history)
    c.phase = prefix + '/prefix'
    world = c.create(bootstrap)
    initial_roots = c.session.arena.root_bindings()
    for raw in frames[:history]:
        c.advance(world, raw, authority=True)
    compare_observation(c.observe(world, history - 1, prefix + '/prefix_head'), reference[history - 1], history - 1)
    wrong, actor = choose_divergence(template, match, crab, reference, history)
    require(wrong != frames[history], 'divergence input unexpectedly equals canonical input')
    with (c.output / prefix / 'speculative-input.pb').open('xb') as stream:
        stream.write(wrong)
    c.phase = prefix + '/speculative'
    divergence, distance = [], 0.0
    for frame in range(history, head + 1):
        actual = c.advance(world, wrong if frame == history else frames[frame], authority=False,
                           observe=prefix + '/speculative')
        if actual != {key: reference[frame][key] for key in ('state', 'entity_states', 'ability_charges')}:
            divergence.append(frame)
        expected_unit = next((unit for unit in reference[frame]['state']['entities'] if unit['id'] == actor['entity']), None)
        actual_unit = next((unit for unit in actual['state']['entities'] if unit['id'] == actor['entity']), None)
        if expected_unit and actual_unit and 'position' in expected_unit and 'position' in actual_unit:
            distance = max(distance, math.dist(expected_unit['position'], actual_unit['position']))
    require(divergence and distance > .05, 'speculative tail failed to cause real movement divergence')
    before = c.metrics(world)
    require(before['confirmed_frame'] == history - 1 and before['predicted_frame'] == head,
            'speculative cursors do not describe the actual eight-frame tail')
    c.phase = prefix + '/authority_enqueue'
    # Include H+1 to prove the boundary forwards known authority instead of a
    # supplied speculative guess. None of these control requests may restore.
    enqueue = c.enqueue(world, frames[history:head + 2])
    before_query = c.metrics(world)
    still_wrong = c.observe(world, head, prefix + '/queued_unrepaired')
    require(still_wrong != {key: reference[head][key] for key in ('state', 'entity_states', 'ability_charges')},
            'authority enqueue or ordinary MakeFrame silently repaired the world')
    require(c.metrics(world) == before_query, 'MakeFrame mutated prediction coordinator state')

    adapter = c.session.prediction_adapters[world]
    original_replay = adapter.process_frame
    correction = dict(replay_seconds=0.0, head_observer_seconds=0.0, observed_head=False)

    def observed_replay(raw, dt):
        number = frame_number(raw)
        require(number == history + len(correction.get('replayed_frame_ids', [])) and raw == frames[number],
                'internal replay lost canonical input identity/order')
        started = time.perf_counter()
        original_replay(raw, dt)
        correction['replay_seconds'] += time.perf_counter() - started
        require(c.last_process == dict(frame=number, sha256=digest(raw)),
                'internal replay did not forward the canonical bytes to original ProcessMsg')
        correction.setdefault('replayed_frame_ids', []).append(number)
        if frame_number(raw) == head:
            started = time.perf_counter()
            result = c.observe(world, head, prefix + '/corrected_head')
            compare_observation(result, reference[head], head)
            correction['head_observer_seconds'] = time.perf_counter() - started
            correction['observed_head'] = True

    adapter.process_frame = observed_replay
    c.phase = prefix + '/boundary_repair'
    native_before = c.native_calls
    # A harmless but different valid next guess; authoritative H+1 is queued.
    next_guess, _ = choose_divergence(template, match, crab, reference, head + 1)
    require(next_guess != frames[head + 1], 'next-frame override control must differ from known authority')
    started = time.perf_counter()
    try:
        c.process(world, next_guess)
    finally:
        adapter.process_frame = original_replay
        correction['boundary_seconds_including_observer'] = time.perf_counter() - started
        correction['boundary_timer_scope'] = 'Actual ProcessMsg dispatch only, including replay-head observer; excludes fixture input construction.'
    after = c.metrics(world)
    require(correction['observed_head'] and after['restores'] - before['restores'] == 1 and
            after['corrections'] - before['corrections'] == 1 and
            after['replayed_frames'] - before['replayed_frames'] == 8 and
            after['confirmed_frame'] == head and after['predicted_frame'] == head and after['prepared'],
            'repair did not restore/replay exactly the intended tail at ProcessMsg boundary')
    require(c.session.prepared_prediction[world] == frames[head + 1], 'known next authority was not forwarded')
    require(c.last_process == dict(frame=head + 1, sha256=digest(frames[head + 1])),
            'original native ProcessMsg did not receive the known next authority')
    require(c.session.arena.root_bindings() == initial_roots, 'root bindings/revision changed during correction')
    correction.update(native_call_count=c.native_calls - native_before, metrics_before=before,
        metrics_after=after, root_bindings_before=initial_roots,
        root_bindings_after=c.session.arena.root_bindings(),
        timing_scope='replay includes original ProcessMsg/Step, Python dispatch and guard IPC; observer separate; not engine-only')
    c.phase = prefix + '/continuation'
    c.step(world)
    compare_observation(c.observe(world, head + 1, prefix + '/continuation'), reference[head + 1], head + 1)
    for frame in range(head + 2, head + 31):
        c.advance(world, frames[frame], authority=True, observe=prefix + '/continuation')
    retirement = c.retire(world)
    return dict(history=history, speculative_frames=8, divergence_frames=divergence,
        max_actor_position_delta=distance, actor=actor, speculative_input_sha256=digest(wrong),
        enqueue=enqueue, correction=correction,
        equal_corrected_heads=1, equal_continuation_frames=30, retirement=retirement)


def child(output):
    # Parent assigns the exact retained Popen handle to its kill-on-close Job
    # before resuming. Missing ownership acknowledgement MUST precede any load.
    require(sys.stdin.buffer.readline(32) == b'OWNED_JOB\n', 'missing retained Job ownership barrier')
    invocation = json.loads((output / 'invocation.json').read_text(encoding='utf-8'))
    report = dict(passed=False, scope=__doc__, pid=os.getpid(), native_executed=False,
                  errors=[], cases=[], lifecycle=[], root_bindings=[])
    folder = output / 'child'
    write(folder / 'report.json', report)
    session = coordinator = None
    started = time.perf_counter()
    try:
        verify_prepared(invocation)
        # Import all observer/parser utilities before the native owner starts.
        import threading
        from client_patch.prediction_worker.native import NativeSession
        from tools.verify_movement_prediction import fixture
        from tools.verify_prediction_combat_fixture import entity_states  # noqa: F401
        from server.native_simulation import decode_snapshot  # noqa: F401
        assets = output / 'inputs/assets'
        baseline = output / 'inputs/baseline'
        with (baseline / 'shared/canonical-frames.bin').open('rb') as stream:
            frames = read_journal(stream)
        reference = read_reference(baseline, frames)
        template, match, crab = fixture(assets)
        bootstrap = (baseline / 'shared/bootstrap.pb').read_bytes()
        require(match.raw_game_data == bootstrap, 'reconstructed fixture differs from retained bootstrap')
        report['python_threads_before'] = threading.active_count()
        require(report['python_threads_before'] == 1, 'native proof requires a sole Python owner thread')
        report['native_executed'] = True
        write(folder / 'report.json', report)
        session = NativeSession.open(original_dll=assets / 'Simulation.dll',
            heap_helper=output / 'inputs/heap' / invocation['heap_name'],
            cooperative=output / 'inputs/cooperative' / invocation['cooperative_name'],
            data_dir=folder / 'native-data')
        report['provenance'] = session.provenance
        report['arena_before'] = session.arena.healthy()
        report['root_bindings'].append(dict(phase='opened', token=session.arena.root_bindings()))
        coordinator = Coordinator(session, folder, reference)
        c = coordinator
        c.success(3, b'\x01')
        c.success(4, struct.pack('<I', 0))
        c.success(1, b'\x00')
        c.phase = 'canonical'
        world = c.create(bootstrap)
        roots = session.arena.root_bindings()
        report['root_bindings'].append(dict(phase='canonical_begin', token=roots))
        canonical_started = time.perf_counter()
        for frame, raw in enumerate(frames):
            c.advance(world, raw, authority=True, observe='canonical')
            metrics = c.metrics(world)
            require(metrics['confirmed_frame'] == metrics['predicted_frame'] == metrics['received_frame'] == frame
                    and metrics['restores'] == metrics['corrections'] == 0,
                    'canonical authority path diverged from its expected cursors')
            if frame % 100 == 0:
                write(folder / 'progress.json', dict(phase='canonical', frame=frame,
                    elapsed_seconds=time.perf_counter() - started, metrics=metrics))
        report['canonical'] = dict(equal_frames=FRAME_COUNT,
            elapsed_seconds=time.perf_counter() - canonical_started, final_metrics=c.metrics(world))
        require(session.arena.root_bindings() == roots, 'canonical run changed native roots/revision')
        report['lifecycle'].append(c.retire(world))
        write(folder / 'report.json', report)
        for history in (500, 740):
            write(folder / 'progress.json', dict(phase='correction', history=history))
            case = correction_case(c, bootstrap, frames, reference, template, match, crab, history)
            report['cases'].append(case)
            report['lifecycle'].append(case['retirement'])
            report['root_bindings'].append(dict(phase='after_correction' + str(history), token=session.arena.root_bindings()))
            write(folder / 'report.json', report)
        require(len(report['lifecycle']) == 3 and len({row['world'] for row in report['lifecycle']}) == 3,
                'sequential rematches did not use three distinct worker world identities')
        report['native_calls'] = c.native_calls
        report['native_export_seconds'] = c.native_seconds
        report['observer_seconds'] = c.observer_seconds
        report['root_bindings'].append(dict(phase='before_close', token=session.arena.root_bindings()))
        require(all(row['token'] == report['root_bindings'][0]['token'] for row in report['root_bindings']),
                'native root bindings/revision changed across sequential worlds')
    except BaseException as error:
        report['errors'].append(dict(phase='proof', error=repr(error), traceback=traceback.format_exc()))
    finally:
        if session is not None:
            try:
                session.close()
                report['session_closed'] = True
            except BaseException as error:
                report['errors'].append(dict(phase='native_cleanup', error=repr(error), traceback=traceback.format_exc()))
            try:
                report['arena_after_close'] = session.arena.healthy()
                report['root_bindings'].append(dict(phase='after_close', token=session.arena.root_bindings()))
                require(report['arena_after_close']['saved_bytes'] == 0 and not session.worlds and
                        not session.predictions and not session.prediction_adapters and not session.prepared_prediction,
                        'native cleanup retained worlds/checkpoint pages')
                require(report['root_bindings'][-1]['token'] == report['root_bindings'][0]['token'],
                        'native cleanup changed root bindings/revision')
                report['native_log_tail'] = [dict(kind=kind, text=text.decode('utf-8', errors='strict'))
                                             for kind, text in session.drain_logs()]
            except BaseException as error:
                report['errors'].append(dict(phase='guard_cleanup', error=repr(error), traceback=traceback.format_exc()))
        if coordinator is not None:
            report['native_calls_including_cleanup'] = coordinator.native_calls
            report['native_export_seconds_including_cleanup'] = coordinator.native_seconds
            try:
                coordinator.close_observers()
            except BaseException as error:
                report['errors'].append(dict(phase='observer_cleanup', error=repr(error)))
        try:
            verify_prepared(invocation)
            report['pinned_inputs_unchanged'] = True
            import threading
            report['python_threads_after'] = threading.active_count()
            require(report.get('python_threads_before') == report['python_threads_after'] == 1,
                    'native proof introduced additional Python threads')
        except BaseException as error:
            report['errors'].append(dict(phase='identity_cleanup', error=repr(error)))
        report['elapsed_seconds'] = time.perf_counter() - started
        report['passed'] = bool(not report['errors'] and report.get('session_closed') and
            report.get('canonical', {}).get('equal_frames') == FRAME_COUNT and len(report['cases']) == 2 and
            all(case['equal_corrected_heads'] == 1 and case['equal_continuation_frames'] == 30 for case in report['cases']))
        raw_paths = sorted(folder.rglob('view*.bin')) + sorted(folder.rglob('states.jsonl'))
        report['raw_observation_sha256'] = {path.relative_to(folder).as_posix(): sha(path) for path in raw_paths}
        write(folder / 'report.json', report)
    return 0 if report['passed'] else 1


def job_attribution(job):
    total = job.get('total') if isinstance(job, dict) else None
    valid = type(total) is int and total >= 1
    return dict(retained_child_processes=1, total_accounted_processes=total,
        unattributed_extra_processes=total - 1 if valid else None,
        attribution='unattributed',
        scope='Cumulative Job accounting; extra process identities/roles were not captured.')


def parent_accepts(report):
    """Lifecycle acceptance does not infer an exact cumulative process count."""
    job = report.get('job_before_close')
    valid_job = (isinstance(job, dict) and all(type(job.get(key)) is int for key in ('total', 'active', 'terminated'))
                 and job['total'] >= 1 and job['active'] == job['terminated'] == 0)
    return bool(valid_job and report.get('errors') == [] and report.get('forced_cleanup') is False and
        all(report.get(key) is True for key in ('reaped', 'retained_handle_closed',
                                               'assigned_before_resume', 'pinned_inputs_unchanged')) and
        type(report.get('exit_code')) is int and report['exit_code'] == 0 and
        isinstance(report.get('child'), dict) and report['child'].get('passed') is True)


def run_prepared(output):
    from tools.verify_prediction_client_worker import RetainedJob, CREATE_SUSPENDED
    invocation = json.loads((output / 'invocation.json').read_text(encoding='utf-8'))
    verify_prepared(invocation)
    require(not (output / 'verification.json').exists() and not (output / 'child/report.json').exists(),
            'prepared native proof has already been attempted')
    report = dict(passed=False, scope=__doc__, command=invocation['command'],
                  invocation_sha256=sha(output / 'invocation.json'), forced_cleanup=False, errors=[])
    process = job = None
    started = time.perf_counter()
    try:
        require(os.name == 'nt', 'owned native proof requires Windows')
        with (output / 'child-stdout.log').open('xb') as stdout, (output / 'child-stderr.log').open('xb') as stderr:
            process = subprocess.Popen(invocation['command'], cwd=output / 'child', stdin=subprocess.PIPE,
                stdout=stdout, stderr=stderr, close_fds=True,
                creationflags=CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW)
            report['pid'] = process.pid
            job = RetainedJob(process)
            report['assigned_before_resume'] = True
            ntdll = C.WinDLL('ntdll', use_last_error=True)
            ntdll.NtResumeProcess.argtypes, ntdll.NtResumeProcess.restype = [C.c_void_p], C.c_long
            require(ntdll.NtResumeProcess(C.c_void_p(int(process._handle))) == 0, 'retained owned child resume failed')
            process.stdin.write(b'OWNED_JOB\n')
            process.stdin.flush()
            process.stdin.close()
            write(output / 'process.json', report)
            deadline = started + invocation['timeout'] - 5
            while process.poll() is None:
                remaining = deadline - time.perf_counter()
                require(remaining > 0, 'owned native proof runtime deadline exceeded')
                try:
                    process.wait(timeout=min(5, remaining))
                except subprocess.TimeoutExpired:
                    pass
            report['exit_code'] = process.returncode
            report['child'] = json.loads((output / 'child/report.json').read_text(encoding='utf-8'))
            require(process.returncode == 0 and report['child'].get('passed') is True,
                    'owned native reconcile proof child failed')
            for name, expected in report['child']['raw_observation_sha256'].items():
                require(sha(output / 'child' / name) == expected, 'raw observation changed after child report')
            report['passed'] = True
    except BaseException as error:
        report['errors'].append(dict(phase='run', error=repr(error), traceback=traceback.format_exc()))
    finally:
        if process is not None:
            if process.poll() is None:
                report['forced_cleanup'] = True
                try:
                    if job:
                        job.terminate_owned()
                    else:
                        process.terminate()  # Only this exact retained, suspended child.
                except BaseException as error:
                    report['errors'].append(dict(phase='terminate', error=repr(error)))
            try:
                process.wait(timeout=5)
                report['reaped'] = True
            except BaseException as error:
                report['errors'].append(dict(phase='reap', error=repr(error)))
                report['reaped'] = False
            report['exit_code'] = process.poll()
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        if job:
            try:
                report['job_before_close'] = job.accounting()
            except BaseException as error:
                report['errors'].append(dict(phase='job_accounting', error=repr(error)))
            try:
                job.close()
            except BaseException as error:
                report['errors'].append(dict(phase='job_close', error=repr(error)))
        if process is not None:
            try:
                process._handle.Close()
                report['retained_handle_closed'] = True
            except BaseException as error:
                report['errors'].append(dict(phase='handle_close', error=repr(error)))
        try:
            verify_prepared(invocation)
            report['pinned_inputs_unchanged'] = True
        except BaseException as error:
            report['errors'].append(dict(phase='identity_cleanup', error=repr(error)))
        report['elapsed_seconds'] = time.perf_counter() - started
        report['job_process_attribution'] = job_attribution(report.get('job_before_close'))
        report['passed'] = parent_accepts(report)
        write(output / 'verification.json', report)
    return report


def read_saved_observations(folder, phase, frame_ids):
    """File-only independent parse of retained view bytes and decoded records."""
    from server.native_simulation import decode_snapshot
    from tools.verify_prediction_combat_fixture import entity_states
    from tools.verify_movement_prediction import decode_cooldowns
    frame_ids = list(frame_ids)
    path = folder / phase / 'states.jsonl'
    require(path.stat().st_size <= 128 * 1024 * 1024, 'saved states exceed bound')
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    require([row['frame'] for row in rows] == frame_ids, 'saved state sequence differs: ' + phase)
    views = {}
    for viewer in (31, 0, 1):
        values = []
        with (folder / phase / ('view' + str(viewer) + '.bin')).open('rb') as stream:
            require(stream.read(8) == b'BASNP001', 'saved view magic mismatch')
            for number, row in zip(frame_ids, rows):
                header = stream.read(8)
                require(len(header) == 8, 'truncated saved view header')
                frame, size = struct.unpack('<II', header)
                require(frame == number and 8 <= size <= MAX_BUFFER, 'saved view frame/size mismatch')
                raw = stream.read(size)
                require(len(raw) == size and digest(raw) == row['raw_sha256'][str(viewer)], 'saved view bytes/hash mismatch')
                values.append(raw)
            require(stream.read(1) == b'', 'trailing saved view bytes')
        views[viewer] = values
    for index, row in enumerate(rows):
        state = decode_snapshot(views[31][index], 31, include_entities=True)
        state.pop('raw_sha256', None)
        parsed = normalized(dict(state=state, entity_states=entity_states(views[31][index]),
            ability_charges={str(viewer): decode_cooldowns(views[viewer][index]) for viewer in (0, 1)}))
        compare_observation(parsed, row, row['frame'])
    return rows


def reanalyze(output):
    """Re-evaluate existing evidence only; never launch or load a native DLL."""
    output = Path(output).resolve()
    destination = output / 'reanalysis01.json'
    require(not destination.exists(), 'preserve the previous file-only reanalysis')
    result = dict(passed=False, native_executed=False, new_native_execution=False,
        scope='File-only reanalysis of a retained owned headless worker run: parsed original-native combat views, '
              'checkpoint correction/continuation, roots/guards and cleanup. No Unity rendering, hidden-state '
              'equality, command-admission or extra Job-process attribution claim.', errors=[])
    try:
        invocation = json.loads((output / 'invocation.json').read_text(encoding='utf-8'))
        parent = json.loads((output / 'verification.json').read_text(encoding='utf-8'))
        child_report = json.loads((output / 'child/report.json').read_text(encoding='utf-8'))
        result['receipts'] = {name: sha(output / name) for name in
                              ('invocation.json', 'verification.json', 'child/report.json')}
        result['reanalyzer_sha256'] = sha(Path(__file__))
        result['archived_verifier_sha256'] = invocation['source_sha256']['tools/verify_prediction_worker_reconcile.py']
        require(parent['invocation_sha256'] == result['receipts']['invocation.json'] and
                parent['command'] == invocation['command'] and parent['child'] == child_report and
                parent['pid'] == child_report['pid'] and parent['scope'] == child_report['scope'] == invocation['scope'],
                'saved parent/child/invocation binding mismatch')
        verify_files(output / 'source', invocation['source_sha256'])
        for group, manifest in invocation['input_sha256'].items():
            verify_files(output / 'inputs' / group, manifest)
            verify_files(invocation['input_origins'][group], manifest)
        require(sha(invocation['python']['path']) == invocation['python']['sha256'], 'pinned Python changed')
        # The file parsers used below are the exact unchanged runtime parsers.
        parsers = ('server/native_simulation.py', 'server/protobuf_wire.py',
                   'tools/verify_prediction_combat_fixture.py', 'tools/verify_movement_prediction.py')
        verify_files(ROOT, {name: invocation['source_sha256'][name] for name in parsers})
        for group, name, source in (('heap', invocation['heap_name'], 'client_patch/checkpoint/arena.cpp'),
                                    ('cooperative', invocation['cooperative_name'], 'client_patch/checkpoint/cooperative.cpp')):
            receipt = json.loads((output / 'inputs' / group / 'build.json').read_text(encoding='utf-8-sig'))
            require(receipt == invocation['helper_receipts'][group] and
                    receipt['dll_sha256'] == sha(output / 'inputs' / group / name) and
                    receipt['source_sha256'] == invocation['source_sha256'][source], 'helper/source receipt mismatch')
        heap = invocation['helper_receipts']['heap']
        for key, name in (('page_source_sha256', 'page_checkpoint.hpp'), ('root_source_sha256', 'thread_state.hpp'),
                          ('build_script_sha256', 'build.ps1')):
            require(heap[key] == invocation['source_sha256']['client_patch/checkpoint/' + name], 'heap header/build receipt mismatch')
        require(heap['baseline_forget_abi'] == 1 and heap['page_storage_abi'] == 2, 'run did not use qualified retired per-page storage')
        result['heap_sha256'] = heap['dll_sha256']
        result['original_parent_passed'] = parent['passed']
        result['job_before_close'] = parent['job_before_close']
        result['job_process_attribution'] = job_attribution(parent['job_before_close'])
        require(parent_accepts(parent), 'retained parent lifecycle gates failed')
        require(child_report['errors'] == [] and child_report['native_executed'] is True and
                child_report['session_closed'] is True and child_report['pinned_inputs_unchanged'] is True and
                child_report['python_threads_before'] == child_report['python_threads_after'] == 1,
                'retained child lifecycle/owner gates failed')
        for name, expected in child_report['raw_observation_sha256'].items():
            verify_files(output / 'child', {name: expected})
        baseline = output / 'inputs/baseline'
        with (baseline / 'shared/canonical-frames.bin').open('rb') as stream:
            frames = read_journal(stream)
        reference = read_reference(baseline, frames)
        require(child_report['canonical']['equal_frames'] == FRAME_COUNT, 'canonical report omitted reference frames')
        canonical = read_saved_observations(output / 'child', 'canonical', range(FRAME_COUNT))
        for row, expected in zip(canonical, reference):
            compare_observation(row, expected, expected['frame'])
        require(len(child_report['cases']) == 2 and [case['history'] for case in child_report['cases']] == [500, 740],
                'retained correction cases differ from the approved fixture')
        summaries = []
        for case in child_report['cases']:
            history, head = case['history'], case['history'] + 7
            prefix = 'correction' + str(history)
            for phase, ids in (('prefix_head', [history - 1]), ('corrected_head', [head]),
                                ('continuation', range(head + 1, head + 31))):
                rows = read_saved_observations(output / 'child', prefix + '/' + phase, ids)
                for row in rows:
                    compare_observation(row, reference[row['frame']], row['frame'])
            speculative = read_saved_observations(output / 'child', prefix + '/speculative', range(history, head + 1))
            queued = read_saved_observations(output / 'child', prefix + '/queued_unrepaired', [head])[0]
            fields = ('state', 'entity_states', 'ability_charges')
            require(all(queued[key] == speculative[-1][key] for key in fields) and
                    any(queued[key] != reference[head][key] for key in fields), 'queued authority repaired before ProcessMsg boundary')
            distance = 0.0
            for row in speculative:
                number = row['frame']
                actual_actor = next((unit for unit in row['state']['entities'] if unit['id'] == case['actor']['entity']), None)
                expected_actor = next((unit for unit in reference[number]['state']['entities'] if unit['id'] == case['actor']['entity']), None)
                if actual_actor and expected_actor and 'position' in actual_actor and 'position' in expected_actor:
                    distance = max(distance, math.dist(actual_actor['position'], expected_actor['position']))
            require(distance > .05 and case['speculative_frames'] == 8 and case['equal_corrected_heads'] == 1 and
                    case['equal_continuation_frames'] == 30, 'real movement divergence/correction coverage missing')
            enqueue = case['enqueue']
            require(enqueue['frames'] == list(range(history, head + 2)) and enqueue['before'] == enqueue['after'],
                    'authority enqueue performed native/checkpoint work')
            correction = case['correction']
            before, after = correction['metrics_before'], correction['metrics_after']
            require(correction['observed_head'] and correction['replayed_frame_ids'] == list(range(history, head + 1)) and
                    after['restores'] - before['restores'] == after['corrections'] - before['corrections'] == 1 and
                    after['replayed_frames'] - before['replayed_frames'] == 8 and
                    correction['root_bindings_before'] == correction['root_bindings_after'], 'retained repair disposition mismatch')
            require(sha(output / 'child' / prefix / 'speculative-input.pb') == case['speculative_input_sha256'],
                    'speculative command input changed')
            summaries.append(dict(history=history, restored_head=head, speculative_frames=8,
                max_actor_position_delta=distance, corrected_heads_equal=1, continuation_frames_equal=30,
                internal_reconcile_max_ms=after['max_reconcile_us'] / 1000,
                outer_verifier_trigger_ms=1000 * correction['boundary_seconds_including_observer'],
                outer_verifier_trigger_scope=correction.get('boundary_timer_scope',
                    'Legacy verifier timer includes next-guess construction/validation plus ProcessMsg dispatch and head observer.'),
                head_observer_ms=1000 * correction['head_observer_seconds'],
                replay_dispatch_ms=1000 * correction['replay_seconds']))
        lifecycle = child_report['lifecycle']
        require(len(lifecycle) == 3 and len({row['world'] for row in lifecycle}) == 3, 'sequential world identities missing')
        for row in lifecycle:
            require(row['metrics_after']['closed'] and row['metrics_after']['cleanup_complete'] and
                    row['arena_after']['saved_bytes'] == 0, 'retained world cleanup failed')
        guards = [row['arena_after'] for row in lifecycle] + [child_report['arena_before'], child_report['arena_after_close']]
        require(all(stats['version'] == 2 and all(stats[key] == 0 for key in ('error', 'unknown', 'foreign_threads')) for stats in guards)
                and child_report['arena_after_close']['saved_bytes'] == 0, 'retained heap/root guards failed')
        roots = child_report['root_bindings']
        token = roots[0]['token']
        require(len(token) == 8 and token[0] and all(token[4:7]) and token[7] == 0 and
                all(row['token'] == token for row in roots), 'native roots/sticky revision changed')
        trace_path = output / 'child/native-calls.jsonl'
        require(trace_path.stat().st_size <= 64 * 1024 * 1024, 'native call trace exceeds bound')
        trace = [json.loads(line) for line in trace_path.read_text(encoding='utf-8').splitlines()]
        require(len(trace) == child_report['native_calls_including_cleanup'] and
                all(row['index'] == index and row.get('result') == 0 and 'error' not in row for index, row in enumerate(trace)),
                'original native API trace failed/truncated')
        for phase, ids in [('canonical', range(FRAME_COUNT))] + [
                ('correction' + str(history) + '/boundary_repair', range(history, history + 9)) for history in (500, 740)]:
            messages = [row for row in trace if row['phase'] == phase and row['name'] == 'SimProcessMsg']
            require([row['input_frame'] for row in messages] == list(ids) and
                    all(row['input_sha256'] == digest(frames[row['input_frame']]) for row in messages),
                    'original ProcessMsg canonical order/identity mismatch')
        result.update(passed=True, equal_canonical_frames=FRAME_COUNT, cases=summaries,
            retired_worlds=3, saved_payload_after_each_retirement=[row['arena_after']['saved_bytes'] for row in lifecycle],
            root_bindings=token, guard_errors=0, unknown_allocations=0, foreign_threads=0,
            native_trace_sha256=sha(trace_path), raw_observation_receipts=child_report['raw_observation_sha256'],
            initial_checkpoint_scope='Helper10 per-page payload ownership and explicit retirement were exercised by three loading-time initial captures; no isolated initial-capture cost claim.',
            timing_scope='Correction boundary includes the verifier-only replay-head observer. Replay dispatch includes Python/original native calls/guards, not engine-only cost.',
            acceptance_change='Permit cumulative Job total>=1 while still requiring active=0,terminated=0, no force, exit0, reaped/closed retained handle and all other gates. Extra identities remain unattributed.')
    except BaseException as error:
        result['errors'].append(dict(error=repr(error), traceback=traceback.format_exc()))
        result['passed'] = False
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--original-dll', type=Path)
    parser.add_argument('--heap-helper', type=Path)
    parser.add_argument('--cooperative', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--timeout', type=float, default=120)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--run-prepared', action='store_true')
    mode.add_argument('--reanalyze', action='store_true')
    mode.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return child(args.output.resolve())
    if args.reanalyze:
        result = reanalyze(args.output)
        print(json.dumps(dict(passed=result['passed'], native_executed=False,
                              report=str(args.output / 'reanalysis01.json'))))
        return 0 if result['passed'] else 1
    if args.run_prepared:
        result = run_prepared(args.output.resolve())
        print(json.dumps(dict(passed=result['passed'], report=str(args.output / 'verification.json'))))
        return 0 if result['passed'] else 1
    if any(value is None for value in (args.original_dll, args.heap_helper, args.cooperative, args.baseline)):
        parser.error('--original-dll, --heap-helper, --cooperative and --baseline are required for preparation')
    invocation = prepare(args)
    print(json.dumps(dict(prepared=True, native_executed=False, output=invocation['output'], command=invocation['command'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
