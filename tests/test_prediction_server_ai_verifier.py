"""Pure authored verifier controls. No processes, native DLLs, or network."""
import copy
import argparse
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from server import protocol, public_protocol as public
from server.game_data import encode_frame, encode_identity, encode_player_input
from server.protobuf_wire import field_bytes as b, field_uint as u
from tools import verify_prediction_server_ai as verify


MATCH = 'a' * 32


def plan():
    return dict(schema=1, native_executed=False, scope=verify.SCOPE, mode=1, human_slots=[0], bot_slots=[1],
                expected_matches=1, solo_ai_host='server', human_movement_exercised=False,
                full_feature_accepted=False, surrender_frame=600, rtt_ms=475, timeout=210,
                profile='nativestest_pm_0123456789_0', output='owned')


def fixture(count=31):
    identities = (encode_identity(1, 'Human'), encode_identity(2, 'Bot', ai_profile_id=7))
    bootstrap = b(1, u(36, 1) + b''.join(b(2, u(1, slot) + u(4, slot) + b(2, identity))
                                       for slot, identity in enumerate(identities)))
    joins = [b(3, u(1, slot) + b(2, b'authored deck')) for slot in (0, 1)]
    journal, raw, bot = [], [], []
    for frame in range(count):
        actions = {slot: [joins[slot]] if frame == 0 else [b(5, b'')] if slot == 1 and frame == 3 else []
                   for slot in (0, 1)}
        inputs = {slot: encode_player_input(identity, actions[slot]) for slot, identity in enumerate(identities)}
        journal.append(encode_frame(frame, inputs))
        raw.append(public.frame(frame, inputs))
        bot.append(inputs[1])
    return bootstrap, journal, raw, bot


def replay_fixture():
    frames, ai = verify.bind_frames(*fixture())
    rows, authority, states = [], [], {}
    for frame in range(len(frames)):
        states[frame] = verify.digest(str(frame).encode())
        rows.append(dict(schema=1, event='confirmed_native_state', world=1, frame=frame,
                         parsed_state_sha256=states[frame], confirmed_frontier=frame,
                         corrections=int(frame >= 3), corrections_delta=int(frame == 3),
                         replayed_frames_total=2 * int(frame >= 3), replayed_frames_delta=2 * int(frame == 3),
                         tick_ms=1000 + frame))
        authority.append(dict(schema=1, world=1, match=MATCH, frame=frame, tick_ms=900 + frame,
                              canonical_sha256=frames[frame]['input_sha256'], wire_sha256=frames[frame]['wire_sha256']))
    return frames, ai, rows, authority, states


