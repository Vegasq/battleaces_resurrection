"""Linux setup refusal, private TLS provisioning, and preservation controls."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile

from tools import linux_server as linux
from tools.package_integrity import PackageError


class LinuxSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_wrong_installer_never_extracts_or_executes(self):
        installer = self.root / 'installer.exe'
        installer.write_bytes(b'not an installer')
        destination = self.root / 'payload'
        with self.assertRaisesRegex(ValueError, 'wrong size'):
            linux.extract_installer(installer, destination)
        with mock.patch.object(linux, 'INSTALLER_BYTES', installer.stat().st_size):
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                linux.extract_installer(installer, destination)
        self.assertFalse(destination.exists())

    def test_archive_paths_are_checked_before_extraction(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(linux.PACKAGE_NAME + '/../escaped', b'authored')
        payload = buffer.getvalue()
        data = b'authored PE header' + payload
        installer = self.root / 'installer.exe'
        installer.write_bytes(data)
        with mock.patch.multiple(linux, INSTALLER_BYTES=len(data), PAYLOAD_BYTES=len(payload),
                                 INSTALLER_SHA256=hashlib.sha256(data).hexdigest(),
                                 PAYLOAD_SHA256=hashlib.sha256(payload).hexdigest()):
            with self.assertRaises(PackageError):
                linux.extract_installer(installer, self.root / 'payload')
        self.assertFalse((self.root / 'payload').exists())
        self.assertFalse((self.root / 'escaped').exists())

    def test_source_game_overlap_is_rejected_without_changes(self):
        game = self.root / 'game'
        game.mkdir()
        marker = game / 'personal-save'
        marker.write_bytes(b'keep exact')
        for destination in (game, game / 'server', self.root):
            with self.subTest(destination=destination), self.assertRaisesRegex(ValueError, 'separate'):
                linux.setup(destination, self.root / 'installer', game)
        self.assertEqual(list(game.iterdir()), [marker])
        self.assertEqual(marker.read_bytes(), b'keep exact')

    def test_existing_deployment_is_never_overwritten(self):
        game = self.root / 'game'
        game.mkdir()
        for name in ('Battle Aces.exe', 'GameAssembly.dll', 'Battle Aces_Data'):
            (game / name).touch()
        deployment = self.root / 'deployment'
        deployment.mkdir()
        marker = deployment / 'host-state'
        marker.write_bytes(b'preserve')
        with mock.patch.object(linux, 'extract_installer') as extract:
            with self.assertRaises(FileExistsError):
                linux.setup(deployment, self.root / 'installer', game)
        extract.assert_not_called()
        self.assertEqual(marker.read_bytes(), b'preserve')


@unittest.skipUnless(os.name == 'posix' and shutil.which('openssl'), 'requires POSIX and OpenSSL')
class LinuxCertificateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.host = Path(self.temporary.name) / 'host with spaces'
        (self.host / 'config').mkdir(parents=True)

    def test_real_tls_material_is_private_and_existing_state_is_preserved(self):
        from server.configuration import load_config
        with mock.patch('server.assets.verify_assets'):
            path = linux.initialize_config(self.host)
        config = load_config(path)
        self.assertEqual(config.access_mode, 'rc-open')
        self.assertEqual(config.assets_directory, self.host / 'assets/build-37822')
        self.assertFalse(config.allow_insecure_loopback)
        self.assertEqual(config.private_key_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.private_key_file.parent.stat().st_mode & 0o777, 0o700)
        before = {p: p.read_bytes() for p in (path, config.private_key_file, config.certificate_file)}
        with mock.patch('subprocess.run', side_effect=AssertionError('must not regenerate keys')):
            self.assertEqual(linux.initialize_config(self.host), path)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        raw = json.loads(path.read_bytes())
        for key in ('assets_directory', 'data_directory', 'certificate_file', 'private_key_file'):
            self.assertFalse(Path(raw[key]).is_absolute())
            self.assertNotIn('\\', raw[key])

    def test_concurrent_config_publication_wins_without_replacement(self):
        config = self.host / 'config/host.json'
        real_link = os.link
        winner = None

        def publish_competitor(source, target):
            nonlocal winner
            value = json.loads(Path(source).read_bytes())
            value['listen_port'] = 47891
            winner = (json.dumps(value) + '\n').encode()
            config.write_bytes(winner)
            real_link(source, target)

        with mock.patch('server.assets.verify_assets'), mock.patch.object(linux.os, 'link', publish_competitor):
            linux.initialize_config(self.host)
        self.assertEqual(config.read_bytes(), winner)
        self.assertEqual(list(config.parent.glob('.linux-host-*.json')), [])


if __name__ == '__main__':
    unittest.main()
