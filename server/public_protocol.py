"""Opt-in public queue extension; legacy community/custom packets stay unchanged.

Only a client that enters this versioned queue receives its assignment/frame
packets. A queue ticket is scoped to its authenticated community connection.
"""
from __future__ import annotations

import struct

from . import protocol as p
from .community_protocol import Reader
from . import loadout_protocol as loadout

VERSION = 1
ENTER, CANCEL, READY, RETURN, STATE, MATCH, FRAME = range(58, 65)
COMMANDS = frozenset((ENTER, CANCEL, READY, RETURN, loadout.ENTER_LOADOUT))
WAITING, OFFERED, PREPARING, LOADING, RUNNING, RESULTS, RETIRED = range(7)
MODES = {1: (2, (0, 1)), 2: (4, (0, 1, 2, 3)), 5: (4, (0, 2))}
FALLBACK_SECONDS = 30.0


def ticket(value):
    p.require(type(value) is int and 0 < value < 2**64, 'invalid public queue ticket')
    return value


def decode_command(kind, payload):
    p.require(kind in COMMANDS and 14 <= len(payload) <= 256, 'invalid public queue command')
    r = Reader(payload)
    request, version, generation = r.number('I'), r.number('H'), ticket(r.number('Q'))
    p.require(request and version == VERSION, 'unsupported public queue version/request')
    value = dict(request=request, ticket=generation)
    if kind in (ENTER, loadout.ENTER_LOADOUT):
        value['mode'], value['wait_ms'], value['deck'] = r.number('B'), r.number('I'), r.deck()
        p.require(value['mode'] in MODES and value['wait_ms'] <= 30000, 'unsupported public mode/deadline')
        if kind == loadout.ENTER_LOADOUT:
            value['cosmetics'] = loadout.decode(r)
    elif kind in (READY, RETURN):
        value['match'] = r.key()
    r.end()
    return value


def command(kind, request, generation, *, mode=None, deck=None, match=None, wait_ms=30000, cosmetics=None):
    body = struct.pack('<IHQ', request, VERSION, ticket(generation))
    if kind in (ENTER, loadout.ENTER_LOADOUT):
        body += bytes((mode,)) + struct.pack('<I', wait_ms) + p.deck_bytes(deck)
        if kind == loadout.ENTER_LOADOUT: body += loadout.encode(cosmetics)
        else: p.require(cosmetics is None, 'legacy public command cannot carry cosmetics')
    elif kind in (READY, RETURN):
        body += p.encode_string(match)
    decode_command(kind, body)
    return body


def state(generation, phase, mode, elapsed_ms, match='', reason=''):
    p.require(phase in range(7) and mode in MODES and 0 <= elapsed_ms <= 0xffffffff,
              'invalid public queue state')
    p.require(not match or p.KEY.fullmatch(match), 'invalid public match key')
    p.require(len(reason.encode('utf-8')) <= 128, 'public reason too long')
    return (struct.pack('<HQBBI', VERSION, ticket(generation), phase, mode, elapsed_ms)
            + p.encode_string(match) + p.encode_string(reason))


def decode_state(payload):
    r = Reader(payload)
    p.require(r.number('H') == VERSION, 'unsupported public state version')
    value = dict(ticket=ticket(r.number('Q')), phase=r.number('B'), mode=r.number('B'), elapsed_ms=r.number('I'))
    value['match'], value['reason'] = r.text(48), r.text(128)
    r.end()
    state(**{('generation' if key == 'ticket' else key): item for key, item in value.items()})
    return value


def assignment(generation, match, mode, slot, human_mask, input_window, deck, *, cosmetics=None):
    p.require(mode in MODES, 'unsupported public assignment mode')
    count, human_slots = MODES[mode]
    p.require(type(slot) is int and slot in human_slots and type(human_mask) is int and
              human_mask & (1 << slot) and 0 < human_mask < 1 << count and
              not human_mask & ~sum(1 << seat for seat in human_slots), 'invalid public human assignment')
    p.require(p.KEY.fullmatch(match), 'invalid public assignment match')
    return (struct.pack('<HQBBBBB', VERSION, ticket(generation), mode, count, slot, human_mask,
                        p.validate_input_window(input_window)) + p.encode_string(match) + p.deck_bytes(deck)
            + (loadout.encode(cosmetics) if cosmetics is not None else b''))


def decode_assignment(payload, *, complete=False):
    r = Reader(payload)
    p.require(r.number('H') == VERSION, 'unsupported public assignment version')
    value = dict(generation=ticket(r.number('Q')), mode=r.number('B'))
    count = r.number('B')
    value.update(slot=r.number('B'), human_mask=r.number('B'), input_window=r.number('B'), match=r.key(), deck=r.deck())
    if complete: value['cosmetics'] = loadout.decode(r)
    r.end()
    p.require(value['mode'] in MODES and count == MODES[value['mode']][0], 'public participant count differs from mode')
    assignment(**value)
    return value | {'count': count}


def frame(number, inputs):
    p.require(type(number) is int and 0 <= number < 0x80000000 and len(inputs) in (2, 4)
              and set(inputs) == set(range(len(inputs))), 'invalid public frame roster/number')
    p.require(all(isinstance(value, bytes) and 0 < len(value) <= p.MAX_INPUT for value in inputs.values()),
              'public player input size limit')
    return struct.pack('<IB', number, len(inputs)) + b''.join(
        struct.pack('<I', len(inputs[slot])) + inputs[slot] for slot in range(len(inputs)))


def decode_frame(payload, participant_count):
    p.require(participant_count in (2, 4) and 5 <= len(payload) <= 5 + participant_count*(4+p.MAX_INPUT),
              'invalid public frame size/count')
    number, count = struct.unpack_from('<IB', payload)
    p.require(number < 0x80000000 and count == participant_count, 'public frame number/count mismatch')
    offset, inputs = 5, {}
    for slot in range(count):
        p.require(offset + 4 <= len(payload), 'truncated public frame length')
        size, = struct.unpack_from('<I', payload, offset)
        offset += 4
        p.require(0 < size <= p.MAX_INPUT and offset + size <= len(payload), 'public frame player input bound')
        inputs[slot] = payload[offset:offset+size]
        offset += size
    p.require(offset == len(payload), 'extra public frame bytes')
    return number, inputs
