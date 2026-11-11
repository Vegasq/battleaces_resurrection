"""Pure close-formation plan, native-copy and report gate boundary controls."""
import argparse
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from tools import prediction_close_formation_evidence as evidence
from tools.prediction_close_formation_fixture import metadata
from tools.verify_high_latency_clients import state_digest


def plan():
    return dict(scenario='close-formation', close_formation=True, lifecycle='natural',
        frames=650, expected_matches=2, move_slot=0, rtt_ms=[130, 475],
        native_position_trace=None, actor_fixture=None, generic_movement_not_exercised=True,
        surrender_frame=700, native_cohort_spec='1:1:130:360:8',
        close_formation_fixture=metadata(), close_formation_scope=evidence.SCOPE)


def report():
    """Authored gate input; this is not an end-to-end gameplay witness."""
    matches = ['a' * 32, 'b' * 32]
    episodes = []
    for index, match in enumerate(matches):
        episodes.append(dict(passed=True, match=match, world=index + 1,
            worlds_by_slot=[index + 11, index + 1], selected_ids=[11, 12, 13, 14],
            rendered_members_verified=4, native_members_verified=4,
            late_remote_replay_verified=True, continuity_verified=True, close_graph_verified=True,
            selection_calls=1, group_assign_calls=1, reselection_calls=0,
            cache_observed_frames=231, members=[dict(entity=i) for i in (11, 12, 13, 14)],
            physicalUI=False, closed_native_frames=721, closed_native_rows_by_slot=[721, 721]))
    proof = dict(passed=True, episodes=episodes, physicalUI=False, collision_solver_qualified=False,
        full_feature_accepted=False, scope=evidence.SCOPE,
        all_closed_native_hashes_checked=2884, all_retained_wire_triples_checked=2884)
    return dict(close_formation=proof, matches=[dict(match=m, canonical_frames=650,
        exact_bridge_and_native_authority_receipts=True) for m in matches],
        clients=[dict(index=slot, matches=matches[:], natural_worker_shutdown=True,
            movement_route=True) for slot in (0, 1)], full_feature_accepted=False)


def native_state(frame=130):
    fixture = metadata()
    positions = [fixture['initial_host']] + fixture['initial_guests']
    entities = [dict(id=identity, type=1, army=0 if identity == 10 else 1,
        max_health=600., current_damage=0., position=position[:])
        for identity, position in zip((10, 11, 12, 13, 14), positions)]
    return dict(frame=frame, viewer=31, entities=entities,
                game_state=dict(complete=False), raw_sha256='0' * 64)


