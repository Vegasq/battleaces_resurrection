"""Known native UTF-16 path limits must fail before game/IPC/file side effects."""
import argparse
import asyncio
from pathlib import Path, PureWindowsPath
import unittest
from unittest import mock

from client_patch.transport import launcher
from tools.verify_packaged_play import owned_profile


class NativePathPreflightTests(unittest.TestCase):
    def config(self, root, profile='default'):
        return dict(game_directory=root, local_profile=profile)

    def at_backup_length(self, length, profile='default'):
        suffix = str(PureWindowsPath('Z:/')/'.battleaces-resurrection'/'profiles'/profile/'StorageSyncBackup'/'A3079428-5DC5-4617-AF2D-0C8656DA760B')
        return self.config(PureWindowsPath('Z:/'+('x'*(length-len(suffix)-1))), profile)

    def test_native_boundary_excludes_terminating_nul(self):
        self.assertEqual(launcher.native_storage_preflight(self.at_backup_length(259)), 'default')
        with self.assertRaisesRegex(launcher.LaunchError, 'save paths too long'):
            launcher.native_storage_preflight(self.at_backup_length(260))

    def test_utf16_units_are_not_unicode_code_points(self):
        config = self.at_backup_length(259)
        config['game_directory'] = PureWindowsPath(str(config['game_directory'])[:-1]+'\U0001f680')
        with self.assertRaisesRegex(launcher.LaunchError, 'save paths too long'):
            launcher.native_storage_preflight(config)

    def test_profile_length_is_included_and_never_shortened(self):
        root = self.at_backup_length(250)['game_directory']
        with self.assertRaisesRegex(launcher.LaunchError, 'save paths too long'):
            launcher.native_storage_preflight(self.config(root, 'a'*48))
        self.assertEqual(launcher.native_storage_preflight(self.config(PureWindowsPath('Z:/game'), 'a'*48)), 'a'*48)

    def test_nonlocal_noncanonical_and_invalid_paths_refused(self):
        for root in ('relative', 'Z:relative', '\\\\server\\share\\game', '\\\\?\\Z:\\game', 'Z:/game/../other', 'Z:/game/\ud800'):
            with self.subTest(root=repr(root)), self.assertRaises(launcher.LaunchError):
                launcher.native_storage_preflight(self.config(root))

    def test_launch_refuses_before_verification_socket_or_spawn(self):
        config = self.at_backup_length(260)
        # Build asyncio's own Windows wakeup pipe BEFORE intercepting only the
        # launch operation; the shared socket module also serves the event loop.
        with asyncio.Runner() as runner:
            with (mock.patch.object(launcher, 'verify_game') as verify,
                  mock.patch.object(launcher.socket, 'socketpair') as pair,
                  mock.patch.object(launcher, 'spawn_game') as spawn):
                with self.assertRaisesRegex(launcher.LaunchError, 'save paths too long'):
                    runner.run(launcher.launch(config, None, argparse.Namespace()))
        verify.assert_not_called(); pair.assert_not_called(); spawn.assert_not_called()

    def test_argument_adapter_refuses_before_creating_runtime_directory(self):
        config = self.at_backup_length(260)
        config['game_directory'] = Path(str(config['game_directory']))
        with mock.patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaisesRegex(launcher.LaunchError, 'save paths too long'):
                launcher.game_arguments(config, None, 123, argparse.Namespace(run_name='client'))
        mkdir.assert_not_called()

    def test_long_replay_fixture_uses_valid_max_profile_not_deep_game_folder(self):
        profile = owned_profile(True)
        self.assertEqual(len(profile), 48)
        root = PureWindowsPath('Z:/'+('g'*72))
        self.assertEqual(launcher.native_storage_preflight(self.config(root, profile)), profile)
        replay = root/'.battleaces-resurrection'/'profiles'/profile/'AutoSaveReplays'/('r'*90+'.rep')
        self.assertGreater(len(str(replay)), 260)
        self.assertTrue(owned_profile().startswith('nativestest_packaged_'))


if __name__ == '__main__':
    unittest.main()
