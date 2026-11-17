"""Private Linux subreaper for one cloned Wine prefix, not a network service."""
from __future__ import annotations

import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

from .wine_worker import ROOT, TEMPLATE_MARKER, WineWorkerBackend, require, snapshot_decoder_path

WORKER_BOOTSTRAP = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('server.simulation_worker',run_name='__main__')"


def worker_command(backend, *, snapshot_decoder_library=None, snapshot_decoder_sha256=None):
    """Build explicit Windows argv after rechecking the host decoder identity."""
    command = [str(backend.wine_executable), backend.translate_path(backend.windows_python),
               '-I', '-S', '-B', '-u', '-c', WORKER_BOOTSTRAP, backend.translate_path(ROOT), '--stdio']
    decoder_path = snapshot_decoder_path(snapshot_decoder_library, snapshot_decoder_sha256)
    if decoder_path is not None:
        command.extend(['--snapshot-decoder-library', backend.translate_path(decoder_path),
                        '--snapshot-decoder-sha256', snapshot_decoder_sha256])
    return command


class Stopped(Exception):
    pass


def _prctl(option, argument):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(option, argument, 0, 0, 0):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return int(fields[1]), int(fields[19]), fields[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def descendants(parent, root_birth=None):
    """Read only process ancestry/creation ticks; never inspect other environments."""
    root = process_identity(parent)
    if root is None or (root_birth is not None and root[1] != root_birth):
        return {}
    identities = {}
    for directory in Path('/proc').iterdir():
        if directory.name.isdecimal():
            pid = int(directory.name)
            try:
                identity = process_identity(pid)
            except PermissionError:
                continue
            if identity is not None:
                identities[pid] = identity
    current = process_identity(parent)
    if current is None or current[1] != root[1]:
        return {}
    owned, frontier = {}, {parent}
    while frontier:
        following = {pid for pid, value in identities.items() if value[0] in frontier and pid not in owned and pid != parent}
        owned.update((pid, identities[pid]) for pid in following)
        frontier = following
    return owned


def _signal_owned(pid, identity, signum, parent, root_birth):
    try:
        handle = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    try:
        # pidfd prevents signalling a reused numeric PID after this check.
        # Re-check ancestry as well as birth ticks before taking action.
        current = descendants(parent, root_birth).get(pid)
        if current is not None and current[1] == identity[1]:
            signal.pidfd_send_signal(handle, signum)
    except ProcessLookupError:
        pass
    finally:
        os.close(handle)


def _reap(main_process=None):
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return True
        if not pid:
            return False
        if main_process is not None and pid == main_process.pid:
            main_process.returncode = os.waitstatus_to_exitcode(status)


def terminate_descendants(parent, *, root_birth=None, timeout=5.0, reap=True, main_process=None):
    """Terminate only this guardian's tree, including adopted daemon children."""
    root = process_identity(parent)
    if root_birth is None:
        require(parent == os.getpid(), 'external descendant cleanup requires a bound guardian identity')
        root_birth = root[1] if root is not None else None
    started = time.monotonic()
    seen = set()
    while True:
        no_children = _reap(main_process) if reap else False
        owned = descendants(parent, root_birth)
        if not owned and (not reap or no_children):
            return {'complete': True, 'descendants_seen': len(seen)}
        elapsed = time.monotonic()-started
        if elapsed >= timeout:
            return {'complete': False, 'descendants_seen': len(seen), 'remaining': sorted(owned)}
        signum = signal.SIGTERM if elapsed < .25 else signal.SIGKILL
        for pid, identity in owned.items():
            seen.add((pid, identity[1]))
            _signal_owned(pid, identity, signum, parent, root_birth)
        time.sleep(.02)


def clone_template(source, destination, check_stop):
    """Copy files with cancellation points; symlinks are copied, never traversed."""
    def copy_file(old, new):
        check_stop()
        identity = os.lstat(old)
        require(stat.S_ISREG(identity.st_mode), 'Wine template contains a nonregular file')
        descriptor = os.open(old, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as reader:
            current = os.fstat(reader.fileno())
            require(stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino),
                    'Wine template file changed during clone')
            destination_fd = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(destination_fd, 'wb') as writer:
                while True:
                    check_stop()
                    block = reader.read(1024*1024)
                    if not block:
                        break
                    writer.write(block)
                os.fchmod(writer.fileno(), stat.S_IMODE(current.st_mode))
        os.utime(new, ns=(current.st_atime_ns, current.st_mtime_ns), follow_symlinks=False)
        return new
    shutil.copytree(source, destination, symlinks=True, copy_function=copy_file)
    check_stop()


def remove_runtime(runtime, working_directory):
    if runtime is None:
        return True
    # Only the unique directory this guardian just created is removable. rmtree
    # on Linux uses dirfd protections and does not traverse the cloned Z: symlink.
    require(runtime.name.startswith('ba-wine-worker-') and runtime.parent.resolve() == working_directory
            and not runtime.is_symlink() and runtime.resolve().is_relative_to(working_directory),
            'refusing unsafe Wine scratch cleanup')
    require(shutil.rmtree.avoids_symlink_attacks, 'platform lacks safe directory cleanup')
    if not runtime.exists():
        return True
    shutil.rmtree(runtime)
    return not runtime.exists()


def run(args):
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    _prctl(36, 1)  # PR_SET_CHILD_SUBREAPER: adopted double-fork Wine services remain owned.
    _prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG; the pipe closes the setup/parent-PID race too.
    require(os.getsid(0) == os.getpid(), 'Wine guardian requires its own session')
    if os.getppid() != args.parent_pid:
        stopped = True
    def check_stop():
        nonlocal stopped
        if select.select([args.watch_fd], [], [], 0)[0]:
            # Parent only retains a write handle, never sends control data.
            os.read(args.watch_fd, 1)
            stopped = True
        if stopped:
            raise Stopped('worker owner closed or exited')
    process, runtime, cgroup = None, None, None
    report = {'schema': 1, 'guardian_pid': os.getpid(), 'cleanup_complete': False}
    working_directory = args.working_directory.resolve(strict=True)
    code = 2
    try:
        from .wine_worker_cgroup import OwnedCgroup
        runtime = args.runtime_directory.resolve(strict=True)
        require(runtime.parent == working_directory and runtime.name.startswith('ba-wine-worker-')
                and not args.runtime_directory.is_symlink(), 'invalid owned Wine runtime directory')
        cgroup = OwnedCgroup(args.cgroup)
        check_stop()
        backend = WineWorkerBackend(args.wine, args.windows_python, args.prefix_template, args.cgroup.parent)
        require(working_directory.is_dir() and not working_directory.is_relative_to(backend.prefix_template),
                'invalid Wine guardian working directory')
        command = worker_command(backend, snapshot_decoder_library=args.snapshot_decoder_library,
                                 snapshot_decoder_sha256=args.snapshot_decoder_sha256)
        import fcntl
        # The prepared template is a source, not a running deployment prefix.
        # Cooperating template preparation takes an exclusive marker lock.
        with (backend.prefix_template/TEMPLATE_MARKER).open('rb') as marker:
            fcntl.flock(marker, fcntl.LOCK_SH | fcntl.LOCK_NB)
            prefix = runtime/'prefix'
            started = time.perf_counter()
            clone_template(backend.prefix_template, prefix, check_stop)
            report['prefix_clone_ms'] = (time.perf_counter()-started)*1000
        scratch = runtime/'work'; scratch.mkdir(mode=0o700)
        environment = dict(os.environ)
        environment.update(WINEPREFIX=str(prefix), WINEARCH='win64', WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=')
        check_stop()
        launched = time.perf_counter()
        guardian_pid = os.getpid()
        require(len(list(Path('/proc/self/task').iterdir())) == 1,
                'Wine guardian pre-exec ownership requires a single-threaded process')
        def child_setup():
            # This guardian is deliberately single-threaded. Establish kernel
            # death ownership and cgroup membership BEFORE executing any Wine
            # loader code; no Python-startup gap outside the owned cgroup.
            _prctl(1, signal.SIGKILL)
            if os.getppid() != guardian_pid:
                os._exit(125)
            cgroup.join_current()
            os.close(cgroup.fd)
        process = subprocess.Popen(command, cwd=scratch, env=environment, stdin=sys.stdin.buffer,
                                   stdout=sys.stdout.buffer, stderr=sys.stderr.buffer, close_fds=True,
                                   pass_fds=(cgroup.fd,), preexec_fn=child_setup)
        report['wine_launcher_pid'] = process.pid
        while process.poll() is None:
            check_stop()
            select.select([args.watch_fd], [], [], .02)
        code = process.returncode
        report['worker_lifetime_ms'] = (time.perf_counter()-launched)*1000
    except Stopped:
        report['stop_reason'] = 'owner_closed_or_exited'
        code = 125
    except Exception as error:
        report['failure'] = type(error).__name__
        print(f'Wine worker guardian failed: {type(error).__name__}: {error}', file=sys.stderr, flush=True)
    finally:
        started = time.perf_counter()
        try:
            cleanup = terminate_descendants(os.getpid(), timeout=3, main_process=process)
            group_removed = cgroup.cleanup() if cgroup is not None else True
            if group_removed and not cleanup['complete']:
                cleanup = terminate_descendants(os.getpid(), timeout=.5, main_process=process)
            report['process_cleanup'] = cleanup
            report['cgroup_removed'] = group_removed
            if cleanup['complete'] and group_removed:
                report['prefix_removed'] = remove_runtime(runtime, working_directory)
            report['cleanup_complete'] = cleanup['complete'] and group_removed and report.get('prefix_removed', False)
            if not report['cleanup_complete']:
                code = 126
        except Exception as error:
            report['cleanup_failure'] = type(error).__name__
            code = 126
        report.update(cleanup_ms=(time.perf_counter()-started)*1000, exit_code=code,
                      native_exit_code=process.returncode if process else None)
        try:
            encoded = json.dumps(report, separators=(',', ':'), allow_nan=False).encode()
            require(len(encoded) <= 4096, 'guardian status exceeded limit')
            os.write(args.status_fd, encoded)
        except (BrokenPipeError, OSError):
            pass  # Owner may have died; cleanup still ran to completion.
        os.close(args.status_fd); os.close(args.watch_fd)
        if cgroup is not None: cgroup.close()
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wine', type=Path, required=True)
    parser.add_argument('--windows-python', type=Path, required=True)
    parser.add_argument('--prefix-template', type=Path, required=True)
    parser.add_argument('--working-directory', type=Path, required=True)
    parser.add_argument('--runtime-directory', type=Path, required=True)
    parser.add_argument('--cgroup', type=Path, required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--watch-fd', type=int, required=True)
    parser.add_argument('--status-fd', type=int, required=True)
    parser.add_argument('--snapshot-decoder-library', type=Path)
    parser.add_argument('--snapshot-decoder-sha256')
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    raise SystemExit(main())
