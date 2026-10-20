"""Diagnostic gates must never be visible while their writer is still open."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import unittest
from unittest import mock
import uuid

from tools.verify_packaged_multiplayer import publish_empty_gate


class DiagnosticGateTests(unittest.TestCase):
    def setUp(self):
        self.base=Path(__file__).resolve().parents[1]/'local'
        self.folder=self.base/('diagnostic-gate-'+uuid.uuid4().hex)
        self.folder.mkdir(parents=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.folder.resolve().relative_to(self.base.resolve())
        shutil.rmtree(self.folder)

    def test_only_closed_empty_file_is_published(self):
        target=self.folder/'native-quit.ready'
        rename=Path.rename
        observed=[]
        def inspect(source,destination):
            self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(),b'')
            observed.append(str(destination))
            return rename(source,destination)
        with mock.patch.object(Path,'rename',inspect):publish_empty_gate(target)
        self.assertEqual(observed,[str(target)])
        self.assertEqual(target.read_bytes(),b'')
        self.assertFalse(target.with_name(target.name+'.pending').exists())

    def test_existing_gate_or_pending_file_is_preserved(self):
        target=self.folder/'native-quit.ready'
        target.write_bytes(b'keep')
        with self.assertRaises(AssertionError):publish_empty_gate(target)
        self.assertEqual(target.read_bytes(),b'keep')
        target.unlink()
        pending=target.with_name(target.name+'.pending');pending.write_bytes(b'keep pending')
        with self.assertRaises(FileExistsError):publish_empty_gate(target)
        self.assertFalse(target.exists());self.assertEqual(pending.read_bytes(),b'keep pending')

    @unittest.skipUnless(os.name=='nt','Win32 native reader sharing contract')
    def test_direct_writer_reproduces_sharing_conflict_but_closed_publication_does_not(self):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        def native_read(path):
            handle=kernel.CreateFileW(str(path),0x80000000,1,None,3,0x200000,None)
            if handle==ctypes.c_void_p(-1).value:return ctypes.get_last_error()
            kernel.CloseHandle(handle);return 0
        target=self.folder/'direct.ready'
        with target.open('xb'):
            self.assertEqual(native_read(target),32) # ERROR_SHARING_VIOLATION
        self.assertEqual(native_read(target),0)
        target=self.folder/'native-quit.ready'
        publish_empty_gate(target)
        self.assertEqual(native_read(target),0)
