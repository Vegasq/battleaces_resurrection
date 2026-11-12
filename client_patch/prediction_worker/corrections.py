"""Copied presentation-only native same-H deltas, outside checkpoint memory.

Querying original views can update auxiliary native registries. This component
does not make queries, modify native/frame/input bytes, or infer hidden actors.
The owner supplies original own-view output and qualified admission/continuity.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from server.native_simulation import _Buffer


MAX_ENTITIES = 65536
HEADER = struct.Struct('<IQiiQI')
ENTRY = struct.Struct('<IIIQfff')


class CorrectionError(ValueError):
    pass


def require(value, reason):
    if not value:
        raise CorrectionError('presentation corrections: '+reason)


def uint(value, bits=32):
    return type(value) is int and 0 <= value < 2**bits


@dataclass(frozen=True)
class Snapshot:
    frame: int
    # entity, type, army, incarnation, x, y, z. Tuples never alias caller maps.
    rows: tuple


def snapshot(raw, *, slot, frame, admitted, continuity):
    require(type(raw) is bytes and 8 <= len(raw) <= 16*1024*1024 and
            slot in (0, 1) and type(slot) is int and type(frame) is int and
            0 <= frame <= 0x7fffffff and type(admitted) is dict and
            len(admitted) <= MAX_ENTITIES and type(continuity) is bool, 'snapshot ownership/schema/budget differs')
    b = _Buffer(raw); root = b.read('I', 0); b.bounds(root, 4)
    require(b.scalar(root, 0, 'I') == frame and b.scalar(root, 1, 'I') == slot,
            'own-view native frame/alliance differs')
    fields = {}
    for field, words in ((2, 1), (3, 1), (4, 1), (7, 3)):
        table = b.table(root, field); ids, count = b.vector(table, 0, 4)
        values, size = b.vector(table, 1, words*4)
        require(count == size and count <= MAX_ENTITIES, 'component count/budget differs')
        rows = {}
        for index in range(count):
            entity = b.read('I', ids+4*index)
            require(entity not in rows, 'duplicate component entity')
            rows[entity] = tuple(b.read('I', values+(index*words+j)*4) for j in range(words))
        fields[field] = rows
    result = []
    for entity in sorted(fields[2].keys() & fields[3].keys() & fields[4].keys() & fields[7].keys()):
        army, kind, state = fields[2][entity][0], fields[3][entity][0], fields[4][entity][0]
        position = struct.unpack('<fff', struct.pack('<III', *fields[7][entity]))
        require(all(math.isfinite(value) for value in position), 'nonfinite native position')
        if army != slot or state == 6 or entity not in admitted or not continuity:
            continue
        identity = admitted[entity]
        require(type(identity) is tuple and len(identity) == 3 and all(uint(x) for x in identity[:2]) and
                uint(identity[2], 64) and identity[2] > 0, 'admission identity/token differs')
        if identity[:2] != (army, kind):
            continue
        result.append((entity, kind, army, identity[2], *position))
    return Snapshot(frame, tuple(result))


class Corrections:
    """One last own-view cache and TWO exact immutable publication responses/world."""
    def __init__(self):
        self.worlds = {}

    def begin(self, world, slot):
        require(uint(world, 64) and world > 0 and type(slot) is int and slot in (0, 1), 'world/slot differs')
        if world in self.worlds:
            require(self.worlds[world]['slot'] == slot, 'world changed owner slot')
            return
        self.worlds[world] = dict(slot=slot, latest=None, stage=None, pending=None, revision=0, responses={})

    def _world(self, world):
        require(world in self.worlds, 'unknown/retired world')
        return self.worlds[world]

    def prepare(self, world, head):
        state = self._world(world)
        require(type(head) is int and -1 <= head < 0x7fffffff and state['stage'] is None,
                'invalid/reentrant physical-head boundary')
        latest = state['latest']
        state['stage'] = dict(head=head, before=latest if latest is not None and latest.frame == head else None,
                              after=None)

    def wants_head(self, world, frame):
        state = self._world(world); stage = state['stage']
        return stage is not None and frame == stage['head']

    def corrected_head(self, world, frame, raw):
        state = self._world(world); stage = state['stage']
        require(stage is not None and frame == stage['head'] and stage['after'] is None and type(raw) is bytes,
                'duplicate/unbound replay head')
        # Admission is promoted only after repair returns. Retain owned bytes
        # until then, rather than borrowing a native Get buffer or old token.
        require(len(raw) <= 16*1024*1024, 'corrected view exceeds buffer budget')
        stage['after'] = raw

    def finish(self, world, *, admitted, continuity):
        state = self._world(world); stage = state['stage']
        require(stage is not None, 'repair completion without preparation')
        if stage['after'] is None:
            state['stage'] = None
            return
        head = stage['head']
        after = snapshot(stage['after'], slot=state['slot'], frame=head, admitted=admitted, continuity=continuity)
        before = stage['before']; pending = state['pending']
        require(state['revision'] < 0xffffffffffffffff, 'revision overflow')
        if pending is not None:
            require(pending['head'] == head, 'unpublished correction was superseded by another head')
            # Multiple repairs at the SAME H preserve the FIRST baseline and
            # use the final corrected H. No ordinary H->H+1 motion is included.
            before = pending['before']
        state['pending'] = dict(head=head, before=before, after=after)
        state['revision'] += 1; state['stage'] = None

    def ordinary(self, world, frame, raw, *, admitted, continuity):
        state = self._world(world)
        require(state['stage'] is None, 'ordinary view during an unfinished repair')
        current = snapshot(raw, slot=state['slot'], frame=frame, admitted=admitted, continuity=continuity)
        latest = state['latest']
        require(latest is None or frame >= latest.frame, 'ordinary own-view frame regressed')
        if latest is not None and frame == latest.frame:
            require(current == latest, 'same ordinary view changed identity/position')
            return
        pending = state['pending']; records = []; correction_head = -1
        if pending is not None:
            require(frame == pending['head']+1, 'corrected metadata missed its exact next publication')
            if pending['before'] is not None:
                old = {r[0]: r for r in pending['before'].rows}
                corrected = {r[0]: r for r in pending['after'].rows}
                visible = {r[0]: r for r in current.rows}
                for entity in sorted(old.keys() & corrected.keys() & visible.keys()):
                    a, b, c = old[entity], corrected[entity], visible[entity]
                    if a[:4] != b[:4] or a[:4] != c[:4]:
                        continue  # Birth/death/type/army/replacement is not a correction offset.
                    delta = tuple(y-x for x, y in zip(a[4:], b[4:]))
                    try:
                        delta = struct.unpack('<fff', struct.pack('<fff', *delta))
                    except (OverflowError, struct.error) as error:
                        raise CorrectionError('presentation corrections: delta exceeds Single') from error
                    require(all(math.isfinite(x) for x in delta), 'nonfinite correction delta')
                    if any(x != 0 for x in delta):
                        records.append((*a[:4], *delta))
            if records:
                correction_head = pending['head']
        require(len(records) <= MAX_ENTITIES, 'correction record budget exceeded')
        response = HEADER.pack(1, world, frame, correction_head, state['revision'], len(records))
        response += b''.join(ENTRY.pack(*row) for row in records)
        responses = dict(state['responses']); responses[frame] = response
        responses = dict(sorted(responses.items())[-2:])
        state['latest'], state['responses'], state['pending'] = current, responses, None

    def packet(self, world, frame):
        state = self._world(world)
        require(type(frame) is int and 0 <= frame <= 0x7fffffff and frame in state['responses'],
                'exact published-frame response unavailable')
        return state['responses'][frame]

    def retire(self, world):
        self.worlds.pop(world, None)

    def clear(self):
        self.worlds.clear()
