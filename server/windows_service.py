"""Windows SCM adapter for the packaged host; registration is an owner action.

Connect to SCM before loading assets or verifying the package. A RUNNING report
means native health checks succeeded and the listener is open. Control callbacks
schedule one cancellation, leaving the host's existing finally/close path intact.
"""
from __future__ import annotations

import asyncio
from contextlib import redirect_stderr, redirect_stdout
import ctypes as c
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

STOPPED, START_PENDING, STOP_PENDING, RUNNING = 1, 2, 3, 4
STOP, INTERROGATE, SHUTDOWN = 1, 4, 5
ACCEPT_STOP_SHUTDOWN = 0x1 | 0x4
ERROR_CALL_NOT_IMPLEMENTED = 120
ERROR_SERVICE_SPECIFIC_ERROR = 1066
START_TIMEOUT, STOP_TIMEOUT = 60.0, 15.0
DEFAULT_NAME = 'BattleAcesResurrection'
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}\Z')
PACKAGE = Path(__file__).resolve().parents[3]
STAGES = ('package_checked', 'configuration_loaded', 'assets_and_storage_checked', 'native_checked')


class ServiceError(ValueError):
    """Fixed, safe diagnostics; no config contents, keys or exception text."""


def service_name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ServiceError('Use a service name of1..64 ASCII letters, digits, underscores or hyphens, starting with a letter')
    return value


def registration(package, config, name=DEFAULT_NAME):
    """Return an exact native argv/SCM ImagePath without editing the registry."""
    from .configuration import load_config
    package = Path(package).resolve()
    config = Path(config).resolve()
    service_name(name)
    # Do not register a relative/network path or invoke a shell/command script.
    if not package.is_absolute() or str(package).startswith('\\\\') or str(config).startswith('\\\\'):
        raise ServiceError('Service program and configuration must use local absolute paths')
    executable = package / 'program/runtime/python.exe'
    if not executable.is_file(): raise ServiceError('Bundled Windows runtime is missing')
    load_config(config)
    argv = [str(executable), '-I', '-B', '-m', 'server.windows_service', '--name', name, '--config', str(config)]
    if any(any(ord(character) < 32 or character == '"' for character in arg) for arg in argv):
        raise ServiceError('Service paths contain unsupported characters')
    return dict(name=name, binary_path=subprocess.list2cmdline(argv), argv=argv,
                config=str(config), startup='Manual', account='Use the account that provisioned the private host files')


@dataclass(frozen=True)
class Status:
    state: int
    controls: int = 0
    checkpoint: int = 0
    wait_hint_ms: int = 0
    win32_exit: int = 0
    specific_exit: int = 0


class ServiceController:
    """Thread-safe SCM lifecycle, with absolute deadlines, not fake heartbeats.

    A deadline exits this service process abnormally. Its kill-on-close worker
    jobs then terminate any stuck native children. Never claim STOPPED before
    cleanup and executor shutdown have returned. Timers are daemon threads.
    """
    def __init__(self, report, *, terminate=os._exit, start_timeout=START_TIMEOUT, stop_timeout=STOP_TIMEOUT):
        if not 0 < start_timeout <= START_TIMEOUT or not 0 < stop_timeout <= STOP_TIMEOUT:
            raise ValueError('invalid service deadline')
        self.report, self.terminate = report, terminate
        self.start_timeout, self.stop_timeout = start_timeout, stop_timeout
        self.lock = threading.RLock()
        self.status = None
        self.stop_requested = False
        self.loop = self.task = self.timer = None
        self.generation = 0
        self.deadline = 0.0
        self.stage = -1
        self.started = False

    def _publish(self, status):
        self.status = status
        self.report(status)

    def _cancel_timer(self):
        self.generation += 1
        if self.timer: self.timer.cancel(); self.timer = None

    def _arm(self, seconds):
        self._cancel_timer()
        self.deadline = time.monotonic() + seconds
        generation = self.generation
        def expired():
            with self.lock:
                if generation == self.generation and self.status.state in (START_PENDING, STOP_PENDING):
                    self.terminate(1)
        self.timer = threading.Timer(seconds, expired)
        self.timer.daemon = True
        self.timer.start()

    def progress(self, stage):
        with self.lock:
            if stage == 'stopping':
                self._begin_stopping()
                return
            index = STAGES.index(stage)
            if self.status.state != START_PENDING or index <= self.stage: return
            self.stage = index
            remaining = max(1, int((self.deadline-time.monotonic())*1000))
            self._publish(Status(START_PENDING, checkpoint=self.status.checkpoint+1, wait_hint_ms=remaining))

    def ready(self, address):
        with self.lock:
            if self.status.state != START_PENDING or self.stop_requested: return
            self._cancel_timer()
            self._publish(Status(RUNNING, controls=ACCEPT_STOP_SHUTDOWN))

    def _begin_stopping(self):
        if self.status.state in (STOP_PENDING, STOPPED): return False
        self._publish(Status(STOP_PENDING, checkpoint=1, wait_hint_ms=int(self.stop_timeout*1000)))
        self._arm(self.stop_timeout)
        return True

    def control(self, code):
        with self.lock:
            if code == INTERROGATE: return 0
            if code not in (STOP, SHUTDOWN): return ERROR_CALL_NOT_IMPLEMENTED
            if self.status is None or self.status.state == STOPPED: return 0
            if self.stop_requested: return 0
            self.stop_requested = True
            # An internal runtime failure may already be cleaning up. A later
            # external Stop must neither cancel that cleanup nor reset its timer.
            newly_stopping = self._begin_stopping()
            if newly_stopping and self.loop is not None and self.task is not None:
                # Cancel exactly once. Repeated controls must not interrupt the
                # native destructor, listener close or profile flush in finally.
                self.loop.call_soon_threadsafe(self.task.cancel)
            return 0

    async def _run(self, factory):
        with self.lock:
            self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
        try:
            if self.stop_requested: return
            await factory(self.ready, self.progress)
            if not self.stop_requested: raise ServiceError('Host returned without a stop request')
        except asyncio.CancelledError:
            if not self.stop_requested: raise
        finally:
            with self.lock: self.loop = self.task = None

    def execute(self, factory):
        with self.lock:
            if self.started: raise ServiceError('A service controller can run only once')
            self.started = True
            self._publish(Status(START_PENDING, checkpoint=1, wait_hint_ms=int(self.start_timeout*1000)))
            self._arm(self.start_timeout)
        failure = 0
        try:
            asyncio.run(self._run(factory))
        except BaseException:
            # Arbitrary filesystem/native exception strings may contain private
            # values. SCM records a fixed code; console check gives safe details.
            failure = 1
        with self.lock:
            self._cancel_timer()
            if self.status.state != STOP_PENDING:
                self._publish(Status(STOP_PENDING, checkpoint=1, wait_hint_ms=1))
            # Last action after cleanup. A stopped SCM status handle is not used
            # again; Windows may terminate the process as soon as this returns.
            self._publish(Status(STOPPED, win32_exit=ERROR_SERVICE_SPECIFIC_ERROR if failure else 0,
                                 specific_exit=failure))
        return failure


