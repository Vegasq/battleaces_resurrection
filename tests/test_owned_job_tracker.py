"""Authored deterministic lifetime/race tests; real owned Windows control separate."""
from types import SimpleNamespace
import unittest
from tools.owned_job_tracker import OwnedJobTracker


class Observer:
    def __init__(self):
        self.live = {101: 11}
        self.total = 1
        self.exited = set()
        self.closed = []
        self.opened = []
        self.reject = False
        self.owner = SimpleNamespace(pid=101, handle=901, job=SimpleNamespace(handle=902))

    def validate_owner(self, child):
        if child is not self.owner:
            raise ValueError('wrong owner')

    def accounting(self, job):
        assert job == 902
        return dict(total=self.total, active=len(self.live), terminated=0)

    def members(self, job):
        assert job == 902
        return list(self.live)

    def open(self, pid):
        handle = (pid, self.live[pid])
        self.opened.append(handle)
        return handle

    def in_job(self, handle, job):
        assert job == 902
        if self.reject:
            raise RuntimeError('foreign job')

    def identity(self, handle, pid, job):
        self.in_job(handle, job)
        return dict(pid=pid, creation_filetime=handle[1], image='authored.exe',
                    image_sha256='a'*64, in_owned_job=True)

    def exit(self, handle):
        return dict(exit_code=0, wait_signaled=True) if handle in self.exited else None

    def close(self, handle):
        self.closed.append(handle)

    def end(self, pid):
        self.exited.add((pid, self.live.pop(pid)))


class TrackerTests(unittest.TestCase):
    def tracker(self):
        api=Observer()
        return api,OwnedJobTracker(api.owner,_observer=api)

    def test_positive_all_retained_terminal_and_handles_only(self):
        api,t=self.tracker();self.assertFalse(t.observe()['complete'])
        api.live[102]=12;api.total=2;t.observe()
        api.end(102);t.observe();api.end(101)
        report=t.settle(timeout=0)
        self.assertTrue(report['complete']);self.assertEqual(len(report['records']),2)
        self.assertEqual(api.closed,[])
        t.close();self.assertCountEqual(api.closed,[(101,11),(102,12)])
        t.close();self.assertEqual(len(api.closed),2)
        self.assertEqual(api.owner.handle,901);self.assertEqual(api.owner.job.handle,902)
        self.assertFalse(report['termination_api_called'])

    def test_missed_short_lived_child_refuses_empty_job(self):
        api,t=self.tracker();t.observe();api.total=2;api.end(101)
        report=t.settle(timeout=0)
        self.assertTrue(report['job_empty']);self.assertTrue(report['all_retained_exited'])
        self.assertFalse(report['total_matches_retained_identities']);self.assertFalse(report['complete']);t.close()

    def test_pid_reuse_retains_two_creation_identities(self):
        api,t=self.tracker();t.observe();api.end(101)
        api.live[101]=44;api.total=2;t.observe();api.end(101)
        self.assertTrue(t.settle(timeout=0)['complete'])
        self.assertEqual([r['creation_filetime'] for r in t.report()['records']],[11,44]);t.close()

    def test_foreign_or_unresolved_member_sticky_failure(self):
        api,t=self.tracker();api.reject=True;t.observe();api.reject=False;t.observe();api.end(101)
        report=t.settle(timeout=0);self.assertFalse(report['complete']);self.assertTrue(report['errors']);t.close()
        self.assertEqual(len(api.closed),2)

    def test_same_live_identity_reuses_retained_handle(self):
        api,t=self.tracker();t.observe();t.observe()
        self.assertEqual(api.opened,[(101,11)]);t.close()

    def test_closed_and_changed_owner_refused(self):
        api,t=self.tracker();t.observe();t.close()
        with self.assertRaisesRegex(RuntimeError,'closed'):t.observe()
        api,t=self.tracker();api.owner.job.handle=999
        with self.assertRaisesRegex(RuntimeError,'changed'):t.observe()
        t.close()

    def test_invalid_bounds_and_timeout(self):
        api,t=self.tracker()
        for options in [dict(timeout=True),dict(timeout=61),dict(timeout=float('nan')),dict(poll=0)]:
            with self.subTest(options=options),self.assertRaises(ValueError):t.settle(**options)
        self.assertTrue(t.settle(timeout=0)['settle_timeout']);t.close()

    def test_job_terminated_or_unstable_not_complete(self):
        api,t=self.tracker();t.observe();api.end(101)
        original=api.accounting
        api.accounting=lambda job:dict(original(job),terminated=1)
        self.assertFalse(t.settle(timeout=0)['complete']);t.close()


if __name__=='__main__':unittest.main()
