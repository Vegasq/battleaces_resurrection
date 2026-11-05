"""Damaged asset inventories fail before native startup and preserve host state."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from server import assets, host
from server.state_lock import exclusive_state
from tests.test_credentials import private_test_folder, remove_test_folder


class AssetRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = private_test_folder('asset-recovery-')
        self.bundle = self.root / 'assets'
        self.bundle.mkdir()
        self.path = self.bundle / 'asset-manifest.json'
        self.contents = {name: b'authored asset' for name in
                         ('Simulation.dll', 'map-1v1.pb.gz', 'unit-catalog.json', 'descriptors/game_pb.proto.json')}
        self.digest = hashlib.sha256(b'authored asset').hexdigest()
        self.manifest = dict(schema=1, game_build=37822, asset_format=1,
            original_gameassembly_sha256=assets.BUILD_SHA, simulation_sha256=self.digest,
            files={name: self.digest for name in self.contents})
        for name, data in self.contents.items():
            target = self.bundle/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.write(self.manifest)
        self.pin = mock.patch.object(assets, 'SIM_SHA', self.digest)
        self.pin.start()

    def tearDown(self):
        self.pin.stop()
        remove_test_folder(self.root)

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding='utf-8')

    def failure(self, code):
        with self.assertRaises(assets.AssetError) as caught:
            assets.verify_assets(self.bundle)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(str(self.root), str(caught.exception))
        self.assertNotIn('private-marker', str(caught.exception))

    def test_non_object_and_wrong_inventory_types(self):
        for value in ([], None, 'private-marker', 1):
            with self.subTest(value=value):
                self.write(value)
                self.failure('invalid_manifest')
        for value in ([], None, 'private-marker', 1):
            with self.subTest(files=value):
                self.write(dict(self.manifest, files=value))
                self.failure('invalid_manifest')

    def test_missing_damaged_duplicate_and_non_utf8_manifest(self):
        self.path.unlink()
        self.failure('missing_manifest')
        for raw in (b'{private-marker', b'\xffprivate-marker', b'{"schema":1,"schema":1}'):
            self.path.write_bytes(raw)
            self.failure('invalid_manifest')

    def test_missing_changed_file_and_repair(self):
        path = self.bundle/'map-1v1.pb.gz'
        path.unlink()
        self.failure('missing_asset')
        path.write_bytes(b'private-marker')
        self.failure('content_mismatch')
        path.write_bytes(self.contents[path.name])
        self.assertEqual(assets.verify_assets(self.bundle), self.manifest)

    def test_schema_build_and_hash_types(self):
        for field, value, code in (('schema', True, 'unsupported_manifest'),
                                   ('game_build', 1, 'unsupported_manifest'),
                                   ('simulation_sha256', '0'*64, 'build_mismatch')):
            self.write(dict(self.manifest, **{field:value}))
            self.failure(code)
        for value in (None, 1, 'private-marker', 'G'*64):
            changed = dict(self.manifest['files'], **{'Simulation.dll':value})
            self.write(dict(self.manifest, files=changed))
            self.failure('invalid_manifest')

    def test_unsafe_paths_rejected_before_read(self):
        for name in ('../private-marker', '/private-marker', 'C:private-marker', 'x\\private-marker', '', '.', 'x\0y'):
            changed = dict(self.manifest['files'], **{name:self.digest})
            self.write(dict(self.manifest, files=changed))
            self.failure('unsafe_path')

    def test_read_permission_has_fixed_actionable_category(self):
        original = Path.read_bytes
        def read(path):
            if path.name == 'map-1v1.pb.gz':
                raise PermissionError(13, 'private-marker', str(self.root/'private-marker'))
            return original(path)
        with mock.patch.object(Path, 'read_bytes', read):
            self.failure('unreadable_asset')

    @unittest.skipUnless(os.name == 'nt', 'real Windows sharing semantics')
    def test_manifest_sharing_lock_has_fixed_error_and_releases_without_repair(self):
        from tools.verify_profile_storage import OwnedFileLock
        before=self.path.read_bytes()
        with OwnedFileLock(self.path,self.bundle,allow_read=False) as lock:
            self.assertEqual(lock.probe_winerror,32)
            self.failure('unreadable_manifest')
            with self.assertRaises(PermissionError):self.path.read_bytes()
        self.assertIsNone(lock.handle)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(assets.verify_assets(self.bundle),self.manifest)

    @unittest.skipUnless(os.name == 'nt', 'real Windows sharing semantics')
    def test_map_sharing_lock_keeps_manifest_readable_and_recovers_without_write(self):
        from tools.verify_profile_storage import OwnedFileLock
        path=self.bundle/'map-1v1.pb.gz';before=path.read_bytes()
        with OwnedFileLock(path,self.bundle,allow_read=False) as lock:
            self.assertEqual(lock.probe_winerror,32)
            self.assertEqual(json.loads(self.path.read_text()),self.manifest)
            self.failure('unreadable_asset')
            with self.assertRaises(PermissionError):path.read_bytes()
        self.assertIsNone(lock.handle)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(assets.verify_assets(self.bundle),self.manifest)

    @unittest.skipUnless(os.name == 'nt', 'real Windows read denial')
    def test_map_permission_denial_restores_exact_descriptor_and_bytes(self):
        from tools.owned_file_denial import OwnedFileReadDenial
        path=self.bundle/'map-1v1.pb.gz';before=path.read_bytes()
        control=OwnedFileReadDenial(path,self.bundle)
        with control:
            self.assertEqual(control.probe_winerror,5)
            self.assertEqual(json.loads(self.path.read_text()),self.manifest)
            self.failure('unreadable_asset')
            with self.assertRaises(PermissionError):path.read_bytes()
        self.assertTrue(control.restored)
        self.assertEqual(control.before,control.after)
        self.assertIsNone(control.handle)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(assets.verify_assets(self.bundle),self.manifest)

    @unittest.skipUnless(os.name == 'nt', 'real Windows read denial')
    def test_permission_denial_restores_on_exception(self):
        from tools.owned_file_denial import OwnedFileReadDenial
        control=OwnedFileReadDenial(self.path,self.bundle)
        with self.assertRaisesRegex(RuntimeError,'authored failure'):
            with control:
                self.failure('unreadable_manifest')
                raise RuntimeError('authored failure')
        self.assertTrue(control.restored)
        self.assertEqual(control.before,control.after)
        self.assertEqual(assets.verify_assets(self.bundle),self.manifest)

    @unittest.skipUnless(os.name == 'nt', 'real Windows file identities')
    def test_permission_control_rejects_escape_directory_and_hardlink(self):
        from tools.owned_file_denial import OwnedFileReadDenial
        for path in (self.root/'outside',self.bundle):
            with self.assertRaises(ValueError):OwnedFileReadDenial(path,self.bundle)
        alias=self.bundle/'hardlink'
        os.link(self.path,alias)
        try:
            with self.assertRaises(ValueError):OwnedFileReadDenial(self.path,self.bundle)
        finally:alias.unlink()

    @unittest.skipUnless(os.name == 'nt', 'real Windows descriptor restoration')
    def test_external_file_without_auto_inherited_bit_is_restored_exactly(self):
        from tools.owned_file_denial import OwnedFileReadDenial, EXTERNAL
        EXTERNAL.mkdir(parents=True,exist_ok=True)
        folder=Path(tempfile.mkdtemp(prefix='acl-regression-',dir=EXTERNAL))
        path=folder/'asset';path.write_bytes(b'authored regression fixture')
        try:
            control=OwnedFileReadDenial(path,folder)
            with control:
                self.assertFalse(control.before['control']&0x400)
                with self.assertRaises(PermissionError):path.read_bytes()
            self.assertEqual(control.before,control.after)
            self.assertTrue(control.restored)
            self.assertEqual(path.read_bytes(),b'authored regression fixture')
        finally:
            self.assertTrue(folder.resolve().is_relative_to(EXTERNAL.resolve()) and folder.resolve()!=EXTERNAL.resolve())
            shutil.rmtree(folder)

    def test_main_returns_one_before_worker_or_listener_and_releases_state(self):
        settings = json.loads((Path(__file__).resolve().parents[1]/'server/host-config.example.json').read_text())
        settings.update(assets_directory=str(self.bundle), data_directory=str(self.root/'data'),
                        allow_insecure_loopback=True, listen_host='127.0.0.1', dashboard_port=0,
                        certificate_file=None, private_key_file=None, credential_directory=None)
        config = self.root/'host.json'
        config.write_text(json.dumps(settings))
        state = self.root/'data/profiles/saved.json'
        state.parent.mkdir(parents=True)
        state.write_bytes(b'previous-player-state')
        for value in ([], dict(self.manifest, files=None)):
            self.write(value)
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors), mock.patch.object(host, 'check_native') as native, \
                    mock.patch.object(host, 'DedicatedServer') as server:
                self.assertEqual(host.main(['--config', str(config), '--check']), 1)
            native.assert_not_called()
            server.assert_not_called()
            self.assertIn('Host asset check failed:', errors.getvalue())
            self.assertIn('manifest', errors.getvalue())
            self.assertNotIn(str(self.root), errors.getvalue())
            self.assertEqual(state.read_bytes(), b'previous-player-state')
            with exclusive_state(self.root/'data'):
                pass


if __name__ == '__main__':
    unittest.main()
