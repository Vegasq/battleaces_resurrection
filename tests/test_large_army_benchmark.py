"""Authored harness controls only: no original assets or native worker launch."""
import asyncio
import copy
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from server.game_data import GameTemplate, encode_deck
from server.bot_catalog import BotChoice, BotDeck
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint, get_bytes, get_repeated_bytes, get_repeated_uint, get_uint, replace_fields, signed64
from tools import benchmark_large_armies as b


def template(mode=1):
    # Only contract fixtures; these are not copied native map/config bytes.
    deck = (75, 74, 76, 73, 77, 47, 80, 70)
    flags = tuple(1 << n for n in range(8))
    entities = b''.join(field_bytes(1, field_uint(1, unit) + field_uint(4, 2*b.Q32) + field_uint(21, flag))
                        for unit, flag in zip(deck, flags))
    entities += b''.join(field_bytes(1, field_uint(1, unit) + field_uint(4, b.Q32) + field_uint(21, 1)) for unit in (1, 2))
    armies = b''.join(field_bytes(2, field_uint(1, s) + field_bytes(3, encode_deck(deck))
                                  + field_uint(4, s % 2) + field_bytes(7, field_uint(1, b.Q32)))
                     for s in range(2 if mode == 1 else 4))
    global_config = field_uint(12, 200*b.Q32) + field_bytes(24, field_packed_uint(1, flags))
    raw = field_bytes(1, entities + armies + field_bytes(3, global_config) + field_uint(36, mode))
    return GameTemplate(raw, catalog_path=None, descriptors_path='unused-authored-descriptors')


def configured(**overrides):
    args = dict(load='large', unit_id=75, opponent='scripted', profile=58, seed=12345, multiplier=1)
    value = template(overrides.pop('mode', 1))
    args.update(overrides)
    match, spec = b.configure_match(value, **args)
    return value, match, spec


def state(frame, counts=(0, 0), *, position=0, damage=0):
    entities = [dict(id=10+s, army=s, type=3, position=[-100+200*s, 0, 0]) for s in (0, 1)]
    entities += [dict(id=100+1000*s+i, army=s, type=75, position=[position+i, 0, s], current_damage=damage)
                 for s in (0, 1) for i in range(counts[s])]
    return dict(frame=frame, raw_sha256='opaque', canonical_fnv1a64='abcdef', entities=entities,
                resources={s: dict(current_supply=counts[s]*2, max_supply=200) for s in (0, 1)},
                game_state=dict(complete=False))


