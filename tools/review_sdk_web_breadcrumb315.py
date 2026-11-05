"""Bind SDK web-request breadcrumb callback to the existing constructor cut."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA

ROOT = Path(__file__).resolve().parents[1]
INSTALLED = ROOT / 'local/privacy301-runtime01/game/GameAssembly.dll'
INSTALLED_SHA = '30600add160a5bd1c23f4f3e37749080596985582ce577e22308cbfe9c64713e'
ASM = ROOT / 'local/privacy315-web-breadcrumb01'
METHODS = {
    'ctor': (163535, '.ctor', 0x6000090, 0x812690, 0x81379a,
             ROOT / 'local/privacy138-sdk-lifetime01/game-812690.asm'),
    'send': (163550, 'Send', 0x600009f, 0x8147e0, 0x814820, ASM / 'send.asm'),
    'web-complete': (163584, 'OnWebRequestComplete', 0x60000c1,
                     0x817e30, 0x818039, ASM / 'complete.asm'),
    'network-breadcrumb': (163587, 'LeaveNetworkBreadcrumb', 0x60000c4,
                           0x8181f0, 0x81884e, ASM / 'leave.asm'),
}


def verify():
    old, metadata, installed = ORIGINAL.read_bytes(), METADATA.read_bytes(), INSTALLED.read_bytes()
    assert hashlib.sha256(old).hexdigest() == OLD_SHA
    assert hashlib.sha256(metadata).hexdigest() == MD_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    pe, ip, md = PE(old), PE(installed), Metadata(metadata)
    _, table = pe.module('BugsnagUnity.Windows.dll', 240)
    rows = {}
    for key, (index, name, token, start, end, path) in METHODS.items():
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[0]), md.string(typ[1]), md.string(method[0]), method[6]) == (
            'Client', 'BugsnagUnity', name, token)
        assert struct.unpack_from('<Q', old, pe.offset(table + ((token & 0xffffff)-1)*8, 8))[0] == pe.base + start
        assert pe.function_ends[pe.base+start] == pe.base+end
        raw = path.read_bytes()
        raw = b''.join(line for line in raw.splitlines(keepends=True)
                       if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                       start <= int(match[1], 16)-pe.base < end)
        try:
            rows[key] = parse_assembly(raw, pe, old, start, end)
        except ValueError as error:
            raise ValueError(f'{key}: {error}') from error
        old_at, new_at = pe.offset(pe.base+start, end-start), ip.offset(ip.base+start, end-start)
        if key == 'web-complete':
            assert old[old_at:old_at+end-start] == installed[new_at:new_at+end-start]
        if key == 'network-breadcrumb':
            assert installed[new_at] == 0xc3
            assert old[old_at+1:old_at+end-start] == installed[new_at+1:new_at+end-start]
    def call(row, site, target):
        code = row[site]['code']
        assert len(code) == 5 and code[0] == 0xe8
        assert site + 5 + struct.unpack('<i', code[1:])[0] == target
    for site in (0x817fcc, 0x818018):
        call(rows['web-complete'], site, 0x8181f0)
    assert rows['web-complete'][0x817e99]['text'] == 'mov rdi, qword ptr [rsi + 0x88]'
    assert rows['ctor'][0x813585]['text'].startswith('call 0x18081a8a0')
    for site in (0x8135f5, 0x813646):
        assert 0x81338d < site < 0x81375c
        assert rows['ctor'][site]['code'][0] == 0xe8
    assert rows['ctor'][0x81375c]['text'] == 'mov rbx, qword ptr [rsp + 0x60]'
    assert rows['send'][0x81480a]['text'].startswith('call 0x18081c6a0')
    ctor_patch = installed[ip.offset(ip.base+0x81338d, 7):][:7]
    assert ctor_patch == bytes.fromhex('e9ca0300009090')
    assert 0x81338d + 5 + struct.unpack('<i', ctor_patch[1:5])[0] == 0x81375c
    assert installed[ip.offset(ip.base+0x813778, 5):][:5] == bytes.fromhex('c390909090')
    assert installed[ip.offset(ip.base+0x8147e0)] == 0xc3
    return dict(passed=True, web_callback='Client.OnWebRequestComplete',
                network_breadcrumb_calls=['0x817fcc', '0x818018'],
                constructor_web_setup_bypassed=True, client_send_guarded=True,
                independent_indirect_calls_unresolved=True)


if __name__ == '__main__':
    print('PASS', verify())
