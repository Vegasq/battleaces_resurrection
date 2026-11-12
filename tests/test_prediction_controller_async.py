"""The diagnostic log decoder must not stall its own network event loop."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from tools import verify_prediction_multiplayer as verifier
from tools.prediction_input_delay import SETTINGS
from tests import test_prediction_multiplayer_verifier as existing


class ControllerAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = existing.ChangingRttControllerTests()
        self.fixture.setUp()
        self.owner_thread = threading.get_ident()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        f = self.fixture
        f.relay.changes.clear()
        f.control = verifier.ChangingRttController(lambda: f.clock, lambda: f.clock * 1_000_000,
            transition_gates=self.folder, directional_delay=dict(SETTINGS))
        self.mutations = []
        self.native_log = ''
        self.logged_rows = self.logged_rtt = self.logged_extra = 0
        setter = f.relay.set_rtt_ms

        def set_rtt(value, *, tick):
            self.mutations.append(('rtt', value, threading.get_ident()))
            return setter(value, tick=tick)

        def set_delay(**kwargs):
            self.mutations.append(('delay', None, threading.get_ident()))
            return dict(window_id=1, effective_tick_ms=f.clock,
                        effective_perf_counter_ns=f.clock * 1_000_000)

        f.relay.set_rtt_ms = set_rtt
        f.relay.set_directional_delay = set_delay
        publish = verifier.publish_transition_gate

        def gate(*args):
            self.mutations.append(('gate', args[2], threading.get_ident()))
            return publish(*args)

        patched = mock.patch.object(verifier, 'publish_transition_gate', side_effect=gate)
        patched.start()
        self.addCleanup(patched.stop)
        f.control.begin(f.match, f.relay)

    def log(self):
        f = self.fixture
        # Live native logs append in time order; rebuilding category blocks
        # would rewrite old RTT rows whenever a new pose arrives.
        for row in f.rows[self.logged_rows:]:
            self.native_log += 'MOVEMENT FEEL ' + json.dumps(row) + '\n'
        self.native_log += f.rtt[self.logged_rtt:]
        extra = getattr(f, 'extra_log', '')
        self.native_log += extra[self.logged_extra:]
        self.logged_rows, self.logged_rtt, self.logged_extra = len(f.rows), len(f.rtt), len(extra)
        return self.native_log

    async def update(self):
        # Exercise the pre-fix synchronous live path for the retained RED, then
        # the new live API once available. This is a behavioral failure control.
        f = self.fixture
        if hasattr(f.control, 'update_async'):
            await f.control.update_async(self.log(), f.relay)
        else:
            f.control.update(self.log(), f.relay)

    def gated_decoder(self, *, error=None):
        original = verifier.feel_rows
        entered, release, finished = (threading.Event() for _ in range(3))
        threads = []

        def decode(log):
            threads.append(threading.get_ident())
            entered.set()
            try:
                self.assertNotEqual(threading.get_ident(), self.owner_thread,
                                    'native log decoder blocked the relay owner thread')
                self.assertTrue(release.wait(3), 'test did not release decoder')
                if error is not None:
                    raise error
                return original(log)
            finally:
                finished.set()

        return mock.patch.object(verifier, 'feel_rows', side_effect=decode), entered, release, finished, threads

    async def wait_event(self, event):
        async def wait():
            while not event.is_set():
                await asyncio.sleep(.001)
        await asyncio.wait_for(wait(), 2)

    async def ready_fall(self):
        self.fixture.clock = 1700
        await self.update()
        self.fixture.fall_ready()
        self.fixture.clock = 5700

    async def test_gated_decoder_leaves_relay_heartbeat_running_and_mutations_on_owner(self):
        self.fixture.clock = 1700
        patched, entered, release, finished, threads = self.gated_decoder()
        with patched:
            task = asyncio.create_task(self.update())
            try:
                await self.wait_event(entered)
                self.assertFalse(task.done(), 'decoder completed before its release')
                heartbeats = 0
                for _ in range(3):
                    await asyncio.sleep(.005)
                    heartbeats += 1
                self.assertEqual(heartbeats, 3)
                self.assertEqual(self.fixture.relay.changes, [130])
            finally:
                release.set()
                await task
        self.assertTrue(finished.is_set())
        self.assertEqual(self.fixture.relay.changes, [130, 475])
        self.assertTrue(threads and all(t != self.owner_thread for t in threads))
        self.assertTrue(all(row[2] == self.owner_thread for row in self.mutations))

    async def test_fall_delay_and_gate_mutations_remain_on_owner_thread(self):
        await self.ready_fall()
        await self.update()
        self.assertEqual([row[:2] for row in self.mutations],
                         [('rtt', 130), ('rtt', 475), ('rtt', 130), ('delay', None), ('gate', 2)])
        self.assertTrue(all(row[2] == self.owner_thread for row in self.mutations))
        self.assertEqual(len(list(self.folder.iterdir())), 1)

    async def test_recovered_phase_decoding_is_off_loop_and_turn3_write_stays_on_owner(self):
        await self.ready_fall()
        await self.update()
        f = self.fixture
        turn = dict(f.command(), ordinal=2, move_id=2, origin=[20, 0, 0], target=[-28, 0, 0],
                    motion_from=[19, 0, 0], sampled_us=5800000, motion_from_sampled_us=5700000,
                    enqueue_sampled_us=5800001, tick_ms=5800, presented_frame=532,
                    completed_frame=532, physical_frame=532, originalCtor=True,
                    physicalUI=False, queueDelta=1, action_sha256='b' * 64)
        f.rtt += f.sample(3, 5800, raw=130, estimate=130)
        f.extra_log = 'MOVEMENT TURN ' + json.dumps(turn) + '\n'
        f.extra_log += f'Movement pacing START: match={f.match} world=7 waitSteadyFrame=1\n'
        for tick, frame in ((6000, 540), (6600, 552)):
            f.extra_log += (f'[{tick}] Movement pacing waiting: reason=6 next={frame} confirmed=500 received=500 '
                f'networkReceived=500 physical={frame-1} presented={frame-1} targetAssigned={frame-1} rtt_us=130000\n')
        f.rows.extend([f.pose(6500, 18, 550), f.pose(6600, 17, 552)])
        f.clock = 6600
        original = verifier.phase_rows
        decoder_threads = []

        def phases(*args):
            decoder_threads.append(threading.get_ident())
            return original(*args)

        with mock.patch.object(verifier, 'phase_rows', side_effect=phases):
            await self.update()
        self.assertTrue(decoder_threads and all(t != self.owner_thread for t in decoder_threads))
        self.assertIn('turn3_gate', f.control.worlds[-1])
        self.assertEqual(self.mutations[-1], ('gate', 3, self.owner_thread))
        self.assertEqual(len(list(self.folder.iterdir())), 2)

    async def stale_world(self, failure=None):
        await self.ready_fall()
        patched, entered, release, finished, _ = self.gated_decoder(error=failure)
        with patched:
            task = asyncio.create_task(self.update())
            try:
                await self.wait_event(entered)
                f = self.fixture
                f.control.worlds[-1]['stage'] = 'failed'
                f.control.begin('b' * 32, f.relay)
                expected = deepcopy(f.control.worlds[-1])
                expected_cache = f.control._live_decode_cache
                mutations = list(self.mutations)
            finally:
                release.set()
                await task
        self.assertEqual(self.fixture.control.worlds[-1], expected)
        self.assertIs(self.fixture.control._live_decode_cache, expected_cache)
        self.assertEqual(self.mutations, mutations)
        self.assertFalse(list(self.folder.iterdir()))

    async def test_new_world_discards_old_decoded_result(self):
        await self.stale_world()

    async def test_new_world_discards_old_decode_assertion(self):
        await self.stale_world(AssertionError('old decoder failure'))

    async def test_new_world_discards_old_decode_value_error(self):
        await self.stale_world(ValueError('old malformed JSON'))

    async def test_same_world_state_change_discards_pending_result(self):
        await self.ready_fall()
        patched, entered, release, finished, _ = self.gated_decoder()
        with patched:
            task = asyncio.create_task(self.update())
            try:
                await self.wait_event(entered)
                self.fixture.control.worlds[-1]['stage'] = 'failed'
                expected = deepcopy(self.fixture.control.worlds[-1])
                mutations = list(self.mutations)
            finally:
                release.set()
                await task
        self.assertEqual(self.fixture.control.worlds[-1], expected)
        self.assertEqual(self.mutations, mutations)
        self.assertFalse(list(self.folder.iterdir()))

    async def test_changed_gate_destination_discards_pending_result(self):
        await self.ready_fall()
        patched, entered, release, finished, _ = self.gated_decoder()
        with patched:
            task = asyncio.create_task(self.update())
            try:
                await self.wait_event(entered)
                other = self.folder / 'other'
                other.mkdir()
                self.fixture.control.transition_gates = other
                expected = deepcopy(self.fixture.control.worlds[-1])
                mutations = list(self.mutations)
            finally:
                release.set()
                await task
        self.assertEqual(self.fixture.control.worlds[-1], expected)
        self.assertEqual(self.mutations, mutations)
        self.assertFalse(list(other.iterdir()))
        self.assertFalse(list(self.folder.glob('*.ready')))

    async def test_cancellation_cannot_later_publish_gate_or_mutate_controller(self):
        await self.ready_fall()
        patched, entered, release, finished, _ = self.gated_decoder()
        with patched:
            task = asyncio.create_task(self.update())
            try:
                await self.wait_event(entered)
                expected = deepcopy(self.fixture.control.worlds[-1])
                expected_cache = self.fixture.control._live_decode_cache
                mutations = list(self.mutations)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
                await self.wait_event(finished)
        await asyncio.sleep(0)
        self.assertEqual(self.fixture.control.worlds[-1], expected)
        self.assertIs(self.fixture.control._live_decode_cache, expected_cache)
        self.assertEqual(self.mutations, mutations)
        self.assertFalse(list(self.folder.iterdir()))

    async def test_current_decode_validation_failure_remains_strict(self):
        self.fixture.clock = 1700
        self.fixture.rows.append(self.fixture.command())
        with self.assertRaisesRegex(AssertionError, 'duplicated subject Move'):
            await self.update()
        self.assertEqual(self.fixture.control.worlds[-1]['stage'], 'failed')
        self.assertEqual(self.fixture.relay.changes, [130])

    async def test_repeated_cumulative_prefix_decodes_no_json_again(self):
        self.fixture.clock = 1700
        await self.update()
        with mock.patch.object(verifier.json, 'loads', wraps=json.loads) as loads:
            await self.update()
        self.assertEqual(loads.call_count, 0, 'unchanged cumulative native log was decoded again')

    async def test_appended_pose_is_the_only_json_decoded(self):
        self.fixture.clock = 1700
        await self.update()
        self.fixture.clock = 1800
        self.fixture.rows.append(self.fixture.pose(1800, 2, 452))
        with mock.patch.object(verifier.json, 'loads', wraps=json.loads) as loads:
            await self.update()
        self.assertEqual(loads.call_count, 1, 'previous native records were decoded again')


if __name__ == '__main__':
    unittest.main()
