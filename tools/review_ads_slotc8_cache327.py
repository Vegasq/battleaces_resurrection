"""Bind slot+c8's tail to the existing identity query and cache cuts."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_ads_virtual_targets310 import CURRENT, verify as verify_virtual
from tools.review_ads_slotc8_predicate326 import verify as verify_predicate
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT/'local/privacy110-cached-serialization01'
BODIES = ((0xc41ec0, 0xc4222a, ASM/'unity-c41ec0.asm'),
          (0xc32430, 0xc32876, ASM/'unity-c32430.asm'))
PATCHES = ((0xc41f0c, 'skip identity-change analytics cache serialization call',
            bytes.fromhex('9090909090')),
           (0xc32468, 'analytics identity refresh uses existing unknown device sentinel',
            bytes.fromhex('e902000000')))


def body(pe, raw, start, end):
    offset = pe.offset(pe.base+start, end-start)
    return raw[offset:offset+end-start]


def verify():
    assert RECIPE_VERSION == 34 and verify_virtual()['passed']
    assert verify_predicate()['passed']
    original, current = ORIGINAL.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(current).hexdigest() == INSTALLED_SHA
    source = patch_component('UnityPlayer.dll', original)
    pe, cp, sp = PE(original), PE(current), PE(source)
    rows = {}
    for start, end, path in BODIES:
        assert pe.function_ends[pe.base+start] == pe.base+end
        rows[start] = parse_assembly(path.read_bytes(), pe, original, start, end)
        before = bytearray(body(pe, original, start, end))
        for rva, label, replacement in PATCHES:
            if not start <= rva < end:
                continue
            patch = [p for p in COMPONENTS['UnityPlayer.dll'].patches if p.label == label]
            assert len(patch) == 1
            patch = patch[0]
            assert (patch.rva, patch.offset, patch.replacement) == (
                rva, pe.offset(pe.base+rva), replacement)
            assert body(pe, original, rva, rva+len(patch.guard)) == patch.guard
            before[rva-start:rva-start+len(replacement)] = replacement
        assert bytes(before) == body(cp, current, start, end)
        assert bytes(before) == body(sp, source, start, end)
    cache, refresh = rows[0xc41ec0], rows[0xc32430]
    assert cache[0xc41ecd]['text'] == 'mov rbx, rcx'
    assert cache[0xc41ed6]['text'] == 'mov rax, qword ptr [rcx]'
    assert cache[0xc41ed9]['text'] == 'call qword ptr [rax + 0x40]'
    assert cache[0xc41f0c]['text'].startswith('call 0x180c4e140')
    assert refresh[0xc3244d]['text'] == 'mov r15, rcx'
    assert refresh[0xc3245b]['text'] == 'mov rax, qword ptr [rcx]'
    assert refresh[0xc3245e]['text'] == 'call qword ptr [rax + 0xf0]'
    assert refresh[0xc32468]['text'].startswith('call 0x1809fb910')
    assert refresh[0xc3246f]['text'].startswith('lea rax, [rip +')
    for raw, descriptor in ((original, pe), (source, sp), (current, cp)):
        for table in (0x1a2aec0, 0x1a2c538):
            assert struct.unpack_from('<Q', raw, descriptor.offset(descriptor.base+table+0x40, 8))[0] == descriptor.base+0xc32430
        assert body(descriptor, raw, 0x1988fa8, 0x1988fb0).startswith(b'unknown\0')
    return dict(passed=True, source_recipe=34,
                original_sha256=ORIGINAL_SHA, installed_sha256=INSTALLED_SHA,
                decoded_instructions={hex(k): len(v) for k, v in rows.items()},
                guarded_sites=[hex(x[0]) for x in PATCHES])


if __name__ == '__main__':
    print('PASS', verify())
