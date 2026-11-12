import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch
from tools import audit_repository
from tools.audit_repository import inspect_content


class PublicationAuditTests(unittest.TestCase):
    def test_only_exact_reviewed_large_source_allowed(self):
        name = 'tools/verify_prediction_multiplayer.py'
        data = (Path(__file__).resolve().parents[1] / name).read_bytes()
        self.assertGreater(len(data), 256 * 1024)
        self.assertEqual(inspect_content(name, data), [])
        reason = 'source file over 256 KiB; review for embedded payload'
        for changed in (data + b'\n', b'#' + data[1:]):
            self.assertIn(reason, inspect_content(name, changed))
        self.assertIn(reason, inspect_content('tools/unreviewed.py', data))

    def test_reviewed_size_does_not_bypass_secret_checks(self):
        name = 'tools/reviewed_example.py'
        data = b'\n' * (256 * 1024) + b'-----BEGIN ' + b'PRIVATE KEY-----'
        reviewed = (len(data), hashlib.sha256(data).hexdigest())
        with patch.dict(audit_repository.REVIEWED_LARGE_SOURCES, {name: reviewed}):
            self.assertEqual(inspect_content(name, data), ['private key'])

    def test_only_exact_reviewed_documentation_media_allowed(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('crabs-2026.gif', 'discord-server.webp'):
            path = f'docs/media/{name}'
            data = (root / path).read_bytes()
            with self.subTest(path=path):
                self.assertEqual(inspect_content(path, data), [])
                for changed in (data + b'changed', data[:-1] + bytes([data[-1] ^ 1]), b'MZdisguised runtime'):
                    self.assertIn('unreviewed documentation media', inspect_content(path, changed))
                self.assertTrue(inspect_content(f'docs/media/unlisted-{name}', data))
                self.assertTrue(inspect_content(f'docs/other/{name}', data))

    def test_only_named_linux_deployment_sources_allowed_with_normal_content_checks(self):
        root = Path(__file__).resolve().parents[1]
        paths = ('deploy/linux/README.md', 'deploy/linux/ba-server-supervise',
                 'deploy/linux/battle-aces-server.service')
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(inspect_content(path, (root / path).read_bytes()), [])
                for data in (b'MZdisguised runtime', b'text\0binary', b'\xff',
                             b'-----BEGIN ' + b'PRIVATE KEY-----', b'ba1_' + b'a' * 43,
                             b'ghp_' + b'a' * 30, b'A' * 1024):
                    self.assertTrue(inspect_content(path, data))
        for path in ('deploy/linux/other.md', 'deploy/linux/extra.service',
                     'deploy/linux/nested/ba-server-supervise', 'deploy/README.md',
                     'deploy/linux/helper.py', 'docs/other.md'):
            with self.subTest(path=path):
                self.assertIn('not an allowed source/documentation path', inspect_content(path, b'ordinary text'))

    def test_only_reviewed_documentation_screenshots_allowed(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('client-installer.png', 'server-dashboard.png'):
            path = f'docs/screenshots/{name}'
            data = (root / path).read_bytes()
            self.assertEqual(inspect_content(path, data), [])
            self.assertIn('unreviewed documentation screenshot',
                          inspect_content(path, data + b'changed'))
            self.assertTrue(inspect_content('docs/screenshots/other.png', data))

    def test_authored_source_and_short_safety_signatures_allowed(self):
        source = b'ORIGINAL_SHA = "' + b'a' * 64 + b'"\nBEFORE = "e812345678"\n'
        self.assertEqual(inspect_content("client_patch/patcher/patch_client.py", source), [])

    def test_game_files_and_disguised_payloads_rejected(self):
        for path, data in (("server/assets/map.txt", b"map"),
                           ("client_patch/src/game.cpp", b"MZbinary"),
                           ("docs/export.txt", b"A" * 1024),
                           ("tests/fixtures/capture.json", b"{}"),
                           ("GameAssembly.dll", b"MZ"),
                           ("tools/generated.cpp", b"0xff, " * 128)):
            with self.subTest(path=path):
                self.assertTrue(inspect_content(path, data))

    def test_secrets_and_absolute_private_paths_rejected(self):
        for data in (b"-----BEGIN " + b"PRIVATE KEY-----", b"ghp_" + b"a" * 30,
                     b"C:" + b"/Users/private/work"):
            self.assertTrue(inspect_content("docs/example.txt", data))
