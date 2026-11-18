"""One owned, externally instrumented Windows full-state Wasp replay.

Ready/identity/release files gate CREATE after native world initialization and
before its reply. STEP timings include instrumentation; no performance gate is
evaluated. The optional exit drain follows serve(), outside every STEP scope.
Never imported by production launchers. No instrumentation is attached here.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import time
import traceback

from tools import verify_compact_worker as v
from tools import profile_worker_timing as p

ROOT = v.ROOT
BOOTSTRAP = "import sys;sys.path.insert(0,sys.argv.pop(1));from tools.profile_native_systems import worker_main;sys.exit(worker_main())"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_new(path, value):
    path = Path(path)
    temporary = path.with_name('.'+path.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic publication, refusing an existing name.
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    path = Path(path)
    require(not path.is_symlink() and path.stat().st_size <= 1024*1024, 'invalid gate file')
    return json.loads(path.read_text(encoding='utf-8'))


def sources():
    return {**v.sources(), **{name: sha(ROOT/name) for name in
        ('tools/profile_native_systems.py', 'tests/test_profile_native_systems.py',
         'tools/profile_worker_timing.py')}}


def nonce_ok(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def fresh_output(path):
    path = Path(path)
    require(path.is_absolute() and not os.path.lexists(path), 'fresh absolute output required')
    resolved = path.resolve()
    local = (ROOT/'local').resolve()
    require(path == resolved and resolved != local and resolved.is_relative_to(local),
            'unredirected output below ignored local required')
    return resolved


def verify_config(config, directory):
    require(config['schema'] == 1 and nonce_ok(config['nonce']), 'invalid gate nonce/schema')
    require(Path(config['output']) == directory and directory.is_absolute()
            and directory.resolve() == directory and not directory.is_symlink(), 'gate directory differs')
    require(type(config['gate_seconds']) in (int, float) and math.isfinite(config['gate_seconds'])
            and 0 < config['gate_seconds'] <= 110, 'gate deadline outside bounds')
    require(type(config['drain_seconds']) in (int, float) and math.isfinite(config['drain_seconds'])
            and 0 <= config['drain_seconds'] <= 2, 'exit drain outside bounds')
    require(config['source_sha256'] == sources(), 'diagnostic source changed')
    for key in ('dll', 'library'):
        require(sha(config[key]) == config[key+'_sha256'], key+' changed')


def await_release(config, directory, simulation, *, monotonic=time.monotonic, sleep=time.sleep):
    verify_config(config, directory)
    require(os.getppid() == config['parent_pid'] and Path(sys.executable).resolve() == Path(config['image']),
            'worker parent/image differs')
    require(simulation.dll_sha256 == config['dll_sha256']
            and simulation._runtime.path == Path(config['dll']) and simulation._world.value,
            'native world identity differs')
    for name in ('ready.json', 'identity.json', 'release.json', 'released.json'):
        require(not os.path.lexists(directory/name), 'reused gate file: '+name)
    ready = dict(schema=1, nonce=config['nonce'], pid=os.getpid(), parent_pid=os.getppid(),
                 image=str(Path(sys.executable).resolve()), dll=config['dll'],
                 dll_sha256=simulation.dll_sha256, world=simulation._world.value,
                 world_hex=hex(simulation._world.value),
                 frame=simulation.frame, source_sha256=config['source_sha256'])
    require(ready['frame'] == -1, 'gate must precede first native STEP')
    write_new(directory/'ready.json', ready)
    deadline = monotonic() + config['gate_seconds']
    while not (directory/'release.json').exists():
        require(monotonic() < deadline, 'external attach/release deadline expired')
        sleep(0.05)
    require(monotonic() < deadline, 'external release arrived after deadline')
    verify_config(config, directory)
    require(read_json(directory/'ready.json') == ready, 'ready receipt changed')
    release = read_json(directory/'release.json')
    abort = dict(schema=1, action='abort', nonce=config['nonce'], pid=ready['pid'], parent_pid=ready['parent_pid'])
    if release == abort:
        raise ValueError('external instrumentation explicitly aborted')
    identity = read_json(directory/'identity.json')
    require(identity['nonce'] == config['nonce'] and identity['pid'] == ready['pid']
            and identity['ready_sha256'] == sha(directory/'ready.json')
            and identity['job_member'] is True and identity['retained_handle'] is True
            and identity['actual_image'] == ready['image']
            and identity['source_sha256'] == config['source_sha256'], 'owned identity receipt differs')
    expected = dict(schema=1, action='release', nonce=config['nonce'], pid=ready['pid'], parent_pid=ready['parent_pid'],
                    ready_sha256=sha(directory/'ready.json'), identity_sha256=sha(directory/'identity.json'),
                    source_sha256=config['source_sha256'], attached=True)
    require(release == expected, 'external attach release differs')
    write_new(directory/'released.json', expected)


@contextlib.contextmanager
def gate_constructor(native_class, config, directory):
    original = native_class.__init__
    used = False

    def initialize(self, *args, **kwargs):
        nonlocal used
        require(not used, 'only one native world is allowed')
        used = True
        original(self, *args, **kwargs)
        try:
            await_release(config, directory, self)
        except BaseException:
            self.close()
            raise
    native_class.__init__ = initialize
    try:
        yield
    finally:
        native_class.__init__ = original


def worker_main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--stdio', action='store_true', required=True)
    parser.add_argument('--snapshot-decoder-library', required=True)
    parser.add_argument('--snapshot-decoder-sha256', required=True)
    parser.add_argument('--native-gate', type=Path, required=True)
    args = parser.parse_args(argv)
    from server import native_simulation as native, simulation_worker as ipc
    directory = args.native_gate
    config = read_json(directory/'launch.json')
    verify_config(config, directory)
    require(args.snapshot_decoder_library == config['library']
            and args.snapshot_decoder_sha256 == config['library_sha256'], 'decoder launch differs')
    sink = ipc.isolate_protocol_stdout()
    try:
        with gate_constructor(native.NativeSimulation, config, directory):
            result = ipc.serve(sys.stdin.buffer, sink, snapshot_decoder_library=args.snapshot_decoder_library,
                               snapshot_decoder_sha256=args.snapshot_decoder_sha256)
        if result == 0 and config['drain_seconds']:
            time.sleep(config['drain_seconds'])
        write_new(directory/'worker-finished.json', dict(exit_code=result, nonce=config['nonce'],
                  pid=os.getpid(), drain_seconds=config['drain_seconds'] if result == 0 else 0))
        return result
    finally:
        sink.close()


class OneLaunch(p._OneLaunch):
    def __init__(self, module, directory, decoder_arguments):
        super().__init__(module, directory, 1, 0, decoder_arguments)
        self.process = None

    def Popen(self, args, *positional, **kwargs):
        self.restore()
        expected = [sys.executable, '-I', '-S', '-B', '-u', '-c', p.WORKER_BOOTSTRAP,
                    str(ROOT), '--stdio'] + p._check_decoder_arguments(self.decoder_arguments)
        require(isinstance(args, list) and args == expected and not positional
                and all(kwargs.get(name) == self.original.PIPE for name in ('stdin', 'stdout', 'stderr'))
                and kwargs.get('close_fds') is True and not kwargs.get('shell', False)
                and kwargs.get('cwd') == self.output/'arm'/'worker', 'unexpected owned native worker launch')
        command = list(args)
        command[6] = BOOTSTRAP
        command.extend(['--native-gate', str(self.output)])
        self.process = self.original.Popen(command, **kwargs)
        return self.process


@contextlib.contextmanager
def owned_launch(module, directory, decoder_arguments):
    require(not isinstance(module.subprocess, p._OneLaunch), 'diagnostic launch already installed')
    original_job = module._WindowsJob
    launch = OneLaunch(module, directory, decoder_arguments)
    captured = {}

    class OneJob(original_job):
        def __init__(self, pid):
            require(module._WindowsJob is OneJob and launch.process is not None
                    and pid == launch.process.pid, 'unexpected owned Job assignment')
            module._WindowsJob = original_job
            super().__init__(pid)
            captured['job'] = self
    module.subprocess = launch
    module._WindowsJob = OneJob
    try:
        yield launch, captured
    finally:
        if module.subprocess is launch:
            module.subprocess = launch.original
        if module._WindowsJob is OneJob:
            module._WindowsJob = original_job


def process_identity(process, job):
    """Query exact retained Popen and exact owned Job handles, without PID reopening."""
    import ctypes as ct
    from ctypes import wintypes as wt
    require(process.poll() is None and job.handle, 'owned process/Job is no longer live')
    kernel = ct.WinDLL('kernel32', use_last_error=True)
    kernel.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ct.POINTER(wt.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wt.BOOL
    kernel.IsProcessInJob.argtypes = [wt.HANDLE, wt.HANDLE, ct.POINTER(wt.BOOL)]
    kernel.IsProcessInJob.restype = wt.BOOL
    image = ct.create_unicode_buffer(32768)
    size, member = wt.DWORD(len(image)), wt.BOOL()
    handle = wt.HANDLE(int(process._handle))
    require(kernel.QueryFullProcessImageNameW(handle, 0, image, ct.byref(size)), 'owned image query failed')
    require(kernel.IsProcessInJob(handle, job.handle, ct.byref(member)) and member.value,
            'exact owned Job membership failed')
    return dict(actual_image=str(Path(image.value).resolve()), job_member=True, retained_handle=True,
                job_handle=int(job.handle), process_handle=int(process._handle))


async def identify(config, directory, launch, captured):
    deadline = time.monotonic() + config['gate_seconds']
    while not (directory/'ready.json').exists():
        require(time.monotonic() < deadline, 'worker ready deadline expired')
        require(launch.process is None or launch.process.poll() is None, 'worker exited before ready')
        await asyncio.sleep(0.05)
    ready = read_json(directory/'ready.json')
    require(launch.process is not None and ready['pid'] == launch.process.pid
            and ready['parent_pid'] == os.getpid() and ready['nonce'] == config['nonce']
            and ready['source_sha256'] == config['source_sha256'] and 'job' in captured,
            'ready process ownership differs')
    identity = process_identity(launch.process, captured['job'])
    require(identity['actual_image'] == config['image'] == ready['image'], 'owned image differs')
    identity.update(schema=1, pid=ready['pid'], parent_pid=os.getpid(), nonce=config['nonce'],
                    ready_sha256=sha(directory/'ready.json'), source_sha256=config['source_sha256'])
    write_new(directory/'identity.json', identity)
    return identity


def validate_args(args):
    require(sys.platform == 'win32' and os.name == 'nt', 'native Windows diagnostic only')
    args.output = fresh_output(args.output)
    require(nonce_ok(args.nonce), 'explicit lowercase 64hex nonce required')
    require(0 < args.gate_seconds <= 110 and math.isfinite(args.gate_seconds), 'gate deadline outside bounds')
    require(0 <= args.drain_seconds <= 2 and math.isfinite(args.drain_seconds), 'exit drain outside bounds')
    require(150 <= args.timeout_seconds <= 1800 and math.isfinite(args.timeout_seconds), 'replay timeout outside bounds')
    for name in ('assets', 'journal', 'library', 'build_receipt', 'baseline_inputs'):
        path = getattr(args, name)
        require(path.is_absolute() and path.resolve() == path and not path.is_symlink(), 'absolute unredirected input required')
        require(not args.output.is_relative_to(path) and not path.is_relative_to(args.output), 'input/output overlap')
    require(nonce_ok(args.library_sha256), 'lowercase decoder SHA256 required')
    args.fresh_ai = False


async def run(args):
    validate_args(args)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, passed=False, scope=__doc__, nonce=args.nonce,
                  performance_acceptance_evaluated=False, external_instrumentation=True,
                  gate_scope='after native init/world creation and before CREATE reply; no STEP yet',
                  exit_drain_seconds=args.drain_seconds)
    bindings, launch = {}, None
    frozen = sources()
    try:
        raw = v.w.remember(args.library, v.w.MAX_LIBRARY, bindings, args.library_sha256)
        require(raw.startswith(b'MZ'), 'PE decoder library required')
        v.w.remember(args.build_receipt, v.w.MAX_JSON, bindings)
        source = v.load_inputs(args, bindings)
        require(len(source['rows']) == 1562, 'exact complete1562frame Wasp reference required')
        require(source['reference']['simulation_sha256'] ==
                '107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb', 'original DLL identity differs')
        config = dict(schema=1, nonce=args.nonce, parent_pid=os.getpid(), image=str(Path(sys.executable).resolve()),
                      output=str(args.output), dll=str(args.assets/'Simulation.dll'),
                      dll_sha256=source['reference']['simulation_sha256'], library=str(args.library),
                      library_sha256=args.library_sha256, source_sha256=frozen,
                      gate_seconds=args.gate_seconds, drain_seconds=args.drain_seconds)
        write_new(args.output/'launch.json', config)
        from server import worker_client
        decoder_args = ['--snapshot-decoder-library', str(args.library), '--snapshot-decoder-sha256', args.library_sha256]
        with owned_launch(worker_client, args.output, decoder_args) as (launch, captured):
            identity_task = asyncio.create_task(identify(config, args.output, launch, captured))
            arm_task = asyncio.create_task(v.run_arm(args, source, None, 'full', args.output/'arm',
                                                   args.output/'projection-reference.jsonl', profiled=False))
            try:
                identity, arm = await asyncio.gather(identity_task, arm_task)
            finally:
                for task in (identity_task, arm_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(identity_task, arm_task, return_exceptions=True)
        require(launch.used and launch.process is not None and launch.process.poll() == 0,
                'owned diagnostic worker did not exit normally')
        require(arm['passed'] and arm['frames'] == 1562 and v.w.clean_exit(arm), 'full replay/state/cleanup failed')
        released = read_json(args.output/'released.json')
        require(released == read_json(args.output/'release.json'), 'release receipt changed')
        finished = read_json(args.output/'worker-finished.json')
        require(finished['exit_code'] == 0 and finished['pid'] == identity['pid']
                and finished['nonce'] == args.nonce, 'worker completion identity differs')
        report.update(passed=True, identity=identity, arm=arm, reference=source['reference'],
                      worker_finished=finished, release_sha256=sha(args.output/'release.json'))
    except BaseException as error:
        report.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    finally:
        if launch is not None and launch.process is not None:
            report['worker_exit_code'] = launch.process.poll()
            if launch.process.poll() is None:
                # Only the retained child from this launch; existing workers are never touched.
                report.update(passed=False, forced_owned_cleanup=True)
                try:
                    launch.process.terminate()
                    await asyncio.to_thread(launch.process.wait, timeout=5)
                except BaseException as error:
                    report['cleanup_error'] = repr(error)
                report['worker_exit_code'] = launch.process.poll()
        report['sources_unchanged'] = sources() == frozen
        report['inputs_unchanged'] = all(sha(path) == item['sha256'] for path, item in bindings.items())
        report['passed'] &= report['sources_unchanged'] and report['inputs_unchanged']
        report['input_sha256'] = {path: item['sha256'] for path, item in bindings.items()}
        write_new(args.output/'verification.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assets', 'journal', 'library', 'build-receipt', 'baseline-inputs', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--library-sha256', required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--gate-seconds', type=float, default=100)
    parser.add_argument('--drain-seconds', type=float, default=1)
    parser.add_argument('--timeout-seconds', type=float, default=600)
    args = parser.parse_args(argv)
    result = asyncio.run(run(args))
    print(json.dumps(dict(passed=result['passed'], output=str(args.output), error=result.get('error'))))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
