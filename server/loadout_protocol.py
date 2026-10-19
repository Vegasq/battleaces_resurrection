"""Explicit complete cosmetic selection extension; legacy packets stay exact.

Structural wire validation is independent of installed catalog validation. Never
use a decoded Selection in a profile or match before validating its catalog.
"""
from dataclasses import dataclass
import struct

from . import protocol as p

VERSION = 1
SET_LOADOUT, ENTER_LOADOUT, MATCH_LOADOUT, LOBBY_LOADOUT = range(65, 69)
SLOTS, BYTES = 17, 168


@dataclass(frozen=True, slots=True)
class Selection:
    catalog_sha256: str
    slots: tuple[tuple[int, int], ...]

    def __post_init__(self):
        p.require(type(self.catalog_sha256) is str and len(self.catalog_sha256) == 64 and
                  all(c in '0123456789abcdef' for c in self.catalog_sha256), 'invalid loadout catalog digest')
        p.require(type(self.slots) in (tuple, list) and len(self.slots) == SLOTS, 'incomplete loadout slots')
        rows, ids, items = [], set(), set()
        for row in self.slots:
            p.require(type(row) in (tuple, list) and len(row) == 2, 'invalid loadout pair')
            slot, item = row
            p.require(type(slot) is int and 0 < slot <= 0xffffffff and slot not in ids and
                      type(item) is int and 0 <= item <= 0xffffffff and (not item or item not in items),
                      'invalid duplicate loadout slot/item')
            ids.add(slot)
            if item: items.add(item)
            rows.append((slot, item))
        object.__setattr__(self, 'slots', tuple(rows))

    def validate(self, catalog):
        p.require(catalog is not None and self.catalog_sha256 == catalog.sha256, 'loadout catalog mismatch')
        snapshot = catalog.validate_selection(self.slots)
        p.require(snapshot.slots == self.slots, 'loadout slots must use native order')
        return snapshot


def encode(snapshot):
    value = Selection(snapshot.catalog_sha256, snapshot.slots)
    return bytes.fromhex(value.catalog_sha256) + b''.join(struct.pack('<II', *row) for row in value.slots)


def decode(reader):
    p.require(reader.offset + BYTES <= len(reader.payload), 'truncated complete loadout')
    digest = reader.payload[reader.offset:reader.offset+32].hex()
    reader.offset += 32
    return Selection(digest, tuple((reader.number('I'), reader.number('I')) for _ in range(SLOTS)))


def set_loadout(request, deck, cosmetics):
    p.require(type(request) is int and 0 < request < 2**32, 'invalid loadout request')
    return struct.pack('<IH', request, VERSION) + p.deck_bytes(deck) + encode(cosmetics)
