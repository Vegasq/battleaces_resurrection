"""Authored source/transport controls, including explicitly synthetic workers."""
import asyncio
from collections import deque
import copy
import gzip
import json
from pathlib import Path
import struct
import tempfile
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from server import admission, dedicated_server as ds, tls_transport as tls
from server.bot_catalog import BotCatalog
from server.game_data import GameTemplate, decode_identity, encode_frame, encode_player_input
from server.worker_client import SimulationWorker
from tests.test_bot_catalog import catalog_fixture
from tests.test_command_scheduling_experiment import schema
from tests.test_large_army_benchmark import configured
from tests.test_hybrid_coordinator_benchmark import MemoryTrace
from tests.synthetic import template as synthetic_template
from tests.test_tls_transport import generate_test_pki, remove_test_pki
from tools import benchmark_buffered_coordinator as b


def fixture_source(folder):
    template, match, spec = configured(load='small')
    schema(folder)
    template.descriptors_path = folder
    driver = b.base.army.Workload(template, match, spec, 100, 100)
    joined, _ = driver.inputs(0)
    payloads = [encode_frame(0, joined)] + [encode_frame(frame, {slot: encode_player_input(identity)
        for slot, identity in match.identities_by_slot.items()}) for frame in range(1, 4)]
    rows = [dict(frame=frame, phase='setup' if frame == 0 else 'movement', input_sha256=b.digest(payload),
        state_sha256='authored-state', unit_counts={'0': 10, '1': 10}, moving_units={'0': 10, '1': 10},
        newly_damaged_units={'0': 0, '1': 0}, newly_lost_unit_resource_cost={'0': 0, '1': 0})
        for frame, payload in enumerate(payloads)]
    (folder/'bootstrap.pb.gz').write_bytes(gzip.compress(match.raw_game_data, mtime=0))
    journal = b''.join(struct.pack('<I', len(payload))+payload for payload in payloads)
    (folder/'frames.bin').write_bytes(journal)
    (folder/'frames.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    report = dict(passed=True, native_qualified=True, source_unchanged=True, workload=spec,
        source_at_start={'authored-fixture.py': 'a'*64}, source_at_finish={'authored-fixture.py': 'a'*64},
        bootstrap_sha256=b.digest(match.raw_game_data), input_journal_sha256=b.digest(journal), asset_manifest_sha256='authored-assets')
    (folder/'benchmark.json').write_text(json.dumps(report))
    return template, match, spec, payloads, rows, report


