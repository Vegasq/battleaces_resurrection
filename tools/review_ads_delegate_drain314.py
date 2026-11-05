"""Bind the queued advertising request to its managed delegate Invoke method."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, INSTALLED, ORIGINAL_SHA, INSTALLED_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / 'local/privacy301-runtime01/game/UnityPlayer.dll'
ASM = ROOT / 'local/privacy311-ads-request01'


def verify():
    old, installed, current = ORIGINAL.read_bytes(), INSTALLED.read_bytes(), CURRENT.read_bytes()
    assert hashlib.sha256(old).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    assert hashlib.sha256(current).hexdigest() == INSTALLED_SHA
    pe, ip = PE(old), PE(installed)
    bodies = [('request-5fb70.asm', 0x5fb70, 0x5fca2),
              ('start.asm', 0x361510, 0x3615e5),
              ('drain-one.asm', 0x361260, 0x361504),
              ('helper-770d00.asm', 0x770d00, 0x770eab)]
    rows = {}
    for name, start, end in bodies:
        assert pe.function_ends[pe.base + start] == pe.base + end
        rows.update(parse_assembly((ASM / name).read_bytes(), pe, old, start, end))
        a, b = pe.offset(pe.base + start, end-start), ip.offset(ip.base + start, end-start)
        assert old[a:a+end-start] == installed[b:b+end-start]
    resolver_start, resolver_end = 0x77fbb0, 0x781e79
    assert pe.function_ends[pe.base+resolver_start] == pe.base+resolver_end
    rows.update(parse_assembly((ROOT / 'local/privacy197-runtime-sink01/unity-77fbb0.asm').read_bytes(),
                               pe, old, resolver_start, resolver_end))
    a, b = pe.offset(pe.base+resolver_start, resolver_end-resolver_start), ip.offset(ip.base+resolver_start, resolver_end-resolver_start)
    assert old[a:a+resolver_end-resolver_start] == installed[b:b+resolver_end-resolver_start]

    def direct(site, target):
        code = rows[site]['code']
        assert len(code) == 5 and code[0] == 0xe8
        assert site + 5 + struct.unpack('<i', code[1:])[0] == target

    def rip(site, target):
        code = rows[site]['code']
        assert len(code) == 7 and code[2] & 0xc7 == 5
        assert site + 7 + struct.unpack('<i', code[3:])[0] == target

    direct(0x3612cd, 0x770d00)
    assert rows[0x5fb7f]['text'] == 'mov r8, rcx'
    assert rows[0x5fbd6]['text'] == 'mov rcx, rbx'
    assert rows[0x5fc43]['text'] == 'movups xmmword ptr [rax + 0x10], xmm0'
    assert rows[0x361540]['text'] == 'movups xmm0, xmmword ptr [rbx + 0x10]'
    assert rows[0x361551]['text'] == 'movaps xmmword ptr [rsp + 0x30], xmm0'
    direct(0x36155c, 0x361260)
    assert rows[0x3612c0]['text'] == 'lea rcx, [rsp + 0x60]'
    assert rows[0x361262]['text'] == 'push rbx'
    assert rows[0x361263]['text'] == 'lea rbp, [rsp - 0x1d8]'
    assert rows[0x36126b]['text'] == 'sub rsp, 0x2d8'
    assert rows[0x770e7b]['text'] == 'mov qword ptr [rbp + 0xf8], rbx'
    assert rows[0x770d28]['text'] == 'mov rbp, rcx'
    rip(0x770d80, 0x1d0d918)
    rip(0x7812b9, 0x1d0d918)
    rip(0x7812ad, 0x19abb78)
    export = b'il2cpp_object_get_class\0'
    at = pe.offset(pe.base+0x19abb78, len(export))
    assert old[at:at+len(export)] == export
    rip(0x770dd1, 0x196f158)
    literal = b'Invoke\0'
    at = pe.offset(pe.base + 0x196f158, len(literal))
    assert old[at:at+len(literal)] == literal
    assert rows[0x770df7]['text'] == 'cmp dl, byte ptr [r15 + rcx - 0x1]'
    assert rows[0x770dfe]['text'] == 'cmp rcx, 0x7'
    assert rows[0x3613d1]['text'] == 'mov rbx, qword ptr [rbp + 0x58]'
    assert rows[0x3613f1]['text'] == 'mov rcx, rbx'
    assert rows[0x3613f4]['text'] == 'call rax'
    # In the caller, post-sub RBP = RSP + 0x100;therefore RBP+0x58
    # is RSP+0x158,exactly helper RCX (RSP+0x60) plus its +0xf8 method slot.
    assert rows[0x361263]['code'] == bytes.fromhex('488dac2428feffff')
    assert rows[0x36126b]['code'] == bytes.fromhex('4881ecd8020000')
    return dict(passed=True, callback_method='Invoke', helper='0x770d00',
                method_store='invocation+0xf8', method_load='caller RBP+0x58',
                runtime_dispatch='il2cpp_runtime_invoke', provider_identified=False)


if __name__ == '__main__':
    print('PASS', verify())
