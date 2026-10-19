"""Validate a locally exported cosmetic catalog and freeze a human loadout.

The native slot order and compatibility matrix are data, not numeric-ID rules.
Flat cosmetic keys are positional for equivalent slots, so never sort/deduplicate
them. This module does not grant inventory or modify an account/deck/profile.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from .protobuf_wire import field_bytes, field_packed_uint

BUILD = 37822
SLOT_COUNT = 17
MAX_ITEMS = 4096
MAX_CATALOG_BYTES = 2 * 1024 * 1024


class CosmeticError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise CosmeticError(message)


def _uint(value, name, *, positive=False):
    _require(type(value) is int and int(positive) <= value <= 0xffffffff,
             f'invalid cosmetic {name}: expected uint32')
    return value


def _object(value, keys, name):
    _require(type(value) is dict and set(value) == set(keys),
             f'invalid cosmetic {name} fields')
    return value


def _array(value, minimum, maximum, name):
    _require(type(value) is list and minimum <= len(value) <= maximum,
             f'cosmetic {name} collection limit')
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate cosmetic catalog JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise CosmeticError('non-finite cosmetic catalog JSON number')


@dataclass(frozen=True, slots=True)
class CosmeticItem:
    id: int
    entitlement: int
    label: int


@dataclass(frozen=True, slots=True)
class CosmeticSlot:
    id: int
    default_item: int
    compatible_items: frozenset[int]


@dataclass(frozen=True, slots=True)
class CosmeticSnapshot:
    """An owned complete selection; slots and keys retain native slot order.

    entitlement is one CommonPb.Entitlement message, with service ID omitted
    (proto3 default0). deck_entitlement is its CommonPb.Deck field3 wrapper.
    Item.entitlement metadata is deliberately not serialized here.
    """
    catalog_sha256: str
    slots: tuple[tuple[int, int], ...]
    keys: tuple[int, ...]
    portrait: int
    banner: int
    entitlement: bytes

    @property
    def deck_entitlement(self):
        return field_bytes(3, self.entitlement)


@dataclass(frozen=True, slots=True, init=False, eq=False)
class CosmeticCatalog:
    sha256: str
    native_slot_order: tuple[int, ...]
    items: Mapping[int, CosmeticItem]
    slots: Mapping[int, CosmeticSlot]
    roles: Mapping[str, int]

    def __init__(self, directory):
        # Bound the read itself, including a file that grows after opening.
        with (Path(directory) / 'cosmetic-catalog.json').open('rb') as stream:
            raw = stream.read(MAX_CATALOG_BYTES + 1)
        self._initialize(raw)

    @classmethod
    def from_bytes(cls, raw):
        result = object.__new__(cls)
        result._initialize(raw)
        return result

    def _initialize(self, raw):
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_CATALOG_BYTES,
                 'cosmetic catalog byte limit')
        try:
            data = json.loads(raw, object_pairs_hook=_unique_object,
                              parse_constant=_invalid_constant)
        except CosmeticError:
            raise
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise CosmeticError('invalid cosmetic catalog JSON') from exc
        _object(data, ('schema', 'build', 'native_slot_order', 'items', 'slots', 'roles'), 'catalog')
        _require(type(data['schema']) is int and data['schema'] == 1 and
                 type(data['build']) is int and data['build'] == BUILD,
                 'unsupported cosmetic catalog schema/build')

        order = tuple(_uint(value, 'slot ID', positive=True) for value in
                      _array(data['native_slot_order'], SLOT_COUNT, SLOT_COUNT, 'native slot order'))
        _require(len(set(order)) == SLOT_COUNT, 'duplicate cosmetic native slot order ID')
        items = {}
        for row in _array(data['items'], 1, MAX_ITEMS, 'items'):
            _object(row, ('id', 'entitlement', 'label'), 'item')
            item = CosmeticItem(_uint(row['id'], 'item ID', positive=True),
                                _uint(row['entitlement'], 'entitlement'),
                                _uint(row['label'], 'label', positive=True))
            _require(item.id not in items, 'duplicate cosmetic item ID')
            items[item.id] = item

        slots = {}
        covered = set()
        defaults = set()
        for row in _array(data['slots'], SLOT_COUNT, SLOT_COUNT, 'slots'):
            _object(row, ('id', 'default_item', 'compatible_items'), 'slot')
            slot_id = _uint(row['id'], 'slot ID', positive=True)
            _require(slot_id not in slots, 'duplicate cosmetic slot ID')
            default = _uint(row['default_item'], 'default item')
            compatible = tuple(_uint(value, 'compatible item ID', positive=True) for value in
                               _array(row['compatible_items'], 0, MAX_ITEMS, 'compatible items'))
            _require(len(set(compatible)) == len(compatible), 'duplicate cosmetic compatible item ID')
            _require(set(compatible) <= items.keys(), 'unknown cosmetic compatible item ID')
            _require((default in compatible) if compatible else default == 0,
                     'invalid cosmetic slot default')
            _require(default == 0 or default not in defaults, 'duplicate cosmetic default item')
            if default:
                defaults.add(default)
            covered.update(compatible)
            slots[slot_id] = CosmeticSlot(slot_id, default, frozenset(compatible))
        _require(set(order) == slots.keys(), 'cosmetic native slot order differs from slots')
        _require(covered == items.keys(), 'cosmetic item has no compatible slot')

        roles = _object(data['roles'], ('portrait', 'banner'), 'roles')
        roles = {name: _uint(value, 'role slot ID', positive=True) for name, value in roles.items()}
        _require(len(set(roles.values())) == 2 and all(slot in slots for slot in roles.values()),
                 'invalid cosmetic role slots')
        _require(all(slots[slot].default_item for slot in roles.values()), 'empty cosmetic role slot')

        # Copy into frozen records/proxies; no parsed mutable JSON roots escape.
        object.__setattr__(self, 'sha256', hashlib.sha256(raw).hexdigest())
        object.__setattr__(self, 'native_slot_order', order)
        object.__setattr__(self, 'items', MappingProxyType(items))
        object.__setattr__(self, 'slots', MappingProxyType({slot: slots[slot] for slot in order}))
        object.__setattr__(self, 'roles', MappingProxyType(roles))

    def validate_selection(self, selection):
        """Strict network input: exactly one effective item for every native slot.

        Accept an integer-keyed mapping or bounded list/tuple of (slot,item)
        pairs. Pairs retain duplicate-slot evidence that a dict would discard.
        """
        return self._snapshot(selection, normalize=False)

    def normalize_local(self, selection=()):
        """Resolve missing/zero local choices to defaults, then validate fully.

        Unknown/invalid nonzero choices and duplicate effective items fail. A
        partial equivalent-slot selection that collides with another default
        must be resolved by the caller/native picker, not reordered here.
        """
        return self._snapshot(selection, normalize=True)

    def _snapshot(self, selection, *, normalize):
        _require(isinstance(selection, Mapping) or type(selection) in (list, tuple),
                 'invalid cosmetic selection collection')
        _require(len(selection) <= SLOT_COUNT, 'cosmetic selection collection limit')
        rows = selection.items() if isinstance(selection, Mapping) else selection
        selected = {}
        for row in rows:
            _require(type(row) in (list, tuple) and len(row) == 2, 'invalid cosmetic selection pair')
            slot_id, item_id = (_uint(row[0], 'selected slot ID', positive=True),
                                _uint(row[1], 'selected item ID'))
            _require(slot_id in self.slots, 'unknown cosmetic selection slot')
            _require(slot_id not in selected, 'duplicate cosmetic selection slot')
            selected[slot_id] = item_id
        _require(normalize or len(selected) == SLOT_COUNT, 'incomplete cosmetic selection')

        pairs, keys, used = [], [], set()
        for slot_id in self.native_slot_order:
            slot = self.slots[slot_id]
            item_id = selected.get(slot_id, 0)
            if normalize and item_id == 0:
                item_id = slot.default_item
            if item_id == 0:
                _require(slot.default_item == 0 and not slot.compatible_items,
                         'zero cosmetic item in nonempty slot')
            else:
                _require(item_id in self.items, 'unknown cosmetic selection item')
                _require(item_id in slot.compatible_items, 'wrong-slot cosmetic selection item')
                _require(item_id not in used, 'duplicate nonzero cosmetic selection item')
                used.add(item_id)
                keys.append(item_id)
            pairs.append((slot_id, item_id))
        frozen = tuple(pairs)
        effective = dict(frozen)
        return CosmeticSnapshot(self.sha256, frozen, tuple(keys), effective[self.roles['portrait']],
                                effective[self.roles['banner']], field_packed_uint(3, keys))
