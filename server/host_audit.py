"""Bounded local host diagnostics; no uploader or raw game-data capture."""
from datetime import datetime, timezone
import json
from pathlib import Path
import stat
import time
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
        if not self.diagnostics and event in self.HIGH_FREQUENCY: return
        record = dict(utc=datetime.now(timezone.utc).isoformat(), perf_counter_ns=time.perf_counter_ns(),
                      session=self.session, event=event, **fields)
        encoded = (json.dumps(record, separators=(',', ':'), ensure_ascii=False) + '\n').encode('utf-8')
        if len(encoded) > self.max_bytes:
            encoded = (json.dumps(dict(utc=record['utc'], session=self.session, event='audit_record_omitted',
                original_event=str(event)[:128], bytes=len(encoded)), separators=(',', ':')) + '\n').encode('utf-8')
        if self.size + len(encoded) > self.max_bytes: self._rotate()
        self.stream.write(encoded); self.size += len(encoded)

    def close(self):
        if self.stream is not None: self.stream.close(); self.stream = None
