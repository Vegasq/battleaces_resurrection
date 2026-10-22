"""Bounded community-session control v1 over the existing framed game stream.

The first message selects this extension; legacy protocol3 HELLO remains unchanged.
TLS admission still precedes either handshake. See docs/community-protocol.txt.
"""
from __future__ import annotations

import struct
from . import protocol as p
from . import loadout_protocol as loadout

VERSION = 1
PORTRAIT_VERSION = 2
DIRECTORY_PORTRAITS = 69
HELLO, WELCOME, DIRECTORY, CREATE, LOBBY = range(40, 45)
INVITE, REPLY, CANCEL, START, READY, LEAVE, SET_DECK, RETURN, ACK, INVITATION, REFRESH, ABORTED = range(45, 57)
PRACTICE = 57
COMMANDS = {CREATE, INVITE, REPLY, CANCEL, START, READY, LEAVE, SET_DECK, RETURN, REFRESH, PRACTICE, loadout.SET_LOADOUT}
MAX_COMMAND = 256
MAX_PLAYERS = 136  # Preserve the community v1 directory bound, including team queues.
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


def hello(profile_id, name, *, version=VERSION):
    p.require(version in (VERSION, PORTRAIT_VERSION), 'unsupported community protocol')
    return struct.pack('<H', version) + p.hello(p.AUTO_SEAT, profile_id, name, 'community')


def hello_version(payload):
    p.require(len(payload) >= 2, 'truncated community hello')
    version, = struct.unpack_from('<H', payload)
    p.require(version in (VERSION, PORTRAIT_VERSION), 'unsupported community protocol')
    return version


def decode_hello(payload):
    hello_version(payload)
    slot, profile_id, name, room = p.decode_hello(payload[2:])
    p.require(slot == p.AUTO_SEAT and room == 'community', 'invalid community hello')
    return profile_id, name


def welcome(profile_id, deck, *, version=VERSION):
    p.require(version in (VERSION, PORTRAIT_VERSION), 'unsupported community protocol')
    return struct.pack('<HH', version, p.VERSION) + p.encode_string(profile_id) + p.deck_bytes(deck)


def decode_command(kind, payload):
    from . import public_protocol as public
    if kind in public.COMMANDS:
        return public.decode_command(kind, payload)
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
    elif kind == loadout.SET_LOADOUT:
        p.require(r.number('H') == loadout.VERSION, 'unsupported complete loadout version')
        result['deck'], result['cosmetics'] = r.deck(), loadout.decode(r)
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


def directory_portraits(revision, rows, catalog_sha256, portraits):
    """Version2 clients only; v1 directory bytes and recipients stay unchanged."""
    p.require(len(rows) <= MAX_PLAYERS, 'community directory capacity')
    p.require(type(catalog_sha256) is str and len(catalog_sha256) == 64 and
              all(c in '0123456789abcdef' for c in catalog_sha256), 'invalid portrait catalog')
    body = struct.pack('<H', 1) + bytes.fromhex(catalog_sha256) + struct.pack('<QH', revision, len(rows))
    for profile, name, status, invitable in rows:
        portrait = portraits.get(profile, 0)
        p.require(type(portrait) is int and 0 <= portrait <= 0xffffffff and
                  (not portrait or catalog_sha256 != '0'*64), 'invalid directory portrait')
        body += (p.encode_string(profile) + p.encode_string(name) + bytes((status, bool(invitable))) +
                 struct.pack('<I', portrait))
    p.require(len(body) <= 32768, 'portrait directory size')
    return body


def lobby_state(lobby, sessions, reason='', *, complete=False):
    prefix = struct.pack('<H', loadout.VERSION) if complete else b''
    if lobby is None:
        return prefix + struct.pack('<QBI', 0, NONE, 0) + b'\0\0' * 3 + p.encode_string(reason) + b'\0'
    header = struct.pack('<QBI', lobby.revision, lobby.phase, lobby.epoch)
    header += b''.join(p.encode_string(value) for value in (lobby.id, lobby.host, lobby.match_id or '', reason))
    return prefix + header + bytes((len(lobby.members),)) + b''.join(
        p.encode_string(profile) + p.deck_bytes(sessions[profile].deck) +
        (loadout.encode(sessions[profile].cosmetics) if complete else b'') +
        bytes((profile in lobby.ready, profile in lobby.returned)) for profile in lobby.members)


def invitation(invite, status, remaining_ms):
    return bytes((status,)) + struct.pack('<I', max(0, remaining_ms)) + b''.join(
        p.encode_string(value) for value in (invite.id, invite.lobby, invite.sender, invite.target))


def aborted(match_id, reason):
    return p.encode_string(match_id) + p.encode_string(reason)
