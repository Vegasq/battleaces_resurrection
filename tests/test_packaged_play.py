"""Real owned job accounting; no proprietary game or fixture data."""
import os
import subprocess
import sys
import time
import unittest
from server.worker_client import _WindowsJob
from tools.verify_packaged_play import job_accounting


@unittest.skipUnless(os.name=='nt','Windows job accounting')
class PackagedPlayJobTests(unittest.TestCase):
    def test_natural_child_exit_is_observed_before_job_close(self):
        process=subprocess.Popen([sys.executable,'-I','-B','-c','import sys; sys.stdin.buffer.read(1)'],stdin=subprocess.PIPE)
        job=None
        try:
            job=_WindowsJob(process.pid)
            self.assertGreaterEqual(job_accounting(job.handle)['active_processes'],1)
            process.stdin.write(b'x');process.stdin.flush();process.stdin.close()
            self.assertEqual(process.wait(timeout=5),0)
            deadline=time.monotonic()+5
            while job_accounting(job.handle)['active_processes']:
                self.assertLess(time.monotonic(),deadline)
                time.sleep(.02)
            self.assertGreaterEqual(job_accounting(job.handle)['total_processes'],1)
        finally:
            if job is not None:job.close()
            if process.poll() is None:process.kill();process.wait(timeout=5)
            if process.stdin and not process.stdin.closed:process.stdin.close()
