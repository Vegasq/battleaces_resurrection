"""Refuse foreign/dead/reused workers; undo only the diagnostic's increment."""
from types import SimpleNamespace
import unittest
from tools.verify_room_faults import WorkerThread
from tools.verify_room_faults import owned_paths,ROOT


class OwnershipTests(unittest.TestCase):
    def test_output_cannot_enter_package_or_asset_trees(self):
        package=ROOT/'local/fixture152-package';assets=ROOT/'local/fixture152-assets'
        for output in (package,assets,package/'program/new',assets/'new',ROOT/'server/new'):
            with self.subTest(output=output),self.assertRaises(AssertionError):owned_paths(package,assets,output)
        output=ROOT/'local/fixture152-output'
        self.assertEqual(owned_paths(package,assets,output),(package.resolve(),assets.resolve(),output.resolve()))
        self.assertFalse(output.exists())

    def fixture(self,count=0,member=True):
        calls=[]
        def in_job(process,job,result):
            calls.append(('job',process,job));result._obj.value=member;return True
        def suspend(handle):calls.append(('suspend',handle));return count
        def resume(handle):calls.append(('resume',handle));return count+1
        ref=object.__new__(WorkerThread);ref.pid=101;ref.tid=202;ref.process=301;ref.thread=302;ref.suspended=False
        ref.identity=dict(pid=101,tid=202,process_creation_filetime=1000,thread_creation_filetime=1001)
        ref.identify=lambda:dict(ref.identity)
        ref.k=SimpleNamespace(IsProcessInJob=in_job,WaitForSingleObject=lambda h,t:258,
                              SuspendThread=suspend,ResumeThread=resume,
                              CloseHandle=lambda h:(calls.append(('close',h)) or True))
        worker=SimpleNamespace(pid=101,_test_backend=False,process=SimpleNamespace(poll=lambda:None),_job=SimpleNamespace(handle=999))
        return ref,worker,calls

    def test_foreign_dead_synthetic_and_reused_identity_never_suspend(self):
        for mutation in ('pid','dead','synthetic','creation'):
            ref,worker,calls=self.fixture()
            if mutation=='pid':worker.pid=102
            if mutation=='dead':worker.process.poll=lambda:1
            if mutation=='synthetic':worker._test_backend=True
            if mutation=='creation':ref.identify=lambda:dict(ref.identity,thread_creation_filetime=2000)
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):ref.suspend(worker)
            self.assertFalse(any(x[0] in ('suspend','resume') for x in calls))
            ref.close();self.assertEqual(calls[-2:],[('close',302),('close',301)])

    def test_foreign_job_never_suspends(self):
        ref,worker,calls=self.fixture(member=False)
        with self.assertRaises(AssertionError):ref.suspend(worker)
        self.assertEqual(calls,[('job',301,999)])

    def test_prior_suspension_refused_after_undoing_exactly_one_increment(self):
        ref,worker,calls=self.fixture(count=1)
        with self.assertRaises(AssertionError):ref.suspend(worker)
        self.assertEqual(calls,[('job',301,999),('suspend',302),('resume',302)])
        self.assertFalse(ref.suspended)
        ref.close()
        self.assertEqual(sum(x[0]=='resume' for x in calls),1)

    def test_failed_suspend_never_resumes_or_claims_ownership(self):
        ref,worker,calls=self.fixture(count=0xffffffff)
        with self.assertRaises(AssertionError):ref.suspend(worker)
        ref.close();self.assertFalse(ref.suspended)
        self.assertFalse(any(x[0]=='resume' for x in calls))

    def test_owned_success_cleanup_resumes_once_and_closes_only_duplicates(self):
        ref,worker,calls=self.fixture()
        self.assertEqual(ref.suspend(worker),0);self.assertTrue(ref.suspended)
        ref.close();ref.close()
        self.assertEqual(calls,[('job',301,999),('suspend',302),('resume',302),('close',302),('close',301)])
        self.assertIsNone(ref.process);self.assertIsNone(ref.thread)


if __name__=='__main__':unittest.main()
