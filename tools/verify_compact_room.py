"""Owned compact Room/fresh original-AI flow over private loopback TLS.

One ordinary solo2vAI search (30s), three original bots, 400 50ms frames,
ordinary human disconnect, abort/history durability and identity recovery.
This is scripted protocol evidence, not Unity UI, human acceptance or timing.
Default workers are native Windows; Linux requires all explicit Wine options.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import time
import traceback

from server.game_data import InputValidation, InputError, encode_player_input
from server.protobuf_wire import field_bytes, field_uint, field_packed_uint
from server.state_projection import validate_state
from server.worker_ai import AISetup
from server.worker_client import SimulationWorker
from tools import verify_hybrid_flows as flow
from tools import verify_rust_worker as binding

ROOT = flow.ROOT
require = flow.require


def sources():
    return {**binding.sources(), **flow.sources(), **{
        name: flow.file_hash(ROOT/name) for name in
        ('tools/verify_compact_room.py', 'tests/test_compact_room_verifier.py',
         'tests/test_tls_transport.py', 'rust/snapshot-decoder/src/main.rs')}}


def sha256_text(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def validate_args(args):
    wine_names = ('wine', 'windows_python', 'prefix_template')
    hybrid = any(getattr(args, name) is not None for name in wine_names)
    require(all(getattr(args, name) is not None for name in wine_names) if hybrid else args.cgroup_parent is None,
            'Wine requires wine/windows-python/prefix-template; cgroup requires Wine')
    require(sys.platform.startswith('linux') if hybrid else sys.platform == 'win32',
            'use native Windows or explicit Linux Wine; no fallback')
    require(sha256_text(args.library_sha256) and sha256_text(args.build_receipt_sha256),
            'explicit lowercase library and build receipt SHA256 required')
    require(math.isfinite(args.timeout) and 180 <= args.timeout <= 600, 'timeout outside180..600seconds')
    tls_names = ('tls_cert', 'tls_key', 'tls_ca')
    supplied = any(getattr(args, name) is not None for name in tls_names)
    require(not supplied or all(getattr(args, name) is not None for name in tls_names),
            'supply all TLS certificate/key/CA paths or generate private PKI')
    require(not os.path.lexists(args.output), 'fresh private output required')
    names = ('assets', 'library', 'build_receipt', 'output')+wine_names+tls_names+('cgroup_parent',)
    for name in names:
        path = getattr(args, name)
        if path is None:
            continue
        require(path.is_absolute() and not path.is_symlink(), f'{name}: absolute unredirected path required')
        setattr(args, name, path.resolve())
    local = (ROOT/'local').resolve()
    require(args.output != local and args.output.is_relative_to(local), 'new ignored local output required')
    for name in names:
        path = getattr(args, name)
        if path is None or name == 'output':
            continue
        require(not args.output.is_relative_to(path) and not path.is_relative_to(args.output),
                'output must be separate from inputs')
    args.play_frames, args.solo_team_only = 400, True
    return hybrid


def verify_build(args, source):
    raw = binding.read_file(args.build_receipt, binding.MAX_JSON)
    require(hashlib.sha256(raw).hexdigest() == args.build_receipt_sha256, 'build receipt hash differs')
    receipt = json.loads(raw)
    expected = {name: sha for name, sha in source.items()
                if name.startswith('rust/snapshot-decoder/') and (name.endswith('.rs') or name.endswith(('Cargo.toml', 'Cargo.lock')))}
    require(receipt.get('schema') == 1 and receipt.get('rust_sources') == expected,
            'build receipt Rust sources differ')
    build = receipt.get('build', {})
    require(type(build.get('exit_code')) is int and build['exit_code'] == 0
            and '--locked' in build.get('argv', []) and receipt.get('toolchain', {}).get('rustc')
            and receipt.get('toolchain', {}).get('cargo'), 'successful locked source-bound build required')
    artifacts = receipt.get('artifacts', {})
    artifact = artifacts.get('ba_snapshot_decoder.dll', {})
    require(artifact.get('sha256') == args.library_sha256
            and type(artifact.get('bytes')) is int and artifact['bytes'] == args.library.stat().st_size,
            'build artifact binding differs')
    require(flow.file_hash(args.library) == args.library_sha256, 'library hash differs')
    return dict(receipt_sha256=args.build_receipt_sha256, library_sha256=args.library_sha256,
                rust_sources=expected, build=build, toolchain=receipt['toolchain'],
                scope='hash-bound retained build receipt and exact current Rust sources; not reproducible-build proof')


def native_record(worker):
    if worker._backend_owner is not None:
        return flow.worker_record(worker)
    return dict(backend='native-windows', pid=worker.pid, native_windows_pid=worker.native_pid,
                runtime=worker.runtime_info, simulation_sha256=worker.dll_sha256,
                exit_code=worker.process.poll(), failure=worker.failure,
                stderr_thread_closed=not worker._stderr_thread.is_alive(),
                io_threads_closed=all(not thread.is_alive() for thread in worker._io._threads),
                job_closed=worker._job is not None and worker._job.handle is None,
                streams_closed=all(stream.closed for stream in
                    (worker.process.stdin, worker.process.stdout, worker.process.stderr)))


def require_native_cleanup(record):
    if record.get('backend') != 'native-windows':
        flow.require_cleanup(record, natural=True)
        return
    require(type(record['exit_code']) is int and record['exit_code'] == 0 and record['failure'] is None
            and all(record[key] is True for key in ('stderr_thread_closed', 'io_threads_closed',
                                                  'job_closed', 'streams_closed')),
            'native worker did not confirm ordinary CLOSE/process/job/thread cleanup')


class ObservedWorker:
    """Observe actual Room state consumption; never replace its validator/state."""
    def __init__(self, worker):
        self.worker, self.room = worker, None
        self.rows, self.expected_history = [], {}
        self.history_checks = 0

    def __getattr__(self, name):
        return getattr(self.worker, name)

    def observe(self, state, *, initial=False):
        validate_state(state, 31, 'ownership')
        require(state['frame'] == (0xffffffff if initial else len(self.rows)-1),
                'native compact initial/STEP frame differs')
        require(len(self.rows) < 2401, 'Room observation bound exceeded')
        for item in state['ownership']:
            self.expected_history[item['id']] = (item['army'], item['type'])
        self.rows.append(copy.deepcopy(state))

    def check_history(self, *, released=False):
        room = self.room
        require(room is not None and room.command_scheduling
                and ((room.sim is None and room.state == 'closed') if released else room.sim is self),
                'actual compact Room/scheduling binding missing')
        require(type(room.validation) is InputValidation and room.validation.entity_lookup == room.entity_history.get
                and room.command_scheduler.validation is room.validation,
                'ordinary Room command ownership validation is not active')
        require(room.entity_history == self.expected_history, 'Room cumulative entity history differs')
        self.history_checks += 1

    async def state(self, viewer=31, **kwargs):
        require(viewer == 31 and kwargs == {'mode': 'ownership'} and not self.rows,
                'Room must request explicit initial ownership STATE exactly once')
        state = await self.worker.state(viewer, **kwargs)
        self.observe(state, initial=True)
        return state

    async def process_frame(self, payload, *, dt_ms=50):
        self.check_history()
        require(dt_ms == 50 and self.state_mode == 'ownership', 'Room STEP mode/timestep changed')
        result = await self.worker.process_frame(payload, dt_ms=dt_ms)
        self.observe(result.state)
        return result


def command_controls(room):
    """Use the actual Room validator; rejected probes are never scheduled/native."""
    slot = 0
    choices = [(entity, kind, ability) for entity, (army, kind) in room.entity_history.items()
               if army == room.validation.players[slot].army_id
               and (not room.template.catalog[kind]['deck_slot_flags'] or kind in room.match.decks_by_slot[slot])
               for ability in room.template.entity_abilities.get(kind, ())]
    require(choices, 'no actual owned configured entity for command controls')
    entity, kind, ability = min(choices)
    unknown = next(value for value in range(0xffffffff, 0xfffff000, -1) if value not in room.entity_history)
    def body(entity_id):
        group = field_uint(1, kind)+field_uint(2, ability)+field_packed_uint(3, [entity_id])
        action = field_bytes(1, field_bytes(1, group)+field_bytes(3, field_bytes(1, b'')))
        return encode_player_input(room.match.identities_by_slot[slot], [action])
    valid = body(entity)
    require(room.validation.validate_player_input(slot, valid) == valid, 'actual owned command refused')
    try:
        room.validation.validate_player_input(slot, body(unknown))
    except InputError as error:
        require(str(error) == 'entity is not owned by this player/type', 'unknown command refused at wrong boundary')
    else:
        raise ValueError('actual Room validator accepted unknown entity')
    return dict(owned_command_accepted=True, unknown_entity_refused=True,
                scope='actual Room InputValidation probes only; no probe submitted to scheduler/native')


class Verification(flow.Verification):
    def make_backend(self):
        return super().make_backend() if self.args.wine is not None else None

    def worker_evidence(self, worker):
        return native_record(worker.worker)

    def require_worker_cleanup(self, worker):
        require_native_cleanup(self.worker_evidence(worker))

    async def factory(self, data, bots=None):
        require(not self.workers and bots is not None and set(bots) == {1, 2, 3},
                'only one actual solo2vAI original three-bot worker permitted')
        folder = self.args.output/'worker-0'
        folder.mkdir()
        native = await SimulationWorker.create(data, self.args.assets/'Simulation.dll', backend=self.backend,
            working_directory=folder, ai=AISetup(self.args.assets, bots), state_mode='ownership',
            snapshot_decoder_library=self.args.library, snapshot_decoder_sha256=self.args.library_sha256,
            startup_timeout=120, request_timeout=15, close_timeout=2)
        worker = ObservedWorker(native)
        self.workers.append(worker)  # Retain before any assertion so failed negotiation still closes.
        expected = dict(implementation='rust', abi_version=1, library_sha256=self.args.library_sha256,
                        library_path=(str(self.args.library) if self.backend is None else self.backend.translate_path(self.args.library)))
        require(not native._test_backend and native.state_mode == 'ownership' and native.projection_version == 1
                and native.state_projection_info == {'version': 1, 'step_mode': 'ownership'}
                and native.state_projection_modes == ['summary', 'full', 'ownership']
                and native.decoder_info == expected, 'actual CREATE compact decoder negotiation differs')
        require(native.runtime_info['os_name'] == 'nt' and native.runtime_info['pointer_bits'] == 64
                and native.dll_sha256 == flow.p.SIM_SHA
                and native.game_data_sha256 == hashlib.sha256(data).hexdigest()
                and native.ai_info == dict(bots=AISetup(self.args.assets, bots).wire()['bots'],
                    dll_sha256=flow.file_hash(self.args.assets/'aiprogram.dll'),
                    manifest_sha256=flow.file_hash(self.args.assets/'ai-rules.json')),
                'actual original-AI/native runtime identity differs')
        return worker

    async def public(self, mode, peers):
        require(mode == 5 and len(peers) == 1, 'only the bounded solo2vAI flow is allowed')
        room, preparation = await super().public(mode, peers)
        room.sim.room = room
        room.sim.check_history()  # Initial history/validator must exist before first player input.
        return room, preparation

    async def load(self, room, peers):
        await super().load(room, peers)
        # JoinArmy in frame0 creates the ordinary starting entities; the initial
        # pre-join native STATE may legitimately contain no owned entities.
        room.sim.check_history()
        self.command_control_results = command_controls(room)

    async def exercise(self):
        peer = await self.connect(dict(name='Compact Room Player', token='ba1_'+secrets.token_urlsafe(32)))
        await self.solo_team(peer)
        worker, = self.workers
        worker.check_history(released=True)
        require(len(worker.rows) == worker.frame+2 and worker.frame >= 400
                and worker.history_checks >= worker.frame+2, 'compact Room observation coverage incomplete')
        self.cases[0].update(state_mode=worker.state_mode, projection_version=worker.projection_version,
            snapshot_decoder=worker.decoder_info, initial_state=worker.rows[0], final_state=worker.rows[-1],
            observed_steps=len(worker.rows)-1, history_checks=worker.history_checks,
            command_controls=self.command_control_results)
        return 1, 0


async def run(args):
    validate_args(args)
    args.output.mkdir(parents=True, exist_ok=False)
    check = Verification(args)
    report = dict(passed=False, native_qualified=False, unity_client_qualified=False,
                  scope=__doc__, source_at_start=sources(), cases=check.cases,
                  real_search_seconds=flow.q.FALLBACK_SECONDS, coordinator_tick_seconds=flow.ds.TICK,
                  coordinator=dict(pid=os.getpid(), platform=sys.platform, executable=sys.executable, python=sys.version))
    pki = None
    try:
        require(flow.q.FALLBACK_SECONDS == 30 and flow.ds.TICK == .05, 'ordinary30s search/50ms tick changed')
        report['build_binding'] = verify_build(args, report['source_at_start'])
        flow.verify_assets(args.assets)
        report['asset_manifest_sha256'] = flow.file_hash(args.assets/'asset-manifest.json')
        if args.tls_cert is None:
            from tests.test_tls_transport import generate_test_pki
            pki = args.output/'ephemeral-pki'
            generated = generate_test_pki(pki)
            args.tls_cert, args.tls_key, args.tls_ca = (generated[key] for key in ('cert', 'key', 'ca'))
        report['tls'] = dict(cert_sha256=flow.file_hash(args.tls_cert), ca_sha256=flow.file_hash(args.tls_ca),
                             scope='explicit private CA pin, localhost verification, loopback port0 listeners')
        async with asyncio.timeout(args.timeout):
            await check.start()
            report['backend'] = 'native-windows' if check.backend is None else dict(
                wine=str(check.backend.wine_executable), wine_sha256=flow.file_hash(check.backend.wine_executable),
                windows_python=str(check.backend.windows_python), windows_python_sha256=flow.file_hash(check.backend.windows_python),
                prefix_template=str(check.backend.prefix_template), cgroup_parent=str(check.backend.cgroup_parent))
            await check.exercise()
            before = flow.read_history(check.dashboard.path)
            require(len(check.workers) == len(before) == 1 and before[0]['state'] == 'aborted', 'exactly one aborted Room required')
            await check.dashboard.close()
            check.dashboard = flow.Dashboard(check.server, args.output/'web-matches.json')
            check.web_address = await check.dashboard.start('127.0.0.1', 0)
            restored = await check.web_snapshot()
            require(flow.read_history(check.dashboard.path) == before and restored['history_total'] == 1
                    and restored['history'] == before, 'aborted history did not survive dashboard restart')
            require(not any(event['event'] == 'protocol_error' for event in check.events), 'unexpected protocol error')
            report.update(history_restart_preserved=True, passed=True, native_qualified=True)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        try:
            await check.close()
            for worker in check.workers:
                check.require_worker_cleanup(worker)
        except BaseException as error:
            report.update(passed=False, native_qualified=False, cleanup_error=repr(error))
        if pki is not None and pki.exists():
            try:
                from tests.test_tls_transport import remove_test_pki
                remove_test_pki(pki)
            except BaseException as error:
                report.update(passed=False, native_qualified=False, pki_cleanup_error=repr(error))
        report['workers'] = [check.worker_evidence(worker) for worker in check.workers]
        with (args.output/'states.jsonl').open('x', encoding='utf-8') as stream:
            for worker in check.workers:
                for state in worker.rows:
                    stream.write(json.dumps(state, sort_keys=True)+'\n')
        report['states_sha256'] = flow.file_hash(args.output/'states.jsonl')
        report['source_at_finish'] = sources()
        report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
        try:
            verify_build(args, report['source_at_finish'])
            flow.verify_assets(args.assets)
            require(report['asset_manifest_sha256'] == flow.file_hash(args.assets/'asset-manifest.json'), 'asset manifest changed')
            report['inputs_unchanged'] = True
        except BaseException as error:
            report.update(inputs_unchanged=False, input_recheck_error=repr(error))
        report['passed'] &= report['source_unchanged'] and report['inputs_unchanged']
        report['native_qualified'] &= report['passed']
        report['elapsed_seconds'] = time.monotonic()-check.started
        (args.output/'events.json').write_text(json.dumps(check.events, indent=2)+'\n', encoding='utf-8')
        report['events_sha256'] = flow.file_hash(args.output/'events.json')
        (args.output/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed', 'native_qualified', 'elapsed_seconds', 'error') if key in report}))
    return 0 if report['passed'] else 1


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'library', 'build-receipt', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('library-sha256', 'build-receipt-sha256'):
        parser.add_argument('--'+name, required=True)
    for name in ('wine', 'windows-python', 'prefix-template', 'cgroup-parent', 'tls-cert', 'tls-key', 'tls-ca'):
        parser.add_argument('--'+name, type=Path)
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args(argv)
    validate_args(args)
    return args


if __name__ == '__main__':
    raise SystemExit(asyncio.run(run(arguments())))