class SourceControls(unittest.TestCase):
    def test_short_source_preserves_exact_inputs_and_cannot_fill_five_minutes(self):
        with tempfile.TemporaryDirectory(prefix='ba-buffered-source-') as temporary:
            folder = Path(temporary)
            template, match, spec, payloads, _, _ = fixture_source(folder)
            source = b.ReplaySource(folder, 'movement', .1)
            source.attach_template(GameTemplate(source.raw, catalog_path=None, descriptors_path='unused'))
            self.assertEqual((source.first, source.last), (1, 2))
            for frame in range(3): self.assertEqual(encode_frame(frame, source.bodies(frame)), payloads[frame])
            with self.assertRaisesRegex(ValueError, 'too short'):
                b.ReplaySource(folder, 'movement', 300)

    def test_corrupt_payload_and_unqualified_population_or_motion_are_refused(self):
        with tempfile.TemporaryDirectory(prefix='ba-buffered-source-') as temporary:
            folder = Path(temporary)
            _, _, _, _, rows, _ = fixture_source(folder)
            for field, value in (('unit_counts', {'0': 9, '1': 10}), ('moving_units', {'0': 0, '1': 10})):
                changed = copy.deepcopy(rows)
                for row in changed[1:]: row[field] = value
                (folder/'frames.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in changed))
                with self.assertRaisesRegex(ValueError, 'target population|activity'):
                    b.ReplaySource(folder, 'movement', .1)
            (folder/'frames.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            (folder/'frames.bin').write_bytes((folder/'frames.bin').read_bytes()+b'extra')
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                b.ReplaySource(folder, 'movement', .1)

    def test_source_hash_maps_are_required_and_cannot_disagree_or_be_malformed(self):
        with tempfile.TemporaryDirectory(prefix='ba-buffered-source-bind-') as temporary:
            folder = Path(temporary)
            _, _, _, _, _, pristine = fixture_source(folder)
            for mutate in (lambda r: r.pop('source_at_start'), lambda r: r.update(source_at_start={}),
                           lambda r: r.update(source_at_finish={'authored-fixture.py': 'b'*64}),
                           lambda r: r.update(source_at_start={'file': 'not-a-sha'}, source_at_finish={'file': 'not-a-sha'})):
                report = copy.deepcopy(pristine); mutate(report)
                (folder/'benchmark.json').write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, 'source hash maps'):
                    b.ReplaySource(folder, 'movement', .1)

    def test_legacy_descriptive_fields_come_from_bound_bootstrap(self):
        with tempfile.TemporaryDirectory(prefix='ba-buffered-old-journal-') as temporary:
            folder = Path(temporary)
            _, _, spec, _, rows, report = fixture_source(folder)
            for name in ('scripted_armies', 'decks', 'player_count', 'mode'): report['workload'].pop(name)
            for row in rows: row.pop('newly_lost_unit_resource_cost')
            (folder/'frames.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            (folder/'benchmark.json').write_text(json.dumps(report))
            source = b.ReplaySource(folder, 'movement', .1)
            self.assertEqual(source.humans, (0, 1))
            self.assertEqual(source.spec['player_count'], 2)
            self.assertFalse(source.load_evidence[0]['resource_loss_counter_available'])

    def test_public_episode_source_binds_actual_window_bootstrap_and_population(self):
        with tempfile.TemporaryDirectory(prefix='ba-buffered-public-source-') as temporary:
            folder = Path(temporary)
            _, match, spec, _, rows, report = fixture_source(folder)
            identity = 'a'*32
            nested = folder/'matches'/identity; nested.mkdir(parents=True)
            for name in ('bootstrap.pb.gz', 'frames.bin'): (folder/name).replace(nested/name)
            events = [dict(event='measurement_started', at_ms=50, end_ms=150),
                dict(event='episode_prepared', match=identity, bootstrap_sha256=report['bootstrap_sha256'],
                     humans=[0, 1], bots={}, effective_decks=spec['decks'])]
            events += [dict(row, event='worker_frame', match=identity, at_ms=row['frame']*50) for row in rows]
            raw = ''.join(json.dumps(row)+'\n' for row in events).encode()
            (folder/'events.jsonl').write_bytes(raw)
            report.pop('workload')
            report.update(source_workload=spec, activity='movement', measurement_start_ms=50,
                episodes=[dict(lane=0, number=0, match=identity, active_started_ms=50)], events_sha256=b.digest(raw))
            (folder/'benchmark.json').write_text(json.dumps(report))
            source = b.ReplaySource(folder, 'movement', .1)
            self.assertEqual(source.raw, match.raw_game_data)
            self.assertEqual(source.load_evidence[0]['target_population_frames'], 2)
            (folder/'events.jsonl').write_bytes(raw+b'\n')
            with self.assertRaisesRegex(ValueError, 'trace digest differs'):
                b.ReplaySource(folder, 'movement', .1)

    def test_source_template_never_substitutes_different_native_roster(self):
        template, match, spec = configured(load='small')
        frozen = b.SourceTemplate(match.raw_game_data, catalog_path=None, descriptors_path='unused')
        frozen.benchmark_seed, frozen.expected_raw = spec['seed'], match.raw_game_data
        roster = [dict(slot=slot, name=f'Benchmark {slot}') for slot in range(2)]
        self.assertEqual(frozen.build_match(roster, match.decks_by_slot).raw_game_data, match.raw_game_data)
        roster[0]['name'] = 'Different Name'
        with self.assertRaisesRegex(ValueError, 'changed source bootstrap'):
            frozen.build_match(roster, match.decks_by_slot)

    def test_inherited_preparer_limits_are_refused_before_starting_a_worker(self):
        template, match, _ = configured(load='small')
        decks = dict(match.decks_by_slot)
        decks[1] = (2, *decks[1][1:])
        mixed = template.build_match([dict(slot=s, name=f'Human{s}') for s in range(2)], decks, seed=7)
        source = b.ReplaySource.__new__(b.ReplaySource); source.humans = (0, 1)
        with self.assertRaisesRegex(ValueError, 'heterogeneous human decks'):
            source.attach_template(GameTemplate(mixed.raw_game_data, catalog_path=None, descriptors_path='unused'))
        team, match, _ = configured(mode=2, load='small')
        mixed = team.build_match([dict(slot=s, name=f'Player{s}', ai_profile_id=17 if s >= 2 else 0)
                                  for s in range(4)], match.decks_by_slot, seed=7)
        with self.assertRaisesRegex(ValueError, 'human cohort is unsupported'):
            source.attach_template(GameTemplate(mixed.raw_game_data, catalog_path=None, descriptors_path='unused'))

    def test_frozen_ai_selection_must_belong_to_the_actual_public_catalog(self):
        with tempfile.TemporaryDirectory(prefix='ba-buffered-bots-') as temporary:
            folder = Path(temporary)
            (folder/'bot-catalog.json').write_text(json.dumps(catalog_fixture()))
            template = synthetic_template()
            catalog = BotCatalog(folder, template=template)
            choice = catalog.choose(1, difficulty='normal', randbelow=lambda n: 0)
            roster = [dict(slot=0, name='Human'), dict(slot=1, name=choice.name, ai_profile_id=choice.profile)]
            decks = {0: template.default_decks[0], 1: choice.deck.units}
            match = template.build_match(roster, decks, seed=7, bot_choices={1: choice})
            frozen = b.SourceTemplate(match.raw_game_data, catalog_path=None, descriptors_path='unused')
            frozen.benchmark_seed, frozen.expected_raw = 7, match.raw_game_data
            source = SimpleNamespace(roster={slot: decode_identity(identity) for slot, identity in match.identities_by_slot.items()})
            choices = b.source_bot_choices(catalog, frozen, source)
            self.assertEqual(choices[1], choice)
            self.assertEqual(frozen.build_match(roster, decks, bot_choices=choices).raw_game_data, match.raw_game_data)
            source.roster[1]['name'] = 'Unknown worker-only bot'
            with self.assertRaisesRegex(ValueError, 'not a public catalog'):
                b.source_bot_choices(catalog, frozen, source)


class EligibilityControls(unittest.IsolatedAsyncioTestCase):
    async def test_future_entity_waits_for_normal_validation_but_due_invalid_input_fails(self):
        available = False
        events = []
        def validate(slot, body):
            self.assertEqual((slot, body), (0, b'input'))
            events.append(('validate', available))
            if not available: raise ValueError('authored entity not created')
            return body
        room = SimpleNamespace(state='running', frame=1, match_id='fixture',
                               validation=SimpleNamespace(validate_player_input=validate))
        peer = SimpleNamespace(slot=0, applied=0, tasks=[], frames=asyncio.Queue())
        trace = MemoryTrace()
        clock_ms = 0
        trace.now = lambda: clock_ms
        waiting, retry = asyncio.Event(), asyncio.Event()
        async def poll_wait(delay):
            self.assertGreater(delay, 0)
            events.append(('wait', available))
            waiting.set()
            await retry.wait()
        # Gate the diagnostic poll itself. Wall-clock sleep duration does not
        # establish that validation waited for the entity on every event loop.
        # Replacing this module's reference leaves the test event loop intact.
        with patch.object(b, 'asyncio', SimpleNamespace(sleep=poll_wait)):
            pending = asyncio.create_task(b.wait_for_input_eligibility(room, [peer], 3, {0: b'input'}, trace))
            try:
                await asyncio.wait_for(waiting.wait(), 1)
                self.assertEqual(events, [('validate', False), ('wait', False)])
                self.assertFalse(pending.done())
                self.assertEqual(trace.rows, [])
                available, clock_ms = True, 20
                events.append(('create_entity', True))
                retry.set()
                await asyncio.wait_for(pending, 1)
                self.assertEqual(events, [('validate', False), ('wait', False),
                                          ('create_entity', True), ('validate', True)])
                self.assertEqual(len(trace.rows), 1)
                self.assertTrue(trace.rows[0]['ownership_eligibility_wait'])
                self.assertEqual(trace.rows[0]['elapsed_ms'], 20)

                available, room.frame = False, 3
                with self.assertRaisesRegex(ValueError, 'invalid when its native frame is due'):
                    await b.wait_for_input_eligibility(room, [peer], 3, {0: b'input'}, trace)
                self.assertEqual(events[-2:], [('validate', True), ('validate', False)])
                self.assertEqual(sum(event[0] == 'wait' for event in events), 1)
                self.assertEqual(len(trace.rows), 1)
            finally:
                if not pending.done(): pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


class BufferedTLSControl(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = b.ROOT/'local'/('buffered-benchmark-tls-control-'+uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.folder)

    @classmethod
    def tearDownClass(cls): remove_test_pki(cls.folder)

    async def test_real_tls_numbered_public_replay_with_explicit_synthetic_worker(self):
        with tempfile.TemporaryDirectory(prefix='ba-buffered-tls-') as temporary:
            folder = Path(temporary)
            template, match, spec, payloads, _, _ = fixture_source(folder)
            # Record exact authored synthetic responses; this is never a native qualification.
            recorder = await SimulationWorker.create(match.raw_game_data, working_directory=folder, _test_backend=True)
            expected = []
            try:
                for frame, payload in enumerate(payloads):
                    result = await recorder.process_frame(payload, dt_ms=50)
                    expected.append(dict(frame=frame, input_sha256=b.digest(payload), state_sha256=b.base.army.state_digest(result.state)))
            finally: await recorder.close()
            source = b.ReplaySource.__new__(b.ReplaySource)
            source.raw, source.spec, source.inputs, source.expected = match.raw_game_data, spec, payloads, expected
            source.humans, source.first, source.last = (0, 1), 1, 3
            schema(folder)
            frozen = b.SourceTemplate(match.raw_game_data, catalog_path=None, descriptors_path=folder)
            frozen.benchmark_seed, frozen.expected_raw = spec['seed'], match.raw_game_data
            source.attach_template(frozen)
            (folder/'bot-catalog.json').write_text(json.dumps(catalog_fixture()))
            catalog = BotCatalog(folder)
            trace = b.base.Trace(folder)
            args = SimpleNamespace(output=folder, assets=folder, matches=1, ai=False, rtt_ms=0, jitter=[0])
            experiment = b.ReplayExperiment(args, trace, frozen, source, None)
            worker_start_failures = deque(maxlen=4)
            async def factory(data, bots=None):
                self.assertIsNone(bots)
                try:
                    native = await SimulationWorker.create(data, working_directory=folder, _test_backend=True)
                except Exception as error:
                    worker_start_failures.append(dict(error_type=type(error).__name__, error=str(error)[:1024]))
                    raise
                wrapped = b.ReplayWorker(native, trace, spec, source)
                experiment.workers.append(wrapped)
                return wrapped
            experiment.server = ds.DedicatedServer(frozen, b.base.ProfileStore(folder/'profiles', frozen),
                sim_factory=factory, ai_factory=factory, bot_catalog=catalog, input_window=b.WINDOW, adaptive_input_window=False,
                audit=trace.emit, data_dir=folder, audit_state=False,
                tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']),
                admission=admission.AdmissionController(None, rc_open=True), experimental_command_scheduling=True)
            experiment.port = (await experiment.server.start('127.0.0.1', 0))[1]
            experiment.client_tls = tls.load_client_context(self.pki['ca'], 'localhost')
            failure = None
            try:
                episode = await asyncio.wait_for(experiment.prepare(0, 0), 10)
                await experiment.load(episode)
                await asyncio.wait_for(experiment.replay(episode), 5)
                self.assertFalse(episode.room.command_scheduling)
            except BaseException as error:
                failure = error
                raise
            finally:
                await experiment.close()
                trace.close()
                if failure is not None:
                    # EventRows can only be read after trace.close(); retain a
                    # bounded diagnostic before TemporaryDirectory removes it.
                    try:
                        relevant = deque(maxlen=20)
                        fields = ('event', 'at_ms', 'room', 'match', 'slot', 'worker_pid',
                                  'error_kind', 'error', 'reason', 'errno', 'winerror')
                        for row in trace.rows:
                            event = row.get('event', '')
                            if ('error' in event or 'fail' in event or event in
                                    ('match_preparing', 'worker_started', 'worker_released', 'match_aborted')):
                                relevant.append({key: value[:1024] if isinstance(value, str) else value
                                                 for key in fields if (value := row.get(key)) is not None})
                        failure.add_note('synthetic TLS replay diagnostics: '+json.dumps(dict(
                            events=list(relevant), worker_start_failures=list(worker_start_failures)), sort_keys=True))
                    except Exception as diagnostic_error:
                        failure.add_note('synthetic TLS replay diagnostics unavailable: '+type(diagnostic_error).__name__)
            result = b.qualify_replay(trace.rows, experiment.episodes, source)
            self.assertTrue(result['complete'])
            self.assertEqual(result['participant_inputs'], 8)
            retained = list(trace.rows)
            missing = copy.deepcopy(retained)
            del missing[next(i for i, row in enumerate(missing) if row['event'] == 'buffered_input_accepted')]
            with self.assertRaisesRegex(ValueError, 'conservation'):
                b.qualify_replay(missing, experiment.episodes, source)
            for event, field in (('worker_frame', 'input_sha256'), ('worker_frame', 'state_sha256'),
                                 ('client_frame_received', 'input_sha256')):
                altered = copy.deepcopy(retained)
                next(row for row in altered if row['event'] == event)[field] = 'changed'
                with self.assertRaisesRegex(ValueError, 'bytes or state differ'):
                    b.qualify_replay(altered, experiment.episodes, source)
            duplicated = retained+[next(row for row in retained if row['event'] == 'buffered_input_created')]
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                b.qualify_replay(duplicated, experiment.episodes, source)
            self.assertTrue(all(worker.process.poll() == 0 for worker in experiment.workers))
            self.assertTrue(all(worker._test_backend for worker in experiment.workers))
            self.assertFalse(any(row['event'] == 'command_scheduling_negotiated' for row in trace.rows))
            self.assertNotIn('legacy-buffered', (folder/'benchmark.json').read_text())


if __name__ == '__main__': unittest.main()
