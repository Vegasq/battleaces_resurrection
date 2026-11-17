"""Test-only Linux x86-64 OFD candidate; production locking is unchanged.

Run on the isolated Linux test machine after measuring the unchanged Wine/Linux
lock probe: python -B -m unittest tests.test_linux_ofd_lock_candidate -v
No Wine, host, native DLL or network starts here. Cross-Wine interoperability
still requires the real two-runtime probe; POSIX-record controls are not Wine.

ABI: Linux x86-64 LP64 struct flock is32bytes, offsets(type,whence,start,len,pid)
=(0,2,8,16,24), using short,short,off_t64,off_t64,pid_t32. A separate C-header
test checks this rather than trusting Python's layout declaration alone.
Semantics: https://man7.org/linux/man-pages/man2/F_OFD_SETLK.2const.html
"""
from contextlib import contextmanager
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from server.state_lock import exclusive_state, StateBusyError

ROOT = Path(__file__).resolve().parents[1]
LINUX_X64 = sys.platform.startswith('linux') and platform.machine().lower() in ('x86_64', 'amd64')


class LinuxX64Flock(ctypes.Structure):
    _fields_ = [('l_type', ctypes.c_short), ('l_whence', ctypes.c_short),
                ('l_start', ctypes.c_int64), ('l_len', ctypes.c_int64), ('l_pid', ctypes.c_int32)]


def declared_layout():
    return dict(size=ctypes.sizeof(LinuxX64Flock),
                offsets=[getattr(LinuxX64Flock, name).offset for name, _ in LinuxX64Flock._fields_])


def require_abi():
    if not (LINUX_X64 and ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_long) == 8
            and declared_layout() == dict(size=32, offsets=[0, 2, 8, 16, 24])):
        raise RuntimeError('OFD candidate only supports verified Linux x86-64 LP64 ABI')


def ofd_lock(fd, fcntl, *, release=False):
    operation = getattr(fcntl, 'F_OFD_SETLK', None)
    if operation is None:
        raise RuntimeError('OFD lock unavailable; refusing flock-only fallback')
    lock = LinuxX64Flock(fcntl.F_UNLCK if release else fcntl.F_WRLCK, os.SEEK_SET, 0, 1, 0)
    try:
        fcntl.fcntl(fd, operation, bytes(lock))
    except OSError as error:
        if error.errno in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.ENOLCK):
            raise RuntimeError('OFD kernel/filesystem locking unavailable; refusing fallback') from error
        raise


@contextmanager
def candidate_state(directory):
    """Independent test-only flock/OFD composition, not a second production lock."""
    require_abi()
    import fcntl
    with (Path(directory)/'.host.lock').open('r+b') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise StateBusyError('candidate flock busy') from error
        try:
            ofd_lock(stream.fileno(), fcntl)
            try:
                yield stream.fileno()
            finally:
                ofd_lock(stream.fileno(), fcntl, release=True)
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def record_state(directory, *, start=0):
    """Traditional POSIX record-lock control, corresponding to Wine's F_SETLK."""
    import fcntl
    with (Path(directory)/'.host.lock').open('r+b') as stream:
        fcntl.lockf(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 1, start, os.SEEK_SET)
        try:
            yield
        finally:
            fcntl.lockf(stream.fileno(), fcntl.LOCK_UN, 1, start, os.SEEK_SET)


CHILD_TRY = '''import sys
sys.path.insert(0,sys.argv[1])
from tests.test_linux_ofd_lock_candidate import candidate_state,record_state,StateBusyError
try:
    lock=candidate_state(sys.argv[3]) if sys.argv[2]=='candidate' else record_state(sys.argv[3],start=int(sys.argv[4]))
    with lock: pass
except (BlockingIOError,StateBusyError): sys.exit(2)
'''


def child_result(kind, directory, *, start=0):
    child = subprocess.run([sys.executable, '-I', '-B', '-c', CHILD_TRY, str(ROOT), kind,
                            str(directory), str(start)], capture_output=True, timeout=5)
    if child.returncode not in (0, 2):
        raise AssertionError(f'lock control failed: {child.returncode}: {child.stderr!r}')
    return child.returncode


class OFDCandidateGuardTests(unittest.TestCase):
    def test_declared_layout_is_explicit_32byte_linux_x64_flock(self):
        self.assertEqual(declared_layout(), dict(size=32, offsets=[0, 2, 8, 16, 24]))

    def test_record_request_has_one_byte_at_zero_and_zero_pid(self):
        fcntl = mock.Mock(F_OFD_SETLK=37, F_WRLCK=1, F_UNLCK=2)
        ofd_lock(123, fcntl)
        fd, operation, payload = fcntl.fcntl.call_args.args
        lock = LinuxX64Flock.from_buffer_copy(payload)
        self.assertEqual((fd, operation), (123, 37))
        self.assertEqual((lock.l_type, lock.l_whence, lock.l_start, lock.l_len, lock.l_pid), (1, os.SEEK_SET, 0, 1, 0))
        ofd_lock(123, fcntl, release=True)
        self.assertEqual(LinuxX64Flock.from_buffer_copy(fcntl.fcntl.call_args.args[2]).l_type, 2)

    def test_unsupported_kernel_or_filesystem_fails_closed(self):
        for code in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.ENOLCK):
            fcntl = mock.Mock(F_OFD_SETLK=37, F_WRLCK=1)
            fcntl.fcntl.side_effect = OSError(code, 'authored unavailable OFD')
            with self.subTest(errno=code), self.assertRaisesRegex(RuntimeError, 'refusing fallback'):
                ofd_lock(123, fcntl)
            fcntl.fcntl.assert_called_once()
            fcntl.flock.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            ofd_lock(123, object())

    def test_contention_stays_contention_and_unsupported_abi_never_opens_state(self):
        fcntl = mock.Mock(F_OFD_SETLK=37, F_WRLCK=1)
        fcntl.fcntl.side_effect = BlockingIOError(errno.EAGAIN, 'held')
        with self.assertRaises(BlockingIOError):
            ofd_lock(123, fcntl)
        with mock.patch(__name__+'.LINUX_X64', False), mock.patch(__name__+'.exclusive_state') as original:
            with self.assertRaisesRegex(RuntimeError, 'only supports'):
                with candidate_state('must-not-open'):
                    self.fail('unsupported ABI was accepted')
            original.assert_not_called()


