"""Exclusive process lifetime lock for one deployed host data directory."""
from contextlib import contextmanager
import ctypes
import errno
import os
import platform
import sys
from pathlib import Path
import stat


class StateBusyError(ValueError):
    pass


class _LinuxFlock(ctypes.Structure):
    # Qualified Linux x86-64 LP64 ABI; tests also compile the system C header.
    _fields_ = [('l_type', ctypes.c_short), ('l_whence', ctypes.c_short),
                ('l_start', ctypes.c_int64), ('l_len', ctypes.c_int64), ('l_pid', ctypes.c_int32)]


def _linux_record_lock(fd):
    """Conflict with legacy Wine's F_SETLK without POSIX close-any-fd lifetime."""
    import fcntl
    layout = [getattr(_LinuxFlock, name).offset for name, _ in _LinuxFlock._fields_]
    if (platform.machine().lower() not in ('x86_64', 'amd64') or
            ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(ctypes.c_long) != 8 or
            ctypes.sizeof(_LinuxFlock) != 32 or layout != [0, 2, 8, 16, 24]):
        raise StateBusyError('Linux state locking requires the supported x86-64 OFD ABI')
    operation = getattr(fcntl, 'F_OFD_SETLK', None)
    if operation is None:
        raise StateBusyError('Required Linux OFD state locking is unavailable; no unsafe fallback')
    lock = _LinuxFlock(fcntl.F_WRLCK, os.SEEK_SET, 0, 1, 0)
    try:
        fcntl.fcntl(fd, operation, bytes(lock))
    except OSError as error:
        if error.errno in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.ENOLCK):
            raise StateBusyError('Linux kernel or filesystem lacks required OFD state locking; no unsafe fallback') from error
        raise


@contextmanager
def exclusive_state(directory):
    """Serialize packaged host/check/backup; OS releases the lock after a crash.

    The persistent file has no PID-based ownership and is never deleted while
    locking. This is an advisory boundary for our deployment entry points, not
    protection against an administrator or unrelated tools modifying state.
    """
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'.host.lock'
    try:
        with path.open('xb'): pass
    except FileExistsError: pass
    information = path.lstat()
    if (not stat.S_ISREG(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400
            or information.st_size not in (0, 1)):
        raise StateBusyError('Host state lock is not a regular bounded file')
    stream = path.open('r+b')
    acquired = False
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True  # Release flock even when the second lock fails.
                if sys.platform.startswith('linux'):
                    _linux_record_lock(stream.fileno())
            acquired = True
        except OSError:
            raise StateBusyError('Server data is in use; stop the host and any maintenance command first') from None
        # Lock the byte range before initialization. This also recovers a
        # first-start crash between exclusive creation and writing the byte.
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'\0'); stream.flush(); os.fsync(stream.fileno())
        yield
    finally:
        try:
            if acquired:
                if os.name == 'nt':
                    stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            # Closing this exact description releases its OFD byte lock, even
            # if an unlock operation failed. Other opens/closes cannot release it.
            stream.close()
