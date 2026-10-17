"""Versioned dedicated adapter wire format (see docs/protocol-v3.txt)."""
from __future__ import annotations

import asyncio
import re
import struct

HELLO, SET_DECK, LOBBY_READY, LEAVE = 21, 22, 23, 24
LOADED, INPUT = 3, 4
WELCOME, BOOTSTRAP, START, FRAME = 31, 12, 13, 14
MATCH_INFO = 32
LOBBY, MATCH_END, NOTICE, ERROR = 35, 36, 37, 255
VERSION = 3
AUTO_SEAT = 255
BUILD_SHA = "e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758"
SIM_SHA = "107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb"
MAX_BODY = 2 * 1024 * 1024
MAX_INPUT = 65536
MIN_INPUT_WINDOW, MAX_INPUT_WINDOW, DEFAULT_INPUT_WINDOW = 2, 12, 6
KEY = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")


class ProtocolError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise ProtocolError(reason)


def encode(kind, payload=b""):
    require(0 <= kind <= 255 and len(payload) < MAX_BODY, "packet size/type limit")
    return struct.pack("<IB", len(payload) + 1, kind) + payload


async def receive(reader):
    size, = struct.unpack("<I", await reader.readexactly(4))
    require(1 <= size <= MAX_BODY, "packet size limit")
    body = await reader.readexactly(size)
    return body[0], body[1:]


def encode_string(text):
    value = text.encode("utf-8")
    require(len(value) <= 65535, "string too long")
    return struct.pack("<H", len(value)) + value


def hello(slot, profile_id, name, room="local"):
    return struct.pack("<HB", VERSION, slot) + bytes.fromhex(BUILD_SHA + SIM_SHA) + b"".join(
        encode_string(value) for value in (profile_id, name, room))


def decode_hello(payload):
    require(len(payload) >= 73, "short hello")
    version, slot = struct.unpack_from("<HB", payload)
    require(version == VERSION, "unsupported game protocol; update client and server together")
    require(slot in (0, 1, AUTO_SEAT), "unsupported slot")
    require(payload[3:35] == bytes.fromhex(BUILD_SHA), "client original build mismatch")
    require(payload[35:67] == bytes.fromhex(SIM_SHA), "client simulation build mismatch")
    cursor, values = 67, []
    for _ in range(3):
        require(cursor + 2 <= len(payload), "truncated hello string")
        size, = struct.unpack_from("<H", payload, cursor)
        cursor += 2
        require(size <= 128 and cursor + size <= len(payload), "hello string size limit")
        try:
            value = payload[cursor:cursor + size].decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ProtocolError("hello requires UTF8") from error
        values.append(value)
        cursor += size
    require(cursor == len(payload), "extra hello fields")
    profile_id, name, room = values
    require(KEY.fullmatch(profile_id) and KEY.fullmatch(room), "invalid profile or room key")
    require(1 <= len(name) <= 32 and all(ord(c) >= 32 for c in name), "invalid display name")
    return slot, profile_id, name, room


def deck_bytes(deck):
    require(len(deck) == 8, "deck must contain8 slots")
    return struct.pack("<8I", *deck)


def decode_deck(payload):
    require(len(payload) == 32, "deck must contain8 IDs")
    return list(struct.unpack("<8I", payload))


def validate_input_window(value):
    require(type(value) is int and MIN_INPUT_WINDOW <= value <= MAX_INPUT_WINDOW,
            "input window must be an integer in2..12 frames")
    return value


def welcome(slot, input_window, deck):
    require(type(slot) is int and slot in (0, 1), "invalid assigned seat")
    return bytes([slot, validate_input_window(input_window)]) + deck_bytes(deck)


def decode_welcome(payload):
    require(len(payload) == 34 and payload[0] in (0, 1), "invalid protocol3 welcome")
    return payload[0], validate_input_window(payload[1]), decode_deck(payload[2:])
