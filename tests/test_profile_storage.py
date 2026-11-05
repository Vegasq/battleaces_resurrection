"""Real Windows controls for the owned profile-storage diagnostic."""
import os
import unittest

from tests.test_credentials import private_test_folder, remove_test_folder
from tools.verify_profile_storage import OwnedFileLock


@unittest.skipUnless(os.name == 'nt', 'Windows file-sharing semantics')
class ProfileStorageControls(unittest.TestCase):
    def setUp(self):
        self.folder = private_test_folder('profile-storage-')
        self.addCleanup(remove_test_folder, self.folder)
        self.profiles = self.folder / 'profiles'
        self.profiles.mkdir()
        self.path = self.profiles / 'owned.json'
        self.path.write_bytes(b'previous valid bytes')

    def test_replace_refused_until_handle_closed(self):
        staged = self.profiles / 'staged.json'
        staged.write_bytes(b'replacement')
        with OwnedFileLock(self.path, self.profiles, allow_read=True) as lock:
            self.assertEqual(lock.probe_winerror, 32)
            with self.assertRaises(PermissionError):
                os.replace(staged, self.path)
            self.assertEqual(self.path.read_bytes(), b'previous valid bytes')
            self.assertEqual(staged.read_bytes(), b'replacement')
        os.replace(staged, self.path)
        self.assertEqual(self.path.read_bytes(), b'replacement')
        lock.close()  # Explicit repeated release is harmless.

    def test_read_refused_and_exception_releases_handle(self):
        with self.assertRaisesRegex(RuntimeError, 'diagnostic interruption'):
            with OwnedFileLock(self.path, self.profiles, allow_read=False) as lock:
                self.assertEqual(lock.probe_winerror, 32)
                with self.assertRaises(PermissionError):
                    self.path.read_bytes()
                raise RuntimeError('diagnostic interruption')
        self.assertEqual(self.path.read_bytes(), b'previous valid bytes')

    def test_sibling_file_outside_profile_folder_refused(self):
        sibling = self.folder / 'outside.json'
        sibling.write_bytes(b'outside')
        with self.assertRaisesRegex(AssertionError, 'owned regular profile required'):
            OwnedFileLock(sibling, self.profiles, allow_read=False)
        self.assertEqual(sibling.read_bytes(), b'outside')


if __name__ == '__main__':
    unittest.main()
