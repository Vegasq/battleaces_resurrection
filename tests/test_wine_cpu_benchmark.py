"""Authored Linux CPU orchestration controls; no systemd/Wine/native execution."""
import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tools import benchmark_wine_cpu as t

NONCE = 'a'*32
INVOCATION = 'b'*32
UNIT = 'ba-cpu-bench-'+NONCE+'.service'


def identity():
    return dict(Id=UNIT, Description=t.description(NONCE), LoadState='loaded', ActiveState='active',
                InvocationID=INVOCATION, ControlGroup='/system.slice/'+UNIT, MainPID='701')


def stopped_identity(active='inactive'):
    return dict(identity(), ActiveState=active, MainPID='0', ControlGroup='')


class CPUPlanningTests(unittest.TestCase):
    def test_cpu_lists_and_ranges_refuse_empty_duplicate_and_malformed(self):
        self.assertEqual(t.cpus('0-2,4'), {0, 1, 2, 4})
        for value in ('', '1-0', '-1', '1,1', '1-2,2', '0;whoami', '65536'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                t.cpus(value)

    def make_topology(self, root):
        (root/'online').write_text('0-3')
        for cpu in range(4):
            target = root/f'cpu{cpu}'/'topology'; target.mkdir(parents=True)
            (target/'physical_package_id').write_text('0')
            (target/'core_id').write_text(str(cpu//2))
            (target/'thread_siblings_list').write_text('0-1' if cpu < 2 else '2-3')

    def test_selects_distinct_physical_cores_and_records_smt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.make_topology(root)
            result = t.topology(root, {1, 2, 3})
            self.assertEqual(result['selected_cpus'], [1, 2])
            self.assertEqual(result['rows'][0]['thread_siblings'], [0, 1])
            with self.assertRaisesRegex(ValueError, 'two distinct'):
                t.topology(root, {0, 1})
            (root/'cpu3/topology/thread_siblings_list').write_text('3')
            with self.assertRaisesRegex(ValueError, 'inconsistent'):
                t.topology(root, {0, 2})

    def test_argv_pins_task_before_source_coordinator_and_has_finite_cleanup(self):
        with patch.object(t.os, 'getuid', return_value=1000, create=True), \
             patch.object(t.os, 'getgid', return_value=1000, create=True):
            argv = t.launch_argv(UNIT, NONCE, [0, 2], Path.cwd()/'request.json', 'c'*64, 600)
        self.assertEqual(argv[0], '/usr/bin/systemd-run')
        for value in ('--wait', '--pipe', '--property=AllowedCPUs=0,2', '--property=Delegate=yes',
                      '--property=DelegateSubgroup=coordinator', '--property=KillMode=control-group',
                      '--property=RuntimeMaxSec=690', '--property=User=1000', '-I', '-S'):
            self.assertIn(value, argv)
        self.assertNotIn('--scope', argv)
        self.assertLess(argv.index('--property=AllowedCPUs=0,2'), argv.index(t.BOOTSTRAP))

    def test_three_alternating_pairs_separate_from_profile_pair(self):
        self.assertEqual(t.schedule(), [(0,1,False), (0,2,False), (1,2,False), (1,1,False),
                                        (2,1,False), (2,2,False), (3,1,True), (3,2,True)])

    def test_unit_identity_requires_nonce_invocation_and_exact_control_group(self):
        self.assertEqual(t.verify_identity(identity(), UNIT, NONCE, INVOCATION), identity())
        for field, value in (('Description', 'unrelated'), ('InvocationID', 'c'*32),
                             ('ControlGroup', '/'), ('Id', 'live.service')):
            wrong = identity(); wrong[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                t.verify_identity(wrong, UNIT, NONCE, INVOCATION)

    def test_cleared_cgroup_is_only_valid_for_stopped_cleanup(self):
        for active in ('inactive', 'failed'):
            state = stopped_identity(active)
            with self.subTest(active=active):
                self.assertEqual(t.verify_identity(state, UNIT, NONCE, INVOCATION, cleanup=True), state)
                with self.assertRaisesRegex(ValueError, 'not active'):
                    t.verify_identity(state, UNIT, NONCE, INVOCATION)

    def test_cleanup_refuses_active_missing_or_malformed_cgroup(self):
        for active in ('active', 'activating', 'deactivating', 'reloading'):
            for control in ('', None, '/', 'relative/'+UNIT, '/system.slice/../'+UNIT,
                            '/system.slice//'+UNIT, '//system.slice/'+UNIT, '/system.slice/live.service'):
                state = identity(); state.update(ActiveState=active, ControlGroup=control)
                with self.subTest(active=active, control=control), self.assertRaisesRegex(ValueError, 'ControlGroup'):
                    t.verify_identity(state, UNIT, NONCE, INVOCATION, cleanup=True)

    def test_stopped_cleanup_requires_explicit_zero_main_pid_and_empty_cgroup(self):
        for main in (None, '', '701', '-1', '00', 0):
            state = stopped_identity(); state['MainPID'] = main
            with self.subTest(main=main), self.assertRaisesRegex(ValueError, 'main PID'):
                t.verify_identity(state, UNIT, NONCE, INVOCATION, cleanup=True)
        for control in (None, '/', '/system.slice/live.service'):
            state = stopped_identity(); state['ControlGroup'] = control
            with self.subTest(control=control), self.assertRaisesRegex(ValueError, 'ControlGroup'):
                t.verify_identity(state, UNIT, NONCE, INVOCATION, cleanup=True)
        state = stopped_identity(); del state['ControlGroup']
        with self.assertRaisesRegex(ValueError, 'ControlGroup'):
            t.verify_identity(state, UNIT, NONCE, INVOCATION, cleanup=True)

    def test_retained_cgroup_effective_mask_and_inode_fail_closed(self):
        handle = t.UnitCpuset.__new__(t.UnitCpuset)
        handle.path, handle.fd, handle.identity, handle.selected = Path('task'), 42, (1, 2), {0, 2}
        info = SimpleNamespace(st_dev=1, st_ino=2, st_mode=stat.S_IFDIR)
        def read(fd, name):
            return '0,2' if name == 'cpuset.cpus.effective' else 'context'
        with patch.object(Path, 'lstat', return_value=info), patch.object(t, 'fd_text', side_effect=read):
            self.assertEqual(handle.verify()['effective_cpus'], [0, 2])
            handle.selected = {0}
            with self.assertRaisesRegex(ValueError, 'hard cpuset'):
                handle.verify()
        info.st_ino = 3
        with patch.object(Path, 'lstat', return_value=info), self.assertRaisesRegex(ValueError, 'identity'):
            handle.verify()

    def test_owned_descendant_uses_retained_fd_and_checks_actual_thread_mask(self):
        handle = t.UnitCpuset.__new__(t.UnitCpuset)
        handle.path, handle.selected, handle.control_group = Path('/owned/task'), {0, 2}, '/system.slice/'+UNIT
        handle.verify = Mock(return_value=dict(effective_cpus=[0, 2]))
        group = SimpleNamespace(path=handle.path/'coordinator/ba-wine-worker-authored', fd=42, _same=lambda: True)
        owner = SimpleNamespace(process=SimpleNamespace(poll=lambda: None), cgroup=group)
        worker = SimpleNamespace(_backend_owner=owner)
        expected = '0::'+handle.control_group+'/coordinator/ba-wine-worker-authored'
        for allowed, inherited in (('0,2', False), ('0,2', True), ('0', False)):
            def read(fd, name):
                self.assertEqual(fd, 42)
                if name == 'cgroup.procs': return '701'
                if inherited: raise FileNotFoundError(name)
                return '0,2'
            def proc_read(path):
                return expected if path.name == 'cgroup' else 'Cpus_allowed_list:\t'+allowed+'\n'
            with patch.object(t, 'fd_text', side_effect=read), \
                 patch.object(t.os, 'scandir', return_value=nullcontext([])), \
                 patch.object(Path, 'iterdir', return_value=iter([Path('/proc/701/task/702')])), \
                 patch.object(Path, 'read_text', proc_read):
                if allowed == '0':
                    with self.assertRaisesRegex(ValueError, 'thread effective CPU mask'):
                        handle.owned_worker(worker)
                else:
                    receipt = handle.owned_worker(worker)
                    self.assertEqual(receipt['observations'][0]['threads'][0]['allowed'], [0, 2])
                    self.assertEqual(receipt['observations'][0]['inherited_from_task_unit'], inherited)


class UnitLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_systemd_query_includes_current_main_pid(self):
        with patch.object(t, 'command', AsyncMock(return_value=(0, 'LoadState=loaded\nMainPID=0\nControlGroup=\n', ''))) as command:
            state = await t.unit_state(UNIT)
        self.assertEqual(state['MainPID'], '0')
        self.assertEqual(state['ControlGroup'], '')
        self.assertIn('--property=MainPID', command.call_args.args[0])

    async def test_retained_client_termination_escalates_with_finite_waits(self):
        process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(),
                                  wait=AsyncMock(side_effect=[TimeoutError(), 0]))
        await t.stop_client(process)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.await_count, 2)

    async def test_retained_query_client_drains_pipes_during_cleanup(self):
        process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(),
                                  communicate=AsyncMock(return_value=(b'', b'')))
        await t.stop_client(process, drain=True)
        process.communicate.assert_awaited_once_with()
        process.kill.assert_not_called()

    async def test_stuck_owned_client_is_reported_after_bounded_kill(self):
        process = SimpleNamespace(returncode=None, terminate=Mock(), kill=Mock(),
                                  wait=AsyncMock(side_effect=TimeoutError()))
        with self.assertRaisesRegex(TimeoutError, 'bounded termination'):
            await t.stop_client(process)
        self.assertEqual(process.wait.await_count, 2)

    async def test_precreate_requires_actual_invocation_group_mask_before_backend(self):
        request = dict(unit=UNIT, nonce=NONCE, cpus=[0, 2])
        group = Path('/delegated')/UNIT/'coordinator'
        handle = Mock()
        handle.verify.return_value = dict(effective_cpus=[0, 2])
        env = dict(BA_CPU_BENCH_UNIT=UNIT, BA_CPU_BENCH_NONCE=NONCE, INVOCATION_ID=INVOCATION)
        with patch.dict(t.os.environ, env, clear=True), \
             patch.object(t, 'unit_state', AsyncMock(return_value=identity())), \
             patch.object(Path, 'read_text', return_value='0::/system.slice/'+UNIT+'/coordinator'), \
             patch('server.wine_worker_cgroup.current_cgroup', return_value=group), \
             patch.object(t, 'UnitCpuset', return_value=handle), \
             patch.object(t.os, 'sched_getaffinity', return_value={0, 2}, create=True):
            actual, receipt = await t.precreate_unit(request)
        self.assertIs(actual, handle)
        self.assertIs(receipt['before_wine_launch'], True)

    async def test_wrong_unit_nonce_refuses_before_opening_cgroup(self):
        with patch.dict(t.os.environ, {}, clear=True), patch.object(t, 'UnitCpuset') as constructor, \
             self.assertRaisesRegex(ValueError, 'nonce'):
            await t.precreate_unit(dict(unit=UNIT, nonce=NONCE, cpus=[0]))
        constructor.assert_not_called()

    async def test_precreate_refuses_stopped_cleared_cgroup_before_opening_it(self):
        env = dict(BA_CPU_BENCH_UNIT=UNIT, BA_CPU_BENCH_NONCE=NONCE, INVOCATION_ID=INVOCATION)
        with patch.dict(t.os.environ, env, clear=True), \
             patch.object(t, 'unit_state', AsyncMock(return_value=stopped_identity())), \
             patch.object(t, 'UnitCpuset') as constructor, self.assertRaisesRegex(ValueError, 'not active'):
            await t.precreate_unit(dict(unit=UNIT, nonce=NONCE, cpus=[0]))
        constructor.assert_not_called()

    async def test_stop_never_targets_unrelated_or_replaced_invocation(self):
        for field, value in (('Description', 'live service'), ('InvocationID', 'c'*32)):
            wrong = identity(); wrong[field] = value
            with patch.object(t, 'unit_state', AsyncMock(return_value=wrong)), \
                 patch.object(t, 'command', AsyncMock()) as command, self.assertRaises(ValueError):
                await t.stop_owned(UNIT, NONCE, INVOCATION)
            command.assert_not_awaited()

    async def test_exact_owned_stop_and_unit_absence(self):
        with patch.object(t, 'unit_state', AsyncMock(side_effect=[identity(), dict(LoadState='not-found')])), \
             patch.object(t, 'command', AsyncMock(return_value=(0, '', ''))) as command:
            result = await t.stop_owned(UNIT, NONCE, INVOCATION)
        command.assert_awaited_once_with([t.SYSTEMCTL, 'stop', UNIT], timeout=25)
        self.assertTrue(result['unit_absent'])

    async def test_already_stopped_cleared_cgroup_needs_no_stop_or_invented_path(self):
        for active in ('inactive', 'failed'):
            state = stopped_identity(active)
            with self.subTest(active=active), \
                 patch.object(t, 'unit_state', AsyncMock(return_value=state)) as query, \
                 patch.object(t, 'command', AsyncMock()) as command:
                result = await t.stop_owned(UNIT, NONCE, INVOCATION)
            query.assert_awaited_once_with(UNIT)
            command.assert_not_awaited()
            self.assertEqual(result['final_state'], state)
            self.assertEqual(result['stopped_owned_invocation'], INVOCATION)
            self.assertTrue(result['already_stopped'])

    async def test_terminal_no_cgroup_still_requires_exact_owner_and_invocation(self):
        for field, value in (('Id', 'live.service'), ('Description', 'unrelated'),
                             ('LoadState', 'error'), ('InvocationID', 'c'*32),
                             ('InvocationID', ''), ('InvocationID', None)):
            state = stopped_identity(); state[field] = value
            with self.subTest(field=field, value=value), \
                 patch.object(t, 'unit_state', AsyncMock(return_value=state)), \
                 patch.object(t, 'command', AsyncMock()) as command, self.assertRaises(ValueError):
                await t.stop_owned(UNIT, NONCE, INVOCATION)
            command.assert_not_awaited()

    async def test_terminal_with_retained_cgroup_still_uses_bounded_owned_stop(self):
        state = stopped_identity(); state['ControlGroup'] = identity()['ControlGroup']
        with patch.object(t, 'unit_state', AsyncMock(side_effect=[state, dict(LoadState='not-found')])), \
             patch.object(t, 'command', AsyncMock(return_value=(0, '', ''))) as command:
            result = await t.stop_owned(UNIT, NONCE, INVOCATION)
        command.assert_awaited_once_with([t.SYSTEMCTL, 'stop', UNIT], timeout=25)
        self.assertTrue(result['unit_absent'])

    async def test_owned_stop_accepts_terminal_cleared_cgroup_after_stop(self):
        after = stopped_identity()
        with patch.object(t, 'unit_state', AsyncMock(side_effect=[identity(), after])), \
             patch.object(t, 'command', AsyncMock(return_value=(0, '', ''))) as command:
            result = await t.stop_owned(UNIT, NONCE, INVOCATION)
        command.assert_awaited_once_with([t.SYSTEMCTL, 'stop', UNIT], timeout=25)
        self.assertEqual(result['final_state'], after)

    async def test_poststop_revalidates_terminal_owner_invocation_and_main_pid(self):
        for field, value in (('Id', 'live.service'), ('Description', 'unrelated'),
                             ('InvocationID', 'c'*32), ('MainPID', '701'), ('ControlGroup', '/')):
            after = stopped_identity(); after[field] = value
            with self.subTest(field=field), \
                 patch.object(t, 'unit_state', AsyncMock(side_effect=[identity(), after])), \
                 patch.object(t, 'command', AsyncMock(return_value=(0, '', ''))), self.assertRaises(ValueError):
                await t.stop_owned(UNIT, NONCE, INVOCATION)

    async def test_preexisting_unit_refused_before_systemd_run(self):
        with patch.object(t, 'unit_state', AsyncMock(return_value=identity())), \
             patch.object(t.asyncio, 'create_subprocess_exec', AsyncMock()) as launch, \
             self.assertRaisesRegex(ValueError, 'already exists'):
            await t.launch_arm(dict(unit=UNIT), Path('unused'), Path('unused-log'))
        launch.assert_not_awaited()

    async def test_timeout_and_cancellation_stop_only_owned_unit(self):
        for failure in (TimeoutError(), asyncio.CancelledError()):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                request = dict(unit=UNIT, nonce=NONCE, cpus=[0], source={}, receipt=str(root/'receipt.json'),
                               config=dict(timeout_seconds=30))
                process = SimpleNamespace(returncode=0, wait=AsyncMock(side_effect=failure))
                cleanup = AsyncMock(return_value=dict(unit_absent=True))
                with patch.object(t, 'unit_state', AsyncMock(return_value=dict(LoadState='not-found'))), \
                     patch.object(t, 'launch_argv', return_value=['owned-systemd-run']), \
                     patch.object(t.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process)), \
                     patch.object(t, 'stop_owned', cleanup), self.assertRaises(type(failure)):
                    await t.launch_arm(request, root/'request.json', root/'log')
                cleanup.assert_awaited_once_with(UNIT, NONCE, None)
                self.assertTrue((root/'request.launch.json').is_file())


if __name__ == '__main__':
    unittest.main()
