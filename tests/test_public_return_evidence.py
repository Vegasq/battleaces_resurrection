"""Reject incomplete or overlapping retries after finished-match RETURN-ACK loss."""
from copy import deepcopy
import unittest

from tools.public_return_evidence import validate


class PublicReturnEvidenceTests(unittest.TestCase):
    def fixture(self,mode=1):
        ids=['a'*32,'b'*32];count=2 if mode==1 else 4
        lines=[];events=[];matches=[]
        for ticket,key in enumerate(ids,1):
            lines.extend([
                f'Public search intent: ticket={ticket} mode={mode} originalSearch=1 deadlineMs=30000 BA_RESURRECTION_PUBLIC_QUEUE_V1',
                f'Client world acquired: generation={ticket} owner=remote match={key}',
                f'Public native match joined: ticket={ticket} match={key} mode={mode} participants={count} seat=0 remoteWorld=1',
                f'Public result Continue routed: mode={mode} source=remote next=End rewards=0 progressionUnchanged=1 publicModePreserved=1',
                f'Client world released: generation={ticket} owner=remote nativeIdle=1',
                f'Public native return: ticket={ticket} match={key} aborted=0 nativeIdle=1',
            ])
            if ticket==1:lines.append('Public intent retired: ticket=1 reason=connection lost after return nativeIdle=1 disconnect=1')
            else:lines.extend([
                f'PUBLIC QUEUE completed return: match={key} completed=1 seatReleased=1',
                'Public intent retired: ticket=2 reason=returned nativeIdle=1 disconnect=0'])
            result=dict(complete=True,game_over_frame=1200,winning_alliance=1)
            matches.append(dict(ticket=ticket,match=key,received_frames=1220,result=deepcopy(result)))
            events.extend([
                dict(event='public_queue_entered',ticket=ticket),
                dict(event='public_match_offered',tickets=[ticket],match=key),
                dict(event='worker_started',match=key),dict(event='match_created',match=key),
                dict(event='match_completed',match=key,result=deepcopy(result)),
                dict(event='probe_return_request',ticket=ticket,match=key,request=4),
                dict(event='public_ticket_retired',ticket=ticket,reason='returned to menu'),
            ])
            if ticket==1:events.append(dict(event='probe_drop_return_ack',request=4,success=True))
        return [''.join(f'[{1000+i}] {line}\n' for i,line in enumerate(lines)),mode,matches,events]

    def test_two_complete_native_matches_in_all_supported_modes_and_windows_logs(self):
        for mode in (1,2,5):
            for crlf in (False,True):
                with self.subTest(mode=mode,crlf=crlf):
                    args=self.fixture(mode)
                    if crlf:args[0]=args[0].replace('\n','\r\n')
                    result=validate(*args)
                    self.assertEqual(result['completed_matches'],2)
                    self.assertEqual(result['received_frames'],[1220,1220])
                    self.assertTrue(result['second_play_after_idle_retirement'])

    def test_retirement_only_or_incomplete_second_match_cannot_pass(self):
        for change in ('one_match','unfinished','few_receipts','same_identity','wrong_ticket','server_result'):
            with self.subTest(change=change):
                args=self.fixture()
                if change=='one_match':args[2].pop()
                if change=='unfinished':args[2][1]['result']['complete']=False
                if change=='few_receipts':args[2][1]['received_frames']=599
                if change=='same_identity':args[2][1]['match']=args[2][0]['match']
                if change=='wrong_ticket':args[2][1]['ticket']=1
                if change=='server_result':
                    next(row for row in args[3] if row['event']=='match_completed' and row['match']=='b'*32)['result']['winning_alliance']=0
                with self.assertRaises(AssertionError):validate(*args)

    def test_early_retry_missing_continue_or_wrong_world_ownership_is_rejected(self):
        for change in ('missing_continue','duplicate_world','early_retry','wrong_match','wrong_generation','wrong_mode'):
            with self.subTest(change=change):
                args=self.fixture();log=args[0]
                if change=='missing_continue':log=log.replace('Public result Continue routed:','missing: ',1)
                if change=='duplicate_world':log+='[2000] Client world acquired: generation=3 owner=remote match='+'c'*32+'\n'
                if change=='early_retry':
                    lines=log.splitlines();lines[6],lines[7]=lines[7],lines[6];log='\n'.join(lines)+'\n'
                if change=='wrong_match':log=log.replace('match='+'b'*32,'match='+'c'*32,1)
                if change=='wrong_generation':log=log.replace('generation=2','generation=1')
                if change=='wrong_mode':args[1]=2
                args[0]=log
                with self.assertRaises(AssertionError):validate(*args)

    def test_false_start_error_fallback_or_received_first_ack_is_rejected(self):
        for marker in ('identity=public-error:1','owner=local-practice','Public fallback accepted:',
                       'Public client failure:','Public result Continue routing failed:',
                       'Public ACK: ticket=1 kind=61 request=4 success=1 reason='):
            with self.subTest(marker=marker):
                args=self.fixture();args[0]+='[2000] '+marker+'\n'
                with self.assertRaises(AssertionError):validate(*args)

    def test_missing_wrong_or_misordered_ack_loss_is_rejected(self):
        for change in ('missing','duplicate','wrong_request','after_second_return','before_first_return','wrong_return','negative_ack','not_returned'):
            with self.subTest(change=change):
                args=self.fixture();events=args[3]
                drop=next(row for row in events if row['event']=='probe_drop_return_ack')
                if change=='missing':events.remove(drop)
                if change=='duplicate':events.append(deepcopy(drop))
                if change=='wrong_request':drop['request']=99
                if change=='after_second_return':events.remove(drop);events.append(drop)
                if change=='before_first_return':events.remove(drop);events.insert(0,drop)
                if change=='wrong_return':next(row for row in events if row['event']=='probe_return_request' and row['ticket']==2)['match']='c'*32
                if change=='negative_ack':drop['success']=False
                if change=='not_returned':next(row for row in events if row['event']=='public_ticket_retired')['reason']='public player disconnected'
                with self.assertRaises(AssertionError):validate(*args)

    def test_extra_queue_worker_abort_or_server_completion_is_rejected(self):
        for event in ('public_queue_entered','public_match_offered','worker_started','match_created','match_aborted','match_completed'):
            with self.subTest(event=event):
                args=self.fixture();args[3].append(dict(event=event,ticket=3,tickets=[3],match='c'*32,result=dict(complete=True)))
                with self.assertRaises(AssertionError):validate(*args)


if __name__=='__main__':unittest.main()
