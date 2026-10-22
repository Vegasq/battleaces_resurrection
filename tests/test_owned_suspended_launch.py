"""Fault-path ownership tests; real suspended control is qualified separately."""
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock,patch
from tools import owned_suspended_launch as launch


@unittest.skipUnless(os.name=='nt','Windows diagnostic only')
class SuspendedOwnership(unittest.TestCase):
    def child(self):
        child=launch.SuspendedChild();child.kernel=Mock();child.handle=11;child.thread=12
        child.pid=21;child.tid=22;child.job=Mock(handle=13);child.returncode=None;child.resumed=False
        child.receipt=dict(forced_cleanup=False,owned_process_reaped=False,primary_thread_resumed=False)
        child.kernel.GetThreadId.return_value=22;child.kernel.GetProcessIdOfThread.return_value=21
        child.kernel.GetTickCount64.return_value=100;child.kernel.WaitForSingleObject.return_value=258
        return child

    def test_resume_identity_mismatch_never_resumes(self):
        child=self.child();child.kernel.GetProcessIdOfThread.return_value=999
        with self.assertRaisesRegex(RuntimeError,'identity'):child.resume()
        child.kernel.ResumeThread.assert_not_called()
        self.assertFalse(child.resumed)

    def test_resume_requires_exact_single_suspension(self):
        for count in (0,2,0xffffffff):
            with self.subTest(count=count):
                child=self.child();child.kernel.ResumeThread.return_value=count
                with self.assertRaisesRegex(RuntimeError,'exactly one'):child.resume()
                self.assertFalse(child.resumed);self.assertEqual(child.thread,12)
        child=self.child();child.kernel.ResumeThread.return_value=1;child.resume()
        self.assertTrue(child.resumed);self.assertIsNone(child.thread)
        with self.assertRaises(RuntimeError):child.resume()
        child.kernel.ResumeThread.assert_called_once()

    def test_accounting_failure_still_releases_job_and_both_handles(self):
        child=self.child()
        with patch.object(launch,'job_accounting',side_effect=RuntimeError('accounting failed')):
            with self.assertRaisesRegex(RuntimeError,'accounting failed'):child.close()
        child.job.close.assert_called_once()
        self.assertEqual([call.args[0] for call in child.kernel.CloseHandle.call_args_list],[12,11])
        self.assertIsNone(child.thread);self.assertIsNone(child.handle)
        self.assertFalse(child.receipt['owned_process_reaped'])

    def test_abort_timeout_never_reports_reaping_and_finally_closes(self):
        child=self.child();child.kernel.TerminateJobObject.return_value=True
        with patch.object(launch,'job_accounting',return_value=dict(active_processes=1)):
            with self.assertRaises(subprocess.TimeoutExpired):child.close()
        self.assertTrue(child.receipt['forced_cleanup']);self.assertFalse(child.receipt['owned_process_reaped'])
        child.job.close.assert_called_once();self.assertEqual(child.kernel.CloseHandle.call_count,2)

    def test_failed_job_assignment_terminates_and_reaps_owned_raw_process(self):
        import _winapi
        kernel=Mock();kernel.GetTickCount64.return_value=1;kernel.WaitForSingleObject.side_effect=[258,0]
        kernel.TerminateProcess.return_value=True
        def exit_code(handle,output):output._obj.value=1;return True
        kernel.GetExitCodeProcess.side_effect=exit_code
        image=launch.ROOT/'local/authored-not-launched.exe'
        with patch.object(Path,'is_file',return_value=True), \
                 patch.object(launch,'kernel_api',return_value=kernel), \
                 patch.object(launch,'_WindowsJob',side_effect=RuntimeError('assignment failed')), \
                 patch.object(_winapi,'CreateProcess',return_value=(11,12,21,22)) as create:
            with self.assertRaises(launch.CreationFailure) as failure:launch.SuspendedChild.create([str(image)])
        self.assertTrue(failure.exception.receipt['forced_cleanup'])
        self.assertTrue(failure.exception.receipt['owned_process_reaped'])
        kernel.TerminateProcess.assert_called_once_with(11,1)
        self.assertEqual([call.args[0] for call in kernel.CloseHandle.call_args_list],[12,11])
        self.assertEqual(create.call_args.args[5],4)
        self.assertIs(create.call_args.args[4],False)

    def test_failed_termination_is_visible_not_a_cleanup_pass(self):
        child=self.child();child.job=None;child.kernel.TerminateProcess.return_value=False
        with self.assertRaises(OSError):child.close()
        self.assertFalse(child.receipt['owned_process_reaped'])
        self.assertTrue(child.receipt['forced_cleanup'])
        self.assertEqual(child.kernel.CloseHandle.call_count,2)


if __name__=='__main__':unittest.main()
