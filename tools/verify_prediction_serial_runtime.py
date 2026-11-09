"""Owned headless threaded/zero-pool parity, with no live or graphical client.

The serial child changes the guarded world-pool immediate in its own mapped
original Simulation.dll before SimInit. With --cooperative, three additional
guarded wait sites can pump original queued tasks. No Submit reordering occurs.
Equality covers decoded native observables, not every hidden native field.
"""
from __future__ import annotations

import argparse
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
import ctypes as C
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.native_simulation import NativeSimulation
from server.protobuf_wire import field_bytes
from server.worker_client import _WindowsJob
from tools.prediction_native import Cooperative, own_thread_ids, preload_original, prepare_serial
from tools.owned_native_context import capture_native_context
from tools.verify_movement_prediction import (canonical_frame, execute, fixture,
    move_action, opening_actions, targets)

SOURCE_FILES = ('tools/verify_prediction_serial_runtime.py', 'tools/prediction_native.py',
                'tools/owned_native_context.py',
                'client_patch/checkpoint/cooperative.cpp','client_patch/checkpoint/build-cooperative.ps1',
                'tools/verify_movement_prediction.py', 'server/native_simulation.py',
                'server/game_data.py', 'server/protobuf_wire.py', 'server/worker_client.py')


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def source_hashes():
    return {name: digest((ROOT / name).read_bytes()) for name in SOURCE_FILES}


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def parsed_state(world):
    state = world.state(31, include_entities=True)
    return {key: value for key, value in state.items() if key != 'raw_sha256'}


def owned_crabs(state, crab):
    return [row for row in state['entities'] if row.get('army') == 0 and row.get('type') == crab]


def fixture_actions(template, match, frame, state, crab, initial_targets):
    result = opening_actions(template, match, frame, state)
    if frame == 360:
        builders = [(entity, ability) for entity in state['entities'] if entity.get('army') == 0
                    for ability in template.entity_abilities.get(entity.get('type'), ())
                    if template.build_ability_slots.get(ability) == 0]
        require(builders, 'no original HQ build action for the second ordinary Crab')
        builder, ability = min(builders, key=lambda pair: (pair[0]['id'], pair[1]))
        result[0].append(execute(builder, ability, field_bytes(1, b'')))
    if frame in (240, 248, 440, 480, 540):
        units = owned_crabs(state, crab)
        require(units, 'no ordinary-built original Crab for Move12')
        for unit in units:
            if unit['id'] not in initial_targets:
                initial_targets[unit['id']] = targets(unit)
            wrong, right = initial_targets[unit['id']]
            target = wrong if frame in (240, 440, 540) else right
            result[0].append(move_action(unit, target))
    return result


def journal(path):
    data, offset, result = path.read_bytes(), 0, []
    while offset < len(data):
        require(offset + 4 <= len(data), 'truncated canonical journal length')
        size, = struct.unpack_from('<I', data, offset)
        offset += 4
        require(0 < size <= 2 * 1024 * 1024 and offset + size <= len(data), 'invalid canonical journal body')
        result.append(data[offset:offset + size])
        offset += size
    return result


