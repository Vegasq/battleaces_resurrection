import unittest

from tools.run_secure_match import current_native_log, recovery_evidence


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

    def test_wrong_match_or_automatic_play_cannot_pass(self):
        self.assertFalse(recovery_evidence(self.trace(),'different')['reset_old_match'])
        log = self.trace().replace('RECOVERY SMOKE fresh lobby', 'Dedicated session 2 joined match=new assignedSeat=0\nRECOVERY SMOKE fresh lobby')
        self.assertFalse(recovery_evidence(log,'old')['new_match_waited_for_play'])
        self.assertFalse(recovery_evidence(self.trace().replace('readyIntent=0','readyIntent=1'),'old')['explicit_unready_retry'])

    def test_postgame_requires_native_continue_evidence(self):
        self.assertFalse(recovery_evidence(self.trace(),'old',postgame=True)['native_continue'])


if __name__ == '__main__':
    unittest.main()
