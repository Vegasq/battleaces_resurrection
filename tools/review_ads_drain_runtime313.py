"""Bind the advertising queue drain's indirect call to the IL2CPP invoke export."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, INSTALLED, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
DRAIN = ROOT / 'local/privacy311-ads-request01/drain-one.asm'
RESOLVER = ROOT / 'local/privacy197-runtime-sink01/unity-77fbb0.asm'
CELL = 0x1d0d8e0


def rip_target(address, code):
    assert len(code) == 7 and code[:2] in (b'\x48\x8b', b'\x48\x89', b'\x48\x8d')
    assert code[2] & 0xc7 == 5
    return address + 7 + struct.unpack('<i', code[3:])[0]


def verify():
    original, installed, current = ORIGINAL.read_bytes(), INSTALLED.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    assert hashlib.sha256(current).hexdigest() == INSTALLED_SHA
    pe, ip = PE(original), PE(installed)
    bodies = [(0x361260, 0x361504, DRAIN), (0x77fbb0, 0x781e79, RESOLVER)]
    rows = {}
    for start, end, path in bodies:
        assert pe.function_ends[pe.base+start] == pe.base+end
        rows.update(parse_assembly(path.read_bytes(), pe, original, start, end))
        old = pe.offset(pe.base+start, end-start)
        new = ip.offset(ip.base+start, end-start)
        assert original[old:old+end-start] == installed[new:new+end-start]
    assert rows[0x3613d1]['text'] == 'mov rbx, qword ptr [rbp + 0x58]'
    assert rows[0x3613ee]['text'] == 'mov rdx, rdi'
    assert rows[0x3613f1]['text'] == 'mov rcx, rbx'
    assert rows[0x3613f4]['text'] == 'call rax'
    assert rip_target(0x3613de, rows[0x3613de]['code']) == CELL
    assert rip_target(0x7814a7, rows[0x7814a7]['code']) == CELL
    assert rip_target(0x78149b, rows[0x78149b]['code']) == 0x19abf08
    assert rows[0x7814a2]['code'] == b'\xe8' + struct.pack('<i', 0x6b31c0 - 0x7814a7)
    name = b'il2cpp_runtime_invoke\0'
    offset = pe.offset(pe.base+0x19abf08, len(name))
    assert original[offset:offset+len(name)] == name
    return dict(passed=True, drain_call='0x3613f4', runtime_cell=hex(CELL),
                export='il2cpp_runtime_invoke', target_method_unresolved=True,
                advertising_provider_unresolved=True)


if __name__ == '__main__':
    print('PASS', verify())
