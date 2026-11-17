import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from server import host
from server.configuration import ConfigurationError, WineWorkerConfig, load_config
from tests.synthetic import template as synthetic_template
from tests.test_credentials import private_test_folder, remove_test_folder

ROOT = Path(__file__).resolve().parents[1]


class HybridConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.root = private_test_folder('hybrid-config-')
        (self.root/'config').mkdir()
        self.path = self.root/'config/host.json'
        self.raw = json.loads((ROOT/'server/host-config.example.json').read_text())
        self.raw['dashboard_port'] = 0

    def tearDown(self):
        remove_test_folder(self.root)

    def load(self):
        self.path.write_text(json.dumps(self.raw), encoding='utf-8')
        return load_config(self.path)

    def worker(self):
        return dict(wine_executable='../bin/wine', windows_python='../runtime space/python.exe',
                    prefix_template='../prefix-é')

    def test_existing_windows_configs_remain_explicitly_without_wine(self):
        self.assertIsNone(self.load().wine_worker)
        self.raw['wine_worker'] = None
        self.assertIsNone(self.load().wine_worker)

    def test_runtime_paths_resolve_relative_to_config_including_spaces_and_unicode(self):
        self.raw['wine_worker'] = self.worker()
        value = self.load().wine_worker
        self.assertIsInstance(value, WineWorkerConfig)
        self.assertEqual(value.wine_executable, self.root/'bin/wine')
        self.assertEqual(value.windows_python, self.root/'runtime space/python.exe')
        self.assertEqual(value.prefix_template, self.root/'prefix-é')

    def test_incomplete_unknown_and_nonobject_worker_configs_are_refused(self):
        for value in (False, 0, [], '', {}, {'wine_executable': 'wine'},
                      self.worker() | {'shell': 'anything'}):
            self.raw['wine_worker'] = value
            with self.subTest(value=value), self.assertRaises(ConfigurationError):
                self.load()

    def test_explicit_cgroup_delegation_path_is_preserved(self):
        self.raw['wine_worker'] = self.worker() | {'cgroup_parent': '../delegated'}
        self.assertEqual(self.load().wine_worker.cgroup_parent, self.root/'delegated')
        self.raw['wine_worker']['cgroup_parent'] = None
        self.assertIsNone(self.load().wine_worker.cgroup_parent)

    def test_nonlocal_empty_or_nonstring_worker_paths_are_refused(self):
        for name in self.worker():
            for value in ('', ' ', '\0', '//host/share', '\\\\host\\share', False, None, []):
                self.raw['wine_worker'] = self.worker() | {name: value}
                with self.subTest(name=name, value=value), self.assertRaises(ConfigurationError):
                    self.load()

    def test_wine_config_cannot_silently_select_a_windows_coordinator(self):
        self.raw['wine_worker'] = self.worker()
        config = self.load()
        with mock.patch.object(host.sys, 'platform', 'win32'), mock.patch.object(host, 'verify_assets') as verify:
            with self.assertRaisesRegex(ConfigurationError, 'Linux coordinator'):
                host.prepare(config)
            verify.assert_not_called()


class HybridHostRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_check_uses_selected_backend_and_reaps_it(self):
        backend = object()
        worker = mock.Mock()
        worker.state = mock.AsyncMock(return_value={'frame': 0xffffffff})
        worker.process_frame = mock.AsyncMock(return_value=SimpleNamespace(frame=0))
        worker.close = mock.AsyncMock()
        worker.process.poll.return_value = 0
        worker.pid, worker.dll_sha256 = 123, 'a'*64
        worker.native_pid = 44
        worker.runtime_info = {'python': '3.14.8', 'platform': 'win32'}
        worker.backend_statistics = dict(native_exit_code=0, cleanup_complete=True,
                                         prefix_removed=True, cgroup_removed=True)
        config = SimpleNamespace(assets_directory=Path('assets'), data_directory=Path('data'))
        template = mock.Mock()
        template.build_match.return_value.raw_game_data = b'authored health data'
        with mock.patch.object(host.SimulationWorker, 'create', mock.AsyncMock(return_value=worker)) as create:
            result = await host.check_native(config, template, backend=backend)
        self.assertIs(create.call_args.kwargs['backend'], backend)
        worker.close.assert_awaited_once()
        self.assertTrue(result['reaped'])
        self.assertEqual(result['guardian_pid'], 123)
        self.assertEqual(result['native_pid'], 44)
        self.assertIs(result['backend_statistics'], worker.backend_statistics)

    async def test_guardian_success_cannot_hide_native_failure_or_incomplete_cleanup(self):
        worker = mock.Mock()
        worker.state = mock.AsyncMock(return_value={'frame': 0xffffffff})
        worker.process_frame = mock.AsyncMock(return_value=SimpleNamespace(frame=0))
        worker.close = mock.AsyncMock()
        worker.process.poll.return_value = 0
        config = SimpleNamespace(assets_directory=Path('assets'), data_directory=Path('data'))
        template = mock.Mock()
        for change in ({'native_exit_code': 1}, {'cleanup_complete': False},
                       {'prefix_removed': False}, {'cgroup_removed': False}):
            worker.backend_statistics = dict(native_exit_code=0, cleanup_complete=True,
                                              prefix_removed=True, cgroup_removed=True) | change
            with self.subTest(change=change), \
                 mock.patch.object(host.SimulationWorker, 'create', mock.AsyncMock(return_value=worker)), \
                 self.assertRaisesRegex(host.WorkerError, 'cleanup'):
                await host.check_native(config, template, backend=object())

    async def test_native_coordinator_routes_health_human_and_ai_to_one_backend(self):
        root = private_test_folder('hybrid-routing-')
        try:
            settings = json.loads((ROOT/'server/host-config.example.json').read_text())
            settings['dashboard_port'] = 0
            (root/'config').mkdir()
            path = root/'config/host.json'; path.write_text(json.dumps(settings))
            config = load_config(path)
            backend = object()
            server = mock.Mock()
            server.start = mock.AsyncMock(return_value=('127.0.0.1', 12345))
            server.listener.serve_forever = mock.AsyncMock()
            server.close = mock.AsyncMock()
            audit = mock.Mock(); audit.aclose = mock.AsyncMock()
            manifest = dict(game_build=37822, asset_format=1, files={})
            with mock.patch.object(host, 'prepare', return_value=(synthetic_template(), None, None, manifest)), \
                 mock.patch.object(host, 'select_worker_backend', return_value=backend), \
                 mock.patch.object(host, 'check_native', mock.AsyncMock(return_value={})) as check, \
                 mock.patch.object(host, 'HostAudit', return_value=audit), \
                 mock.patch.object(host, 'ProfileStore'), \
                 mock.patch.object(host, 'DedicatedServer', return_value=server) as factory, \
                 mock.patch.object(host.SimulationWorker, 'create', mock.AsyncMock()) as create, \
                 mock.patch('builtins.print'):
                await host._run_owned(config)
                check.assert_awaited_once_with(config, mock.ANY, backend=backend)
                await factory.call_args.kwargs['sim_factory'](b'human world')
                self.assertIs(create.call_args.kwargs['backend'], backend)
                await factory.call_args.kwargs['ai_factory'](b'AI world', {1: 58})
                self.assertIs(create.call_args.kwargs['backend'], backend)
                self.assertEqual(create.call_args.kwargs['ai'].bots, {1: 58})
            server.close.assert_awaited_once()
            audit.aclose.assert_awaited_once()
        finally:
            remove_test_folder(root)


if __name__ == '__main__':
    unittest.main()
