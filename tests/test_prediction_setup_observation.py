"""Authored FlatBuffer controls for the pure reader; no DLL or process calls."""
import math
import struct
import unittest

from server.protobuf_wire import field_bytes, field_uint
from tools.prediction_setup_observation import (LabelRegistry, SetupObservationError, decode,
                                               label_names_from_config)


class Buffer:
    """Small forward writer for independent authored protocol fixtures."""
    def __init__(self):
        self.data = bytearray(4)

    def align(self, width=4):
        self.data.extend(b'\0' * (-len(self.data) % width))

    def table(self, fields, count=None):
        count = count if count is not None else max(fields, default=-1) + 1
        self.align(2)
        vtable = len(self.data)
        self.data.extend(struct.pack('<HH', 4 + 2 * count, 4 + 4 * count))
        self.data.extend(b''.join(struct.pack('<H', 4 + 4 * index if index in fields else 0)
                                  for index in range(count)))
        self.align()
        table = len(self.data)
        self.data.extend(struct.pack('<i', table - vtable) + b'\0' * (4 * count))
        return table, {index:table + 4 + index * 4 for index in fields}

    def vector(self, values, fmt='I'):
        self.align()
        start = len(self.data)
        self.data.extend(struct.pack('<I', len(values)))
        self.data.extend(b''.join(struct.pack('<' + fmt, value) for value in values))
        return start

    def pointer(self, field, target):
        struct.pack_into('<I', self.data, field, target - field)

    def string(self, text):
        self.align()
        start = len(self.data)
        raw = text.encode('utf-8') if isinstance(text, str) else text
        self.data.extend(struct.pack('<I', len(raw)) + raw + b'\0')
        return start

    def finish(self, root):
        self.pointer(0, root)
        return bytes(self.data)


def registry_blob(strings, sets):
    writer = Buffer()
    root, fields = writer.table((0, 1))
    strings_vector = writer.vector([0] * len(strings))
    writer.pointer(fields[0], strings_vector)
    for index, name in enumerate(strings):
        writer.pointer(strings_vector + 4 + 4 * index, writer.string(name))
    sets_vector = writer.vector([0] * len(sets))
    writer.pointer(fields[1], sets_vector)
    for index, labels in enumerate(sets):
        table, fields = writer.table((0,))
        writer.pointer(sets_vector + 4 + 4 * index, table)
        writer.pointer(fields[0], writer.vector(labels))
    return writer.finish(root)


def snapshot(frame=140, *, states=(), labels=(), times=(), omit=()):
    writer = Buffer()
    root, fields = writer.table((0, *(field for field in (4, 11, 27) if field not in omit)), count=28)
    struct.pack_into('<I', writer.data, fields[0], frame)
    locations = dict(root=root, fields=fields)
    for field, rows, fmt in ((4, states, 'I'), (11, labels, 'I'), (27, times, 'f')):
        if field in omit:
            continue
        table, component = writer.table((0, 1))
        writer.pointer(fields[field], table)
        ids, values = writer.vector([row[0] for row in rows]), writer.vector([row[1] for row in rows], fmt)
        writer.pointer(component[0], ids)
        writer.pointer(component[1], values)
        locations[field] = dict(table=table, ids=ids, values=values, fields=component)
    return writer.finish(root), locations


NAMES = ('Ground', 'ThreatToGround', 'Immobile', 'SettingUp', 'Deployed', 'UnsettingUp')
SETS = ((0, 1), (0, 1, 2, 3), (0, 1, 2, 4), (0, 1, 2, 5))


def config_blob(rows):
    return b''.join(field_bytes(6, field_bytes(1, name.encode('utf-8') if isinstance(name, str) else name) +
                               (field_uint(2, label) if label else b'')) for label, name in rows)


LABEL_NAMES = label_names_from_config(config_blob(enumerate(NAMES)))


