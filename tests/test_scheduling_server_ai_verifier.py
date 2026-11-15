"""Offline corruption controls for the real scheduling/server-AI verifier."""
import argparse
import copy
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from client_patch.transport import bridge
from server import protocol as p, public_protocol as q
from server.game_data import encode_frame, encode_identity, encode_player_input
from server.protobuf_wire import field_bytes, field_uint
from tests.synthetic import template
from tools.verify_scheduling_server_ai import (PublicBridge, ai_conservation, classify_worker_cleanup, diagnostic_arguments,
    digest, human_conservation, human_search_deadline, read_journal, solo_startup, validate_options)
from tools.verify_public_clients import journal_builds

MATCH = '0123456789abcdef0123456789abcdef'


def fixture():
    identities = [encode_identity(slot+1, 'Fixture '+str(slot)) for slot in (0, 1)]
    joins = [field_bytes(3, field_uint(1, slot)) for slot in (0, 1)]
    move = field_bytes(5, field_bytes(1, b''))
    human, bots, events, log = {}, {}, [], []
    journal = [dict(frame=frame, players={0:(joins[0],) if frame == 0 else (move,) if frame == 1 else (),
                                         1:(joins[1],) if frame == 0 else (move,) if frame == 2 else ()}) for frame in range(3)]
    for frame in journal:
        bots[(MATCH, frame['frame'], 1)] = encode_player_input(identities[1], frame['players'][1])
        if not frame['players'][0]: continue
        sequence = frame['frame']+1
        body = encode_player_input(identities[0], frame['players'][0]); human[(MATCH, 0, sequence)] = body
        common = dict(match=MATCH, slot=0, sequence=sequence, body_sha256=digest(body), action_count=1)
        events += [dict(common, event='command_batch_accepted', earliest_frame=frame['frame']),
                   dict(common, event='command_batch_committed', frame=frame['frame'])]
        log.append(f'Original command batch submitted: match={MATCH} sequence={sequence} actions=1 bytes={len(body)} body_sha256={digest(body)}')
    return journal, events, human, bots, '\n'.join(log)


class ConservationTests(unittest.TestCase):
    def setUp(self): self.journal, self.events, self.human, self.bots, self.log = fixture()

    def check(self):
        return human_conservation(MATCH, self.journal, self.events, self.human, self.human, self.log, 3)

    def test_human_and_native_ai_are_separately_bound_to_same_journal(self):
        self.assertTrue(self.check()['native_socket_bytes_match'])
        self.assertEqual(ai_conservation(MATCH, self.journal, self.bots)['non_startup_actions'], 1)

    def test_human_command_mutation_and_duplicate_commit_fail(self):
        self.journal[1]['players'][0] = ()
        with self.assertRaisesRegex(AssertionError, 'canonical command'): self.check()
        self.journal, self.events, self.human, self.bots, self.log = fixture()
        self.events.append(copy.deepcopy(self.events[-1]))
        with self.assertRaisesRegex(AssertionError, 'committed twice'): self.check()

    def test_missing_prefix_commit_is_not_hidden_by_empty_journal(self):
        self.events.pop(); self.journal[1]['players'][0] = ()
        with self.assertRaisesRegex(AssertionError, 'lost'): self.check()

    def test_native_submission_hash_is_independent_of_authority(self):
        self.log = self.log.replace(digest(self.human[(MATCH, 0, 2)]), '0'*64)
        with self.assertRaisesRegex(AssertionError, 'actual socket'): self.check()

    def test_ai_action_mutation_or_idle_only_producer_fail(self):
        self.journal[2]['players'][1] = ()
        with self.assertRaisesRegex(AssertionError, 'AI commands'): ai_conservation(MATCH, self.journal, self.bots)
        self.bots[(MATCH, 2, 1)] = encode_player_input(encode_identity(2, 'Fixture 1'), ())
        with self.assertRaisesRegex(AssertionError, 'no non-startup'): ai_conservation(MATCH, self.journal, self.bots)

    def test_earliest_frame_mutation_fails_even_if_content_is_preserved(self):
        self.events[2]['earliest_frame'] = 0
        with self.assertRaisesRegex(AssertionError, 'next legal seal'): self.check()


class PublicWireTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_assignment_and_frame_bind_exact_public_payload(self):
        evidence = []; observed = PublicBridge(None, None, None, version=2, evidence=evidence)
        assignment = q.assignment(1, MATCH, 1, 0, 1, 6, template().default_decks[0])
        payload = q.frame(0, {slot:encode_player_input(encode_identity(slot+1, 'Fixture '+str(slot)), ()) for slot in (0, 1)})
        stream = p.encode(q.MATCH, assignment)+p.encode(q.FRAME, payload)
        with mock.patch.object(bridge.Bridge, 'send', new=mock.AsyncMock()):
            for offset in range(0, len(stream), 3): await observed.send(bridge.DATA, 1, stream[offset:offset+3])
        self.assertEqual(evidence, [dict(match=MATCH, frame=0, payload_sha256=digest(payload))])

    async def test_human_pair_assignment_and_unassigned_frame_are_rejected(self):
        with mock.patch.object(bridge.Bridge, 'send', new=mock.AsyncMock()):
            observed = PublicBridge(None, None, None, version=2, evidence=[])
            assignment = q.assignment(1, MATCH, 1, 0, 3, 6, template().default_decks[0])
            with self.assertRaisesRegex(AssertionError, 'one human'):
                await observed.send(bridge.DATA, 1, p.encode(q.MATCH, assignment))
            observed = PublicBridge(None, None, None, version=2, evidence=[])
            with self.assertRaisesRegex(AssertionError, 'precedes assignment'):
                await observed.send(bridge.DATA, 1, p.encode(q.FRAME, struct.pack('<I', 0)))


class ScopeAndBarrierTests(unittest.TestCase):
    def options(self):
        return argparse.Namespace(scheduling='arrival', frames=600, timeout=180, rtt_ms=475, expected_helper_sha256='a'*64)

    def test_nonfinite_or_unbounded_delay_refused(self):
        validate_options(self.options())
        for value in (float('nan'), float('inf'), -1, 501, True):
            args = self.options(); args.rtt_ms = value
            with self.subTest(value=value), self.assertRaises(AssertionError): validate_options(args)

    def test_flags_exercise_ordinary_public_lifecycle_without_prediction(self):
        flags = diagnostic_arguments(600)
        self.assertIn('-public-queue-smoke-mode=1', flags)
        self.assertIn('-dedicated-surrender-frame=670', flags)
        self.assertFalse(any('prediction' in flag for flag in flags))

    def test_team_modes_have_explicit_prefix_scope_without_false_concede_result(self):
        for mode in (2, 5):
            flags = diagnostic_arguments(600, mode)
            self.assertIn('-public-queue-smoke-mode='+str(mode), flags)
            self.assertNotIn('-dedicated-surrender-smoke', flags)

    def test_four_player_journal_requires_each_human_and_ai_identity(self):
        inputs = {slot:encode_player_input(encode_identity(slot+1, 'Slot '+str(slot)),
                                          (field_bytes(3, field_uint(1, slot)),)) for slot in range(4)}
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder); target = output/'matches'/MATCH; target.mkdir(parents=True)
            raw = encode_frame(0, inputs)
            (target/'frames.bin').write_bytes(struct.pack('<I', len(raw))+raw)
            self.assertEqual(set(read_journal(output, MATCH, 1, 4)[0]['players']), set(range(4)))
            with self.assertRaisesRegex(AssertionError, 'invalid journal player'):
                read_journal(output, MATCH, 1, 2)

    def barrier(self):
        common = dict(match=MATCH)
        return [dict(common, event='probe_command_frame_sealed', frame=0, observed_perf_counter=1.0),
                dict(common, event='command_startup_waiting', frame=0, ready_slots=[0], observed_at=1.1),
                dict(common, event='command_startup_ready', frame=0, slot=0, ready_count=1, all_ready=True, observed_at=1.3),
                dict(common, event='command_startup_released', frame=1, ready_slots=[0], observed_at=1.3, rebased_at=10.0, next_tick=10.05, wait_ms=200),
                dict(common, event='probe_command_frame_sealed', frame=1, observed_perf_counter=10.05)]

    def test_human_readiness_is_required_but_ai_ack_is_forbidden(self):
        events = self.barrier(); self.assertEqual(solo_startup(MATCH, events)['human_ready_slots'], [0])
        events[1]['ready_slots'] = [0, 1]
        with self.assertRaisesRegex(AssertionError, 'AI must not'): solo_startup(MATCH, events)

    def test_early_frame1_seal_fails(self):
        events = self.barrier(); events[-1]['observed_perf_counter'] = 10.049
        with self.assertRaisesRegex(AssertionError, 'frame1 sealed'): solo_startup(MATCH, events)


class SearchDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.events = [dict(event='public_queue_entered', profile='human', ticket=1, mode=1, wait_ms=27468,
                            observed_at=103.400, queue_started_at=100.344, queue_deadline=130.344),
                       dict(event='public_match_offered', match=MATCH, mode=1, humans=['human'], tickets=[1],
                            fallback=True, observed_at=130.344, queue_decision_at=130.344, probe_tick_ms=130344)]
        self.log = ('[100000] Native search began: ticket=1 mode=1 nativeStatus=5\n'
                    '[100000] PUBLIC QUEUE SMOKE original OnMapSelected: mode=1 visible=1\n')

    def check(self): return human_search_deadline(MATCH, self.events, self.log, 1)

    def test_delayed_profile_save_audit_does_not_shorten_actual_deadline(self):
        result = self.check()
        self.assertGreater(result['queue_audit_delay_ms'], 500)
        self.assertLess(result['audit_to_audit_seconds'], 27.468)
        self.assertEqual(result['native_search_to_offer_ms'], 30344)
        self.assertEqual(result['server_deadline_lateness_ms'], 0)

    def test_early_offer_rejected_despite_delayed_audit_and_normal_native_elapsed(self):
        self.events[1]['queue_decision_at'] -= .001
        with self.assertRaisesRegex(AssertionError, 'preceded actual'): self.check()

    def test_shortened_native_or_server_search_rejected(self):
        self.events[1]['probe_tick_ms'] = 129999
        with self.assertRaisesRegex(AssertionError, 'thirty seconds'): self.check()
        self.events[1]['probe_tick_ms'] = 130344
        self.events[0]['queue_started_at'] += .001
        with self.assertRaisesRegex(AssertionError, 'duration differs'): self.check()

    def test_missing_native_start_or_mismatched_ticket_rejected(self):
        self.log = self.log.replace('Native search began:', 'missing:')
        with self.assertRaisesRegex(AssertionError, 'start/callback'): self.check()
        self.events[1]['tickets'] = [2]
        with self.assertRaisesRegex(AssertionError, 'identity'): self.check()


