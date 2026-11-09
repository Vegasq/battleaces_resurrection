"""Observe original native frame advancement after an ordinary Core surrender.

One hidden headless child, assigned to its retained-handle Job before resume.
Unmodified Simulation.dll and combat01 journal only. No Unity/game/live server,
allocator checkpoint, worker proxy, synthetic completion or renderer writes.
--prepare-only freezes the invocation without starting any native process.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.game_data import InputValidation, decode_player_input, encode_player_input
from server.native_simulation import NativeSimulation, SUPPORTED_DLL_SHA256, _protobuf_header, decode_snapshot
from server.protobuf_wire import field_bytes, get_repeated_bytes, get_uint, parse_fields, replace_fields
from tools.prediction_native import own_thread_ids
from tools.verify_movement_prediction import execute, fixture
from tools.verify_prediction_client_worker import RetainedJob

SOURCES = ('tools/verify_prediction_terminal_drain.py', 'server/native_simulation.py',
           'server/game_data.py', 'server/protobuf_wire.py', 'server/assets.py',
           'tools/verify_movement_prediction.py', 'tools/prediction_native.py',
           'tools/verify_prediction_client_worker.py', 'server/worker_client.py',
           'client_patch/prediction_worker/native.py')
MAX_INPUT = 32 * 1024 * 1024
AFTER_COMPLETE = 8


def require(value, message):
    if not value:
        raise AssertionError(message)


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def source_hashes():
    return {name: digest((ROOT / name).read_bytes()) for name in SOURCES}


def journal_records(raw):
    stream = io.BytesIO(raw)
    result = []
    while header := stream.read(4):
        require(len(header) == 4 and len(result) < 1200, 'journal header/count outside bound')
        length, = struct.unpack('<I', header)
        require(1 <= length <= MAX_INPUT, 'journal frame byte limit')
        value = stream.read(length)
        require(len(value) == length and _protobuf_header(value) == (len(result), 50), 'journal frame/order/dt mismatch')
        result.append(value)
    require(result, 'empty journal')
    return result


def inject_surrender(raw, *, slot, action, validation):
    players = get_repeated_bytes(raw, 6)
    require(len(players) <= 2 and slot in (0, 1) and set(validation.players) == {0, 1}, 'two-player original journal required')
    slots = {player.player_id: key for key, player in validation.players.items()}
    by_slot = {}
    for player in players:
        key = slots.get(decode_player_input(player)['identity']['player_id'])
        require(key is not None and key not in by_slot, 'unknown/duplicate journal player')
        by_slot[key] = player
    # Canonical idle frames omit player bodies entirely; retain the exact
    # frozen identity when introducing the Core's first action on this frame.
    player = by_slot.get(slot, encode_player_input(validation.match.identities_by_slot[slot]))
    edited = player + field_bytes(2, action)
    require(validation.validate_player_input(slot, edited) == edited, 'surrender changed during authoritative validation')
    by_slot[slot] = edited
    replacement = [field_bytes(6, body) for _, body in sorted(by_slot.items())]
    return replace_fields(raw, {6: replacement})


def bindings(args):
    assets, baseline = args.assets.resolve(), args.baseline.resolve()
    original = assets / 'Simulation.dll'
    require(digest(original.read_bytes()) == SUPPORTED_DLL_SHA256, 'exact unmodified original DLL required')
    manifest = json.loads((baseline / 'verification.json').read_text())
    require(manifest['passed'] is True, 'positive original combat baseline required')
    template, match, _ = fixture(assets)
    bootstrap = baseline / 'shared/bootstrap.pb'
    journal = baseline / 'shared/canonical-frames.bin'
    raw_bootstrap, raw_journal = bootstrap.read_bytes(), journal.read_bytes()
    require(match.raw_game_data == raw_bootstrap, 'regenerated bootstrap differs from combat01')
    require(digest(raw_journal) == manifest['baseline']['canonical_journal_sha256'], 'combat journal digest differs')
    records = journal_records(raw_journal)
    require(args.maximum_frame < len(records), 'continuation exceeds retained original journal')
    states = [json.loads(line) for line in (baseline / 'baseline/states.jsonl').read_text().splitlines()]
    require(len(states) == len(records) and all(row['frame'] == index for index, row in enumerate(states)), 'baseline state order/count')
    before = states[args.surrender_frame - 1]['state']
    descriptor = json.loads((assets / 'descriptors/game_config_pb.proto.json').read_text())
    definition = next(field for message in descriptor['messages'] if message['name'] == 'AbilityConfig'
                      for field in message['fields'] if field['name'] == 'self_destruct_ability')
    choices = [(entity, ability) for entity in before['entities'] if entity.get('army') == 0
               for ability in template.entity_abilities[entity['type']]
               if any(field.number == definition['number'] for field in parse_fields(template.abilities[ability]))]
    # Original ConcedeGame's shared generic body explicitly chooses HQ before
    # resolving the configured ability and making ExecuteInstantCommand.
    cores = [(entity, ability) for entity, ability in choices if template.catalog[entity['type']]['name'] == 'Core']
    require(len(cores) == 1, 'one actual owned original Core surrender ability required')
    core, ability = cores[0]
    action = execute(core, ability, field_bytes(1, b''))
    lookup = {entity['id']: (entity.get('army'), entity.get('type')) for entity in before['entities']}
    validation = InputValidation(match, template, entity_lookup=lookup.get)
    changed = inject_surrender(records[args.surrender_frame], slot=0, action=action, validation=validation)
    files = dict(original_dll=original, bootstrap=bootstrap, canonical_journal=journal,
                 baseline_states=baseline / 'baseline/states.jsonl', baseline_verification=baseline / 'verification.json',
                 ability_descriptor=assets / 'descriptors/game_config_pb.proto.json',
                 message_descriptor=assets / 'descriptors/game_messages_pb.proto.json',
                 structure_descriptor=assets / 'descriptors/game_structures_pb.proto.json',
                 python=Path(sys.executable))
    identity = dict(sources=source_hashes(), files={key: dict(path=str(path), sha256=digest(path.read_bytes())) for key, path in files.items()},
                    surrender_frame=args.surrender_frame, maximum_frame=args.maximum_frame, after_complete=AFTER_COMPLETE,
                    core_id=core['id'], core_type=core['type'], ability_id=ability,
                    ability_oneof_field=definition['number'], action_sha256=digest(action), modified_frame_sha256=digest(changed),
                    static_evidence='original GameAssembly e59d08...: ConcedeGame3e67eb0 -> generic11fd820, HQ lookup11fd940 and ExecuteInstantCommand construction; descriptor SelfDestructAbility selected from actual Core config')
    return identity, records, states, changed


def raw_tick(world, raw, current_seed):
    """Call exact raw exports to retain nonzero post-terminal return codes.

    Never use NativeSimulation.frame as evidence: it is a Python input cursor.
    """
    dll, handle = world._runtime.dll, world._world
    message = C.create_string_buffer(raw)
    current = C.c_int32(current_seed)
    codes = dict(process_msg=int(dll.SimProcessMsg(handle, message, len(raw))),
                 step=int(dll.SimStep(handle, 50, C.byref(current))))
    size = C.c_uint32()
    codes['make_frame'] = int(dll.SimMakeSimFrame(handle, 31, C.byref(size)))
    codes['get_frame'] = None
    snapshot = None
    if codes['make_frame'] == 0:
        require(8 <= size.value <= 16 * 1024 * 1024, 'native snapshot size outside bound')
        output = C.create_string_buffer(size.value)
        codes['get_frame'] = int(dll.SimGetSimFrameBuffer(handle, output))
        if codes['get_frame'] == 0:
            snapshot = output.raw
    return codes, current.value, snapshot


def continuation_summary(rows, complete_frame):
    after = rows[complete_frame + 1:complete_frame + 1 + AFTER_COMPLETE]
    require(len(after) == AFTER_COMPLETE, 'eight further numbered tick attempts not captured')
    return dict(after_complete=[{key: row[key] for key in ('request_frame', 'native_frame', 'return_codes', 'game_time_seconds')} for row in after],
                native_frame_follows_requests=all(row['native_frame'] == row['request_frame'] for row in after),
                all_postterminal_calls_successful=all(all(code == 0 for code in row['return_codes'].values()) for row in after),
                complete_remains_set=all(row['state'] and row['state']['game_state']['complete'] for row in after))


def child(args):
    output = args.output.resolve()
    folder = output / 'child'
    require(folder.is_dir() and not (folder / 'report.json').exists(), 'fresh prepared child required')
    report = dict(passed=False, pid=os.getpid(), scope=__doc__)
    world = None
    started = time.perf_counter()
    try:
        identity, records, baseline, changed = bindings(args)
        require(identity == json.loads((output / 'invocation.json').read_text())['identity'], 'source/artifacts changed before child')
        report['identity'] = identity
        in_job = C.c_int()
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.IsProcessInJob.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(C.c_int)]
        require(kernel.IsProcessInJob(C.c_void_p(-1), None, C.byref(in_job)) and in_job.value, 'owned child not in Job')
        os.chdir(folder)
        before_threads = own_thread_ids()
        world = NativeSimulation((args.baseline / 'shared/bootstrap.pb').read_bytes(), args.assets / 'Simulation.dll')
        report['added_world_threads'] = sorted(set(own_thread_ids()) - set(before_threads))
        require(len(report['added_world_threads']) == 3, 'unmodified native world must retain three original workers')
        rows, complete_frame, current = [], None, 0
        with (folder / 'states.jsonl').open('x', encoding='utf-8') as trace:
            for frame in range(args.maximum_frame + 1):
                raw = changed if frame == args.surrender_frame else records[frame]
                codes, current, snapshot = raw_tick(world, raw, current)
                state = decode_snapshot(snapshot, 31, include_entities=True) if snapshot else None
                if state:
                    state.pop('raw_sha256', None)
                row = dict(request_frame=frame, input_sha256=digest(raw), return_codes=codes, game_time_seconds=current,
                           native_frame=state['frame'] if state else None, state=state,
                           state_sha256=digest(state) if state else None)
                trace.write(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
                rows.append(row)
                if frame < args.surrender_frame:
                    require(all(code == 0 for code in codes.values()) and digest(state) == baseline[frame]['state_sha256'],
                            'unmodified pre-surrender prefix differs from original combat baseline')
                if state and state['game_state']['complete'] and complete_frame is None:
                    complete_frame = frame
                    report['first_complete'] = dict(request_frame=frame, native_frame=state['frame'], game_state=state['game_state'])
                if frame >= args.surrender_frame and snapshot:
                    (folder / f'snapshot-request-{frame}.bin').write_bytes(snapshot)
                if complete_frame is not None and frame >= complete_frame + AFTER_COMPLETE:
                    break
        require(complete_frame is not None and complete_frame >= args.surrender_frame, 'ordinary surrender did not end native world within bound')
        report.update(attempted_frames=len(rows), prefix_equal_frames=args.surrender_frame,
                      **continuation_summary(rows, complete_frame),
                      limitations=['Observes ended original world only; no checkpoint restore or managed renderer integration.',
                                   'Monotonic corrected H+1 publication still requires a qualified restore to playing state and ordinary managed publication/events.'],
                      source_hashes_at_finish=source_hashes())
        require(report['source_hashes_at_finish'] == identity['sources'], 'source changed during owned probe')
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        try:
            if world is not None:
                world.close()
                require(own_thread_ids() == before_threads, 'native threads remained after close')
            report['native_closed'] = world is None or world.closed
        except BaseException as error:
            report.update(passed=False, cleanup_error=repr(error))
        report['elapsed_seconds'] = time.perf_counter() - started
        write(folder / 'report.json', report)
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'attempted_frames', 'native_frame_follows_requests') if key in report}))
    return 0 if report['passed'] else 1


def prepare(args):
    output = args.output.resolve()
    require(output.is_relative_to(ROOT / 'local') and not output.exists(), 'fresh ignored local output required')
    identity, _, _, _ = bindings(args)
    output.mkdir(parents=True)
    (output / 'child').mkdir()
    command = [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()), '--child',
               '--assets', str(args.assets.resolve()), '--baseline', str(args.baseline.resolve()),
               '--output', str(output), '--surrender-frame', str(args.surrender_frame), '--maximum-frame', str(args.maximum_frame)]
    write(output / 'invocation.json', dict(identity=identity, command=command, timeout=args.timeout))
    return dict(prepared=True, native_launched=False, output=str(output), run_command=[sys.executable, str(Path(__file__).resolve()),
                '--assets', str(args.assets.resolve()), '--baseline', str(args.baseline.resolve()), '--output', str(output),
                '--run-prepared', '--surrender-frame', str(args.surrender_frame), '--maximum-frame', str(args.maximum_frame),
                '--timeout', str(args.timeout)])


def run_prepared(args):
    output = args.output.resolve()
    require(os.name == 'nt' and output.is_relative_to(ROOT / 'local') and not (output / 'verification.json').exists(), 'fresh prepared Windows output required')
    invocation = json.loads((output / 'invocation.json').read_text())
    require(not (output / 'child/report.json').exists(), 'prior child report preserved; use fresh output')
    identity, _, _, _ = bindings(args)
    require(identity == invocation['identity'], 'prepared source/artifacts changed')
    report = dict(passed=False, identity=identity, forced_cleanup=False, assigned_before_resume=False)
    process = job = None
    try:
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0
        with (output / 'stdout.log').open('xb') as stdout, (output / 'stderr.log').open('xb') as stderr:
            process = subprocess.Popen(invocation['command'], cwd=output / 'child', stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, startupinfo=info, close_fds=True,
                creationflags=0x4 | subprocess.CREATE_NO_WINDOW)
            report.update(pid=process.pid, retained_process_handle=True)
            job = RetainedJob(process)
            report['assigned_before_resume'] = True
            resume = C.WinDLL('ntdll', use_last_error=True).NtResumeProcess
            resume.argtypes, resume.restype = [C.c_void_p], C.c_long
            require(resume(C.c_void_p(int(process._handle))) == 0, 'retained child resume failed')
            write(output / 'process.json', report)
            report['exit_code'] = process.wait(timeout=args.timeout)
        report['child'] = json.loads((output / 'child/report.json').read_text())
        require(report['exit_code'] == 0 and report['child']['passed'], 'owned terminal probe failed; preserve child report')
        require(bindings(args)[0] == identity, 'source/artifact changed during probe')
        report['passed'] = True
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        errors = []
        if process is not None:
            if process.poll() is None:
                report['forced_cleanup'] = True
                try:
                    if job is not None:
                        job.terminate_owned()
                    else:
                        process.terminate()  # Exact retained handle, including failed pre-assignment launch.
                except BaseException as error:
                    errors.append(repr(error))
            try:
                process.wait(timeout=5)
                report.update(reaped=True, exit_code=process.returncode)
            except BaseException as error:
                errors.append(repr(error))
        if job is not None:
            try:
                report['job_before_close'] = job.accounting()
                report['passed'] &= report['job_before_close']['terminated'] == 0
                if report['job_before_close']['active']:
                    report['forced_cleanup'] = True
                job.close()
            except BaseException as error:
                errors.append(repr(error))
        report['cleanup_errors'] = errors
        report['passed'] &= not errors and not report['forced_cleanup'] and report.get('reaped', False)
        write(output / 'verification.json', report)
    print(json.dumps({key: report[key] for key in ('passed', 'error', 'pid', 'exit_code', 'reaped', 'forced_cleanup') if key in report}))
    return 0 if report['passed'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--surrender-frame', type=int, choices=(100, 500), default=500)
    parser.add_argument('--maximum-frame', type=int, default=1000)
    parser.add_argument('--timeout', type=float, default=45)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--run-prepared', action='store_true')
    mode.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.assets, args.baseline, args.output = args.assets.resolve(), args.baseline.resolve(), args.output.resolve()
    require(args.surrender_frame + AFTER_COMPLETE < args.maximum_frame <= 1100 and 1 <= args.timeout <= 90, 'bounded frame/deadline required')
    if args.child:
        return child(args)
    if args.run_prepared:
        return run_prepared(args)
    result = prepare(args)
    print(json.dumps(result))
    return 0 if args.prepare_only else run_prepared(args)


if __name__ == '__main__':
    raise SystemExit(main())
