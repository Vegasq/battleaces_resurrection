"""Bind the SDK Client user-init ID-query cut to the original call and owner flow."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA

ASM = Path('local/privacy349-user-object01')
PREVIOUS_SHA = 'ba894975597777edd2e7544ea2df9aafb59101800885734e7decb0b66660ff92'
CURRENT_SHA = '89b6da75d36009ec3824859c6583cf29650e7db6d23dd804ac6100fa30ef30fd'
LATEST_SHA = 'cd71b66d3249985e820fc75c3597034c3e2bcfdfa01da96c8844c19e0df8db08'
LABEL = 'BugsnagUnity.Client::InitUserObject cached device ID'
METHODS = (
    (163545, 'BugsnagUnity', 'Client', 'InitUserObject', 0, 59011, 0x8141f0, 0x814401),
    (164070, 'BugsnagUnity', 'CacheManager', 'GetCachedDeviceId', 0, 55083, 0x8368b0, 0x836aca),
    (164607, 'BugsnagUnity.Payload', 'User', '.ctor', 0, 59011, 0x84fdf0, 0x84ff02),
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_asm(path: Path, pe: PE, original: bytes, start: int, end: int):
    raw = b''.join(line for line in path.read_bytes().splitlines(keepends=True)
                   if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                   start <= int(match[1], 16)-pe.base < end)
    return parse_assembly(raw, pe, original, start, end)


def verify() -> dict:
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert (sha(original), sha(metadata)) == (OLD_SHA, MD_SHA) and RECIPE_VERSION in (37, 38)
    pe, md = PE(original), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 666)
    bodies = {}
    for index, namespace, type_name, name, argc, return_type, start, end in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
                method[2], method[-1]) == (namespace, type_name, name, return_type, argc)
        slot = (method[6] & 0xffffff)-1
        assert 0 <= slot < count
        assert struct.unpack_from('<Q', original, pe.offset(table+slot*8, 8))[0] == pe.base+start
        assert pe.function_ends[pe.base+start] == pe.base+end
        bodies[start] = read_asm(ASM/f'{start:x}.asm', pe, original, start, end)
    init, user = bodies[0x8141f0], bodies[0x84fdf0]
    assert init[0x814289]['text'].startswith('call 0x18084fdf0')
    assert init[0x81429d]['text'].startswith('call 0x1808368b0')
    assert init[0x8142b4]['text'].startswith('call 0x1808501e0')
    assert init[0x8142c4]['text'] == 'mov qword ptr [rdi], rsi'
    assert init[0x8142b9]['text'].startswith('cmp dword ptr [rip +')
    assert user[0x84fe9e]['text'] == 'mov qword ptr [r8], rbx'
    # The constructor's direct call reaches the user-init method; the new
    # branch skips only the cache query and Id setter after User construction.
    assert original[pe.offset(pe.base+0x812ec4):pe.offset(pe.base+0x812ec4)+5] == bytes.fromhex('e827130000')
    patch = [p for p in COMPONENTS['GameAssembly.dll'].patches if p.label == LABEL]
    assert len(patch) == 1
    patch = patch[0]
    offset = pe.offset(pe.base+0x81428e)
    assert (patch.rva, patch.offset, patch.replacement) == (
        0x81428e, offset, bytes.fromhex('e9260000009090'))
    assert original[offset:offset+len(patch.guard)] == patch.guard
    current = patch_component('GameAssembly.dll', original)
    if RECIPE_VERSION == 38:
        assert sha(current) == LATEST_SHA
        normalized = bytearray(current)
        session = pe.offset(pe.base+0x826b40)
        assert normalized[session] == 0xc3
        normalized[session] = original[session]
        current = bytes(normalized)
    assert sha(current) == CURRENT_SHA
    assert current[offset:offset+7] == patch.replacement
    previous = bytearray(current)
    previous[offset:offset+7] = original[offset:offset+7]
    assert sha(previous) == PREVIOUS_SHA
    return dict(passed=True, recipe=RECIPE_VERSION, query_call='0x81429d',
                preserved_user_store='0x8142c4', original_instructions=sum(map(len, bodies.values())),
                previous_sha256=PREVIOUS_SHA, current_sha256=CURRENT_SHA)


if __name__ == '__main__':
    print('PASS', verify())
