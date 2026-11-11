"""Authored finite histories for the pure held-click evaluator; no game/input."""
from copy import deepcopy
import json
import struct
import unittest

from tools import prediction_held_click_evidence as evidence


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def fixture(variants=(evidence.PRESERVED, evidence.PRESERVED)):
    records, episodes = [], []
    for index, match in enumerate(('a' * 32, 'b' * 32)):
        world, update_base, clock_base = index + 1, index * 1000, index * 100
        actor = [dict(schema=1, event=name, world=world, match=match, entity=5, army=1,
            unit_type=3, frame=frame, tick_ms=1000 + index * 10000 + frame,
            original_actor='100', current_actor='100' if n < 2 else '200',
            original_focus_supported=False, original_group_supported=False,
            focus_retained_at_death=False, physicalUI=False)
            for n, (name, frame) in enumerate(zip(evidence.ACTOR_EVENTS, (130,156,161,166)))]
        episodes.append(dict(match=match, passed=True, rows=deepcopy(actor)))
        frames = (130,130,148,150,150,151,154,156,161,161,165,166,166,166)
        updates = (100,100,118,120,120,121,124,126,131,131,135,136,136,136)
        target = [bits(400), bits(300)]
        for n, name in enumerate(evidence.PHASES):
            if n in (0,7,8,13):
                records.append(('ACTOR CORRECTION ', actor[(0,7,8,13).index(n)]))
            preserved = variants[index] == evidence.PRESERVED
            current_ids = [5] if n < 7 or n >= 11 or preserved else []
            preview_ids = [5] if n in (3,4,5,6,9,10) or (preserved and n in (7,8)) else []
            held = 5 <= n <= 10
            row = dict(schema=1, event=name, sequence=n + 1, world=world, match=match,
                slot=1, entity=5, unit_type=3, frame=frames[n], update=update_base + updates[n],
                update_scope='original_frontend_callback', input_sequence=(0,0,1,1,2,2,2,2,2,2,3,3,3,3)[n],
                selector='AA', action='BB', control='CC', device='DD', input_source='bound_existing_mouse',
                ownership_scope='borrowed_current' if n < 12 else 'retained_scalar',
                owned_button=held if n < 12 else None, input_closed=n >= 12,
                click_id=5 if n >= 5 else 2**32 - 1, mode=1 if held else 0,
                primary=held, context=False, drag=False, now_bits=bits(clock_base + 20 + updates[n] / 100),
                last_up_bits=bits(clock_base + 20 if n < 11 else clock_base + 21.36), window_bits=bits(.25),
                target_position_bits=target.copy() if n >= 2 else [0,0],
                current_position_bits=target.copy() if n >= 3 else [0,0],
                down_position_bits=target.copy() if n >= 5 else [0,0],
                reference_position_bits=target.copy() if n >= 5 else [0,0],
                current_ids=current_ids, preview_ids=preview_ids,
                current_exact5=current_ids == [5], current_empty=not current_ids,
                preview_exact5=preview_ids == [5], preview_empty=not preview_ids,
                original_actor='100', current_actor='100' if n < 7 else '0' if n == 7 else '200',
                original_token=71 + index * 100, current_token=0 if n == 7 else 71 + index * 100,
                original_dead=n >= 7, original_component=n < 7, focus_group=-1, focus_actor='0', active_caster='0',
                input_serial=0 if n < 2 else 1 if n < 5 else 2 if n < 11 else 3,
                accepted_down_serial=2 if held else 0,
                provenance_phase=0 if n < 5 or n >= 11 else 1 if n < 7 or preserved else 3,
                originalClockSingle=True, selectionWritesAfterPress=0, physicalUI=False)
            records.append((evidence.PREFIX, row))
    return records, episodes


def render(records):
    return '\n'.join('[1000] ' + prefix + json.dumps(row, separators=(',', ':')) for prefix, row in records)


class HeldEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.records, self.episodes = fixture()

    def row(self, phase, world=1):
        return next(row for prefix, row in self.records if prefix == evidence.PREFIX and
                    row['event'] == phase and row['world'] == world)

    def evaluate(self, text=None):
        return evidence.evaluate(render(self.records) if text is None else text,
            actor_episodes=self.episodes, expected_matches=['a' * 32, 'b' * 32])

    def test_both_balanced_held_episodes_require_full_actor_proofs(self):
        result = self.evaluate()
        self.assertTrue(result['passed'])
        self.assertEqual([row['world'] for row in result['episodes']], [1,2])
        self.assertFalse(result['physical_input_exercised'] or result['expected_refusal_is_pass'])
        self.assertTrue(all(row['held_history_preserved'] and row['roots_closed_after_release'] for row in result['episodes']))
        self.assertEqual([row['proof_variant'] for row in result['episodes']], [evidence.PRESERVED]*2)

    def test_tracked_natural_removed_variant_and_mixed_world_variants_pass(self):
        for variants in ((evidence.NATURAL_REMOVED,)*2, (evidence.PRESERVED,evidence.NATURAL_REMOVED),
                (evidence.NATURAL_REMOVED,evidence.PRESERVED)):
            self.records, self.episodes = fixture(variants)
            with self.subTest(variants=variants):
                result = self.evaluate()
                self.assertEqual([row['proof_variant'] for row in result['episodes']], list(variants))
                self.assertTrue(all(row['original_token'] == row['restored_token'] for row in result['episodes']))

    def test_hover_shape_is_bound_to_position_delivery_before_press(self):
        original = deepcopy(self.records)
        for phase in ('position_observed', 'press_queued'):
            self.records = deepcopy(original);row = self.row(phase)
            row['preview_ids'] = [];row['preview_exact5'] = False;row['preview_empty'] = True
            with self.subTest(phase=phase), self.assertRaises(AssertionError): self.evaluate()

    def test_preexisting_exact_hover_can_survive_rematch_before_position_delivery(self):
        original = deepcopy(self.records)
        for world in (1, 2):
            for mask in range(8):
                self.records = deepcopy(original)
                for index, phase in enumerate(('setup', 'focused', 'position_queued')):
                    row = self.row(phase, world)
                    hovered = bool(mask & (1 << index))
                    row['preview_ids'] = [5] if hovered else []
                    row['preview_exact5'] = hovered;row['preview_empty'] = not hovered
                with self.subTest(world=world,mask=mask):
                    self.assertTrue(self.evaluate()['passed'])

    def test_prepress_hover_still_requires_exact_raw_cache_and_selected_hq(self):
        original = deepcopy(self.records)
        for phase in ('setup', 'focused', 'position_queued'):
            for key, value in (('current_ids', []), ('preview_ids', [6]),
                    ('preview_exact5', True), ('primary', True), ('mode', 1)):
                self.records = deepcopy(original);self.row(phase)[key] = value
                with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError):
                    self.evaluate()

    def test_death_mixed_sets_and_wrong_provenance_never_select_a_variant(self):
        original = deepcopy(self.records)
        for current, preview, phase in (([5],[],1), ([],[5],1), ([5],[5],3), ([],[],1),
                ([5],[5],0), ([5],[5],2)):
            self.records = deepcopy(original);row = self.row('dead_hq_retained')
            for stem, ids in (('current',current),('preview',preview)):
                row[stem+'_ids'] = ids;row[stem+'_exact5'] = bool(ids);row[stem+'_empty'] = not ids
            row['provenance_phase'] = phase
            with self.subTest(current=current,preview=preview,phase=phase), self.assertRaises(AssertionError): self.evaluate()

    def test_preserved_variant_cannot_change_to_empty_or_removed_after_death(self):
        original = deepcopy(self.records)
        for phase, change in (('hq_restored','current'), ('preview_ready','preview'), ('release_queued','phase')):
            self.records = deepcopy(original);row = self.row(phase)
            if change == 'phase': row['provenance_phase'] = 3
            else:
                row[change+'_ids'] = [];row[change+'_exact5'] = False;row[change+'_empty'] = True
            with self.subTest(phase=phase), self.assertRaises(AssertionError): self.evaluate()

    def test_removed_variant_cannot_reselect_current_or_switch_phase_before_up(self):
        self.records, self.episodes = fixture((evidence.NATURAL_REMOVED,)*2)
        original = deepcopy(self.records)
        for phase, change in (('hq_restored','current'), ('preview_ready','current'), ('release_queued','phase')):
            self.records = deepcopy(original);row = self.row(phase)
            if change == 'phase': row['provenance_phase'] = 1
            else:
                row['current_ids'] = [5];row['current_exact5'] = True;row['current_empty'] = False
            with self.subTest(phase=phase), self.assertRaises(AssertionError): self.evaluate()

    def test_missing_duplicate_and_reordered_suffix_stay_red(self):
        original = deepcopy(self.records)
        for kind in ('missing', 'duplicate', 'reorder'):
            self.records = deepcopy(original)
            i = next(i for i, (prefix, row) in enumerate(self.records) if prefix == evidence.PREFIX and row['event'] == 'released')
            if kind == 'missing': self.records.pop(i)
            if kind == 'duplicate': self.records.insert(i, deepcopy(self.records[i]))
            if kind == 'reorder': self.records[i], self.records[i + 1] = self.records[i + 1], self.records[i]
            with self.subTest(kind=kind), self.assertRaises(AssertionError): self.evaluate()

    def test_unchanged_live_guard_refusal_cannot_be_an_expected_pass(self):
        for suffix in ('Held click smoke failed: reason=guard',
                'retiring identity remains in live or unresolved click intent',
                'retiring identity remains in held gesture selection or cached type subset'):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(AssertionError, 'remains RED'):
                self.evaluate(render(self.records) + '\n' + suffix)
        self.records = self.records[:10]
        with self.assertRaises(AssertionError): self.evaluate()

    def test_queue_receipts_cannot_replace_actual_press_up_and_distinct_callbacks(self):
        original = deepcopy(self.records)
        for phase, key, value in (('pressed','owned_button',False), ('pressed','primary',False),
                ('pressed','update',120), ('released','update',135), ('released','owned_button',True),
                ('release_queued','input_sequence',2), ('pressed','update_scope','InputSystem.Update')):
            self.records = deepcopy(original);self.row(phase)[key] = value
            with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError): self.evaluate()

    def test_finite_frame_windows_and_setup_before_press(self):
        original = deepcopy(self.records)
        for phase, value in (('setup',131), ('position_queued',150), ('press_queued',152),
                ('pressed',155), ('held_checkpoint',153), ('dead_hq_retained',157),
                ('hq_restored',165), ('preview_ready',165), ('release_queued',164), ('released',168)):
            self.records = deepcopy(original);self.row(phase)['frame'] = value
            with self.subTest(phase=phase), self.assertRaises(AssertionError): self.evaluate()

    def test_admission_frontier163_or164_still_waits_two_frames_before_real_up(self):
        for restored in (163, 164):
            self.records, self.episodes = fixture()
            queued, released = max(165, restored + 2), max(165, restored + 2) + 1
            for phase in ('hq_restored', 'preview_ready'):
                self.row(phase, 2)['frame'] = restored
            self.row('release_queued', 2)['frame'] = queued
            for phase in ('released', 'input_closed', 'complete'):
                self.row(phase, 2)['frame'] = released
            for prefix, row in self.records:
                if prefix == 'ACTOR CORRECTION ' and row['world'] == 2:
                    if row['event'] == evidence.ACTOR_EVENTS[2]: row['frame'] = restored
                    if row['event'] == evidence.ACTOR_EVENTS[3]: row['frame'] = released
            self.episodes[1]['rows'][2]['frame'] = restored
            self.episodes[1]['rows'][3]['frame'] = released
            with self.subTest(restored=restored):
                self.assertTrue(self.evaluate()['passed'])
            if restored == 164:
                self.row('release_queued', 2)['frame'] = 165
                with self.assertRaisesRegex(AssertionError, 'frame contract'):
                    self.evaluate()

    def test_history_positions_modifiers_and_reselection_refuse(self):
        original = deepcopy(self.records)
        for phase, key, value in (('held_checkpoint','last_up_bits',bits(21)), ('hq_restored','mode',0),
                ('preview_ready','click_id',9), ('preview_ready','window_bits',bits(.5)),
                ('dead_hq_retained','down_position_bits',[bits(401),bits(300)]),
                ('release_queued','reference_position_bits',[bits(400),bits(301)]),
                ('preview_ready','context',True), ('preview_ready','drag',True),
                ('hq_restored','selectionWritesAfterPress',1), ('hq_restored','focus_group',4),
                ('released','focus_actor','100'), ('released','active_caster','101')):
            self.records = deepcopy(original);self.row(phase)[key] = value
            with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError): self.evaluate()

    def test_raw_typed_ghosts_extra_ids_wrong_key_and_early_selection_refuse(self):
        original = deepcopy(self.records)
        changes = (('pressed','preview_exact5',False), ('dead_hq_retained','current_empty',True),
            ('preview_ready','preview_ids',[5,9]), ('preview_ready','preview_ids',[]),
            ('preview_ready','current_ids',[]), ('released','preview_empty',False),
            ('released','current_ids',[]))
        for phase, key, value in changes:
            self.records = deepcopy(original);self.row(phase)[key] = value
            with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError): self.evaluate()

    def test_no_close_while_still_held_or_claimed_device_substitution(self):
        original = deepcopy(self.records)
        for phase, key, value in (('preview_ready','input_closed',True), ('released','ownership_scope','retained_scalar'),
                ('input_closed','owned_button',False), ('pressed','device','EE'),
                ('setup','input_source','added_mouse'), ('released','input_source','physical_mouse')):
            self.records = deepcopy(original);self.row(phase)[key] = value
            with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError): self.evaluate()

    def test_same_canonical_identity_allows_replacement_and_reused_physical_address(self):
        original = deepcopy(self.records)
        for phase, key, value in (('pressed','original_token',0), ('hq_restored','current_token',72),
                ('hq_restored','current_token',0),
                ('released','current_token',73), ('dead_hq_retained','current_actor','100'),
                ('dead_hq_retained','original_dead',False), ('complete','original_actor','101')):
            self.records = deepcopy(original);self.row(phase)[key] = value
            with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError): self.evaluate()
        self.records = deepcopy(original)
        for prefix, row in self.records:
            if prefix == evidence.PREFIX and row['world'] == 1 and row['sequence'] >= 9:
                row['current_actor'] = '100'
            elif prefix == 'ACTOR CORRECTION ' and row['world'] == 1 and row['frame'] >= 161:
                row['current_actor'] = '100'
        for row in self.episodes[0]['rows'][2:]:
            row['current_actor'] = '100'
        self.assertTrue(self.evaluate()['passed'])

    def test_consistently_changed_logical_token_cannot_masquerade_as_recreation(self):
        original = deepcopy(self.records)
        for changed in (0, 72):
            self.records = deepcopy(original)
            for prefix, row in self.records:
                if prefix == evidence.PREFIX and row['world'] == 1 and row['sequence'] >= 9:
                    row['current_token'] = changed
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                self.evaluate()
        self.records = deepcopy(original)
        result = self.evaluate()
        self.assertTrue(all(row['original_token'] == row['restored_token'] and
            row['canonical_identity_preserved'] for row in result['episodes']))

    def test_physical_actor_lifecycle_join_is_not_replaced_by_token_equality(self):
        self.row('hq_restored')['current_actor'] = '300'
        self.row('preview_ready')['current_actor'] = '300'
        for phase in ('release_queued','released','input_closed','complete'):
            self.row(phase)['current_actor'] = '300'
        with self.assertRaisesRegex(AssertionError, 'physical actor join'):
            self.evaluate()

    def test_accepted_down_natural_removal_and_original_up_epoch_required(self):
        original = deepcopy(self.records)
        for phase, key, value in (('pressed','accepted_down_serial',0), ('dead_hq_retained','provenance_phase',3),
                ('preview_ready','input_serial',3), ('released','accepted_down_serial',2),
                ('released','provenance_phase',3), ('released','input_serial',2)):
            self.records = deepcopy(original);self.row(phase)[key] = value
            with self.subTest(phase=phase,key=key), self.assertRaises(AssertionError): self.evaluate()

    def test_independent_actor_failure_source_join_and_crossworld_reset_refuse(self):
        self.episodes[1]['passed'] = False
        with self.assertRaisesRegex(AssertionError, 'independently passed'): self.evaluate()
        self.records, self.episodes = fixture();self.episodes[0]['rows'][2]['frame'] = 162
        with self.assertRaisesRegex(AssertionError, 'retained source'): self.evaluate()
        self.records, self.episodes = fixture();self.row('setup',2)['update'] = 1
        with self.assertRaisesRegex(AssertionError, 'regressed'): self.evaluate()
        self.records, self.episodes = fixture()
        actor_index = next(i for i, (prefix, row) in enumerate(self.records) if prefix == 'ACTOR CORRECTION ' and row['event'] == 'original_dead_hq_retained')
        value = self.records.pop(actor_index);self.records.insert(actor_index + 1,value)
        with self.assertRaisesRegex(AssertionError, 'source/frame'): self.evaluate()

    def test_duplicate_unknown_bool_numeric_nonfinite_and_malformed_json_refuse(self):
        text = render(self.records).replace('"schema":1', '"schema":1,"schema":1', 1)
        with self.assertRaisesRegex(AssertionError, 'duplicate JSON'): self.evaluate(text)
        original = deepcopy(self.records)
        for key, value in (('unobserved_cleanup',True), ('mode',True), ('original_token',True),
                ('now_bits',0x7f800000), ('window_bits',0x7fc00000), ('selector','0')):
            self.records = deepcopy(original);self.row('pressed')[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): self.evaluate()
        with self.assertRaises(AssertionError): self.evaluate('HELD CLICK {bad')


if __name__ == '__main__':
    unittest.main()
