"""Authored snapshot fixtures for the Python/Rust decoder comparison.

These buffers are constructed from the source-owned decoder contract. They are
not game exports and contain no captured player state. ``valid_cases`` means
accepted by the reference decoder; named Python edge cases deliberately include
its zero-root and out-of-native-range viewer behavior. Native snapshot retrieval
has separate viewer/size constraints, which should be tested at that boundary.
"""
from __future__ import annotations

import struct


_COMPONENTS = (
    (2, "army", 1),
    (3, "type", 1),
    (5, "health", 1),
    (7, "position", 3),
    (21, "resources", 8),
)
_NAMES = tuple(name for _, name, _ in _COMPONENTS)


class _Builder:
    def __init__(self, leading_padding=0):
        self.data = bytearray(4 + leading_padding)

    def table(self, slots, fields):
        fields = tuple(fields)
        vtable = len(self.data)
        size = 4 + 8 * len(fields)
        offsets = {key: 4 + 8 * index for index, key in enumerate(fields)}
        self.data.extend(struct.pack("<HH", 4 + 2 * slots, size))
        self.data.extend(b"".join(struct.pack("<H", offsets.get(i, 0)) for i in range(slots)))
        start = len(self.data)
        self.data.extend(struct.pack("<i", start - vtable) + bytes(size - 4))
        return start, vtable, {key: start + offset for key, offset in offsets.items()}

    def point(self, source, target):
        struct.pack_into("<I", self.data, source, target - source)

    def vector(self, records, width):
        records = list(records)
        start = len(self.data)
        self.data.extend(struct.pack("<I", len(records)))
        for record in records:
            if len(record) != width:
                raise ValueError("authored vector row has the wrong width")
            self.data.extend(struct.pack("<" + "I" * width, *record))
        return start


