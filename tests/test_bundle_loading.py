"""Catalog compatibility, cached content verification and recovery boundaries."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from client_patch.patcher import bundle_loading as loading
from tests.bundle_support import AuthoredBundles


class BundleLoadingTests(unittest.TestCase):
    def test_progress_keeps_stdout_available_for_json_consumers(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            loading.console_progress(0, 133)
            loading.console_progress(133, 133)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('Checking game files (133/133)', stderr.getvalue())

    def setUp(self):
        self.parent = Path(__file__).resolve().parents[1] / 'local/bundle-loading-tests'
        self.root = self.parent / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.fixture = AuthoredBundles(self.root)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(loading, 'BUILD', self.fixture.build))
        self.addCleanup(self.stack.close)
        self.addCleanup(self.remove_fixture)

    def remove_fixture(self):
        target = self.root.resolve()
        self.assertEqual(target.parent, self.parent.resolve())
        self.assertEqual(len(target.name), 32)
        shutil.rmtree(target)

    def installed(self):
        plan = loading.prepare_install(self.root)
        plan.backup.parent.mkdir(parents=True)
        plan.backup.write_bytes(plan.original)
        plan.target.write_bytes(plan.installed)
        plan.receipt_path.write_bytes(plan.receipt_after)
        return plan

    def test_catalog_changes_only_crc_numbers_and_retains_binary_offsets(self):
        self.assertEqual(loading.patch_catalog(self.fixture.original), self.fixture.patched)
        self.assertEqual(len(self.fixture.original), len(self.fixture.patched))
        for data in (self.fixture.original + b' ', b'{}', self.fixture.patched):
            with self.subTest(data=data[:16]), self.assertRaisesRegex(ValueError, 'supported build'):
                loading.patch_catalog(data)

    def test_unchanged_install_receipt_avoids_all_bundle_hash_reads(self):
        self.installed()
        with patch.object(hashlib, 'file_digest', side_effect=AssertionError('unexpected bundle scan')):
            loading.verify_installed(self.root, loading.descriptor())

    @unittest.skipUnless(os.name == 'nt', 'real Windows cached-file access refusals')
    def test_cached_bundle_read_denial_and_sharing_lock_refuse_without_rehash(self):
        from tools.owned_file_denial import OwnedFileReadDenial
        from tools.verify_profile_storage import OwnedFileLock
        plan=self.installed();prior=plan.receipt_path.read_bytes()
        path=self.root/loading.BUNDLE_DIR/next(iter(self.fixture.content))
        fingerprint=loading._fingerprint(path.stat())
        controls=(lambda:OwnedFileReadDenial(path,self.root),
                  lambda:OwnedFileLock(path,self.root,allow_read=False))
        for make in controls:
            with self.subTest(control=make):
                with make():
                    self.assertEqual(loading._fingerprint(path.stat()),fingerprint)
                    with patch.object(hashlib,'file_digest',side_effect=AssertionError('unchanged bundle should not be rehashed')):
                        with self.assertRaises(OSError):loading.verify_installed(self.root,loading.descriptor())
                self.assertEqual(plan.receipt_path.read_bytes(),prior)
                loading.verify_installed(self.root,loading.descriptor())

    def test_metadata_change_rehashes_one_unchanged_file_then_refreshes_receipt(self):
        plan = self.installed()
        path = self.root / loading.BUNDLE_DIR / next(iter(self.fixture.content))
        before = path.stat()
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
        digest = hashlib.file_digest
        with patch.object(hashlib, 'file_digest', wraps=digest) as read:
            loading.verify_installed(self.root, loading.descriptor())
            self.assertEqual(read.call_count, 1)
        with patch.object(hashlib, 'file_digest', side_effect=AssertionError('stale receipt')):
            loading.verify_installed(self.root, loading.descriptor())
        self.assertEqual(json.loads(plan.receipt_path.read_bytes())['files'][path.name]['fingerprint']['mtime_ns'], path.stat().st_mtime_ns)

    def test_same_size_changed_content_is_rejected_without_updating_receipt(self):
        plan = self.installed()
        before = plan.receipt_path.read_bytes()
        path = self.root / loading.BUNDLE_DIR / next(iter(self.fixture.content))
        old = path.stat();path.write_bytes(b'X' * old.st_size)
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns + 5_000_000_000))
        with self.assertRaisesRegex(ValueError, 'bundle hash differs'):
            loading.verify_installed(self.root, loading.descriptor())
        self.assertEqual(plan.receipt_path.read_bytes(), before)

    def test_missing_or_bad_receipt_requires_fresh_full_verification(self):
        plan = self.installed()
        good = plan.receipt_path.read_bytes()
        stale = json.loads(good);stale['inventory_sha256'] = '0' * 64
        for value in (None, b'{', b'{"schema":1,"schema":1}', json.dumps(stale).encode()):
            with self.subTest(value=value):
                if value is None:plan.receipt_path.unlink()
                else:plan.receipt_path.write_bytes(value)
                digest = hashlib.file_digest
                with patch.object(hashlib, 'file_digest', wraps=digest) as read:
                    loading.verify_installed(self.root, loading.descriptor())
                    self.assertEqual(read.call_count, 2)
                self.assertTrue(loading._valid_receipt(json.loads(plan.receipt_path.read_bytes())))

    @unittest.skipUnless(os.name == 'nt', 'real Windows cache replacement refusal')
    def test_locked_receipt_keeps_valid_content_available_and_recovers(self):
        from tools.verify_profile_storage import OwnedFileLock
        from client_patch.patcher.patch_client import atomic_write
        plan=self.installed();prior=plan.receipt_path.read_bytes()
        path=self.root/loading.BUNDLE_DIR/next(iter(self.fixture.content));info=path.stat()
        os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns+5_000_000_000))
        with OwnedFileLock(plan.receipt_path,self.root,allow_read=True):
            # Installation/other callers retain strict atomic-write failure.
            with self.assertRaises(OSError):atomic_write(plan.receipt_path,b'not published')
            errors=io.StringIO()
            with redirect_stderr(errors):loading.verify_installed(self.root,loading.descriptor())
            self.assertIn('Game files verified',errors.getvalue())
            self.assertIn('verification cache could not be saved',errors.getvalue())
            self.assertNotIn(str(self.root),errors.getvalue())
            self.assertEqual(plan.receipt_path.read_bytes(),prior)
            self.assertFalse(list(plan.receipt_path.parent.glob(plan.receipt_path.name+'.*.tmp')))
        with patch.object(hashlib,'file_digest',wraps=hashlib.file_digest) as reads:
            loading.verify_installed(self.root,loading.descriptor());self.assertEqual(reads.call_count,1)
        self.assertNotEqual(plan.receipt_path.read_bytes(),prior)
        with patch.object(hashlib,'file_digest',side_effect=AssertionError('recovered cache not reused')):
            loading.verify_installed(self.root,loading.descriptor())

    def test_cache_create_and_flush_failures_preserve_optional_receipt_state(self):
        from client_patch.patcher import patch_client
        plan=self.installed()
        for existing,stage in ((False,'create'),(True,'flush')):
            with self.subTest(existing=existing,stage=stage):
                prior=plan.receipt_path.read_bytes()
                if not existing:plan.receipt_path.unlink()
                path=self.root/loading.BUNDLE_DIR/next(iter(self.fixture.content));info=path.stat()
                os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns+5_000_000_000))
                real_open=Path.open
                def open_file(path,*args,**kwargs):
                    if path.name.startswith(plan.receipt_path.name+'.') and args and args[0]=='xb':
                        raise OSError(28,'private marker')
                    return real_open(path,*args,**kwargs)
                failure=patch.object(Path,'open',open_file) if stage=='create' else patch.object(patch_client.os,'fsync',side_effect=OSError(28,'private marker'))
                errors=io.StringIO()
                with failure,redirect_stderr(errors):loading.verify_installed(self.root,loading.descriptor())
                self.assertIn('verification cache could not be saved',errors.getvalue())
                self.assertNotIn('private marker',errors.getvalue())
                self.assertEqual(plan.receipt_path.read_bytes() if existing else None,prior if existing else None)
                self.assertEqual(plan.receipt_path.exists(),existing)
                self.assertFalse(list(plan.receipt_path.parent.glob(plan.receipt_path.name+'.*.tmp')))
                loading.verify_installed(self.root,loading.descriptor())
                self.assertTrue(loading._valid_receipt(json.loads(plan.receipt_path.read_bytes())))

    def test_bad_content_never_becomes_cache_warning_or_success(self):
        from client_patch.patcher import patch_client
        plan=self.installed();prior=plan.receipt_path.read_bytes()
        path=self.root/loading.BUNDLE_DIR/next(iter(self.fixture.content));info=path.stat()
        path.write_bytes(b'X'*info.st_size);os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns+5_000_000_000))
        errors=io.StringIO()
        with patch.object(patch_client,'atomic_write',side_effect=OSError(28,'cache write')) as writer,redirect_stderr(errors):
            with self.assertRaisesRegex(ValueError,'bundle hash differs'):loading.verify_installed(self.root,loading.descriptor())
        writer.assert_not_called();self.assertEqual(errors.getvalue(),'')
        self.assertEqual(plan.receipt_path.read_bytes(),prior)

    def test_typed_manifest_and_catalog_refusals_precede_bundle_scans(self):
        self.installed()
        values = [None, dict(loading.descriptor(), schema=True), dict(loading.descriptor(), enabled=1),
                  dict(loading.descriptor(), bundle_count=True), dict(loading.descriptor(), receipt='../escape')]
        with patch.object(hashlib, 'file_digest', side_effect=AssertionError('must reject before scan')):
            for value in values:
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'manifest differs'):
                    loading.verify_installed(self.root, value)
            self.fixture.catalog.write_bytes(self.fixture.original)
            with self.assertRaisesRegex(ValueError, 'catalog differs'):
                loading.verify_installed(self.root, loading.descriptor())

    def test_file_changed_during_hash_is_not_published(self):
        plan = self.installed();prior = plan.receipt_path.read_bytes()
        path = self.root / loading.BUNDLE_DIR / next(iter(self.fixture.content));info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))
        digest = hashlib.file_digest
        def changing(stream, algorithm):
            result = digest(stream, algorithm)
            current = path.stat()
            os.utime(path, ns=(current.st_atime_ns, current.st_mtime_ns + 5_000_000_000))
            return result
        with patch.object(hashlib, 'file_digest', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'changed during verification'):
                loading.verify_installed(self.root, loading.descriptor())
        self.assertEqual(plan.receipt_path.read_bytes(), prior)

    def test_linked_receipt_or_missing_receipt_under_linked_parent_is_refused(self):
        plan = self.installed();prior = plan.receipt_path.read_bytes()
        lstat = Path.lstat
        # Simulate a reported Windows reparse attribute; no actual junction is created.
        for target in (plan.receipt_path, plan.receipt_path.parent):
            if target == plan.receipt_path.parent:plan.receipt_path.unlink()
            def linked(path, *args, **kwargs):
                info = lstat(path, *args, **kwargs)
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == target else info
            with patch.object(Path, 'lstat', linked):
                with self.assertRaisesRegex(ValueError, 'linked paths'):
                    loading.verify_installed(self.root, loading.descriptor())
            if target == plan.receipt_path:self.assertEqual(plan.receipt_path.read_bytes(), prior)

    def test_restore_preserves_original_even_if_a_bundle_is_missing(self):
        plan = self.installed()
        (self.root / loading.BUNDLE_DIR / next(iter(self.fixture.content))).unlink()
        restore = loading.prepare_install(self.root, restore=True, previous={'asset_loading': loading.descriptor()})
        self.assertEqual(restore.installed, self.fixture.original)
        self.assertIsNone(restore.receipt_after)
        plan.backup.unlink()
        with self.assertRaisesRegex(ValueError, 'backup is missing'):
            loading.prepare_install(self.root, restore=True, previous={'asset_loading': loading.descriptor()})

    def test_legacy_restore_does_not_require_an_unmodified_catalog(self):
        self.fixture.catalog.unlink()
        self.assertIsNone(loading.prepare_install(self.root, restore=True, previous={}))
