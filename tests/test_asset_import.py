import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from server.game_data import canonical_gzip
from server.protocol import BUILD_SHA, SIM_SHA
from tests.synthetic import template
from tools.import_assets import import_assets, verify_export


class AssetImportTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(__file__).resolve().parents[1] / 'local/test-assets'
        self.directory = self.base / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        raw = template().raw_game_data
        self.data = {'map-1v1.pb.gz': canonical_gzip(raw), 'unit-catalog.json': b'{"synthetic":true}'}
        self.manifest = {'schema': 1, 'asset_format': 1, 'build': 37822, 'complete': True,
                         'original_gameassembly_sha256': BUILD_SHA, 'simulation_sha256': SIM_SHA,
                         'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                                   for name, data in self.data.items()},
                         'raw_game_data': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}}
        for name, data in self.data.items():
            (self.directory / name).write_bytes(data)
        self.write_manifest()

    def tearDown(self):
        target = self.directory.resolve()
        self.assertEqual(target.parent, self.base.resolve())
        self.assertEqual(len(target.name), 32)
        shutil.rmtree(target)

    def write_manifest(self):
        (self.directory / 'export.json').write_text(json.dumps(self.manifest))

    def test_complete_export_verified_before_import(self):
        self.assertEqual(verify_export(self.directory), self.data)

    def test_corrupt_payload_or_hash_cannot_be_imported(self):
        (self.directory / 'unit-catalog.json').write_bytes(b'{"altered":true}')
        with self.assertRaisesRegex(ValueError, 'size/hash'):
            verify_export(self.directory)

    def test_incomplete_or_wrong_build_rejected(self):
        for key, value in (('complete', False), ('build', 1), ('original_gameassembly_sha256', '0' * 64)):
            original = self.manifest[key]
            self.manifest[key] = value
            self.write_manifest()
            with self.assertRaises(ValueError):
                verify_export(self.directory)
            self.manifest[key] = original

    def test_import_cannot_write_into_tracked_source(self):
        source = Path(__file__).resolve().parents[1] / 'server'
        with self.assertRaisesRegex(ValueError, 'ignored local'):
            import_assets('unused-game', self.directory, source)
