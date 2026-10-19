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
from server.ai_rules import SUPPORTED_AI_SHA256
from tests.test_ai_rules import synthetic_rules
from tests.test_bot_catalog import catalog_fixture


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

    def test_cosmetic_export_requires_envelope_hash_and_strict_inner_matrix(self):
        from tests.test_cosmetics import catalog_fixture as cosmetics_fixture, encode
        name = 'cosmetic-catalog.json'
        def update(raw):
            (self.directory/name).write_bytes(raw)
            self.manifest['files'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            self.write_manifest()
        data = cosmetics_fixture();raw = encode(data);update(raw)
        self.assertEqual(verify_export(self.directory)[name], raw)
        (self.directory/name).write_bytes(raw+b' ')
        with self.assertRaisesRegex(ValueError, 'size/hash'): verify_export(self.directory)
        data['slots'][0]['compatible_items'] = [0xffffffff];update(encode(data))
        with self.assertRaises(ValueError): verify_export(self.directory)

    def test_ai_export_requires_both_envelope_hash_and_valid_inner_rules(self):
        rules, _ = synthetic_rules()
        entry = dict(profile=4, mode=1, enabled=True, file='ai-rules-4.fb', bytes=len(rules), sha256=hashlib.sha256(rules).hexdigest())
        metadata = dict(schema=1, build=37822, format='Uncapped.Flatbuffers.Fuzzy', ai_dll_sha256=SUPPORTED_AI_SHA256,
                        default_profile=4, profiles=[entry])
        def update():
            data = json.dumps(metadata).encode()
            (self.directory/'ai-rules.json').write_bytes(data)
            self.manifest['files']['ai-rules.json'] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            self.write_manifest()
        (self.directory/entry['file']).write_bytes(rules); update()
        self.assertEqual(verify_export(self.directory)[entry['file']], rules)
        (self.directory/entry['file']).write_bytes(b'\0'*len(rules))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): verify_export(self.directory)
        entry['sha256'] = hashlib.sha256(b'\0'*len(rules)).hexdigest(); update()
        with self.assertRaisesRegex(ValueError, 'offset'): verify_export(self.directory)

    def add_bot_bundle(self):
        source, bots = template(), catalog_fixture()
        catalog = dict(slot_flags=list(source.slot_flags), units=[dict(id=key, menu_slot_flags=row['deck_slot_flags'],
                       release_deck_playable=True, menu_entity_present=True, active_ability_groups=[])
                       for key, row in source.catalog.items()])
        self.data['unit-catalog.json'] = json.dumps(catalog).encode()
        self.data['bot-catalog.json'] = json.dumps(bots).encode()
        self.manifest['raw_maps'] = {'map-1v1.pb.gz': self.manifest['raw_game_data']}
        for name, mode in (('map-2v2.pb.gz', 2), ('map-2vai.pb.gz', 5)):
            raw = template(mode).raw_game_data
            self.data[name] = canonical_gzip(raw)
            self.manifest['raw_maps'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        rules, _ = synthetic_rules()
        entries = []
        for row in bots['profiles']:
            name = f"ai-rules-{row['profile']}.fb"
            (self.directory/name).write_bytes(rules)
            entries.append(dict(profile=row['profile'], mode=row['mode'], enabled=True, file=name,
                                bytes=len(rules), sha256=hashlib.sha256(rules).hexdigest()))
        self.data['ai-rules.json'] = json.dumps(dict(schema=1, build=37822, format='Uncapped.Flatbuffers.Fuzzy',
                   ai_dll_sha256=SUPPORTED_AI_SHA256, default_profile=501, profiles=entries)).encode()
        for name, data in self.data.items():
            (self.directory/name).write_bytes(data)
            self.manifest['files'][name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.write_manifest()

    def test_complete_team_bot_bundle_and_inner_catalog_are_verified(self):
        self.add_bot_bundle()
        verified = verify_export(self.directory)
        self.assertTrue({'map-2v2.pb.gz', 'map-2vai.pb.gz', 'bot-catalog.json', 'ai-rules-505.fb'} <= verified.keys())
        bots = catalog_fixture(); bots['profiles'][0]['decks'][0]['deck_hex'] = '00'
        changed = json.dumps(bots).encode()
        (self.directory/'bot-catalog.json').write_bytes(changed)
        self.manifest['files']['bot-catalog.json'] = dict(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
        self.write_manifest()
        with self.assertRaises(ValueError): verify_export(self.directory)

    def test_missing_team_map_or_uncompressed_hash_cannot_be_accepted(self):
        self.add_bot_bundle()
        saved = self.manifest['files'].pop('map-2vai.pb.gz'); self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Incomplete team'): verify_export(self.directory)
        self.manifest['files']['map-2vai.pb.gz'] = saved
        self.manifest['raw_maps']['map-2vai.pb.gz']['sha256'] = '0'*64; self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'uncompressed map hash'): verify_export(self.directory)
