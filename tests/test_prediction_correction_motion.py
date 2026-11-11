"""Authored closed-record controls, without loading a simulation or game."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import prediction_correction_motion as motion


def authored_world(world=1, amount=1.89):
    match = str(world)*32
    binding = dict(world=world, match=match, entity=74, unit_type=1, army=0, incarnation=75)
    rows = []; publications = []
    def native(frame, x, end, revision=0, event='native_position', **extra):
        row = dict(world=world, frame=frame, position=motion.vec([x, 0, 0]), status='present',
                   event=event, record=len(rows), revision=revision, query_begin_us=end-50,
                   query_end_us=end, corrections=0, replayed_frames=0, **extra)
        rows.append(row)
        return row
    for frame in range(98, 105):
        row = native(frame, (frame-100)*.315, 100000+(frame-98)*1000)
        publications.append(dict(frame=frame, qpc_us=row['query_end_us']+200))
    old = rows[-1]
    before = dict(old, event='before_restore_cached_head', record=len(rows), revision=1,
                  cached_from_record=old['record'], first_divergent_frame=100)
    rows.append(before)
    after = native(104, old['position'][0]-amount, 106600, 1, 'after_replay_same_head')
    after['replayed_frames'] = 4
    for frame in range(105, 110):
        row = native(frame, after['position'][0]+(frame-104)*.315,
                     107000+(frame-105)*1000, 1)
        publications.append(dict(frame=frame, qpc_us=row['query_end_us']+200))
    pair = dict(before_record=before['record'], after_record=after['record'],
                first_divergent_frame=100, physical_head=104, revision=1, qualified=True, changed=True)
    action = b'original turn2'
    action_hash = hashlib.sha256(action).hexdigest()
    journal = [dict(frame=frame, players={0: [action] if frame == 103 else [], 1: []})
               for frame in range(100, 104)]
    workers = [dict(world=world, frame=frame, confirmed_frontier=103,
                    replayed_frames_delta=5 if frame == 100 else 0,
                    corrections=1, corrections_delta=1 if frame == 100 else 0, replayed_frames_total=5,
                    parsed_state_sha256=hashlib.sha256(str(frame).encode()).hexdigest())
               for frame in range(100, 104)]
    canonical = {str(r['frame']): r['parsed_state_sha256'] for r in workers}
    order = dict(ordinal=2, world=world, match=match, entity=74, unit_type=1, incarnation=75,
                 originalCtor=True, physicalUI=False, queueDelta=1, enqueue_sampled_us=100500,
                 origin=[0, 0, 0], target=[48, 0, 0])
    command = dict(ordinal=2, sequence=4, action_sha256=action_hash, assigned_frame=100,
                   canonical_frame=103, native67_tick_ms=100, native72_send_tick_ms=100,
                   original_order=order)
    # True interpolation observations: exact frame endpoints, with a large
    # peak-to-trough reversal during the first corrected output interval.
    endpoints = {r['frame']: r for r in rows if r['event'] == 'native_position'}
    endpoints[104] = old
    poses = []
    for frame, alpha, lag in [(102, .5, 100), (103, .5, 100), (104, 1, 100),
                              (105, .1, 100), (105, .9, 300), (105, 1, 500), (106, .5, 100)]:
        a, b = endpoints[frame-1]['position'], endpoints[frame]['position']
        position = motion.vec([x+(y-x)*alpha for x, y in zip(a, b)])
        publication = next(p for p in publications if p['frame'] == frame)
        poses.append(dict(event='transform', world=world, match=match, entity=74, unit_type=1,
            incarnation=75, source='UnityEngine.Transform.get_position', jobsJoined=True,
            sampled_us=publication['qpc_us']+lag, presented_frame=frame, completed_frame=frame,
            position=position))
    return dict(binding=binding, native=rows, episodes=[pair], publications=publications,
                poses=poses, workers=workers, canonical=canonical, journal=journal,
                command=command, next_enqueue_us=200000, minimum_backtrack=.75)


class CorrectionMotionTests(unittest.TestCase):
    def test_large_native_retime_contains_render_and_exact_endpoint_equation(self):
        result = motion.decompose_world(**authored_world())
        self.assertGreater(result['render_backtrack']['amount'], 1.5)
        self.assertTrue(result['attribution_passed'])
        self.assertFalse(result['renderer_amplification_observed'])
        correction = result['corrections'][0]
        self.assertAlmostEqual(correction['native_correction_magnitude'], 1.89, places=6)
        self.assertAlmostEqual(correction['ordinary_next_motion_magnitude'], .315, places=6)
        self.assertAlmostEqual(correction['published_endpoint_magnitude'], 1.575, places=6)
        self.assertEqual(correction['promotion']['frames'], [100, 101, 102, 103])
        self.assertIsNone(correction['promotion']['native65_timestamp_for_empty_frame'])
        summary = motion.summarize([result, motion.decompose_world(**authored_world(2, .63))],
                                   minimum_backtrack=.75)
        self.assertTrue(summary['passed'])
        self.assertTrue(summary['large_event_reproduced'])
        self.assertFalse(summary['full_feature_accepted'])

    def test_small_capture_is_not_large_event_qualification(self):
        rows = [motion.decompose_world(**authored_world(w, .63)) for w in (1, 2)]
        summary = motion.summarize(rows, minimum_backtrack=.75)
        self.assertTrue(summary['decomposition_complete'])
        self.assertFalse(summary['large_event_reproduced'])
        self.assertFalse(summary['passed'])

    def test_residual_not_canned_renderer_acceptance(self):
        data = authored_world(); data['poses'][4]['position'][1] = .05
        result = motion.decompose_world(**data)
        self.assertTrue(result['renderer_amplification_observed'])
        self.assertEqual(result['renderer_classification'], 'outside_published_native_segments')
        self.assertFalse(result['attribution_passed'])
        self.assertGreater(result['envelope']['maximum_outside_segment_distance'], .049)

    def test_missing_or_wrong_endpoint_actor_clock_and_revision_refused(self):
        mutations = [
            lambda d: d['publications'].pop(6),
            lambda d: d['poses'][0].update(incarnation=76),
            lambda d: d['poses'][0].update(sampled_us=106300),
            lambda d: d['poses'][0].update(completed_frame=107),
            lambda d: d['native'][-1].update(position=[float('nan'), 0, 0]),
            lambda d: d['native'][9].update(revision=2),
            lambda d: d['episodes'][0].update(qualified=False),
            lambda d: d['episodes'].clear(),
            lambda d: d['command']['original_order'].update(incarnation=76),
            lambda d: d['command']['original_order'].update(physicalUI=True),
            lambda d: d.update(next_enqueue_us=106000),
        ]
        for mutation in mutations:
            data = authored_world(); mutation(data)
            with self.subTest(mutation=mutation), self.assertRaises(motion.EvidenceError):
                motion.decompose_world(**data)

    def test_replay_exact_counter_group_full_parity_and_unique_action(self):
        mutations = [
            lambda d: d['workers'][-1].update(replayed_frames_total=6),
            lambda d: d['workers'][-1].update(corrections=2),
            lambda d: d['workers'][0].update(parsed_state_sha256='0'*64),
            lambda d: d['workers'][0].update(replayed_frames_delta=0),
            lambda d: d['workers'][0].update(corrections_delta=0),
            lambda d: d['journal'][0]['players'][1].append(b'other remote command'),
            lambda d: d['journal'][-1]['players'][0].append(b'other own command'),
            lambda d: d['journal'][-1]['players'][0].clear(),
            lambda d: d['command'].update(action_sha256='0'*64),
            lambda d: d['episodes'][0].update(first_divergent_frame=99),
        ]
        for mutation in mutations:
            data = authored_world(); mutation(data)
            with self.subTest(mutation=mutation), self.assertRaises(motion.EvidenceError):
                motion.decompose_world(**data)

    def test_early_empty_group_is_bound_without_invented_timestamp(self):
        data = authored_world()
        # An early empty assigned-frame promotion can precede C; the final C
        # group/+20 is checked separately by analyze_run, not fabricated here.
        data['workers'] = data['workers'][:2]
        for row in data['workers']:
            row['confirmed_frontier'] = 101
        result = motion.decompose_world(**data)
        promotion = result['corrections'][0]['promotion']
        self.assertEqual(promotion['canonical_actions'], [])
        self.assertEqual(promotion['confirmed_frontier'], 101)
        self.assertIsNone(promotion['native65_timestamp_for_empty_frame'])
        data['journal'][0]['players'][0].append(b'unrelated')
        with self.assertRaises(motion.EvidenceError):
            motion.decompose_world(**data)

    def test_nine_digit_decimals_reconstruct_single_before_projection(self):
        data = authored_world()
        for p in data['poses']:
            p['position'] = [float(format(x, '.9g')) for x in p['position']]
        result = motion.decompose_world(**data)
        self.assertTrue(result['attribution_passed'])
        self.assertEqual(result['envelope']['rows'][0]['position'], motion.vec(data['poses'][0]['position']))
        self.assertLess(result['envelope']['maximum_outside_segment_distance'],
                        result['envelope']['precision_bound'])

    def test_clock_contract_requires_real_brackets_interpreter_and_function(self):
        source = b'static bool timestampMicros(uint64_t& output) { output=1; return true; }'
        samples = dict(frequency=10_000_000, rows=[dict(raw_qpc=1_000_000+i*10,
            cpp_us=100000+i, begin_ns=(100000+i)*1000, end_ns=(100000+i)*1000+500) for i in range(32)])
        raw = json.dumps(samples).encode()
        receipt = dict(passed=True, samples=32, natural_exit=0, forced=False,
                       job=dict(active=0, terminated=0), python_sha256='python',
                       stdout_sha256=hashlib.sha256(raw).hexdigest(),
                       cpp_source_sha256=hashlib.sha256(source).hexdigest())
        args = dict(receipt=receipt, samples=samples, samples_sha256=hashlib.sha256(raw).hexdigest(),
                    python_sha256='python', reference_source=source, consumed_source=source)
        self.assertTrue(motion.validate_clock(**args)['passed'])
        for key, change in [('python_sha256', 'different'), ('samples_sha256', 'different'),
                            ('consumed_source', source.replace(b'output=1', b'output=2'))]:
            bad = dict(args); bad[key] = change
            with self.subTest(key=key), self.assertRaises(motion.EvidenceError):
                motion.validate_clock(**bad)
        bad = copy.deepcopy(args); bad['samples']['rows'][5]['cpp_us'] += 2
        with self.assertRaises(motion.EvidenceError):
            motion.validate_clock(**bad)

    def test_actual65_hash_and_separate_arrival_clock_not_fabricated_tsv_time(self):
        correction = motion.decompose_world(**authored_world())['corrections'][0]
        args = dict(correction=correction, receipt=dict(frame=100, sha256='a'*64, sim=104, actions=0),
            bridge=dict(frame=100, payload_sha256='a'*64, received_tick_ms=1),
            arrival=dict(event='arrival', frame=100, qpc_us=106500), payload_sha256='a'*64)
        result = motion.bind_replay_authority(**args)
        self.assertIsNone(result['native65_tick_ms'])
        self.assertEqual(result['arrival_qpc_us'], 106500)
        for owner, key, value in [('receipt', 'sha256', 'b'*64), ('receipt', 'frame', 101),
                                   ('arrival', 'qpc_us', 106700), ('arrival', 'event', 'view')]:
            bad = copy.deepcopy(args); bad[owner][key] = value
            with self.subTest(key=key), self.assertRaises(motion.EvidenceError):
                motion.bind_replay_authority(**bad)

    def test_file_entrypoint_refuses_failed_or_mutated_parent_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); run = folder/'run'; run.mkdir()
            invocation = folder/'invocation.json'; report_path = run/'verification.json'
            invocation.write_text(json.dumps(dict(source_sha256={})))
            base = dict(passed=True, source_unchanged=True, files_unchanged=True,
                forced_cleanup=False, cleanup_errors=[], source_sha256_at_start={},
                source_sha256_at_finish={}, invocation_sha256=motion.sha(invocation))
            options = dict(clock_receipt=folder/'absent-clock', clock_samples=folder/'absent-samples',
                           clock_reference_source=folder/'absent-source', delay_proof={})
            for change in (dict(passed=False), dict(forced_cleanup=True), dict(cleanup_errors=['unreaped']),
                           dict(files_unchanged=False), dict(source_sha256_at_finish={'changed': 'source'}),
                           dict(invocation_sha256='0'*64), dict(passed=1)):
                report_path.write_text(json.dumps(dict(base, **change)))
                before = {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
                with self.subTest(change=change), self.assertRaisesRegex(motion.EvidenceError, 'parent command/state/lifetime'):
                    motion.analyze_run(folder, **options)
                self.assertEqual(before, {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()})

    def test_exact_retained_sender_body_survives_canonical_identity_normalization(self):
        from server.game_data import encode_identity, encode_player_input, decode_player_input
        from server.protobuf_wire import field_bytes, field_uint, field_packed_uint
        from tools import verify_prediction_multiplayer as controller
        match = 'a'*32; sequence = 4
        point = b''.join(field_uint(i, value*2**32) for i, value in enumerate((48, 0, 0), 1))
        group = field_uint(1, 1)+field_uint(2, 12)+field_packed_uint(3, [74])
        action = field_bytes(1, field_bytes(1, group)+field_bytes(3, field_bytes(3, field_bytes(1, point))))
        original = encode_player_input(encode_identity(1, 'LAN Player 1'), [action])
        normalized = encode_player_input(encode_identity(1, 'Prediction host'), [action])
        self.assertEqual(decode_player_input(original)['actions'], decode_player_input(normalized)['actions'])
        self.assertNotEqual(original, normalized)
        digest = lambda raw: hashlib.sha256(raw).hexdigest()
        log = (f'Movement local batch registered: sequence=4 speculativeFrame=551 tick=1001 match={match}\n'
               f'Original command batch submitted: match={match} sequence=4 actions=1 bytes={len(original)} '
               f'body_sha256={digest(original)} sendTick=1002 sourceNextFrame=551\n')
        order = dict(match=match, entity=74, unit_type=1, action_sha256=digest(action), tick_ms=1000, target=[48, 0, 0])
        journal = [dict(frame=553, players={0: [action], 1: []})]
        commits = [dict(event='command_batch_committed', match=match, slot=0, sequence=sequence, frame=553)]
        kwargs = dict(slot=0, journal=journal, commits=commits)
        with self.assertRaisesRegex(AssertionError, 'native72 sender differs'):
            controller.transition_order_binding(log, order, raw_bodies={(match, 0, sequence): normalized}, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); path = folder/f'{match}-0-4.pb'; path.write_bytes(original)
            before = path.read_bytes(); retained = motion.read_submitted_bodies(folder)
            bound = controller.transition_order_binding(log, order, raw_bodies=retained, **kwargs)
            self.assertEqual(bound['assigned_frame'], 551)
            self.assertEqual(bound['canonical_frame'], 553)
            self.assertEqual(bound['body_sha256'], digest(original))
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
