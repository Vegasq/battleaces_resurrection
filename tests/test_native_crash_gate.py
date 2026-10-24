"""Actual Windows sharing/publication and refused-crash false-pass regressions."""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import native_crash_gate as gate

READY = ('[10] NATIVE CRASH ready: version=1 thread=19 recipe=23 mode=3 savedMode=32769 '
         'expectedMode=3 managerPresent=1 managerDisabledChecked=1 pendingTreeChecked=1 '
         'managerAbsent=0 controllerOnCurrentStack=1 ipcInvalid=6 cursorCallbackRva=801fb0 '
         'recursion=0 breakOnCrash=0 originalWrapperRva=1484d0 gateRequired=1\n')
TRIGGER = ('[20] NATIVE CRASH trigger: version=1 thread=19 category=0 '
           'wrapperRva=1484d0 nativeCaller=1 mode=3\n')
REFUSED = '[21] NATIVE CRASH refused: version=1 thread=19 reason=native crash gate unavailable\n'


@unittest.skipUnless(os.name == 'nt', 'Actual Windows sharing/rename contract')
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='crash169-gate-', dir=gate.ROOT / 'local'))
        self.profile = self.root / '.battleaces-resurrection/profiles/nativestest_crash169_0123456789ab'
        self.profile.mkdir(parents=True)
        self.target = self.profile / gate.ARM_NAME
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                           w.DWORD, w.DWORD, w.HANDLE]
        self.kernel.CreateFileW.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.CloseHandle.restype = w.BOOL

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(gate.ROOT / 'local'))
        shutil.rmtree(self.root)

    def reader_error(self, path):
        # Exact native probe access/share/open flags; no relaxed write sharing.
        handle = self.kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200080, None)
        if handle == ctypes.c_void_p(-1).value:
            return ctypes.get_last_error()
        self.assertTrue(self.kernel.CloseHandle(handle))
        return 0

    def test_old_direct_writer_reproduces_sharing_violation(self):
        with self.target.open('xb') as stream:
            stream.write(gate.AUTHORIZATION)
            stream.flush()
            self.assertEqual(self.reader_error(self.target), 32)
        self.assertEqual(self.reader_error(self.target), 0)

    def test_final_path_absent_during_write_and_writer_closed_before_rename(self):
        sync, rename = os.fsync, os.rename
        def during_write(fd):
            self.assertEqual(self.reader_error(self.target), 2)
            sync(fd)
        def before_rename(source, target):
            self.assertEqual(self.reader_error(self.target), 2)
            self.assertEqual(self.reader_error(source), 0)
            self.assertEqual(Path(source).read_bytes(), gate.AUTHORIZATION)
            rename(source, target)
        with patch.object(gate.os, 'fsync', side_effect=during_write), \
                patch.object(gate.os, 'rename', side_effect=before_rename):
            self.assertEqual(gate.publish_arm(self.profile), self.target)
        self.assertEqual(self.reader_error(self.target), 0)
        self.assertEqual(self.target.read_bytes(), gate.AUTHORIZATION)
        self.assertEqual(list(self.profile.iterdir()), [self.target])

    def test_existing_gate_is_never_overwritten(self):
        self.target.write_bytes(b'prior malformed authorization')
        with self.assertRaises(FileExistsError):
            gate.publish_arm(self.profile)
        self.assertEqual(self.target.read_bytes(), b'prior malformed authorization')
        self.assertEqual(list(self.profile.iterdir()), [self.target])

    def test_flush_failure_never_publishes(self):
        with patch.object(gate.os, 'fsync', side_effect=OSError('injected flush failure')):
            with self.assertRaises(OSError):
                gate.publish_arm(self.profile)
        self.assertEqual(list(self.profile.iterdir()), [])

    def test_unowned_or_wrong_profile_refuses(self):
        for path in (gate.ROOT, self.root, self.profile.parent):
            with self.subTest(path=path), self.assertRaises(ValueError):
                gate.publish_arm(path)


class ExitTests(unittest.TestCase):
    def child(self, code):
        return Mock(tid=19, poll=Mock(return_value=code))

    def test_refusal_stops_without_waiting_for_exit_or_timeout(self):
        child, tracker = self.child(None), Mock()
        text = READY + '[21] NATIVE CRASH gate open failed: version=1 thread=19 error=32\n' + REFUSED
        with patch.object(gate.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'error=32.*native crash gate unavailable'):
                gate.wait_for_crash_exit(child, tracker, lambda: text)
            child.poll.assert_not_called()
            sleep.assert_not_called()

    def test_final_refusal_cannot_pass_even_with_exception_exit(self):
        reads = iter([READY + TRIGGER, READY + TRIGGER + REFUSED])
        with self.assertRaises(RuntimeError):
            gate.wait_for_crash_exit(self.child(gate.FAULT), Mock(), lambda: next(reads))

    def test_missing_foreign_duplicate_or_early_trigger_refuses(self):
        texts = [READY, READY + TRIGGER.replace('thread=19', 'thread=20'),
                 READY + TRIGGER * 2, READY + TRIGGER.replace('[20]', '[9]'),
                 READY.replace('mode=3', 'mode=1') + TRIGGER,
                 READY.replace('managerAbsent=0', 'managerAbsent=1') + TRIGGER]
        for text in texts:
            with self.subTest(text=text), self.assertRaises(ValueError):
                gate.wait_for_crash_exit(self.child(gate.FAULT), Mock(), lambda: text)

    def test_wrong_exit_code_refuses(self):
        with self.assertRaises(RuntimeError):
            gate.wait_for_crash_exit(self.child(0), Mock(), lambda: READY + TRIGGER)

    def test_actual_matching_marker_contract_and_exit_pass(self):
        self.assertEqual(gate.wait_for_crash_exit(self.child(gate.FAULT), Mock(),
                                               lambda: READY + TRIGGER), gate.FAULT)

    def test_saved_mode_is_bound_to_this_launch_without_changing_active_policy(self):
        text = READY.replace('savedMode=32769', 'savedMode=1') + TRIGGER
        self.assertEqual(gate.wait_for_crash_exit(self.child(gate.FAULT), Mock(),
                                               lambda: text, saved_mode=1), gate.FAULT)
        with self.assertRaises(ValueError):
            gate.wait_for_crash_exit(self.child(gate.FAULT), Mock(), lambda: text)
        for mode in (-1, 2**32, True, '1'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                gate.validate_ready(text, 19, saved_mode=mode)
        with self.assertRaises(ValueError):
            gate.validate_ready(text.replace('mode=3', 'mode=1'), 19, saved_mode=1)

    def test_saved_mode_binding_requires_one_complete_original_thread_preflight(self):
        for mode in (1, 32769):
            text = READY.replace('savedMode=32769', 'savedMode=' + str(mode))
            self.assertEqual(gate.ready_saved_mode(text, 19), mode)
            for invalid in (text * 2, text.replace('thread=19', 'thread=20'),
                            text.replace('mode=3', 'mode=1'),
                            text.replace('savedMode=' + str(mode), 'savedMode=4294967296')):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    gate.ready_saved_mode(invalid, 19)

    def test_deadline_is_bounded(self):
        for timeout in (0, 61, True, float('nan'), float('inf')):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                gate.wait_for_crash_exit(self.child(None), Mock(), lambda: READY, timeout=timeout)
        with patch.object(gate.time, 'monotonic', side_effect=[0, 61]), \
                patch.object(gate.time, 'sleep') as sleep:
            with self.assertRaises(TimeoutError):
                gate.wait_for_crash_exit(self.child(None), Mock(), lambda: READY)
            sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
