"""Bind original SDK OnError/OnSession callback lists and direct call sites."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from client_patch.patcher.telemetry import RECIPE_VERSION
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA


ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / 'local/privacy309-onerror01'
INSTALLED = ROOT / 'local/privacy301-runtime01/game/GameAssembly.dll'
INSTALLED_SHA = '30600add160a5bd1c23f4f3e37749080596985582ce577e22308cbfe9c64713e'
METHODS = {
    'add-on-error': (163615, 'Configuration', 'AddOnError', 0x60000e0, 0x81ad10, 0x81aef3, 0x158),
    'add-on-session': (163621, 'Configuration', 'AddOnSession', 0x60000e6, 0x81b850, 0x81ba33, 0x178),
    'client-session-facade': (163569, 'Client', 'AddOnSession', 0x60000b2, 0x8176b0, 0x817728, None),
}


def direct_calls(pe, data, target):
    result = []
    for base, size, file_offset in pe.sections:
        for offset in range(file_offset, min(file_offset + size, len(data)) - 4):
            if data[offset] != 0xe8:
                continue
            address = base + offset - file_offset
            if address + 5 + struct.unpack_from('<i', data, offset + 1)[0] == pe.base + target:
                result.append(address - pe.base)
    return tuple(result)


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    installed = INSTALLED.read_bytes()
    assert hashlib.sha256(original).hexdigest() == OLD_SHA
    assert hashlib.sha256(metadata).hexdigest() == MD_SHA
    assert hashlib.sha256(installed).hexdigest() == INSTALLED_SHA
    assert RECIPE_VERSION >= 28
    pe, ip, md = PE(original), PE(installed), Metadata(metadata)
    _, table = pe.module('BugsnagUnity.Windows.dll', 227)
    lengths = {}
    for path, (index, typ_name, method_name, token, start, end, field) in METHODS.items():
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[0]), md.string(typ[1]), md.string(method[0]), method[6],
                method[2], method[-1]) == (typ_name, 'BugsnagUnity', method_name, token, 59011, 1)
        assert pe.function_ends[pe.base + start] == pe.base + end
        assert struct.unpack_from('<Q', original, pe.offset(table + ((token & 0xffffff) - 1)*8, 8))[0] == pe.base + start
        rows = parse_assembly((ASM / (path + '.asm')).read_bytes(), pe, original, start, end)
        old_offset, new_offset = pe.offset(pe.base + start, end-start), ip.offset(ip.base + start, end-start)
        assert original[old_offset:old_offset+end-start] == installed[new_offset:new_offset+end-start]
        if field is not None:
            assert any(f'[rbx + {field:#x}]' in row['text'] for row in rows.values())
            assert not any('[rbx + 0x168]' in row['text'] for row in rows.values())
        lengths[path] = len(rows)
    assert direct_calls(pe, original, 0x81ad10) == ()
    assert direct_calls(pe, original, 0x81b850) == (0x8176f9,)
    assert direct_calls(pe, original, 0x8176b0) == ()
    assert original[pe.offset(pe.base + 0x81a410, 7):pe.offset(pe.base + 0x81a410, 7)+7] == bytes.fromhex('4c8d8758010000')
    assert original[pe.offset(pe.base + 0x81a5b0, 7):pe.offset(pe.base + 0x81a5b0, 7)+7] == bytes.fromhex('4c8d8778010000')
    return {'passed': True, 'recipe': RECIPE_VERSION, 'decoded_instructions': lengths,
            'direct_calls': {'AddOnError': [], 'AddOnSession': ['0x8176f9'], 'facade': []},
            'on_send_error_list_is_distinct': True}


if __name__ == '__main__':
    print('PASS', verify())
