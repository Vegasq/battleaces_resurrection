import json
import os
from pathlib import Path
import unittest
from unittest import mock

from server.configuration import load_config, ConfigurationError
from server.host_audit import HostAudit
from server import host
from server.worker_client import SimulationWorker, WorkerError
from tests.test_credentials import private_test_folder, remove_test_folder
from tests.synthetic import template as synthetic_template

ROOT = Path(__file__).resolve().parents[1]


class HostConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.root = private_test_folder('host-config-')
        (self.root / 'config').mkdir()
        self.path = self.root / 'config/host.json'
        self.settings = json.loads((ROOT / 'server/host-config.example.json').read_text())
    def tearDown(self): remove_test_folder(self.root)
    def load(self):
        self.path.write_text(json.dumps(self.settings), encoding='utf-8')
        return load_config(self.path)

    def test_paths_follow_config_and_tls_is_required_by_default(self):
        config = self.load()
        self.assertEqual(config.data_directory, self.root / 'data')
        self.assertEqual(config.assets_directory, self.root / 'assets/build-37822')
        self.assertEqual(config.private_key_file, self.root / 'config/server-key.pem')
        self.assertFalse(config.allow_insecure_loopback)
        self.settings['certificate_file'] = None
        with self.assertRaises(ConfigurationError): self.load()

    def test_experimental_command_scheduling_is_optional_and_defaults_off_in_both_schemas(self):
        for schema in (1, 2):
            self.settings['schema'] = schema
            if schema == 2: self.settings['access_mode'] = 'invite'
            for selected in (None, False, True):
                self.settings.pop('experimental_command_scheduling', None)
                if selected is not None: self.settings['experimental_command_scheduling'] = selected
                with self.subTest(schema=schema, selected=selected):
                    self.assertIs(self.load().experimental_command_scheduling, selected is True)

    def test_experimental_command_scheduling_rejects_nonboolean_json_values(self):
        for selected in (None, 0, 1, 2, '', 'false', 'true', [], {}):
            self.settings['experimental_command_scheduling'] = selected
            with self.subTest(selected=selected), self.assertRaises(ConfigurationError): self.load()

    def test_dashboard_defaults_disable_and_public_address(self):
        self.settings.pop('dashboard_host', None)
        self.settings.pop('dashboard_port', None)
        config = self.load()
        self.assertEqual((config.dashboard_host, config.dashboard_port), ('127.0.0.1', 47624))
        self.settings.update(dashboard_host='0.0.0.0', dashboard_port=8080)
        self.assertEqual(self.load().dashboard_port, 8080)
        self.settings['dashboard_port'] = 0
        self.assertEqual(self.load().dashboard_port, 0)
        for key, value in (('dashboard_host', 'localhost'), ('dashboard_host', '::1'),
                           ('dashboard_port', True), ('dashboard_port', -1), ('dashboard_port', 47623)):
            prior = self.settings.copy(); self.settings[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ConfigurationError): self.load()
            self.settings = prior

    def test_update_policy_defaults_and_bounds(self):
        self.settings.pop('minimum_client_revision', None)
        self.settings.pop('client_update_message', None)
        self.assertEqual(self.load().minimum_client_revision, 1)
        self.settings.update(minimum_client_revision=0,client_update_message='Server rollout: update your client.')
        self.assertEqual(self.load().minimum_client_revision, 0)
        for key, value in (('minimum_client_revision',True),('minimum_client_revision',-1),
                           ('client_update_message',''),('client_update_message','x'*161),('client_update_message','bad\rtext')):
            prior=self.settings.copy(); self.settings[key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ConfigurationError): self.load()
            self.settings=prior

    def test_plaintext_requires_explicit_numeric_loopback_and_no_tls_settings(self):
        self.settings.update(allow_insecure_loopback=True, certificate_file=None, private_key_file=None, credential_directory=None)
        for address in ('0.0.0.0', '192.0.2.1', 'localhost', '::1', ''):
            self.settings['listen_host'] = address
            with self.subTest(address=address), self.assertRaises(ConfigurationError): self.load()
        self.settings['listen_host'] = '127.0.0.1'
        self.assertTrue(self.load().allow_insecure_loopback)
        self.settings.update(certificate_file='cert', private_key_file='key', credential_directory='../private')
        with self.assertRaises(ConfigurationError): self.load()

    def test_ambiguous_schema_types_and_duplicates_fail_closed(self):
        for name, value in (('listen_port', True), ('max_rooms', 65), ('input_window', 1),
                            ('diagnostic_audit', 1), ('schema', True), ('unknown', 'not echoed')):
            prior = self.settings.copy(); self.settings[name] = value
            with self.subTest(name=name), self.assertRaises(ConfigurationError): self.load()
            self.settings = prior
        self.path.write_text('{"schema":1,"schema":1}')
        with self.assertRaises(ConfigurationError): load_config(self.path)

    def test_data_assets_config_and_credentials_do_not_overlap(self):
        for name, value in (('data_directory', '../assets'), ('assets_directory', '../data/assets'),
                            ('credential_directory', '../assets/build-37822/private'),
                            ('data_directory', '..'), ('private_key_file', '../data/key.pem'),
                            ('data_directory', str(ROOT / 'server'))):
            prior = self.settings.copy(); self.settings[name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ConfigurationError): self.load()
            self.settings = prior

    def test_audit_caps_actual_utf8_bytes_and_preserves_unrelated_files(self):
        directory = self.root / 'logs'; directory.mkdir()
        unrelated = directory / 'owner-notes.txt'; unrelated.write_text('keep')
        audit = HostAudit(directory, max_bytes=65536, backups=2, diagnostics=True)
        for index in range(100): audit('room_test', index=index, label='\u754c'*900)
        audit('too_large', text='x'*70000)
        audit.close()
        paths = sorted(directory.glob('events.jsonl*'))
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(path.stat().st_size <= 65536 for path in paths))
        records = [json.loads(line) for path in paths for line in path.read_text(encoding='utf-8').splitlines()]
        self.assertTrue(any(row['event'] == 'audit_record_omitted' for row in records))
        self.assertEqual(unrelated.read_text(), 'keep')
        quiet = HostAudit(self.root / 'quiet', max_bytes=65536, backups=1)
        quiet('frame_queued', frame=1); quiet('match_completed', result='test'); quiet.close()
        self.assertEqual([json.loads(line)['event'] for line in (self.root/'quiet/events.jsonl').read_text().splitlines()], ['match_completed'])

    def test_bundle_separates_runtime_and_application_from_mutable_paths(self):
        program = self.root / 'program'
        with mock.patch('server.configuration.ROOT', program / 'app'):
            self.load()
            for name, item in (('data_directory', '../program/runtime'), ('assets_directory', '../program/app/local/assets'),
                               ('private_key_file', '../program/runtime/key.pem')):
                prior = self.settings.copy(); self.settings[name] = item
                with self.subTest(name=name), self.assertRaises(ConfigurationError): self.load()
                self.settings = prior


class HostWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_host_run_passes_only_explicit_experiment_opt_in_to_real_coordinator(self):
        root = private_test_folder('host-experiment-wiring-')
        try:
            config_path = root / 'config/host.json'; config_path.parent.mkdir()
            base = json.loads((ROOT / 'server/host-config.example.json').read_text())
            base['dashboard_port'] = 0
            original_server = host.DedicatedServer
            for selected in (None, False, True):
                settings = dict(base)
                if selected is not None: settings['experimental_command_scheduling'] = selected
                config_path.write_text(json.dumps(settings))
                config = load_config(config_path)
                servers = []
                def construct(*args, **kwargs):
                    server = original_server(*args, **kwargs)
                    server.start = mock.AsyncMock(return_value=('127.0.0.1', 12345))
                    server.listener = mock.Mock()
                    server.listener.serve_forever = mock.AsyncMock()
                    server.listener.wait_closed = mock.AsyncMock()
                    servers.append(server)
                    return server
                audit = mock.Mock(); audit.aclose = mock.AsyncMock()
                manifest = dict(game_build=37822, asset_format=1, files={})
                with self.subTest(selected=selected), \
                     mock.patch.object(host, 'prepare', return_value=(synthetic_template(), None, None, manifest)), \
                     mock.patch.object(host, 'check_native', mock.AsyncMock(return_value={})), \
                     mock.patch.object(host, 'HostAudit', return_value=audit), \
                     mock.patch.object(host, 'DedicatedServer', side_effect=construct) as factory, \
                     mock.patch('builtins.print'):
                    await host.run(config)
                self.assertEqual(len(servers), 1)
                self.assertIs(factory.call_args.kwargs['experimental_command_scheduling'], selected is True)
                self.assertIs(servers[0].experimental_command_scheduling, selected is True)
                server = servers[0]
                self.assertTrue(server.closing)
                server.start.assert_awaited_once()
                audit.aclose.assert_awaited_once()
        finally: remove_test_folder(root)

    async def test_worker_uses_writable_cwd_without_importing_foreign_code(self):
        path = private_test_folder('worker-cwd-')
        try:
            (path/'server.py').write_text('raise RuntimeError("foreign cwd import")')
            (path/'sitecustomize.py').write_text('raise RuntimeError("foreign environment import")')
            with mock.patch.dict(os.environ, {'PYTHONPATH': str(path)}):
                worker = await SimulationWorker.create(b'authored synthetic game', working_directory=path, _test_backend=True)
                try:
                    self.assertEqual((await worker.state())['frame'], -1)
                finally: await worker.close()
            self.assertEqual(worker.process.poll(), 0)
            self.assertEqual(sorted(p.name for p in path.iterdir()), ['server.py', 'sitecustomize.py'])
        finally: remove_test_folder(path)

    async def test_native_health_failure_closes_owned_worker_and_never_reports_success(self):
        worker = mock.Mock()
        worker.state = mock.AsyncMock(return_value={'frame': 0xffffffff})
        worker.process_frame = mock.AsyncMock(side_effect=WorkerError('bounded test failure'))
        worker.close = mock.AsyncMock()
        template = mock.Mock(); template.build_match.return_value.raw_game_data = b'test'
        config = mock.Mock(assets_directory=Path('assets'), data_directory=Path('data'))
        with mock.patch.object(host.SimulationWorker, 'create', mock.AsyncMock(return_value=worker)):
            with self.assertRaises(WorkerError): await host.check_native(config, template)
        worker.close.assert_awaited_once()


if __name__ == '__main__': unittest.main()
