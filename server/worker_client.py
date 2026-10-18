"""Async supervision of one private native simulation subprocess per match."""
from __future__ import annotations
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading

from . import simulation_worker as ipc

ROOT = Path(__file__).resolve().parents[1]


class WorkerError(RuntimeError):
    """Terminal worker failure; the coordinator must stop the affected match."""


class WorkerTimeout(WorkerError):
    pass


@dataclass(frozen=True)
class FrameResult:
    frame: int
    game_time_seconds: int
    state: dict


class _WindowsJob:
    """Unnamed owned job: an ungraceful parent exit also kills its worker."""
    def __init__(self, pid):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                        ("minimum_working_set", c.c_size_t), ("maximum_working_set", c.c_size_t),
                        ("active_processes", w.DWORD), ("affinity", c.c_size_t),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Counters(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]
        class Limits(c.Structure):
            _fields_ = [("basic", Basic), ("io", Counters), ("process_memory", c.c_size_t),
                        ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]
        kernel = c.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]; kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]; kernel.SetInformationJobObject.restype = w.BOOL
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; kernel.OpenProcess.restype = w.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]; kernel.AssignProcessToJobObject.restype = w.BOOL
        kernel.CloseHandle.argtypes = [w.HANDLE]; kernel.CloseHandle.restype = w.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise WorkerError(f"CreateJobObject failed: {c.get_last_error()}")
        process = None
        try:
            limits = Limits(); limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
            if not kernel.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
                raise WorkerError(f"SetInformationJobObject failed: {c.get_last_error()}")
            process = kernel.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE.
            if not process or not kernel.AssignProcessToJobObject(self.handle, process):
                raise WorkerError(f"AssignProcessToJobObject failed: {c.get_last_error()}")
        except BaseException:
            self.close()
            raise
        finally:
            if process: kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def normalize_state(state):
    if not isinstance(state, dict) or type(state.get("frame")) is not int:
        raise WorkerError("invalid worker state")
    resources = state.get("resources")
    if not isinstance(resources, dict):
        raise WorkerError("invalid worker resource state")
    # JSON object keys are strings; restore NativeSimulation's integer army keys.
    state["resources"] = {int(army): values for army, values in resources.items()}
    return state