class PreparationTests(unittest.TestCase):
    def test_template_catalog_preflight_uses_real_match_identities_without_native(self):
        from client_patch.prediction_worker.commands import CanonicalRoster
        from server.bot_catalog import BotCatalog
        from tests.synthetic import template
        from tests.test_bot_catalog import catalog_fixture
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'bot-catalog.json').write_text(json.dumps(catalog_fixture()))
            selected = template()
            raw, proof = verify.bootstrap_preflight(selected, BotCatalog(directory, template=selected))
        roster = CanonicalRoster.from_game_data(raw)
        self.assertFalse(proof['native_executed'])
        self.assertGreater(proof['bot_profile'], 0)
        self.assertEqual(proof['identity_sha256'], [verify.digest(value) for value in roster.identities])

    def test_default_cli_only_prepares_and_never_enters_runner(self):
        args = ['--output', 'owned', '--assets', 'assets', '--python', 'python', '--heap-helper', 'heap',
                '--cooperative', 'cooperative', '--helper-build-receipt', 'receipt',
                '--expected-helper-sha256', 'a' * 64, '--expected-gameassembly-sha256', 'b' * 64]
        with mock.patch.object(verify, 'prepare', return_value=plan()) as prepare, \
             mock.patch.object(verify, 'run_prepared') as run, mock.patch('sys.stdout', new=io.StringIO()):
            self.assertEqual(verify.main(args), 0)
        run.assert_not_called()
        observed = prepare.call_args.args[0]
        self.assertEqual((observed.rtt_ms, observed.surrender_frame, observed.timeout), (475, 600, 210))

    def test_run_requires_frozen_inputs_and_rejects_runtime_overrides_before_launch(self):
        with mock.patch.object(verify, 'run_prepared') as run:
            for extra in (['--game', 'other'], ['--timeout', '120'], ['--rtt-ms', '130'], ['--assets', 'other'],
                          ['--human-move'],['--visual-correction']):
                with self.subTest(extra=extra), self.assertRaisesRegex(AssertionError, 'frozen'):
                    verify.main(['--run-prepared', 'owned', *extra])
        run.assert_not_called()

    def test_plan_refuses_mode_roster_fallback_and_unbounded_scope(self):
        verify.validate_plan(plan())
        for changes in ({'mode': 2}, {'mode': True}, {'bot_slots': []}, {'human_slots': [0, 1]},
                        {'solo_ai_host': 'local'}, {'expected_matches': 2}, {'human_movement_exercised': True},
                        {'native_executed': True}, {'rtt_ms': float('nan')}, {'surrender_frame': 99999}):
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                verify.validate_plan(plan() | changes)

    def test_context_and_custom_gameplay_diagnostics_are_not_enabled(self):
        inputs = dict(files={name: dict(path=name) for name in ('python', 'heap_helper', 'cooperative')},
                      worker_module_root='root')
        command = verify.command_extra(plan(), inputs, Path('run'))
        self.assertIn('-prediction-server-ai-observe', command)
        self.assertIn('-public-queue-smoke-mode=1', command)
        self.assertIn('-dedicated-surrender-frame=600', command)
        self.assertFalse(any(value.startswith(('-prediction-movement-smoke', '-prediction-mobile',
                                              '-community-match-host-smoke', '-community-match-guest-smoke'))
                             for value in command))

    def test_human_move_requires_its_typed_scope_and_concede600_without_custom_flags(self):
        selected = plan() | dict(human_move=True, scope=verify.MOVE_SCOPE)
        verify.validate_plan(selected)
        inputs = dict(files={name: dict(path=name) for name in ('python', 'heap_helper', 'cooperative')},
                      worker_module_root='root')
        base = verify.command_extra(plan(), inputs, Path('run'))
        command = verify.command_extra(selected, inputs, Path('run'))
        self.assertEqual(command, base + ['-prediction-server-ai-move-smoke'])
        self.assertFalse(selected['human_movement_exercised'])  # Preparation is not runtime proof.
        for changes in ({'scope': verify.SCOPE}, {'human_move': 1}, {'surrender_frame': 500}):
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                verify.validate_plan(selected | changes)

    def test_visual_correction_adds_only_the_human_runtime_flag(self):
        selected=plan()|dict(human_move=True,scope=verify.MOVE_SCOPE)
        inputs=dict(files={name:dict(path=name)for name in ('python','heap_helper','cooperative')},worker_module_root='root')
        base=verify.command_extra(selected,inputs,Path('run'))
        actual=verify.command_extra(selected|dict(visual_correction=True),inputs,Path('run'))
        self.assertEqual(actual,base+['-prediction-visual-correction'])
        self.assertEqual(verify.command_extra(selected|dict(visual_correction=False),inputs,Path('run')),base)
        self.assertFalse(any('visual-observe'in flag or 'presentation-stages'in flag for flag in actual))

    def test_visual_option_is_typed_and_rejects_startup_before_resource_access(self):
        for value in (0,1,None,'true',[],{}):
            with self.subTest(value=value),mock.patch.object(verify.owned,'owned_paths')as paths:
                with self.assertRaisesRegex(AssertionError,'Boolean'):
                    verify.prepare(argparse.Namespace(human_move=True,visual_correction=value))
                paths.assert_not_called()
        with mock.patch.object(verify.owned,'owned_paths')as paths:
            with self.assertRaisesRegex(AssertionError,'human Move scope'):
                verify.prepare(argparse.Namespace(human_move=False,visual_correction=True))
            paths.assert_not_called()
        for changes in ({'visual_correction':1},{'visual_correction':True}):
            with self.subTest(changes=changes),self.assertRaises(AssertionError):verify.validate_plan(plan()|changes)

    def test_visual_helper_requires_join_and_flag_without_observation_flags(self):
        join=b'OfflinePredictionVisualJoin\0';flag='-prediction-visual-correction'.encode('utf-16-le')
        verify.visual_helper(True,join+flag)
        verify.visual_helper(False,b'')
        for data in (join,flag,b''):
            with self.subTest(data=data),self.assertRaisesRegex(AssertionError,'visual join or correction flag'):
                verify.visual_helper(True,data)

    def test_visual_bundle_binds_worker_server_and_human_launcher_source_closure(self):
        from tools.build_windows_packages import PREDICTION_CLIENT
        with tempfile.TemporaryDirectory()as directory:
            package=Path(directory);root=package/'program/app'
            names=tuple(name for name in PREDICTION_CLIENT if name.endswith('.py'))
            sources={}
            manifest=dict(schema=1,product='client',files={})
            def publish_manifest():
                (package/'package-manifest.json').write_text(json.dumps(manifest))
            def pin(name):
                file=root/name
                manifest['files']['program/app/'+name]=dict(bytes=file.stat().st_size,sha256=verify.sha(file))
                publish_manifest()
            for name in names:
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('# authored '+name)
                sources[name]=verify.sha(file)
                pin(name)
            # The frozen loopback authority has more server modules than the
            # private worker package. Do not require unshipped authority files.
            self.assertNotIn('server/dedicated_server.py',names)
            sources['server/dedicated_server.py']='a'*64
            inputs=dict(worker_package=str(package),worker_module_root=str(root),source_sha256=sources)
            verify.packaged_source_closure(inputs,True)
            for name in ('server/native_simulation.py','client_patch/prediction_worker/commands.py',
                         'tools/prediction_client.py','client_patch/transport/launcher.py'):
                file=root/name;before=file.read_bytes();file.write_bytes(before+b'changed')
                pin(name)
                with self.subTest(name=name),self.assertRaisesRegex(AssertionError,'worker/source differs'):
                    verify.packaged_source_closure(inputs,True)
                file.write_bytes(before);pin(name)
            with self.assertRaisesRegex(AssertionError,'source pins missing'):
                verify.packaged_source_closure(dict(inputs,source_sha256={names[0]:sources[names[0]]}),True)
            # A coherent manifest cannot conceal a required missing dependency.
            missing='client_patch/prediction_worker/commands.py'
            (root/missing).unlink();del manifest['files']['program/app/'+missing];publish_manifest()
            with self.assertRaisesRegex(AssertionError,'module inventory differs'):
                verify.packaged_source_closure(inputs,True)

    def test_visual_prepare_freezes_outer_flag_without_enabling_custom_visual_fixture(self):
        from server.ai_rules import SUPPORTED_AI_SHA256
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);output=root/'output';output.mkdir();assets=root/'assets';assets.mkdir()
            for name in ('aiprogram.dll','bot-catalog.json'):(assets/name).write_bytes(b'authored')
            args=argparse.Namespace(game=root/'game',output=output,assets=assets,rtt_ms=475,surrender_frame=600,
                timeout=210,human_move=True,visual_correction=True)
            inputs=dict(files={'helper':{'path':'helper'}},profiles=['nativestest_pm_0123456789_0'],worker_package=None)
            helper=(verify.OBSERVER_MARKER+verify.MOVE_MARKER+b'OfflinePredictionVisualJoin\0'+
                ''.join(('-prediction-server-ai-observe','-prediction-server-ai-move-smoke',
                         '-prediction-visual-correction')).encode('utf-16-le'))
            with mock.patch.object(verify.owned,'owned_paths',return_value=(args.game,output)), \
                    mock.patch.object(verify.owned,'prepare',return_value=inputs)as nested, \
                    mock.patch('server.assets.verify_assets'),mock.patch('server.ai_rules.RuleBook')as rules, \
                    mock.patch('server.game_data.GameTemplate.load'),mock.patch('server.bot_catalog.BotCatalog'), \
                    mock.patch.object(verify,'bootstrap_preflight',return_value=(b'bootstrap',{})), \
                    mock.patch.object(verify,'read',return_value=helper), \
                    mock.patch.object(verify,'sha',side_effect=lambda path:SUPPORTED_AI_SHA256 if Path(path).name=='aiprogram.dll'else'a'*64):
                rules.return_value.files={}
                prepared=verify.prepare(args)
            self.assertIs(prepared['visual_correction'],True)
            self.assertIs(json.loads((output/'invocation.json').read_text())['visual_correction'],True)
            self.assertIs(nested.call_args.args[0].visual_correction,False)
            self.assertIs(args.visual_correction,True)