class WindowsSCM:
    """ctypes definitions are local so source-only tests can import elsewhere."""
    def __init__(self):
        if os.name != 'nt' or c.sizeof(c.c_void_p) != 8: raise ServiceError('Service requires64-bit Windows')
        DWORD = c.c_uint32
        self.main_type = c.WINFUNCTYPE(None, DWORD, c.POINTER(c.c_wchar_p))
        self.handler_type = c.WINFUNCTYPE(DWORD, DWORD, DWORD, c.c_void_p, c.c_void_p)
        class Table(c.Structure):
            _fields_ = [('name', c.c_wchar_p), ('main', self.main_type)]
        class NativeStatus(c.Structure):
            _fields_ = [(name, DWORD) for name in ('type', 'state', 'controls', 'exit', 'specific', 'checkpoint', 'wait')]
        self.Table, self.NativeStatus = Table, NativeStatus
        self.api = a = c.WinDLL('advapi32', use_last_error=True)
        a.StartServiceCtrlDispatcherW.argtypes = [c.POINTER(Table)]
        a.StartServiceCtrlDispatcherW.restype = c.c_int
        a.RegisterServiceCtrlHandlerExW.argtypes = [c.c_wchar_p, self.handler_type, c.c_void_p]
        a.RegisterServiceCtrlHandlerExW.restype = c.c_void_p
        a.SetServiceStatus.argtypes = [c.c_void_p, c.POINTER(NativeStatus)]
        a.SetServiceStatus.restype = c.c_int

    def dispatch(self, name, factory):
        service_name(name)
        controller = None
        result = 1
        @self.handler_type
        def handler(code, event_type, event_data, context):
            try: return controller.control(code) if controller else 0
            except BaseException:
                os._exit(1)  # Never let an exception cross a native callback.
        @self.main_type
        def main(argc, argv):
            nonlocal controller, result
            try:
                handle = self.api.RegisterServiceCtrlHandlerExW(name, handler, None)
                if not handle: os._exit(1)
                def report(status):
                    native = self.NativeStatus(0x10, status.state, status.controls, status.win32_exit,
                                               status.specific_exit, status.checkpoint, status.wait_hint_ms)
                    if not self.api.SetServiceStatus(handle, c.byref(native)): os._exit(1)
                controller = ServiceController(report)
                # Services have no console; do not depend on inherited stdio.
                with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
                    result = controller.execute(factory)
            except BaseException:
                os._exit(1)
        # Keep callback objects and the null-terminated table alive throughout
        # the blocking dispatcher call, including handler invocations on threads.
        table = (self.Table*2)(self.Table(name, main), self.Table(None, self.main_type()))
        if not self.api.StartServiceCtrlDispatcherW(table):
            code = c.get_last_error()
            if code == 1063: raise ServiceError('Run this entry through Windows Services; use start for console hosting')
            raise ServiceError('Cannot connect to Windows Service Control Manager (Windows error ' + str(code) + ')')
        return result


async def packaged_host(config_path, ready, progress):
    # Import and verify after connecting to SCM. No asset or credential work is
    # done on the dispatch thread or in a control callback.
    from tools.package_integrity import verify
    from .configuration import load_config
    from .host import run
    verify(PACKAGE, 'server')
    progress('package_checked')
    config = load_config(config_path)
    progress('configuration_loaded')
    await run(config, on_progress=progress, on_ready=ready)


def main(argv=None):
    from tools.package_integrity import SafeParser
    parser = SafeParser(description=__doc__)
    parser.add_argument('--name', default=DEFAULT_NAME)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        service_name(args.name)
        if not args.config.is_absolute(): raise ServiceError('Service requires an absolute config path')
        return WindowsSCM().dispatch(args.name, lambda ready, progress: packaged_host(args.config, ready, progress))
    except (OSError, ServiceError) as error:
        print(str(error) if isinstance(error, ServiceError) else 'Service OS initialization failed', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
