"""Small bounded protobuf wire reader/editor that preserves untouched bytes.

Supports current proto3 wire types 0, 1, 2 and 5. Deprecated groups are rejected
explicitly. This is not a generic replacement for generated protobuf classes.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

MAX_MESSAGE_BYTES = 32 * 1024 * 1024
MAX_FIELDS = 1_000_000
MAX_FIELD_NUMBER = (1 << 29) - 1


class WireError(ValueError):
    pass


@dataclass(frozen=True)
class Field:
    number: int
    wire_type: int
    value: int | bytes
    raw: bytes


def encode_varint(value: int) -> bytes:
    if type(value) is not int or not 0 <= value < (1 << 64):
        raise WireError("varint value must be uint64")
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    if not 0 <= offset <= len(data):
        raise WireError("varint offset outside message")
    value = 0
    for index in range(10):
        if offset >= len(data):
            raise WireError("truncated varint")
        byte = data[offset]
        offset += 1
        if index == 9 and byte > 1:
            raise WireError("varint exceeds uint64")
        value |= (byte & 127) << (7 * index)
        if byte < 128:
            return value, offset
    raise WireError("overlong varint")


def _key(number: int, wire_type: int) -> bytes:
    if type(number) is not int or not 1 <= number <= MAX_FIELD_NUMBER:
        raise WireError("invalid protobuf field number")
    return encode_varint((number << 3) | wire_type)


def field_uint(number: int, value: int) -> bytes:
    return _key(number, 0) + encode_varint(value)


def field_bytes(number: int, value: bytes) -> bytes:
    if not isinstance(value, bytes):
        raise WireError("length-delimited value must be bytes")
    return _key(number, 2) + encode_varint(len(value)) + value


def field_fixed32(number: int, value: int) -> bytes:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise WireError("fixed32 value outside range")
    return _key(number, 5) + struct.pack("<I", value)


def field_float(number: int, value: float) -> bytes:
    return _key(number, 5) + struct.pack("<f", value)


def field_packed_uint(number: int, values: Iterable[int]) -> bytes:
    return field_bytes(number, b"".join(encode_varint(value) for value in values))


def parse_fields(data: bytes, *, max_bytes: int = MAX_MESSAGE_BYTES,
                 max_fields: int = MAX_FIELDS) -> tuple[Field, ...]:
    if not isinstance(data, bytes) or len(data) > max_bytes:
        raise WireError("message must be bytes within size limit")
    result = []
    offset = 0
    while offset < len(data):
        if len(result) >= max_fields:
            raise WireError("protobuf field count limit")
        start = offset
        key, offset = decode_varint(data, offset)
        number, wire_type = key >> 3, key & 7
        if not 1 <= number <= MAX_FIELD_NUMBER:
            raise WireError("invalid protobuf field number")
        if wire_type == 0:
            value, offset = decode_varint(data, offset)
        elif wire_type in (1, 5):
            size = 8 if wire_type == 1 else 4
            if size > len(data) - offset:
                raise WireError("truncated fixed-width field")
            value = data[offset:offset + size]
            offset += size
        elif wire_type == 2:
            size, offset = decode_varint(data, offset)
            if size > len(data) - offset:
                raise WireError("truncated length-delimited field")
            value = data[offset:offset + size]
            offset += size
        else:
            raise WireError("unsupported protobuf wire type (groups are not supported)")
        result.append(Field(number, wire_type, value, data[start:offset]))
    return tuple(result)


def _singular(data: bytes, number: int, wire_type: int, default, required: bool):
    matches = [field for field in parse_fields(data) if field.number == number]
    if len(matches) > 1:
        raise WireError(f"duplicate singular field {number}")
    if not matches:
        if required:
            raise WireError(f"required field {number} absent")
        return default
    if matches[0].wire_type != wire_type:
        raise WireError(f"wrong wire type for field {number}")
    return matches[0].value


def get_bytes(data: bytes, number: int, default: bytes = b"", *, required: bool = False) -> bytes:
    return _singular(data, number, 2, default, required)


def get_uint(data: bytes, number: int, default: int = 0, *, required: bool = False) -> int:
    return _singular(data, number, 0, default, required)


def get_repeated_bytes(data: bytes, number: int) -> tuple[bytes, ...]:
    result = []
    for field in parse_fields(data):
        if field.number == number:
            if field.wire_type != 2:
                raise WireError(f"wrong repeated message wire type for field {number}")
            result.append(field.value)
    return tuple(result)


def get_repeated_uint(data: bytes, number: int, *, max_values: int = MAX_FIELDS) -> tuple[int, ...]:
    result = []
    for field in parse_fields(data):
        if field.number != number:
            continue
        if field.wire_type == 0:
            result.append(field.value)
        elif field.wire_type == 2:
            offset = 0
            while offset < len(field.value):
                value, offset = decode_varint(field.value, offset)
                result.append(value)
                if len(result) > max_values:
                    raise WireError("packed scalar count limit")
        else:
            raise WireError(f"wrong repeated scalar wire type for field {number}")
        if len(result) > max_values:
            raise WireError("repeated scalar count limit")
    return tuple(result)


def replace_fields(data: bytes, replacements: Mapping[int, Sequence[bytes]]) -> bytes:
    """Replace every occurrence at its first position; preserve all other raw bytes.

    Missing replacement fields append in field-number order. An empty sequence
    deletes the field. Each supplied item must encode exactly one matching field.
    """
    normalized = {}
    for number, values in replacements.items():
        _key(number, 0)
        values = tuple(values)
        for value in values:
            fields = parse_fields(value, max_fields=1)
            if len(fields) != 1 or fields[0].number != number:
                raise WireError("replacement must be one field with the matching number")
        normalized[number] = values
    emitted = set()
    output = []
    for field in parse_fields(data):
        if field.number not in normalized:
            output.append(field.raw)
        elif field.number not in emitted:
            output.extend(normalized[field.number])
            emitted.add(field.number)
    for number in sorted(normalized.keys() - emitted):
        output.extend(normalized[number])
    result = b"".join(output)
    if len(result) > MAX_MESSAGE_BYTES:
        raise WireError("edited message exceeds size limit")
    return result


def signed64(value: int) -> int:
    return value - (1 << 64) if value & (1 << 63) else value
