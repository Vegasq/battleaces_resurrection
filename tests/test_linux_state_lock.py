"""Production lock regression controls; actual Unix semantics run only on Linux."""
from contextlib import contextmanager
import ctypes
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from server import state_lock as locks
from tests.test_linux_ofd_lock_candidate import LINUX_X64, ROOT, record_state


@contextmanager
def mocked_linux_abi():
    """Exercise fail-closed syscall handling on Windows without a native syscall."""
    fake = SimpleNamespace(F_OFD_SETLK=37, F_WRLCK=1, fcntl=mock.Mock(), flock=mock.Mock())
    actual_sizeof = ctypes.sizeof
    def sizeof(kind):
        return 8 if kind is ctypes.c_long else actual_sizeof(kind)
    with mock.patch.dict(sys.modules, fcntl=fake), mock.patch.object(locks.platform, 'machine', return_value='x86_64'), \
            mock.patch.object(locks.ctypes, 'sizeof', side_effect=sizeof):
        yield fake


PRODUCTION_TRY = '''import sys
sys.path.insert(0,sys.argv[1])
from server.state_lock import exclusive_state,StateBusyError
from tests.test_linux_ofd_lock_candidate import record_state
try:
    lock=exclusive_state(sys.argv[3]) if sys.argv[2]=='production' else record_state(sys.argv[3])
    with lock: pass
except (BlockingIOError,StateBusyError): sys.exit(2)
'''


def child_result(kind, directory):
    child = subprocess.run([sys.executable, '-I', '-B', '-c', PRODUCTION_TRY, str(ROOT), kind, str(directory)],
                           capture_output=True, timeout=5)
    if child.returncode not in (0, 2):
        raise AssertionError(f'production lock control failed: {child.returncode}: {child.stderr!r}')
    return child.returncode


class ProductionStateLockGuards(unittest.TestCase):
    def test_linux_record_lock_uses_exact_one_byte_ofd_request(self):
        with mocked_linux_abi() as fcntl:
            locks._linux_record_lock(123)
            fd, operation, payload = fcntl.fcntl.call_args.args
            self.assertEqual((fd, operation, len(payload)), (123, 37, 32))
            value = locks._LinuxFlock.from_buffer_copy(payload)
            self.assertEqual((value.l_type, value.l_whence, value.l_start, value.l_len, value.l_pid),
                             (1, os.SEEK_SET, 0, 1, 0))
            self.assertEqual([getattr(locks._LinuxFlock, n).offset for n, _ in locks._LinuxFlock._fields_],
                             [0, 2, 8, 16, 24])

    def test_unsupported_abi_or_operation_never_attempts_fallback(self):
        with mocked_linux_abi() as fcntl:
            with mock.patch.object(locks.platform, 'machine', return_value='aarch64'):
                with self.assertRaisesRegex(locks.StateBusyError, 'supported x86-64'):
                    locks._linux_record_lock(123)
            fcntl.fcntl.assert_not_called()
            del fcntl.F_OFD_SETLK
            with self.assertRaisesRegex(locks.StateBusyError, 'no unsafe fallback'):
                locks._linux_record_lock(123)
            fcntl.fcntl.assert_not_called()
            fcntl.flock.assert_not_called()

    def test_kernel_and_filesystem_rejections_are_actionable_and_fail_closed(self):
        for code in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.ENOLCK):
            with self.subTest(errno=code), mocked_linux_abi() as fcntl:
                fcntl.fcntl.side_effect = OSError(code, 'authored unsupported kernel/filesystem')
                with self.assertRaisesRegex(locks.StateBusyError, 'no unsafe fallback'):
                    locks._linux_record_lock(123)
                fcntl.fcntl.assert_called_once()
                fcntl.flock.assert_not_called()

    def test_record_contention_is_not_misclassified_as_unsupported_kernel(self):
        with mocked_linux_abi() as fcntl:
            fcntl.fcntl.side_effect = BlockingIOError(errno.EAGAIN, 'held by a record-lock owner')
            with self.assertRaises(BlockingIOError):
                locks._linux_record_lock(123)

    @unittest.skipUnless(os.name == 'nt', 'native Windows branch control')
    def test_windows_lock_does_not_attempt_linux_syscall(self):
        with tempfile.TemporaryDirectory(prefix='ba-state-windows-') as folder:
            with mock.patch.object(locks, '_linux_record_lock', side_effect=AssertionError('Windows used OFD')) as linux:
                with locks.exclusive_state(folder):
                    pass
                linux.assert_not_called()

    def test_unlock_error_still_closes_owned_descriptor_and_releases_lock(self):
        with tempfile.TemporaryDirectory(prefix='ba-state-unlock-') as folder:
            context = locks.exclusive_state(folder)
            context.__enter__()
            if os.name == 'nt':
                import msvcrt
                owner, method = msvcrt, 'locking'
            else:
                import fcntl
                owner, method = fcntl, 'flock'
            with mock.patch.object(owner, method, side_effect=OSError('authored unlock failure')):
                with self.assertRaisesRegex(OSError, 'authored unlock failure'):
                    context.__exit__(None, None, None)
            with locks.exclusive_state(folder):
                pass


