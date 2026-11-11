"""Two-world authored evidence pipeline; no original native/client execution."""
from copy import deepcopy
import json
import struct
import unittest

from server.game_data import encode_identity, encode_player_input
from tools import prediction_close_formation_evidence as e
from tools import verify_prediction_multiplayer as controller
from tools.verify_high_latency_clients import state_digest
from tests.test_prediction_multi_unit_evidence import action


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def bits(point):
    return [struct.unpack('<I', struct.pack('<f', v))[0] for v in point]


SQUARE = dict(zip(e.IDS, [[-81., 0., -61.], [-81., 0., -59.], [-79., 0., -61.], [-79., 0., -59.]]))


class Fixture:
    def __init__(self):
        self.logs = {0: [], 1: []}; self.contexts = []; self.native = []
        self.worker = {0: [], 1: []}; self.receipts = {}; self.peer_bridge = []
        self.raw = {}; self.matches = ['a'*32, 'b'*32]
        for world, match in enumerate(self.matches, 1):
            self.world(world, match)
        self.refresh_logs()

    @staticmethod
    def position(identity, frame):
        if identity == 10:
            return [60., 0., f32(60.-max(0, min(frame-320, 80))*.2)]
        original = SQUARE[identity]
        approach = max(0, min(frame-180, 50))*.2
        fresh = max(0, min(frame-300, 80))*.2
        return [f32(original[0]+approach), 0., f32(original[2]+approach-fresh)]

    @classmethod
    def state(cls, frame):
        return dict(frame=frame, viewer=31, entities=[dict(id=i, type=1, army=0 if i == 10 else 1,
            max_health=600, current_damage=0, position=cls.position(i, frame)) for i in [10]+e.IDS],
            game_state=dict(complete=False, game_over_frame=-1), raw_sha256='opaque')

    @classmethod
    def view_position(cls, identity, frame):
        p = cls.position(identity, frame)
        return [f32(-v if identity != 10 and axis in (0, 2) else v) for axis, v in enumerate(p)]

    def emit(self, slot, row):
        self.logs[slot].append(e.PREFIX+json.dumps(row))

    def common(self, world, match, slot, frame, event, *, tag=None, extra_us=100):
        return dict(schema=1, event=event, order_tag=tag, world=world if slot else world+100,
            match=match, slot=slot, frame=frame, completed_frame=frame, tick_ms=world*100000+frame*50+extra_us//1000,
            sampled_us=world*100000000+frame*50000+extra_us, physicalUI=False)

    def snapshot(self, world, match, slot, frame, event):
        ids = e.IDS if slot else [10]; members = []
        for identity in ids:
            token = world*100+identity; actor = f'{world*10000+identity:X}'
            p = self.view_position(identity, frame)
            moving = (181 <= frame < 230 or 301 <= frame < 380) if slot else frame >= 321
            members.append(dict(id=identity, unit_type=1, army=slot, original_token=token,
                incarnation=token, canonical_token=token, original_actor=actor, actor=actor,
                native_present=True, native_state=1 if moving else 0, admitted=True, initialized=True,
                position=p, position_bits=bits(p), position_sampled_us=world*100000000+frame*50000,
                jobs_joined=True))
        row = self.common(world, match, slot, frame, event)
        row.update(members=members, selector=f'{world*100+slot+1:X}', manager=f'{world*100+slot+11:X}',
            simulation=f'{world*100+slot+21:X}', group_generation=world,
            current_ids=e.IDS[:] if slot else [], preview_ids=[], casting_ids=[], active_caster=None,
            primary=False, context=False, drag=False, last_click_id=0xffffffff, click_mode=0,
            pending_commands=0, selection_calls=slot, group_assign_calls=slot,
            selection_scope_player_initiated=False if slot else None, history_writes=0,
            current_count=4 if slot else 0, current_all_ids=e.IDS[:] if slot else [],
            current_typed_ids=e.IDS[:] if slot else [], current_frame_owner=f'{world*100+31:X}')
        for key in ('group', 'helper', 'group_ids', 'group_count', 'group_all_ids', 'group_typed_ids',
                    'group_frame_owner', 'tracked_released_ids', 'auto_type1'):
            row[key] = None
        if slot:
            row.update(group=f'{world*100+41:X}', helper=f'{world*100+51:X}', group_ids=e.IDS[:],
                group_count=4, group_all_ids=e.IDS[:], group_typed_ids=e.IDS[:],
                group_frame_owner=row['current_frame_owner'], tracked_released_ids=[], auto_type1=False)
        return row

    def command(self, world, match, slot, frame, tag, target, sequence, raw_action):
        ids = e.IDS if slot else [10]; origins = [self.view_position(i, frame) for i in ids]
        q = self.common(world, match, slot, frame, 'move_queued', tag=tag, extra_us=1000)
        command = f'{world*1000+frame:X}'; proto = f'{world*1000+frame+10000:X}'
        q.update(source_ids=ids[:], incarnations=[world*100+i for i in ids], origins=origins,
            origins_sampled_us=[world*100000000+frame*50000+500]*len(ids), target=target, target_bits=bits(target),
            command=command, command_class='Uncapped.ExecuteTargetGroundCommand', queued=False,
            ability=12, queue_before=0, queue_after=1, originalCtor=True,
            original_callback='Uncapped.ExecuteTargetGroundCommand..ctor',
            enqueue_sampled_us=world*100000000+frame*50000+2000, local_alliance=slot,
            map_perspective=slot, map_perspective_source='Uncapped.Map.GetAlliancePerspective',
            map_perspective_enum='Uncapped.Map.Perspective', map_perspective_enum_matches_ctor=True,
            map_perspective_normal=0, map_perspective_flipped=1,
            map_perspective_value_name='Flipped' if slot else 'Normal')
        self.emit(slot, q)
        body = encode_player_input(encode_identity(slot+1, 'human'), [raw_action])
        self.raw[match, slot, sequence] = body
        for event, extra, us in (
            ('serialized', dict(command=command, action=proto, sequence=sequence, source_next_frame=frame+1, action_index=0), 3000),
            ('batch_registered', dict(command=command, action=proto, sequence=sequence, speculative_frame=frame+1,
                action_index=0, action_sha256=e.shared.digest(raw_action), body_sha256=e.shared.digest(body)), 4000)):
            self.emit(slot, self.common(world, match, slot, frame, event, tag=tag, extra_us=us) | extra)
        tick = world*100000+frame*50
        self.logs[slot].append(f'Movement local batch registered: sequence={sequence} speculativeFrame={frame+1} tick={tick+3} match={match}')
        self.logs[slot].append(f'Original command batch submitted: match={match} sequence={sequence} actions=1 bytes={len(body)} body_sha256={e.shared.digest(body)} sendTick={tick+4} sourceNextFrame={frame+1}')

    def world(self, world, match):
        hashes = {f: state_digest(self.state(f)) for f in range(650)}
        wires = {f: e.shared.digest(f'{match}/wire/{f}'.encode()) for f in hashes}
        targets = dict(approach=[70., 0., 50.], fresh=[70., 0., 66.], remote=[60., 0., 44.])
        actions = dict(approach=action(e.IDS, [-70., 0., -50.]), fresh=action(e.IDS, [-70., 0., -66.]), remote=action([10], targets['remote']))
        commits = [dict(event='command_batch_committed', match=match, slot=s, sequence=seq, frame=f)
                   for s, seq, f in ((1, 2, 181), (1, 3, 301), (0, 2, 321))]
        journal = [dict(frame=f, players={0: [actions['remote']] if f == 321 else [],
            1: [actions['approach']] if f == 181 else [actions['fresh']] if f == 301 else []}) for f in hashes]
        bridges = [dict(match=match, frame=f, payload_sha256=wires[f], received_tick_ms=world*100000+(f+9)*50+6) for f in hashes]
        self.peer_bridge.extend(bridges)
        for slot in (0, 1):
            self.receipts[slot, match] = [dict(frame=f, sha256=wires[f]) for f in hashes]
            self.logs[slot].append(f'Movement prediction ready: generation={world} match={match} world={world if slot else world+100} slot={slot} source=authored')
            for f in hashes:
                correction = int(slot == 1 and f >= 321)
                self.worker[slot].append(dict(schema=1, event='confirmed_native_state', world=world if slot else world+100,
                    frame=f, parsed_state_sha256=hashes[f], confirmed_frontier=f, corrections=correction,
                    corrections_delta=int(slot == 1 and f == 321), replayed_frames_total=correction*10,
                    replayed_frames_delta=10*int(slot == 1 and f == 321), tick_ms=world*100000+(f+9)*50+20))
            for f in range(130, 390):
                if f <= 360:
                    self.emit(slot, self.snapshot(world, match, slot, f,
                        'selected' if f == 130 and slot else 'setup' if f == 130 else 'complete' if f == 360 else 'sample'))
                if slot == 1 and f in (180, 300):
                    tag = 'approach' if f == 180 else 'fresh'
                    self.command(world, match, slot, f, tag, targets[tag], 2 if f == 180 else 3, actions[tag])
                if slot == 0 and f == 320:
                    self.command(world, match, slot, f, 'remote', targets['remote'], 2, actions['remote'])
                canonical = f-9
                if 130 <= canonical <= 380:
                    self.emit(slot, self.common(world, match, slot, f, 'authority', extra_us=5000) |
                        dict(canonical_frame=canonical, wire_sha256=wires[canonical], canonical_sha256='c'*64))
        for f in range(130, 361):
            row = self.native_row(world, f)
            self.native.append(row)
            if f == 330:
                before = dict(row, event='before_restore_cached_head', revision=1, checkpoint_base=320,
                    first_divergent_frame=321, context_source='cached_query_before_restore',
                    cached_from_record=row['record'], cached_physical_head=330, record=len(self.native))
                self.native.append(before)
                for replay in range(321, 331):
                    self.native.append(self.native_row(world, replay, stage='replay', at=16510000+(replay-321)*1000))
        native_states = [e.native_observation(self.state(f), hashes[f]) for f in range(130, 381)]
        self.contexts.append(dict(match=match, raw_bodies=self.raw, commits=commits, journal=journal,
            canonical_states=hashes, canonical_payloads=wires, bridge_frames=bridges, native_states=native_states))

    def native_row(self, world, frame, *, stage='ordinary', at=None):
        replay = stage == 'replay'; revision = int(replay or frame >= 331)
        begin = world*100000000+(frame*50000-4000 if at is None else at)
        tick = begin//1000
        return dict(schema=1, event='after_replay_same_head' if replay and frame == 330 else 'native_cohort_positions',
            record=len(self.native), world=world, frame=frame, revision=revision, query_revision=revision,
            checkpoint_base=320 if revision else None, first_divergent_frame=321 if revision else None,
            cohort_spec=e.SPEC.copy(), context_source='same_decoded_native_query', stage=stage,
            head=330 if replay else frame-1, confirmed=320 if replay else frame-10, received=321 if replay else frame-10,
            corrections=0 if replay else revision, replayed_frames=frame-321 if replay else revision*10,
            query_begin_us=begin, query_end_us=begin+10, query_begin_tick_ms=tick, query_end_tick_ms=tick,
            status='present', count=4, entities=[dict(id=i, type=1, army=1, position=self.position(i, frame),
                position_bits=bits(self.position(i, frame))) for i in e.IDS],
            clock_source='python.perf_counter_ns//1000', query_scope='existing-native-make-get-and-decode')

    def refresh_logs(self):
        for c in self.contexts: c.update(log='\n'.join(self.logs[1]), attacker_log='\n'.join(self.logs[0]))

    def mutate_rows(self, slot, function):
        result = []
        for line in self.logs[slot]:
            if line.startswith(e.PREFIX):
                row = json.loads(line[len(e.PREFIX):]); function(row)
                line = e.PREFIX+json.dumps(row)
            result.append(line)
        self.logs[slot] = result; self.refresh_logs()

    def run(self):
        return e.evaluate(contexts=self.contexts, cohort_trace=self.native, worker_states=self.worker,
            native_receipts=self.receipts, peer_bridge_frames=self.peer_bridge,
            authority_rows=lambda _: (_ for _ in ()).throw(AssertionError('generic sparse authority is not the accepted65 witness')),
            join_check=controller.joined_worker_evidence)


