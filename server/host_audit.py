"""Bounded local host diagnostics; no uploader or raw game-data capture."""
from datetime import datetime, timezone
import asyncio
from collections import deque
import json
from pathlib import Path
import stat
import time
import threading
import uuid


class HostAudit:
    HIGH_FREQUENCY = frozenset(('frame_queued', 'frame_received', 'input_received', 'input_accepted', 'native_snapshot'))

    def __init__(self, directory, *, max_bytes, backups, diagnostics=False):
        if type(max_bytes) is not int or max_bytes < 65536 or type(backups) is not int or not 1 <= backups <= 16:
            raise ValueError('invalid local audit retention limits')
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.paths = [self.directory / ('events.jsonl' + (f'.{i}' if i else '')) for i in range(backups+1)]
        self.max_bytes, self.diagnostics = max_bytes, diagnostics
        self.session = uuid.uuid4().hex
        self.stream = None
        self._check_files()
        self.stream = self.paths[0].open('ab', buffering=0)
        self.size = self.stream.tell()

    def _check_files(self):
        for path in self.paths:
            try: info = path.lstat()
            except FileNotFoundError: continue
            if not stat.S_ISREG(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('audit files must be ordinary local files')

    def _rotate(self):
        self._check_files()
        self.stream.close(); self.stream = None
        # Only this audit's fixed filenames are rotated, never a directory tree.
        self.paths[-1].unlink(missing_ok=True)
        for index in range(len(self.paths)-2, -1, -1):
            if self.paths[index].exists(): self.paths[index].replace(self.paths[index+1])
        self.stream = self.paths[0].open('xb', buffering=0); self.size = 0

    def __call__(self, event, **fields):
        encoded = self._encode(event, fields)
        if encoded is not None: self._append(encoded)

    def _encode(self, event, fields):
        if not self.diagnostics and event in self.HIGH_FREQUENCY: return
        record = dict(utc=datetime.now(timezone.utc).isoformat(), perf_counter_ns=time.perf_counter_ns(),
                      session=self.session, event=event, **fields)
        encoded = (json.dumps(record, separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')
        if len(encoded) > self.max_bytes:
            encoded = (json.dumps(dict(utc=record['utc'], session=self.session, event='audit_record_omitted',
                original_event=str(event)[:128], bytes=len(encoded)), separators=(',', ':')) + '\n').encode('utf-8')
        return encoded

    def _append(self, encoded):
        if self.size + len(encoded) > self.max_bytes: self._rotate()
        if self.stream.write(encoded) != len(encoded):
            raise OSError('incomplete local audit write')
        self.size += len(encoded)

    def close(self):
        if self.stream is not None: self.stream.close(); self.stream = None


class AuditQueueFull(OSError):
    """The bounded audit writer could not accept another record."""


class QueuedHostAudit(HostAudit):
    """Encode on the producer; one owned thread performs ordered file I/O.

    Limits include the in-flight record. A full queue stops acceptance and drains
    accepted records. A write failure abandons remaining records. Both notify the
    host and make close fail; subsequent calls are counted as rejected, allowing
    the host's worker/resource cleanup to finish without logging exceptions.
    """
    ASYNCHRONOUS = True

    def __init__(self, directory, *, max_bytes, backups, diagnostics=False,
                 max_pending_records=1024, max_pending_bytes=None, on_failure=None):
        if max_pending_bytes is None: max_pending_bytes = 2 * max_bytes
        if (type(max_pending_records) is not int or max_pending_records < 1 or
                type(max_pending_bytes) is not int or max_pending_bytes < max_bytes):
            raise ValueError('invalid audit queue limits')
        self._condition = threading.Condition()
        self._queue = deque()
        self._closing = self._closed = False
        self._error = self._notification_error = None
        self._on_failure = on_failure
        self._accepted = self._written = self._rejected = self._abandoned = 0
        self._pending_records = self._pending_bytes = 0
        self._peak_records = self._peak_bytes = 0
        self._record_limit, self._byte_limit = max_pending_records, max_pending_bytes
        self._close_task = None
        super().__init__(directory, max_bytes=max_bytes, backups=backups, diagnostics=diagnostics)
        self._thread = threading.Thread(target=self._write_loop, name='host-audit', daemon=False)
        try: self._thread.start()
        except BaseException:
            super().close()
            raise

    def _fail_locked(self, error):
        first = self._error is None
        if first: self._error = error
        self._closing = True
        self._condition.notify_all()
        return first

    def _notify_failure(self):
        if self._on_failure is not None:
            try: self._on_failure()
            except Exception as error:
                with self._condition: self._notification_error = error

    def __call__(self, event, **fields):
        notify = False
        with self._condition:
            if self._closing:
                self._rejected += 1
                if self._error is None: raise RuntimeError('audit writer is closed')
                return
            encoded = self._encode(event, fields)
            if encoded is None: return
            if (self._pending_records >= self._record_limit or
                    self._pending_bytes + len(encoded) > self._byte_limit):
                self._rejected += 1
                notify = self._fail_locked(AuditQueueFull('local audit queue capacity exceeded'))
            else:
                self._queue.append(encoded)
                self._accepted += 1
                self._pending_records += 1
                self._pending_bytes += len(encoded)
                self._peak_records = max(self._peak_records, self._pending_records)
                self._peak_bytes = max(self._peak_bytes, self._pending_bytes)
                self._condition.notify()
        if notify: self._notify_failure()

    def _write_loop(self):
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._queue or self._closing)
                    if not self._queue: break
                    encoded = self._queue.popleft()
                self._append(encoded)
                with self._condition:
                    self._written += 1
                    self._pending_records -= 1
                    self._pending_bytes -= len(encoded)
                # Do not retain an already-accounted buffer while awaiting work.
                del encoded
        except BaseException as error:
            with self._condition:
                notify = self._fail_locked(error)
                self._abandoned += self._pending_records
                self._pending_records = self._pending_bytes = 0
                self._queue.clear()
            if notify: self._notify_failure()
        finally:
            try: super().close()
            except BaseException as error:
                with self._condition: notify = self._fail_locked(error)
                if notify: self._notify_failure()
            finally:
                with self._condition:
                    self._closed = True
                    self._condition.notify_all()

    def raise_if_failed(self):
        with self._condition:
            if self._error is not None: raise self._error

    def status(self):
        with self._condition:
            return dict(asynchronous=True, accepted=self._accepted, written=self._written,
                rejected=self._rejected, abandoned=self._abandoned,
                pending_records=self._pending_records, pending_bytes=self._pending_bytes,
                peak_records=self._peak_records, peak_bytes=self._peak_bytes,
                record_limit=self._record_limit, byte_limit=self._byte_limit,
                failed=self._error is not None, closed=self._closed,
                thread_alive=self._thread.is_alive(),
                error_type=type(self._error).__name__ if self._error else None,
                notification_error=type(self._notification_error).__name__ if self._notification_error else None)

    def close(self):
        with self._condition:
            self._closing = True
            self._condition.notify_all()
        self._thread.join()
        self.raise_if_failed()

    async def aclose(self):
        if self._close_task is None:
            self._close_task = asyncio.create_task(asyncio.to_thread(self.close))
        cancelled = False
        while not self._close_task.done():
            try: await asyncio.shield(self._close_task)
            except asyncio.CancelledError: cancelled = True
        self._close_task.result()
        if cancelled: raise asyncio.CancelledError