def _position_words(index):
    # Exact finite f32 coordinates in four authored movement lanes.
    army = index % 4
    return struct.unpack("<III", struct.pack("<fff", (index % 37 - 18) * .25,
                                             (index % 3) * .125, army * 20 + (index // 37) * .5))


def _build(entity_count=800, *, components=_NAMES, resource_armies=(0, 1, 2, 3),
           sparse=False, reordered=False, leading_padding=0, complete=False):
    if type(entity_count) is not int or not 0 <= entity_count <= 10000:
        raise ValueError("authored entity count must be within0..10000")
    if not set(components) <= set(_NAMES) or len(set(components)) != len(components):
        raise ValueError("invalid authored component selection")
    builder = _Builder(leading_padding)
    selected = [(field, name, width) for field, name, width in _COMPONENTS if name in components]
    root, vtable, fields = builder.table(24, (0, 1, *(field for field, _, _ in selected), 23))
    struct.pack_into("<I", builder.data, 0, root)
    struct.pack_into("<I", builder.data, fields[0], 123)
    struct.pack_into("<I", builder.data, fields[1], 1)
    metadata = {"root": root, "root_vtable": vtable, "root_fields": fields, "components": {}}
    for field, name, width in selected:
        rows = []
        if name == "resources":
            for army in resource_armies:
                population = sum(index % 4 == army for index in range(entity_count))
                values = (1000 + army, 0xFFFFFFFF if army == 1 else 500,
                          population, 200, 0x80000000 if army == 2 else 1200,
                          0x7FFFFFFF if army == 3 else 600, 13 + army, 7 + army)
                rows.append((army, values, None))
        else:
            for index in range(entity_count):
                if sparse and ((name == "army" and index % 3 == 0)
                               or (name == "type" and index % 3 == 1)
                               or (name == "health" and index % 4 == 0)
                               or (name == "position" and index % 4 == 1)):
                    continue
                values = {"army": (index % 4,), "type": (2 if index % 2 else 75,),
                          "health": (100 + index % 11,), "position": _position_words(index)}[name]
                rows.append((100 + index, values, index % 7 if name == "health" else None))
        if reordered:
            rows.reverse()
        table, table_vtable, pointers = builder.table(3 if name == "health" else 2,
                                                      (0, 1, 2) if name == "health" else (0, 1))
        builder.point(fields[field], table)
        ids = builder.vector(((entity,) for entity, _, _ in rows), 1)
        values = builder.vector((values for _, values, _ in rows), width)
        builder.point(pointers[0], ids)
        builder.point(pointers[1], values)
        info = dict(table=table, vtable=table_vtable, pointers=pointers,
                    ids=ids, values=values, count=len(rows), width=width)
        if name == "health":
            damage = builder.vector(((damage,) for _, _, damage in rows), 1)
            builder.point(pointers[2], damage)
            info["damage"] = damage
        metadata["components"][name] = info
    result, result_vtable, result_fields = builder.table(5, (0, 1, 2, 3, 4))
    builder.point(fields[23], result)
    struct.pack_into("<B", builder.data, result_fields[0], complete)
    struct.pack_into("<i", builder.data, result_fields[1], 123 if complete else -1)
    struct.pack_into("<I", builder.data, result_fields[2], 3 if complete else 0)
    struct.pack_into("<I", builder.data, result_fields[3], 5 if complete else 0)
    struct.pack_into("<Q", builder.data, result_fields[4], 0xFEDCBA9876543210 if complete else 0)
    metadata.update(result=result, result_vtable=result_vtable, result_fields=result_fields)
    return bytes(builder.data), metadata


def make_snapshot(entity_count=800):
    """Return a deterministic four-army authored state, suitable for benchmarks."""
    return _build(entity_count)[0]


def _case(name, raw, *, viewer=31, include_entities=True):
    return dict(name=name, raw=raw, viewer=viewer, include_entities=include_entities)


def _changed(raw, offset, fmt, *values):
    changed = bytearray(raw)
    struct.pack_into("<" + fmt, changed, offset, *values)
    return bytes(changed)


def _float_case(name, words, *, include_entities):
    raw, metadata = _build(4)
    position = metadata["components"]["position"]["values"] + 4
    return _case(name, _changed(raw, position, "III", *words), include_entities=include_entities)


def valid_cases():
    """Reference-accepted states with JSON-serializable output in this mode."""
    raw, metadata = _build(8)
    complete, _ = _build(8, complete=True)
    cases = [_case("full_eight_entities", raw),
             _case("full_without_entities", raw, include_entities=False),
             _case("completed_unsigned64_result", complete),
             _case("empty_entity_vectors", make_snapshot(0)),
             _case("single_entity", make_snapshot(1)),
             _case("large_four_armies_800", make_snapshot(800)),
             _case("sparse_entity_components", _build(8, sparse=True)[0]),
             _case("reordered_component_rows", _build(8, reordered=True)[0]),
             _case("misaligned_tables_and_vectors", _build(8, leading_padding=1)[0]),
             _case("python_zero_root", bytes(4))]
    for viewer in (0, 1, 32, 0xFFFFFFFF):
        cases.append(_case(f"viewer_{viewer}", raw, viewer=viewer))
    for name in _NAMES:
        cases.append(_case(f"absent_{name}_component", _build(8, components=tuple(n for n in _NAMES if n != name))[0]))
    cases.append(_case("all_components_absent", _build(0, components=())[0]))
    # A well-formed table with no fields exercises every scalar default.
    builder = _Builder()
    root, _, _ = builder.table(0, ())
    struct.pack_into("<I", builder.data, 0, root)
    cases.append(_case("all_root_fields_absent", bytes(builder.data)))
    result_field_entry = metadata["root_vtable"] + 4 + 23 * 2
    cases.append(_case("result_table_absent", _changed(raw, result_field_entry, "H", 0)))
    cases.append(_case("preinitialization_unsigned_frame", _changed(raw, metadata["root_fields"][0], "I", 0xFFFFFFFF)))
    cases.append(_case("signed_minimum_result_frame", _changed(raw, metadata["result_fields"][1], "i", -0x80000000)))
    cases.append(_case("maximum_unsigned64_checksum", _changed(raw, metadata["result_fields"][4], "Q", 0xFFFFFFFFFFFFFFFF)))
    cases.append(_case("nonzero_complete_byte", _changed(raw, metadata["result_fields"][0], "B", 255)))
    cases.append(_case("trailing_padding", raw + bytes((0xA5, 0x5A, 0x00, 0xFF))))
    # FlatBuffer vtable deduplication can place the selected vtable after a table.
    negative = bytearray(raw)
    vtable = metadata["root_vtable"]
    length = struct.unpack_from("<H", raw, vtable)[0]
    after = len(negative)
    negative.extend(raw[vtable:vtable + length])
    struct.pack_into("<i", negative, metadata["root"], metadata["root"] - after)
    cases.append(_case("negative_vtable_displacement", bytes(negative)))
    # Army and type tables share the same two-field layout and can share a vtable.
    army = metadata["components"]["army"]
    unit_type = metadata["components"]["type"]
    shared = _changed(raw, unit_type["table"], "i", unit_type["table"] - army["vtable"])
    cases.append(_case("shared_component_vtable", shared))
    cases.append(_float_case("signed_zero_and_subnormal_positions", (0, 0x80000000, 1), include_entities=True))
    cases.append(_float_case("finite_float_extremes", (0x7F7FFFFF, 0xFF7FFFFF, 0x00800000), include_entities=True))
    cases.append(_float_case("nonfinite_bits_without_entities", (0x7FC00001, 0x7F800000, 0xFF800000), include_entities=False))
    return cases


def invalid_cases():
    """Malformed buffers rejected by the reference decoder (fewer than300)."""
    compact, _ = _build(0, components=("resources",), resource_armies=(0, 1))
    # The final referenced u64 ends exactly at EOF, so every shorter prefix fails.
    cases = [_case(f"truncated_prefix_{length:03d}", compact[:length]) for length in range(len(compact))]
    raw, metadata = _build(8)
    cases.extend((
        _case("root_beyond_buffer", _changed(raw, 0, "I", 0xFFFFFFFF)),
        _case("root_vtable_before_buffer", _changed(raw, metadata["root"], "i", 0x7FFFFFFF)),
        _case("root_vtable_after_buffer", _changed(raw, metadata["root"], "i", -0x80000000)),
        _case("scalar_field_beyond_buffer", _changed(raw, metadata["root_vtable"] + 4, "H", 0xFFFF)),
    ))
    for field, name, _ in _COMPONENTS:
        info = metadata["components"][name]
        first_id = struct.unpack_from("<I", raw, info["ids"] + 4)[0]
        cases.extend((
            _case(f"duplicate_{name}_id", _changed(raw, info["ids"] + 8, "I", first_id)),
            _case(f"mismatched_{name}_values", _changed(raw, info["values"], "I", 0)),
            _case(f"{name}_table_offset_overflow", _changed(raw, metadata["root_fields"][field], "I", 0xFFFFFFFF)),
            _case(f"{name}_ids_offset_overflow", _changed(raw, info["pointers"][0], "I", 0xFFFFFFFF)),
        ))
    health = metadata["components"]["health"]
    cases.extend((
        _case("health_damage_count_mismatch", _changed(raw, health["damage"], "I", 0)),
        _case("health_damage_vector_missing", _changed(raw, health["vtable"] + 4 + 2 * 2, "H", 0)),
        _case("vector_count_exceeds_bound", _changed(raw, metadata["components"]["army"]["ids"], "I", 1_000_001)),
        _case("vector_count_exceeds_bytes", _changed(raw, metadata["components"]["army"]["ids"], "I", 1_000_000)),
        _case("result_table_offset_overflow", _changed(raw, metadata["root_fields"][23], "I", 0xFFFFFFFF)),
    ))
    if len(cases) >= 300:
        raise AssertionError("authored invalid corpus exceeded the bounded case budget")
    return cases


def json_refusal_cases():
    """Parser-accepted nonfinite positions that production JSON must reject."""
    return [
        _float_case("positive_and_negative_infinity", (0x7F800000, 0xFF800000, 0), include_entities=True),
        _float_case("quiet_nan_payloads", (0x7FC00001, 0xFFC12345, 0), include_entities=True),
        _float_case("signaling_nan_payload", (0x7FA00001, 0, 0), include_entities=True),
    ]