@unittest.skipUnless(LINUX_X64, 'actual OFD semantics require the isolated Linux x86-64 machine')
class OFDCandidateLinuxTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ba-ofd-candidate-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root/'state'
        self.state.mkdir()
        (self.state/'.host.lock').write_bytes(b'\0')

    def test_c_headers_independently_confirm_ctypes_abi(self):
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('C compiler absent; independent struct-flock ABI gate remains unverified')
        source, output = self.root/'flock_abi.c', self.root/'flock_abi'
        source.write_text('''#define _GNU_SOURCE
#include <fcntl.h>
#include <stddef.h>
#include <stdio.h>
int main(void) {
 printf("{\\\"size\\\":%zu,\\\"offsets\\\":[%zu,%zu,%zu,%zu,%zu],\\\"operation\\\":%d,\\\"write\\\":%d,\\\"unlock\\\":%d}\\n",
 sizeof(struct flock), offsetof(struct flock,l_type), offsetof(struct flock,l_whence),
 offsetof(struct flock,l_start), offsetof(struct flock,l_len), offsetof(struct flock,l_pid),
 F_OFD_SETLK, F_WRLCK, F_UNLCK);
 return 0;
}
''', encoding='ascii')
        subprocess.run([compiler, '-std=c11', '-Wall', '-Werror', str(source), '-o', str(output)],
                       check=True, capture_output=True, timeout=15)
        actual = json.loads(subprocess.check_output([str(output)], timeout=5))
        import fcntl
        self.assertEqual(actual, declared_layout() | dict(operation=fcntl.F_OFD_SETLK,
                                                        write=fcntl.F_WRLCK, unlock=fcntl.F_UNLCK))

    def test_ofd_and_traditional_record_locks_exclude_each_other_both_directions(self):
        with candidate_state(self.state):
            self.assertEqual(child_result('record', self.state), 2)
            self.assertEqual(child_result('candidate', self.state), 2)
        with record_state(self.state):
            self.assertEqual(child_result('candidate', self.state), 2)
        self.assertEqual(child_result('candidate', self.state), 0)

    def test_rejected_nested_lock_and_unrelated_descriptor_close_preserve_ofd_lock(self):
        with candidate_state(self.state):
            with self.assertRaises(StateBusyError):
                with candidate_state(self.state):
                    self.fail('nested candidate admitted')
            with (self.state/'.host.lock').open('rb') as another:
                self.assertEqual(another.read(), b'\0')  # Unix lock remains advisory.
            self.assertEqual(child_result('record', self.state), 2)
        self.assertEqual(child_result('record', self.state), 0)

    def test_plain_posix_control_loses_lock_after_another_descriptor_closes(self):
        with record_state(self.state):
            self.assertEqual(child_result('record', self.state), 2)
            with (self.state/'.host.lock').open('rb'):
                pass
            self.assertEqual(child_result('record', self.state), 0)

    def test_record_range_and_other_state_directory_remain_independent(self):
        other = self.root/'other'; other.mkdir()
        (other/'.host.lock').write_bytes(b'\0')
        with candidate_state(self.state):
            self.assertEqual(child_result('record', self.state, start=1), 0)
            self.assertEqual(child_result('candidate', other), 0)
            self.assertEqual(child_result('record', self.state), 2)

    def test_candidate_crash_releases_both_locks_without_replacing_file(self):
        ready = self.root/'ready'
        inode = (self.state/'.host.lock').stat().st_ino
        code = '''import os,sys
sys.path.insert(0,sys.argv[1])
from pathlib import Path
from tests.test_linux_ofd_lock_candidate import candidate_state
with candidate_state(sys.argv[2]):
    Path(sys.argv[3]).write_text('owned')
    sys.stdin.buffer.read(1)
    os._exit(73)
'''
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', code, str(ROOT), str(self.state), str(ready)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            import time
            deadline = time.monotonic()+5
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists(), 'candidate never acquired its locks')
            self.assertEqual(child_result('record', self.state), 2)
            child.communicate(b'x', timeout=5)
            self.assertEqual(child.returncode, 73)
            self.assertEqual(child_result('record', self.state), 0)
            self.assertEqual(child_result('candidate', self.state), 0)
            self.assertEqual((self.state/'.host.lock').read_bytes(), b'\0')
            self.assertEqual((self.state/'.host.lock').stat().st_ino, inode)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