class SetupObservationTests(unittest.TestCase):
    def setUp(self):
        self.registry = LabelRegistry(LABEL_NAMES)
        self.registry.observe(registry_blob(NAMES, SETS))

    def read(self, **kwargs):
        raw, _ = snapshot(**kwargs)
        return decode(raw, self.registry, expected_frame=kwargs.get('frame', 140))

    def test_real_phase_signals_are_distinct_from_identity_stability(self):
        # Same full ID throughout: only state, advancing timer and resolved names
        # distinguish successful setup/unsetup from an unchanged no-op actor.
        phases = ((139, 0, 0, None), (140, 11, 1, .05), (150, 11, 1, .55),
                  (200, 0, 2, None), (210, 11, 3, .05), (220, 11, 3, .55), (270, 0, 0, None))
        rows = []
        for frame, state, handle, elapsed in phases:
            result = self.read(frame=frame, states=((0x2000b, state),), labels=((0x2000b, handle),),
                               times=() if elapsed is None else ((0x2000b, elapsed),))
            self.assertEqual(result['frame'], frame)
            self.assertEqual(set(result['entities']), {0x2000b})
            rows.append(result['entities'][0x2000b])
        self.assertEqual(rows[0]['labels'], ['Ground', 'ThreatToGround'])
        self.assertEqual(rows[1]['labels'], ['Ground', 'ThreatToGround', 'Immobile', 'SettingUp'])
        self.assertGreater(rows[2]['setup_time'], rows[1]['setup_time'])
        self.assertIn('Deployed', rows[3]['labels'])
        self.assertNotIn('SettingUp', rows[3]['labels'])
        self.assertIn('UnsettingUp', rows[4]['labels'])
        self.assertNotIn('Deployed', rows[4]['labels'])
        self.assertGreater(rows[5]['setup_time'], rows[4]['setup_time'])
        self.assertEqual(rows[6]['labels'], rows[0]['labels'])

    def test_full_ids_and_sparse_components_join_by_id(self):
        result = self.read(states=((0x1000b, 0), (0x2000b, 11)),
                           labels=((0x2000b, 1), (0x1000b, 0)), times=((0x2000b, 1.25),))
        self.assertEqual(set(result['entities']), {0x1000b, 0x2000b})
        self.assertEqual(result['entities'][0x2000b]['setup_time'], 1.25)
        self.assertIsNone(result['entities'][0x1000b]['setup_time'])

    def test_zero_based_handles_are_not_shifted_or_aliased(self):
        self.assertEqual(self.registry.resolve(0), list(NAMES[:2]))
        self.assertEqual(self.registry.resolve(1)[-1], 'SettingUp')
        with self.assertRaises(SetupObservationError):
            self.registry.resolve(len(SETS))

    def test_explicit_label_keys_resolve_exact_utf8(self):
        registry = LabelRegistry(label_names_from_config(config_blob(((0, 'Ground'), (1, '設置')))))
        registry.observe(registry_blob(('Ground', '設置'), ((0,), (1,))))
        self.assertEqual(registry.resolve(0), ['Ground'])
        self.assertEqual(registry.resolve(1), ['設置'])

    def test_full_cumulative_update_appends_without_rebasing(self):
        registry = LabelRegistry(LABEL_NAMES)
        registry.observe(registry_blob(NAMES[:2], SETS[:1]))
        registry.observe(registry_blob(NAMES, SETS))
        self.assertEqual(registry.resolve(0), list(NAMES[:2]))
        self.assertEqual(registry.resolve(3), ['Ground', 'ThreatToGround', 'Immobile', 'UnsettingUp'])
        registry.observe(registry_blob(NAMES, SETS))
        self.assertEqual(registry.sets, SETS)

    def test_delta_is_rejected_instead_of_rebased(self):
        with self.assertRaisesRegex(SetupObservationError, 'shrank'):
            self.registry.observe(registry_blob(('UnsettingUp',), ((0,),)))
        self.assertEqual(self.registry.strings, NAMES)
        self.assertEqual(self.registry.sets, SETS)

    def test_existing_string_prefix_cannot_change(self):
        with self.assertRaisesRegex(SetupObservationError, 'prefix'):
            self.registry.observe(registry_blob(('FabricatedGround', *NAMES[1:]), SETS))
        self.assertEqual(self.registry.resolve(0), list(NAMES[:2]))

    def test_existing_set_prefix_cannot_change(self):
        with self.assertRaisesRegex(SetupObservationError, 'prefix'):
            self.registry.observe(registry_blob(NAMES, ((1,), *SETS[1:])))
        self.assertEqual(self.registry.sets, SETS)

    def test_undeclared_label_key_is_rejected_atomically(self):
        with self.assertRaisesRegex(SetupObservationError, 'undeclared config label key'):
            self.registry.observe(registry_blob((*NAMES, 'Other'), (*SETS, (100,))))
        self.assertEqual(self.registry.strings, NAMES)

    def test_unknown_handle_is_rejected_without_one_based_fallback(self):
        raw, _ = snapshot(states=((11, 0),), labels=((11, 99),))
        with self.assertRaisesRegex(SetupObservationError, 'unknown label-set'):
            decode(raw, self.registry, expected_frame=140)

    def test_duplicate_label_reference_is_rejected(self):
        with self.assertRaisesRegex(SetupObservationError, 'duplicate label'):
            LabelRegistry(LABEL_NAMES).observe(registry_blob(NAMES, ((0, 0),)))

    def test_setup_missing_actual_timer_signal_stays_none(self):
        for omit in ((), (27,)):
            with self.subTest(omit=omit):
                row = self.read(states=((11, 11),), labels=((11, 1),), omit=omit)['entities'][11]
                self.assertEqual(row['state'], 11)
                self.assertIsNone(row['setup_time'])
                self.assertEqual(row['label_keys'], list(SETS[1]))
                self.assertIn('SettingUp', row['labels'])

    def test_setup_missing_actual_label_signal_stays_missing(self):
        for omit in ((), (11,)):
            with self.subTest(omit=omit):
                row = self.read(states=((11, 11),), times=((11, .05),), omit=omit)['entities'][11]
                self.assertEqual(row['state'], 11)
                self.assertAlmostEqual(row['setup_time'], .05)
                self.assertIsNone(row['label_handle'])
                self.assertEqual(row['label_keys'], [])
                self.assertEqual(row['labels'], [])

    def test_inactive_missing_components_stay_missing(self):
        result = self.read(states=((11, 0),), labels=((12, 0),), times=((13, 0.),))['entities']
        self.assertEqual(result[11], dict(state=0, label_handle=None, label_keys=[], labels=[], setup_time=None))
        self.assertEqual(result[12]['state'], None)
        self.assertEqual(result[13]['setup_time'], 0.)
        self.assertEqual(result[13]['labels'], [])

    def test_zero_timer_is_not_fabricated_progress(self):
        result = self.read(states=((11, 11),), labels=((11, 1),), times=((11, 0.),))
        self.assertEqual(result['entities'][11]['setup_time'], 0.)

    def test_nonfinite_and_negative_timer_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf, -.01):
            with self.subTest(value=value), self.assertRaisesRegex(SetupObservationError, 'elapsed time'):
                self.read(times=((11, value),))

    def test_duplicate_entity_ids_rejected_in_each_sparse_component(self):
        for keyword, value in (('states', 0), ('labels', 0), ('times', .5)):
            with self.subTest(component=keyword), self.assertRaisesRegex(SetupObservationError, 'duplicate sparse'):
                self.read(**{keyword:((11, value), (11, value))})

    def test_mismatched_sparse_vector_counts_rejected(self):
        for field in (4, 11, 27):
            raw, locations = snapshot(states=((11, 0),), labels=((11, 0),), times=((11, .05),))
            changed = bytearray(raw)
            struct.pack_into('<I', changed, locations[field]['values'], 0)
            with self.subTest(field=field), self.assertRaisesRegex(SetupObservationError, 'counts disagree'):
                decode(bytes(changed), self.registry, expected_frame=140)

    def test_expected_frame_is_exact(self):
        raw, _ = snapshot(frame=140)
        with self.assertRaisesRegex(SetupObservationError, 'frame differs'):
            decode(raw, self.registry, expected_frame=139)
        for value in (True, -1, 2**32, 140.0):
            with self.subTest(expected=value), self.assertRaises(SetupObservationError):
                decode(raw, self.registry, expected_frame=value)

    def test_absent_optional_tables_are_empty_not_fabricated(self):
        self.assertEqual(self.read(omit=(4, 11, 27)), dict(frame=140, entities={}))

    def test_bad_root_and_short_inputs_rejected(self):
        raw, _ = snapshot()
        for changed in (b'', b'\0' * 4, b'\0' * 8, struct.pack('<I', 0xfffffff0) + raw[4:],
                        struct.pack('<I', 3) + raw[4:], bytearray(raw)):
            with self.subTest(value=repr(changed[:8])), self.assertRaises(SetupObservationError):
                decode(changed, self.registry, expected_frame=140)

    def test_truncated_vectors_and_oversized_counts_rejected(self):
        raw, locations = snapshot(times=((11, .05),))
        corrupt = bytearray(raw)
        struct.pack_into('<I', corrupt, locations[27]['values'], 0xffffffff)
        for changed in (raw[:-1], bytes(corrupt)):
            with self.subTest(size=len(changed)), self.assertRaises(SetupObservationError):
                decode(changed, self.registry, expected_frame=140)

    def test_field_offset_cannot_escape_table(self):
        raw, locations = snapshot()
        changed = bytearray(raw)
        table = locations['root']
        vtable = table - struct.unpack_from('<i', raw, table)[0]
        struct.pack_into('<H', changed, vtable + 4 + 2 * 27, 0xffff)
        with self.assertRaisesRegex(SetupObservationError, 'outside FlatBuffer'):
            decode(bytes(changed), self.registry, expected_frame=140)

    def test_invalid_registry_utf8_and_terminator_rejected(self):
        for blob in (registry_blob((b'\xff',), ((0,),)), registry_blob(('Ground',), ((0,),))):
            changed = blob if b'\xff' in blob else blob.replace(b'Ground\0', b'Ground!')
            with self.subTest(invalid=changed), self.assertRaises(SetupObservationError):
                LabelRegistry(LABEL_NAMES).observe(changed)

    def test_failed_registry_update_does_not_mutate_raw_or_registry(self):
        raw = registry_blob((*NAMES, 'new'), (*SETS, (12345,)))
        before = bytes(raw)
        with self.assertRaises(SetupObservationError):
            self.registry.observe(raw)
        self.assertEqual(raw, before)
        self.assertEqual(self.registry.strings, NAMES)
        self.assertEqual(self.registry.sets, SETS)

    def test_decode_preserves_raw_and_registry(self):
        raw, _ = snapshot(states=((11, 11),), labels=((11, 1),), times=((11, .05),))
        before = bytes(raw)
        decode(raw, self.registry, expected_frame=140)
        self.assertEqual(raw, before)
        self.assertEqual(self.registry.sets, SETS)


