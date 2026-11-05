"""Bind the three Main virtual +f0 calls in the connection-state slot+c8 path."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_ads_virtual_targets310 import CURRENT
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT/'local/privacy310-virtual-targets01/slotc8.asm'
PREDICATE_ASM = ROOT/'local/privacy136-adjacent-source01/unity-c33490.asm'
CALLS = (0xc32fc0, 0xc32fdf, 0xc33004)


def body(pe, raw, start, end):
    off = pe.offset(pe.base+start, end-start)
    return raw[off:off+end-start]


def verify():
    original, current = ORIGINAL.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(current).hexdigest() == INSTALLED_SHA
    pe, cp = PE(original), PE(current)
    for table in (0x1a2aec0, 0x1a2c538):
        for raw, descriptor in ((original, pe), (current, cp)):
            value = struct.unpack_from('<Q', raw, descriptor.offset(descriptor.base+table+0xf0, 8))[0]
            assert value == descriptor.base+0xc33490
    start, end = 0xc32e30, 0xc3302c
    assert pe.function_ends[pe.base+start] == pe.base+end
    rows = parse_assembly(ASM.read_bytes(), pe, original, start, end)
    assert rows[0xc32e3a]['text'] == 'mov rsi, rcx'
    assert [a for a, row in rows.items() if row['text'].split()[0] in ('mov','lea','pop','xchg')
            and row['text'].split()[1].startswith('rsi')] == [0xc32e3a, 0xc33020, 0xc3302a]
    assert tuple(a for a, row in rows.items() if row['text'] == 'call qword ptr [rax + 0xf0]') == CALLS
    for call, rcx, vtable in ((0xc32fc0, 0xc32fbd, 0xc32fba),
                              (0xc32fdf, 0xc32fdc, 0xc32fd9),
                              (0xc33004, 0xc33001, 0xc32ffe)):
        assert rows[rcx]['text'] == 'mov rcx, rsi'
        assert rows[vtable]['text'] == 'mov rax, qword ptr [rsi]'
        assert rows[call]['code'] == bytes.fromhex('ff90f0000000')
    assert body(pe, original, start, end) == body(cp, current, start, end)
    pred_start, pred_end = 0xc33490, 0xc334d7
    assert pe.function_ends[pe.base+pred_start] == pe.base+pred_end
    predicate = parse_assembly(PREDICATE_ASM.read_bytes(), pe, original, pred_start, pred_end)
    assert predicate[0xc33499]['text'].startswith('mov rcx, qword ptr [rip +')
    assert predicate[0xc334a5]['text'] == 'add rcx, 0x98'
    assert predicate[0xc334af]['text'] == 'call qword ptr [rax + 0x40]'
    assert predicate[0xc334b6]['text'] == 'lea rcx, [rbx + 0x14a0]'
    assert predicate[0xc334c0]['text'] == 'call qword ptr [rax + 0x30]'
    assert body(pe, original, pred_start, pred_end) == body(cp, current, pred_start, pred_end)
    # Prior128 binds these two virtual targets to boolean getters. Recheck the
    # concrete table entries and leaf bytes in both exact images.
    for raw, descriptor in ((original, pe), (current, cp)):
        assert struct.unpack_from('<Q', raw, descriptor.offset(descriptor.base+0x1a27a98+0x40, 8))[0] == descriptor.base+0xc05a70
        assert body(descriptor, raw, 0xc05a70, 0xc05a75) == bytes.fromhex('0fb6411ac3')
        assert struct.unpack_from('<Q', raw, descriptor.offset(descriptor.base+0x1a2afc8+0x30, 8))[0] == descriptor.base+0xc30890
        assert body(descriptor, raw, 0xc30890, 0xc30898) == bytes.fromhex('0fb681a8010000c3')
    return dict(passed=True, slotc8_calls=[hex(x) for x in CALLS],
                virtual_target='0xc33490', original_sha256=ORIGINAL_SHA,
                installed_sha256=INSTALLED_SHA, predicate_instructions=len(predicate))


if __name__ == '__main__':
    print('PASS', verify())
