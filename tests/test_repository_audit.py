import unittest
from pathlib import Path
from tools.audit_repository import inspect_content


class PublicationAuditTests(unittest.TestCase):
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
