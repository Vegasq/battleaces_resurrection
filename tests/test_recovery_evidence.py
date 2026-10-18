import argparse
from pathlib import Path
import shutil
import unittest
import uuid

from tools.run_secure_match import current_native_log, native_result_ready, read_native_log, recovery_evidence, scenario_expectations


class NativeResultEvidenceTests(unittest.TestCase):
    START = 'Offline initial state reached after game initialization. PID=123\n'
    READY = '[100] Dedicated postgame gates 3/24: match=final gate=continue-handler-ready sessions=2'

    def test_actual_result_required_after_server_completion(self):
        self.assertFalse(native_result_ready(self.START + 'Dedicated match ended: final', 'final'))
        waiting = self.READY.replace('continue-handler-ready', 'world-not-idle')
        self.assertFalse(native_result_ready(self.START + waiting, 'final'))
        self.assertTrue(native_result_ready(self.START + waiting + '\n' + self.READY, 'final'))

    def test_other_match_and_stale_process_evidence_rejected(self):
        log = self.START + self.READY
        for match in ('other', 'fin', '', None):
            with self.subTest(match=match):
                self.assertFalse(native_result_ready(log, match))
        self.assertFalse(native_result_ready(log + '\n' + self.START, 'final'))
        self.assertFalse(native_result_ready(self.READY, 'final'))
        self.assertFalse(native_result_ready(log.replace('ready sessions', 'ready-wait sessions'), 'final'))


class NativeLogEncodingTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(__file__).resolve().parents[1]/'local/test-native-log'
        self.game = self.base/uuid.uuid4().hex
        self.game.mkdir(parents=True)

    def tearDown(self):
        target = self.game.resolve()
        self.assertEqual(target.parent, self.base.resolve())
        self.assertEqual(len(target.name), 32)
        shutil.rmtree(target)

    def test_utf8_names_and_partial_writes_do_not_corrupt_evidence(self):
        path = self.game/'investigation/runtime/dedicated-native-123.log'
        path.parent.mkdir(parents=True)
        start = '[201] Offline initial state reached after game initialization. PID=123\n'
        name = 'Public bot name=Fixture\u25cfBot\u2468\n'
        encoded = name.encode('utf-8')
        partial = encoded[:encoded.index(b'\xe2') + 2]
        path.write_bytes(start.encode('utf-8') + partial)
        self.assertEqual(read_native_log(self.game,123,since_tick=200), start.split('] ',1)[1])
        path.write_bytes((start + name).encode('utf-8'))
        self.assertEqual(read_native_log(self.game,123,since_tick=200), start.split('] ',1)[1] + name)
        self.assertEqual(read_native_log(self.game,123,since_tick=202), '')
        path.write_bytes(start.encode('utf-8') + b'invalid=\xff\n')
        with self.assertRaises(UnicodeDecodeError):
            read_native_log(self.game,123,since_tick=200)


