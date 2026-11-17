"""Opt-in real Wine/Simulation.dll two-world isolation and timeout evidence.

Two workers replay an already verified native benchmark journal. After both
match frames0..19, only the victim's retained private simulation cgroup is frozen.
Its frame20 must time out and finish owned cleanup within10s. The survivor must
match frames20..39 and close normally. Recorded AI commands are replayed; this
does not regenerate AI decisions or qualify aiprogram.dll concurrency.
No game UI, listeners, real host profiles, global PID scans or wineserver calls.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import sys
import time
import traceback

from server.assets import verify_assets
from server.game_data import decompress_game_data
from server.native_simulation import SUPPORTED_DLL_SHA256
from server.wine_worker import WineWorkerBackend
from server.worker_client import SimulationWorker, WorkerTimeout
from tools.benchmark_large_armies import MAX_FRAMES, check_record, read_frame, state_digest

ROOT = Path(__file__).resolve().parents[1]
INITIAL_FRAMES, SURVIVOR_FRAMES = 20, 20
FAULT_TIMEOUT = .25
RECORD_FILES = ('benchmark.json', 'bootstrap.pb.gz', 'frames.bin', 'frames.jsonl')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_hashes():
    files = sorted((ROOT/'server').glob('*.py')) + [Path(__file__), ROOT/'tools/benchmark_large_armies.py']
    return {path.relative_to(ROOT).as_posix(): file_hash(path) for path in files}


def bounded_json(path, limit):
    require(path.stat().st_size <= limit, 'JSON evidence exceeds bound')
    return json.loads(path.read_text(encoding='utf-8'))


def hash_text(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def load_recording(directory, manifest_sha256):
    """Read/validate authored file structure; this alone is never native evidence."""
    report = bounded_json(directory/'benchmark.json', 4*1024*1024)
    require(isinstance(report, dict) and report.get('passed') is True and report.get('native_qualified') is True,
            'recording must be a completed native benchmark')
    count = report.get('frames')
    require(type(count) is int and INITIAL_FRAMES+SURVIVOR_FRAMES <= count <= MAX_FRAMES,
            'recording needs at least40 bounded sequential frames')
    require(report.get('asset_manifest_sha256') == manifest_sha256, 'recording asset manifest differs')
    require(report.get('simulation_sha256') == SUPPORTED_DLL_SHA256, 'recording simulation identity differs')
    require((directory/'frames.bin').stat().st_size <= 512*1024*1024 and
            (directory/'frames.jsonl').stat().st_size <= 256*1024*1024, 'recorded journals exceed bounds')
    require((directory/'bootstrap.pb.gz').stat().st_size <= 2*1024*1024, 'recorded bootstrap exceeds bound')
    hashes = {name: file_hash(directory/name) for name in RECORD_FILES}
    require(report.get('input_journal_sha256') == hashes['frames.bin'], 'input journal digest differs')
    data = decompress_game_data((directory/'bootstrap.pb.gz').read_bytes())
    require(hashlib.sha256(data).hexdigest() == report.get('bootstrap_sha256'), 'bootstrap digest differs')
    selected, expected = [], []
    with (directory/'frames.bin').open('rb') as binary, (directory/'frames.jsonl').open('rb') as rows:
        for number in range(count):
            line = rows.readline(512*1024+1)
            require(line and len(line) <= 512*1024 and line.endswith(b'\n'), 'missing/oversized recorded frame row')
            row, payload = json.loads(line), read_frame(binary)
            require(isinstance(row, dict) and type(row.get('frame')) is int and row['frame'] == number,
                    'recorded frames are not sequential')
            require(hash_text(row.get('input_sha256')) and hash_text(row.get('state_sha256')),
                    'recorded frame hashes are invalid')
            require(hashlib.sha256(payload).hexdigest() == row['input_sha256'], 'frame input digest differs')
            if number < INITIAL_FRAMES+SURVIVOR_FRAMES:
                selected.append(payload); expected.append(row)
        require(not binary.read(1) and not rows.read(1), 'recording contains trailing frames')
    return data, selected, expected, dict(files_sha256=hashes, frames=count,
        bootstrap_sha256=report['bootstrap_sha256'], source_at_recording=report.get('source_at_start'),
        workload=report.get('workload'), scope='original simulation replay; AI commands are recorded, not regenerated')


def validate_paths(args):
    for name in ('assets', 'replay', 'output', 'wine', 'windows_python', 'prefix_template'):
        value = Path(getattr(args, name))
        require(value.is_absolute(), f'{name} must be an explicit absolute path')
        if name == 'prefix_template':
            require(not value.is_symlink(), 'prefix template may not be a symlink')
        setattr(args, name, value.resolve())
    require(args.output.is_relative_to(ROOT/'local') and not args.output.exists(), 'require a new ignored local output directory')
    for name in ('assets', 'replay', 'prefix_template'):
        path = getattr(args, name)
        require(path.is_dir(), f'{name} directory is missing')
        require(not args.output.is_relative_to(path) and not path.is_relative_to(args.output),
                'output must be separate from input/template directories')
    if args.cgroup_parent is not None:
        require(args.cgroup_parent.is_absolute(), 'cgroup parent must be absolute')


def parse_members(raw):
    require(len(raw) <= 65536, 'owned cgroup member list exceeds bound')
    words = raw.decode('ascii').split()
    require(0 < len(words) <= 256 and all(word.isdecimal() and 0 < int(word) <= 0x7fffffff for word in words),
            'owned cgroup member list is empty or invalid')
    members = [int(word) for word in words]
    require(len(set(members)) == len(members), 'owned cgroup contains duplicate member IDs')
    return members


def parse_events(raw):
    require(len(raw) <= 4096, 'owned cgroup event list exceeds bound')
    rows = [line.split() for line in raw.decode('ascii').splitlines()]
    require(all(len(row) == 2 for row in rows), 'invalid cgroup event row')
    values = dict(rows)
    require(len(values) == len(rows) and values.get('populated') in ('0', '1') and values.get('frozen') in ('0', '1'),
            'cgroup events lack valid populated/frozen state')
    return values


def validate_members(members, *, coordinator_pid, guardian_pids):
    require(coordinator_pid not in members and not set(guardian_pids).intersection(members),
            'refusing to freeze a coordinator or guardian cgroup')


class VictimScope:
    """Retain the victim's exact kernel directory and member pidfds, never a PID search."""
    def __init__(self, victim, survivor):
        self.fd, self.pidfds, self.frozen = None, [], False
        owner, other = victim._backend_owner, survivor._backend_owner
        require(owner is not None and other is not None and owner is not other, 'two distinct backend owners required')
        require(victim.pid != survivor.pid and owner.cgroup.path != other.cgroup.path and owner.runtime != other.runtime,
                'workers share process, cgroup or scratch identity')
        require(not victim.closed and not survivor.closed and not victim._test_backend and not survivor._test_backend,
                'only live real Wine workers may be frozen')
        require(owner.cgroup.fd is not None and owner.cgroup._same(), 'victim cgroup ownership changed')
        self.path, self.runtime = owner.cgroup.path, owner.runtime
        self.guardians = (victim.pid, survivor.pid)
        self.fd = os.dup(owner.cgroup.fd)
        try:
            actual = os.fstat(self.fd)
            require((actual.st_dev, actual.st_ino) == (owner.cgroup.identity.st_dev, owner.cgroup.identity.st_ino),
                    'retained victim cgroup identity differs')
            self.identity = dict(device=actual.st_dev, inode=actual.st_ino)
            validate_members(self.members(), coordinator_pid=os.getpid(), guardian_pids=self.guardians)
        except BaseException:
            os.close(self.fd); self.fd = None
            raise

    def read(self, name, limit):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            return os.read(descriptor, limit+1)
        finally:
            os.close(descriptor)

    def members(self):
        return parse_members(self.read('cgroup.procs', 65536))

    def write_freeze(self, frozen):
        require(self.fd is not None, 'victim cgroup handle is closed')
        descriptor = os.open('cgroup.freeze', os.O_WRONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            require(os.write(descriptor, b'1' if frozen else b'0') == 1, 'incomplete cgroup freeze write')
        finally:
            os.close(descriptor)

    async def freeze(self):
        self.write_freeze(True)
        self.frozen = True
        deadline = time.monotonic()+3
        while True:
            events = parse_events(self.read('cgroup.events', 4096))
            if events['frozen'] == '1':
                require(events['populated'] == '1', 'victim exited before freezing')
                break
            require(time.monotonic() < deadline, 'victim did not reach frozen state within3s')
            await asyncio.sleep(.01)
        members = self.members()
        validate_members(members, coordinator_pid=os.getpid(), guardian_pids=self.guardians)
        for pid in members:
            self.pidfds.append(os.pidfd_open(pid))
        return dict(cgroup=str(self.path), identity=self.identity, frozen_confirmed=True,
                    populated_confirmed=True, linux_member_pids=members,
                    coordinator_and_guardians_excluded=True)

    def all_members_exited(self):
        return bool(self.pidfds) and len(select.select(self.pidfds, [], [], 0)[0]) == len(self.pidfds)

    def safety_thaw(self):
        if not self.frozen or not self.path.exists():
            return False
        self.write_freeze(False)
        self.frozen = False
        return True

    def close(self):
        for fd in self.pidfds:
            os.close(fd)
        self.pidfds = []
        if self.fd is not None:
            os.close(self.fd); self.fd = None


def worker_record(worker):
    owner = worker._backend_owner
    return dict(guardian_pid=worker.pid, native_windows_pid=worker.native_pid,
                runtime=worker.runtime_info, simulation_sha256=worker.dll_sha256,
                guardian_exit_code=worker.process.poll(), frame=worker.frame, failure=worker.failure,
                backend_statistics=worker.backend_statistics,
                stderr_thread_closed=not worker._stderr_thread.is_alive(),
                io_threads_closed=all(not thread.is_alive() for thread in worker._io._threads),
                owner_thread_closed=not owner._monitor_thread.is_alive(),
                private_cgroup_absent=not owner.cgroup.path.exists(), private_scratch_absent=not owner.runtime.exists())


def require_cleanup(record, *, natural):
    statistics = record['backend_statistics']
    require(record['guardian_exit_code'] is not None and isinstance(statistics, dict) and
            all(statistics.get(name) is True for name in ('cleanup_complete', 'cgroup_removed', 'prefix_removed')),
            'worker did not confirm complete owned cleanup')
    require(all(record[name] for name in ('stderr_thread_closed', 'io_threads_closed', 'owner_thread_closed',
                                         'private_cgroup_absent', 'private_scratch_absent')),
            'worker threads, scratch or cgroup survived cleanup')
    if natural:
        require(record['guardian_exit_code'] == 0 and statistics.get('native_exit_code') == 0 and record['failure'] is None,
                'survivor did not exit naturally')


async def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, native_qualified=False, scope=__doc__, platform=platform.platform(),
                  coordinator_pid=os.getpid(), python=sys.version, source_at_start=source_hashes(),
                  comparison='all parsed state fields except nonsemantic raw buffer hash', workers={})
    started, workers, scope = time.monotonic(), {}, None
    try:
        verify_assets(args.assets)
        report['asset_manifest_sha256'] = file_hash(args.assets/'asset-manifest.json')
        data, frames, expected, recording = load_recording(args.replay, report['asset_manifest_sha256'])
        report['recording'] = recording
        backend = WineWorkerBackend(args.wine, args.windows_python, args.prefix_template, args.cgroup_parent)
        report['backend'] = dict(wine=str(backend.wine_executable), windows_python=str(backend.windows_python),
                                windows_python_sha256=file_hash(backend.windows_python),
                                prefix_template=str(backend.prefix_template), cgroup_parent=str(backend.cgroup_parent))
        for name in ('victim', 'survivor'):
            work = args.output/name; work.mkdir()
            worker = await SimulationWorker.create(data, args.assets/'Simulation.dll', backend=backend,
                working_directory=work, startup_timeout=120, request_timeout=10, close_timeout=2)
            workers[name] = worker
            require(worker.dll_sha256 == SUPPORTED_DLL_SHA256 and worker.runtime_info['os_name'] == 'nt',
                    'worker native runtime identity differs')
        victim, survivor = workers['victim'], workers['survivor']
        with (args.output/'observations.jsonl').open('x', encoding='utf-8') as trace:
            async def step(name, number):
                result = await workers[name].process_frame(frames[number], dt_ms=50)
                check_record(number, frames[number], result.state, expected[number])
                trace.write(json.dumps(dict(worker=name, frame=number, state_sha256=state_digest(result.state),
                                            input_sha256=expected[number]['input_sha256']))+'\n')
                trace.flush()
                return result.state
            for number in range(INITIAL_FRAMES):
                first, second = await step('victim', number), await step('survivor', number)
                require(state_digest(first) == state_digest(second), 'independent worlds diverged before fault')
            report['matching_initial_frames_per_worker'] = INITIAL_FRAMES
            scope = VictimScope(victim, survivor)
            report['fault'] = await scope.freeze()
            report['fault'].update(action='freeze only owned simulation cgroup', failed_frame=INITIAL_FRAMES,
                                   request_timeout_seconds=FAULT_TIMEOUT, victim_cleanup_is_natural=False)
            victim.request_timeout = FAULT_TIMEOUT
            fault_started = time.monotonic()
            try:
                await victim.process_frame(frames[INITIAL_FRAMES], dt_ms=50)
            except WorkerTimeout:
                report['fault']['expected_worker_timeout'] = True
            else:
                raise ValueError('frozen simulation unexpectedly completed STEP')
            report['fault']['timeout_and_cleanup_seconds'] = time.monotonic()-fault_started
            require(report['fault']['timeout_and_cleanup_seconds'] < 10, 'victim timeout/cleanup exceeded10s')
            require(victim.frame == INITIAL_FRAMES-1, 'failed victim STEP advanced authoritative frame')
            report['fault']['all_retained_member_pidfds_exited'] = scope.all_members_exited()
            require(report['fault']['all_retained_member_pidfds_exited'], 'frozen victim process survived cleanup')
            require_cleanup(worker_record(victim), natural=False)
            for number in range(INITIAL_FRAMES, INITIAL_FRAMES+SURVIVOR_FRAMES):
                await step('survivor', number)
            report['matching_survivor_frames_after_fault'] = SURVIVOR_FRAMES
        await survivor.close()
        require_cleanup(worker_record(survivor), natural=True)
        report.update(passed=True, native_qualified=True)
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if scope is not None:
            try:
                report['safety_thaw_used'] = scope.safety_thaw()
            except Exception as error:
                report.update(passed=False, native_qualified=False, thaw_error=repr(error))
        for name, worker in workers.items():
            try:
                await worker.close()
            except BaseException as error:
                report.setdefault('cleanup_errors', {})[name] = repr(error)
                report.update(passed=False, native_qualified=False)
            report['workers'][name] = worker_record(worker)
        if scope is not None:
            scope.close()
        report.update(elapsed_seconds=time.monotonic()-started, source_at_finish=source_hashes())
        report['source_unchanged'] = report['source_at_start'] == report['source_at_finish']
        if 'recording' in report:
            report['recording_unchanged'] = report['recording']['files_sha256'] == {
                name: file_hash(args.replay/name) for name in RECORD_FILES}
        report['passed'] &= report['source_unchanged'] and report.get('recording_unchanged', False)
        report['native_qualified'] &= report['passed']
        (args.output/'verification.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    print(json.dumps({name: report[name] for name in ('passed', 'native_qualified', 'elapsed_seconds', 'error') if name in report}))
    return 0 if report['passed'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'replay', 'output', 'wine', 'windows-python', 'prefix-template'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--cgroup-parent', type=Path)
    args = parser.parse_args(argv)
    require(sys.platform.startswith('linux'), 'requires native Linux Python and a delegated cgroup-v2 hierarchy')
    validate_paths(args)
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
