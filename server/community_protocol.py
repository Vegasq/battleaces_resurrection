"""Bounded community-session control v1 over the existing framed game stream.

The first message selects this extension; legacy protocol3 HELLO remains unchanged.
TLS admission still precedes either handshake. See docs/community-protocol.txt.
"""
from __future__ import annotations

import struct
from . import protocol as p

VERSION = 1
HELLO, WELCOME, DIRECTORY, CREATE, LOBBY = range(40, 45)
INVITE, REPLY, CANCEL, START, READY, LEAVE, SET_DECK, RETURN, ACK, INVITATION, REFRESH, ABORTED = range(45, 57)
PRACTICE = 57
COMMANDS = {CREATE, INVITE, REPLY, CANCEL, START, READY, LEAVE, SET_DECK, RETURN, REFRESH, PRACTICE}
MAX_COMMAND = 256
MAX_PLAYERS = 136  # Existing coordinator's maximum connection capacity:64*2+8.
NONE, OPEN, STARTING, LOADING, RUNNING, RESULTS = range(6)
AVAILABLE, IN_LOBBY, IN_MATCH, UNAVAILABLE = range(4)
PENDING, ACCEPTED, DECLINED, CANCELLED, EXPIRED, BUSY = range(6)


class Reader:
    def __init__(self, payload):
        self.payload, self.offset = payload, 0

    def number(self, fmt):
        size = struct.calcsize('<' + fmt)
        p.require(self.offset + size <= len(self.payload), 'truncated community message')
        value, = struct.unpack_from('<' + fmt, self.payload, self.offset)
        self.offset += size
        return value

    def text(self, maximum=128):
        size = self.number('H')
        p.require(size <= maximum and self.offset + size <= len(self.payload), 'community string bound')
        raw = self.payload[self.offset:self.offset + size]
        self.offset += size
        try:
            value = raw.decode('utf-8', errors='strict')
        except UnicodeError:
            raise p.ProtocolError('community string requires UTF8') from None
        p.require(all(ord(c) >= 32 for c in value), 'invalid community text')
        return value

    def key(self):
        value = self.text(48)
        p.require(p.KEY.fullmatch(value), 'invalid community key')
        return value

    def flag(self):
        value = self.number('B')
        p.require(value in (0, 1), 'invalid community flag')
        return bool(value)

    def deck(self):
        p.require(self.offset + 32 <= len(self.payload), 'truncated community deck')
        value = p.decode_deck(self.payload[self.offset:self.offset + 32])
        self.offset += 32
        return value

    def end(self):
        p.require(self.offset == len(self.payload), 'extra community fields')


def hello(profile_id, name):
    return struct.pack('<H', VERSION) + p.hello(p.AUTO_SEAT, profile_id, name, 'community')


def decode_hello(payload):
    p.require(len(payload) >= 2 and struct.unpack_from('<H', payload)[0] == VERSION,
              'unsupported community protocol')
    slot, profile_id, name, room = p.decode_hello(payload[2:])
    p.require(slot == p.AUTO_SEAT and room == 'community', 'invalid community hello')
    return profile_id, name


def welcome(profile_id, deck):
    return struct.pack('<HH', VERSION, p.VERSION) + p.encode_string(profile_id) + p.deck_bytes(deck)


def decode_command(kind, payload):
    p.require(kind in COMMANDS and 4 <= len(payload) <= MAX_COMMAND, 'invalid community command')
    r = Reader(payload)
    request = r.number('I')
    p.require(request != 0, 'community request ID must be positive')
    result = {'request': request}
    if kind == CREATE:
        result['mode'] = r.number('B')
    elif kind == INVITE:
        result['target'] = r.key()
    elif kind in (REPLY, CANCEL):
        result['invite'] = r.key()
        if kind == REPLY:
            result['accept'] = r.flag()
    elif kind in (START, READY, LEAVE):
        result['lobby'] = r.key()
        if kind == START:
            result['revision'] = r.number('Q')
        elif kind == READY:
            result['epoch'], result['ready'] = r.number('I'), r.flag()
    elif kind == SET_DECK:
        result['deck'] = r.deck()
    elif kind == RETURN:
        result['match'] = r.key()
    elif kind == PRACTICE:
        result['active'] = r.flag()
    r.end()
    return result


def acknowledgement(request, kind, ok, reason='', object_id=''):
    return struct.pack('<IBB', request, kind, bool(ok)) + p.encode_string(reason) + p.encode_string(object_id)


def directory(revision, rows):
    p.require(len(rows) <= MAX_PLAYERS, 'community directory capacity')
    return struct.pack('<QH', revision, len(rows)) + b''.join(
        p.encode_string(profile) + p.encode_string(name) + bytes((status, bool(invitable)))
        for profile, name, status, invitable in rows)


def lobby_state(lobby, sessions, reason=''):
    if lobby is None:
        return struct.pack('<QBI', 0, NONE, 0) + b'\0\0' * 3 + p.encode_string(reason) + b'\0'
    header = struct.pack('<QBI', lobby.revision, lobby.phase, lobby.epoch)
    header += b''.join(p.encode_string(value) for value in (lobby.id, lobby.host, lobby.match_id or '', reason))
    return header + bytes((len(lobby.members),)) + b''.join(
        p.encode_string(profile) + p.deck_bytes(sessions[profile].deck) +
        bytes((profile in lobby.ready, profile in lobby.returned)) for profile in lobby.members)


def invitation(invite, status, remaining_ms):
    return bytes((status,)) + struct.pack('<I', max(0, remaining_ms)) + b''.join(
        p.encode_string(value) for value in (invite.id, invite.lobby, invite.sender, invite.target))


def aborted(match_id, reason):
    return p.encode_string(match_id) + p.encode_string(reason)
