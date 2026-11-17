"""Authored/mocked compact Room verifier controls; no original native launch."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from server.command_scheduling import ArrivalScheduler
from server.game_data import InputValidation
from tests.synthetic import template
from tests.test_command_scheduling_experiment import schema
from tools import verify_compact_room as v


def state(frame=0xffffffff, records=None):
    return dict(frame=frame, viewer=31, local_alliance=0, canonical_fnv1a64='0'*16,
        raw_sha256='a'*64, byte_count=100, counts=dict(army=1, type=1, health=1, position=1, resources=0),
        resources={}, game_state=dict(complete=False, game_over_frame=-1, winning_alliance=0,
            army_conceded_flag=0, game_over_checksum=0),
        ownership=copy.deepcopy([dict(id=42, army=0, type=100)] if records is None else records))


class Controls(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.patch = mock.patch.object(v, 'ROOT', self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.args = SimpleNamespace(assets=self.root/'assets', library=self.root/'decoder.dll',
            library_sha256='a'*64, build_receipt=self.root/'receipt.json', build_receipt_sha256='b'*64,
            output=self.root/'local'/'new', timeout=300, wine=None, windows_python=None,
            prefix_template=None, cgroup_parent=None, tls_cert=None, tls_key=None, tls_ca=None)

    def test_native_arguments_fix_one_case_four_hundred_frames(self):
        with mock.patch.object(v.sys, 'platform', 'win32'):
            self.assertFalse(v.validate_args(self.args))
        self.assertEqual((self.args.play_frames, self.args.solo_team_only), (400, True))

    def test_explicit_wine_and_default_native_have_no_platform_fallback(self):
        with mock.patch.object(v.sys, 'platform', 'linux'), self.assertRaisesRegex(ValueError, 'no fallback'):
            v.validate_args(self.args)
        self.args.wine, self.args.windows_python, self.args.prefix_template = (self.root/name for name in ('wine', 'python.exe', 'prefix'))
        with mock.patch.object(v.sys, 'platform', 'linux'):
            self.assertTrue(v.validate_args(self.args))
        with mock.patch.object(v.sys, 'platform', 'win32'), self.assertRaisesRegex(ValueError, 'no fallback'):
            v.validate_args(self.args)

    def test_incomplete_wine_and_tls_refused(self):
        for name in ('wine', 'cgroup_parent', 'tls_cert', 'tls_key'):
            args = copy.copy(self.args); setattr(args, name, self.root/name)
            with self.subTest(name=name), mock.patch.object(v.sys, 'platform', 'win32'), self.assertRaises(ValueError):
                v.validate_args(args)

    def test_output_overlap_existing_and_nonfinite_timeout_refused(self):
        self.args.output.mkdir(parents=True)
        with mock.patch.object(v.sys, 'platform', 'win32'), self.assertRaisesRegex(ValueError, 'fresh'):
            v.validate_args(self.args)
        self.args.output = self.root/'local'/'other'
        self.args.assets = self.root/'local'
        with mock.patch.object(v.sys, 'platform', 'win32'), self.assertRaisesRegex(ValueError, 'separate'):
            v.validate_args(self.args)
        self.args.timeout = float('nan')
        with mock.patch.object(v.sys, 'platform', 'win32'), self.assertRaisesRegex(ValueError, 'timeout'):
            v.validate_args(self.args)

    def build_fixture(self):
        self.args.library.write_bytes(b'authored library fixture, never loaded')
        self.args.library_sha256 = v.flow.file_hash(self.args.library)
        sources = {'rust/snapshot-decoder/Cargo.toml': 'c'*64, 'rust/snapshot-decoder/src/lib.rs': 'd'*64}
        receipt = dict(schema=1, rust_sources=sources,
            build=dict(exit_code=0, argv=['cargo', 'build', '--locked']), toolchain=dict(cargo='fixture', rustc='fixture'),
            artifacts={'ba_snapshot_decoder.dll': dict(sha256=self.args.library_sha256, bytes=self.args.library.stat().st_size)})
        return sources, receipt

    def write_receipt(self, receipt):
        self.args.build_receipt.write_text(json.dumps(receipt), encoding='utf-8')
        self.args.build_receipt_sha256 = v.flow.file_hash(self.args.build_receipt)

    def test_build_receipt_binds_exact_sources_artifact_and_content(self):
        sources, receipt = self.build_fixture(); self.write_receipt(receipt)
        self.assertEqual(v.verify_build(self.args, sources)['rust_sources'], sources)
        self.args.library.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'artifact|library'):
            v.verify_build(self.args, sources)

    def test_receipt_hash_source_build_and_artifact_spoof_refused(self):
        sources, receipt = self.build_fixture()
        variants = []
        for key, value in (('rust_sources', {}), ('build', dict(exit_code=1, argv=['--locked'])), ('artifacts', {})):
            altered = copy.deepcopy(receipt); altered[key] = value; variants.append(altered)
        for altered in variants:
            self.write_receipt(altered)
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                v.verify_build(self.args, sources)
        self.write_receipt(receipt); self.args.build_receipt_sha256 = '0'*64
        with self.assertRaisesRegex(ValueError, 'hash'):
            v.verify_build(self.args, sources)

    def test_native_cleanup_requires_normal_exit_job_streams_and_threads(self):
        record = dict(backend='native-windows', exit_code=0, failure=None, stderr_thread_closed=True,
                      io_threads_closed=True, job_closed=True, streams_closed=True)
        v.require_native_cleanup(record)
        for key, value in (('exit_code', 1), ('exit_code', None), ('failure', 'forced'),
                           ('stderr_thread_closed', False), ('io_threads_closed', False),
                           ('job_closed', False), ('streams_closed', False)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'cleanup'):
                v.require_native_cleanup({**record, key: value})

    def test_wine_cleanup_reuses_existing_owned_checks(self):
        record = dict(backend_statistics={})
        with mock.patch.object(v.flow, 'require_cleanup') as check:
            v.require_native_cleanup(record)
        check.assert_called_once_with(record, natural=True)

    def test_backend_hook_keeps_legacy_wine_default(self):
        with mock.patch.object(v.flow, 'WineWorkerBackend', return_value='explicit') as backend:
            self.assertEqual(v.flow.Verification(self.args).make_backend(), 'explicit')
            backend.assert_called_once()
        self.assertIsNone(v.Verification(self.args).make_backend())


class Observations(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        directory = Path(self.folder.name); schema(directory)
        self.template = template(); self.template.descriptors_path = directory
        self.template.entity_abilities = {100: {7}}
        self.match = self.template.build_match([dict(slot=i, player_id=i+1, name='Player '+str(i)) for i in (0, 1)],
                                               self.template.default_decks, seed=17)
        self.native = SimpleNamespace(state_mode='ownership', state=mock.AsyncMock(return_value=state()),
            process_frame=mock.AsyncMock(return_value=SimpleNamespace(state=state(0))))
        self.worker = v.ObservedWorker(self.native)
        history = {42: (0, 100)}
        self.room = SimpleNamespace(sim=self.worker, command_scheduling=True, entity_history=history,
                                   template=self.template, match=self.match)
        self.room.validation = InputValidation(self.match, self.template, entity_lookup=history.get)
        self.room.command_scheduler = ArrivalScheduler(self.room.validation, (0,))
        self.worker.room = self.room

    async def test_initial_state_explicit_then_every_compact_step_and_history(self):
        initial = await self.worker.state(31, mode='ownership')
        self.native.state.assert_awaited_once_with(31, mode='ownership')
        result = await self.worker.process_frame(b'authored frame', dt_ms=50)
        self.worker.check_history()
        self.assertEqual((initial['frame'], result.state['frame'], len(self.worker.rows)), (0xffffffff, 0, 2))
        self.assertEqual(self.worker.history_checks, 2)

    async def test_full_or_summary_initial_queries_refused_before_native(self):
        for kwargs in ({'include_entities': True}, {'mode': 'full'}, {}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'explicit initial'):
                await self.worker.state(31, **kwargs)
        self.native.state.assert_not_awaited()

    async def test_full_step_output_missing_ownership_or_bad_frame_refused(self):
        await self.worker.state(31, mode='ownership')
        for altered in ({**state(0), 'frame': 7}, {key: value for key, value in state(0).items() if key != 'ownership'},
                        {**state(0), 'entities': []}):
            self.native.process_frame.return_value = SimpleNamespace(state=altered)
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                await self.worker.process_frame(b'frame')

    async def test_lost_history_and_disabled_validator_fail_before_next_native_step(self):
        await self.worker.state(31, mode='ownership')
        self.room.entity_history.clear()
        with self.assertRaisesRegex(ValueError, 'history'):
            await self.worker.process_frame(b'frame')
        self.native.process_frame.assert_not_awaited()
        self.room.entity_history[42] = (0, 100)
        self.room.validation.entity_lookup = None
        with self.assertRaisesRegex(ValueError, 'validation'):
            await self.worker.process_frame(b'frame')
        self.native.process_frame.assert_not_awaited()

    async def test_final_history_check_requires_normal_room_release(self):
        await self.worker.state(31, mode='ownership')
        self.room.sim, self.room.state = None, 'closed'
        self.worker.check_history(released=True)
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.worker.check_history()
        self.room.state = 'running'
        with self.assertRaisesRegex(ValueError, 'binding'):
            self.worker.check_history(released=True)

    async def test_death_retains_history_and_complete_owner_type_change_updates(self):
        await self.worker.state(31, mode='ownership')
        self.native.process_frame.return_value = SimpleNamespace(state=state(0, []))
        await self.worker.process_frame(b'frame0')
        self.worker.check_history()
        changed = state(1, [dict(id=42, army=1, type=100)])
        self.native.process_frame.return_value = SimpleNamespace(state=changed)
        await self.worker.process_frame(b'frame1')
        with self.assertRaisesRegex(ValueError, 'history'):
            self.worker.check_history()
        self.room.entity_history[42] = (1, 100)
        self.worker.check_history()
        changed['ownership'].clear()
        self.assertEqual(self.worker.rows[-1]['ownership'], [dict(id=42, army=1, type=100)])

    async def test_actual_authored_input_validation_accepts_owned_rejects_unknown(self):
        result = v.command_controls(self.room)
        self.assertTrue(result['owned_command_accepted'] and result['unknown_entity_refused'])
        self.room.validation.entity_lookup = None
        with self.assertRaisesRegex(ValueError, 'accepted unknown'):
            v.command_controls(self.room)

    async def test_factory_selects_explicit_compact_and_closes_failed_negotiation_later(self):
        args = SimpleNamespace(output=Path(self.folder.name), assets=Path(self.folder.name),
                               library=Path(self.folder.name)/'decoder.dll', library_sha256='a'*64)
        check = v.Verification(args); check.backend = None
        native = SimpleNamespace(_test_backend=False, state_mode='full', projection_version=1,
                                 close=mock.AsyncMock())
        with mock.patch.object(v, 'AISetup', return_value='original-ai-setup'), \
             mock.patch.object(v.SimulationWorker, 'create', new=mock.AsyncMock(return_value=native)) as create:
            with self.assertRaisesRegex(ValueError, 'negotiation'):
                await check.factory(b'GameData', {1: 2, 2: 3, 3: 4})
        options = create.call_args.kwargs
        self.assertEqual(options['state_mode'], 'ownership')
        self.assertEqual(options['snapshot_decoder_library'], args.library)
        self.assertEqual(options['snapshot_decoder_sha256'], args.library_sha256)
        self.assertEqual(len(check.workers), 1)
        await check.workers[0].close()
        native.close.assert_awaited_once()

    async def test_exercise_delegates_only_existing_solo_team(self):
        args = SimpleNamespace()
        check = v.Verification(args)
        worker = SimpleNamespace(check_history=mock.Mock(), rows=[{}]*402, frame=400, history_checks=402,
                                 state_mode='ownership', projection_version=1, decoder_info={'bound': True})
        async def solo(peer):
            check.workers.append(worker); check.cases.append({})
        check.connect = mock.AsyncMock(return_value='peer')
        check.solo_team = mock.AsyncMock(side_effect=solo)
        check.command_control_results = {'authored': True}
        self.assertEqual(await check.exercise(), (1, 0))
        check.solo_team.assert_awaited_once_with('peer')
        self.assertEqual(check.cases[0]['observed_steps'], 401)


if __name__ == '__main__':
    unittest.main()
