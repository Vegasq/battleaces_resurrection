"""Client CLI transaction/refusal controls; no game or Wine is launched here."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import linux_client as client
from tools.linux_wine import wine_environment


@unittest.skipUnless(sys.platform.startswith('linux'), 'Linux CLI controls')
class LinuxClientTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.game = self.base / 'original'
        (self.game / 'Battle Aces_Data').mkdir(parents=True)
        (self.game / 'Battle Aces.exe').write_bytes(b'authored executable')
        (self.game / 'GameAssembly.dll').write_bytes(b'original game')
        self.save = self.game / '.battleaces-resurrection/profiles/default/save'
        self.save.parent.mkdir(parents=True)
        self.save.write_bytes(b'personal save')
        self.root = self.base / 'deployment'

    def run_setup(self, returncodes):
        with (mock.patch.object(client, 'extract_installer', return_value=self.base / 'package'),
              mock.patch.object(client, 'installed_runtime', return_value=self.base / 'installed'),
              mock.patch.object(client.subprocess, 'check_output', return_value='wine-authored\n'),
              mock.patch.object(client.subprocess, 'run', side_effect=[
                  subprocess.CompletedProcess([], code) for code in returncodes]) as run):
            client.setup(self.root, self.base / 'installer.exe', self.game, server='localhost', name='Test Pilot')
        return run.call_args_list

    def test_setup_only_installs_and_verifies_with_graphics_disabled(self):
        with mock.patch.dict(os.environ, {'DISPLAY': ':99', 'WAYLAND_DISPLAY': 'wayland-99', 'WINEPREFIX': '/unrelated'}):
            calls = self.run_setup([0, 0])
        self.assertEqual(len(calls), 2)
        first = calls[0].args[0]
        self.assertIn('install-game', first)
        self.assertNotIn('start', first)
        self.assertIn('-c', calls[1].args[0])
        for call in calls:
            environment = call.kwargs['env']
            self.assertEqual(environment['DISPLAY'], '')
            self.assertEqual(environment['WAYLAND_DISPLAY'], '')
            self.assertEqual(environment['WINEPREFIX'], str(self.root / 'wineprefix'))
            self.assertIn('winex11.drv,winewayland.drv=', environment['WINEDLLOVERRIDES'])
        self.assertFalse((self.root / 'game/.battleaces-resurrection/profiles').exists())
        self.assertEqual(self.save.read_bytes(), b'personal save')
        self.assertEqual((self.game / 'GameAssembly.dll').read_bytes(), b'original game')
        receipt = json.loads((self.root / 'linux-setup.json').read_bytes())
        self.assertTrue(receipt['files_verified'])
        self.assertFalse(receipt['game_started'])

    def test_backend_failure_retains_copy_and_logs_without_publishing_launcher(self):
        with self.assertRaisesRegex(ValueError, 'Installation failed'):
            self.run_setup([1])
        self.assertTrue((self.root / 'install.log').exists())
        self.assertEqual((self.root / 'game/GameAssembly.dll').read_bytes(), b'original game')
        self.assertFalse((self.root / 'Start Battle Aces.sh').exists())
        self.assertFalse((self.root / 'linux-setup.json').exists())
        self.assertEqual(self.save.read_bytes(), b'personal save')

    def test_failed_verification_does_not_publish_a_successful_install(self):
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            self.run_setup([0, 1])
        self.assertTrue((self.root / 'check.log').exists())
        self.assertFalse((self.root / 'Start Battle Aces.sh').exists())
        self.assertFalse((self.root / 'linux-setup.json').exists())

    def test_overlap_or_existing_deployment_never_changes_source_or_old_state(self):
        for root in (self.game, self.game / 'child', self.base):
            with self.subTest(root=root), self.assertRaisesRegex(ValueError, 'separate'):
                client.setup(root, self.base / 'installer.exe', self.game)
        self.root.mkdir()
        marker = self.root / 'existing-save'
        marker.write_bytes(b'preserve existing')
        with mock.patch.object(client, 'extract_installer') as extract:
            with self.assertRaises(FileExistsError):
                client.setup(self.root, self.base / 'installer.exe', self.game)
        extract.assert_not_called()
        self.assertEqual(marker.read_bytes(), b'preserve existing')

    def test_invalid_name_address_and_long_native_path_fail_before_copy(self):
        for settings in ({'name': 'bad"name'}, {'server': 'https://invalid.example'}, {'server': 'host:1234'}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                client.setup(self.root, self.base / 'installer.exe', self.game, **settings)
            self.assertFalse(self.root.exists())
        with self.assertRaisesRegex(ValueError, 'too long'):
            client.setup(self.base / ('x' * 200), self.base / 'installer.exe', self.game)

    def test_installed_runtime_tampering_is_rejected(self):
        package = self.root / 'package' / client.PACKAGE_NAME
        data = b'authored runtime'
        manifest = json.dumps(dict(schema=1, product='client', files={
            'program/runtime/python.exe': dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())})).encode()
        identity = hashlib.sha256(manifest).hexdigest()[:20]
        runtime = self.root / 'game/.battleaces-resurrection/client-runtime' / identity
        for folder in (package, runtime):
            (folder / 'program/runtime').mkdir(parents=True)
            (folder / 'program/runtime/python.exe').write_bytes(data)
            (folder / 'package-manifest.json').write_bytes(manifest)
        self.assertEqual(client.installed_runtime(self.root), runtime)
        (runtime / 'program/runtime/python.exe').write_bytes(b'tampered runtime')
        with self.assertRaises(ValueError):
            client.installed_runtime(self.root)

    def test_launcher_quotes_paths_without_shell_expansion(self):
        root = self.base / "space ' $(touch SENTINEL)"
        root.mkdir()
        fake = self.base / "fake ' python"
        fake.write_text('#!/usr/bin/env python3\nimport json,sys;print(json.dumps(sys.argv[1:]))\n')
        fake.chmod(0o700)
        with mock.patch.object(client.sys, 'executable', str(fake)), mock.patch.object(client, 'ROOT', root):
            client.write_launcher(root)
        result = subprocess.run([str(root / 'Start Battle Aces.sh')], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), ['-m', 'tools.linux_client', 'start', '--root', str(root)])
        self.assertFalse((root / 'SENTINEL').exists())

    def test_only_explicit_start_retains_desktop_environment(self):
        with mock.patch.dict(os.environ, {'DISPLAY': ':99', 'WAYLAND_DISPLAY': 'wayland-99'}):
            headless = wine_environment(self.root, headless=True)
            desktop = wine_environment(self.root)
        self.assertEqual(headless['DISPLAY'], '')
        self.assertEqual(desktop['DISPLAY'], ':99')
        self.assertEqual(desktop['WINEDLLOVERRIDES'], 'mscoree,mshtml=')


if __name__ == '__main__':
    unittest.main()
