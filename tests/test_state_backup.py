"""Real filesystem transactions/locks; privacy mocks are explicitly scoped."""
import asyncio
from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from server import credentials as c, host, state_backup as b, protocol
from server.configuration import load_config
from server.profiles import ProfileStore, parse_profile, profile_bytes
from server.state_lock import exclusive_state, StateBusyError
from tests.synthetic import template as synthetic_template
from tests.test_credentials import private_test_folder, remove_test_folder

ROOT = Path(__file__).resolve().parents[1]


def config_at(folder):
    (folder/'config').mkdir()
    settings = json.loads((ROOT/'server/host-config.example.json').read_text())
    path = folder/'config/host.json'; path.write_text(json.dumps(settings))
    return load_config(path)


def synthetic_identity():
    return dict(game_build=37822, asset_format=1, game_protocol=protocol.VERSION,
        original_gameassembly_sha256=protocol.BUILD_SHA, simulation_sha256=protocol.SIM_SHA,
        asset_files_sha256=hashlib.sha256(b'authored synthetic assets, no game content').hexdigest())


class StateBackupTests(unittest.TestCase):
    def setUp(self):
        self.folder = private_test_folder('state-backup-')
        self.config = config_at(self.folder)
        self.template = synthetic_template()
        self.identity = synthetic_identity()
        self.patches = [
            mock.patch.object(c, '_ensure_private_directory', side_effect=lambda path: path.mkdir(parents=True, exist_ok=True)),
            mock.patch.object(c, '_assert_private_path'),
            mock.patch.object(c, '_private_create', side_effect=lambda path: path.open('x+b')),
            mock.patch.object(b, 'load_inputs', return_value=(self.template, self.identity)),
        ]
        for patch in self.patches: patch.start()
        self.profiles = ProfileStore(self.config.data_directory/'profiles', self.template)
        self.store = c.CredentialStore(self.config.credential_directory)
        self.first = self.store.issue_to_file(self.folder/'one.json', label='First')
        self.second = self.store.issue_to_file(self.folder/'two.json', label='Second')
        self.tokens = [c.read_credential_file(self.folder/name)['token'] for name in ('one.json', 'two.json')]
        self.store.revoke(self.second['invite_id'])
        self.deck = list(self.template.default_decks[0])
        self.profiles.save(self.first['player_id'], self.deck)
        self.output = self.folder/'snapshots/one.backup.json'
        self.target = self.folder/'restored'

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        remove_test_folder(self.folder)

    def test_snapshot_and_fresh_restore_preserve_deck_identity_revocation_and_originals(self):
        original_config = self.config.source.read_bytes()
        original_store = self.store.path.read_bytes()
        (self.config.data_directory/'owner-note.txt').write_text('not backed up')
        self.config.private_key_file.write_text('test marker, never a key to export')
        public = b.backup(self.config, self.output)
        self.assertEqual((public['profiles'], public['invites'], public['revoked']), (1, 2, 1))
        raw = self.output.read_bytes()
        for token in self.tokens: self.assertNotIn(token.encode(), raw)
        self.assertNotIn(b'not backed up', raw)
        self.assertNotIn(b'never a key', raw)
        self.assertTrue(b.verify_snapshot(self.config, self.output)['verified'])
        restored = b.restore(self.config, self.output, self.target)
        config = load_config(restored['config'])
        self.assertEqual(config.data_directory, self.target/'data')
        self.assertEqual(config.assets_directory, self.config.assets_directory)
        self.assertEqual(config.private_key_file, self.config.private_key_file)
        store = c.CredentialStore(config.credential_directory)
        self.assertEqual(store.list_public(), self.store.list_public())
        self.assertEqual(store.authenticate(self.tokens[0]), self.first['player_id'])
        with self.assertRaises(c.AuthenticationError): store.authenticate(self.tokens[1])
        self.assertEqual(ProfileStore(config.data_directory/'profiles', self.template).load(self.first['player_id'], []), self.deck)
        self.assertEqual(self.config.source.read_bytes(), original_config)
        self.assertEqual(self.store.path.read_bytes(), original_store)
        self.assertEqual(self.output.read_bytes(), raw)
        reissued = store.issue_to_file(self.target/'reissued.json', player_id=self.first['player_id'])
        self.assertEqual(reissued['player_id'], self.first['player_id'])

    def test_host_state_ownership_refuses_snapshot_without_output(self):
        with exclusive_state(self.config.data_directory):
            with self.assertRaises(StateBusyError): b.backup(self.config, self.output)
        self.assertFalse(self.output.exists())
        b.backup(self.config, self.output)  # Released lock is immediately usable.

    def enable_cosmetics(self):
        from server.cosmetics import CosmeticCatalog
        from tests.test_cosmetics import catalog_fixture, encode
        raw = encode(catalog_fixture())
        self.config.assets_directory.mkdir(parents=True, exist_ok=True)
        (self.config.assets_directory/'cosmetic-catalog.json').write_bytes(raw)
        catalog = CosmeticCatalog.from_bytes(raw)
        self.identity['cosmetic_catalog_sha256'] = catalog.sha256
        self.profiles = ProfileStore(self.config.data_directory/'profiles', self.template, catalog=catalog)
        pairs = list(catalog.normalize_local().slots)
        for index in (4, 12, 13): pairs[index] = (pairs[index][0], pairs[index][1]+10000)
        a, z = pairs[8], pairs[11];pairs[8], pairs[11] = (a[0], z[1]), (z[0], a[1])
        return catalog, catalog.validate_selection(pairs)

    def test_full_cosmetic_snapshot_restore_and_legacy_profile_migration(self):
        legacy = (self.profiles.path/(self.first['player_id']+'.json')).read_bytes()
        catalog, selection = self.enable_cosmetics()
        self.assertEqual(self.profiles.load_state(self.first['player_id'], []).cosmetics, catalog.normalize_local())
        self.assertEqual((self.profiles.path/(self.first['player_id']+'.json')).read_bytes(), legacy)
        self.profiles.save(self.first['player_id'], self.deck, cosmetics=selection)
        old = ProfileStore(self.profiles.path, self.template)
        old.save(self.second['player_id'], self.deck)
        legacy_second = (self.profiles.path/(self.second['player_id']+'.json')).read_bytes()
        b.backup(self.config, self.output)
        raw = self.output.read_bytes();saved = json.loads(raw)
        self.assertEqual(saved['schema'], 2)
        self.assertEqual(saved['payload']['profiles'][self.first['player_id']]['cosmetics']['slots'],
                         [list(pair) for pair in selection.slots])
        self.assertTrue(b.verify_snapshot(self.config, self.output)['verified'])
        restored = load_config(b.restore(self.config, self.output, self.target)['config'])
        copied = ProfileStore(restored.data_directory/'profiles', self.template, catalog=catalog)
        self.assertEqual(copied.load_state(self.first['player_id'], []).cosmetics, selection)
        self.assertEqual(copied.load_state(self.second['player_id'], []).cosmetics, catalog.normalize_local())
        self.assertEqual((self.profiles.path/(self.second['player_id']+'.json')).read_bytes(), legacy_second)
        self.assertEqual(self.output.read_bytes(), raw)
        for token in self.tokens: self.assertNotIn(token.encode(), raw)
        credentials = c.CredentialStore(restored.credential_directory)
        self.assertEqual(credentials.authenticate(self.tokens[0]), self.first['player_id'])
        with self.assertRaises(c.AuthenticationError): credentials.authenticate(self.tokens[1])

    def test_bad_cosmetic_snapshot_is_rejected_before_creating_restore_directory(self):
        catalog, selection = self.enable_cosmetics()
        self.profiles.save(self.first['player_id'], self.deck, cosmetics=selection)
        b.backup(self.config, self.output)
        original = json.loads(self.output.read_bytes())
        cases = []
        value = copy.deepcopy(original['payload']);value['profiles'][self.first['player_id']]['cosmetics']['catalog_sha256'] = '0'*64;cases.append(value)
        value = copy.deepcopy(original['payload']);value['profiles'][self.first['player_id']]['cosmetics']['slots'].pop();cases.append(value)
        value = copy.deepcopy(original['payload']);rows = value['profiles'][self.first['player_id']]['cosmetics']['slots'];rows[1][0] = rows[0][0];cases.append(value)
        value = copy.deepcopy(original['payload']);value['profiles'][self.first['player_id']]['cosmetics']['slots'][0][1] = 50002;cases.append(value)
        value = copy.deepcopy(original['payload']);value['profiles'][self.first['player_id']]['schema'] = 1;cases.append(value)
        value = copy.deepcopy(original['payload']);value['profiles'][self.first['player_id']] = self.deck;cases.append(value)
        for value in cases:
            self.output.write_bytes(b.canonical(dict(schema=2, payload=value, sha256=b.digest(b.canonical(value)))))
            with self.assertRaises(ValueError): b.restore(self.config, self.output, self.target)
            self.assertFalse(self.target.exists())
        # Correctly hashed schema2 cannot be opened by a catalog-less target.
        with self.assertRaisesRegex(b.BackupError, 'catalog'):
            b.validate_snapshot(b.canonical(original), self.template, self.identity, secure=True)

    def test_corrupt_full_profile_stops_backup_and_catalog_changes_stop_restore(self):
        catalog, selection = self.enable_cosmetics()
        self.profiles.save(self.first['player_id'], self.deck, cosmetics=selection)
        b.backup(self.config, self.output)
        path = self.profiles.path/(self.first['player_id']+'.json')
        corrupt = path.read_bytes()[:-3];path.write_bytes(corrupt)
        with self.assertRaises(ValueError): b.backup(self.config, self.folder/'snapshots/other.json')
        self.assertEqual(path.read_bytes(), corrupt)
        self.assertFalse((self.folder/'snapshots/other.json').exists())
        selected = self.config.assets_directory/'cosmetic-catalog.json'
        selected.write_bytes(selected.read_bytes()+b' ')
        with self.assertRaisesRegex(b.BackupError, 'catalog changed'): b.restore(self.config, self.output, self.target)
        self.assertFalse(self.target.exists())

    def test_schema1_snapshot_with_matching_assets_restores_defaults_under_new_catalog(self):
        catalog, selection = self.enable_cosmetics()
        payload = dict(created_at=1, compatibility=self.identity, profiles={self.first['player_id']:self.deck},
                       credentials=json.loads(self.store.export_snapshot()))
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b.canonical(dict(schema=1, payload=payload, sha256=b.digest(b.canonical(payload)))))
        restored = load_config(b.restore(self.config, self.output, self.target)['config'])
        state = ProfileStore(restored.data_directory/'profiles', self.template, catalog=catalog).load_state(self.first['player_id'], [])
        self.assertEqual(state.deck, tuple(self.deck))
        self.assertEqual(state.cosmetics, catalog.normalize_local())

    def test_existing_outputs_and_live_data_are_never_overwritten(self):
        records = self.store.export_snapshot()
        with mock.patch.object(Path, 'exists', return_value=False):
            # Nonexistence of a followed target (for example a dangling link)
            # must not authorize replacing an existing directory entry.
            with self.assertRaises(c.CredentialError): self.store.import_snapshot(records)
        b.backup(self.config, self.output); original = self.output.read_bytes()
        with self.assertRaises(b.BackupError): b.backup(self.config, self.output)
        self.assertEqual(self.output.read_bytes(), original)
        self.target.mkdir(); (self.target/'owner.txt').write_bytes(b'preserve')
        with self.assertRaises(FileExistsError): b.restore(self.config, self.output, self.target)
        self.assertEqual((self.target/'owner.txt').read_bytes(), b'preserve')
        for root in (self.config.data_directory, self.config.assets_directory, self.config.credential_directory):
            with self.assertRaises(b.BackupError): b.backup(self.config, root/'new.json')
            with self.assertRaises(b.BackupError): b.restore(self.config, self.output, root/'new')
        with mock.patch.object(b, 'ROOT', self.folder/'program/app'):
            for area in ('app', 'runtime'):
                path = self.folder/'program'/area/'must-not-create'
                with self.assertRaises(b.BackupError): b.backup(self.config, path)
                with self.assertRaises(b.BackupError): b.restore(self.config, self.output, path)
            self.assertFalse((self.folder/'program').exists())

    def replace_payload(self, payload):
        self.output.write_bytes(b.canonical(dict(schema=1, payload=payload, sha256=b.digest(b.canonical(payload)))))

    def test_corrupt_or_forged_snapshot_is_rejected_before_creating_destination(self):
        b.backup(self.config, self.output)
        original = json.loads(self.output.read_bytes())
        mutations = []
        value = copy.deepcopy(original['payload']); value['compatibility']['asset_files_sha256'] = '0'*64; mutations.append(value)
        value = copy.deepcopy(original['payload']); value['compatibility']['asset_format'] = True; mutations.append(value)
        value = copy.deepcopy(original['payload']); value['profiles']['../escape'] = self.deck; mutations.append(value)
        value = copy.deepcopy(original['payload']); value['profiles']['CON'] = self.deck; mutations.append(value)
        value = copy.deepcopy(original['payload']); value['profiles'][self.first['player_id'].upper()] = self.deck; mutations.append(value)
        value = copy.deepcopy(original['payload']); value['profiles'][self.first['player_id']] = [True]*8; mutations.append(value)
        value = copy.deepcopy(original['payload']); value['credentials']['invites'][0]['token'] = self.tokens[0]; mutations.append(value)
        value = copy.deepcopy(original['payload']); value['credentials'] = None; mutations.append(value)
        value = copy.deepcopy(original['payload']); value['created_at'] = True; mutations.append(value)
        for value in mutations:
            self.replace_payload(value)
            with self.assertRaises(ValueError): b.restore(self.config, self.output, self.target)
            self.assertFalse(self.target.exists())
        broken = copy.deepcopy(original); broken['payload']['created_at'] += 1
        self.output.write_text(json.dumps(broken))
        with self.assertRaisesRegex(b.BackupError, 'integrity'): b.restore(self.config, self.output, self.target)
        for raw in (b'{"schema":1,"schema":1}', b'x'*(b.MAX_BACKUP_BYTES+1), b'[]'):
            self.output.write_bytes(raw)
            with self.assertRaises(b.BackupError): b.restore(self.config, self.output, self.target)
            self.assertFalse(self.target.exists())

    def test_uncommitted_profile_temp_is_ignored_but_unknown_data_is_not_silently_dropped(self):
        temporary = self.profiles.path/('.profile-'+'0'*32+'.tmp')
        temporary.write_bytes(b'incomplete saved deck')
        b.backup(self.config, self.output)
        self.assertEqual(json.loads(self.output.read_bytes())['payload']['profiles'], {self.first['player_id']:self.deck})
        self.assertEqual(temporary.read_bytes(), b'incomplete saved deck')
        (self.profiles.path/'unexpected.txt').write_bytes(b'owner file')
        with self.assertRaises(b.BackupError): b.backup(self.config, self.folder/'snapshots/other.json')
        self.assertEqual((self.profiles.path/'unexpected.txt').read_bytes(), b'owner file')

    def test_failed_snapshot_flush_removes_only_new_partial_file(self):
        original = self.store.path.read_bytes()
        flush = os.fsync
        def fail_output(descriptor):
            if os.fstat(descriptor).st_size > 1: raise OSError('authored disk fault')
            return flush(descriptor)
        with mock.patch.object(b.os, 'fsync', side_effect=fail_output):
            with self.assertRaises(b.BackupError): b.backup(self.config, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.store.path.read_bytes(), original)
        with exclusive_state(self.config.data_directory): pass

    def test_failed_restore_retains_incomplete_new_folder_without_runnable_config(self):
        b.backup(self.config, self.output)
        original = self.store.path.read_bytes()
        with mock.patch('server.profiles.os.replace', side_effect=OSError('authored disk fault')):
            with self.assertRaises(b.BackupError): b.restore(self.config, self.output, self.target)
        self.assertTrue(self.target.is_dir())
        self.assertFalse((self.target/'host.json').exists())
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_cli_outputs_public_summary_and_never_echoes_tokens(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(b.main(['backup', '--config', str(self.config.source), '--out', str(self.output)]), 0)
        for token in self.tokens: self.assertNotIn(token, output.getvalue()+errors.getvalue())
        output = io.StringIO()
        with redirect_stderr(output), self.assertRaises(SystemExit): b.main([self.tokens[0]])
        self.assertNotIn(self.tokens[0], output.getvalue())

    def mode_config(self, mode):
        settings = json.loads(self.config.source.read_bytes())
        settings.update(schema=2, access_mode='invite')
        if mode == 'rc-open':
            settings.update(access_mode='rc-open', credential_directory=None)
        elif mode == 'development':
            settings.update(listen_host='127.0.0.1', allow_insecure_loopback=True,
                            certificate_file=None, private_key_file=None, credential_directory=None)
        else:
            self.assertEqual(mode, 'invite')
        path = self.config.source.with_name('host-'+mode+'.json')
        path.write_bytes(b.canonical(settings))
        return load_config(path)

    def test_rc_backup_restore_without_invite_store_preserves_profiles_and_tls_mode(self):
        config = self.mode_config('rc-open')
        original_config, original_store = config.source.read_bytes(), self.store.path.read_bytes()
        with mock.patch.object(c, 'CredentialStore', side_effect=AssertionError('RC mode must not open an invite store')):
            summary = b.backup(config, self.output)
            self.assertTrue(b.verify_snapshot(config, self.output)['verified'])
            result = b.restore(config, self.output, self.target)
        restored = load_config(result['config'])
        self.assertEqual((summary['profiles'], summary['invites'], summary['players'], summary['revoked']), (1, 0, 0, 0))
        envelope = json.loads(self.output.read_bytes())
        self.assertEqual(envelope['schema'], 3)
        self.assertEqual(envelope['payload']['access_mode'], 'rc-open')
        self.assertIsNone(envelope['payload']['credentials'])
        self.assertEqual(restored.access_mode, 'rc-open')
        self.assertFalse(restored.allow_insecure_loopback)
        self.assertIsNone(restored.credential_directory)
        self.assertEqual(restored.certificate_file, config.certificate_file)
        self.assertEqual(restored.private_key_file, config.private_key_file)
        self.assertEqual(restored.listen_port, config.listen_port)
        self.assertEqual(ProfileStore(restored.data_directory/'profiles', self.template).load(self.first['player_id'], []), self.deck)
        self.assertFalse((restored.data_directory/'private/credentials').exists())
        self.assertEqual(config.source.read_bytes(), original_config)
        self.assertEqual(self.store.path.read_bytes(), original_store)

    def test_rc_full_cosmetic_snapshot_roundtrip_and_bad_selection_refusal(self):
        catalog, selection = self.enable_cosmetics()
        self.profiles.save(self.first['player_id'], self.deck, cosmetics=selection)
        config = self.mode_config('rc-open')
        with mock.patch.object(c, 'CredentialStore', side_effect=AssertionError('unexpected invite store')):
            b.backup(config, self.output)
            result = b.restore(config, self.output, self.target)
        restored = load_config(result['config'])
        state = ProfileStore(restored.data_directory/'profiles', self.template, catalog=catalog).load_state(self.first['player_id'], [])
        self.assertEqual(state.deck, tuple(self.deck))
        self.assertEqual(state.cosmetics, selection)
        original = json.loads(self.output.read_bytes())
        bad = copy.deepcopy(original['payload'])
        bad['profiles'][self.first['player_id']]['cosmetics']['slots'].pop()
        self.output.write_bytes(b.canonical(dict(schema=3, payload=bad, sha256=b.digest(b.canonical(bad)))))
        refused = self.folder/'bad-cosmetics'
        with self.assertRaises(ValueError): b.restore(config, self.output, refused)
        self.assertFalse(refused.exists())

    def test_all_three_snapshot_modes_refuse_cross_mode_restore_before_creation(self):
        configs = {mode:self.mode_config(mode) for mode in ('invite', 'development', 'rc-open')}
        snapshots = {}
        for mode, config in configs.items():
            snapshots[mode] = self.folder/'snapshots'/(mode+'.json')
            b.backup(config, snapshots[mode])
            self.assertEqual(json.loads(snapshots[mode].read_bytes())['schema'], 3 if mode=='rc-open' else 1)
        for source_mode, source in snapshots.items():
            for destination_mode, config in configs.items():
                target = self.folder/('restore-'+source_mode+'-to-'+destination_mode)
                with self.subTest(source=source_mode, destination=destination_mode):
                    if source_mode == destination_mode:
                        self.assertTrue(b.verify_snapshot(config, source)['verified'])
                        restored = load_config(b.restore(config, source, target)['config'])
                        self.assertEqual(restored.access_mode, config.access_mode)
                        self.assertEqual(restored.allow_insecure_loopback, config.allow_insecure_loopback)
                        self.assertEqual(json.loads(restored.source.read_bytes())['schema'], 2)
                    else:
                        with self.assertRaisesRegex(b.BackupError, 'mode'):
                            b.verify_snapshot(config, source)
                        with self.assertRaisesRegex(b.BackupError, 'mode'):
                            b.restore(config, source, target)
                        self.assertFalse(target.exists())

    def test_rc_snapshot_requires_explicit_mode_and_no_credentials(self):
        config = self.mode_config('rc-open')
        b.backup(config, self.output)
        original = json.loads(self.output.read_bytes())['payload']
        cases = []
        for mode in ('invite', 'development', True, None):
            value = copy.deepcopy(original); value['access_mode'] = mode; cases.append(value)
        value = copy.deepcopy(original); del value['access_mode']; cases.append(value)
        value = copy.deepcopy(original); value['credentials'] = json.loads(self.store.export_snapshot()); cases.append(value)
        value = copy.deepcopy(original); value['extra'] = 'unexpected'; cases.append(value)
        for payload in cases:
            with self.subTest(keys=list(payload), mode=payload.get('access_mode')):
                self.output.write_bytes(b.canonical(dict(schema=3, payload=payload, sha256=b.digest(b.canonical(payload)))))
                with self.assertRaises(ValueError): b.restore(config, self.output, self.target)
                self.assertFalse(self.target.exists())


class ProfileDurabilityTests(unittest.TestCase):
    def test_flush_or_replace_failure_preserves_previous_deck(self):
        folder = private_test_folder('profile-durability-')
        try:
            template = synthetic_template(); profiles = ProfileStore(folder, template)
            profiles.save('player', template.default_decks[0])
            original = (folder/'player.json').read_bytes()
            for operation in ('fsync', 'replace'):
                with mock.patch('server.profiles.os.'+operation, side_effect=OSError('authored disk fault')):
                    with self.assertRaises(OSError): profiles.save('player', template.default_decks[1])
                self.assertEqual((folder/'player.json').read_bytes(), original)
                self.assertEqual(list(folder.glob('*.tmp')), [])
            for raw in (b'{"schema":1,"schema":1}', b'x'*4097,
                        profile_bytes('another', template.default_decks[0], template)):
                with self.assertRaises(ValueError): parse_profile(raw, 'player', template)
        finally: remove_test_folder(folder)


class StateLockTests(unittest.IsolatedAsyncioTestCase):
    def test_empty_lock_from_interrupted_initial_creation_recovers_under_lock(self):
        folder = private_test_folder('empty-state-lock-')
        try:
            (folder/'.host.lock').touch()
            with exclusive_state(folder):
                with self.assertRaises(StateBusyError):
                    with exclusive_state(folder): self.fail('Interrupted lock admitted a second owner')
            self.assertEqual((folder/'.host.lock').read_bytes(), b'\0')
        finally: remove_test_folder(folder)

    async def test_host_and_check_hold_one_lock_until_cancelled_cleanup_finishes(self):
        folder = private_test_folder('host-lock-')
        entered = asyncio.Event()
        async def owned(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        task = None
        try:
            config = mock.Mock(data_directory=folder/'data')
            with mock.patch.object(host, '_run_owned', side_effect=owned) as run:
                task = asyncio.create_task(host.run(config))
                await asyncio.wait_for(entered.wait(), 2)
                with self.assertRaises(StateBusyError): await host.run(config, check_only=True)
                self.assertEqual(run.call_count, 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
            with exclusive_state(config.data_directory): pass
        finally:
            if task and not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
            remove_test_folder(folder)

    async def test_actual_child_crash_releases_lock_without_deleting_lock_file(self):
        folder = private_test_folder('state-lock-process-')
        process = None
        code = ('import sys;sys.path.insert(0,sys.argv[1]);from server.state_lock import exclusive_state\n'
                'with exclusive_state(sys.argv[2]):\n print("owned",flush=True)\n sys.stdin.read(1)\n')
        try:
            # Ordinary anonymous pipes match the worker transport; asyncio's
            # Windows overlapped named-pipe creation is denied in restricted runs.
            process = subprocess.Popen([sys.executable, '-I', '-B', '-c', code,
                str(ROOT), str(folder)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            ready = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 5)
            self.assertEqual(ready.rstrip(b'\r\n'), b'owned')
            with self.assertRaises(StateBusyError):
                with exclusive_state(folder): self.fail('Concurrent state lock was acquired')
            process.kill(); process.wait(timeout=5)
            with exclusive_state(folder): pass
            self.assertEqual((folder/'.host.lock').read_bytes(), b'\0')
        finally:
            if process:
                if process.poll() is None: process.kill(); process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr): stream.close()
            remove_test_folder(folder)


@unittest.skipUnless(os.name == 'nt' and os.environ.get('BA_RUN_PRIVATE_ACL_TESTS') == '1',
                     'real snapshot DACL test requires explicit BA_RUN_PRIVATE_ACL_TESTS=1 on Windows')
class WindowsStateBackupPrivacyTests(unittest.TestCase):
    def test_real_private_snapshot_and_restore_permissions(self):
        folder = private_test_folder('backup-real-acl-')
        try:
            try:
                config = config_at(folder); template = synthetic_template()
                profiles = ProfileStore(config.data_directory/'profiles', template)
                store = c.CredentialStore(config.credential_directory)
                handoff_file = config.credential_directory/'test-invite.json'
                public = store.issue_to_file(handoff_file)
                profiles.save(public['player_id'], template.default_decks[0])
                output, restored = folder/'snapshots/one.json', folder/'restored'
                # Only game assets are synthetic here; all OS privacy, locking,
                # writes and readback use the actual implementation.
                with mock.patch.object(b, 'load_inputs', return_value=(template, synthetic_identity())):
                    b.backup(config, output)
                    result = b.restore(config, output, restored)
                c._assert_private_path(output)
                restored_config = load_config(result['config'])
                recovered = c.CredentialStore(restored_config.credential_directory)
                c._assert_private_path(recovered.directory, directory=True)
                c._assert_private_path(recovered.path)
                c._assert_private_path(restored_config.source)
                self.assertEqual(recovered.authenticate(c.read_credential_file(handoff_file)['token']), public['player_id'])
            except c.CredentialError as error:
                if any(word in str(error) for word in ('inaccessible', 'unavailable', 'cannot create private')):
                    self.skipTest('observed restricted-token/private-DACL limitation: '+str(error))
                raise
        finally:
            try: remove_test_folder(folder)
            except PermissionError: pass  # Do not change ACLs for cleanup.


if __name__ == '__main__': unittest.main()
