"""Synthetic cosmetic matrices only; no recovered game catalog rows or assets."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid

from server.cosmetics import CosmeticCatalog, CosmeticError, MAX_CATALOG_BYTES, MAX_ITEMS
from server.protobuf_wire import get_repeated_bytes, get_repeated_uint, get_uint, parse_fields


def catalog_fixture():
    # IDs/labels are authored; order deliberately differs from sorted slot IDs.
    order = [108, 103, 115, 101, 112, 106, 117, 102, 110, 104, 116, 105, 111, 109, 107, 113, 114]
    items, slots = [], []
    emotes = [50001 + i for i in range(8, 12)] + [60001 + i for i in range(8, 12)]
    for index, slot in enumerate(order):
        compatible, default = [], 0
        if index < 14:
            default = 50001 + index
            compatible = emotes if 8 <= index < 12 else [default, 60001 + index]
            label = 208 if 8 <= index < 12 else 200 + index
            items.extend(dict(id=item, entitlement=0 if index % 2 else 90000 + index, label=label)
                         for item in (default, 60001 + index))
        slots.append(dict(id=slot, default_item=default, compatible_items=list(compatible)))
    return dict(schema=1, build=37822, native_slot_order=order, items=list(reversed(items)),
                slots=list(reversed(slots)), roles=dict(portrait=order[4], banner=order[5]))


def encode(data):
    return json.dumps(data, separators=(',', ':')).encode('utf-8')


def defaults(data):
    by_slot = {row['id']: row['default_item'] for row in data['slots']}
    return [(slot, by_slot[slot]) for slot in data['native_slot_order']]


class CosmeticCatalogTests(unittest.TestCase):
    def setUp(self):
        self.data = catalog_fixture()
        self.raw = encode(self.data)
        self.book = CosmeticCatalog.from_bytes(self.raw)

    def test_defaults_retain_all_slots_empty_slots_and_role_identity(self):
        snapshot = self.book.normalize_local({})
        self.assertEqual(snapshot.slots, tuple(defaults(self.data)))
        self.assertEqual(len(snapshot.slots), 17)
        self.assertEqual(snapshot.slots[-3:], tuple((slot, 0) for slot in self.data['native_slot_order'][-3:]))
        self.assertEqual(snapshot.keys, tuple(range(50001, 50015)))
        # The two authored announcer-like slots are kept beyond the first12.
        self.assertEqual(snapshot.slots[12:14], tuple(defaults(self.data)[12:14]))
        self.assertEqual((snapshot.portrait, snapshot.banner), (50005, 50006))
        self.assertEqual(snapshot.catalog_sha256, hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(self.book.normalize_local(), snapshot)
        self.assertEqual(self.book.normalize_local([(slot, 0) for slot in self.book.native_slot_order]), snapshot)
        self.assertEqual(self.book.validate_selection(list(reversed(snapshot.slots))), snapshot)

    def test_swapped_equivalent_slots_have_exact_ordered_service_zero_encoding(self):
        selection = defaults(self.data)
        left, right = selection[8], selection[11]
        selection[8], selection[11] = (left[0], right[1]), (right[0], left[1])
        snapshot = self.book.validate_selection(dict(reversed(selection)))
        self.assertEqual(snapshot.slots, tuple(selection))
        self.assertEqual(snapshot.keys[8:12], (50012, 50010, 50011, 50009))
        # Independent fixed wire oracle for these authored IDs: packed field3,
        # 14 three-byte varints. No field1(service0) or field2 appears.
        expected = bytes.fromhex('1a2a d18603 d28603 d38603 d48603 d58603 d68603 d78603 d88603 '
                                 'dc8603 da8603 db8603 d98603 dd8603 de8603')
        self.assertEqual(snapshot.entitlement, expected)
        self.assertEqual(snapshot.deck_entitlement, b'\x1a\x2c' + expected)
        fields = parse_fields(snapshot.entitlement)
        self.assertEqual([(field.number, field.wire_type) for field in fields], [(3, 2)])
        self.assertEqual(get_uint(snapshot.entitlement, 1), 0)
        self.assertEqual(get_repeated_uint(snapshot.entitlement, 3), snapshot.keys)
        self.assertEqual(get_repeated_bytes(snapshot.deck_entitlement, 3), (expected,))
        self.assertNotEqual(snapshot.keys, tuple(sorted(snapshot.keys)))

    def test_local_missing_and_zero_defaults_are_distinct_from_strict_network(self):
        portrait_slot = self.book.roles['portrait']
        snapshot = self.book.normalize_local({portrait_slot: 60005})
        self.assertEqual(snapshot.portrait, 60005)
        self.assertEqual(dict(snapshot.slots)[self.book.roles['banner']], 50006)
        for incomplete in ({}, {portrait_slot: 60005}, defaults(self.data)[:-1]):
            with self.subTest(incomplete=incomplete), self.assertRaisesRegex(CosmeticError, 'incomplete'):
                self.book.validate_selection(incomplete)
        all_zero = [(slot, 0) for slot in self.book.native_slot_order]
        with self.assertRaisesRegex(CosmeticError, 'zero cosmetic'):
            self.book.validate_selection(all_zero)

    def test_duplicate_items_rejected_even_when_matrix_allows_both_slots(self):
        selection = defaults(self.data)
        selection[9] = (selection[9][0], selection[8][1])
        with self.assertRaisesRegex(CosmeticError, 'duplicate nonzero'):
            self.book.validate_selection(selection)
        # Do not repair a partial emote selection by silently reassigning defaults.
        with self.assertRaisesRegex(CosmeticError, 'duplicate nonzero'):
            self.book.normalize_local({selection[9][0]: selection[8][1]})

    def test_unknown_wrong_slot_and_empty_slot_items_rejected_for_both_paths(self):
        for index, item, error in ((0, 0xffffffff, 'unknown'), (0, 50002, 'wrong-slot'),
                                   (16, 50001, 'wrong-slot')):
            selection = defaults(self.data)
            selection[index] = (selection[index][0], item)
            for method in (self.book.normalize_local, self.book.validate_selection):
                with self.subTest(index=index, method=method.__name__), self.assertRaisesRegex(CosmeticError, error):
                    method(selection)

    def test_catalog_and_snapshot_do_not_expose_mutable_roots(self):
        selection = [list(pair) for pair in defaults(self.data)]
        snapshot = self.book.validate_selection(selection)
        selection[0][1] = 60001
        self.data['native_slot_order'].reverse()
        self.data['slots'][0]['compatible_items'].append(0xffffffff)
        self.assertEqual(snapshot.slots[0], (108, 50001))
        self.assertEqual(self.book.native_slot_order[0], 108)
        with self.assertRaises(FrozenInstanceError): snapshot.portrait = 1
        with self.assertRaises(FrozenInstanceError): self.book.sha256 = 'changed'
        with self.assertRaises(TypeError): self.book.items[1] = self.book.items[50001]
        with self.assertRaises(TypeError): self.book.slots[108] = self.book.slots[103]
        with self.assertRaises(TypeError): self.book.roles['portrait'] = 108
        with self.assertRaises(FrozenInstanceError): self.book.items[50001].entitlement = 1
        with self.assertRaises(FrozenInstanceError): self.book.slots[108].default_item = 1
        self.assertIsInstance(self.book.slots[108].compatible_items, frozenset)
        self.assertIsInstance(snapshot.slots, tuple)
        self.assertIsInstance(snapshot.keys, tuple)
        self.assertIsInstance(snapshot.entitlement, bytes)

    def test_compatibility_comes_from_exported_matrix_not_label_or_entitlement(self):
        data = copy.deepcopy(self.data)
        # Metadata alone neither equips an item nor constrains the matrix.
        alternative = next(row for row in data['items'] if row['id'] == 60001)
        alternative.update(label=999999, entitlement=0xffffffff)
        book = CosmeticCatalog.from_bytes(encode(data))
        selected = book.normalize_local({108: 60001})
        self.assertEqual(selected.keys[0], 60001)
        self.assertNotIn(0xffffffff, get_repeated_uint(selected.entitlement, 3))

    def test_selection_rejects_duplicate_slots_invalid_shapes_and_scalar_types(self):
        selection = defaults(self.data)
        bad = [None, 'not a selection', iter(selection), selection + [selection[0]],
               selection[:-1] + [selection[0]], [[108]], [[108, 50001, 0]],
               [[999999, 50001]], [[True, 50001]], [[108, True]], [[108, False]],
               [[108, -1]], [[108, 1 << 32]], [[108, 1.0]], [[108, '50001']],
               [[0, 50001]], [[1 << 32, 50001]], {'108': 50001}]
        for invalid in bad:
            for method in (self.book.normalize_local, self.book.validate_selection):
                with self.subTest(value=repr(invalid), method=method.__name__), self.assertRaises(CosmeticError):
                    method(invalid)

    def test_catalog_rejects_unknown_missing_and_duplicate_json_fields(self):
        for data in (dict(self.data, extra=True), {key: value for key, value in self.data.items() if key != 'roles'},
                     dict(self.data, roles=dict(portrait=108, banner=103, extra=101))):
            with self.subTest(data=data.keys()), self.assertRaisesRegex(CosmeticError, 'fields'):
                CosmeticCatalog.from_bytes(encode(data))
        for raw in (b'{"schema":1,"schema":1}', self.raw.replace(b'"id":', b'"id":1,"id":', 1)):
            with self.assertRaisesRegex(CosmeticError, 'duplicate'):
                CosmeticCatalog.from_bytes(raw)

    def test_catalog_rejects_invalid_identity_order_defaults_roles_and_matrix(self):
        mutations = [
            lambda d: d.update(schema=True), lambda d: d.update(schema=2),
            lambda d: d.update(build=True), lambda d: d.update(build=0),
            lambda d: d['native_slot_order'].pop(),
            lambda d: d['native_slot_order'].__setitem__(0, d['native_slot_order'][1]),
            lambda d: d['native_slot_order'].__setitem__(0, 999999),
            lambda d: d['native_slot_order'].__setitem__(0, True),
            lambda d: d['slots'].pop(), lambda d: d['slots'].append(d['slots'][0]),
            lambda d: d['slots'][0].update(id=d['slots'][1]['id']),
            lambda d: d['slots'][0].update(default_item=50001),
            lambda d: d['slots'][-1].update(default_item=0),
            lambda d: d['slots'][-1].update(default_item=50002),
            lambda d: d['slots'][-1]['compatible_items'].append(999999),
            lambda d: d['slots'][-1]['compatible_items'].append(d['slots'][-1]['compatible_items'][0]),
            lambda d: d['items'].append(d['items'][0]),
            lambda d: d['items'].append(dict(id=999999, entitlement=0, label=500)),
            lambda d: d['items'][0].update(id=0),
            lambda d: d['items'][0].update(label=0),
            lambda d: d['items'][0].update(entitlement=-1),
            lambda d: d.update(items=[]),
            lambda d: d['roles'].update(portrait=999999),
            lambda d: d['roles'].update(portrait=d['roles']['banner']),
            lambda d: d['roles'].update(portrait=d['native_slot_order'][-1]),
            lambda d: d['roles'].update(portrait=True),
        ]
        for index, mutate in enumerate(mutations):
            data = copy.deepcopy(self.data)
            mutate(data)
            with self.subTest(mutation=index), self.assertRaises(CosmeticError):
                CosmeticCatalog.from_bytes(encode(data))
        duplicate_defaults = copy.deepcopy(self.data)
        emote_slots = [row for row in duplicate_defaults['slots'] if row['id'] in self.data['native_slot_order'][8:12]]
        emote_slots[0]['default_item'] = emote_slots[1]['default_item']
        with self.assertRaisesRegex(CosmeticError, 'duplicate cosmetic default'):
            CosmeticCatalog.from_bytes(encode(duplicate_defaults))

    def test_catalog_rejects_scalar_coercions_and_wrong_collection_types(self):
        for value in (True, False, -1, 1 << 32, 1.0, '1', None):
            for field in ('id', 'entitlement', 'label'):
                data = copy.deepcopy(self.data)
                data['items'][0][field] = value
                with self.subTest(value=value, field=field), self.assertRaises(CosmeticError):
                    CosmeticCatalog.from_bytes(encode(data))
        for path in ('items', 'slots', 'native_slot_order'):
            data = copy.deepcopy(self.data)
            data[path] = {}
            with self.subTest(path=path), self.assertRaises(CosmeticError):
                CosmeticCatalog.from_bytes(encode(data))
        for field in ('id', 'default_item', 'compatible_items'):
            data = copy.deepcopy(self.data)
            data['slots'][0][field] = True
            with self.subTest(field=field), self.assertRaises(CosmeticError):
                CosmeticCatalog.from_bytes(encode(data))

    def test_bounded_bytes_json_depth_and_collection_sizes(self):
        for raw in (b'', b'null', b'[]', b'{', b'\xff', b' ' * (MAX_CATALOG_BYTES + 1),
                    b'[' * 2000 + b'0' + b']' * 2000, self.raw.replace(b'37822', b'NaN'),
                    bytearray(self.raw), self.raw.decode()):
            with self.subTest(kind=type(raw), size=len(raw)), self.assertRaises(CosmeticError):
                CosmeticCatalog.from_bytes(raw)
        # The byte bound is inclusive; harmless trailing JSON whitespace fits.
        self.assertEqual(CosmeticCatalog.from_bytes(self.raw.ljust(MAX_CATALOG_BYTES, b' ')).normalize_local().keys,
                         self.book.normalize_local().keys)
        for field in ('items', 'compatible_items'):
            data = copy.deepcopy(self.data)
            if field == 'items':
                data[field] = [data['items'][0]] * (MAX_ITEMS + 1)
            else:
                data['slots'][-1][field] = [50001] * (MAX_ITEMS + 1)
            with self.subTest(field=field), self.assertRaisesRegex(CosmeticError, 'collection limit'):
                CosmeticCatalog.from_bytes(encode(data))

    def test_directory_loader_uses_same_hash_validation_and_bounded_read(self):
        base = Path(__file__).resolve().parents[1] / 'local/test-cosmetics'
        directory = base / uuid.uuid4().hex
        directory.mkdir(parents=True)
        try:
            path = directory / 'cosmetic-catalog.json'
            path.write_bytes(self.raw)
            loaded = CosmeticCatalog(directory)
            self.assertEqual(loaded.sha256, self.book.sha256)
            self.assertEqual(loaded.normalize_local(), self.book.normalize_local())
            path.write_bytes(b' ' * (MAX_CATALOG_BYTES + 1))
            with self.assertRaisesRegex(CosmeticError, 'byte limit'):
                CosmeticCatalog(directory)
        finally:
            target = directory.resolve()
            self.assertEqual(target.parent, base.resolve())
            self.assertEqual(len(target.name), 32)
            shutil.rmtree(target)


if __name__ == '__main__':
    unittest.main()
