"""Negative evidence controls for the recovered native game qualification."""
import copy
import unittest

from tools.verify_recovered_game import validate_completion, validate_dashboard


def evidence():
    state=dict(complete=True,winning_alliance=1,army_conceded_flag=1,game_over_frame=140)
    record=dict(match='owned184',native_result=state.copy(),
                public_result=dict(match='owned184',reason='native game complete',result=state.copy()),
                frame_payload_sha256=[str(i) for i in range(160)])
    rows=[]
    def add(event,**fields):
        rows.append(dict(event=event,match='owned184',perf_counter_ns=len(rows),**fields))
    add('worker_started',worker_pid=184)
    add('match_created');add('match_started')
    for frame in range(160):add('frame_queued',frame=frame,frame_payload_sha256=str(frame))
    add('native_game_over',result=state.copy())
    add('match_completed',next_frame=160,result=state.copy())
    add('worker_released',worker_pid=184)
    rows.append(dict(event='server_stopped',perf_counter_ns=200))
    return rows,record


class CompletionEvidenceTests(unittest.TestCase):
    def test_matching_native_public_and_audit_results(self):
        rows,record=evidence()
        self.assertEqual(validate_completion(rows,record,stop_ns=199),184)

    def test_incomplete_wrong_winner_and_wrong_frame_rejected(self):
        for key,value in [('complete',False),('winning_alliance',0),
                          ('army_conceded_flag',0),('game_over_frame',59)]:
            with self.subTest(key=key):
                rows,record=evidence()
                record['public_result']['result'][key]=value
                with self.assertRaises(AssertionError):validate_completion(rows,record)

    def test_abort_and_missing_or_duplicate_release_rejected(self):
        for mutation in ('abort','missing','duplicate','other_worker','release_after_stop'):
            with self.subTest(mutation=mutation):
                rows,record=evidence()
                release=next(row for row in rows if row['event']=='worker_released')
                if mutation=='abort':rows.append(dict(event='match_aborted',match='owned184'))
                if mutation=='missing':rows.remove(release)
                if mutation=='duplicate':rows.append(copy.deepcopy(release))
                if mutation=='other_worker':release['worker_pid']=999
                if mutation=='release_after_stop':release['perf_counter_ns']=201
                with self.assertRaises(AssertionError):validate_completion(rows,record,stop_ns=199)

    def test_dropped_reordered_or_changed_frames_rejected(self):
        for mutation in ('drop','order','bytes'):
            with self.subTest(mutation=mutation):
                rows,record=evidence()
                if mutation=='drop':rows.pop(5)
                if mutation=='order':rows[5],rows[6]=rows[6],rows[5]
                if mutation=='bytes':record['frame_payload_sha256'][0]='different'
                with self.assertRaises(AssertionError):validate_completion(rows,record)

    def test_native_result_mismatch_rejected(self):
        rows,record=evidence();record['native_result']['winning_alliance']=0
        with self.assertRaises(AssertionError):validate_completion(rows,record)

    def test_dashboard_cannot_substitute_another_result_or_player(self):
        _,record=evidence()
        row=dict(id='owned184',state='completed',winning_alliance=1,
                 players=[dict(id=str(i),name='Recovery Player '+str(i),bot=False) for i in (0,1)])
        status=dict(history=[row],active=[],completed=1,history_total=1)
        validate_dashboard(status,record,{'0','1'},completed=True)
        for key,value in [('id','another'),('state','aborted'),('winning_alliance',0)]:
            changed=copy.deepcopy(status);changed['history'][0][key]=value
            with self.assertRaises(AssertionError):validate_dashboard(changed,record,{'0','1'},completed=True)
        changed=copy.deepcopy(status);changed['history'][0]['players'][0]['id']='wrong'
        with self.assertRaises(AssertionError):validate_dashboard(changed,record,{'0','1'},completed=True)


if __name__=='__main__':unittest.main()
