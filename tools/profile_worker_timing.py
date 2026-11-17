"""Explicit diagnostic worker profiling; never imported by normal launchers.

The real worker protocol and native calls remain unchanged. Records are bounded
in memory and written only after serve() ends. A forced process kill can leave an
empty/incomplete output: absence of a completed report is not successful evidence.
Nested metrics are inclusive and must not be added to their parent measurements.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
WORKER_BOOTSTRAP = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('server.simulation_worker',run_name='__main__')"
PROFILE_BOOTSTRAP = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('tools.profile_worker_timing',run_name='__main__')"
OPERATIONS = {1: 'CREATE', 2: 'STEP', 3: 'STATE', 4: 'SNAPSHOT', 5: 'CLOSE', 6: 'TEST_CONTROL', 7: 'BOT_INPUT'}


def _limits(max_records, thread_sample_interval):
    if type(max_records) is not int or not 1 <= max_records <= 20000:
        raise ValueError('max_records must be in 1..20000')
    if type(thread_sample_interval) is not int or not 0 <= thread_sample_interval <= 20000:
        raise ValueError('thread_sample_interval must be in 0..20000')


class _OneLaunch:
    """Intercept exactly one known launch, restoring the module before Popen."""
    def __init__(self, module, output, max_records, thread_sample_interval):
        self.module, self.original = module, module.subprocess
        self.output, self.max_records = output, max_records
        self.thread_sample_interval = thread_sample_interval
        self.owner_thread = threading.get_ident()
        self.used = False

    def __getattr__(self, name):
        return getattr(self.original, name)

    def restore(self):
        # This executes synchronously before SimulationWorker.create's first
        # await. Concurrent normal workers therefore never inherit this proxy.
        if self.module.subprocess is self:
            self.module.subprocess = self.original
        else:
            raise RuntimeError('diagnostic launch ownership changed')
        if self.used or threading.get_ident() != self.owner_thread:
            raise RuntimeError('unexpected diagnostic worker launch')
        self.used = True

    def Popen(self, args, *positional, **kwargs):
        self.restore()
        expected = [sys.executable, '-I', '-S', '-B', '-u', '-c', WORKER_BOOTSTRAP, str(ROOT), '--stdio']
        if (not isinstance(args, list) or args[:9] != expected or args[9:] not in ([], ['--test-backend'])
                or positional or kwargs.get('stdin') != self.original.PIPE
                or kwargs.get('stdout') != self.original.PIPE or kwargs.get('stderr') != self.original.PIPE
                or kwargs.get('close_fds') is not True or kwargs.get('shell', False)):
            raise RuntimeError('unexpected diagnostic worker command or pipe ownership')
        command = list(args)
        command[6] = PROFILE_BOOTSTRAP
        command.extend(['--profile-output', str(self.output), '--max-records', str(self.max_records),
                        '--thread-sample-interval', str(self.thread_sample_interval)])
        return self.original.Popen(command, **kwargs)


GUARDIAN_PROFILE_BOOTSTRAP = "import sys;sys.path.insert(0,sys.argv.pop(1));from tools.profile_worker_timing import guardian_main;sys.exit(guardian_main())"
GUARDIAN_FIELDS = ('--wine', '--windows-python', '--prefix-template', '--working-directory',
                   '--runtime-directory', '--cgroup', '--parent-pid', '--watch-fd', '--status-fd')
HYBRID_PROFILE_SOURCES = ('server/wine_worker.py', 'server/wine_worker_guardian.py', 'server/wine_worker_cgroup.py')


def _guardian_fields(argv):
    if (not isinstance(argv, list) or len(argv) != len(GUARDIAN_FIELDS)*2
            or tuple(argv[::2]) != GUARDIAN_FIELDS or not all(isinstance(v, str) for v in argv)):
        raise RuntimeError('unexpected diagnostic guardian arguments')
    return dict(zip(GUARDIAN_FIELDS, argv[1::2]))


def _wine_output(output):
    # translate_path requires an existing path. Translate the validated parent;
    # reserve the new file exclusively in the Windows worker, never overwrite.
    from server.wine_worker import windows_path
    if not output.is_absolute() or output.exists() or output.is_symlink() or not output.parent.is_dir():
        raise ValueError('diagnostic output must be a new absolute file in an existing directory')
    if any(char in output.name for char in '\\:*?"<>|\r\n\0'):
        raise ValueError('diagnostic output name cannot be represented safely in Wine')
    return windows_path(output.parent) + '\\' + output.name


class _OneGuardianLaunch(_OneLaunch):
    def __init__(self, module, output, max_records, thread_sample_interval, backend, directory):
        super().__init__(module, output, max_records, thread_sample_interval)
        self.backend, self.directory = backend, directory

    def Popen(self, args, *positional, **kwargs):
        self.restore()
        from server.wine_worker import GUARDIAN_BOOTSTRAP
        expected = [sys.executable, '-I', '-S', '-B', '-u', '-c', GUARDIAN_BOOTSTRAP, str(ROOT)]
        if not isinstance(args, list) or args[:8] != expected:
            raise RuntimeError('unexpected diagnostic guardian bootstrap')
        fields = _guardian_fields(args[8:])
        runtime, cgroup = Path(fields['--runtime-directory']), Path(fields['--cgroup'])
        try:
            descriptors = tuple(int(fields[name]) for name in ('--watch-fd', '--status-fd'))
        except ValueError as error:
            raise RuntimeError('unexpected diagnostic guardian descriptors') from error
        if (positional or fields['--wine'] != str(self.backend.wine_executable)
                or fields['--windows-python'] != str(self.backend.windows_python)
                or fields['--prefix-template'] != str(self.backend.prefix_template)
                or fields['--working-directory'] != str(self.directory)
                or fields['--parent-pid'] != str(os.getpid())
                or runtime.parent != self.directory or not runtime.name.startswith('ba-wine-worker-')
                or cgroup.parent != self.backend.cgroup_parent or cgroup.name != runtime.name
                or kwargs.get('cwd') != self.directory or kwargs.get('stdin') != self.original.PIPE
                or kwargs.get('stdout') != self.original.PIPE or kwargs.get('stderr') != self.original.PIPE
                or kwargs.get('close_fds') is not True or kwargs.get('start_new_session') is not True
                or kwargs.get('pass_fds') != descriptors or min(descriptors) < 0 or len(set(descriptors)) != 2
                or kwargs.get('shell', False) or self.output.is_relative_to(runtime)
                or self.output.is_relative_to(self.backend.prefix_template)):
            raise RuntimeError('unexpected diagnostic guardian command or ownership')
        command = list(args)
        command[6] = GUARDIAN_PROFILE_BOOTSTRAP
        command.extend(['--profile-output', str(self.output), '--max-records', str(self.max_records),
                        '--thread-sample-interval', str(self.thread_sample_interval)])
        return self.original.Popen(command, **kwargs)


class _OneWineChildLaunch(_OneLaunch):
    def __init__(self, module, output, max_records, thread_sample_interval, guardian_args):
        super().__init__(module, output, max_records, thread_sample_interval)
        self.fields = _guardian_fields(guardian_args)

    def Popen(self, args, *positional, **kwargs):
        self.restore()
        from server.wine_worker import windows_path
        fields = self.fields
        runtime = Path(fields['--runtime-directory'])
        expected = [fields['--wine'], windows_path(Path(fields['--windows-python'])),
                    '-I', '-S', '-B', '-u', '-c', WORKER_BOOTSTRAP, windows_path(ROOT), '--stdio']
        pass_fds = kwargs.get('pass_fds')
        environment = kwargs.get('env', {})
        if (args != expected or positional or kwargs.get('cwd') != runtime/'work'
                or kwargs.get('stdin') is not sys.stdin.buffer or kwargs.get('stdout') is not sys.stdout.buffer
                or kwargs.get('stderr') is not sys.stderr.buffer or kwargs.get('close_fds') is not True
                or not isinstance(pass_fds, tuple) or len(pass_fds) != 1
                or type(pass_fds[0]) is not int or pass_fds[0] < 0
                or not callable(kwargs.get('preexec_fn')) or kwargs.get('shell', False)
                or environment.get('WINEPREFIX') != str(runtime/'prefix')
                or environment.get('WINEARCH') != 'win64'
                or environment.get('WINEDLLOVERRIDES') != 'mscoree,mshtml='
                or self.output.is_relative_to(runtime)
                or self.output.is_relative_to(Path(fields['--prefix-template']))):
            raise RuntimeError('unexpected diagnostic Wine child command or ownership')
        command = list(args)
        command[7] = PROFILE_BOOTSTRAP
        command.extend(['--profile-output', _wine_output(self.output), '--max-records', str(self.max_records),
                        '--thread-sample-interval', str(self.thread_sample_interval), '--profile-hybrid-worker'])
        return self.original.Popen(command, **kwargs)


def guardian_main(argv=None):
    """Explicit diagnostic entrypoint; reuse every production guardian lifetime rule."""
    from server import wine_worker_guardian as guardian
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 6 or argv[-6::2] != ['--profile-output', '--max-records', '--thread-sample-interval']:
        raise ValueError('diagnostic guardian requires explicit profiling arguments')
    output, max_records, interval = Path(argv[-5]), int(argv[-3]), int(argv[-1])
    _limits(max_records, interval)
    _wine_output(output)
    if isinstance(guardian.subprocess, _OneLaunch):
        raise RuntimeError('another diagnostic guardian launch is active')
    proxy = _OneWineChildLaunch(guardian, output, max_records, interval, argv[:-6])
    guardian.subprocess = proxy
    try:
        return guardian.main(argv[:-6])
    finally:
        if guardian.subprocess is proxy:
            guardian.subprocess = proxy.original


async def create_profiled_worker(game_data, dll_path=None, *, profile_path,
                                 max_records=20000, thread_sample_interval=0, **kwargs):
    """Create an ordinary owned SimulationWorker with an explicit sidecar profile.

    The supplied output must not exist. Native and synthetic backend selection,
    validation, job ownership, timeout handling and cleanup remain the normal
    SimulationWorker implementation. No instrumentation persists in the parent.
    """
    from server import worker_client
    _limits(max_records, thread_sample_interval)
    backend = kwargs.get('backend')
    if backend is not None:
        from server import wine_worker
        if type(backend) is not wine_worker.WineWorkerBackend:
            raise ValueError('diagnostic profiling requires an explicit WineWorkerBackend or direct backend')
    output = Path(profile_path).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('profile output parent must already exist')
    output = output.parent.resolve(strict=True)/output.name
    module = worker_client if backend is None else wine_worker
    if isinstance(module.subprocess, _OneLaunch):
        raise RuntimeError('another diagnostic worker launch is active')
    if backend is None:
        proxy = _OneLaunch(module, output, max_records, thread_sample_interval)
    else:
        _wine_output(output)
        if kwargs.get('working_directory') is None:
            raise ValueError('profiled Wine worker requires an explicit working directory')
        directory = Path(kwargs['working_directory']).resolve(strict=True)
        proxy = _OneGuardianLaunch(module, output, max_records, thread_sample_interval, backend, directory)
    module.subprocess = proxy
    try:
        return await worker_client.SimulationWorker.create(game_data, dll_path, **kwargs)
    finally:
        if module.subprocess is proxy:
            module.subprocess = proxy.original


def _clocks():
    return time.perf_counter_ns(), time.thread_time_ns(), time.process_time_ns()


def _delta(start):
    end = _clocks()
    return tuple(max(0, end[index] - start[index]) for index in range(3))


def thread_cpu_snapshot():
    """Current-process live thread identities and cumulative CPU, no suspension.

    A thread that exits between samples can be absent. Process CPU is recorded
    separately. Windows values use GetThreadTimes (100ns units); Linux uses
    /proc/self/task ticks. Neither route proves what DLL created a thread.
    """
    rows = []
    if os.name == 'nt':
        import ctypes as C
        from ctypes import wintypes as W
        class Entry(C.Structure):
            _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('tid', W.DWORD), ('pid', W.DWORD),
                        ('base', W.LONG), ('delta', W.LONG), ('flags', W.DWORD)]
        kernel = C.WinDLL('kernel32', use_last_error=True)
        kernel.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = W.HANDLE
        for name in ('Thread32First', 'Thread32Next'):
            method = getattr(kernel, name)
            method.argtypes = [W.HANDLE, C.POINTER(Entry)]; method.restype = W.BOOL
        kernel.OpenThread.argtypes = [W.DWORD, W.BOOL, W.DWORD]; kernel.OpenThread.restype = W.HANDLE
        kernel.GetThreadTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
        kernel.GetThreadTimes.restype = W.BOOL
        kernel.CloseHandle.argtypes = [W.HANDLE]; kernel.CloseHandle.restype = W.BOOL
        snapshot = kernel.CreateToolhelp32Snapshot(4, 0)
        if snapshot == C.c_void_p(-1).value:
            raise OSError(C.get_last_error(), 'thread snapshot failed')
        try:
            entry = Entry(); entry.size = C.sizeof(entry)
            more = kernel.Thread32First(snapshot, C.byref(entry))
            while more:
                if entry.pid == os.getpid():
                    handle = kernel.OpenThread(0x0800, False, entry.tid)
                    if handle:
                        try:
                            creation, exit_time, system, user = (W.FILETIME() for _ in range(4))
                            if kernel.GetThreadTimes(handle, *(C.byref(v) for v in (creation, exit_time, system, user))):
                                value = lambda v: (v.dwHighDateTime << 32) | v.dwLowDateTime
                                rows.append({'tid': entry.tid, 'creation': value(creation),
                                             'kernel_cpu_ns': value(system) * 100, 'user_cpu_ns': value(user) * 100})
                        finally:
                            kernel.CloseHandle(handle)
                more = kernel.Thread32Next(snapshot, C.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        source = 'GetThreadTimes'
    elif sys.platform.startswith('linux'):
        ticks = os.sysconf('SC_CLK_TCK')
        for path in Path('/proc/self/task').glob('*/stat'):
            try:
                # comm may contain spaces or parentheses; fields after ')' start
                # at field3. utime/stime/starttime are fields14/15/22.
                fields = path.read_text().rsplit(')', 1)[1].split()
                rows.append({'tid': int(path.parent.name), 'creation': int(fields[19]),
                             'kernel_cpu_ns': int(fields[12]) * 1_000_000_000 // ticks,
                             'user_cpu_ns': int(fields[11]) * 1_000_000_000 // ticks})
            except (FileNotFoundError, ProcessLookupError):
                pass
        source = 'proc-task-stat'
    else:
        return {'available': False, 'reason': 'unsupported thread sampler', 'threads': []}
    return {'available': True, 'source': source, 'threads': sorted(rows, key=lambda item: item['tid'])}


class Recorder:
    def __init__(self, max_records=20000, thread_sample_interval=0):
        _limits(max_records, thread_sample_interval)
        self.max_records, self.thread_sample_interval = max_records, thread_sample_interval
        self.records, self.thread_samples = [], []
        self.current = None
        self.dropped_records = 0
        self.requests = 0

    def measure(self, label, function, *args, **kwargs):
        start = _clocks()
        try:
            return function(*args, **kwargs)
        finally:
            if self.current is not None:
                wall, thread, process = _delta(start)
                metric = self.current['metrics'].setdefault(label,
                    dict(calls=0, wall_ns=0, thread_cpu_ns=0, process_cpu_ns=0, max_wall_ns=0))
                metric['calls'] += 1; metric['wall_ns'] += wall
                metric['thread_cpu_ns'] += thread; metric['process_cpu_ns'] += process
                metric['max_wall_ns'] = max(metric['max_wall_ns'], wall)

    def sample_threads(self, request_id):
        if not self.thread_sample_interval or len(self.thread_samples) >= self.max_records:
            return 0
        start = time.perf_counter_ns()
        try:
            sample = thread_cpu_snapshot()
        except Exception as error:
            sample = {'available': False, 'reason': type(error).__name__, 'threads': []}
        elapsed = time.perf_counter_ns() - start
        sample.update(request_id=request_id, perf_counter_ns=start, sample_wall_ns=elapsed)
        self.thread_samples.append(sample)
        return elapsed

    def read(self, original, source):
        # The preceding write normally ends the prior record. Malformed/truncated
        # input may create a final partial record, explicitly marked below.
        if self.current is not None:
            self.finish(False)
        self.current = {'request_id': None, 'operation': None, 'frame': None, 'metrics': {}}
        start = _clocks()
        message = original(source)
        elapsed = _delta(start)
        if message is None:
            self.current = None
            return None
        operation, flags, request_id, frame, metadata, payload = message
        self.requests += 1
        self.current.update(request_id=request_id, operation=OPERATIONS.get(operation, str(operation)), frame=frame,
                            request_payload_bytes=len(payload), receive_wall_ns=elapsed[0],
                            receive_thread_cpu_ns=elapsed[1], receive_process_cpu_ns=elapsed[2])
        observer = 0
        if self.requests == 1 or (self.thread_sample_interval and self.requests % self.thread_sample_interval == 0):
            observer = self.sample_threads(request_id)
        self.current['observer_thread_sample_wall_ns'] = observer
        self.current['_active_start'] = _clocks()
        return message

    def write(self, original, sink, packet):
        result = self.measure('ipc.write', original, sink, packet)
        if self.current is not None:
            from server import simulation_worker as ipc
            operation, flags, request_id, frame, metadata_size, payload_size = ipc.decode_header(packet[:ipc.HEADER.size])
            self.current.update(response_bytes=len(packet), response_metadata_bytes=metadata_size,
                                response_payload_bytes=payload_size, response_error=bool(flags))
            self.finish(True)
        return result

    def finish(self, replied):
        if self.current is None:
            return
        row, self.current = self.current, None
        start = row.pop('_active_start', None)
        if start is not None:
            wall, thread, process = _delta(start)
            row.update(active_wall_ns=wall, active_thread_cpu_ns=thread, active_process_cpu_ns=process)
        row['replied'] = replied
        if len(self.records) < self.max_records:
            self.records.append(row)
        else:
            self.dropped_records += 1


@contextmanager
def instrumentation(recorder):
    """Install wrappers only inside this explicitly launched diagnostic child."""
    from server import native_ai, native_simulation, simulation_worker as ipc, worker_ai
    replacements = []
    def replace(owner, name, replacement):
        original = getattr(owner, name)
        replacements.append((owner, name, original))
        setattr(owner, name, replacement(original))
    def timed(label):
        def build(original):
            @wraps(original)
            def call(*args, **kwargs):
                return recorder.measure(label, original, *args, **kwargs)
            return call
        return build
    def exports(prefix):
        def build(original):
            @wraps(original)
            def call(instance, name, *args):
                return recorder.measure(prefix + name, original, instance, name, *args)
            return call
        return build
    try:
        replace(native_simulation._Runtime, 'call', exports('sim.'))
        replace(native_ai._Runtime, 'call', exports('ai.'))
        replace(native_simulation, 'decode_snapshot', timed('decode_snapshot'))
        replace(native_ai, 'decode_action_queue', timed('decode_ai_actions'))
        for name in ('process_frame', 'snapshot_bytes', 'state'):
            replace(native_simulation.NativeSimulation, name, timed('simulation.' + name))
        replace(native_ai.NativeAI, 'commands', timed('ai.commands'))
        replace(worker_ai.WorkerAI, 'prepare', timed('worker.prepare_bots'))
        replace(worker_ai.WorkerAI, 'before_step', timed('worker.validate_bot_frame'))
        replace(ipc, 'decode_metadata', timed('ipc.decode_metadata'))
        replace(ipc, 'encode_message', timed('ipc.encode'))
        replace(ipc, 'read_message', lambda original: lambda source: recorder.read(original, source))
        replace(ipc, 'write_packet', lambda original: lambda sink, packet: recorder.write(original, sink, packet))
        yield
    finally:
        for owner, name, original in reversed(replacements):
            setattr(owner, name, original)


def source_hashes(hybrid=False):
    names = ('tools/profile_worker_timing.py', 'server/worker_client.py', 'server/simulation_worker.py',
             'server/native_simulation.py', 'server/native_ai.py', 'server/worker_ai.py')
    if hybrid:
        names += HYBRID_PROFILE_SOURCES
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def main(argv=None):
    from server import simulation_worker as ipc
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stdio', required=True, action='store_true')
    parser.add_argument('--test-backend', action='store_true')
    parser.add_argument('--profile-output', type=Path, required=True)
    parser.add_argument('--max-records', type=int, default=20000)
    parser.add_argument('--thread-sample-interval', type=int, default=0)
    parser.add_argument('--profile-hybrid-worker', action='store_true')
    args = parser.parse_args(argv)
    _limits(args.max_records, args.thread_sample_interval)
    if args.test_backend and os.environ.get('BA_ENABLE_SYNTHETIC_WORKER_TESTS') != '1':
        parser.error('synthetic backend requires explicit test environment gate')
    if args.profile_hybrid_worker and (args.test_backend or os.name != 'nt' or sys.platform != 'win32' or sys.maxsize <= 2**32):
        parser.error('hybrid profile requires the actual Windows x64 native worker')
    if not args.profile_output.is_absolute():
        parser.error('profile output must be absolute')
    # Reserve the destination before any native execution. No frame-time writes.
    with args.profile_output.open('x', encoding='utf-8') as output:
        recorder = Recorder(args.max_records, args.thread_sample_interval)
        hashes = source_hashes(args.profile_hybrid_worker)
        sink = ipc.isolate_protocol_stdout()
        exit_code = 2
        failure = None
        try:
            with instrumentation(recorder):
                exit_code = ipc.serve(sys.stdin.buffer, sink, test_backend=args.test_backend)
        except Exception as error:
            failure = type(error).__name__
            print(f'Profiled worker failed: {failure}: {error}', file=sys.stderr, flush=True)
        finally:
            recorder.finish(False)
            recorder.sample_threads(recorder.requests)
            sink.close()
            report = dict(schema=1, completed=True, exit_code=exit_code, failure=failure, pid=os.getpid(),
                synthetic_test_backend=args.test_backend, source_sha256=hashes,
                launch_kind='native-linux-wine-worker' if args.profile_hybrid_worker else 'direct-worker',
                clock_resolution_seconds={name: time.get_clock_info(name).resolution
                                          for name in ('perf_counter', 'thread_time', 'process_time')},
                metric_scope='inclusive nested timings; do not sum parent and child',
                records=recorder.records, dropped_records=recorder.dropped_records,
                thread_samples=recorder.thread_samples,
                limitations=['live-thread samples omit threads that exit between samples',
                             'instrumentation overhead requires an unprofiled paired control',
                             'forced kill leaves no completed report'])
            json.dump(report, output, separators=(',', ':'), allow_nan=False)
            output.write('\n')
            output.flush()
        return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
