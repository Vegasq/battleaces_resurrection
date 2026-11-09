"""Pure reconciliation tests with owned deterministic stand-in worlds; no native launches."""
import asyncio
import importlib
import unittest

from server.game_data import encode_frame, encode_identity, encode_player_input, decode_frame
from server.protobuf_wire import field_bytes, field_uint, field_float, get_repeated_bytes, get_uint
from server.worker_client import FrameResult


def actions(frame, delta=0):
    # Authored additive action interpreted only by the stand-in world below.
    command = [field_bytes(5, field_uint(1, delta))] if delta else []
    return encode_frame(frame, {0: encode_player_input(encode_identity(1, 'Authored'), command), 1: b''})


class World:
    def __init__(self, index):
        self.index, self.frame, self.total = index, -1, 0
        self.closed, self.close_fail = False, False
        self.fail_frame = self.hold_frame = None
        self.extra = 0
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.close_entered, self.close_release = asyncio.Event(), asyncio.Event()
        self.hold_close = False

    async def process_frame(self, data, dt_ms=50):
        frame = decode_frame(data)['frame']
        assert not self.closed and frame == self.frame + 1 and dt_ms == 50
        if frame == self.hold_frame:
            self.entered.set(); await self.release.wait()
        if frame == self.fail_frame: raise RuntimeError('authored step failure')
        for player in decode_frame(data)['players']:
            for action in get_repeated_bytes(player, 2):
                self.total += get_uint(get_repeated_bytes(action, 5)[0], 1)
        self.total += self.extra
        self.frame = frame
        return FrameResult(frame, frame // 20,
                           dict(frame=frame, total=self.total, raw_sha256='view-' + str(self.index)))

    async def close(self):
        self.close_entered.set()
        try:
            if self.hold_close: await self.close_release.wait()
            if self.close_fail: raise RuntimeError('authored close failure')
        finally:
            self.closed = True


class Factory:
    def __init__(self):
        self.worlds, self.bootstraps = [], []
        self.configure = lambda world: None

    async def __call__(self, bootstrap):
        world = World(len(self.worlds))
        self.configure(world)
        self.worlds.append(world); self.bootstraps.append(bootstrap)
        return world


class MovementPredictionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = importlib.import_module('client_patch.transport.prediction')
        self.factory = Factory()
        self.controllers = []

    async def asyncTearDown(self):
        for controller in self.controllers:
            try: await controller.close()
            except self.api.PredictionError: pass

    async def create(self, **kwargs):
        controller = await self.api.PredictionController.create(b'authored bootstrap', self.factory, **kwargs)
        self.controllers.append(controller)
        return controller

    async def test_predict_applies_immediately_and_matching_authority_does_not_rebuild(self):
        controller = await self.create()
        result = await controller.predict(actions(0, 3))
        self.assertEqual((result.frame, result.state['total'], controller.confirmed_frame), (0, 3, -1))
        self.assertEqual(controller.predicted_frame, 0)
        outcome = await controller.confirm(actions(0, 3))
        self.assertEqual((outcome.frame, outcome.status, outcome.replayed_frames), (0, 'matched', 0))
        self.assertEqual(len(self.factory.worlds), 1)
        self.assertEqual(controller.confirmed_inputs, (actions(0, 3),))
        self.assertEqual(controller.speculative_inputs, ())

    async def test_mismatch_rebuilds_bootstrap_and_replays_trailing_predictions_atomically(self):
        controller = await self.create()
        for frame, delta in enumerate((100, 2, 3)): await controller.predict(actions(frame, delta))
        old = controller.world
        outcome = await controller.confirm(actions(0, 1))
        self.assertEqual((outcome.status, outcome.replayed_frames), ('corrected', 3))
        self.assertIsNot(controller.world, old); self.assertTrue(old.closed)
        self.assertEqual((controller.world.frame, controller.world.total), (2, 6))
        self.assertEqual(self.factory.bootstraps, [b'authored bootstrap'] * 2)
        self.assertEqual(controller.confirmed_inputs, (actions(0, 1),))
        self.assertEqual(controller.speculative_inputs, (actions(1, 2), actions(2, 3)))
        self.assertEqual((controller.metrics['mismatches'], controller.metrics['corrections']), (1, 1))

    async def test_confirmed_prefix_and_corrected_continuation_match_fresh_replay(self):
        controller = await self.create()
        for frame, delta in enumerate((1, 2)): await controller.confirm(actions(frame, delta))
        await controller.predict(actions(2, 99)); await controller.predict(actions(3, 4))
        await controller.confirm(actions(2, 3))
        self.assertEqual(controller.world.total, 10)
        await controller.confirm(actions(3, 4))
        await controller.predict(actions(4, 5)); await controller.confirm(actions(4, 5))
        self.assertEqual(controller.world.total, 15)
        self.assertEqual(controller.confirmed_inputs, tuple(actions(i, i+1) for i in range(5)))
        self.assertEqual(len(self.factory.worlds), 2)

    async def test_stale_gap_and_duplicate_input_reject_without_mutation_or_terminal_failure(self):
        controller = await self.create()
        await controller.predict(actions(0, 1))
        for operation, data in ((controller.predict, actions(0)), (controller.predict, actions(2)),
                                (controller.confirm, actions(1))):
            with self.assertRaises(self.api.PredictionInputError): await operation(data)
        await controller.confirm(actions(0, 1))
        with self.assertRaises(self.api.PredictionInputError): await controller.confirm(actions(0, 1))
        self.assertFalse(controller.failed); self.assertEqual(controller.world.total, 1)

    async def test_header_frame_timing_types_duplicates_and_size_are_validated_before_step(self):
        controller = await self.create()
        bad = [b'', True, b'\x00', actions(0) + field_uint(2, 20),
               field_uint(2, 30) + field_uint(3, 50) + field_float(4, 1),
               field_uint(2, 20) + field_uint(3, 25) + field_float(4, 1),
               field_uint(2, 20) + field_uint(3, 50) + field_float(4, float('nan')),
               field_uint(1, 2**31) + actions(0), b'x' * (2*1024*1024+1)]
        for data in bad:
            with self.subTest(size=len(data) if isinstance(data, bytes) else data), self.assertRaises(self.api.PredictionInputError):
                await controller.predict(data)
        self.assertEqual(controller.world.frame, -1); self.assertFalse(controller.failed)

    async def test_prediction_ahead_limit_recovers_after_confirmation(self):
        controller = await self.create(max_ahead=2)
        await controller.predict(actions(0)); await controller.predict(actions(1))
        with self.assertRaises(self.api.PredictionLimitError): await controller.predict(actions(2))
        await controller.confirm(actions(0)); await controller.predict(actions(2))
        self.assertEqual(controller.predicted_frame, 2); self.assertFalse(controller.failed)

    async def test_replay_budget_failure_is_terminal_and_retains_pending_authority(self):
        controller = await self.create(max_replay_frames=2)
        for frame in range(3): await controller.predict(actions(frame, 10))
        with self.assertRaises(self.api.PredictionBudgetError): await controller.confirm(actions(0, 1))
        self.assertTrue(controller.failed); self.assertTrue(self.factory.worlds[0].closed)
        self.assertEqual(controller.pending_authoritative, actions(0, 1))
        with self.assertRaises(self.api.PredictionError): _ = controller.world

    async def test_replay_step_failure_never_replaces_world_and_closes_both_owned_worlds(self):
        controller = await self.create()
        for frame in range(3): await controller.predict(actions(frame, 10))
        self.factory.configure = lambda world: setattr(world, 'fail_frame', 1)
        with self.assertRaises(self.api.PredictionError): await controller.confirm(actions(0, 1))
        self.assertTrue(controller.failed); self.assertTrue(all(world.closed for world in self.factory.worlds))
        self.assertEqual(controller.metrics['corrections'], 0)
        with self.assertRaises(self.api.PredictionError): await controller.predict(actions(3))

    async def test_confirmed_prefix_replay_divergence_is_terminal(self):
        controller = await self.create()
        await controller.confirm(actions(0, 1)); await controller.predict(actions(1, 9))
        self.factory.configure = lambda world: setattr(world, 'extra', 1)
        with self.assertRaises(self.api.PredictionReplayError): await controller.confirm(actions(1, 2))
        self.assertTrue(controller.failed); self.assertTrue(all(world.closed for world in self.factory.worlds))

    async def test_close_failure_after_rebuild_stops_controller_and_closes_replacement(self):
        controller = await self.create()
        await controller.predict(actions(0, 9)); self.factory.worlds[0].close_fail = True
        with self.assertRaises(self.api.PredictionCleanupError): await controller.confirm(actions(0, 1))
        self.assertTrue(controller.failed); self.assertTrue(self.factory.worlds[1].closed)
        self.assertGreaterEqual(controller.metrics['cleanup_failures'], 1)

    async def test_cancellation_during_replay_is_terminal_with_owned_cleanup(self):
        controller = await self.create(cleanup_timeout=.1)
        await controller.predict(actions(0, 9))
        self.factory.configure = lambda world: setattr(world, 'hold_frame', 0)
        correction = asyncio.create_task(controller.confirm(actions(0, 1)))
        while len(self.factory.worlds) < 2: await asyncio.sleep(0)
        await self.factory.worlds[1].entered.wait()
        correction.cancel()
        with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(correction, .5)
        self.assertTrue(controller.failed); self.assertTrue(all(world.closed for world in self.factory.worlds))

    async def test_cancelling_close_does_not_abandon_its_owned_cleanup(self):
        controller = await self.create(cleanup_timeout=.2)
        world = controller.world; world.hold_close = True
        closing = asyncio.create_task(controller.close()); await world.close_entered.wait()
        closing.cancel(); await asyncio.sleep(.01); self.assertFalse(closing.done())
        world.close_release.set()
        with self.assertRaises(asyncio.CancelledError): await closing
        self.assertTrue(world.closed); self.assertTrue(controller.closed)

    async def test_close_timeout_is_bounded_and_reported(self):
        controller = await self.create(cleanup_timeout=.01)
        controller.world.hold_close = True
        with self.assertRaises(self.api.PredictionCleanupError): await asyncio.wait_for(controller.close(), .3)
        self.assertTrue(controller.closed)

    async def test_constructor_bounds_reject_booleans_and_invalid_limits(self):
        for name, value in (('max_ahead', True), ('max_ahead', 0), ('max_replay_frames', False),
                            ('max_replay_frames', 0), ('cleanup_timeout', True), ('cleanup_timeout', 0),
                            ('operation_timeout', 0), ('max_history_bytes', 0)):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError): await self.create(**{name: value})
