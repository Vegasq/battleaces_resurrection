"""Pure readers for the shipped Setup observations; no native calls.

Exact-build static contract (original GameAssembly SHA256 e59d08c01479b274
04778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758): SimFrame Labels11,
States4, SetupTimes27; SetupTimeBuffer.Time is float32 (RVA3a086b0).
LabelSets contains compact strings0 and sets1; each LabelSet contains uint32
label KEYS0, whose names require GameConfig.label_table explicit IDs. Control01
proved these differ: key35 is Big, while the compact string vector has32 items.
The original cache ReadLabels at RVA197bf30 reads cumulative full tables,
appending suffixes from the previous string/set counts (197c111..29a and
197c321..506). GetLabels at197c560 directly indexes the set list, zero based.
Other ReadLabels instantiations197cd80/197dab0/197e7e0/197f5f0 use the same
contract. All these inspected bytes match the pinned original. This reader
also rejects changed old prefixes instead of silently ignoring conflicting data.
It does not classify a successful cast from an unchanged identity or one row.
"""
from __future__ import annotations

import math
import struct
from collections.abc import Mapping
from types import MappingProxyType

from server.protobuf_wire import WireError, parse_fields


MAX_BYTES = 16 * 1024 * 1024
MAX_ENTITIES = 32768
MAX_REGISTRY_ENTRIES = 65536
MAX_LABEL_BYTES = 4096


class SetupObservationError(ValueError):
    """Malformed or unresolved original Setup observation."""


