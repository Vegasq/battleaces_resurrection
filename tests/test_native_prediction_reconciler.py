"""Synchronous authored-world reconciliation; no original native DLL is loaded."""
import copy
import importlib
import unittest

from server.game_data import encode_frame, encode_identity, encode_player_input, decode_frame, decode_identity
from server.protobuf_wire import field_bytes, field_uint, field_float, get_repeated_bytes, get_uint


def delta(value):
    return field_bytes(1, field_uint(1, value))


def move(entity, target):
    return field_bytes(2, field_uint(1, entity) + field_uint(2, target))


def frame(number, local=(), remote=()):
    return encode_frame(number, {slot: encode_player_input(encode_identity(slot + 1, str(slot)), actions)
                                for slot, actions in enumerate((local, remote))})


class Sim:
    def __init__(self):
        self.frame = -1
        self.state = dict(total=[0, 0], positions={1: 0, 2: 6}, targets={1: 0, 2: 6},
                          hp={1: 3, 2: 3}, owner={1: 0, 2: 1}, deaths=[])
        self.query_marker = 0
        self.binding = (101, 7, 0xAAA, 11, 0xBBB, 0xCCC)
        self.saved, self.events = {}, []
        self.next_token = 1
        self.fail_frame = None
        self.capture_fail = False
        self.drop_failures = 0
        self.closed = False

    def root_bindings(self):
        self.events.append(('bindings', self.binding))
        return self.binding

    def query(self):
        self.query_marker += 1
        self.events.append(('query', self.frame, self.query_marker))

    def capture(self, number):
        assert not self.closed and self.frame == number
        self.events.append(('capture', number, self.query_marker))
        if self.capture_fail:
            raise RuntimeError('authored capture failure')
        token = self.next_token
        self.next_token += 1
        self.saved[token] = self.frame, copy.deepcopy(self.state), self.query_marker
        return token

    def restore(self, token):
        self.events.append(('restore', token))
        self.frame, self.state, self.query_marker = copy.deepcopy(self.saved[token])

    def drop(self, token):
        self.events.append(('drop', token))
        if self.drop_failures:
            self.drop_failures -= 1
            raise RuntimeError('authored checkpoint drop failure')
        del self.saved[token]

    def process_frame(self, raw, dt_ms=50):
        number = decode_frame(raw)['frame']
        assert not self.closed and dt_ms == 50 and number == self.frame + 1
        self.events.append(('step', number, raw))
        for player in decode_frame(raw)['players']:
            identity = get_repeated_bytes(player, 1)[0]
            slot = decode_identity(identity)['player_id'] - 1
            for action in get_repeated_bytes(player, 2):
                if values := get_repeated_bytes(action, 1):
                    self.state['total'][slot] += get_uint(values[0], 1)
                if values := get_repeated_bytes(action, 2):
                    entity, target = get_uint(values[0], 1), get_uint(values[0], 2)
                    assert self.state['owner'][entity] == slot
                    self.state['targets'][entity] = target
        for entity, position in tuple(self.state['positions'].items()):
            target = self.state['targets'][entity]
            self.state['positions'][entity] = position + (target > position) - (target < position)
        if len(self.state['positions']) == 2 and len(set(self.state['positions'].values())) == 1:
            for entity in tuple(self.state['hp']):
                self.state['hp'][entity] -= 1
                if self.state['hp'][entity] == 0:
                    self.state['deaths'].append((number, entity))
                    for name in ('positions', 'targets', 'hp', 'owner'):
                        del self.state[name][entity]
        self.frame = number
        if number == self.fail_frame:
            raise RuntimeError('authored partial native step failure')


class NativePredictionReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.api = importlib.import_module('client_patch.prediction_worker.prediction')
        self.sim = Sim()
        self.reconcilers = []

    def create(self, **kwargs):
        result = self.api.Reconciler(self.sim, **kwargs)
        self.reconcilers.append(result)
        return result

    def tearDown(self):
        for owner in self.reconcilers:
            owner.close()
            self.assertTrue(owner.metrics['cleanup_complete'])

    def execute(self, owner, raw):
        chosen = owner.before_next_frame(raw)
        self.sim.process_frame(chosen, 50)
        owner.after_native_frame(chosen)
        self.sim.query()
        return chosen

    def test_local_header_parser_matches_zero_omission_and_rejects_invalid_shape(self):
        self.assertEqual(self.api.frame_number(frame(0)), 0)
        self.assertEqual(self.api.frame_number(frame(99, (delta(1),))), 99)
        self.assertEqual(self.api.frame_number(field_uint(1, 0) + frame(0)), 0)
        bad = [True, b'', b'\0', b'x' * (2 * 1024 * 1024 + 1), frame(0) + field_uint(2, 20),
               field_uint(2, 30) + field_uint(3, 50) + field_float(4, 1),
               field_uint(2, 20) + field_uint(3, 25) + field_float(4, 1),
               field_uint(2, 20) + field_uint(3, 50) + field_float(4, float('nan')),
               frame(0) + field_uint(1, 2**31), frame(0) + field_bytes(5, b''),
               frame(0) + field_bytes(6, b'') * 5]
        for raw in bad:
            with self.subTest(raw=raw[:16] if isinstance(raw, bytes) else raw), self.assertRaises(self.api.PredictionInputError):
                self.api.frame_number(raw)

    def test_capture_occurs_after_previous_ordinary_queries_not_after_step(self):
        owner = self.create()
        self.sim.query()
        self.execute(owner, frame(0))
        self.assertEqual([row for row in self.sim.events if row[0] == 'capture'], [('capture', -1, 1)])
        owner.before_next_frame(frame(1))
        self.assertEqual([row for row in self.sim.events if row[0] == 'capture'][-1], ('capture', 0, 2))
        self.assertEqual(owner.predicted_frame, 0)
        self.assertEqual(len([row for row in self.sim.events if row[0] == 'step']), 1)

    def test_future_authority_loading_queue_is_chosen_instead_of_supplied_guess(self):
        owner = self.create()
        actual = [frame(number, (delta(number + 1),), (delta(2),)) for number in range(6)]
        for raw in actual:
            owner.enqueue_authority(raw)
        self.assertEqual(self.sim.events, [])
        self.assertEqual(owner.pending, tuple(enumerate(actual)))
        for number, raw in enumerate(actual):
            self.assertEqual(self.execute(owner, frame(number, (delta(99),))), raw)
            self.assertEqual(owner.confirmed_frame, number)
        self.assertEqual(self.sim.state['total'], [21, 12])
        self.assertFalse(any(row[0] == 'restore' for row in self.sim.events))

    def test_matching_authority_keeps_needed_base_until_next_quiescent_capture(self):
        owner = self.create()
        owner.enqueue_authority(frame(0, (delta(3),)))
        self.execute(owner, frame(0, (delta(99),)))
        self.assertEqual(owner.confirmed_frame, 0)
        self.assertFalse(any(row[0] == 'drop' for row in self.sim.events))
        owner.before_next_frame(frame(1))
        captured = next(index for index, row in enumerate(self.sim.events) if row[:2] == ('capture', 0))
        dropped = next(index for index, row in enumerate(self.sim.events) if row[0] == 'drop')
        self.assertLess(captured, dropped)
        self.assertEqual(owner.metrics['checkpoints'], 1)

    def test_delayed_local_and_remote_authority_replays_all_twelve_remaining_frames(self):
        owner = self.create()
        owner.enqueue_authority(frame(0))
        self.execute(owner, frame(0))
        guesses = {number: frame(number, (delta(100 if number == 1 else 1),)) for number in range(1, 13)}
        for raw in guesses.values():
            self.execute(owner, raw)
        first = frame(1, (delta(1),), (delta(10),))
        second = frame(2, (delta(2),), (delta(20),))
        before = tuple(self.sim.events)
        owner.enqueue_authority(first)
        owner.enqueue_authority(second)
        self.assertEqual(tuple(self.sim.events), before)
        chosen = owner.before_next_frame(frame(13))
        control = Sim()
        for raw in [frame(0), first, second] + [guesses[number] for number in range(3, 13)]:
            control.process_frame(raw)
        self.assertEqual(self.sim.state, control.state)
        self.assertEqual((self.sim.frame, owner.predicted_frame, owner.confirmed_frame), (12, 12, 2))
        self.assertEqual(chosen, frame(13))
        self.assertEqual((owner.metrics['corrections'], owner.metrics['last_replay_frames']), (1, 12))
        self.assertEqual(owner.metrics['mismatches'], 2)
        self.assertLessEqual(owner.metrics['peak_checkpoints'], 14)
        # Recaptured internal boundaries preserve later rollback, not only H.
        self.sim.process_frame(chosen)
        owner.after_native_frame(chosen)
        self.sim.query()
        owner.enqueue_authority(frame(3, (delta(7),)))
        owner.before_next_frame(frame(14))
        control = Sim()
        for raw in [frame(0), first, second, frame(3, (delta(7),))] + [guesses[number] for number in range(4, 13)] + [chosen]:
            control.process_frame(raw)
        self.assertEqual(self.sim.state, control.state)

    def test_collision_and_death_after_remote_correction_match_fresh_authored_sim(self):
        owner = self.create()
        owner.enqueue_authority(frame(0))
        self.execute(owner, frame(0))
        for number in range(1, 7):
            self.execute(owner, frame(number, (move(1, 3),) if number == 1 else ()))
        self.assertEqual(len(self.sim.state['positions']), 2)
        authority = frame(1, (move(1, 3),), (move(2, 3),))
        owner.enqueue_authority(authority)
        owner.before_next_frame(frame(7))
        control = Sim()
        for raw in [frame(0), authority] + [frame(number) for number in range(2, 7)]:
            control.process_frame(raw)
        self.assertEqual(self.sim.state, control.state)
        self.assertEqual(self.sim.state['positions'], {})
        self.assertEqual(len(self.sim.state['deaths']), 2)

    def test_repeated_identical_orders_retire_distinct_frames(self):
        owner = self.create()
        for number in range(2):
            raw = frame(number, (delta(5),))
            self.execute(owner, raw)
            owner.enqueue_authority(raw)
        owner.before_next_frame(frame(2))
        self.assertEqual((owner.confirmed_frame, self.sim.state['total']), (1, [10, 0]))
        self.assertEqual(owner.metrics['confirmations'], 2)
        self.assertEqual(owner.metrics['corrections'], 0)

    def test_authority_arriving_between_preparation_and_step_waits_for_next_boundary(self):
        owner = self.create()
        guessed = owner.before_next_frame(frame(0, (delta(9),)))
        owner.enqueue_authority(frame(0, (delta(1),)))
        self.assertFalse(any(row[0] == 'restore' for row in self.sim.events))
        self.sim.process_frame(guessed)
        owner.after_native_frame(guessed)
        self.sim.query()
        owner.before_next_frame(frame(1))
        self.assertEqual(self.sim.state['total'], [1, 0])
        self.assertEqual(owner.confirmed_frame, 0)

    def test_changed_fls_binding_refuses_before_restore_and_is_terminal(self):
        owner = self.create()
        self.execute(owner, frame(0, (delta(9),)))
        owner.enqueue_authority(frame(0, (delta(1),)))
        self.sim.binding = (101, 7, 0xDDD, 11, 0xBBB, 0xCCC)
        with self.assertRaises(self.api.PredictionBindingError):
            owner.before_next_frame(frame(1))
        self.assertTrue(owner.failed)
        self.assertFalse(any(row[0] == 'restore' for row in self.sim.events))
        self.assertEqual(self.sim.saved, {})
        self.assertEqual(owner.metrics['corrections'], 0)

    def test_partial_replay_failure_is_terminal_drops_owned_tokens_and_rejects_more_work(self):
        owner = self.create()
        for number in range(3):
            self.execute(owner, frame(number, (delta(9),)))
        owner.enqueue_authority(frame(0, (delta(1),)))
        self.sim.fail_frame = 1
        with self.assertRaises(self.api.PredictionReplayError):
            owner.before_next_frame(frame(3))
        self.assertTrue(owner.failed)
        self.assertEqual(self.sim.saved, {})
        self.assertEqual(owner.metrics['corrections'], 0)
        for call in (lambda: owner.enqueue_authority(frame(1)), lambda: owner.before_next_frame(frame(3)),
                     lambda: owner.after_native_frame(frame(3))):
            with self.assertRaises(self.api.PredictionError):
                call()

    def test_input_shape_and_order_rejections_are_atomic_before_adapter_calls(self):
        owner = self.create()
        owner.enqueue_authority(frame(0))
        before, events = owner.metrics, tuple(self.sim.events)
        for call in (lambda: owner.enqueue_authority(frame(0)), lambda: owner.enqueue_authority(frame(2)),
                     lambda: owner.enqueue_authority(b'\0'), lambda: owner.before_next_frame(frame(1))):
            with self.assertRaises(self.api.PredictionInputError):
                call()
            self.assertEqual(owner.metrics, before)
            self.assertEqual(tuple(self.sim.events), events)
        owner.before_next_frame(frame(0))
        before, events = owner.metrics, tuple(self.sim.events)
        with self.assertRaises(self.api.PredictionInputError):
            owner.before_next_frame(frame(0))
        self.assertEqual(owner.metrics, before)
        self.assertEqual(tuple(self.sim.events), events)

    def test_invalid_already_executed_native_input_is_terminal_until_owned_close(self):
        owner = self.create()
        owner.enqueue_authority(frame(0, (delta(1),)))
        owner.before_next_frame(frame(0, (delta(9),)))
        self.sim.process_frame(frame(0, (delta(9),)))  # Caller violated the chosen-bytes contract.
        with self.assertRaises(self.api.PredictionReplayError):
            owner.after_native_frame(frame(0, (delta(9),)))
        self.assertTrue(owner.failed)
        self.assertTrue(self.sim.saved)  # No adapter work from the non-quiescent record callback.
        owner.close()
        self.assertEqual(self.sim.saved, {})

    def test_ahead_checkpoint_and_queue_budgets_fail_terminal_without_forwarding_next(self):
        owner = self.create(max_ahead=2, max_checkpoints=4)
        self.execute(owner, frame(0))
        self.execute(owner, frame(1))
        with self.assertRaises(self.api.PredictionBudgetError):
            owner.before_next_frame(frame(2))
        self.assertTrue(owner.failed)
        self.assertEqual(self.sim.frame, 1)
        self.assertEqual(self.sim.saved, {})
        self.sim = Sim()
        ring = self.create(max_checkpoints=2)
        self.execute(ring, frame(0))
        self.execute(ring, frame(1))
        with self.assertRaises(self.api.PredictionBudgetError):
            ring.before_next_frame(frame(2))
        self.assertLessEqual(ring.metrics['peak_checkpoints'], 2)
        queue = self.create(max_checkpoints=2)
        queue.enqueue_authority(frame(0))
        queue.enqueue_authority(frame(1))
        before = tuple(self.sim.events)
        with self.assertRaises(self.api.PredictionBudgetError):
            queue.enqueue_authority(frame(2))
        self.assertEqual(tuple(self.sim.events), before)
        self.assertEqual(len(queue.pending), 2)

    def test_journal_byte_budget_does_not_restore_from_control_enqueue(self):
        owner = self.create(max_journal_bytes=2 * len(frame(0)) - 1)
        self.execute(owner, frame(0))
        events = tuple(self.sim.events)
        with self.assertRaises(self.api.PredictionBudgetError):
            owner.enqueue_authority(frame(0))
        self.assertTrue(owner.failed)
        self.assertEqual(tuple(self.sim.events), events)
        owner.close()
        self.assertEqual(self.sim.saved, {})

    def test_prepared_bytes_are_reserved_across_control_enqueue_before_step(self):
        guess, authority = frame(0, (delta(9),)), frame(0, (delta(1),))
        owner = self.create(max_journal_bytes=len(guess) + len(authority) - 1)
        owner.before_next_frame(guess)
        self.assertEqual(owner.metrics['journal_bytes'], len(guess))
        before = tuple(self.sim.events)
        with self.assertRaises(self.api.PredictionBudgetError):
            owner.enqueue_authority(authority)
        self.assertEqual(tuple(self.sim.events), before)
        self.assertEqual(self.sim.frame, -1)
        self.assertEqual(owner.pending, ())

    def test_replay_byte_budget_refuses_before_restore(self):
        owner = self.create(max_journal_bytes=len(frame(0)) + len(frame(1)) + len(frame(0, (delta(1),))))
        self.execute(owner, frame(0))
        self.execute(owner, frame(1))
        owner.enqueue_authority(frame(0, (delta(1),)))
        with self.assertRaises(self.api.PredictionBudgetError):
            owner.before_next_frame(frame(2))
        self.assertFalse(any(row[0] == 'restore' for row in self.sim.events))
        self.assertTrue(owner.failed)
        self.assertEqual(self.sim.saved, {})

    def test_capture_failure_stops_before_next_native_frame_and_releases_old_base(self):
        owner = self.create()
        self.execute(owner, frame(0))
        self.sim.capture_fail = True
        with self.assertRaises(self.api.PredictionReplayError):
            owner.before_next_frame(frame(1))
        self.assertTrue(owner.failed)
        self.assertEqual(self.sim.frame, 0)
        self.assertEqual(self.sim.saved, {})

    def test_cleanup_drop_failure_is_visible_and_retry_is_bounded(self):
        owner = self.create()
        self.execute(owner, frame(0))
        self.sim.drop_failures = 1
        with self.assertRaises(self.api.PredictionCleanupError):
            owner.close()
        self.assertTrue(owner.closed)
        self.assertFalse(owner.metrics['cleanup_complete'])
        owner.close()
        self.assertTrue(owner.metrics['cleanup_complete'])
        self.assertEqual(self.sim.saved, {})

    def test_optional_missing_initial_baseline_cannot_correct_frame_zero(self):
        owner = self.create()
        self.sim.process_frame(frame(0, (delta(9),)))
        owner.after_native_frame(frame(0, (delta(9),)))
        self.sim.query()
        owner.enqueue_authority(frame(0, (delta(1),)))
        with self.assertRaises(self.api.PredictionReplayError):
            owner.before_next_frame(frame(1))
        self.assertFalse(any(row[0] == 'restore' for row in self.sim.events))
        self.assertTrue(owner.failed)

    def test_world_retirement_releases_journal_and_late_messages_cannot_cross_rematch(self):
        owner = self.create()
        self.execute(owner, frame(0))
        owner.close()
        self.assertEqual((owner.pending, owner.metrics['journal_bytes'], self.sim.saved), ((), 0, {}))
        self.sim.closed = True
        for call in (lambda: owner.enqueue_authority(frame(0)), lambda: owner.before_next_frame(frame(1)),
                     lambda: owner.after_native_frame(frame(1))):
            with self.assertRaises(self.api.PredictionError):
                call()
        self.sim = Sim()
        fresh = self.create()
        self.assertEqual(self.execute(fresh, frame(0)), frame(0))

    def test_configuration_and_mutable_root_tokens_reject(self):
        for key, value in (('max_ahead', True), ('max_ahead', 0), ('max_ahead', 13),
                           ('max_journal_bytes', 0), ('max_checkpoints', True), ('max_checkpoints', 17)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.create(**{key: value})
        owner = self.create()
        self.sim.binding = [101, 7, 8]
        with self.assertRaises(self.api.PredictionBindingError):
            owner.before_next_frame(frame(0))
        self.assertFalse(any(row[0] == 'capture' for row in self.sim.events))


if __name__ == '__main__':
    unittest.main()
