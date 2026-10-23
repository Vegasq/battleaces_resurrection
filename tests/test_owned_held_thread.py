"""Owned held-thread failure/identity boundaries using an authored fake API."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from tools.owned_held_thread import HeldThreadFailure, OwnedHeldThread
from tools.owned_suspended_launch import SuspendedChild


class Observer:
    def __init__(self):
        self.owner=SuspendedChild();self.owner.handle=901;self.owner.pid=100
        self.owner.job=SimpleNamespace(handle=902)
        self.process_handle=201;self.thread_handle=202
        self.process=dict(pid=101,creation_filetime=1000,image=r'C:\owned\child.exe',image_sha256='a'*64,in_owned_job=True)
        self.thread=dict(pid=101,tid=102,creation_filetime=1010,exit_filetime=0,exit_code=259)
        self.exit_result=None;self.owner_exit_result=None;self.count=1;self.calls=[];self.close_fail=set()
        self.descriptor=dict(pid=101,pebAddress='0x1000')
        self.foreign=False;self.tick_value=100

    def record(self):return dict(deepcopy(self.process),exit=None)
    def validate_owner(self,owner):
        self.calls.append(('owner',owner.handle))
        if owner is not self.owner or owner.pid!=100:raise RuntimeError('owner handle identity differs')
    def open(self,pid):
        self.calls.append(('open_process',pid));return self.process_handle
    def identity(self,handle,pid,job):
        self.calls.append(('process_identity',handle,pid,job))
        if self.foreign:raise RuntimeError('not in owned job')
        return deepcopy(self.process)
    def exit(self,handle):return self.owner_exit_result if handle==self.owner.handle else self.exit_result
    def open_thread(self,tid):
        self.calls.append(('open_thread',tid));return self.thread_handle
    def thread_identity(self,handle,pid,tid):
        self.calls.append(('thread_identity',handle,pid,tid));return deepcopy(self.thread)
    def basic(self,handle,pid):
        self.calls.append(('basic',handle,pid));return dict(self.descriptor)
    def tick(self):self.tick_value+=1;return self.tick_value
    def resume_thread(self,handle):
        self.calls.append(('resume',handle));return self.count
    def close(self,handle):
        self.calls.append(('close',handle))
        if handle in self.close_fail:raise OSError('authored close error')


class HeldThreadTests(unittest.TestCase):
    def create(self,api=None,**kw):
        api=api or Observer()
        return api,OwnedHeldThread(api.owner,record=api.record(),tid=102,_observer=api,**kw)
    def resumes(self,api):return [c for c in api.calls if c[0]=='resume']
    def closed(self,api):return [c[1] for c in api.calls if c[0]=='close']

    def test_success_revalidates_then_resumes_once_and_closes_only_own_handles(self):
        api,held=self.create();self.assertEqual(held.cwd_descriptor,dict(pid=101,pebAddress='0x1000'))
        descriptor=held.cwd_descriptor;descriptor['pid']=9
        self.assertEqual(held.pid,101);self.assertEqual(held.tid,102)
        receipt=held.resume();self.assertTrue(receipt['resumed']);self.assertEqual(receipt['resume_previous_count'],1)
        with self.assertRaisesRegex(RuntimeError,'already attempted'):held.resume()
        self.assertEqual(self.resumes(api),[('resume',202)])
        self.assertEqual(len([c for c in api.calls if c[0]=='process_identity']),2)
        held.close();held.close();self.assertEqual(self.closed(api),[202,201])
        self.assertEqual(api.owner.handle,901);self.assertEqual(api.owner.job.handle,902)
        self.assertFalse(receipt['termination_api_called']);self.assertFalse(receipt['suspension_api_called'])

    def test_wrong_owner_type_and_malformed_record_have_no_open_side_effects(self):
        api=Observer()
        with self.assertRaises(ValueError):OwnedHeldThread(SimpleNamespace(handle=901,job=api.owner.job,pid=100),record=api.record(),tid=102,_observer=api)
        for change in [dict(pid=True),dict(pid=0),dict(creation_filetime=0),dict(image='relative.exe'),dict(image_sha256='bad'),dict(in_owned_job=False),dict(exit=dict(exit_code=0))]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                OwnedHeldThread(api.owner,record=dict(api.record(),**change),tid=102,_observer=api)
        for tid in (False,0,-1,2**32,'102'):
            with self.subTest(tid=tid),self.assertRaises(ValueError):OwnedHeldThread(api.owner,record=api.record(),tid=tid,_observer=api)
        self.assertEqual(api.calls,[])

    def test_foreign_job_closes_process_before_thread_open(self):
        api=Observer();api.foreign=True
        with self.assertRaises(HeldThreadFailure) as cm: self.create(api)
        self.assertEqual(self.closed(api),[201]);self.assertFalse(cm.exception.receipt['resumed'])
        self.assertFalse(any(c[0]=='open_thread' for c in api.calls));self.assertFalse(self.resumes(api))

    def test_pid_reuse_image_or_creation_change_rejected_before_resume(self):
        for change in [dict(pid=999),dict(creation_filetime=1001),dict(image=r'C:\other\child.exe'),dict(image_sha256='b'*64),dict(in_owned_job=False)]:
            with self.subTest(change=change):
                api,held=self.create();api.process.update(change)
                with self.assertRaises(HeldThreadFailure):held.resume()
                # A rejected call cannot be repaired and retried later.
                api.process=api.record();api.process['creation_filetime']=1000
                with self.assertRaisesRegex(RuntimeError,'already attempted'):held.resume()
                self.assertFalse(self.resumes(api));held.close();self.assertEqual(self.closed(api),[202,201])

    def test_record_snapshot_does_not_mutate_with_callers_record(self):
        api=Observer();record=api.record();held=OwnedHeldThread(api.owner,record=record,tid=102,_observer=api)
        record.update(creation_filetime=2000,image_sha256='b'*64)
        self.assertTrue(held.resume()['resumed']);held.close()

    def test_wrong_thread_pid_tid_dead_or_creation_rejected_and_both_handles_closed(self):
        for change in [dict(pid=999),dict(tid=999),dict(creation_filetime=999),dict(exit_filetime=2000),dict(exit_code=0)]:
            with self.subTest(change=change):
                api=Observer();api.thread.update(change)
                with self.assertRaises(HeldThreadFailure):self.create(api)
                self.assertEqual(self.closed(api),[202,201]);self.assertFalse(self.resumes(api))

    def test_process_exit_or_thread_reuse_before_resume_refused(self):
        api,held=self.create();api.exit_result=dict(exit_code=0,wait_signaled=True)
        with self.assertRaises(HeldThreadFailure):held.resume()
        self.assertFalse(self.resumes(api));held.close()
        api,held=self.create();api.thread['creation_filetime']=1020
        with self.assertRaises(HeldThreadFailure):held.resume()
        self.assertFalse(self.resumes(api));held.close()

    def test_prior_count_zero_two_or_api_failure_cannot_retry_or_implicitly_resume(self):
        for count in (0,2,0xffffffff):
            with self.subTest(count=count):
                api,held=self.create();api.count=count
                with self.assertRaises(HeldThreadFailure) as cm:held.resume()
                self.assertTrue(cm.exception.receipt['resume_attempted']);self.assertFalse(cm.exception.receipt['resumed'])
                self.assertEqual(cm.exception.receipt['resume_previous_count'],count)
                with self.assertRaisesRegex(RuntimeError,'already attempted'):held.resume()
                held.close();self.assertEqual(self.resumes(api),[('resume',202)])

    def test_close_without_resume_keeps_thread_held_and_owner_untouched(self):
        api,held=self.create();held.close();self.assertFalse(self.resumes(api))
        with self.assertRaisesRegex(RuntimeError,'closed'):held.resume()
        self.assertEqual(api.owner.handle,901);self.assertEqual(api.owner.job.handle,902)

    def test_close_error_attempts_other_handle_and_can_retry_without_resuming(self):
        api,held=self.create();api.close_fail.add(202)
        receipt=held.close();self.assertFalse(receipt['closed']);self.assertEqual(self.closed(api),[202,201])
        api.close_fail.clear();self.assertTrue(held.close()['closed'])
        self.assertEqual(self.closed(api),[202,201,202]);self.assertFalse(self.resumes(api))
        api,held=self.create();api.close_fail.update((201,202))
        self.assertFalse(held.close()['closed'])
        with self.assertRaisesRegex(RuntimeError,'closed'):held.resume()
        api.close_fail.clear();held.close();self.assertFalse(self.resumes(api))

    def test_missing_handle_and_bad_basic_info_refuse_with_cleanup(self):
        for change in ('process','thread','zero_process','zero_thread','pid','peb','extra'):
            with self.subTest(change=change):
                api=Observer()
                if change=='process':api.process_handle=None
                elif change=='thread':api.thread_handle=None
                elif change=='zero_process':api.process_handle=0
                elif change=='zero_thread':api.thread_handle=0
                elif change=='pid':api.descriptor['pid']=999
                elif change=='peb':api.descriptor['pebAddress']='0x1001'
                else:api.descriptor['environment']='not allowed'
                with self.assertRaises(HeldThreadFailure):self.create(api)
                self.assertFalse(self.resumes(api))
                self.assertNotIn(None,self.closed(api))
                self.assertNotIn(0,self.closed(api))

    def test_constructor_close_failure_retains_explicit_retry_owner_without_resume(self):
        api=Observer();api.thread['tid']=999;api.close_fail.add(202)
        with self.assertRaises(HeldThreadFailure) as cm:self.create(api)
        self.assertFalse(cm.exception.receipt['closed']);self.assertEqual(self.closed(api),[202,201])
        api.close_fail.clear();self.assertTrue(cm.exception.close()['closed'])
        self.assertEqual(self.closed(api),[202,201,202]);self.assertFalse(self.resumes(api))

    def test_missing_owner_handles_reject_before_observer(self):
        for change in ('process','job','job_handle'):
            api=Observer()
            if change=='process':api.owner.handle=None
            elif change=='job':api.owner.job=None
            else:api.owner.job=SimpleNamespace()
            with self.subTest(change=change),self.assertRaises(ValueError):self.create(api)
            self.assertEqual(api.calls,[])

    def test_owner_job_changed_before_resume_never_calls_target_thread(self):
        api,held=self.create();api.owner.job.handle=999
        with self.assertRaises(HeldThreadFailure):held.resume()
        self.assertFalse(self.resumes(api));held.close();self.assertEqual(self.closed(api),[202,201])

    def test_expired_owner_handle_still_in_job_refused_before_open_and_before_resume(self):
        api=Observer();api.owner_exit_result=dict(exit_code=0,wait_signaled=True)
        with self.assertRaises(HeldThreadFailure):self.create(api)
        self.assertFalse(any(c[0].startswith('open_') for c in api.calls))
        api,held=self.create();api.owner_exit_result=dict(exit_code=0,wait_signaled=True)
        with self.assertRaises(HeldThreadFailure):held.resume()
        self.assertFalse(self.resumes(api));held.close();self.assertEqual(self.closed(api),[202,201])


if __name__=='__main__':unittest.main()
