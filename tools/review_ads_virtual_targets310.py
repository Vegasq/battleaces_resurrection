"""Bound original Main connection-state virtual targets without executing Unity."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, INSTALLED, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly


ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / 'local/privacy310-virtual-targets01'
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
BODIES = {
    'slot38': (0xc34430, 0xc34d67),
    'slota0': (0xc3d120, 0xc3d1a5),
    'slot98': (0xc3d0f0, 0xc3d116),
    'slota8': (0xc3d1b0, 0xc3d270),
    'callback-d0': (0xc2e6d0, 0xc2e783),
    'slotc8': (0xc32e30, 0xc3302c),
}
SLOTS = {0x38: 0xc34430, 0xa0: 0xc3d120,
         0x98: 0xc3d0f0, 0xa8: 0xc3d1b0, 0xc8: 0xc32e30}
ANCHORS = {
    'slot38': {0xc344a1: 'call qword ptr [rax + 0xa8]',
               0xc3450e: 'lea rdx, [rip - 0x5e75]',
               0xc34518: 'call 0x180c46880 <UnityMain+0x441420>',
               0xc3468f: 'call qword ptr [rax + 0x38]',
               0xc347d1: 'lea rdx, [rip - 0x6118]',
               0xc347db: 'call 0x180c46880 <UnityMain+0x441420>',
               0xc34a8e: 'lea rdx, [rip - 0x63c5]',
               0xc34a98: 'call 0x180c46880 <UnityMain+0x441420>'},
    'slota0': {0xc3d152: 'call qword ptr [rax + 0x98]',
               0xc3d158: 'mov eax, 0x4'},
    'slot98': {0xc3d104: 'call 0x180c3dc00 <UnityMain+0x4387a0>',
               0xc3d111: 'jmp 0x180c3e7f0 <UnityMain+0x439390>'},
    'slota8': {0xc3d1c4: 'call qword ptr [rax + 0x98]',
               0xc3d205: 'mov eax, 0x5'},
    'callback-d0': {0xc2e6ed: 'lea rsi, [rcx + 0x1350]',
                    0xc2e756: 'call 0x180c4f270 <UnityMain+0x449e10>'},
    'slotc8': {0xc32eb0: 'call 0x180c4ee80 <UnityMain+0x449a20>',
               0xc32eda: 'mov rdi, qword ptr [rsi + 0x1340]',
               0xc32fc0: 'call qword ptr [rax + 0xf0]',
               0xc33021: 'jmp 0x180c41ec0 <UnityMain+0x43ca60>'},
}


def verify():
    original, installed = ORIGINAL.read_bytes(), INSTALLED.read_bytes()
    current = CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    assert hashlib.sha256(current).hexdigest() == INSTALLED_SHA
    pe, ip = PE(original), PE(installed)
    for table in (0x1a2aec0, 0x1a2c538):
        for slot, target in SLOTS.items():
            assert struct.unpack_from('<Q', original, pe.offset(pe.base + table + slot, 8))[0] == pe.base + target
    result = {}
    for name, (start, end) in BODIES.items():
        assert pe.function_ends[pe.base + start] == pe.base + end
        rows = parse_assembly((ASM / (name + '.asm')).read_bytes(), pe, original, start, end)
        for address, expected in ANCHORS[name].items():
            assert rows[address]['text'] == expected
        old_off = pe.offset(pe.base + start, end-start)
        new_off = ip.offset(ip.base + start, end-start)
        assert original[old_off:old_off+end-start] == installed[new_off:new_off+end-start]
        assert not any('0x180c307c0' in row['text'] or '0x1498]' in row['text']
                       for row in rows.values())
        result[name] = len(rows)
        if name == 'slot38':
            for site, target in ((0xc3450e, 0xc2e6a0),
                                 (0xc347d1, 0xc2e6c0),
                                 (0xc34a8e, 0xc2e6d0)):
                code = rows[site]['code']
                assert len(code) == 7 and site + 7 + struct.unpack('<i', code[3:])[0] == target
    # The c34430 branch registers this short callback. It dispatches through
    # vtable+c8 only when a stack flag is set; it is not c307c0 itself.
    leaf = original[pe.offset(pe.base + 0xc2e6a0, 16):pe.offset(pe.base + 0xc2e6a0, 16)+16]
    assert leaf == bytes.fromhex('807c242800740a488b0148ffa0c80000')
    assert original[pe.offset(pe.base + 0xc2e6a0, 16):pe.offset(pe.base + 0xc2e6a0, 16)+16] == installed[
        ip.offset(ip.base + 0xc2e6a0, 16):ip.offset(ip.base + 0xc2e6a0, 16)+16]
    callback_c0 = bytes.fromhex('807c2428000f85e52f0100c3')
    old_c0 = pe.offset(pe.base + 0xc2e6c0, len(callback_c0))
    new_c0 = ip.offset(ip.base + 0xc2e6c0, len(callback_c0))
    assert original[old_c0:old_c0+len(callback_c0)] == callback_c0
    assert installed[new_c0:new_c0+len(callback_c0)] == callback_c0
    return {'passed': True, 'decoded_instructions': result,
            'reviewed_vtable_slots': [hex(x) for x in sorted(SLOTS)],
            'registered_immediate_callbacks': ['0xc2e6a0', '0xc2e6c0', '0xc2e6d0'],
            'advertising_callback_identified': False}


if __name__ == '__main__':
    print('PASS', verify())
