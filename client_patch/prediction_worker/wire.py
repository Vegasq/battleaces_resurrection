"""Bounded BAPW v1 codec, independent of native DLL loading."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct

MAGIC, VERSION = b'BAPW', 1
HEADER = struct.Struct('<4sBBHII')
MAX_PAYLOAD, MAX_BUFFER = 32 * 1024 * 1024, 16 * 1024 * 1024
MAX_LOGS, MAX_LOG_BYTES, MAX_SYSTEMS = 256, 16 * 1024, 2048
ERROR, RESPONSE = 1, 0x80


class Op(IntEnum):
    INIT = 1
    DESTROY = 2
    SET_LOG_CALLBACK = 3
    SET_LOG_FLAGS = 4
    CREATE_WORLD = 5
    DESTROY_WORLD = 6
    PROCESS_MSG = 7
    STEP = 8
    MAKE_FRAME = 9
    GET_FRAME = 10
    LABEL_SIZE = 11
    GET_LABEL = 12
    PLAYERS_SIZE = 13
    GET_PLAYERS = 14
    MAP_SIZE = 15
    GET_MAP = 16
    CRASH = 17
    DEBUG_COUNT = 18
    DEBUG_SIZE = 19
    GET_DEBUG = 20
    DEBUG_CLEAR = 21
    DEBUG_ACTIVE = 22
    SYSTEM_COUNT = 23
    SYSTEM_ATTRIBUTES = 24
    PREDICTION_BEGIN = 64
    PREDICTION_AUTHORITY = 65
    PREDICTION_METRICS = 66
    LOCAL_BATCH = 67
    ENTITIES = 68
    PREDICTION_END = 69
    ACTIVE_ENTITIES = 70
    ENTITY_GUARD = 71
    CANONICAL_ROSTER = 76
    PRESENTATION_CORRECTIONS = 77
    SHUTDOWN = 127


LOCAL_GETS = frozenset((Op.GET_FRAME, Op.GET_LABEL, Op.GET_PLAYERS, Op.GET_MAP, Op.GET_DEBUG))
WIRE_OPS = frozenset(Op) - LOCAL_GETS


class ProtocolError(ValueError):
    def __init__(self, message, *, opcode=None, request_id=None):
        super().__init__(message)
        self.opcode, self.request_id = opcode, request_id


def require(value, message):
    if not value:
        raise ProtocolError(message)


@dataclass(frozen=True)
class Packet:
    opcode: int
    request_id: int
    payload: bytes
    flags: int = 0


@dataclass(frozen=True)
class Command:
    opcode: Op
    args: tuple


def read_exact(stream, size, *, eof_ok=False):
    result = bytearray()
    while len(result) < size:
        part = stream.read(size - len(result))
        if not part:
            if eof_ok and not result:
                return None
            raise ProtocolError('truncated worker message')
        require(len(part) <= size - len(result), 'worker stream exceeded requested read')
        result.extend(part)
    return bytes(result)


def decode_request(packet):
    require(type(packet.payload) is bytes and len(packet.payload) <= MAX_PAYLOAD, 'payload exceeds limit')
    try:
        op = Op(packet.opcode)
    except ValueError as exc:
        raise ProtocolError('unknown/reserved worker opcode') from exc
    require(op in WIRE_OPS, 'Get is client-local; no wire request allowed')
    require(packet.flags == 0, 'request flags must be zero')
    require(type(packet.request_id) is int and 1 <= packet.request_id <= 0xffffffff, 'invalid request ID')
    body = packet.payload

    def exact(fmt):
        require(len(body) == struct.calcsize(fmt), 'invalid opcode payload length')
        return struct.unpack(fmt, body)

    if op in (Op.INIT, Op.SET_LOG_CALLBACK):
        args = exact('<B')
        require(args[0] in (0, 1), 'boolean must be zero or one')
    elif op in (Op.DESTROY, Op.CRASH, Op.SHUTDOWN):
        args = exact('<')
    elif op == Op.SET_LOG_FLAGS:
        args = exact('<I')
    elif op == Op.CREATE_WORLD:
        require(bool(body), 'empty GameData')
        args = (body,)
    elif op in (Op.DESTROY_WORLD, Op.DEBUG_CLEAR, Op.PREDICTION_METRICS, Op.ENTITIES, Op.ACTIVE_ENTITIES, Op.ENTITY_GUARD):
        args = exact('<Q')
    elif op in (Op.PROCESS_MSG, Op.PREDICTION_AUTHORITY):
        require(len(body) > 8, 'empty/truncated InputActions')
        if op == Op.PREDICTION_AUTHORITY:
            require(len(body) <= 8 + 2 * 1024 * 1024, 'prediction authority exceeds2MiB')
        args = (struct.unpack_from('<Q', body)[0], body[8:])
    elif op == Op.PREDICTION_BEGIN:
        args = exact('<QII')
        require(1 <= args[1] <= 12 and 4096 <= args[2] <= 64 * 1024 * 1024,
                'prediction lead/journal budget outside bounds')
    elif op == Op.CANONICAL_ROSTER:
        args = exact('<QI')
        require(args[1] == 0, 'canonical AI roster requires own human slot0')
    elif op == Op.PRESENTATION_CORRECTIONS:
        args = exact('<Qi')
        require(args[0] > 0 and 0 <= args[1] <= 0x7fffffff, 'invalid presentation correction world/frame')
    elif op == Op.LOCAL_BATCH:
        require(16 < len(body) <= 16 + 65536, 'local batch player body exceeds64KiB/is empty')
        world, sequence = struct.unpack_from('<QQ', body)
        require(sequence != 0, 'local batch sequence must start at1')
        args = (world, sequence, body[16:])
    elif op == Op.PREDICTION_END:
        args = exact('<Qi')
        require(args[1] >= 0, 'prediction end requires canonical startup')
    elif op == Op.STEP:
        args = exact('<QIi')
    elif op in (Op.MAKE_FRAME, Op.LABEL_SIZE, Op.DEBUG_SIZE):
        args = exact('<QII')
    elif op == Op.PLAYERS_SIZE:
        args = exact('<Qii')
    elif op == Op.MAP_SIZE:
        args = exact('<Qi')
    elif op in (Op.DEBUG_COUNT, Op.SYSTEM_COUNT):
        args = exact('<QI')
    elif op == Op.DEBUG_ACTIVE:
        require(len(body) >= 12, 'truncated debug array header')
        world, count = struct.unpack_from('<QI', body)
        require(count <= MAX_SYSTEMS and len(body) == 12 + 4 * count, 'invalid debug array count/length')
        args = (world, tuple(struct.unpack_from('<' + str(count) + 'i', body, 12)))
    elif op == Op.SYSTEM_ATTRIBUTES:
        require(len(body) >= 12, 'truncated system array header')
        world, count = struct.unpack_from('<QI', body)
        require(count <= MAX_SYSTEMS and len(body) == 12 + 128 * count, 'invalid system array count/length')
        args = (world, count, body[12:])
    else:  # Enum additions are closed until their full codec exists.
        raise ProtocolError('opcode is not implemented')
    if op not in (Op.INIT, Op.DESTROY, Op.SET_LOG_CALLBACK, Op.SET_LOG_FLAGS,
                  Op.CREATE_WORLD, Op.CRASH, Op.SHUTDOWN):
        require(args[0] != 0, 'world ID must be nonzero')
    return Command(op, args)


def read_request(stream, expected_id):
    header = read_exact(stream, HEADER.size, eof_ok=True)
    if header is None:
        return None
    magic, version, opcode, flags, request_id, size = HEADER.unpack(header)
    try:
        require(magic == MAGIC and version == VERSION, 'worker magic/version mismatch')
        require(size <= MAX_PAYLOAD, 'payload exceeds limit')
        require(opcode in WIRE_OPS and flags == 0, 'unknown/reserved opcode or request flags')
        require(request_id == expected_id and request_id > 0, 'request IDs must be contiguous from one')
        payload = read_exact(stream, size)
        packet = Packet(opcode, request_id, payload, flags)
        command = decode_request(packet)
    except ProtocolError as exc:
        exc.opcode, exc.request_id = opcode, request_id
        raise
    return packet, command


def encode_request(opcode, request_id, payload=b''):
    packet = Packet(int(opcode), request_id, payload)
    decode_request(packet)
    return HEADER.pack(MAGIC, VERSION, packet.opcode, 0, request_id, len(payload)) + payload


def encode_response(packet, result, data=b'', logs=(), *, error=False):
    require(type(result) is int and -0x80000000 <= result <= 0x7fffffff, 'invalid native return code')
    require(type(data) is bytes and len(logs) <= MAX_LOGS, 'invalid response data/log count')
    body = bytearray(struct.pack('<iI', result, len(logs)))
    for kind, text in logs:
        require(type(kind) is int and -0x80000000 <= kind <= 0x7fffffff, 'invalid log kind')
        require(type(text) is bytes and len(text) <= MAX_LOG_BYTES, 'log exceeds limit')
        text.decode('utf-8')
        body.extend(struct.pack('<iI', kind, len(text)))
        body.extend(text)
    body.extend(data)
    require(len(body) <= MAX_PAYLOAD, 'response exceeds payload limit')
    return HEADER.pack(MAGIC, VERSION, int(packet.opcode) | RESPONSE, ERROR if error else 0,
                       packet.request_id, len(body)) + body


def error_data(error):
    text = str(error).encode('utf-8', errors='replace')[:MAX_LOG_BYTES].decode('utf-8', errors='ignore').encode('utf-8')
    return struct.pack('<I', len(text)) + text


def write_packet(stream, packet):
    remaining = memoryview(packet)
    while remaining:
        size = stream.write(remaining)
        require(type(size) is int and 0 < size <= len(remaining), 'worker pipe write failed')
        remaining = remaining[size:]
    stream.flush()
