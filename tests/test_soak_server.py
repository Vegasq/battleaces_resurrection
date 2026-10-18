"""Evidence bounds and resource/timing measurements for the opt-in soak runner."""
import asyncio
from collections import Counter
import io
import os
from pathlib import Path
import unittest
from unittest import mock
from contextlib import redirect_stderr
import copy
import threading

from tools import soak_server as s


class SoakEvidenceTests(unittest.TestCase):
    def test_gate_rejects_short_single_room_slow_stalled_leaking_or_unreaped_runs(self):
        good = dict(all_workers_reaped=True,source_unchanged=True,asset_manifest_sha256='a',asset_manifest_sha256_at_finish='a',
            elapsed_seconds=28801,rounds=21,matches=42,created_workers=126,connections_created=4,
            concurrent_room_seconds={'2':28000},baseline_idle={'handles':100,'private_bytes':10000000},
            final_idle={'handles':102,'private_bytes':11000000},
            timings={'publish_interval_ms':{'count':10000,'mean_ms':50,'max_ms':90},'worker_ms':{'count':10000,'over50ms':1}})
        self.assertTrue(all(s.assess(good,seconds=28800,rooms=2,minimum_rounds=21).values()))
        changes = [dict(elapsed_seconds=28799),dict(rounds=20),dict(matches=43),dict(created_workers=125),
            dict(connections_created=5),dict(all_workers_reaped=False),dict(source_unchanged=False),
            dict(asset_manifest_sha256_at_finish='b'),dict(concurrent_room_seconds={'2':100}),dict(baseline_idle=None),
            dict(final_idle={'handles':117,'private_bytes':11000000}),dict(final_idle={'handles':101,'private_bytes':80000000})]
        for fields in changes:
            sample = copy.deepcopy(good); sample.update(fields)
            with self.subTest(fields=fields): self.assertFalse(all(s.assess(sample,seconds=28800,rooms=2,minimum_rounds=21).values()))
        for key,field,value in [('publish_interval_ms','mean_ms',52),('publish_interval_ms','max_ms',2000),
                                ('publish_interval_ms','count',0),('worker_ms','over50ms',101)]:
            sample = copy.deepcopy(good); sample['timings'][key][field] = value
            self.assertFalse(all(s.assess(sample,seconds=28800,rooms=2,minimum_rounds=21).values()))

    def test_histogram_stays_bounded_preserves_outliers_and_does_not_understate_percentiles(self):
        values = s.Distribution()
        for _ in range(95): values.add(.2)
        for _ in range(4): values.add(50.1)
        values.add(6000)
        summary = values.summary()
        self.assertEqual(len(values.bins),5002)
        self.assertEqual(summary['count'],100)
        self.assertEqual(summary['p95_ms_upper'],1)
        self.assertEqual(summary['p99_ms_upper'],51)
        self.assertEqual(summary['max_ms'],6000)
        self.assertEqual(summary['over50ms'],5)
        for value in (float('inf'),float('nan'),-1):
            with self.assertRaises(AssertionError): values.add(value)

    def test_cadence_measures_complete_publication_intervals_separately_per_room(self):
        runner = s.Soak.__new__(s.Soak)
        runner.events = Counter(); runner.audit = mock.Mock()
        runner.last_published = {}; runner.running_rooms = {'one','two'}
        runner.concurrent_seconds = Counter(); runner.active_started = 0
        runner.diagnostics = {'audit_ms':s.Distribution()}
        runner.timings = {key:s.Distribution() for key in ('publish_interval_ms','interval_ms')}
        # Existing interval excludes native work and cannot establish20Hz alone.
        with mock.patch.object(s.time,'perf_counter',side_effect=[1,1.01,1.08,1.06]):
            runner.event('frame_queued',match='one',frame=0,interval_ms=30)
            runner.event('frame_queued',match='two',frame=0,interval_ms=30)
            runner.event('frame_queued',match='one',frame=1,interval_ms=30)
            runner.event('frame_queued',match='two',frame=1,interval_ms=30)
        self.assertAlmostEqual(runner.timings['publish_interval_ms'].summary()['mean_ms'],65)
        self.assertEqual(runner.timings['interval_ms'].summary()['mean_ms'],30)
        runner.event('match_completed',match='one')
        self.assertNotIn('one',runner.last_published)

    def test_cli_keeps_short_pilots_distinct_from_eight_hour_request(self):
        args = s.arguments(['--assets','local/assets','--output','local/test'])
        self.assertEqual((args.seconds,args.rooms,args.minimum_rounds),(28800,2,20))
        for field,value in (('--seconds','0'),('--seconds','36000'),('--rooms','1'),('--minimum-rounds','2'),('--match-frames','0')):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                s.arguments(['--assets','local/assets','--output','local/test',field,value])

    def test_natural_result_tail_never_tries_to_build_at_a_destroyed_base(self):
        runner = s.Soak.__new__(s.Soak)
        runner.args = mock.Mock(match_frames=3600)
        room = mock.Mock(result={'complete':True})
        room.sim.last_state = {'entities':[]}
        room.match.identities_by_slot = {0:b'authored one',1:b'authored two'}
        room.match.decks_by_slot = {0:(100,),1:(101,)}
        combat = {key:[set(),set()] for key in ('produced','moved','damaged')}
        combat.update(positions=[{},{}],peak_units=[0,0],build_commands=[0,0],attack_commands=[0,0])
        bodies = runner.inputs(room,140,combat)
        self.assertEqual(bodies,[s.encode_player_input(room.match.identities_by_slot[slot],[]) for slot in (0,1)])

    @unittest.skipUnless(os.name == 'nt','Windows process metrics')
    def test_actual_owned_process_metrics_are_readable_and_identity_is_stable(self):
        sampler = s.ProcessSampler()
        first, second = sampler.sample(os.getpid()),sampler.sample(os.getpid())
        self.assertEqual(first['created_filetime'],second['created_filetime'])
        for key in ('handles','private_bytes','working_set_bytes','created_filetime'):
            self.assertGreater(first[key],0)
        self.assertGreaterEqual(second['cpu_seconds'],first['cpu_seconds'])
        self.assertEqual(first['handles'],second['handles'])


class SoakWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_disk_failure_during_final_observer_drain_cannot_be_a_pass(self):
        runner = s.Soak.__new__(s.Soak)
        runner.args = mock.Mock(seconds=0,minimum_rounds=1,rooms=2,assets=Path('authored-assets'))
        runner.output = Path('authored-output'); runner.started = s.time.monotonic()
        runner.template = mock.Mock(); runner.event = mock.Mock(); runner.factory = mock.Mock()
        runner.evidence = s.EvidenceWrites(); runner.peers = []; runner.active_workers = set()
        runner.rounds = runner.created = runner.reaped = runner.finished = 0; runner.baseline = None
        runner.events = Counter(); runner.sampler = mock.Mock()
        runner.samples = mock.Mock(); runner.matches = mock.Mock(); runner.audit = mock.Mock()
        runner.report = dict(passed=False,source_sha256={},asset_manifest_sha256=s.digest(b'authored manifest'))
        runner.status = mock.Mock(return_value={}); runner.source_hashes = mock.Mock(return_value={})
        runner.pair = mock.AsyncMock(return_value=object())
        entered = asyncio.Event()
        async def monitor():
            entered.set()
            try: await asyncio.Future()
            except asyncio.CancelledError: raise OSError('authored final write failure')
        runner.heartbeat = monitor
        async def probe(): await asyncio.Future()
        runner.loop_probe = probe
        async def match(*_): await entered.wait()
        runner.match = match
        server = mock.Mock(rooms={},retired={})
        server.start = mock.AsyncMock(return_value=('127.0.0.1',12345))
        server.close = mock.AsyncMock()
        with mock.patch.object(s.dedicated_server,'DedicatedServer',return_value=server), \
             mock.patch.object(s,'ProfileStore'), mock.patch.object(s,'verify_assets'), \
             mock.patch.object(s.Path,'read_bytes',return_value=b'authored manifest'), \
             mock.patch.object(s,'write_json'), mock.patch.object(s,'assess',return_value={'other_checks':True}), \
             mock.patch('builtins.print'):
            await runner.run()
        self.assertFalse(runner.report['passed'])
        self.assertFalse(runner.report['eight_hour_gate'])
        self.assertEqual(runner.report['state'],'failed')
        self.assertEqual(runner.report['error'],'OSError: authored final write failure')
        server.close.assert_awaited_once()
        runner.audit.close.assert_called_once()
        self.assertFalse(runner.evidence.lock.locked())

    async def test_slow_write_allows_frames_and_cancellation_drains_before_next_write(self):
        evidence = s.EvidenceWrites()
        entered, release = threading.Event(),threading.Event()
        order = []
        def slow_write():
            order.append('first starts'); entered.set()
            if not release.wait(5): raise TimeoutError('Test failed to release evidence write')
            order.append('first ends')
        runner = s.Soak.__new__(s.Soak)
        runner.events = Counter(); runner.last_published = {}
        runner.started = s.time.monotonic(); runner.worst_gaps = []; runner.evidence = evidence
        runner.timings = {'publish_interval_ms':s.Distribution()}
        first = asyncio.create_task(evidence.call('blocked sample',slow_write))
        second = None
        try:
            async with asyncio.timeout(2):
                while not entered.is_set(): await asyncio.sleep(.005)
            for frame in range(5):
                runner.event('frame_queued',match='authored',frame=frame)
                await asyncio.sleep(.01)
            self.assertFalse(first.done())
            self.assertEqual(runner.events['frame_queued'],5)
            self.assertEqual(runner.timings['publish_interval_ms'].count,4)
            first.cancel(); await asyncio.sleep(0)
            second = asyncio.create_task(evidence.call('later status',order.append,'second'))
            first.cancel(); await asyncio.sleep(.01)
            self.assertFalse(first.done())
            self.assertFalse(second.done())
            self.assertEqual(order,['first starts'])
            release.set()
            async with asyncio.timeout(2):
                with self.assertRaises(asyncio.CancelledError): await first
                await second
            self.assertEqual(order,['first starts','first ends','second'])
            self.assertEqual(evidence.io_ms.count,2)
            self.assertGreaterEqual(evidence.io_ms.maximum,50)
            self.assertIsNone(evidence.active)
        finally:
            release.set()
            await asyncio.gather(first,*([second] if second else []),return_exceptions=True)
            evidence.close()

    async def test_disk_error_is_reported_and_writer_does_not_keep_the_lock(self):
        evidence = s.EvidenceWrites()
        try:
            with self.assertRaisesRegex(OSError,'authored disk failure'):
                await evidence.call('bad sample',mock.Mock(side_effect=OSError('authored disk failure')))
            self.assertEqual(await evidence.call('next status',lambda:42),42)
            self.assertEqual(evidence.io_ms.count,2)
            self.assertFalse(evidence.lock.locked())
            self.assertIsNone(evidence.active)
        finally: evidence.close()

    async def test_evidence_timing_and_gap_details_have_fixed_retention(self):
        evidence = s.EvidenceWrites()
        runner = s.Soak.__new__(s.Soak)
        runner.events = Counter(); runner.last_published = {}; runner.evidence = evidence
        runner.started = s.time.monotonic(); runner.worst_gaps = []
        runner.timings = {'publish_interval_ms':s.Distribution()}
        try:
            for index in range(20): await evidence.call('sample',lambda:None)
            with mock.patch.object(s.time,'perf_counter',side_effect=[float(index) for index in range(20)]):
                for frame in range(20): runner.event('frame_queued',match='authored',frame=frame)
            self.assertEqual(len(evidence.slowest),8)
            self.assertEqual(len(runner.worst_gaps),8)
            self.assertEqual(runner.timings['publish_interval_ms'].count,19)
            self.assertEqual(runner.worst_gaps[0]['gap_ms'],1000)
        finally: evidence.close()

    async def test_heartbeat_records_failed_gap_before_failing_fast(self):
        evidence = s.EvidenceWrites()
        runner = s.Soak.__new__(s.Soak)
        runner.evidence = evidence; runner.output = mock.Mock()
        runner.output.__truediv__ = mock.Mock(return_value=mock.Mock(exists=lambda:False))
        runner.status = mock.Mock(return_value={}); runner.active_workers = set()
        runner.write_sample = mock.Mock()
        runner.diagnostics = {'snapshot_ms':s.Distribution()}
        runner.timings = {'publish_interval_ms':s.Distribution()}
        runner.timings['publish_interval_ms'].add(1001)
        try:
            with self.assertRaisesRegex(RuntimeError,'1000ms limit'): await runner.heartbeat()
            runner.write_sample.assert_called_once()
            self.assertEqual(evidence.io_ms.count,1)
        finally: evidence.close()

    async def test_failed_native_frame_never_enters_successful_input_journal(self):
        native = mock.Mock()
        native.process_frame = mock.AsyncMock(side_effect=[object(),RuntimeError('authored native error')])
        worker = s.ObservedWorker(native)
        await worker.process_frame(b'first')
        before = worker.journal.digest()
        with self.assertRaises(RuntimeError): await worker.process_frame(b'second')
        self.assertEqual(worker.frames,1)
        self.assertEqual(worker.journal.digest(),before)


if __name__ == '__main__': unittest.main()