class Pipeline(unittest.TestCase):
    def test_actual_nine_digit_single_operands_and_one_ulp_wrong_target(self):
        # Actual71 both worlds: each nine-digit log value round-trips to the
        # original Single, but is not itself that Single as a Python double.
        origins = [[71.5149078, 0., 51.5150604], [71.3545609, 0., 49.9230652],
                   [69.9230499, 0., 51.353817], [69.7626953, 0., 49.7619324]]
        actual_bits = [1116555026, 0, 1116030694]
        self.assertEqual(bits(e.fresh_target(origins)), actual_bits)
        for wrong in (False, True):
            fixture = Fixture(); context = fixture.contexts[0]; match = context['match']
            target_bits = actual_bits[:]
            if wrong: target_bits[0] -= 1
            target = [float(format(struct.unpack('<f', struct.pack('<I', value))[0], '.9g')) for value in target_bits]
            mapped = [-f32(value) if axis in (0, 2) else f32(value) for axis, value in enumerate(target)]
            raw_action = action(e.IDS, mapped)
            body = encode_player_input(encode_identity(2, 'human'), [raw_action])
            context['raw_bodies'][match, 1, 3] = body
            context['journal'][301]['players'][1] = [raw_action]
            amended = []
            for line in fixture.logs[1]:
                if line.startswith(e.PREFIX):
                    row = json.loads(line[len(e.PREFIX):])
                    if row['match'] == match and row['order_tag'] == 'fresh':
                        if row['event'] == 'move_queued': row.update(origins=deepcopy(origins), target=target, target_bits=target_bits)
                        elif row['event'] == 'batch_registered': row.update(action_sha256=e.shared.digest(raw_action), body_sha256=e.shared.digest(body))
                        line = e.PREFIX+json.dumps(row)
                elif f'Original command batch submitted: match={match} sequence=3 ' in line:
                    line = (f'Original command batch submitted: match={match} sequence=3 actions=1 bytes={len(body)} '
                            f'body_sha256={e.shared.digest(body)} sendTick=115004 sourceNextFrame=301')
                amended.append(line)
            log = '\n'.join(amended)
            rows = [row for row in e.records(log, slot=1, matches=fixture.matches) if row['row']['match'] == match]
            if wrong:
                with self.assertRaisesRegex(AssertionError, 'fresh target is not the ordered Single'):
                    e._command(log, rows, 'fresh', 1, context)
            else:
                order, binding = e._command(log, rows, 'fresh', 1, context)
                self.assertEqual(bits(order['target']), actual_bits)
                self.assertEqual(binding['protocol_target'], mapped)

    def test_complete_two_world_same_lease_pipeline_and_zero_local_correction_are_honest(self):
        fixture = Fixture(); result = fixture.run()
        self.assertTrue(result['passed']); self.assertEqual(result['all_closed_native_hashes_checked'], 2600)
        self.assertEqual(result['all_retained_wire_triples_checked'], 2600)
        for episode in result['episodes']:
            self.assertEqual(episode['selected_ids'], e.IDS)
            self.assertEqual(episode['rendered_members_verified'], 4)
            self.assertEqual(episode['native_members_verified'], 4)
            self.assertTrue(all(m['render']['response_ms'] > 0 and m['native']['before_native65_ms'] > 0 for m in episode['members']))
            self.assertTrue(all(p['magnitude'] == 0 for p in episode['remote_same_head']['entities']))
            self.assertFalse(episode['geometry']['speculative_native']['geometric_near_contact'])
            self.assertFalse(episode['geometry']['collision_solver_qualified'])
            self.assertGreaterEqual(episode['native_quiet_baseline']['span_us'], 200000)

    def test_pending_one_is_valid_only_between_actual_enqueue_and_serializer(self):
        fixture = Fixture(); amended = []
        for line in fixture.logs[1]:
            amended.append(line)
            if line.startswith(e.PREFIX):
                row = json.loads(line[len(e.PREFIX):])
                if row['event'] == 'move_queued':
                    pending = fixture.snapshot(row['world'], row['match'], 1, row['frame'], 'sample')
                    pending.update(sampled_us=row['sampled_us']+1500, tick_ms=row['tick_ms']+1, pending_commands=1)
                    amended.append(e.PREFIX+json.dumps(pending))
        fixture.logs[1] = amended; fixture.refresh_logs()
        self.assertTrue(fixture.run()['passed'])
        fixture.mutate_rows(1, lambda row: row.update(pending_commands=0)
                            if row['event'] == 'sample' and row['pending_commands'] == 1 else None)
        with self.assertRaisesRegex(AssertionError, 'pending ICommand'): fixture.run()

    def test_pre_receipt_render_bracket_uses_source_order_not_equal_coarse_tick(self):
        fixture = Fixture(); amended = []
        for line in fixture.logs[1]:
            amended.append(line)
            if line.startswith(e.PREFIX):
                receipt = json.loads(line[len(e.PREFIX):])
                if receipt['event'] == 'authority' and receipt['canonical_frame'] == 321:
                    # A correction can change a pose in the SAME GetTickCount64
                    # millisecond after65. It is not a pre-receipt observation.
                    row = fixture.snapshot(receipt['world'], receipt['match'], 1, receipt['frame'], 'sample')
                    row.update(sampled_us=receipt['sampled_us']+100, tick_ms=receipt['tick_ms'])
                    for member in row['members']:
                        member['position'][2] += 2.
                        member['position_bits'] = bits(member['position'])
                        member['position_sampled_us'] = receipt['sampled_us']+50
                    amended.append(e.PREFIX+json.dumps(row))
        fixture.logs[1] = amended; fixture.refresh_logs()
        self.assertTrue(fixture.run()['passed'])

    def test_raw_cache_enumeration_order_is_preserved_without_weakening_member_order(self):
        fixture = Fixture()
        def reorder(row):
            if row['event'] in ('selected', 'sample', 'complete'):
                for key in ('current_ids', 'current_all_ids', 'current_typed_ids', 'group_ids', 'group_all_ids', 'group_typed_ids'):
                    row[key] = list(reversed(row[key]))
        fixture.mutate_rows(1, reorder)
        self.assertTrue(fixture.run()['passed'])
        fixture.mutate_rows(1, lambda row: row['members'].reverse() if row['event'] == 'selected' else None)
        with self.assertRaises(AssertionError): fixture.run()

    def test_lost_member_reselection_wrong_lease_and_unexplained_pending_queue_are_refused(self):
        for kind in ('cache', 'reselection', 'actor', 'token', 'pending', 'ready', 'bits'):
            fixture = Fixture()
            def corrupt(row):
                if row['match'] == fixture.matches[0] and row['event'] == 'sample' and row['frame'] == 300:
                    if kind == 'cache': row['group_typed_ids'].pop()
                    elif kind == 'reselection': row['selection_calls'] = 2
                    elif kind == 'actor': row['members'][0]['actor'] = 'FFFF'
                    elif kind == 'token': row['members'][0]['incarnation'] += 1
                    elif kind == 'pending': row['pending_commands'] = 1
                    elif kind == 'ready': row['members'][0]['native_state'] = 1
                    else: row['members'][0]['position_bits'][0] += 1
            fixture.mutate_rows(1, corrupt)
            with self.subTest(kind=kind), self.assertRaises(AssertionError): fixture.run()

    def test_individual_motion_cannot_be_hidden_by_three_other_members(self):
        for kind in ('render', 'native'):
            fixture = Fixture()
            if kind == 'render':
                def freeze(row):
                    if row['event'] in ('sample', 'complete') and row['frame'] > 300:
                        p = fixture.view_position(14, 300); row['members'][3].update(position=p, position_bits=bits(p))
                fixture.mutate_rows(1, freeze)
            else:
                for row in fixture.native:
                    if row['event'] != 'before_restore_cached_head' and row['frame'] > 300:
                        p = fixture.position(14, 300); row['entities'][3].update(position=p, position_bits=bits(p))
            with self.subTest(kind=kind), self.assertRaises(AssertionError): fixture.run()

    def test_missing_dense_success_receipt_raw_wire_body_or_closed_native_hash_refuses(self):
        for kind in ('accepted', 'wire', 'body', 'host_hash', 'guest_hash', 'extra_action', 'phase', 'duplicate_bridge'):
            fixture = Fixture(); context = fixture.contexts[0]
            if kind == 'accepted':
                fixture.logs[1] = [line for line in fixture.logs[1] if not (line.startswith(e.PREFIX) and
                    (lambda r: r['match'] == context['match'] and r['event'] == 'authority' and r['canonical_frame'] == 321)(json.loads(line[len(e.PREFIX):])))]
                fixture.refresh_logs()
            elif kind == 'wire': fixture.receipts[1, context['match']][321]['sha256'] = '0'*64
            elif kind == 'body': context['raw_bodies'][context['match'], 1, 3] = context['raw_bodies'][context['match'], 1, 2]
            elif kind in ('host_hash', 'guest_hash'): fixture.worker[int(kind == 'guest_hash')][500]['parsed_state_sha256'] = '0'*64
            elif kind == 'extra_action': context['journal'][305]['players'][1].append(context['journal'][301]['players'][1][0])
            elif kind == 'duplicate_bridge': fixture.peer_bridge.append(dict(fixture.peer_bridge[400]))
            else:
                fixture.logs[1] = [line.replace('sequence=3 speculativeFrame=301', 'sequence=3 speculativeFrame=304') for line in fixture.logs[1]]
                fixture.refresh_logs()
            with self.subTest(kind=kind), self.assertRaises(AssertionError): fixture.run()

    def test_native_geometry_empty_replay_and_correction_tail_are_not_substituted(self):
        for kind in ('disconnected', 'empty_replay', 'missing_pair', 'no_replay', 'tail_hash', 'before65_replay', 'native_baseline'):
            fixture = Fixture()
            if kind == 'disconnected':
                row = next(r for r in fixture.native if r['world'] == 1 and r['frame'] == 300)
                row['entities'][3].update(position=[100., 0., 100.], position_bits=bits([100., 0., 100.]))
            elif kind == 'empty_replay':
                row = next(r for r in fixture.native if r['world'] == 1 and r['event'] == 'after_replay_same_head')
                row.update(status='empty', count=0, entities=[])
            elif kind == 'missing_pair':
                row = next(r for r in fixture.native if r['world'] == 1 and r['event'] == 'after_replay_same_head')
                row['event'] = 'native_cohort_positions'
            elif kind == 'no_replay':
                for row in fixture.worker[1]: row.update(corrections=0, corrections_delta=0, replayed_frames_total=0, replayed_frames_delta=0)
            elif kind == 'before65_replay':
                for row in fixture.native:
                    if row['world'] == 1 and row['stage'] == 'replay':
                        row['query_begin_us'] -= 10000; row['query_end_us'] -= 10000
                        row['query_begin_tick_ms'] -= 10; row['query_end_tick_ms'] -= 10
            elif kind == 'native_baseline':
                for row in fixture.native:
                    if row['world'] == 1 and 296 <= row['frame'] <= 299:
                        for member in row['entities']:
                            member['position'][2] += .05; member['position'] = list(struct.unpack('<fff', struct.pack('<fff', *member['position'])))
                            member['position_bits'] = bits(member['position'])
            else: fixture.worker[1][341]['parsed_state_sha256'] = '0'*64
            with self.subTest(kind=kind), self.assertRaises(AssertionError): fixture.run()

    def test_authority_component_health_hash_and_single_centroid_mismatch_refuse(self):
        for kind in ('health', 'missing', 'hash', 'centroid'):
            fixture = Fixture()
            if kind == 'health': fixture.contexts[0]['native_states'][170]['participants'][4]['max_health'] = 100
            elif kind == 'missing': fixture.contexts[0]['native_states'][170]['participants'].pop()
            elif kind == 'hash': fixture.contexts[0]['native_states'][170]['parsed_state_sha256'] = '0'*64
            else:
                def corrupt(row):
                    if row['event'] == 'move_queued' and row['order_tag'] == 'fresh':
                        row['target'][2] += 1.; row['target_bits'] = bits(row['target'])
                fixture.mutate_rows(1, corrupt)
            with self.subTest(kind=kind), self.assertRaises(AssertionError): fixture.run()
