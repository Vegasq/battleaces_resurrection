"""Disabled-by-default arrival-command experiment; normal frame input is unchanged."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import re
import struct
from types import MappingProxyType

from . import protocol as p
from .game_data import MAX_ACTIONS, MAX_INPUT_BYTES, encode_player_input
from .protobuf_wire import get_repeated_bytes, parse_fields

NEGOTIATE, ACK, BATCH, HEARTBEAT, READY, VERSION = 70, 71, 72, 73, 74, 1
MATCH = re.compile(r'[0-9a-f]{32}\Z')


def _match(value):
    p.require(isinstance(value, str) and MATCH.fullmatch(value), 'invalid command match identity')
    return value.encode('ascii')


def batch(match, sequence, body):
    p.require(type(sequence) is int and 1 <= sequence < 2**64, 'invalid command sequence')
    p.require(isinstance(body, bytes) and len(body) <= MAX_INPUT_BYTES, 'command batch size limit')
    return bytes([VERSION]) + _match(match) + struct.pack('<Q', sequence) + body


def decode_batch(payload):
    p.require(isinstance(payload, bytes) and 41 <= len(payload) <= 41 + MAX_INPUT_BYTES and
              payload[0] == VERSION, 'invalid command batch header')
    try: identity = payload[1:33].decode('ascii')
    except UnicodeError: raise p.ProtocolError('invalid command match identity') from None
    _match(identity)
    sequence, = struct.unpack_from('<Q', payload, 33)
    p.require(sequence != 0, 'invalid command sequence')
    return identity, sequence, payload[41:]


def heartbeat(match, last_applied):
    p.require(type(last_applied) is int and -1 <= last_applied <= 0x7fffffff, 'invalid command heartbeat frame')
    return bytes([VERSION]) + _match(match) + struct.pack('<I', last_applied & 0xffffffff)


def decode_heartbeat(payload):
    p.require(isinstance(payload, bytes) and len(payload) == 37 and payload[0] == VERSION,
              'invalid command heartbeat header')
    try: identity = payload[1:33].decode('ascii')
    except UnicodeError: raise p.ProtocolError('invalid command match identity') from None
    _match(identity)
    frame, = struct.unpack_from('<I', payload, 33)
    p.require(frame == 0xffffffff or frame <= 0x7fffffff, 'invalid command heartbeat frame')
    return identity, -1 if frame == 0xffffffff else frame


def ready(match):
    return bytes([VERSION]) + _match(match)


def decode_ready(payload):
    p.require(isinstance(payload, bytes) and len(payload) == 33 and payload[0] == VERSION,
              'invalid command startup readiness header')
    try: identity = payload[1:].decode('ascii')
    except UnicodeError: raise p.ProtocolError('invalid command match identity') from None
    _match(identity)
    return identity


@dataclass(frozen=True)
class CommandBatch:
    slot: int
    sequence: int
    body: bytes
    actions: tuple

    @property
    def body_sha256(self): return hashlib.sha256(self.body).hexdigest()

    @property
    def action_count(self): return len(self.actions)


@dataclass(frozen=True)
class SealedFrame:
    frame: int
    inputs: object
    batches: tuple


class ArrivalScheduler:
    def __init__(self, validation, human_slots, *, max_queued_batches=64, max_queued_bytes=256*1024):
        slots = frozenset(human_slots)
        p.require(slots and slots <= validation.players.keys(), 'invalid command human roster')
        p.require(type(max_queued_batches) is int and 1 <= max_queued_batches <= 256 and
                  type(max_queued_bytes) is int and 1 <= max_queued_bytes <= 4*1024*1024,
                  'invalid command queue capacity')
        self.validation, self.slots = validation, slots
        self.max_queued_batches, self.max_queued_bytes = max_queued_batches, max_queued_bytes
        self.queues = {slot: deque() for slot in slots}
        self.queued_bytes = {slot: 0 for slot in slots}
        self.next_sequence = {slot: 1 for slot in slots}
        self.joined = set()
        self.next_frame, self.inflight = 0, None

    @property
    def ready(self): return self.joined == self.slots

    @property
    def queued_sequences(self):
        return MappingProxyType({slot: tuple(item.sequence for item in queue) for slot, queue in self.queues.items()})

    def accept(self, slot, sequence, body):
        p.require(slot in self.slots and type(sequence) is int and 1 <= sequence < 2**64 and
                  sequence == self.next_sequence[slot], 'command sequence must be contiguous')
        canonical = self.validation.validate_player_input(slot, body)
        p.require(len(canonical) <= MAX_INPUT_BYTES, 'canonical command batch size limit')
        actions = get_repeated_bytes(canonical, 2)
        joins = [index for index, action in enumerate(actions) if parse_fields(action)[0].number == 3]
        if slot not in self.joined:
            p.require(sequence == 1 and joins == [0], 'first command batch requires exactly one initial JoinArmy')
        else:
            p.require(not joins, 'JoinArmy is allowed once in the initial command batch')
        queue = self.queues[slot]
        p.require(len(queue) < self.max_queued_batches and
                  self.queued_bytes[slot] + len(canonical) <= self.max_queued_bytes, 'command queue capacity reached')
        accepted = CommandBatch(slot, sequence, canonical, actions)
        queue.append(accepted)
        self.queued_bytes[slot] += len(canonical)
        self.next_sequence[slot] += 1
        if joins: self.joined.add(slot)
        return accepted

    def seal(self, frame):
        p.require(type(frame) is int and frame == self.next_frame and frame <= 0x7fffffff and
                  self.inflight is None, 'command frame is already sealed or out of order')
        if not self.ready: return None
        inputs, selected = {}, []
        # Validate every selected body and assembled player before mutating any queue.
        for slot in sorted(self.slots):
            actions = []
            identity = self.validation.match.identities_by_slot[slot]
            for item in self.queues[slot]:
                combined = actions + list(item.actions)
                body = encode_player_input(identity, combined)
                if len(combined) > MAX_ACTIONS or len(body) > MAX_INPUT_BYTES: break
                p.require(self.validation.validate_player_input(slot, item.body) == item.body,
                          'accepted command body changed during sealing')
                actions, selected = combined, [*selected, item]
            inputs[slot] = self.validation.validate_player_input(slot, encode_player_input(identity, actions))
        sealed = SealedFrame(frame, MappingProxyType(inputs), tuple(selected))
        for item in selected:
            p.require(self.queues[item.slot][0] is item, 'command queue order changed')
            self.queues[item.slot].popleft()
            self.queued_bytes[item.slot] -= len(item.body)
        self.inflight = sealed
        self.next_frame = frame + 1  # Advance BEFORE any worker await can admit a new batch.
        return sealed

    def commit(self, frame):
        p.require(self.inflight is not None and self.inflight.frame == frame, 'command commit differs from sealed frame')
        items = self.inflight.batches
        self.inflight = None
        return items