class PublicPacketTests(unittest.TestCase):
    def assignment(self):
        return public.assignment(1, MATCH, 1, 0, 1, 6, tuple(range(100, 108)))

    def test_fragmented_assignment_and_public64_keep_actual_raw_body_and_identity(self):
        _, _, raw, _ = fixture(1)
        parser = verify.PublicPackets()
        stream = protocol.encode(public.MATCH, self.assignment()) + protocol.encode(public.FRAME, raw[0])
        received = []
        for byte in stream:
            received.extend(parser.feed(7, bytes([byte]), 100))
        self.assertEqual(received, raw)
        self.assertEqual(parser.frames, [dict(identity=7, match=MATCH, frame=0,
                                             payload_sha256=verify.digest(raw[0]), received_tick_ms=100)])

    def test_unowned_or_duplicate_frame_and_wrong_seat_assignment_reject(self):
        _, _, raw, _ = fixture(1)
        parser = verify.PublicPackets()
        with self.assertRaises(AssertionError):
            parser.feed(7, protocol.encode(public.FRAME, raw[0]), 0)
        parser = verify.PublicPackets()
        parser.feed(7, protocol.encode(public.MATCH, self.assignment()), 0)
        parser.feed(7, protocol.encode(public.FRAME, raw[0]), 0)
        with self.assertRaises(AssertionError):
            parser.feed(7, protocol.encode(public.FRAME, raw[0]), 1)
        wrong = public.assignment(1, MATCH, 1, 1, 3, 6, tuple(range(100, 108)))
        with self.assertRaises(AssertionError):
            verify.PublicPackets().feed(7, protocol.encode(public.MATCH, wrong), 0)

    def test_closed_raw_reader_rejects_truncation_instead_of_rewriting_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.bin'
            for raw in (b'\x01', struct.pack('<I', 2) + b'x', struct.pack('<I', 0)):
                path.write_bytes(raw)
                with self.subTest(raw=raw), self.assertRaises(AssertionError):
                    verify.records(path)
            path.write_bytes(struct.pack('<I', 2) + b'xy')
            self.assertEqual(verify.records(path), [b'xy'])