def child(args):
    output, shared = args.output.resolve(), args.shared.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT / 'local') and output.is_dir(), 'owned local Windows evidence required')
    os.chdir(output)
    report = dict(passed=False, mode=args.child, pid=os.getpid(), source_sha256_at_start=source_hashes(),
                  scope=__doc__, thread_ids={'before_load': own_thread_ids()})
    started, world = time.perf_counter(), None
    retained = cooperative = None
    current_frame = -1
    kernel = C.WinDLL('kernel32')
    kernel.GetCurrentThreadId.argtypes, kernel.GetCurrentThreadId.restype = [], C.c_ulong
    def progress(phase, **fields):
        write(output/'progress.json', dict(phase=phase, frame=current_frame,
            native_thread_id=kernel.GetCurrentThreadId(), pid=os.getpid(),
            module_base=hex(retained._handle) if retained is not None else None,
            elapsed_seconds=time.perf_counter()-started, **fields))
    try:
        dll = args.assets.resolve() / 'Simulation.dll'
        retained = prepare_serial(dll) if args.child == 'serial' else preload_original(dll)
        if args.child == 'serial' and args.cooperative is not None:
            cooperative = Cooperative(args.cooperative, retained)
            report['cooperative_helper'] = cooperative.provenance
            progress('cooperative_installed')
        progress('module_prepared')
        report['preparation'] = retained.prediction_preparation
        report['thread_ids']['after_load'] = own_thread_ids()
        template, match, crab = fixture(args.assets.resolve())
        if args.child == 'baseline':
            (shared / 'bootstrap.pb').write_bytes(match.raw_game_data)
            inputs = []
        else:
            require((shared / 'bootstrap.pb').read_bytes() == match.raw_game_data, 'fixture bootstrap differs')
            inputs = journal(shared / 'canonical-frames.bin')
            require(len(inputs) == args.frames, 'canonical journal frame count')
        report.update(bootstrap_sha256=digest(match.raw_game_data), crab_type=crab)
        progress('before_world_create')
        world = NativeSimulation(match.raw_game_data, dll)
        original_call = world._runtime.call
        def traced_call(name, *arguments):
            if name in ('SimProcessMsg','SimStep','SimMakeSimFrame'):
                progress('before_'+name)
            result = original_call(name, *arguments)
            if name in ('SimProcessMsg','SimStep','SimMakeSimFrame'):
                progress('after_'+name)
            return result
        world._runtime.call = traced_call
        progress('world_created')
        report['thread_ids']['after_world_create'] = own_thread_ids()
        added = sorted(set(report['thread_ids']['after_world_create']) - set(report['thread_ids']['after_load']))
        report['added_world_thread_ids'] = added
        require(len(added) == (0 if args.child == 'serial' else 3), 'world pool thread-count delta differs')
        observations, input_targets, positions = [], {}, {}
        with (output / 'states.jsonl').open('x', encoding='utf-8') as states:
            for frame in range(args.frames):
                current_frame = frame
                before = parsed_state(world)
                if args.child == 'baseline':
                    actions = fixture_actions(template, match, frame, before, crab, input_targets)
                    raw = canonical_frame(template, match, frame, actions, before)
                    inputs.append(raw)
                else:
                    raw = inputs[frame]
                world.process_frame(raw, dt_ms=50)
                state = parsed_state(world)
                require(state['frame'] == frame, 'native result frame differs')
                for unit in owned_crabs(state, crab):
                    positions.setdefault(unit['id'], []).append(unit['position'])
                row = dict(frame=frame, input_sha256=digest(raw), state_sha256=digest(state), state=state)
                states.write(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
                states.flush()
                observations.append(dict(frame=frame, input_sha256=row['input_sha256'], state_sha256=row['state_sha256']))
                if frame in (0, 240, args.frames - 1):
                    report['thread_ids']['frame_' + str(frame)] = own_thread_ids()
        require(len(owned_crabs(state, crab)) >= 2, 'second ordinary build did not produce a real native Crab')
        distances = {entity: max(math.dist(values[0], position) for position in values) for entity, values in positions.items()}
        require(any(distance > .5 for distance in distances.values()), 'Move12 did not produce real native displacement')
        if args.child == 'baseline':
            with (shared / 'canonical-frames.bin').open('xb') as stream:
                for raw in inputs:
                    stream.write(struct.pack('<I', len(raw)) + raw)
        report.update(frames=observations, canonical_journal_sha256=digest((shared / 'canonical-frames.bin').read_bytes()),
                      final_owned_crabs=len(owned_crabs(state, crab)), maximum_displacement=distances,
                      movement_frames=[240, 248, 440, 480, 540], ordinary_build_frames=[140, 360])
        if cooperative is not None:
            report['cooperative_before_world_close'] = cooperative.stats()
            require(cooperative.healthy() and cooperative.stats()['pumps'] > 0, 'cooperative execution did not remain healthy/active')
        report['passed'] = True
    except BaseException as error:
        report.update(error=type(error).__name__ + ': ' + str(error), traceback=traceback.format_exc())
    finally:
        try:
            if world is not None:
                world.close()
            report['thread_ids']['after_world_close'] = own_thread_ids()
            if 'after_load' in report['thread_ids']:
                require(report['thread_ids']['after_world_close'] == report['thread_ids']['after_load'], 'owned world threads remained after close')
            report['native_world_closed'] = world is None or world.closed
            if cooperative is not None:
                report['cooperative_after_world_close'] = cooperative.stats()
                require(cooperative.healthy(), 'cooperative helper failed before native cleanup')
                cooperative.close()
                report['cooperative_disabled'] = cooperative.closed
            if retained is not None:
                require(digest((args.assets.resolve() / 'Simulation.dll').read_bytes()) == retained.prediction_preparation['disk_sha256'], 'original DLL disk bytes changed')
        except BaseException as error:
            report.update(passed=False, cleanup_error=type(error).__name__ + ': ' + str(error))
        report.update(source_sha256_at_finish=source_hashes(), elapsed_seconds=time.perf_counter() - started)
        report['passed'] &= report['source_sha256_at_start'] == report['source_sha256_at_finish']
        write(output / 'report.json', report)
    print(json.dumps(dict(passed=report['passed'], mode=args.child, frames=len(report.get('frames', [])), error=report.get('error'), cleanup_error=report.get('cleanup_error'))))
    return 0 if report['passed'] else 1


def parent(args):
    output = args.output.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT / 'local') and not output.exists(), 'fresh owned local output required')
    require(args.frames == 601 and 10 <= args.timeout <= 180, 'bounded601-frame parity required')
    output.mkdir(parents=True)
    shared = output / 'shared'
    shared.mkdir()
    report = dict(passed=False, scope=__doc__, source_sha256_at_start=source_hashes(), argv=sys.argv[1:], children=[])
    started = time.perf_counter()
    try:
        modes = ('baseline', 'serial')
        if args.baseline is not None:
            previous = args.baseline.resolve()
            baseline_path = previous/'baseline/report.json'
            baseline = json.loads(baseline_path.read_text())
            require(baseline['passed'] and baseline['source_sha256_at_start'] == baseline['source_sha256_at_finish'], 'previous baseline did not pass source-bound proof')
            for name in ('bootstrap.pb','canonical-frames.bin'):
                shutil.copyfile(previous/'shared'/name, shared/name)
            require(digest((shared/'canonical-frames.bin').read_bytes()) == baseline['canonical_journal_sha256'], 'previous baseline journal digest changed')
            report.update(baseline=baseline, baseline_evidence=dict(report=str(baseline_path), sha256=digest(baseline_path.read_bytes())))
            modes = ('serial',)
        for mode in modes:
            folder = output / mode
            folder.mkdir()
            command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--child', mode,
                '--assets', str(args.assets.resolve()), '--output', str(folder), '--shared', str(shared), '--frames', str(args.frames)]
            if mode == 'serial' and args.cooperative is not None:
                command += ['--cooperative', str(args.cooperative.resolve())]
            with (folder / 'stdout.log').open('xb') as stdout, (folder / 'stderr.log').open('xb') as stderr:
                process = subprocess.Popen(command, cwd=folder, stdout=stdout, stderr=stderr,
                    stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                job, forced = None, False
                row = dict(mode=mode, pid=process.pid, command=command, retained_popen_handle=True, job_assigned=False)
                report['children'].append(row)
                try:
                    job = _WindowsJob(process.pid)
                    row['job_assigned'] = True
                    write(output / 'processes.json', report['children'])
                    if args.capture_hang_after is not None:
                        try:
                            row['exit_code'] = process.wait(timeout=args.capture_hang_after)
                        except subprocess.TimeoutExpired:
                            phase = json.loads((folder/'progress.json').read_text())
                            capture = capture_native_context(process, job, phase['native_thread_id'], int(phase['module_base'],16))
                            capture['phase'] = phase
                            write(folder/'hang-context.json', capture)
                            row['hang_context'] = str(folder/'hang-context.json')
                            row['exit_code'] = process.wait(timeout=max(1,args.timeout-args.capture_hang_after))
                    else:
                        row['exit_code'] = process.wait(timeout=args.timeout)
                finally:
                    if process.poll() is None:
                        forced = True
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    if job is not None:
                        job.close()
                    row.update(exit_code=process.poll(), reaped=process.poll() is not None, forced_cleanup=forced)
                    write(output / 'processes.json', report['children'])
            require(row['exit_code'] == 0 and not forced, 'owned ' + mode + ' child failed; retain its report/logs')
            child_report = json.loads((folder / 'report.json').read_text())
            require(child_report['passed'], 'owned child report failed')
            report[mode] = child_report
        baseline, serial = report['baseline'], report['serial']
        require(baseline['bootstrap_sha256'] == serial['bootstrap_sha256'] and
                baseline['canonical_journal_sha256'] == serial['canonical_journal_sha256'], 'different canonical inputs')
        require(baseline['frames'] == serial['frames'], 'threaded/serial parsed-state prefix differs')
        report.update(passed=True, equal_frames=args.frames, equal_240_through_600_frames=361,
            limitations=['Decoded observable equality; not complete hidden native state equality.',
                         'The pool immediate and, when selected, three cooperative wait sites are modified; no checkpoint/restore operation tested.',
                         'No graphical client integration, live network, AI, or combat/cooldown qualification.'])
    except BaseException as error:
        report.update(error=type(error).__name__ + ': ' + str(error), traceback=traceback.format_exc())
    finally:
        report.update(source_sha256_at_finish=source_hashes(), elapsed_seconds=time.perf_counter() - started)
        report['passed'] &= report['source_sha256_at_start'] == report['source_sha256_at_finish']
        write(output / 'verification.json', report)
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'equal_frames', 'elapsed_seconds', 'children') if key in report}))
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, default=601)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--baseline', type=Path, help='Retained successful baseline evidence folder; replay its exact journal only.')
    parser.add_argument('--capture-hang-after', type=float, help='One owned-thread context capture if still running after this many seconds.')
    parser.add_argument('--cooperative', type=Path, help='Isolated source-bound cooperative helper, serial child only.')
    parser.add_argument('--child', choices=('baseline', 'serial'), help=argparse.SUPPRESS)
    parser.add_argument('--shared', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    require(args.capture_hang_after is None or 1 <= args.capture_hang_after < args.timeout, 'bounded hang-capture delay required')
    if args.child:
        require(args.shared is not None and args.frames == 601, 'owned child requires explicit shared journal')
        return child(args)
    return parent(args)


if __name__ == '__main__':
    raise SystemExit(main())