class WorkerCleanupTests(unittest.TestCase):
    def setUp(self):
        self.worker = mock.Mock(pid=123, failure='CancelledError: ', closed=True, stderr_tail='')
        self.worker.process.poll.return_value = 1
        self.worker._cleanup_task.done.return_value = True
        self.worker._cleanup_task.cancelled.return_value = False
        self.worker._cleanup_task.exception.return_value = None
        self.worker._stderr_thread.is_alive.return_value = False
        self.events = [dict(event='worker_started', match=MATCH, worker_pid=123),
                       dict(event='probe_owned_team_prefix_teardown', match=MATCH, healthy_worker_pids=[123]),
                       dict(event='match_aborted', match=MATCH, reason='public player disconnected'),
                       dict(event='worker_released', match=MATCH, worker_pid=123)]

    def check(self, complete_match=False):
        return classify_worker_cleanup(self.worker, self.events, complete_match=complete_match)

    def test_owned_incomplete_team_cancellation_is_explicit_and_reaped(self):
        result = self.check()
        self.assertTrue(result['passed'])
        self.assertTrue(result['expected_cancelled_request'])
        self.assertTrue(result['owned_resources_reaped'])

    def test_completed_game_cancellation_and_unexpected_failure_are_rejected(self):
        self.assertFalse(self.check(complete_match=True)['passed'])
        self.worker.failure = 'WorkerError: broken simulation'
        self.assertFalse(self.check()['passed'])
        self.worker.failure = None
        self.assertFalse(self.check()['passed'])
        self.worker.process.poll.return_value = 0
        self.assertTrue(self.check(complete_match=True)['passed'])

    def test_cancellation_before_owned_stop_or_after_completion_is_rejected(self):
        self.events[1]['healthy_worker_pids'] = []
        self.assertFalse(self.check()['passed'])
        self.events[1]['healthy_worker_pids'] = [123]
        self.events[1], self.events[2] = self.events[2], self.events[1]
        self.assertFalse(self.check()['passed'])
        self.events[1], self.events[2] = self.events[2], self.events[1]
        self.events.append(dict(event='match_completed', match=MATCH))
        self.assertFalse(self.check()['passed'])

    def test_live_process_thread_or_unfinished_failed_cleanup_task_is_rejected(self):
        self.worker.process.poll.return_value = None
        self.assertFalse(self.check()['passed'])
        self.worker.process.poll.return_value = 1
        self.worker._stderr_thread.is_alive.return_value = True
        self.assertFalse(self.check()['passed'])
        self.worker._stderr_thread.is_alive.return_value = False
        self.worker._cleanup_task.done.return_value = False
        self.assertFalse(self.check()['passed'])
        self.worker._cleanup_task.done.return_value = True
        self.worker._cleanup_task.exception.return_value = RuntimeError('cleanup failed')
        self.assertFalse(self.check()['passed'])

    def test_release_must_belong_to_exact_owned_worker_and_match(self):
        self.events[-1]['worker_pid'] = 124
        self.assertFalse(self.check()['passed'])
        self.events[-1]['worker_pid'] = 123
        self.events[-1]['match'] = 'f'*32
        self.assertFalse(self.check()['passed'])
        self.events[-1]['match'] = MATCH
        self.events[2]['reason'] = 'native simulation failed'
        self.assertFalse(self.check()['passed'])


class PublicHumanBuildTests(unittest.TestCase):
    def journal(self, directory, duplicate=False):
        path = Path(directory)/'frames.bin'
        action = field_bytes(1, field_bytes(1, field_uint(2, 34)))
        with path.open('wb') as stream:
            for frame in range(4):
                inputs = {slot:encode_player_input(encode_identity(slot+1, 'Human '+str(slot)),
                         [action] if slot == 0 and (frame == 2 or duplicate and frame == 3) else []) for slot in (0, 1)}
                raw = encode_frame(frame, inputs); stream.write(struct.pack('<I', len(raw))+raw)
        clients = [dict(seat=0, name='Human 0', build_frame=1,
                        native_build='LAN NORMAL BUILD smoke frame1 slot0 army0 ability34 queued=1 commandQueueDelta=1')]
        return path, clients

    def test_arrival_build_is_bound_to_actual_server_frame_not_local_queue_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            path, clients = self.journal(directory)
            self.assertEqual(journal_builds(path, clients, 4, scheduling='arrival')[0]['frame'], 2)
            with self.assertRaisesRegex(AssertionError, 'human .*absent'):
                journal_builds(path, clients, 4, scheduling='buffered')

    def test_duplicate_or_wrong_ability_does_not_count_as_human_command_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path, clients = self.journal(directory, duplicate=True)
            with self.assertRaisesRegex(AssertionError, 'duplicated'):
                journal_builds(path, clients, 4, scheduling='arrival')
            path, clients = self.journal(directory)
            clients[0]['native_build'] = clients[0]['native_build'].replace('ability34', 'ability35')
            with self.assertRaisesRegex(AssertionError, 'coverage incomplete'):
                journal_builds(path, clients, 4, scheduling='arrival')


if __name__ == '__main__': unittest.main()