def _label_name(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_LABEL_BYTES:
        raise SetupObservationError('config label name outside byte bound')
    try:
        name = raw.decode('utf-8', errors='strict')
    except UnicodeDecodeError as error:
        raise SetupObservationError('invalid config label UTF-8') from error
    if '\0' in name:
        raise SetupObservationError('config label name contains NUL')
    return name


def label_names_from_config(raw_game_config):
    """Freeze original field6 EntityLabel{name1, uint32 id2} in wire order.

    Proto3 may omit the zero ID. Nonzero IDs are never inferred from declaration
    position: the original table skips26..28 and32..33. No native code is loaded.
    """
    result = {}
    names = set()
    try:
        fields = parse_fields(raw_game_config, max_bytes=MAX_BYTES, max_fields=MAX_REGISTRY_ENTRIES)
        for field in fields:
            if field.number != 6:
                continue
            if field.wire_type != 2 or len(result) >= MAX_REGISTRY_ENTRIES:
                raise SetupObservationError('invalid config label table field')
            entry = parse_fields(field.value, max_bytes=MAX_LABEL_BYTES + 32, max_fields=8)
            values = {}
            for item in entry:
                if item.number not in (1, 2) or item.number in values:
                    raise SetupObservationError('unknown or duplicate config label field')
                if item.wire_type != (2 if item.number == 1 else 0):
                    raise SetupObservationError('wrong config label field wire type')
                values[item.number] = item.value
            name = _label_name(values.get(1))
            label = values.get(2, 0)
            if not 0 <= label <= 0xffffffff:
                raise SetupObservationError('config label ID must be uint32')
            if label in result or name in names:
                raise SetupObservationError('duplicate config label ID or name')
            result[label] = name
            names.add(name)
    except WireError as error:
        raise SetupObservationError('invalid config label protobuf: ' + str(error)) from error
    if not result:
        raise SetupObservationError('config label table is empty')
    return MappingProxyType(result)


class _Reader:
    def __init__(self, raw):
        if not isinstance(raw, bytes) or not 8 <= len(raw) <= MAX_BYTES:
            raise SetupObservationError('FlatBuffer must be bounded nonempty bytes')
        self.raw = raw
        self.root = self.indirect(0)
        self.table(self.root)

    def bounds(self, offset, size):
        if offset < 0 or size < 0 or offset > len(self.raw) - size:
            raise SetupObservationError('FlatBuffer bounds')

    def read(self, fmt, offset):
        self.bounds(offset, struct.calcsize('<' + fmt))
        return struct.unpack_from('<' + fmt, self.raw, offset)[0]

    def indirect(self, offset):
        relative = self.read('I', offset)
        target = offset + relative
        if relative == 0 or target % 4:
            raise SetupObservationError('invalid FlatBuffer relative offset')
        self.bounds(target, 4)
        return target

    def table(self, table):
        if table % 4:
            raise SetupObservationError('unaligned FlatBuffer table')
        distance = self.read('i', table)
        if not distance:
            raise SetupObservationError('missing FlatBuffer vtable')
        vtable = table - distance
        self.bounds(vtable, 4)
        length, size = self.read('H', vtable), self.read('H', vtable + 2)
        if vtable % 2 or length < 4 or length % 2 or size < 4:
            raise SetupObservationError('invalid FlatBuffer vtable')
        self.bounds(vtable, length)
        self.bounds(table, size)
        return vtable, length, size

    def field(self, table, index, width=4):
        vtable, length, size = self.table(table)
        slot = 4 + index * 2
        if slot >= length:
            return None
        relative = self.read('H', vtable + slot)
        if not relative:
            return None
        if relative < 4 or relative + width > size:
            raise SetupObservationError('field outside FlatBuffer object')
        result = table + relative
        self.bounds(result, width)
        return result

    def vector(self, table, index, *, limit):
        field = self.field(table, index)
        if field is None:
            return 0, 0
        vector = self.indirect(field)
        count = self.read('I', vector)
        if count > limit:
            raise SetupObservationError('FlatBuffer vector exceeds bound')
        self.bounds(vector + 4, count * 4)
        return vector + 4, count

    def string(self, pointer):
        start = self.indirect(pointer)
        size = self.read('I', start)
        if size > MAX_LABEL_BYTES:
            raise SetupObservationError('label string exceeds bound')
        self.bounds(start + 4, size + 1)
        if self.raw[start + 4 + size] != 0:
            raise SetupObservationError('unterminated label string')
        try:
            return self.raw[start + 4:start + 4 + size].decode('utf-8', errors='strict')
        except UnicodeDecodeError as error:
            raise SetupObservationError('invalid label UTF-8') from error


class LabelRegistry:
    """One world's cumulative original Unit(1) registry, with zero-based handles.

    observe accepts a full nonempty FlatBuffer, never a delta or b''. Callers
    retain raw registry updates alongside snapshots, including rejected updates.
    A failed observation leaves this registry unchanged.
    """
    def __init__(self, label_names):
        if not isinstance(label_names, Mapping) or not 0 < len(label_names) <= MAX_REGISTRY_ENTRIES:
            raise SetupObservationError('an ordered original config label map is required')
        declared = {}
        seen_names = set()
        for label, name in label_names.items():
            if type(label) is not int or not 0 <= label <= 0xffffffff or not isinstance(name, str):
                raise SetupObservationError('invalid original config label map entry')
            try:
                _label_name(name.encode('utf-8', errors='strict'))
            except UnicodeEncodeError as error:
                raise SetupObservationError('invalid config label UTF-8') from error
            if label in declared or name in seen_names:
                raise SetupObservationError('duplicate config label ID or name')
            declared[label] = name
            seen_names.add(name)
        self.label_names = MappingProxyType(declared)
        self.declaration_names = tuple(declared.values())
        self.strings: tuple[str, ...] = ()
        self.sets: tuple[tuple[int, ...], ...] = ()

    def observe(self, raw):
        reader = _Reader(raw)
        start, count = reader.vector(reader.root, 0, limit=MAX_REGISTRY_ENTRIES)
        strings = tuple(reader.string(start + 4 * index) for index in range(count))
        start, count = reader.vector(reader.root, 1, limit=MAX_REGISTRY_ENTRIES)
        sets = []
        for index in range(count):
            table = reader.indirect(start + 4 * index)
            values, size = reader.vector(table, 0, limit=MAX_REGISTRY_ENTRIES)
            keys = tuple(reader.read('I', values + 4 * item) for item in range(size))
            if len(set(keys)) != size:
                raise SetupObservationError('duplicate label key')
            if any(key not in self.label_names for key in keys):
                raise SetupObservationError('undeclared config label key')
            sets.append(keys)
        sets = tuple(sets)
        if len(strings) < len(self.strings) or len(sets) < len(self.sets):
            raise SetupObservationError('label registry shrank; full tables required')
        if strings[:len(self.strings)] != self.strings or sets[:len(self.sets)] != self.sets:
            raise SetupObservationError('label registry changed an existing prefix')
        if len(strings) > len(self.declaration_names) or strings != self.declaration_names[:len(strings)]:
            raise SetupObservationError('registry strings differ from config declaration order')
        self.strings, self.sets = strings, sets

    def resolve_keys(self, handle):
        if type(handle) is not int or not 0 <= handle < len(self.sets):
            raise SetupObservationError('unknown label-set handle')
        return list(self.sets[handle])

    def resolve(self, handle):
        return [self.label_names[key] for key in self.resolve_keys(handle)]


def _sparse(reader, field, fmt):
    pointer = reader.field(reader.root, field)
    if pointer is None:
        return {}
    table = reader.indirect(pointer)
    ids, count = reader.vector(table, 0, limit=MAX_ENTITIES)
    values, value_count = reader.vector(table, 1, limit=MAX_ENTITIES)
    if count != value_count:
        raise SetupObservationError('sparse component vector counts disagree')
    result = {}
    for index in range(count):
        entity = reader.read('I', ids + index * 4)
        if entity in result:
            raise SetupObservationError('duplicate sparse entity ID')
        value = reader.read(fmt, values + index * 4)
        if fmt == 'f' and (not math.isfinite(value) or value < 0):
            raise SetupObservationError('invalid setup elapsed time')
        result[entity] = value
    return result


def decode(raw, registry, *, expected_frame):
    """Read exact sparse observations; missing inactive components stay None.

    Missing sparse components remain None even during SETUP: actual captured
    completion edges can lose their timer one frame before state/labels change.
    Progress, missing interior samples and completion are the caller's temporal
    classification policy; this reader never fills a missing timer with zero.
    Labels are explicit original config names; raw numeric label keys are also
    retained. They are never compact string indices, masks or guessed aliases.
    """
    if not isinstance(registry, LabelRegistry):
        raise SetupObservationError('a world-owned LabelRegistry is required')
    if type(expected_frame) is not int or not 0 <= expected_frame <= 0xffffffff:
        raise SetupObservationError('expected frame must be uint32')
    reader = _Reader(raw)
    field = reader.field(reader.root, 0)
    frame = reader.read('I', field) if field is not None else 0
    if frame != expected_frame:
        raise SetupObservationError('native snapshot frame differs from expected frame')
    states, labels, times = (_sparse(reader, field, fmt)
                             for field, fmt in ((4, 'I'), (11, 'I'), (27, 'f')))
    entities = {}
    for entity in sorted(states.keys() | labels.keys() | times.keys()):
        state, handle, elapsed = states.get(entity), labels.get(entity), times.get(entity)
        keys = registry.resolve_keys(handle) if handle is not None else []
        names = registry.resolve(handle) if handle is not None else []
        entities[entity] = dict(state=state, label_handle=handle, label_keys=keys, labels=names, setup_time=elapsed)
    return dict(frame=frame, entities=entities)
