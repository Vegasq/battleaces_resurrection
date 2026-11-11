"""Queued movement must not skip an omitted command on the same unit.

Authored ledger tests only; native queue execution is qualified separately.
"""
import unittest

from client_patch.prediction_worker.commands import CommandLedger
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint
from tests.test_prediction_command_ledger import body, forecast_actions, join
from tools.verify_movement_prediction import position_message


def ground(ability=12, ids=(11,), *, queued=False, unit_type=1):
    group = field_uint(1, unit_type) + field_uint(2, ability) + field_packed_uint(3, ids)
    target = field_bytes(3, field_bytes(1, position_message((-70., 0., -50.))))
    execute = field_bytes(1, group) + (field_uint(2, 1) if queued else b'') + field_bytes(3, target)
    return field_bytes(1, execute)


class QueuedDependencyTests(unittest.TestCase):
    def ready(self):
        ledger = CommandLedger(0)
        ledger.register(1, body([join()]), 0)
        ledger.observe_authority(0, body([join(deck=b'authoritative-frozen-deck')], name='canonical identity'))
        return ledger

    def test_standalone_queued_move_keeps_exact_original_bytes(self):
        ledger = self.ready()
        move = ground(queued=True)
        registration = ledger.register(2, body([move]), 3)
        self.assertEqual(registration.send_body, body([move]))
        self.assertEqual(forecast_actions(ledger.forecast(3)), (move,))

    def test_queued_move_waits_for_omitted_predecessor_on_same_unit(self):
        ledger = self.ready()
        prior, move = ground(88), ground(queued=True)
        first = ledger.register(2, body([prior]), 3)
        second = ledger.register(3, body([move]), 4)
        self.assertEqual(forecast_actions(ledger.forecast(4)), ())
        self.assertEqual([item.ordinal for item in ledger.pending], [(2, 0), (3, 0)])
        self.assertEqual((first.send_body, second.send_body), (body([prior]), body([move])))

    def test_same_batch_retains_dependency_order(self):
        ledger = self.ready()
        prior, move = ground(88), ground(queued=True)
        ledger.register(2, body([prior, move]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), ())
        receipt = ledger.observe_authority(1, body([prior, move], name='canonical identity'))
        self.assertEqual([item.ordinal for item in receipt.retired], [(2, 0), (2, 1)])
        self.assertFalse(ledger.pending)

    def test_confirmation_releases_dependency_without_changing_pending_ordinal(self):
        ledger = self.ready()
        prior, move = ground(88), ground(queued=True)
        ledger.register(2, body([prior]), 3)
        ledger.register(3, body([move]), 4)
        self.assertEqual(forecast_actions(ledger.revision_plan(1, 4)[4]), ())
        ledger.observe_authority(1, body([prior], name='canonical identity'))
        self.assertEqual([item.ordinal for item in ledger.pending], [(3, 0)])
        self.assertEqual(forecast_actions(ledger.forecast(4)), (move,))
        ledger.observe_authority(2, body([move], name='canonical identity'))
        self.assertEqual(forecast_actions(ledger.forecast(4)), ())

    def test_unrelated_unit_command_does_not_delay_queued_move(self):
        ledger = self.ready()
        move = ground(queued=True)
        ledger.register(2, body([ground(88, (12,)), move]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (move,))

    def test_immediate_move_still_predicts_after_nonpredictive_predecessor(self):
        ledger = self.ready()
        move = ground()
        ledger.register(2, body([ground(88), move]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (move,))

    def test_queued_move_after_predicted_move_preserves_fifo(self):
        ledger = self.ready()
        first, second = ground(), ground(queued=True)
        ledger.register(2, body([first, second]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (first, second))

    def test_later_nonpredictive_order_does_not_block_earlier_queued_move(self):
        ledger = self.ready()
        move = ground(queued=True)
        ledger.register(2, body([move, ground(88)]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (move,))

    def test_skipped_shared_order_propagates_dependency_to_every_member(self):
        ledger = self.ready()
        shared = ground(ids=(11, 12), queued=True)
        follow = ground(ids=(12,), queued=True)
        ledger.register(2, body([ground(88), shared, follow]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), ())

    def test_immediate_replacement_clears_only_its_units_dependency(self):
        ledger = self.ready()
        replacement = ground(ids=(11,))
        available = ground(ids=(11,), queued=True)
        blocked = ground(ids=(12,), queued=True)
        ledger.register(2, body([ground(88, (11, 12)), replacement, available, blocked]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (replacement, available))

    def test_later_omitted_command_establishes_new_dependency(self):
        ledger = self.ready()
        replacement = ground()
        ledger.register(2, body([ground(88), replacement, ground(88), ground(queued=True)]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (replacement,))

    def test_nonpredictive_ui_and_empty_execute_do_not_create_unit_dependency(self):
        ledger = self.ready()
        ui = field_bytes(5, field_bytes(1, b''))
        move = ground(queued=True)
        registration = ledger.register(2, body([ui, ground(88, ()), move]), 3)
        self.assertEqual(registration.locally_elided_noops, 1)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (move,))

    def test_future_immediate_order_cannot_release_an_earlier_dependency(self):
        ledger = self.ready()
        prior, queued, replacement = ground(88), ground(queued=True), ground()
        ledger.register(2, body([prior]), 3)
        ledger.register(3, body([queued]), 4)
        ledger.register(4, body([replacement]), 5)
        self.assertEqual(forecast_actions(ledger.forecast(4)), ())
        self.assertEqual(forecast_actions(ledger.forecast(5)), (replacement,))
        self.assertEqual(forecast_actions(ledger.forecast(4)), ())

    def test_omitted_mixed_ability_action_blocks_every_nonempty_group(self):
        ledger = self.ready()
        groups = b''.join(field_bytes(1, field_uint(1, 1) + field_uint(2, ability) +
                         field_packed_uint(3, (identity,))) for identity, ability in ((11, 12), (12, 88)))
        target = field_bytes(3, field_bytes(1, position_message((-70., 0., -50.))))
        mixed = field_bytes(1, groups + field_bytes(3, target))
        ledger.register(2, body([mixed, ground(ids=(11,), queued=True)]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), ())

    def test_immediate_replacement_partially_clears_a_propagated_dependency(self):
        ledger = self.ready()
        replacement, released = ground(), ground(queued=True)
        ledger.register(2, body([ground(88), ground(ids=(11, 12), queued=True),
            replacement, released, ground(ids=(12,), queued=True)]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (replacement, released))

    def test_immediate_hold_clears_its_predecessor_dependency(self):
        ledger = self.ready()
        group = field_uint(1, 1) + field_uint(2, 14) + field_packed_uint(3, (11,))
        hold = field_bytes(1, field_bytes(1, group) + field_bytes(3, field_bytes(1, b'')))
        move = ground(queued=True)
        ledger.register(2, body([ground(88), hold, move]), 3)
        self.assertEqual(forecast_actions(ledger.forecast(3)), (hold, move))

    def test_worker_replays_predecessor_before_releasing_queued_forecast(self):
        # Actual NativeSession dispatch/replay coordination with authored native
        # API responses. This is distinct from the original-DLL control.
        from tests.test_prediction_worker_ledger_integration import IntegrationTests
        worker = IntegrationTests(methodName='runTest')
        self.addCleanup(worker.doCleanups)
        worker.ready()
        prior = ground(88, (42,), unit_type=75)
        move = ground(ids=(42,), queued=True, unit_type=75)
        worker.batch(2, [prior]); worker.batch(3, [move])
        worker.process(1); worker.step(); worker.query()
        self.assertEqual(forecast_actions(worker.raw.inputs[-1]), ())
        native_calls = len(worker.raw.calls)
        worker.authority(1, [prior])
        self.assertEqual(len(worker.raw.calls), native_calls)
        worker.process(2); worker.step(); worker.query()
        self.assertEqual(forecast_actions(worker.raw.inputs[-2]), (prior,))
        self.assertEqual(forecast_actions(worker.raw.inputs[-1]), (move,))
        self.assertEqual([item.ordinal for item in worker.s.command_ledgers[worker.key].pending], [(3, 0)])
        self.assertGreater(worker.s.predictions[worker.key].metrics['corrections'], 0)
        worker.authority(2, [move])
        worker.process(3); worker.step(); worker.query()
        self.assertFalse(worker.s.command_ledgers[worker.key].pending)


if __name__ == '__main__':
    unittest.main()