class CanonicalEvidenceTests(unittest.TestCase):
    def test_both_real_joins_once_and_exact_ai_native_bytes_bind_to_public64(self):
        frames, ai = verify.bind_frames(*fixture())
        self.assertEqual(ai, [3])
        self.assertEqual((frames[0]['human_actions'], frames[0]['bot_actions']), (1, 1))
        self.assertEqual(frames[3]['bot_actions'], 1)

    def test_forged_bot_bytes_wrong_raw_body_association_and_late_join_reject(self):
        for corruption in ('bot', 'raw', 'late_join'):
            bootstrap, journal, raw, bot = fixture()
            if corruption == 'bot':
                bot[3] = bot[4]
            elif corruption == 'raw':
                _, inputs = public.decode_frame(raw[3], 2)
                inputs[1] = bot[4]
                raw[3] = public.frame(3, inputs)
            else:
                identity = get_identity(bot[3])
                bot[3] = encode_player_input(identity, [b(3, u(1, 1) + b(2, b'deck'))])
                _, original = public.decode_frame(raw[0], 2)
                inputs = {0: encode_player_input(get_identity(original[0])), 1: bot[3]}
                journal[3], raw[3] = encode_frame(3, inputs), public.frame(3, inputs)
            with self.subTest(corruption=corruption), self.assertRaises(AssertionError):
                verify.bind_frames(bootstrap, journal, raw, bot)

    def test_replay_requires_real_ai_only_correction_and20_full_state_continuations(self):
        args = replay_fixture()
        proof = verify.ai_correction_evidence(*args, match=MATCH)
        self.assertEqual((proof['bot_action_frame'], proof['continuation_last_frame'], proof['matched_full_states']),
                         (3, 23, 31))
        for corruption in ('no_replay', 'no_correction', 'human_action', 'wrong_state', 'foreign_match', 'missing_tail'):
            frames, ai, rows, authority, states = copy.deepcopy(args)
            if corruption == 'no_replay':
                for row in rows:
                    row['replayed_frames_total'] = row['replayed_frames_delta'] = 0
            elif corruption == 'no_correction':
                for row in rows:
                    row['corrections'] = row['corrections_delta'] = 0
            elif corruption == 'human_action':
                frames[3]['human_actions'] = 1
            elif corruption == 'wrong_state':
                rows[20]['parsed_state_sha256'] = 'f' * 64
            elif corruption == 'foreign_match':
                authority[3]['match'] = 'b' * 32
            else:
                frames, rows, authority = frames[:20], rows[:20], authority[:20]
                states = {key: value for key, value in states.items() if key < 20}
            with self.subTest(corruption=corruption), self.assertRaises(AssertionError):
                verify.ai_correction_evidence(frames, ai, rows, authority, states, match=MATCH)

    def test_single_human_startup_and_original_fallback_deadline_are_required(self):
        events = [dict(event='public_queue_entered', mode=1, command_scheduling=True, profile='human',
                       wait_ms=30000, monotonic=0),
                  dict(event='public_match_offered', match=MATCH, mode=1, command_scheduling=True,
                       humans=['human'], fallback=True, monotonic=30),
                  dict(event='command_startup_waiting', match=MATCH, frame=0, ready_slots=[0]),
                  dict(event='command_startup_ready', match=MATCH, frame=0, slot=0, all_ready=True),
                  dict(event='command_startup_released', match=MATCH, frame=1, ready_slots=[0])]
        self.assertEqual(verify.startup_evidence(events, MATCH)['real_human_ready_slots'], [0])
        for corruption in ('fake_bot_ready', 'early_offer', 'ordinary_cohort', 'missing_ready'):
            wrong = copy.deepcopy(events)
            if corruption == 'fake_bot_ready':
                wrong[-1]['ready_slots'] = [0, 1]
            elif corruption == 'early_offer':
                wrong[1]['monotonic'] = 1
            elif corruption == 'ordinary_cohort':
                wrong[0]['command_scheduling'] = False
            else:
                wrong.pop(3)
            with self.subTest(corruption=corruption), self.assertRaises(AssertionError):
                verify.startup_evidence(wrong, MATCH)


