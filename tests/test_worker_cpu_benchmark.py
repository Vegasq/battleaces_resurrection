"""CPU experiment orchestration controls; no native launches or actual affinity."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from tools import benchmark_worker_cpu as t


class CPUBenchmarkTests(unittest.TestCase):
    def test_three_alternating_primary_pairs_then_separate_profile_pair(self):
        self.assertEqual(t.schedule(), [(0, 1, False), (0, 2, False), (1, 2, False),
                         (1, 1, False), (2, 1, False), (2, 2, False), (3, 1, True), (3, 2, True)])

    def test_summaries_keep_phases_separate_and_count_budget_misses(self):
        rows = [dict(phase=phase, step_rpc_ms=value) for phase, value in
                [('setup', 1), ('movement', 30), ('combat', 51), ('combat', 101)]]
        result = t.whole_step_summary(rows)
        self.assertEqual(result['combat']['above_50ms'], 2)
        self.assertEqual(result['combat']['above_100ms'], 1)
        self.assertEqual(result['movement']['mean'], 30)

    def test_cli_explicit_both_retained_workloads(self):
        args = t.arguments(['--workload', 'wasp', 'a', 'j', '--workload', 'crab', 'b', 'k',
                            '--library', 'decoder.dll', '--library-sha256', 'a'*64, '--output', 'out'])
        self.assertEqual([row[0] for row in args.workload], ['wasp', 'crab'])
        self.assertIn('limited', args.environment_notes)


class CPUArmTests(unittest.IsolatedAsyncioTestCase):
    def options(self):
        return SimpleNamespace(assets=Path('assets'), output=Path('output'), profile_worker=False,
                              snapshot_decoder_library=Path('decoder.dll'), snapshot_decoder_sha256='a'*64)

    async def test_one_launch_passes_affinity_before_create_and_restores_callback(self):
        original = t.b.create_worker
        worker = SimpleNamespace(affinity_info=dict(before_create=True, actual_mask=5), close=AsyncMock())
        old_close = worker.close
        policy = SimpleNamespace(verify=lambda: 5)
        create = AsyncMock(return_value=worker)

        async def run(options):
            await t.b.create_worker(options, b'data', Path('owned'))
            self.assertIs(t.b.create_worker, original)
            await worker.close()
            return 0

        with patch.object(t, 'WindowsWorkerAffinity', return_value=policy), \
             patch.object(t.SimulationWorker, 'create', create), patch.object(t.b, 'run', run):
            receipt = await t.run_owned_arm(self.options(), [0, 2])
        self.assertIs(t.b.create_worker, original)
        self.assertIs(create.call_args.kwargs['owned_cpu_affinity'], policy)
        self.assertEqual(receipt['before_close_mask'], 5)
        old_close.assert_awaited_once()

    async def test_verification_failure_still_closes_owned_worker(self):
        original = t.b.create_worker
        worker = SimpleNamespace(affinity_info=dict(before_create=True, actual_mask=1), close=AsyncMock())
        old_close = worker.close
        values = iter([1, ValueError('mask changed')])

        def verify():
            value = next(values)
            if isinstance(value, Exception): raise value
            return value

        async def run(options):
            await t.b.create_worker(options, b'data', Path('owned'))
            await worker.close()
            return 0

        with patch.object(t, 'WindowsWorkerAffinity', return_value=SimpleNamespace(verify=verify)), \
             patch.object(t.SimulationWorker, 'create', AsyncMock(return_value=worker)), \
             patch.object(t.b, 'run', run), self.assertRaisesRegex(ValueError, 'mask changed'):
            await t.run_owned_arm(self.options(), [0])
        old_close.assert_awaited_once()
        self.assertIs(t.b.create_worker, original)

    async def test_callback_restored_when_benchmark_refuses_before_launch(self):
        original = t.b.create_worker
        with patch.object(t.b, 'run', AsyncMock(side_effect=ValueError('preflight'))), \
             self.assertRaisesRegex(ValueError, 'preflight'):
            await t.run_owned_arm(self.options(), [0])
        self.assertIs(t.b.create_worker, original)


if __name__ == '__main__':
    unittest.main()