class ExplicitConfigLabelTests(unittest.TestCase):
    # These are the shipped sparse IDs, whose declaration positions26..31 differ
    # from their IDs. No test borrows the decoder's mapping algorithm.
    ROWS = tuple(enumerate(('DO_NOT_USE', 'Ground', 'Air', 'Ranged', 'Cloaked', 'Detector',
                           'Immobile', 'Deployed', 'Building', 'SettingUp', 'UnsettingUp',
                           'Containing', 'Container', 'OutOfCombat', 'CoreExpansion', 'ThreatToAir',
                           'ThreatToGround', 'Overclocked', 'Hover', 'Worker', 'ExcludeFromAllArmy',
                           'AlwaysReveal', 'Small', 'Expansion', 'VariableBlocker', 'Recall'))) + (
        (29, 'Harassment'), (30, 'Anti-Big'), (31, 'SmallExtraDmgTaken'),
        (34, 'CoreUnit'), (35, 'Big'), (36, 'Turrets'))

    def test_sparse_ids_do_not_alias_compact_string_positions(self):
        names = label_names_from_config(config_blob(self.ROWS))
        registry = LabelRegistry(names)
        registry.observe(registry_blob(tuple(name for _, name in self.ROWS),
                                      ((29,), (30,), (31,), (34,), (35,), (36,))))
        expected = ('Harassment', 'Anti-Big', 'SmallExtraDmgTaken', 'CoreUnit', 'Big', 'Turrets')
        raw, _ = snapshot(states=tuple((i, 0) for i in range(6)), labels=tuple((i, i) for i in range(6)))
        decoded = decode(raw, registry, expected_frame=140)['entities']
        for handle, ((label, _), name) in enumerate(zip(self.ROWS[-6:], expected)):
            with self.subTest(key=label):
                self.assertEqual(registry.resolve(handle), [name])
                self.assertEqual(decoded[handle]['labels'], [name])
                self.assertEqual(decoded[handle]['label_keys'], [label])
        self.assertNotEqual(decoded[0]['labels'], ['CoreUnit'])

    def test_raw_key_order_is_preserved_with_names(self):
        registry = LabelRegistry(label_names_from_config(config_blob(self.ROWS)))
        registry.observe(registry_blob(tuple(name for _, name in self.ROWS), ((35, 14, 8),)))
        raw, _ = snapshot(labels=((11, 0),))
        row = decode(raw, registry, expected_frame=140)['entities'][11]
        self.assertEqual(row['label_keys'], [35, 14, 8])
        self.assertEqual(row['labels'], ['Big', 'CoreExpansion', 'Building'])

    def test_actual_completion_edge_shape_preserves_missing_timer(self):
        registry = LabelRegistry(label_names_from_config(config_blob(self.ROWS)))
        keys = ((1, 16, 13), (1, 9, 16, 13, 6), (1, 16, 13, 6, 7), (1, 16, 13, 6, 10))
        registry.observe(registry_blob(tuple(name for _, name in self.ROWS), keys))
        for start, active, finished, effect in ((189, 1, 2, 'SettingUp'), (259, 3, 0, 'UnsettingUp')):
            rows = []
            for frame, state, handle, timer in ((start, 11, active, 2.45),
                                                (start + 1, 11, active, None),
                                                (start + 2, 0, finished, None)):
                raw, _ = snapshot(frame=frame, states=((10, state),), labels=((10, handle),),
                                  times=() if timer is None else ((10, timer),))
                rows.append(decode(raw, registry, expected_frame=frame)['entities'][10])
            with self.subTest(missing_timer_frame=start + 1):
                self.assertAlmostEqual(rows[0]['setup_time'], 2.45)
                self.assertEqual(rows[1]['state'], 11)
                self.assertIsNone(rows[1]['setup_time'])
                self.assertNotEqual(rows[1]['setup_time'], 0.)
                self.assertEqual(rows[1]['label_keys'], list(keys[active]))
                self.assertIn(effect, rows[1]['labels'])
                self.assertEqual(rows[2]['state'], 0)
                self.assertNotIn(effect, rows[2]['labels'])
                self.assertIn('OutOfCombat', rows[2]['labels'])

    def test_missing_timer_and_actual_zero_remain_distinct(self):
        registry = LabelRegistry(label_names_from_config(config_blob(self.ROWS)))
        registry.observe(registry_blob(tuple(name for _, name in self.ROWS), ((1, 16, 13),)))
        zero, _ = snapshot(frame=140, states=((10, 11),), labels=((10, 0),), times=((10, 0.),))
        missing, _ = snapshot(frame=190, states=((10, 11),), labels=((10, 0),))
        self.assertEqual(decode(zero, registry, expected_frame=140)['entities'][10]['setup_time'], 0.)
        self.assertIsNone(decode(missing, registry, expected_frame=190)['entities'][10]['setup_time'])

    def test_config_names_are_immutable_and_in_declaration_order(self):
        names = label_names_from_config(config_blob(((35, 'Big'), (1, 'Ground'), (0, 'DO_NOT_USE'))))
        self.assertEqual(tuple(names.items()), ((35, 'Big'), (1, 'Ground'), (0, 'DO_NOT_USE')))
        with self.assertRaises(TypeError):
            names[35] = 'Fabricated'
        registry = LabelRegistry(names)
        registry.observe(registry_blob(('Big', 'Ground', 'DO_NOT_USE'), ((35, 1),)))
        self.assertEqual(registry.resolve(0), ['Big', 'Ground'])

    def test_constructor_freezes_caller_map(self):
        source = {35:'Big', 1:'Ground'}
        registry = LabelRegistry(source)
        source[35] = 'Fabricated'
        registry.observe(registry_blob(('Big', 'Ground'), ((35,),)))
        self.assertEqual(registry.resolve(0), ['Big'])
        with self.assertRaises(TypeError):
            registry.label_names[35] = 'Fabricated'

    def test_registry_name_order_must_match_explicit_config(self):
        registry = LabelRegistry(label_names_from_config(config_blob(((35, 'Big'), (1, 'Ground')))))
        for strings in (('Ground', 'Big'), ('Fabricated', 'Ground'), ('Big', 'Ground', 'Extra')):
            with self.subTest(strings=strings), self.assertRaisesRegex(SetupObservationError, 'declaration order'):
                registry.observe(registry_blob(strings, ((35,),)))
        self.assertEqual(registry.strings, ())
        self.assertEqual(registry.sets, ())

    def test_undeclared_numeric_hole_is_not_string_position(self):
        registry = LabelRegistry(label_names_from_config(config_blob(self.ROWS)))
        for label in (26, 27, 28, 32, 33, 100):
            with self.subTest(label=label), self.assertRaisesRegex(SetupObservationError, 'undeclared'):
                registry.observe(registry_blob(tuple(name for _, name in self.ROWS), ((label,),)))

    def test_duplicate_config_ids_and_names_rejected(self):
        for rows in (((1, 'Ground'), (1, 'Air')), ((1, 'Ground'), (2, 'Ground')),
                     ((0, 'DO_NOT_USE'), (0, 'Other'))):
            with self.subTest(rows=rows), self.assertRaisesRegex(SetupObservationError, 'duplicate'):
                label_names_from_config(config_blob(rows))

    def test_duplicate_singular_config_fields_rejected(self):
        for row in (field_bytes(1, b'Ground') * 2 + field_uint(2, 1),
                    field_bytes(1, b'Ground') + field_uint(2, 1) * 2):
            with self.subTest(row=row), self.assertRaisesRegex(SetupObservationError, 'duplicate'):
                label_names_from_config(field_bytes(6, row))

    def test_invalid_config_utf8_empty_nul_and_long_names_rejected(self):
        for name in (b'\xff', b'', b'Ground\0Fabricated', b'a' * 4097):
            with self.subTest(size=len(name)), self.assertRaises(SetupObservationError):
                label_names_from_config(config_blob(((1, name),)))

    def test_malformed_config_wire_and_id_bounds_rejected(self):
        for raw in (b'', b'\x32\x80', field_uint(6, 1), field_bytes(6, field_uint(1, 1)),
                    field_bytes(6, field_bytes(1, b'Ground') + field_bytes(2, b'1')),
                    config_blob(((2**32, 'Overflow'),)), field_bytes(6, field_uint(2, 1))):
            with self.subTest(raw=raw[:20]), self.assertRaises(SetupObservationError):
                label_names_from_config(raw)

    def test_config_map_is_required(self):
        for value in (None, {}, [], {True:'Ground'}, {1:''}, {1:'\ud800'}):
            with self.subTest(value=repr(value)), self.assertRaises(SetupObservationError):
                LabelRegistry(value)


if __name__ == '__main__':
    unittest.main()