class CloseFormationPlanTests(unittest.TestCase):
    def test_argparse_float_rtts_and_json_plan_are_accepted(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--rtt-ms', nargs=2, type=float)
        parsed = parser.parse_args(['--rtt-ms', '130', '475'])
        selected = plan()
        selected['rtt_ms'] = parsed.rtt_ms
        self.assertEqual([type(v) for v in parsed.rtt_ms], [float, float])
        evidence.validate_plan(selected)
        evidence.validate_plan(json.loads(json.dumps(selected)))
        self.assertEqual(evidence.scope(selected), evidence.SCOPE)

    def test_nonfinite_bool_or_wrong_order_rtts_are_refused(self):
        for rtts in ([130, True], [False, 475], [float('nan'), 475], [130, float('inf')],
                     [float('-inf'), 475], [475, 130], [130, 474.9], (130, 475), [130]):
            with self.subTest(rtts=rtts), self.assertRaises(AssertionError):
                evidence.validate_plan(dict(plan(), rtt_ms=rtts))

    def test_exact_metadata_order_spec_and_concede_contract_are_required(self):
        variants = [dict(surrender_frame=v) for v in (699, 701, 700., True)]
        variants += [dict(native_cohort_spec=v) for v in ('1:1:130:220:8', '1:1:130:360:4', None)]
        variants += [dict(frames=650.), dict(expected_matches=True), dict(move_slot=False),
                     dict(generic_movement_not_exercised=1), dict(close_formation=1),
                     dict(lifecycle='prefix'), dict(close_formation_scope=None)]
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                evidence.validate_plan(dict(plan(), **changes))
        for key, value in (('guest_ids', [14, 13, 12, 11]), ('seed', 1),
                           ('remote_physical_frame', 321), ('ordinary_globals_unchanged', 1)):
            selected = plan()
            selected['close_formation_fixture'][key] = value
            with self.subTest(metadata=key), self.assertRaises(AssertionError):
                evidence.validate_plan(selected)

    def test_every_other_fixture_requires_typed_false_and_unselected_defaults_remain_inert(self):
        for key in evidence.EXCLUSIONS:
            for value in (True, 0):
                with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                    evidence.validate_plan(dict(plan(), **{key: value}))
        for unselected in ({}, dict(scenario='startup'), dict(scenario='movement', close_formation=False)):
            evidence.validate_plan(unselected)
            self.assertIsNone(evidence.scope(unselected))
            self.assertTrue(evidence.gate(unselected, {}))
        with self.assertRaises(AssertionError):
            evidence.validate_plan(dict(scenario='close-formation'))
        self.assertFalse(evidence.gate(dict(scenario='close-formation'), {}))

    def test_option_derives_only_selected_scenario_and_refuses_topology_or_hidden_override(self):
        args = SimpleNamespace(scenario='close-formation', lifecycle='natural', move_slot=0,
                               rtt_ms=(130., 475.))
        self.assertIs(evidence.option(args, 650, None), True)
        for updates, frames, trace in ((dict(lifecycle='prefix'), 650, None),
                (dict(move_slot=1), 650, None), (dict(surrender_frame=260), 650, None),
                (dict(mobile_correction=True), 650, None), ({}, 600, None),
                ({}, 650, '11:1:1:130:360')):
            changed = SimpleNamespace(**(vars(args) | updates))
            with self.subTest(updates=updates, frames=frames, trace=trace), self.assertRaises(AssertionError):
                evidence.option(changed, frames, trace)
        args.scenario = 'startup'
        self.assertIs(evidence.option(args, 200, None), False)


class CloseFormationNativeObservationTests(unittest.TestCase):
    def test_observation_binds_actual_digest_and_copies_ordered_float32_participants(self):
        state = native_state()
        state['entities'].reverse()
        observed = evidence.native_observation(state, state_digest(state))
        self.assertEqual([r['id'] for r in observed['participants']], [10, 11, 12, 13, 14])
        self.assertEqual(observed['parsed_state_sha256'], state_digest(state))
        self.assertEqual(observed['participants'][0]['position'], [60., 0., 60.])
        state['entities'][-1]['position'][0] = 0.
        state['game_state']['complete'] = True
        self.assertEqual(observed['participants'][0]['position'], [60., 0., 60.])
        self.assertIs(observed['game_state']['complete'], False)
        raw_changed = native_state()
        digest = state_digest(raw_changed)
        raw_changed['raw_sha256'] = 'f' * 64
        self.assertEqual(state_digest(raw_changed), digest)
        self.assertEqual(evidence.native_observation(raw_changed, digest)['parsed_state_sha256'], digest)

    def test_changed_full_state_hash_or_missing_duplicate_participant_is_refused(self):
        state = native_state()
        digest = state_digest(state)
        state['game_state']['authored_extra'] = 1
        with self.assertRaisesRegex(AssertionError, 'state/hash'):
            evidence.native_observation(state, digest)
        for change in ('missing', 'duplicate', 'wrong-army', 'non-float32', 'missing-component'):
            state = native_state()
            if change == 'missing':
                state['entities'].pop()
            elif change == 'duplicate':
                state['entities'].append(deepcopy(state['entities'][-1]))
            elif change == 'wrong-army':
                state['entities'][-1]['army'] = 0
            elif change == 'non-float32':
                state['entities'][-1]['position'][0] = .1
            else:
                state['entities'][-1].pop('max_health')
            with self.subTest(change=change), self.assertRaises(AssertionError):
                evidence.native_observation(state, state_digest(state))

    def test_only_bounded_actual_authority_frames_are_observed(self):
        for frame in (130, 380):
            state = native_state(frame)
            self.assertEqual(evidence.native_observation(state, state_digest(state))['frame'], frame)
        for frame in (129, 381):
            self.assertIsNone(evidence.native_observation(dict(frame=frame), None))
        for frame in (True, 130., -1, None):
            with self.subTest(frame=frame), self.assertRaises(AssertionError):
                evidence.native_observation(dict(frame=frame), None)


class CloseFormationReportGateTests(unittest.TestCase):
    def test_complete_authored_report_finalizes_and_survives_json_roundtrip(self):
        result = report()
        evidence.finalize(result, plan())
        self.assertTrue(evidence.gate(plan(), result))
        self.assertTrue(result['close_formation_witness_passed'])
        self.assertTrue(result['generic_movement_not_exercised'])
        self.assertFalse(result['movement_feel_witness_passed'])
        self.assertFalse(result['full_feature_accepted'])
        restored = json.loads(json.dumps(result))
        self.assertEqual(restored['close_formation']['episodes'][1]['worlds_by_slot'], [12, 2])
        self.assertTrue(evidence.gate(json.loads(json.dumps(plan())), restored))

    def test_incomplete_lifecycle_and_receipts_cannot_finalize_or_reuse_success_flags(self):
        changes = {
            'error': lambda r: r.update(error='authored failure'),
            'missing-client': lambda r: r['clients'].pop(),
            'unnatural-worker': lambda r: r['clients'][1].update(natural_worker_shutdown=False),
            'wrong-client-match': lambda r: r['clients'][1].update(matches=['b' * 32, 'a' * 32]),
            'short-prefix': lambda r: r['matches'][1].update(canonical_frames=649),
            'missing-receipt': lambda r: r['matches'][1].update(exact_bridge_and_native_authority_receipts=False),
        }
        for name, change in changes.items():
            result = report()
            evidence.finalize(result, plan())
            change(result)
            with self.subTest(change=name):
                self.assertFalse(evidence.gate(plan(), result))
                with self.assertRaises(AssertionError):
                    evidence.finalize(result, plan())
                self.assertIs(result['close_formation_witness_passed'], False)
                self.assertIs(result['scoped_observation_passed'], False)

    def test_missing_members_worlds_parity_or_broader_claims_fail_closed(self):
        changes = {
            'missing-episode': lambda p: p['episodes'].pop(),
            'member-order': lambda p: p['episodes'][0]['members'].reverse(),
            'duplicate-world': lambda p: p['episodes'][1].update(world=1, worlds_by_slot=[12, 1]),
            'string-world-keys': lambda p: p['episodes'][0].update(worlds_by_slot={'0': 11, '1': 1}),
            'wrong-guest-world': lambda p: p['episodes'][0].update(worlds_by_slot=[11, 3]),
            'short-native-prefix': lambda p: p['episodes'][0].update(closed_native_frames=649),
            'wrong-total': lambda p: p.update(all_closed_native_hashes_checked=2883),
            'no-replay': lambda p: p['episodes'][0].update(late_remote_replay_verified=False),
            'collision-claim': lambda p: p.update(collision_solver_qualified=True),
            'physical-claim': lambda p: p.update(physicalUI=True),
            'full-acceptance': lambda p: p.update(full_feature_accepted=True),
        }
        for name, change in changes.items():
            result = report()
            evidence.finalize(result, plan())
            change(result['close_formation'])
            with self.subTest(change=name):
                self.assertFalse(evidence.gate(plan(), result))
                with self.assertRaises(AssertionError):
                    evidence.finalize(result, plan())


if __name__ == '__main__':
    unittest.main()
