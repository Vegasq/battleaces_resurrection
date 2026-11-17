import hashlib
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from tools import audit_repository
from tools.audit_repository import inspect_content


class PublicationAuditTests(unittest.TestCase):
    def test_rust_sources_keep_binary_secret_and_output_guards(self):
        for path in ('rust/snapshot-decoder/Cargo.toml', 'rust/snapshot-decoder/Cargo.lock',
                     'rust/snapshot-decoder/src/lib.rs', 'rust/snapshot-decoder/src/main.rs'):
            self.assertEqual(inspect_content(path, b'ordinary source'), [])
            for data in (b'MZpayload', b'\x7fELFbinary', b'ghp_' + b'a'*30, b'text\0binary'):
                self.assertTrue(inspect_content(path, data))
        for path in ('rust/other/Cargo.toml', 'rust/snapshot-decoder/output.json',
                     'rust/snapshot-decoder/target/debug/app.rs',
                     'rust/snapshot-decoder/src/target/embedded.rs', 'tools/unrelated.rs'):
            self.assertTrue(inspect_content(path, b'ordinary text'))

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


class HistoricalReviewTests(unittest.TestCase):
    size_reason = 'source file over 256 KiB; review for embedded payload'
    path_reason = 'developer-specific absolute path'
    large_source = b'# authored diagnostic source\n' * 10000
    example = b'Hash-check example: C:' + b'/Games/Example/library.dll\n'

    def reviews(self, name, data, reason):
        return {(name, len(data), hashlib.sha256(data).hexdigest()): reason}

    def test_exact_history_review_leaves_current_content_strict(self):
        for name, data, reason in [('tools/check.py', self.large_source, self.size_reason),
                                   ('README.md', self.example, self.path_reason)]:
            with self.subTest(name=name), patch.object(audit_repository, 'HISTORICAL_REVIEWS',
                                                      self.reviews(name, data, reason)):
                self.assertEqual(audit_repository.inspect_historical_content(name, data), ([], [reason]))
                self.assertEqual(inspect_content(name, data), [reason])

    def test_changed_path_size_or_digest_does_not_inherit_review(self):
        name, data = 'tools/check.py', self.large_source
        reviews = self.reviews(name, data, self.size_reason)
        for path, changed in [(name, data + b'# more\n'), (name, data[:-1] + b' '),
                              ('tools/other.py', data)]:
            with self.subTest(path=path, size=len(changed)), patch.object(audit_repository, 'HISTORICAL_REVIEWS', reviews):
                self.assertEqual(audit_repository.inspect_historical_content(path, changed), ([self.size_reason], []))
        bad_size = {(name, len(data) + 1, hashlib.sha256(data).hexdigest()): self.size_reason}
        with patch.object(audit_repository, 'HISTORICAL_REVIEWS', bad_size):
            self.assertEqual(audit_repository.inspect_historical_content(name, data), ([self.size_reason], []))

    def test_review_removes_only_its_named_finding(self):
        for payload, reason in [(b'ghp_' + b'a' * 30, 'GitHub credential'),
                                (b'ba1_' + b'a' * 43, 'player invite credential'),
                                (b'-----BEGIN ' + b'PRIVATE KEY-----', 'private key'),
                                (b'A' * 1024, 'long encoded payload'),
                                (b'0xff, ' * 128, 'large byte array'),
                                (b'\0', 'binary or archive content'),
                                (self.example, self.path_reason)]:
            data = self.large_source + payload
            with self.subTest(reason=reason), patch.object(audit_repository, 'HISTORICAL_REVIEWS',
                    self.reviews('tools/check.py', data, self.size_reason)):
                self.assertEqual(audit_repository.inspect_historical_content('tools/check.py', data),
                                 ([reason], [self.size_reason]))

    def test_cli_reports_reviews_separately_from_failures(self):
        def audit(history, *, reviewed):
            self.assertTrue(history)
            reviewed.append(dict(path='README.md', object='a' * 40, reasons=[self.path_reason]))
            return 2, []
        output = io.StringIO()
        with patch.object(audit_repository, 'audit', audit), patch('sys.argv', ['audit', '--history']), redirect_stdout(output):
            self.assertFalse(audit_repository.main())
        self.assertIn('Reviewed history README.md (' + 'a' * 40 + ')', output.getvalue())
        self.assertIn('1 reviewed historical findings; 0 failures', output.getvalue())

    def test_real_git_all_refs_and_index_remain_audited(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def git(*args):
                result = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
                return result.stdout
            git('init', '--quiet')
            git('config', 'user.name', 'Audit fixture')
            git('config', 'user.email', 'audit@example.invalid')
            (root / 'empty-hooks').mkdir()
            git('config', 'core.hooksPath', str(root / 'empty-hooks'))
            git('config', 'core.autocrlf', 'false')
            readme = root / 'README.md'
            readme.write_bytes(b'Current clean documentation\n')
            git('add', 'README.md')
            git('-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Clean current source')
            base = git('rev-parse', 'HEAD').decode().strip()
            git('checkout', '--quiet', '-b', 'historical-side-branch')
            readme.write_bytes(self.example)
            git('add', 'README.md')
            git('-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'Historical example')
            historical = git('rev-parse', 'HEAD:README.md').decode().strip()
            git('checkout', '--quiet', '-b', 'current', base)
            with patch.object(audit_repository, 'git', git), patch.object(audit_repository,
                    'HISTORICAL_REVIEWS', self.reviews('README.md', self.example, self.path_reason)):
                reviewed = []
                self.assertEqual(audit_repository.audit(history=True, reviewed=reviewed), (2, []))
                self.assertEqual(reviewed, [dict(path='README.md', object=historical, reasons=[self.path_reason])])
                with patch.object(audit_repository, 'HISTORICAL_REVIEWS', {}):
                    self.assertEqual(audit_repository.audit(history=True)[1], reviewed)
                # Reintroducing the very same reviewed object into today's index fails.
                readme.write_bytes(self.example)
                git('add', 'README.md')
                self.assertEqual(audit_repository.audit()[1], reviewed)
                self.assertEqual(audit_repository.audit(history=True)[1], reviewed)
                # Construct the historical mode without materializing a symlink:
                # Git's core.symlinks setting and OS privileges are irrelevant to
                # an audit of Git objects. Keep the current checkout on base.
                git('update-index', '--cacheinfo', '120000,' + historical + ',README.md')
                tree = git('write-tree').decode().strip()
                commit = git('-c', 'commit.gpgsign=false', 'commit-tree', tree, '-p', base,
                             '-m', 'Unsupported historical mode').decode().strip()
                git('branch', 'unsupported-mode', commit)
                git('read-tree', base)
                readme.write_bytes(b'Current clean documentation\n')
                failures = audit_repository.audit(history=True)[1]
                self.assertEqual(len(failures), 1)
                self.assertEqual(failures[0]['reasons'], ['symlink or unsupported file mode'])
                readme.write_bytes(self.example)
                git('add', 'README.md')
                failures = audit_repository.audit(history=True)[1]
                self.assertEqual([item['reasons'] for item in failures],
                                 [[self.path_reason], ['symlink or unsupported file mode']])