class RecoveryEvidenceTests(unittest.TestCase):
    def trace(self, *, postgame=False):
        lines = [
            'Offline initial state reached after game initialization. PID=123',
            'RECOVERY SMOKE invoking original disconnected modal OnConfirm',
            'Dedicated Reconnect callback queued: update=10 originalChannel=0 pendingClosure=0 thenPlay=0',
            'RECOVERY SMOKE original OnConfirm returned; modalStillOwned=1 queued=1',
            'Dedicated retry modal released on later update: requested=10 current=11 nativeRelease=1 hadModal=1 menu=1 worldIdle=1',
        ]
        if postgame:
            lines.append('Dedicated postgame Reconnect invokes original OnContinue: match=old menu=0 worldIdle=1 navigation=0')
        lines += [
            'Dedicated session reset: match=old sessions=1 completed=0 nextFrame=100; native world inactive/zero',
            'Dedicated explicit retry opening fresh lobby; readyIntent=0',
            'RECOVERY SMOKE fresh lobby is not ready; invoking native Play',
            'Dedicated session 2 joined match=new assignedSeat=0',
        ]
        return '\n'.join(lines)

    def test_complete_ordered_recovery_and_postgame_continue(self):
        for postgame in (False, True):
            with self.subTest(postgame=postgame):
                self.assertTrue(all(recovery_evidence(self.trace(postgame=postgame),'old',postgame=postgame).values()))

    def test_reused_pid_does_not_supply_old_success_markers(self):
        log = self.trace() + '\nOffline initial state reached after game initialization. PID=123\nnew run'
        self.assertNotIn('callback queued',current_native_log(log))
        self.assertFalse(any(recovery_evidence(log,'old').values()))
        self.assertEqual(current_native_log('marker without startup'), '')

    def test_callback_release_must_be_deferred_and_ordered(self):
        log = self.trace().replace('current=11','current=10')
        self.assertFalse(recovery_evidence(log,'old')['later_update'])
        lines = self.trace().splitlines()
        lines[3],lines[4] = lines[4],lines[3]
        self.assertFalse(recovery_evidence('\n'.join(lines),'old')['ordered'])
        self.assertFalse(recovery_evidence(self.trace().replace('requested=10','requested=9'),'old')['later_update'])

    def test_reused_pid_is_empty_until_this_launch_writes_startup(self):
        old = '[100] ' + self.trace()
        self.assertEqual(current_native_log(old, since_tick=200), '')
        fresh = old + '\n[201] Offline initial state reached after game initialization. PID=123\nnew run'
        self.assertEqual(current_native_log(fresh, since_tick=200),
                         'Offline initial state reached after game initialization. PID=123\nnew run')
        self.assertEqual(current_native_log(self.trace(), since_tick=200), '')

    def test_wrong_match_or_automatic_play_cannot_pass(self):
        self.assertFalse(recovery_evidence(self.trace(),'different')['reset_old_match'])
        log = self.trace().replace('RECOVERY SMOKE fresh lobby', 'Dedicated session 2 joined match=new assignedSeat=0\nRECOVERY SMOKE fresh lobby')
        self.assertFalse(recovery_evidence(log,'old')['new_match_waited_for_play'])
        self.assertFalse(recovery_evidence(self.trace().replace('readyIntent=0','readyIntent=1'),'old')['explicit_unready_retry'])

    def test_postgame_requires_native_continue_evidence(self):
        self.assertFalse(recovery_evidence(self.trace(),'old',postgame=True)['native_continue'])

    def test_pre_match_recovery_requires_a_session_zero_reset(self):
        log = self.trace().replace('match=old sessions=1', 'match= sessions=0')
        self.assertTrue(all(recovery_evidence(log,None).values()))
        self.assertFalse(recovery_evidence(self.trace(),None)['reset_old_match'])


class QualificationScenarioTests(unittest.TestCase):
    def options(self, **overrides):
        values = dict(disconnect_frame=None,postgame_error=False,pre_match_failure=None,
                      quit_on_failure=False,rtt_ms=0,jitter_ms=0)
        return argparse.Namespace(**(values | overrides))

    def test_recovery_and_quit_have_distinct_completion_requirements(self):
        cases = [({},(2,4)), ({'disconnect_frame':100},(1,4)),
            ({'postgame_error':True},(2,4)),
            ({'pre_match_failure':'unavailable'},(1,2)),
            ({'pre_match_failure':'authentication'},(1,2)),
            ({'pre_match_failure':'lobby'},(1,3)),
            ({'disconnect_frame':100,'quit_on_failure':True},(0,2)),
            ({'postgame_error':True,'quit_on_failure':True},(1,2))]
        for options,expected in cases:
            with self.subTest(options=options):
                self.assertEqual(scenario_expectations(self.options(**options)),expected)

    def test_ambiguous_faults_and_unsupported_quit_or_shaping_rejected(self):
        cases = [dict(disconnect_frame=100,postgame_error=True),
            dict(pre_match_failure='lobby',postgame_error=True),
            dict(quit_on_failure=True),
            dict(pre_match_failure='authentication',quit_on_failure=True),
            dict(pre_match_failure='unavailable',rtt_ms=50),
            dict(pre_match_failure='lobby',jitter_ms=20)]
        for options in cases:
            with self.subTest(options=options),self.assertRaises(ValueError):
                scenario_expectations(self.options(**options))


if __name__ == '__main__':
    unittest.main()