@unittest.skipUnless(LINUX_X64, 'actual production OFD semantics require Linux x86-64')
class ProductionStateLockLinuxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ba-state-linux-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root/'state'
        self.state.mkdir()
        (self.state/'.host.lock').write_bytes(b'\0')

    def test_production_and_posix_record_owners_block_both_directions(self):
        with locks.exclusive_state(self.state):
            self.assertEqual(child_result('record', self.state), 2)
            self.assertEqual(child_result('production', self.state), 2)
        with record_state(self.state):
            self.assertEqual(child_result('production', self.state), 2)
        self.assertEqual(child_result('production', self.state), 0)

    def test_failed_nested_attempt_and_other_descriptor_close_preserve_record_lock(self):
        with locks.exclusive_state(self.state):
            with self.assertRaises(locks.StateBusyError):
                with locks.exclusive_state(self.state):
                    self.fail('nested lock was admitted')
            with (self.state/'.host.lock').open('rb') as other:
                self.assertEqual(other.read(), b'\0')
            self.assertEqual(child_result('record', self.state), 2)
        self.assertEqual(child_result('record', self.state), 0)

    def test_record_failure_unwinds_flock_before_yield_or_initialization(self):
        (self.state/'.host.lock').write_bytes(b'')
        with mock.patch.object(locks, '_linux_record_lock', side_effect=locks.StateBusyError('OFD unsupported')):
            with self.assertRaisesRegex(locks.StateBusyError, 'OFD unsupported'):
                with locks.exclusive_state(self.state):
                    self.fail('body ran without the record lock')
        self.assertEqual((self.state/'.host.lock').read_bytes(), b'')
        self.assertEqual(child_result('production', self.state), 0)
        self.assertEqual((self.state/'.host.lock').read_bytes(), b'\0')

    def test_production_crash_releases_both_locks_without_deleting_file(self):
        ready = self.root/'ready'
        inode = (self.state/'.host.lock').stat().st_ino
        code = '''import os,sys
sys.path.insert(0,sys.argv[1])
from pathlib import Path
from server.state_lock import exclusive_state
with exclusive_state(sys.argv[2]):
    Path(sys.argv[3]).write_text('owned')
    sys.stdin.buffer.read(1)
    os._exit(73)
'''
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', code, str(ROOT), str(self.state), str(ready)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic()+5
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists(), 'production owner failed to acquire lock')
            self.assertEqual(child_result('record', self.state), 2)
            child.communicate(b'x', timeout=5)
            self.assertEqual(child.returncode, 73)
            self.assertEqual(child_result('record', self.state), 0)
            self.assertEqual(child_result('production', self.state), 0)
            self.assertEqual((self.state/'.host.lock').stat().st_ino, inode)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
