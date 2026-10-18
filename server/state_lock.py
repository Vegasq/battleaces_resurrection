"""Exclusive process lifetime lock for one deployed host data directory."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat


class StateBusyError(ValueError):
    pass


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
            acquired = True
        except OSError:
            raise StateBusyError('Server data is in use; stop the host and any maintenance command first') from None
        # Lock the byte range before initialization. This also recovers a
        # first-start crash between exclusive creation and writing the byte.
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b'\0'); stream.flush(); os.fsync(stream.fileno())
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
