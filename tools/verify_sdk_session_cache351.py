"""Bind the session device-ID cut and all direct cached-ID getter callers."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA

ASM = Path('local/privacy351-session-cache01')
USER_ASM = Path('local/privacy349-user-object01/8141f0.asm')
PREVIOUS_SHA = '89b6da75d36009ec3824859c6583cf29650e7db6d23dd804ac6100fa30ef30fd'
CURRENT_SHA = 'cd71b66d3249985e820fc75c3597034c3e2bcfdfa01da96c8844c19e0df8db08'
LABEL = 'BugsnagUnity.SessionTracker::StartManagedSession'
METHODS = (
    (163545, 'Client', 'InitUserObject', 0, 0x8141f0, 0x814401),
    (163559, 'Client', 'NotifyOnMainThread', 5, 0x815ba0, 0x816cca),
    (163901, 'SessionTracker', 'StartManagedSession', 0, 0x826b40, 0x827208),
    (164070, 'CacheManager', 'GetCachedDeviceId', 0, 0x8368b0, 0x836aca),
)
CALLS = (0x81429d, 0x8160b5, 0x826d9c)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse(path: Path, pe: PE, original: bytes, start: int, end: int):
    raw = b''.join(line for line in path.read_bytes().splitlines(keepends=True)
                   if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                   start <= int(match[1], 16)-pe.base < end)
    return parse_assembly(raw, pe, original, start, end)


def direct_call_candidates(pe: PE, original: bytes, target: int) -> tuple[int, ...]:
    found = []
    for address, size, offset in pe.sections:
        for i in range(size-4):
            if (original[offset+i] == 0xe8 and
                    address+i+5+struct.unpack_from('<i', original, offset+i+1)[0] == target):
                found.append(address+i-pe.base)
    return tuple(sorted(found))


def verify() -> dict:
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert (sha(original), sha(metadata), RECIPE_VERSION) == (OLD_SHA, MD_SHA, 38)
    pe, md = PE(original), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 666)
    bodies = {}
    for index, type_name, name, argc, start, end in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]), method[-1]) == (
            'BugsnagUnity', type_name, name, argc)
        slot = (method[6] & 0xffffff)-1
        assert 0 <= slot < count
        assert struct.unpack_from('<Q', original, pe.offset(table+slot*8, 8))[0] == pe.base+start
        assert pe.function_ends[pe.base+start] == pe.base+end
        if start != 0x8368b0:
            path = USER_ASM if start == 0x8141f0 else ASM/f'{start:x}.asm'
            bodies[start] = parse(path, pe, original, start, end)
    assert md.methods[163901][2] == 59011  # void
    assert md.methods[164070][2] == 55083  # managed string
    assert direct_call_candidates(pe, original, pe.base+0x8368b0) == CALLS
    for start, address in zip((0x8141f0, 0x815ba0, 0x826b40), CALLS):
        assert bodies[start][address]['text'].startswith('call 0x1808368b0')
        assert bodies[start][address]['code'][0] == 0xe8
    session = bodies[0x826b40]
    assert session[0x826da1]['text'] == 'mov rbx, rax'
    assert session[0x826db6]['text'] == 'mov r8, rbx'
    assert session[0x826dbf]['text'].startswith('call 0x18083f8d0')
    matches = [p for p in COMPONENTS['GameAssembly.dll'].patches if p.label == LABEL]
    assert len(matches) == 1
    patch = matches[0]
    offset = pe.offset(pe.base+0x826b40)
    assert (patch.rva, patch.offset, patch.replacement) == (0x826b40, offset, b'\xc3')
    assert original[offset:offset+len(patch.guard)] == patch.guard
    current = patch_component('GameAssembly.dll', original)
    assert sha(current) == CURRENT_SHA
    assert current[offset:offset+0x827208-0x826b40] == b'\xc3'+original[offset+1:offset+0x827208-0x826b40]
    assert current[pe.offset(pe.base+0x815ba0)] == 0xc3
    assert current[pe.offset(pe.base+0x81428e):pe.offset(pe.base+0x81428e)+7] == bytes.fromhex('e9260000009090')
    previous = bytearray(current)
    previous[offset] = original[offset]
    assert sha(previous) == PREVIOUS_SHA
    return dict(passed=True, recipe=RECIPE_VERSION, direct_getter_calls=[hex(x) for x in CALLS],
                original_instructions=sum(map(len, bodies.values())), previous_sha256=PREVIOUS_SHA,
                current_sha256=CURRENT_SHA)


if __name__ == '__main__':
    print('PASS', verify())
