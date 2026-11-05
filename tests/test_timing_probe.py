import asyncio
import copy
import threading
import unittest

from tools.timing_probe import AsyncStatusPublisher, TimingObservations, review_timing


class Clock:
    def __init__(self):
        self.now = 1_000_000_000

    def __call__(self):
        return self.now


class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_threaded_status_returns_original_result_and_closes(self):
        probe=TimingObservations();writer=AsyncStatusPublisher(probe)
        main_thread=threading.get_ident()
        try:
            actual=await writer.call(lambda:(threading.get_ident(),37))
            self.assertNotEqual(actual[0],main_thread)
            self.assertEqual(actual[1],37)
            self.assertEqual([row['kind'] for row in probe.rows],['status'])
        finally:writer.close()
        self.assertFalse(any(thread.is_alive() for thread in writer.executor._threads))
        with self.assertRaisesRegex(RuntimeError,'closed'):await writer.call(lambda:None)

    async def test_cancelled_status_drains_thread_and_does_not_block_loop(self):
        probe=TimingObservations();writer=AsyncStatusPublisher(probe)
        started=threading.Event();release=threading.Event();finished=threading.Event()
        def held():
            started.set()
            if not release.wait(3):raise TimeoutError('test gate not released')
            finished.set()
        task=asyncio.create_task(writer.call(held))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            with self.assertRaisesRegex(RuntimeError,'already writing'):await writer.call(lambda:None)
            with self.assertRaisesRegex(RuntimeError,'before I/O drained'):writer.close()
            task.cancel();await asyncio.sleep(0);await asyncio.sleep(0)
            task.cancel();await asyncio.sleep(0);await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertFalse(finished.is_set())
            release.set()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(finished.is_set())
            self.assertIsNone(writer.pending)
            self.assertEqual(len(probe.rows),1)
        finally:
            release.set()
            await asyncio.gather(task,return_exceptions=True)
            writer.close()
        self.assertFalse(any(thread.is_alive() for thread in writer.executor._threads))

    async def test_thread_write_error_survives_and_window_retained(self):
        probe=TimingObservations();writer=AsyncStatusPublisher(probe)
        error=OSError('original status write failed')
        def failed():raise error
        try:
            with self.assertRaises(OSError) as caught:await writer.call(failed)
            self.assertIs(caught.exception,error)
            self.assertIsNone(writer.pending)
            self.assertEqual(len(probe.rows),1)
        finally:writer.close()

    def test_original_result_error_and_bounded_retention(self):
        clock = Clock()
        probe = TimingObservations(capacity=1, clock=clock)
        sentinel = object()
        error = RuntimeError('original write failure')
        def callback(result):
            clock.now += 250_000_000
            return result
        self.assertIs(probe.call('status', callback, sentinel), sentinel)
        def failed():
            clock.now += 300_000_000
            raise error
        with self.assertRaises(RuntimeError) as caught:
            probe.call('status', failed)
        self.assertIs(caught.exception, error)
        report = probe.report()
        self.assertEqual(len(report['rows']), 1)
        self.assertEqual(report['dropped'], 1)
        self.assertEqual(report['rows'][0]['finished_ns']-report['rows'][0]['started_ns'], 250_000_000)

    def test_failed_callback_window_is_retained(self):
        clock = Clock()
        probe = TimingObservations(clock=clock)
        def failed():
            clock.now += 123_000_000
            raise OSError('write refused')
        with self.assertRaises(OSError):
            probe.call('audit', failed, metadata={'event':'frame_queued','match':'a','frame':0})
        row = probe.report()['rows'][0]
        self.assertEqual(row['finished_ns']-row['started_ns'],123_000_000)
        self.assertEqual(row['event'],'frame_queued')

    async def test_loop_delay_excludes_intended_sleep_and_cancellation_propagates(self):
        clock = Clock()
        probe = TimingObservations(clock=clock)
        calls = 0
        async def sleep(period):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise asyncio.CancelledError()
            clock.now += round(period*1_000_000_000)+300_000_000
        with self.assertRaises(asyncio.CancelledError):
            await probe.loop_probe(sleep=sleep)
        self.assertEqual(len(probe.rows),2)
        self.assertTrue(all(row['finished_ns']-row['started_ns']==300_000_000 for row in probe.rows))

    def fixture(self):
        probe = TimingObservations()
        for frame, start in ((0,1_000_000_000),(1,1_500_000_000)):
            probe.record('audit',start,start+1_000_000,event='frame_queued',match='a',frame=frame)
        probe.record('status',1_100_000_000,1_400_000_000)
        probe.record('loop_delay',1_050_000_000,1_450_000_000)
        events=[dict(event='frame_queued',match='a',frame=frame,perf_counter_ns=start+500_000,
                     frame_work_ms=5.,worker_ms=3.,snapshot_ms=0.,interval_ms=45.)
                for frame,start in ((0,1_000_000_000),(1,1_500_000_000))]
        return probe.report(),events

    def test_overlap_windows_are_not_added_or_called_exclusive_causes(self):
        raw, events = self.fixture()
        result = review_timing(raw,events)
        self.assertEqual(result['frame_audits'],2)
        gap = result['largest_gaps'][0]
        self.assertEqual(gap['gap_ms'],500)
        self.assertEqual(gap['outside_current_interval_and_work_ms'],450)
        overlaps = {row['kind']:row['overlap_ms'] for row in gap['overlaps'] if row['kind']!='audit'}
        self.assertEqual(overlaps,{'status':300.,'loop_delay':400.})

    def test_incomplete_or_mismatched_evidence_refused(self):
        raw,events=self.fixture()
        bad=copy.deepcopy(raw);bad['dropped']=1
        with self.assertRaisesRegex(ValueError,'incomplete'):review_timing(bad,events)
        bad=copy.deepcopy(raw);bad['rows']=[r for r in bad['rows'] if r['kind']!='status']
        with self.assertRaisesRegex(ValueError,'category'):review_timing(bad,events)
        bad=copy.deepcopy(events);bad[1]['perf_counter_ns']+=2_000_000
        with self.assertRaisesRegex(ValueError,'outside'):review_timing(raw,bad)
        bad=copy.deepcopy(raw);bad['rows'].append(copy.deepcopy(bad['rows'][0]))
        with self.assertRaisesRegex(ValueError,'coverage'):review_timing(bad,events)
        with self.assertRaisesRegex(ValueError,'coverage'):review_timing(raw,events[:1])


if __name__=='__main__':
    unittest.main()
