import copy
import unittest
from tools.verify_settings_flush import fault_evidence,startup_log,unresolved_exit_evidence


class SettingsFlushTests(unittest.TestCase):
    def test_pre_menu_save_log_preserved_without_old_pid_or_partial_lines(self):
        raw=b'[90] old process\n[101] early failed save\n[110] Offline initial state reached\n[120] menu\n[130] partial'
        self.assertEqual(startup_log(raw,100),'[101] early failed save\n[110] Offline initial state reached\n[120] menu')
        self.assertEqual(startup_log(b'[100] unfinished',100),'')
    def rows(self):return [dict(kind='armed',pid=42,sequence=1),dict(kind='flush-failed',pid=42,sequence=2,original=1,result=0,error=29)]

    def test_scoped_failed_api_result(self):
        proof=fault_evidence(self.rows(),42)
        self.assertEqual(proof['failed_calls'],1)
        self.assertFalse(proof['rename_while_faulted'])

    def test_rejects_publication_error_wrong_result_and_identity(self):
        for change in (dict(kind='unexpected-rename'),dict(kind='error'),dict(pid=43),dict(sequence=1),dict(original=0),dict(result=1),dict(error=0)):
            rows=copy.deepcopy(self.rows());rows[1].update(change)
            with self.subTest(change=change),self.assertRaises(AssertionError):fault_evidence(rows,42)

    def test_requires_observed_failure(self):
        for rows in ([],self.rows()[:1]):
            with self.assertRaises(AssertionError):fault_evidence(rows,42)

    def publication(self):
        return [dict(kind='armed',pid=42,sequence=1),
                dict(kind='flush-completed',pid=42,sequence=2,path='owned.tmp',result=1),
                dict(kind='target-locked',pid=42,sequence=3,path='owned.tmp',share=3),
                dict(kind='publication-refused',pid=42,sequence=4,path='owned.tmp',result=0,error=32,lock_closed=True)]

    def test_real_publication_refusal_after_flush(self):
        for error in (5,32):
            rows=self.publication();rows[-1]['error']=error
            self.assertEqual(fault_evidence(rows,42,'publication')['win32_errors'],[error])

    def test_rejects_wrong_order_success_unreleased_lock_or_other_path(self):
        for index,change in ((1,dict(result=0)),(2,dict(share=7)),(2,dict(path='other.tmp')),
                             (3,dict(result=1)),(3,dict(error=123)),(3,dict(lock_closed=False)),(1,dict(kind='target-locked'))):
            rows=self.publication();rows[index].update(change)
            with self.subTest(change=change),self.assertRaises(AssertionError):fault_evidence(rows,42,'publication')

    def test_incomplete_publication_and_probe_error_rejected(self):
        for rows in (self.publication()[:-1],self.publication()[:1],self.rows()):
            with self.assertRaises(AssertionError):fault_evidence(rows,42,'publication')

    def first_save(self):
        rows=self.rows();rows.insert(1,dict(kind='helper-bound',pid=42,sequence=2))
        rows.insert(2,dict(kind='target-open',pid=42,sequence=3,disposition=4,success=True,size=0));rows[-1]['sequence']=4
        return rows

    def test_first_save_requires_early_helper_binding(self):
        self.assertEqual(fault_evidence(self.first_save(),42,first_save=True)['failed_calls'],1)
        with self.assertRaises(AssertionError):fault_evidence(self.rows(),42,first_save=True)

    def test_first_save_rejects_late_binding_and_publication(self):
        rows=self.first_save();rows[1]['kind']='flush-failed';rows[2]['kind']='helper-bound'
        with self.assertRaises(AssertionError):fault_evidence(rows,42,first_save=True)

    def test_first_save_rejects_partial_target_and_unproved_placeholder(self):
        for change in (dict(size=1),dict(success=False),dict(disposition=3)):
            rows=self.first_save();rows[2].update(change)
            with self.assertRaises(AssertionError):fault_evidence(rows,42,first_save=True)
        rows=self.first_save();rows.append(dict(kind='target-write',pid=42,sequence=5,requested=1,result=1))
        with self.assertRaises(AssertionError):fault_evidence(rows,42,first_save=True)

    def test_unresolved_exit_requires_fault_during_original_quit(self):
        rows=self.first_save();rows[-1]['tick']=100
        rows.append(dict(rows[-1],sequence=5,tick=200))
        trace=[dict(event='OnConfirm.dispatch',pid=42,tick=150)]
        self.assertTrue(unresolved_exit_evidence(rows,'',42,trace,1)['failed_during_quit'])
        for changed,log,events,count in ((rows[:-1],'',trace,1),(rows,'',trace,2),(rows,'',[],1),
                                         (rows,'NATIVE SETTINGS save result: succeeded=1',trace,1)):
            with self.assertRaises(AssertionError):unresolved_exit_evidence(changed,log,42,events,count)
        rows[-1]['tick']=149
        with self.assertRaises(AssertionError):unresolved_exit_evidence(rows,'',42,trace,1)
        rows=self.first_save();rows[-1]['kind']='unexpected-rename'
        with self.assertRaises(AssertionError):fault_evidence(rows,42,first_save=True)


if __name__=='__main__':unittest.main()
