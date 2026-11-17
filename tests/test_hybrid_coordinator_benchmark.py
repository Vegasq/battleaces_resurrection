"""Authored/synthetic harness controls; no original DLLs or live services."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

from server import admission, dedicated_server as ds, protocol as p, public_protocol as q, tls_transport as tls
from server.profiles import ProfileStore
from server.worker_client import SimulationWorker
from tests.test_command_scheduling_experiment import schema
from tests.test_bot_catalog import catalog_fixture
from tests.test_large_army_benchmark import configured
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools import benchmark_hybrid_coordinator as b


class MemoryTrace:
    def __init__(self):
        self.started = time.perf_counter()
        self.rows = []

    def now(self):
        return (time.perf_counter()-self.started)*1000

    def emit(self, event, **fields):
        row = dict(event=event, at_ms=self.now(), **fields)
        self.rows.append(row)
        return row


class Writer:
    def __init__(self):
        self.written = []
        self.transport = SimpleNamespace(abort=lambda: None)

    def write(self, data): self.written.append(data)
    async def drain(self): await asyncio.sleep(0)
    def close(self): pass
    async def wait_closed(self): pass


class DelayControls(unittest.IsolatedAsyncioTestCase):
    async def test_downlink_delay_is_independent_not_an_extra_rtt_per_frame(self):
        trace, reader = MemoryTrace(), asyncio.StreamReader()
        peer = b.Peer(reader, Writer(), trace, 'fixture', 475, [0])
        peer.count, peer.slot, peer.match = 2, 0, 'a'*32
        began = time.perf_counter()
        try:
            for frame in range(12):
                reader.feed_data(p.encode(q.FRAME, q.frame(frame, {0: b'authored0', 1: b'authored1'})))
                await asyncio.sleep(.01)
            received = [await asyncio.wait_for(peer.frames.get(), 1) for _ in range(12)]
            self.assertEqual([frame for frame, _ in received], list(range(12)))
            self.assertLess(time.perf_counter()-began, 1.0)  # Serial475/2ms holds would take2.85s.
            waits = [r for r in trace.rows if r['event'] == 'delivery_hold']
            self.assertEqual(len(waits), 12)
            self.assertTrue(all(r['requested_ms'] == 237.5 for r in waits))
        finally:
            await peer.close()

    async def test_uplink_queued_batches_keep_sequence_and_do_not_block_producer(self):
        trace, writer = MemoryTrace(), Writer()
        peer = b.Peer(asyncio.StreamReader(), writer, trace, 'fixture', 130, [20, -20, 0])
        peer.slot, peer.match = 0, 'a'*32
        try:
            began = time.perf_counter()
            for _ in range(10):
                await peer.batch(b'authored-command')
            self.assertLess(time.perf_counter()-began, .04)
            await asyncio.wait_for(peer.tx_queue.join(), 1)
            sent = [r['sequence'] for r in trace.rows if r['event'] == 'client_command_sent']
            self.assertEqual(sent, list(range(1, 11)))
            self.assertEqual(len(writer.written), 10)
            self.assertEqual([r['sequence'] for r in trace.rows if r['event'] == 'client_command_created'], sent)
        finally:
            await peer.close()

    async def test_control_notifications_survive_ack_wait(self):
        peer = b.Peer(asyncio.StreamReader(), Writer(), MemoryTrace(), 'fixture', 0, [0])
        try:
            await peer.queue.put((q.STATE, b'offered-before-ack'))
            await peer.queue.put((44, b'ack'))
            self.assertEqual(await peer.receive(44), b'ack')
            self.assertEqual(await peer.receive(q.STATE), b'offered-before-ack')
        finally:
            await peer.close()


class MeasurementsTests(unittest.TestCase):
    def test_jitter_trace_is_reproducible_and_does_not_reorder(self):
        left = b.Delivery(130, [20, -20, 0], None, '', '')
        right = b.Delivery(130, [20, -20, 0], None, '', '')
        times = [0, 10, 20, 30, 40, 50]
        first = [left.schedule(t) for t in times]
        self.assertEqual(first, [right.schedule(t) for t in times])
        self.assertEqual([row[0] for row in first], sorted(row[0] for row in first))
        self.assertGreater(first[1][2], 0)
        for rtt, jitter in ((500, [0]), (130, []), (130, [float('nan')])):
            with self.assertRaises(ValueError): b.Delivery(rtt, jitter, None, '', '')

    def test_episode_gaps_are_not_removed_from_continuous_cadence(self):
        regular = [dict(at_ms=50*i) for i in range(101)]
        self.assertTrue(b.publication_stats(regular)['cadence_pass'])
        interrupted = regular[:50] + [dict(at_ms=r['at_ms']+1000) for r in regular[50:]]
        result = b.publication_stats(interrupted)
        self.assertFalse(result['cadence_pass'])
        self.assertEqual(result['gaps_ms']['above_100ms'], 1)
        self.assertFalse(b.publication_stats(regular, 0, 6000)['cadence_pass'])
        self.assertFalse(b.publication_stats([dict(at_ms=r['at_ms']+1000) for r in regular], 0, 6000)['cadence_pass'])

    def test_active_load_excludes_setup_dead_units_and_episode_gaps(self):
        episode = SimpleNamespace(room=SimpleNamespace(match_id='m'), active_started=100,
                                  ended=500, driver=SimpleNamespace(scripted=(0, 1)))
        rows = [dict(event='worker_frame', match='m', at_ms=t, unit_counts={'0': count, '1': count}, game_complete=False)
                for t, count in ((0, 100), (100, 100), (200, 10), (400, 100))]
        intervals = b.active_intervals(rows, episode, 50, 600, 100, .8)
        self.assertEqual(intervals, [(100, 200), (400, 500)])
        self.assertAlmostEqual(b.overlap_seconds({0: intervals, 1: [(150, 450)]}), .1)
        rows[-1]['game_complete'] = True
        self.assertEqual(b.active_intervals(rows, episode, 50, 600, 100, .8), [(100, 200)])
        for row in rows: row['moving_units'] = {'0': 100, '1': 0}
        self.assertEqual(b.active_intervals(rows, episode, 50, 600, 100, .8, 0), [])
        rows[1]['moving_units']['1'] = 10
        self.assertEqual(b.active_intervals(rows, episode, 50, 600, 100, .8, 0), [(100, 200)])
        self.assertEqual(b.active_intervals(rows, episode, 50, 600, 100, .8, .5), [])

    def rows(self):
        identity = dict(match='m', slot=0, sequence=2)
        rows = [dict(event='client_command_created', at_ms=0, body_sha256='same', **identity),
                dict(event='client_command_sent', at_ms=10, **identity),
                dict(event='command_batch_accepted', at_ms=12, body_sha256='same', **identity),
                dict(event='command_frame_sealed', at_ms=50, match='m', frame=5, batches={0: [2]}),
                dict(event='worker_frame', at_ms=59, match='m', frame=5, step_rpc_ms=8, ai_rpc_ms=1, observer_ms=.5, input_sha256='input'),
                dict(event='frame_queued', at_ms=60, match='m', frame=5, frame_work_ms=15, frame_payload_sha256='payload'),
                dict(event='command_batch_committed', at_ms=61, frame=5, body_sha256='same', **identity),
                dict(event='client_frame_received', at_ms=62, match='m', slot=0, frame=5, payload_sha256='payload', input_sha256='input'),
                dict(event='client_frame_delivered', at_ms=110, match='m', slot=0, frame=5)]
        return rows

    def test_latency_attribution_uses_one_clock_and_separates_injected_wait(self):
        result = b.measurements(self.rows(), {'m': 0}, {0: ['m']})
        times = result['command_timings_ms']
        self.assertEqual(times['injected_uplink_ms']['p50'], 10)
        self.assertEqual(times['sent_to_accepted_ms']['p50'], 2)
        self.assertEqual(times['accepted_to_sealed_ms']['p50'], 38)
        self.assertEqual(times['created_to_delivered_ms']['p50'], 110)
        self.assertEqual(times['coordinator_outside_worker_ms']['p50'], 5.5)
        self.assertEqual(result['unmatched_committed_commands'], [])

    def test_corruption_and_clock_order_cannot_be_hidden_by_clipping(self):
        for index, field, value in ((2, 'body_sha256', 'changed'), (7, 'payload_sha256', 'wrong'),
                                    (7, 'input_sha256', 'different-native-inputs'), (3, 'batches', {0: [7]}), (1, 'at_ms', 13)):
            rows = self.rows(); rows[index][field] = value
            with self.assertRaises(ValueError): b.measurements(rows, {'m': 0}, {0: ['m']})
        rows = self.rows()[:-1]
        self.assertEqual(b.measurements(rows, {'m': 0}, {0: ['m']})['unmatched_committed_commands'], [('m', 0, 2)])

    def test_full_conservation_rejects_lost_stages_duplicates_and_impossible_residual(self):
        for index in (0, 1, 2, 6):
            rows = self.rows(); del rows[index]
            result = b.measurements(rows, {'m': 0}, {0: ['m']})
            self.assertFalse(result['conservation']['complete'])
            self.assertEqual(result['unmatched_committed_commands'], [('m', 0, 2)])
        for index in (0, 1, 2, 6):
            rows = self.rows(); rows.append(dict(rows[index]))
            with self.assertRaisesRegex(ValueError, 'duplicate command'):
                b.measurements(rows, {'m': 0}, {0: ['m']})
        rows = self.rows(); rows[5]['frame_work_ms'] = 3
        with self.assertRaisesRegex(ValueError, 'timing exceeds'):
            b.measurements(rows, {'m': 0}, {0: ['m']})

    def test_trace_persistence_is_outside_measured_loop_and_identity_is_reproducible(self):
        with tempfile.TemporaryDirectory(prefix='ba-trace-control-') as temporary:
            output = Path(temporary)
            trace = b.Trace(output)
            trace.emit('authored_test', value=1)
            self.assertEqual((output/'events.jsonl').stat().st_size, 0)
            self.assertIn('authored_test', trace.emit_ms)
            trace.close()
            self.assertEqual(json.loads((output/'events.jsonl').read_text())['value'], 1)
        self.assertEqual(b.benchmark_token(1, 'seat0'), b.benchmark_token(1, 'seat0'))
        self.assertNotEqual(b.benchmark_token(1, 'seat0'), b.benchmark_token(1, 'seat1'))
        self.assertRegex(b.benchmark_token(1, 'seat0'), r'^ba1_[A-Za-z0-9_-]{43}$')

    def test_pair_audit_exposes_intent_frame_and_state_differences(self):
        rows = self.rows()
        rows[4].update(input_sha256='input', state_sha256='state')
        rows.append(dict(event='episode_prepared', match='m', lane=0, episode=0, bootstrap_sha256='bootstrap'))
        report = dict(passed=True, native_qualified=True, source_unchanged=True, asset_manifest_sha256='fixture',
                      source_bootstrap_sha256='fixture', source_journal_report_sha256='fixture', source_at_start={},
                      duration_seconds=5, matches=1, rtt_ms=0, jitter_trace_ms=[0], activity='movement', ai=False)
        with tempfile.TemporaryDirectory(prefix='ba-pair-control-') as temporary:
            output = Path(temporary)
            raw = ''.join(json.dumps(row)+'\n' for row in rows).encode()
            (output/'events.jsonl').write_bytes(raw)
            (output/'benchmark.json').write_text(json.dumps(report | dict(events_sha256=b.digest(raw))))
            self.assertTrue(b.compare_runs(report, rows, output)['exact_pair'])
            changed = copy.deepcopy(rows)
            changed[4]['state_sha256'] = 'different'
            result = b.compare_runs(report, changed, output)
            self.assertFalse(result['exact_pair'])
            self.assertFalse(result['differences']['input_and_observable_state']['equal'])
            changed = copy.deepcopy(rows); changed[6]['frame'] = 6
            self.assertFalse(b.compare_runs(report, changed, output)['differences']['applied_command_frames']['equal'])
            (output/'events.jsonl').write_bytes(raw+b'\n')
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                b.compare_runs(report, rows, output)

    def test_linux_stat_preserves_kernel_pid_domain_and_reuse_identity(self):
        fields = ['S'] + ['0']*23
        fields[11], fields[12], fields[19], fields[21] = '10', '4', '12345', '9'
        self.assertEqual(b.proc_stat('17 (name with spaces) '+' '.join(fields)),
                         dict(cpu_ticks=14, start_ticks=12345, rss_pages=9))


class SyntheticTLSControl(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = b.ROOT/'local'/('hybrid-benchmark-tls-control-'+uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.folder)

    @classmethod
    def tearDownClass(cls): remove_test_pki(cls.folder)

    async def test_real_tls_public_protocol_with_explicit_synthetic_worker_never_qualifies_native(self):
        with tempfile.TemporaryDirectory(prefix='ba-authored-coordinator-') as temporary:
            output = Path(temporary)
            template, _, spec = configured(load='small')
            schema(output)
            template.descriptors_path = output
            (output/'bot-catalog.json').write_text(json.dumps(catalog_fixture()), encoding='utf-8')
            catalog = b.BotCatalog(output)
            trace = b.Trace(output)
            args = SimpleNamespace(output=output, assets=output, matches=2, ai=False, rtt_ms=0, jitter=[0])
            experiment = b.Experiment(args, trace, template, spec, None)
            async def factory(data, bots=None):
                self.assertIsNone(bots)
                native = await SimulationWorker.create(data, working_directory=output, _test_backend=True)
                wrapped = b.ObservedWorker(native, trace, spec)
                experiment.workers.append(wrapped)
                return wrapped
            experiment.server = ds.DedicatedServer(template, ProfileStore(output/'profiles', template),
                sim_factory=factory, audit=trace.emit, data_dir=output, audit_state=False,
                bot_catalog=catalog, ai_factory=factory,
                tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']),
                admission=admission.AdmissionController(None, rc_open=True), experimental_command_scheduling=True)
            experiment.port = (await experiment.server.start('127.0.0.1', 0))[1]
            experiment.client_tls = tls.load_client_context(self.pki['ca'], 'localhost')
            try:
                episodes = [await asyncio.wait_for(experiment.prepare(lane, 0), 10) for lane in range(2)]
                await asyncio.wait_for(asyncio.gather(*(experiment.load(episode) for episode in episodes)), 10)
                async with asyncio.timeout(3):
                    while any(episode.room.frame < 4 for episode in episodes): await asyncio.sleep(.02)
                self.assertEqual(len({episode.room.match_id for episode in episodes}), 2)
                self.assertEqual(len({worker.pid for worker in experiment.workers}), 2)
                for episode in episodes:
                    self.assertTrue(episode.room.command_scheduling)
                    self.assertEqual(set(episode.room.peers), {0, 1})
                    self.assertTrue(all(peer.applied >= 0 for peer in episode.peers))
                    self.assertTrue(episode.room.sim._test_backend)
                    await episode.room.sim.stop_requests()
                    await episode.room.finish('bounded benchmark episode teardown', aborted=True)
            finally:
                await experiment.close()
                trace.stream.close()
            self.assertTrue(all(worker.process.poll() == 0 for worker in experiment.workers))
            self.assertFalse((output/'benchmark.json').exists())  # No native acceptance receipt from fixture control.


if __name__ == '__main__': unittest.main()