class SubmittedBatchTests(unittest.TestCase):
    def test_retains_exact_immutable72_bytes_and_refuses_duplicate_or_gapped_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = verify.SubmittedBatches(Path(directory) / 'batches')
            body = fixture(1)[3][0]
            capture.record(MATCH, 0, 1, body, 1000)
            self.assertIs(capture.bodies[MATCH, 0, 1], body)
            self.assertEqual((capture.directory / capture.rows[0]['file']).read_bytes(), body)
            self.assertEqual(capture.rows[0]['body_sha256'], verify.digest(body))
            for sequence in (1, 3):
                with self.subTest(sequence=sequence), self.assertRaises(AssertionError):
                    capture.record(MATCH, 0, sequence, b'changed', 1001)
            self.assertEqual(len(capture.rows), 1)

    def test_refuses_bot_foreign_or_mutable_body_and_byte_budget_before_mutation(self):
        for slot, body in ((1, b'body'), (0, bytearray(b'body')), (0, b'x' * 65537)):
            capture = verify.SubmittedBatches()
            with self.subTest(slot=slot, size=len(body)), self.assertRaises(AssertionError):
                capture.record(MATCH, slot, 1, body, 1000)
            self.assertEqual(capture.bodies, {})
        capture = verify.SubmittedBatches()
        capture.total_bytes = 16 * 1024 * 1024
        with self.assertRaises(AssertionError):
            capture.record(MATCH, 0, 1, b'body', 1000)
        self.assertEqual(capture.rows, [])


class HumanMoveEvidenceTests(unittest.TestCase):
    def fixture(self):
        from tests.test_prediction_multiplayer_verifier import FeelEvidenceTests
        rows, args = FeelEvidenceTests().fixture(unit_type=1)
        args['bridge_frames'][0]['payload_sha256'] = 'd' * 64
        args['authority_rows'] = [dict(match=MATCH, world=7, frame=445, tick_ms=1225, wire_sha256='d' * 64)]
        return rows, args

    def test_original_move_reuses_actual67_72_canonical_phase_and_both_delivery_clocks(self):
        rows, args = self.fixture()
        proof = verify.human_move_evidence(rows, **args)
        self.assertTrue(proof['passed'])
        self.assertEqual(proof['command_to_visible_ms'], 30)
        self.assertEqual(proof['accepted65']['tick_ms'], 1225)
        self.assertEqual(proof['continuation_frames'], 20)

    def test_missing_actual72_wrong_body_sequence_and_late_pose_cannot_be_reconstructed(self):
        for corruption in ('missing72', 'body', 'sequence', 'late_pose', 'accepted65_hash', 'accepted65_clock'):
            rows, args = self.fixture()
            if corruption == 'missing72':
                args['raw_bodies'] = {}
            elif corruption == 'body':
                args['raw_bodies'][MATCH, 0, 2] += b'changed'
            elif corruption == 'sequence':
                args['raw_bodies'][MATCH, 0, 3] = args['raw_bodies'].pop((MATCH, 0, 2))
            elif corruption == 'late_pose':
                next(row for row in rows if row['event'] == 'transform' and row['tick_ms'] == 1130)['tick_ms'] = 1229
            elif corruption == 'accepted65_hash':
                args['authority_rows'][0]['wire_sha256'] = 'e' * 64
            else:
                args['authority_rows'][0]['tick_ms'] = 1219
            with self.subTest(corruption=corruption), self.assertRaises(AssertionError):
                verify.human_move_evidence(rows, **args)


def get_identity(body):
    from server.protobuf_wire import get_bytes
    return get_bytes(body, 1, required=True)
