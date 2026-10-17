"""Small authored fixtures; these are not exports from any game installation."""
import struct
from server.game_data import GameTemplate, encode_deck
from server.protobuf_wire import field_bytes, field_packed_uint, field_uint


def template():
    flags = tuple(1 << index for index in range(8))
    deck = tuple(range(100, 108))
    global_config = field_bytes(24, field_packed_uint(1, flags))
    entities = b''.join(field_bytes(1, field_uint(1, entity) + field_uint(21, mask))
                        for entity, mask in zip(deck, flags))
    armies = b''.join(field_bytes(2, field_uint(1, army) + field_bytes(3, encode_deck(deck)))
                      for army in (0, 1))
    raw = field_bytes(1, entities + armies + field_bytes(3, global_config))
    return GameTemplate(raw, catalog_path=None, descriptors_path='unused-synthetic-descriptors')


def snapshot(frame=0, winner=0, complete=False):
    # Hand-constructed FlatBuffer with only frame, resources and result fields.
    data = bytearray(4)

    def table(slots, fields):
        vtable = len(data)
        table_size = 4 + 8 * len(fields)
        data.extend(struct.pack('<HH', 4 + 2 * slots, table_size))
        offsets = {key: 4 + 8 * index for index, key in enumerate(fields)}
        data.extend(b''.join(struct.pack('<H', offsets.get(i, 0)) for i in range(slots)))
        start = len(data)
        data.extend(struct.pack('<i', start - vtable) + bytes(table_size - 4))
        return start, {key: start + offset for key, offset in offsets.items()}

    def point(offset, target):
        struct.pack_into('<I', data, offset, target - offset)

    root, f = table(24, (0, 1, 21, 23))
    struct.pack_into('<I', data, 0, root)
    struct.pack_into('<I', data, f[0], frame)
    resources, r = table(2, (0, 1))
    point(f[21], resources)
    ids = len(data)
    data.extend(struct.pack('<III', 2, 0, 1))
    point(r[0], ids)
    values = len(data)
    data.extend(struct.pack('<I', 2))
    for army in (0, 1):
        data.extend(struct.pack('<8I', 1000 + army, 500, 3, 200, 1200, 600, 200, 100))
    point(r[1], values)
    state, s = table(5, (0, 1, 2, 3, 4))
    point(f[23], state)
    struct.pack_into('<B', data, s[0], complete)
    struct.pack_into('<i', data, s[1], frame if complete else -1)
    struct.pack_into('<I', data, s[2], winner)
    struct.pack_into('<Q', data, s[4], 123456789 if complete else 0)
    return bytes(data)
