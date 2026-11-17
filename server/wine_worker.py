"""Explicit Linux coordinator -> isolated Windows/Wine simulation backend.

Only a deliberately prepared private template is accepted. Every launch clones
it into a new prefix, with symlinks preserved, and owns a Linux guardian. There
is no shared-prefix wineserver termination and no fallback to a test backend.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
import select
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time

TEMPLATE_MARKER = '.battleaces-worker-template.json'
TEMPLATE_PURPOSE = 'battleaces-isolated-worker-template'
ROOT = Path(__file__).resolve().parents[1]
GUARDIAN_BOOTSTRAP = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('server.wine_worker_guardian',run_name='__main__')"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def private_path(path, *, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o077
            and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)),
            'Wine template and marker must be owned private regular paths')


def windows_path(value):
    """Translate an existing absolute host path through the validated Z: map."""
    path = Path(value)
    require(path.is_absolute(), 'Wine worker paths must be absolute host paths')
    path = path.resolve(strict=True)
    require(not any(any(char in part for char in '\\:*?"<>|\r\n\0') for part in path.parts[1:]),
            'host path cannot be represented safely in Wine')
    return 'Z:\\' + '\\'.join(path.parts[1:])


def snapshot_decoder_path(library_path, expected_sha256):
    """A Wine worker loads a hash-bound Windows x64 DLL, never a host ELF library."""
    if library_path is None and expected_sha256 is None:
        return None
    from .rust_snapshot_decoder import verified_library_path
    path = verified_library_path(library_path, expected_sha256)
    with path.open('rb') as stream:
        header = stream.read(64)
        require(len(header) == 64 and header[:2] == b'MZ', 'Wine snapshot decoder must be a Windows x64 DLL')
        offset = struct.unpack_from('<I', header, 60)[0]
        require(64 <= offset <= 1024*1024, 'invalid snapshot decoder PE offset')
        stream.seek(offset); pe = stream.read(24)
        require(len(pe) == 24 and pe[:4] == b'PE\0\0' and struct.unpack_from('<H', pe, 4)[0] == 0x8664
                and struct.unpack_from('<H', pe, 22)[0] & 0x2000,
                'Wine snapshot decoder must be a Windows x64 DLL')
    return path


def validate_template(prefix):
    require(prefix != Path.home()/'.wine', 'the default user Wine prefix is not a worker template')
    private_path(prefix, directory=True)
    marker = prefix/TEMPLATE_MARKER
    private_path(marker)
    require(marker.stat().st_size <= 4096, 'Wine template marker exceeds limit')
    value = json.loads(marker.read_text(encoding='utf-8'))
    require(value == {'format': 1, 'purpose': TEMPLATE_PURPOSE, 'uid': os.getuid()},
            'Wine prefix lacks the explicit isolated-worker template marker')
    require((prefix/'drive_c').is_dir() and not (prefix/'drive_c').is_symlink(), 'Wine template drive_c is invalid')
    for name in ('system.reg', 'user.reg'):
        info = (prefix/name).lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), 'Wine template registry is not an owned file')
        require((prefix/name).stat().st_size > 0, 'Wine template is not initialized')
    require((prefix/'dosdevices').is_dir() and not (prefix/'dosdevices').is_symlink(), 'Wine template drive map is invalid')
    drive = prefix/'dosdevices/z:'
    require(drive.is_symlink() and drive.resolve(strict=True) == Path('/'), 'Wine template requires Z: mapped to host root')
    drive_c = prefix/'dosdevices/c:'
    require(drive_c.is_symlink() and os.readlink(drive_c) == '../drive_c'
            and drive_c.resolve(strict=True) == prefix/'drive_c',
            'Wine template C: must use the clone-relative ../drive_c mapping')


@dataclass(frozen=True)
class WineWorkerBackend:
    wine_executable: Path
    windows_python: Path
    prefix_template: Path
    cgroup_parent: Path | None = None

    def __post_init__(self):
        require(sys.platform.startswith('linux') and platform.machine().lower() in ('x86_64', 'amd64')
                and struct.calcsize('P') == 8, 'Wine workers require native Linux x64 Python')
        require(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'), 'Wine workers require Linux pidfd support')
        for name in ('wine_executable', 'windows_python', 'prefix_template'):
            path = Path(getattr(self, name))
            require(path.is_absolute(), 'Wine backend paths must be explicit absolute paths')
            # A symlink to somebody else's user prefix is never accepted.
            if name == 'prefix_template':
                require(not path.is_symlink(), 'Wine template may not be a symlink')
            object.__setattr__(self, name, path.resolve(strict=True))
        require(self.wine_executable.is_file() and os.access(self.wine_executable, os.X_OK), 'Wine executable is not executable')
        require(not self.wine_executable.stat().st_mode & 0o022, 'Wine executable must not be group/world writable')
        require(self.windows_python.is_file(), 'Windows Python executable is missing')
        with self.windows_python.open('rb') as stream:
            header = stream.read(64)
            require(len(header) == 64 and header[:2] == b'MZ', 'worker interpreter must be Windows x64 Python')
            offset = struct.unpack_from('<I', header, 60)[0]
            require(64 <= offset <= 1024*1024, 'invalid Windows interpreter PE offset')
            stream.seek(offset); pe = stream.read(24)
            require(len(pe) == 24 and pe[:4] == b'PE\0\0' and struct.unpack_from('<H', pe, 4)[0] == 0x8664,
                    'worker interpreter must be Windows x64 Python')
        validate_template(self.prefix_template)
        from .wine_worker_cgroup import current_cgroup, validate_parent
        parent = current_cgroup() if self.cgroup_parent is None else Path(self.cgroup_parent)
        require(parent.is_absolute(), 'Wine cgroup parent must be absolute')
        object.__setattr__(self, 'cgroup_parent', validate_parent(parent))

    def translate_path(self, path):
        return windows_path(path)

    def launch(self, *, source_root, working_directory, snapshot_decoder_library=None, snapshot_decoder_sha256=None):
        require(Path(source_root).resolve() == ROOT, 'Wine worker source must be the coordinator checkout')
        directory = Path(working_directory).resolve(strict=True)
        require(directory.is_dir(), 'Wine worker working directory must exist')
        require(not directory.is_relative_to(self.prefix_template), 'worker scratch may not be inside the Wine template')
        decoder_path = snapshot_decoder_path(snapshot_decoder_library, snapshot_decoder_sha256)
        if decoder_path is not None:
            self.translate_path(decoder_path)  # Refuse unrepresentable paths before allocating ownership resources.
        validate_template(self.prefix_template)
        # No synthetic environment gate or external loader override crosses the
        # backend boundary. Command arguments are always an argv list, no shell.
        environment = dict(os.environ)
        for name in ('BA_ENABLE_SYNTHETIC_WORKER_TESTS', 'WINEPREFIX', 'WINEARCH', 'WINELOADER', 'WINESERVER',
                     'WINEDLLPATH', 'WINEDLLOVERRIDES', 'WINEDEBUG', 'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME',
                     'DISPLAY', 'WAYLAND_DISPLAY'):
            environment.pop(name, None)
        from .wine_worker_cgroup import OwnedCgroup
        runtime = Path(tempfile.mkdtemp(prefix='ba-wine-worker-', dir=directory))
        try:
            cgroup = OwnedCgroup(self.cgroup_parent/runtime.name, create=True)
        except BaseException:
            runtime.rmdir()
            raise
        watch_read, watch_write = os.pipe()
        status_read, status_write = os.pipe()
        try:
            command = [sys.executable, '-I', '-S', '-B', '-u', '-c', GUARDIAN_BOOTSTRAP, str(ROOT),
                '--wine', str(self.wine_executable), '--windows-python', str(self.windows_python),
                '--prefix-template', str(self.prefix_template), '--working-directory', str(directory),
                '--runtime-directory', str(runtime), '--cgroup', str(cgroup.path),
                '--parent-pid', str(os.getpid()), '--watch-fd', str(watch_read), '--status-fd', str(status_write)]
            if decoder_path is not None:
                command.extend(['--snapshot-decoder-library', str(decoder_path),
                                '--snapshot-decoder-sha256', snapshot_decoder_sha256])
            process = subprocess.Popen(command, cwd=directory, env=environment, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, close_fds=True,
                pass_fds=(watch_read, status_write), start_new_session=True)
        except BaseException:
            os.close(watch_write); os.close(status_read)
            cgroup.cleanup(); cgroup.close(); runtime.rmdir()
            raise
        finally:
            os.close(watch_read); os.close(status_write)
        try:
            owner = WineWorkerOwner(process, watch_write, status_read, cgroup, runtime, directory)
        except BaseException:
            os.close(watch_write); os.close(status_read)
            process.wait(timeout=12)
            from .wine_worker_guardian import remove_runtime
            cgroup.cleanup(); cgroup.close(); remove_runtime(runtime, directory)
            for stream in (process.stdin, process.stdout, process.stderr): stream.close()
            raise
        return process, owner


class WineWorkerOwner:
    """Monitor guardian death independently; cgroup ownership survives reparenting."""
    def __init__(self, process, watch_fd, status_fd, cgroup, runtime, working_directory):
        from .wine_worker_guardian import process_identity
        self.process, self.watch_fd, self.status_fd = process, watch_fd, status_fd
        self.statistics = None
        self.failure = None
        self.cgroup, self.runtime, self.working_directory = cgroup, runtime, working_directory
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._callback = None
        self._notified = False
        self._pidfd = os.pidfd_open(process.pid)
        try:
            identity = process_identity(process.pid)
            require(identity is not None and identity[0] == os.getpid(), 'Wine guardian owner identity differs')
            self._birth = identity[1]
        except BaseException:
            os.close(self._pidfd)
            raise
        self._monitor_thread = threading.Thread(target=self._monitor, name=f'ba-wine-owner-{process.pid}', daemon=True)
        try:
            self._monitor_thread.start()
        except BaseException:
            os.close(self._pidfd)
            raise

    def on_exit(self, callback):
        with self._lock:
            self._callback = callback
        self._notify()

    def _notify(self):
        callback = None
        with self._lock:
            if self._done.is_set() and self._callback is not None and not self._notified:
                self._notified = True
                callback = self._callback
        if callback is not None:
            callback()

    def _monitor(self):
        from .wine_worker_guardian import remove_runtime
        report = None
        try:
            select.select([self._pidfd], [], [])
            self.process.wait()
            raw = b''
            while select.select([self.status_fd], [], [], 0)[0]:
                part = os.read(self.status_fd, 4096)
                if not part: break
                raw += part
                if len(raw) > 4096: raise RuntimeError('Wine guardian status exceeded limit')
            if raw:
                report = json.loads(raw)
                if not isinstance(report, dict): raise RuntimeError('invalid Wine guardian status')
            if report is None or report.get('cleanup_complete') is not True:
                self.failure = 'Wine guardian exited without complete cleanup status'
            started = time.perf_counter()
            group_removed = self.cgroup.cleanup()
            prefix_removed = group_removed and remove_runtime(self.runtime, self.working_directory)
            report = report or {'schema': 1, 'guardian_pid': self.process.pid, 'exit_code': self.process.returncode,
                                'native_exit_code': None, 'parent_recovery': True}
            report.update(cgroup_removed=group_removed, prefix_removed=prefix_removed,
                          cleanup_complete=group_removed and prefix_removed,
                          parent_cleanup_ms=(time.perf_counter()-started)*1000)
            if not report['cleanup_complete']:
                self.failure = 'Wine parent could not complete owned cgroup/prefix cleanup'
        except BaseException as error:
            self.failure = f'Wine owner cleanup failed: {type(error).__name__}: {error}'
            # Status parsing can fail independently of ownership. Always attempt
            # kernel-scoped cleanup even when no valid guardian report survives.
            try:
                group_removed = self.cgroup.cleanup()
                prefix_removed = group_removed and remove_runtime(self.runtime, self.working_directory)
            except Exception:
                group_removed = prefix_removed = False
            report = {'schema': 1, 'guardian_pid': self.process.pid, 'parent_recovery': True,
                      'exit_code': self.process.returncode, 'native_exit_code': None,
                      'cgroup_removed': group_removed, 'prefix_removed': prefix_removed,
                      'cleanup_complete': group_removed and prefix_removed}
        finally:
            if self.failure is not None: report['owner_failure'] = self.failure
            self.statistics = report
            self.cgroup.close()
            with self._lock:
                os.close(self.status_fd); self.status_fd = None
                os.close(self._pidfd); self._pidfd = None
                if self.watch_fd is not None:
                    os.close(self.watch_fd); self.watch_fd = None
            self._done.set()
            self._notify()

    def request_stop(self):
        """Signal the existing guardian without allocating another cleanup thread."""
        with self._lock:
            if self.watch_fd is not None:
                os.close(self.watch_fd); self.watch_fd = None

    def close(self, *, deadline=None):
        self.request_stop()
        deadline = time.monotonic()+9.5 if deadline is None else deadline
        # Reserve recovery time inside one caller-owned monotonic deadline. The
        # preceding lock/ACK/process waits consume that same budget.
        grace = max(0, min(5, deadline-time.monotonic()-3))
        if not self._done.wait(grace):
            with self._lock:
                if self._pidfd is not None:
                    try: signal.pidfd_send_signal(self._pidfd, signal.SIGKILL)
                    except ProcessLookupError: pass
            if not self._done.wait(max(0, deadline-time.monotonic())):
                raise RuntimeError('Wine owner exceeded its cleanup budget')
        self._monitor_thread.join(timeout=.1)
        if self.failure is not None:
            raise RuntimeError(self.failure)