class BenchmarkTests(unittest.TestCase):
    def test_loads_derive_counts_from_normal_supply_cost_without_modifying_cap(self):
        for unit, expected in ((75, (10, 50, 100)), (2, (20, 100, 200))):
            for load, count in zip(b.LOADS, expected):
                with self.subTest(unit=unit, load=load):
                    original, match, spec = configured(load=load, unit_id=unit)
                    self.assertEqual(spec['target_units_per_scripted_army'], count)
                    self.assertEqual(get_bytes(match.game_config, 3), original.global_config)
                    self.assertFalse(spec['spawned_units'])
                    self.assertTrue(spec['ordinary_economy'])

    def test_fixed_seed_generates_identical_input_world_and_only_explicit_income_changes(self):
        original, normal, spec = configured()
        _, repeat, _ = configured()
        _, accelerated, changed = configured(multiplier=16)
        self.assertEqual(normal.raw_game_data, repeat.raw_game_data)
        self.assertEqual(get_bytes(normal.game_config, 3), get_bytes(accelerated.game_config, 3))
        self.assertEqual(get_repeated_bytes(normal.game_config, 1), get_repeated_bytes(accelerated.game_config, 1))
        self.assertFalse(changed['ordinary_economy'])
        self.assertEqual(accelerated.sha256, b.digest(accelerated.gzip_game_data))
        for slot in (0, 1):
            self.assertEqual(get_uint(get_bytes(accelerated.armies_by_slot[slot], 7), 1), 16*b.Q32)
            self.assertEqual(get_uint(get_bytes(normal.armies_by_slot[slot], 7), 1), b.Q32)
        self.assertEqual(original.raw_game_data, template().raw_game_data)
        for invalid in (0, 17, True):
            with self.assertRaises(ValueError):
                configured(multiplier=invalid)

    def test_signed_ground_coordinates_are_q32_int64_not_zigzag(self):
        point = get_bytes(get_bytes(b.ground_command(-3.5, 7.25), 3), 1)
        self.assertEqual(signed64(get_uint(point, 1)), -int(3.5*b.Q32))
        self.assertEqual(signed64(get_uint(point, 3)), int(7.25*b.Q32))
        with self.assertRaises(ValueError):
            b.ground_command(float('nan'), 0)
        with self.assertRaises(ValueError):
            b.execute(75, 12, list(range(201)), b'')

    def test_absent_normal_army_modifiers_follow_existing_default_unity_contract(self):
        t = template()
        t.armies = {slot: replace_fields(army, {7: []}) for slot, army in t.armies.items()}
        match, spec = b.configure_match(t, load='small', unit_id=75, opponent='scripted',
                                       profile=58, seed=42, multiplier=16)
        for army in match.armies_by_slot.values():
            self.assertEqual(get_uint(get_bytes(army, 7), 1), 16*b.Q32)

    def workload(self, **spec_overrides):
        t, m, spec = configured(opponent=spec_overrides.pop('opponent', 'scripted'))
        spec.update(target_units_per_scripted_army=2, **spec_overrides)
        t.entity_abilities[3] = {34}
        t.build_ability_slots[34] = 0
        validator = SimpleNamespace(validate_player_input=lambda slot, body: body)
        with mock.patch.object(b, 'InputValidation', return_value=validator):
            return b.Workload(t, m, spec, setup_frames=5, measure_frames=20)

    def test_phase_transition_requires_actual_counts_and_movement_uses_owned_units(self):
        w = self.workload()
        w.update(state(0, (1, 1)), 0)
        self.assertEqual(w.phase, 'setup')
        inputs, counts = w.inputs(1)
        action = get_repeated_bytes(inputs[0], 2)[0]
        group = get_bytes(get_bytes(action, 1), 1)
        self.assertEqual(get_repeated_uint(group, 3), (10,))
        w.update(state(1, (2, 2)), 1)
        self.assertEqual((w.phase, w.reached_frame), ('movement', 1))
        inputs, counts = w.inputs(2)
        group = get_bytes(get_bytes(get_repeated_bytes(inputs[0], 2)[0], 1), 1)
        self.assertEqual((get_uint(group, 2), get_repeated_uint(group, 3)), (12, (100, 101)))
        w.update(state(21, (2, 2)), 21)
        self.assertEqual(w.phase, 'combat')
        inputs, _ = w.inputs(22)
        action = get_bytes(get_repeated_bytes(inputs[0], 2)[0], 1)
        self.assertEqual(get_uint(get_bytes(action, 1), 2), 88)
        w.update(state(41, (2, 2)), 41)
        self.assertEqual(w.phase, 'done')

    def test_missing_army_size_and_supply_cheats_are_not_accepted(self):
        w = self.workload()
        with self.assertRaisesRegex(ValueError, 'requested army size'):
            w.update(state(4, (1, 0)), 4)
        w = self.workload()
        with self.assertRaisesRegex(ValueError, 'supply limit exceeded'):
            w.update(state(0, (101, 1)), 0)
        changed = state(0)
        changed['resources'][0]['max_supply'] = 201
        with self.assertRaisesRegex(ValueError, 'supply cap differs'):
            w.update(changed, 0)

    def test_ai_ownership_is_not_replaced_by_scripted_input(self):
        w = self.workload(opponent='ai')
        inputs, commands = w.inputs(0)
        self.assertEqual(set(inputs), {0})
        w.update(state(0, (2, 0)), 0)
        self.assertEqual(w.phase, 'movement')

    def test_observation_requires_same_entity_movement_and_actual_damage(self):
        _, _, spec = configured()
        first, second = state(0, (2, 1)), state(1, (2, 1), position=2, damage=4)
        before = b.observation(first, None, spec)
        after = b.observation(second, first, spec)
        self.assertEqual(before['moving_units'], {'0': 0, '1': 0})
        self.assertEqual(after['moving_units'], {'0': 2, '1': 1})
        self.assertEqual(after['newly_damaged_units'], {'0': 2, '1': 1})
        second['entities'].append(dict(id=999, army=1, type=2, current_damage=1))
        mixed = b.observation(second, first, spec)
        self.assertEqual(mixed['unit_counts']['1'], 1)
        self.assertEqual(mixed['army_unit_counts']['1'], 2)
        self.assertEqual(mixed['unit_types']['1'], {'2': 1, '75': 1})
        first['resources'][0]['primary_lost'] = 100
        second['resources'][0]['primary_lost'] = 200
        self.assertEqual(b.observation(second, first, spec)['newly_lost_unit_resource_cost']['0'], 100)

    def test_replay_rejects_corruption_reordering_and_state_mismatch(self):
        current, payload = state(0, (1, 1)), b'authored frame'
        expected = dict(frame=0, input_sha256=b.digest(payload), state_sha256=b.state_digest(current))
        b.check_record(0, payload, current, expected)
        opaque = dict(current, raw_sha256='different allocation')
        b.check_record(0, payload, opaque, expected)
        for frame, body, snapshot in ((1, payload, current), (0, payload+b'bad', current),
                                     (0, payload, state(0, (1, 2)))):
            with self.assertRaises(ValueError):
                b.check_record(frame, body, snapshot, expected)
        for contents in (b'', b'123', struct.pack('<I', b.MAX_FRAME_BYTES+1), struct.pack('<I', 5)+b'123'):
            with self.assertRaises(ValueError):
                b.read_frame(io.BytesIO(contents))
        self.assertEqual(b.read_frame(io.BytesIO(struct.pack('<I', len(payload))+payload)), payload)

    def test_percentiles_and_budget_misses_are_not_hidden_by_average(self):
        result = b.summary([1]*98 + [51, 101])
        self.assertEqual((result['p95'], result['p99'], result['maximum']), (1, 51, 101))
        self.assertEqual((result['above_50ms'], result['above_100ms']), (2, 1))

    def test_existing_output_or_unbounded_workload_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            args = SimpleNamespace(assets=root/'assets', output=root/'local/run', setup_frames=4000,
                measure_frames=600, timeout_seconds=600, seed=1, resource_multiplier=1, profile=58,
                profile_thread_interval=0, replay=None)
            with mock.patch.object(b, 'ROOT', root), mock.patch.object(b.os, 'name', 'nt'):
                b.validate_args(args)
                args.output.mkdir(parents=True)
                with self.assertRaisesRegex(ValueError, 'new ignored'):
                    b.validate_args(args)
                args.output = root/'local/new'
                args.measure_frames = 6001
                with self.assertRaisesRegex(ValueError, 'frame budget'):
                    b.validate_args(args)

    def test_four_scripted_armies_retain_distinct_identity_and_normal_per_army_cap(self):
        t, match, spec = configured(mode=2, unit_id=2)
        self.assertEqual(spec['scripted_armies'], [0, 1, 2, 3])
        self.assertEqual(spec['alliances'], {'0': 0, '1': 1, '2': 0, '3': 1})
        self.assertEqual(spec['target_units_per_scripted_army'], 200)
        self.assertEqual(len(set(match.identities_by_slot.values())), 4)
        for slot in range(4):
            self.assertEqual(get_uint(match.armies_by_slot[slot], 1), slot)
            self.assertEqual(match.decks_by_slot[slot][0], 2)

    def test_team_bots_require_frozen_mode_compatible_catalog_choices(self):
        t = template(5)
        deck = t.default_decks[1]
        original_deck = BotDeck(1, 1, 'Authored deck', 0, 0, encode_deck(deck), deck)
        choices = {s: BotChoice(58+s, 5, f'Authored bot{s}', 0, 0, original_deck,
                               original_deck.message, 'normal', (b.Q32, b.Q32, b.Q32)) for s in (1, 3)}
        _, match, spec = configured(mode=5, opponent='ai', unit_id=2, bot_choices=choices)
        self.assertEqual(spec['scripted_armies'], [0, 2])
        self.assertEqual(spec['ai_profiles'], {'1': 59, '3': 61})
        self.assertEqual(match.decks_by_slot[0][0], 2)
        self.assertEqual(match.decks_by_slot[1], original_deck.units)
        for selection in (None, {1: choices[1]}):
            with self.assertRaisesRegex(ValueError, 'catalog choices'):
                configured(mode=5, opponent='ai', bot_choices=selection)
        with self.assertRaisesRegex(ValueError, 'requires original AI'):
            configured(mode=5, opponent='scripted')

    def test_team_commands_never_merge_allied_owners_or_attack_teammates(self):
        t, match, spec = configured(mode=2)
        t.entity_abilities[3], t.build_ability_slots[34] = {34}, 0
        validator = SimpleNamespace(validate_player_input=lambda slot, body: body)
        with mock.patch.object(b, 'InputValidation', return_value=validator):
            w = b.Workload(t, match, spec, 100, 20)
        w.entities = {100+s: dict(id=100+s, army=s, type=75, position=[s, 0, 0]) for s in range(4)}
        w.hqs = {s: dict(id=10+s, army=s, type=3, position=[100*(s % 2), 0, 100*(s//2)]) for s in range(4)}
        w.entities.update({v['id']: v for v in w.hqs.values()})
        w.phase, w.phase_frame = 'combat', 0
        inputs, _ = w.inputs(1)
        for slot, body in inputs.items():
            action = get_bytes(get_repeated_bytes(body, 2)[0], 1)
            group = get_bytes(action, 1)
            self.assertEqual(get_repeated_uint(group, 3), (100+slot,))
            target = get_uint(get_bytes(get_bytes(action, 3), 2), 1)
            self.assertNotEqual(w.entities[target]['army'] % 2, slot % 2)

    def test_one_active_army_cannot_qualify_four_army_movement_or_combat(self):
        phases = dict(setup={}, movement=dict(movement_by_army={str(s): True for s in range(4)}),
                      combat=dict(combat_by_army={str(s): True for s in range(4)}))
        b.qualify_phases(phases, 4)
        for phase, field in (('movement', 'movement_by_army'), ('combat', 'combat_by_army')):
            changed = copy.deepcopy(phases)
            changed[phase][field]['3'] = False
            with self.assertRaisesRegex(ValueError, 'every army'):
                b.qualify_phases(changed, 4)
            del changed[phase][field]['3']
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                b.qualify_phases(changed, 4)

    def test_profile_thread_interval_is_bounded_and_passed_explicitly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            args = SimpleNamespace(assets=root/'assets', output=root/'local/run', setup_frames=4000,
                measure_frames=600, timeout_seconds=600, seed=1, resource_multiplier=1, profile=58,
                profile_thread_interval=0, replay=None)
            with mock.patch.object(b, 'ROOT', root), mock.patch.object(b.os, 'name', 'nt'):
                for interval in (0, 20, 20000):
                    args.profile_thread_interval = interval
                    b.validate_args(args)
                for interval in (-1, 20001, True):
                    args.profile_thread_interval = interval
                    with self.assertRaisesRegex(ValueError, 'thread interval'):
                        b.validate_args(args)
            args.profile_worker = True
            from tools import profile_worker_timing
            for interval in (0, 20):
                args.profile_thread_interval = interval
                with mock.patch.object(profile_worker_timing, 'create_profiled_worker', new_callable=mock.AsyncMock) as factory:
                    asyncio.run(b.create_worker(args, b'authored-bootstrap', root/'worker'))
                    self.assertEqual(factory.await_args.kwargs['thread_sample_interval'], interval)

    def test_wine_paths_are_all_or_nothing_with_no_implicit_fallback(self):
        args = SimpleNamespace(profile_worker=False, wine_executable=None, windows_python=None,
                               wine_prefix_template=None, wine_cgroup_parent=None)
        self.assertFalse(b.wine_requested(args))
        self.assertIsNone(b.select_backend(args))
        args.wine_executable = Path.cwd()/'wine'
        with self.assertRaisesRegex(ValueError, 'supplied together'):
            b.wine_requested(args)
        args.windows_python = Path.cwd()/'python.exe'
        args.wine_prefix_template = Path.cwd()/'private-template'
        self.assertTrue(b.wine_requested(args))
        args.profile_worker = True
        with self.assertRaisesRegex(ValueError, 'profiling.*not supported'):
            b.wine_requested(args)
        args.profile_worker = False
        args.wine_prefix_template = Path('relative-prefix')
        with self.assertRaisesRegex(ValueError, 'absolute'):
            b.wine_requested(args)
        args.wine_executable = args.windows_python = args.wine_prefix_template = None
        args.wine_cgroup_parent = Path.cwd()/'cgroup'
        with self.assertRaisesRegex(ValueError, 'requires the three'):
            b.wine_requested(args)

    def test_backend_constructor_and_worker_receive_exact_explicit_values(self):
        args = SimpleNamespace(assets=Path.cwd()/'assets', profile_worker=False,
            wine_executable=Path.cwd()/'wine', windows_python=Path.cwd()/'python.exe',
            wine_prefix_template=Path.cwd()/'template', wine_cgroup_parent=Path.cwd()/'cgroup')
        from server import wine_worker
        with mock.patch.object(wine_worker, 'WineWorkerBackend') as constructor:
            selected = b.select_backend(args)
            constructor.assert_called_once_with(wine_executable=args.wine_executable, windows_python=args.windows_python,
                prefix_template=args.wine_prefix_template, cgroup_parent=args.wine_cgroup_parent)
        with mock.patch.object(b.SimulationWorker, 'create', new_callable=mock.AsyncMock) as factory:
            asyncio.run(b.create_worker(args, b'authored-world', Path.cwd(), backend=selected))
            self.assertIs(factory.await_args.kwargs['backend'], selected)
            self.assertNotIn('_test_backend', factory.await_args.kwargs)
        args.profile_worker = True
        with mock.patch.object(b.SimulationWorker, 'create', new_callable=mock.AsyncMock) as factory:
            with self.assertRaisesRegex(ValueError, 'profiling.*not supported'):
                asyncio.run(b.create_worker(args, b'authored-world', Path.cwd(), backend=selected))
            factory.assert_not_called()

    def test_backend_identity_binds_runtime_binaries_and_bounds_version_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wine, python = root/'wine', root/'python.exe'
            wine.write_bytes(b'authored-wine-file')
            python.write_bytes(b'authored-python-file')
            backend = SimpleNamespace(wine_executable=wine, windows_python=python,
                                      prefix_template=root/'template', cgroup_parent=root/'cgroup')
            completed = SimpleNamespace(stdout=b'wine-authored-version\n', stderr=b'')
            with mock.patch.object(b.subprocess, 'run', return_value=completed) as probe:
                result = b.backend_identity(backend)
            self.assertEqual(result['wine_version'], 'wine-authored-version')
            self.assertEqual(result['windows_python_sha256'], b.digest(b'authored-python-file'))
            self.assertEqual(probe.call_args.args[0], [str(wine), '--version'])
            self.assertEqual(probe.call_args.kwargs['timeout'], 5)
            self.assertNotIn('WINEPREFIX', probe.call_args.kwargs['env'])
            with mock.patch.object(b.subprocess, 'run', return_value=SimpleNamespace(stdout=b'x'*4097, stderr=b'')):
                with self.assertRaisesRegex(ValueError, 'exceeds bound'):
                    b.backend_identity(backend)

    def test_hybrid_cleanup_requires_native_exit_and_both_ownership_boundaries_closed(self):
        good = dict(cleanup_complete=True, prefix_removed=True, cgroup_removed=True, exit_code=0, native_exit_code=0)
        self.assertTrue(b.backend_cleanup_complete(good))
        self.assertFalse(b.backend_cleanup_complete(None))
        for key, value in good.items():
            with self.subTest(field=key):
                changed = dict(good)
                del changed[key]
                self.assertFalse(b.backend_cleanup_complete(changed))
                changed[key] = False if value is True else 1
                self.assertFalse(b.backend_cleanup_complete(changed))


if __name__ == '__main__':
    unittest.main()