class SimulationWorker:
    def __init__(self, process, *, request_timeout, close_timeout, test_backend):
        self.process = process
        self.request_timeout, self.close_timeout = request_timeout, close_timeout
        self._test_backend = test_backend
        self._lock = asyncio.Lock()
        self._request_id = 0
        self._terminal = False
        self._cleanup_task = None
        self._job = None
        self.frame = -1
        self.game_time_seconds = 0
        self.last_state = None
        self.failure = None
        self.game_data_sha256 = None
        self.dll_sha256 = None
        self.ai_info = self._bot_roster = self._prepared_bots = None
        self._stderr = deque(maxlen=8)  # At most eight 4096-byte chunks retained.
        self._stderr_lock = threading.Lock()
        self._io = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"ba-worker-{process.pid}")
        self._stderr_thread = threading.Thread(target=self._drain_stderr, name=f"ba-stderr-{process.pid}", daemon=True)
        self._stderr_thread.start()

    @classmethod
    async def create(cls, game_data, dll_path=None, *, startup_timeout=120.0, request_timeout=3.0,
                     close_timeout=2.0, working_directory=None, ai=None, _test_backend=False):
        if not isinstance(game_data, bytes) or not 1 <= len(game_data) <= ipc.MAX_PAYLOAD:
            raise ValueError("GameData must contain 1..32 MiB of raw bytes")
        if any(not isinstance(value, (int, float)) or not 0 < value <= 600
               for value in (startup_timeout, request_timeout, close_timeout)):
            raise ValueError("worker timeouts must be in (0,600] seconds")
        if os.name != "nt" and not _test_backend:
            raise WorkerError("production simulation workers require Windows x64")
        roster = None
        if ai is not None:
            from .worker_ai import AISetup, BotRoster
            if not isinstance(ai, AISetup) or _test_backend:
                raise ValueError('native AI requires an explicit AISetup and native worker')
            roster = BotRoster(game_data, ai.bots)
        # Keep native output in the caller's writable data directory while loading
        # only our module tree. Neither cwd, PYTHONPATH nor user site packages may
        # select a different worker. Works with a relocated embeddable runtime too.
        bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('server.simulation_worker',run_name='__main__')"
        args = [sys.executable, "-I", "-S", "-B", "-u", "-c", bootstrap, str(ROOT), "--stdio"]
        working_directory = Path(working_directory).resolve() if working_directory is not None else ROOT
        if not working_directory.is_dir(): raise ValueError('worker working directory must already exist')
        environment = os.environ.copy()
        if _test_backend:
            args.append("--test-backend")
            environment["BA_ENABLE_SYNTHETIC_WORKER_TESTS"] = "1"
        else:
            environment.pop("BA_ENABLE_SYNTHETIC_WORKER_TESTS", None)
        # Anonymous pipes avoid Windows Proactor's named-pipe requirements. Only
        # private I/O threads block on them; the coordinator event loop does not.
        process = subprocess.Popen(args, cwd=working_directory, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            bufsize=0, close_fds=True)
        worker = cls(process, request_timeout=request_timeout, close_timeout=close_timeout, test_backend=_test_backend)
        try:
            worker._job = _WindowsJob(process.pid)
            async with worker._lock:
                metadata = {"dll_path": str(Path(dll_path).resolve())} if dll_path is not None else {}
                if ai is not None: metadata['ai'] = ai.wire()
                response, payload = await worker._exchange(ipc.CREATE, -1, metadata, game_data, timeout=startup_timeout)
                expected = hashlib.sha256(game_data).hexdigest()
                if payload or response.get("pid") != process.pid or response.get("game_data_sha256") != expected:
                    raise WorkerError("worker CREATE identity/digest mismatch")
                if response.get("synthetic_test_backend") is not bool(_test_backend):
                    raise WorkerError("unexpected worker backend")
                ai_info = response.get('ai')
                if ai is None:
                    if ai_info is not None: raise WorkerError('unexpected worker AI')
                else:
                    from .ai_rules import SUPPORTED_AI_SHA256
                    if not (isinstance(ai_info, dict) and ai_info.get('bots') == ai.wire()['bots'] and
                            ai_info.get('dll_sha256') == SUPPORTED_AI_SHA256 and
                            isinstance(ai_info.get('manifest_sha256'), str) and len(ai_info['manifest_sha256']) == 64):
                        raise WorkerError('worker AI assignment/digest mismatch')
                worker.ai_info, worker._bot_roster = ai_info, roster
                worker.game_data_sha256 = expected
                worker.dll_sha256 = response.get("dll_sha256")
            return worker
        except BaseException as error:
            worker.failure = str(error)
            await worker._abort()
            raise

    @property
    def pid(self):
        return self.process.pid

    @property
    def closed(self):
        return self._terminal or self.process.poll() is not None

    @property
    def stderr_tail(self):
        with self._stderr_lock:
            return b"".join(self._stderr).decode("utf-8", "replace")

    def _drain_stderr(self):
        while True:
            chunk = self.process.stderr.read(4096)
            if not chunk: return
            with self._stderr_lock:
                self._stderr.append(chunk)

    def _wire_exchange(self, packet, operation, request_id, frame):
        ipc.write_packet(self.process.stdin, packet)
        header = ipc.read_exact(self.process.stdout, ipc.HEADER.size)
        reply_op, flags, reply_id, reply_frame, metadata_size, payload_size = ipc.decode_header(header)
        if (reply_op, reply_id, reply_frame) != (operation | ipc.RESPONSE, request_id, frame):
            raise WorkerError("worker response operation/request/frame mismatch")
        metadata = ipc.decode_metadata(ipc.read_exact(self.process.stdout, metadata_size))
        payload = ipc.read_exact(self.process.stdout, payload_size)
        if flags:
            raise WorkerError(f"worker rejected request: {metadata.get('error')}: {metadata.get('message')}")
        return metadata, payload

    async def _exchange(self, operation, frame, metadata=None, payload=b"", *, timeout=None):
        if self.closed:
            raise WorkerError(f"worker unavailable (exit={self.process.returncode}): {self.failure or 'closed'}")
        self._request_id += 1
        packet = ipc.encode_message(operation, self._request_id, frame, metadata, payload)
        try:
            pending = asyncio.get_running_loop().run_in_executor(self._io, self._wire_exchange,
                                                                 packet, operation, self._request_id, frame)
            return await asyncio.wait_for(pending,
                                          timeout if timeout is not None else self.request_timeout)
        except BaseException as error:
            self.failure = f"{type(error).__name__}: {error}"
            await self._abort()
            if isinstance(error, asyncio.CancelledError): raise
            if isinstance(error, TimeoutError):
                raise WorkerTimeout(f"simulation worker timed out on operation {operation}") from error
            if isinstance(error, WorkerError): raise
            raise WorkerError(f"simulation worker failed on operation {operation}: {error}") from error

    async def bot_inputs(self, frame):
        from .worker_ai import unpack_inputs
        async with self._lock:
            if self._bot_roster is None or type(frame) is not int or frame != self.frame + 1 or self._prepared_bots is not None:
                raise ValueError('bot inputs require one request before the next AI frame')
            response, payload = await self._exchange(ipc.BOT_INPUT, frame)
            try:
                if response.get('sha256') != hashlib.sha256(payload).hexdigest():
                    raise ValueError('bot input digest mismatch')
                inputs = unpack_inputs(payload)
                self._bot_roster.check_inputs(inputs)
            except (ValueError, KeyError, TypeError) as error:
                self.failure = str(error)
                await self._abort()
                raise WorkerError('invalid prepared bot inputs') from error
            self._prepared_bots = dict(inputs)
            return inputs

    async def process_frame(self, actions, dt_ms=None):
        from .native_simulation import _protobuf_header
        if not isinstance(actions, bytes) or not 1 <= len(actions) <= ipc.MAX_PAYLOAD:
            raise ValueError("InputActions must contain 1..32 MiB of raw bytes")
        frame, step = _protobuf_header(actions)
        if dt_ms is not None and dt_ms != step:
            raise ValueError("step differs from InputActions time step")
        async with self._lock:
            if frame != self.frame + 1:
                raise ValueError(f"expected frame {self.frame + 1}, received {frame}")
            if self._bot_roster is not None:
                if self._prepared_bots is None: raise ValueError('prepare bot inputs before STEP')
                self._bot_roster.check_frame(actions, self._prepared_bots)
            response, payload = await self._exchange(ipc.STEP, frame, {"dt_ms": step}, actions)
            try:
                state = normalize_state(response["state"])
                seconds = response["game_time_seconds"]
                if payload or response.get("input_sha256") != hashlib.sha256(actions).hexdigest() or state["frame"] != frame or type(seconds) is not int:
                    raise WorkerError("worker step state/digest mismatch")
            except (KeyError, ValueError, TypeError, WorkerError) as error:
                self.failure = str(error)
                await self._abort()
                raise WorkerError("invalid completed-step response") from error
            self.frame, self.game_time_seconds, self.last_state = frame, seconds, state
            self._prepared_bots = None
            return FrameResult(frame, seconds, state)

    async def state(self, viewer=31, *, include_entities=False):
        async with self._lock:
            response, payload = await self._exchange(ipc.STATE, self.frame, {"viewer": viewer, "include_entities": include_entities})
            try:
                state = normalize_state(response["state"])
                expected = 0xFFFFFFFF if self.frame == -1 and not self._test_backend else self.frame
                if payload or state["frame"] != expected: raise WorkerError("state frame differs")
                return state
            except (KeyError, ValueError, TypeError, WorkerError) as error:
                self.failure = str(error)
                await self._abort()
                raise WorkerError("invalid state response") from error

    async def snapshot(self, viewer=31):
        async with self._lock:
            response, payload = await self._exchange(ipc.SNAPSHOT, self.frame, {"viewer": viewer})
            if not payload or len(payload) > 16 * 1024 * 1024 or response.get("sha256") != hashlib.sha256(payload).hexdigest():
                self.failure = "invalid snapshot response"
                await self._abort()
                raise WorkerError(self.failure)
            return payload

    async def _test_control(self, action):
        if not self._test_backend: raise WorkerError("test controls disabled")
        async with self._lock:
            await self._exchange(ipc.TEST_CONTROL, self.frame, {"action": action})

    async def _cleanup(self):
        self._terminal = True
        # Terminate before closing pipe objects: another thread may be blocked
        # inside their read/write methods. Child exit releases those calls.
        if self.process.poll() is None:
            try: self.process.terminate()
            except ProcessLookupError: pass
        try:
            await asyncio.to_thread(self.process.wait, timeout=self.close_timeout)
        except subprocess.TimeoutExpired:
            if self.process.poll() is None:
                try: self.process.kill()
                except ProcessLookupError: pass
            await asyncio.to_thread(self.process.wait, timeout=self.close_timeout)
        finally:
            if self._job is not None: self._job.close()
            await asyncio.to_thread(self._stderr_thread.join, self.close_timeout)
            await asyncio.to_thread(self._io.shutdown, wait=True, cancel_futures=True)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()

    async def _abort(self):
        self._terminal = True
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup())
        await asyncio.shield(self._cleanup_task)

    async def close(self):
        if self.closed:
            await self._abort()
            return
        acquired = False
        try:
            await asyncio.wait_for(self._lock.acquire(), self.close_timeout)
            acquired = True
            if not self.closed:
                await self._exchange(ipc.CLOSE, self.frame, timeout=self.close_timeout)
                await asyncio.to_thread(self.process.wait, timeout=self.close_timeout)
        except (WorkerError, TimeoutError, subprocess.TimeoutExpired):
            pass  # A stuck destructor cannot prevent owned-process cleanup.
        finally:
            if acquired: self._lock.release()
            await self._abort()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()
