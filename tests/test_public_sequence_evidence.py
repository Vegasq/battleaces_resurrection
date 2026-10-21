"""Authored lifecycle fixtures for the four-stage public transition check."""
import unittest

from tools.public_sequence_evidence import MODES, sequence, stage


class PublicSequenceEvidenceTests(unittest.TestCase):
    def fixture(self):
        gate = 'a'*32
        logs, stages = [], []
        for ticket, mode in enumerate(MODES, 1):
            match = str(ticket)*32
            seat, count, mask = (0, 2 if mode == 1 else 4, 5 if mode == 5 else 3)
            lines = [
                f'PUBLIC MODE SEQUENCE gate released: key={gate} stage={ticket}',
                f'Public search intent: ticket={ticket} mode={mode} originalSearch=1 deadlineMs=30000',
                f'Public match assignment: ticket={ticket} match={match} mode={mode} count={count} seat={seat} humans={mask} inputWindow=6',
                f'Client world acquired: generation={ticket} owner=remote match={match}',
                f'Public native match joined: ticket={ticket} match={match} mode={mode} participants={count} seat={seat} remoteWorld=1',
                f'Native search joining signal: ticket={ticket} original=1',
                'Practice native EndOfGameResponse delivered; winner=1',
                'DEDICATED REMATCH SMOKE automated original MatchResultVM.OnContinue; active=0',
                f'Public result Continue routed: mode={mode} source=remote next=End',
                f'Native search released: ticket={ticket} reason=returned',
                f'Client world released: generation={ticket} owner=remote nativeIdle=1',
                f'Public native return: ticket={ticket} match={match} aborted=0 nativeIdle=1',
                f'PUBLIC QUEUE completed return: match={match} completed={ticket} seatReleased=1',
                f'Public intent retired: ticket={ticket} reason=returned nativeIdle=1 disconnect=0',
            ]
            log = ''.join(f'[{index+1}] {line}\n' for index, line in enumerate(lines))
            logs.append(log)
            stages.append(dict(ticket=ticket, mode=mode, match=match, seat=seat, gate=gate, human_mask=mask))
        return logs, stages

    def test_complete_same_process_sequence_and_windows_newlines(self):
        logs, stages = self.fixture()
        for newline in ('\n', '\r\n'):
            proofs = [stage(log.replace('\n', newline), **value) for log, value in zip(logs, stages)]
            result = sequence(''.join(logs), proofs)
            self.assertEqual(result['modes'], [1, 2, 5, 1])
            self.assertEqual(result['remote_worlds'], 4)
            self.assertFalse(result['physical_native_quit_bundled_or_lan_qualified'])

    def test_wrong_mode_seat_match_generation_or_human_group_is_rejected(self):
        logs, stages = self.fixture()
        for old, new in (('mode=2', 'mode=1'), ('seat=0', 'seat=2'), ('humans=3', 'humans=1'),
                         ('generation=2', 'generation=1'), ('match='+'2'*32, 'match='+'9'*32)):
            with self.subTest(change=old):
                with self.assertRaises(AssertionError):
                    stage(logs[1].replace(old, new), **stages[1])

    def test_no_continue_duplicate_world_fallback_and_early_release_are_rejected(self):
        logs, stages = self.fixture()
        for change in ('missing_continue', 'duplicate', 'fallback', 'error', 'early_release'):
            with self.subTest(change=change):
                log = logs[0]
                if change == 'missing_continue':
                    log = log.replace('automated original MatchResultVM.OnContinue;', 'other callback;')
                elif change == 'duplicate':
                    log += '[99] Client world acquired: generation=9 owner=remote match='+'9'*32+'\n'
                elif change == 'fallback':
                    log += '[99] Public fallback accepted: ticket=1\n'
                elif change == 'error':
                    log += '[99] Public client failure: fixture\n'
                else:
                    lines = log.splitlines()
                    release = next(row for row in lines if 'Client world released:' in row)
                    lines.remove(release)
                    lines.insert(0, release)
                    log = '\n'.join(lines)+'\n'
                with self.assertRaises(AssertionError):
                    stage(log, **stages[0])

    def test_repeated_mode_stale_lease_and_extra_intent_are_rejected(self):
        logs, stages = self.fixture()
        proofs = [stage(log, **value) for log, value in zip(logs, stages)]
        for change in ('wrong_modes', 'stale_lease', 'extra_intent', 'missing_stage', 'duplicate_match'):
            with self.subTest(change=change):
                log = ''.join(logs)
                values = [dict(value) for value in proofs]
                if change == 'wrong_modes':
                    values[1]['mode'] = 1
                elif change == 'stale_lease':
                    log = log.replace('generation=3', 'generation=2')
                elif change == 'extra_intent':
                    log += '[999] Public search intent: ticket=5 mode=1\n'
                elif change == 'missing_stage':
                    values.pop()
                else:
                    values[3]['match'] = values[0]['match']
                with self.assertRaises(AssertionError):
                    sequence(log, values)


if __name__ == '__main__':
    unittest.main()
