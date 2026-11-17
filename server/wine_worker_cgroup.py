"""One delegated cgroup-v2 per Wine worker, retaining ownership after daemonization."""
from __future__ import annotations
import ctypes
import os
from pathlib import Path, PurePosixPath
import re
import time


def current_cgroup():
    """Map the actual unified hierarchy through this process's cgroup2 mount."""
    rows = [line.split(':', 2) for line in Path('/proc/self/cgroup').read_text().splitlines()]
    groups = [PurePosixPath(row[2]) for row in rows if len(row) == 3 and row[:2] == ['0', '']]
    if len(groups) != 1 or not groups[0].is_absolute() or '..' in groups[0].parts:
        raise ValueError('Wine workers require an identifiable unified cgroup-v2 hierarchy')
    unescape = lambda value: re.sub(r'\\([0-7]{3})', lambda item: chr(int(item[1], 8)), value)
    candidates = []
    for row in Path('/proc/self/mountinfo').read_text().splitlines():
        before, separator, after = row.partition(' - ')
        fields = before.split()
        if not separator or not after.startswith('cgroup2 ') or len(fields) < 5:
            continue
        root, mount = PurePosixPath(unescape(fields[3])), Path(unescape(fields[4]))
        if groups[0].is_relative_to(root):
            candidate = (mount/str(groups[0].relative_to(root))).resolve(strict=True)
            try:
                members = (candidate/'cgroup.procs').read_text().split()
            except OSError:
                continue
            if str(os.getpid()) in members:
                candidates.append((len(root.parts), candidate))
    if not candidates:
        raise ValueError('cannot bind the coordinator to its mounted cgroup-v2 directory')
    return max(candidates, key=lambda item: item[0])[1]


def validate_parent(path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(current_cgroup()):
        raise ValueError('Wine cgroup parent must remain inside the coordinator supervisor hierarchy')
    if not path.is_dir() or not (path/'cgroup.controllers').is_file() or not os.access(path, os.W_OK):
        raise ValueError('Wine workers require a writable delegated cgroup-v2 parent')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.statfs.argtypes = [ctypes.c_char_p, ctypes.c_void_p]; libc.statfs.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(256)
    if libc.statfs(os.fsencode(path), buffer) or ctypes.c_long.from_buffer(buffer).value != 0x63677270:
        raise ValueError('Wine worker process ownership requires the cgroup-v2 filesystem')
    return path


class OwnedCgroup:
    def __init__(self, path, *, create=False):
        self.path = Path(path)
        if not self.path.name.startswith('ba-wine-worker-'):
            raise ValueError('invalid Wine worker cgroup identity')
        validate_parent(self.path.parent)
        if create:
            self.path.mkdir(mode=0o700)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.identity = os.fstat(self.fd)
        try:
            for name in ('cgroup.kill', 'cgroup.procs', 'cgroup.events'):
                if not (self.path/name).is_file():
                    raise ValueError('Wine workers require cgroup.kill and cgroup.events support')
        except BaseException:
            os.close(self.fd)
            if create: self.path.rmdir()
            raise

    def _same(self):
        try:
            current = self.path.lstat()
        except FileNotFoundError:
            return False
        if (current.st_dev, current.st_ino) != (self.identity.st_dev, self.identity.st_ino):
            raise RuntimeError('owned Wine cgroup path identity changed')
        return True

    def join_current(self):
        """Called before exec in the guardian's single-threaded fork child."""
        descriptor = os.open('cgroup.procs', os.O_WRONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        try: os.write(descriptor, str(os.getpid()).encode())
        finally: os.close(descriptor)

    def populated(self):
        descriptor = os.open('cgroup.events', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        try:
            values = dict(line.split() for line in os.read(descriptor, 4096).decode('ascii').splitlines())
        finally: os.close(descriptor)
        if values.get('populated') not in ('0', '1'):
            raise RuntimeError('invalid Wine cgroup populated state')
        return values['populated'] == '1'

    def kill_and_wait(self, timeout=2.0):
        if not self._same():
            return True  # A populated cgroup cannot be removed; the other owner completed cleanup.
        descriptor = os.open('cgroup.kill', os.O_WRONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        try: os.write(descriptor, b'1')
        finally: os.close(descriptor)
        deadline = time.monotonic()+timeout
        while self.populated():
            if time.monotonic() >= deadline:
                return False
            time.sleep(.01)
        return True

    def cleanup(self, timeout=2.0):
        if not self.kill_and_wait(timeout):
            return False
        if self._same():
            self.path.rmdir()
        return True

    def close(self):
        if self.fd is not None:
            os.close(self.fd); self.fd = None
