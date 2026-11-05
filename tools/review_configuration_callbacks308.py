"""Bind original Bugsnag Configuration callback-list lifecycle to recipe28.

The ignored LLVM disassemblies are checked byte-for-byte against the pinned
original. This is a named-method review, not a whole-program writer proof.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA


ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / 'local/privacy308-config-callbacks01'
METHODS = {
    'ctor': (163600, '.ctor', 0x60000d1, 0x819760, 0x81a7a9),
    'get-send-error': (163619, 'GetOnSendErrorCallbacks', 0x60000e4, 0x81b4a0, 0x81b6a2),
    'remove-send-error': (163620, 'RemoveOnSendError', 0x60000e5, 0x81b6b0, 0x81b84e),
    'clone': (163632, 'Clone', 0x60000f1, 0x81bfa0, 0x81c1bb),
}
ANCHORS = {
    'ctor': {0x81a4e0: 'lea r8, [rdi + 0x168]',
             0x81a4e7: 'mov qword ptr [r8], rbx'},
    'get-send-error': {0x81b52d: 'mov rsi, qword ptr [rbx + 0x168]',
                       0x81b57f: 'mov rdx, rsi'},
    'remove-send-error': {0x81b73c: 'mov rcx, qword ptr [rbx + 0x168]',
                          0x81b753: 'mov rdx, rdi'},
    'clone': {0x81bfd7: 'call 0x1806017f0 <GlobalizationNative_GetTimeZoneDisplayName+0x1ea0>',
              0x81c04a: 'lea r8, [rdi + 0x58]',
              0x81c13e: 'lea r8, [rdi + 0xe8]'},
}


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(original).hexdigest() == OLD_SHA
    assert hashlib.sha256(metadata).hexdigest() == MD_SHA
    assert RECIPE_VERSION >= 28
    pe, md = PE(original), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 239)
    assert count >= 239
    rows_by_name = {}
    for key, (index, name, token, start, end) in METHODS.items():
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(method[0]), md.string(typ[0]), md.string(typ[1]), method[6]) == (
            name, 'Configuration', 'BugsnagUnity', token)
        assert pe.function_ends[pe.base + start] == pe.base + end
        assert struct.unpack_from('<Q', original, pe.offset(table + ((token & 0xffffff) - 1) * 8, 8))[0] == pe.base + start
        rows = parse_assembly((ASM / (key + '.asm')).read_bytes(), pe, original, start, end)
        for rva, expected in ANCHORS[key].items():
            assert rows[rva]['text'] == expected, (key, hex(rva), rows[rva]['text'])
        rows_by_name[key] = rows
    # The named getter/remover/clone contain no direct store into this field.
    for key in ('get-send-error', 'remove-send-error', 'clone'):
        assert not any('0x168]' in row['text'] and row['text'].startswith(('mov qword ptr [', 'lea '))
                       for row in rows_by_name[key].values())
    assert not any('0x168]' in row['text'] for row in rows_by_name['clone'].values())
    # The original helper called by Clone copies source object data to a new object.
    # Bind the direct call and the visible memcpy argument setup, without naming
    # every runtime branch or claiming a deep copy.
    helper = 0x6017f0
    assert rows_by_name['clone'][0x81bfd7]['code'][0] == 0xe8
    assert 0x81bfd7 + 5 + struct.unpack('<i', rows_by_name['clone'][0x81bfd7]['code'][1:])[0] == helper
    assert original[pe.offset(pe.base + 0x601841, 16):pe.offset(pe.base + 0x601841, 16) + 16] == bytes.fromhex(
        '488bcf4c8d43f0488d5610e84fa80700')
    patched = patch_component('GameAssembly.dll', original)
    assert patched[pe.offset(pe.base + 0x81b2b0)] == 0xc3
    return {'passed': True, 'recipe': RECIPE_VERSION,
            'decoded_instructions': {name: len(rows) for name, rows in rows_by_name.items()},
            'named_list_field': 'Configuration+0x168',
            'registration_entry': 'RET'}


if __name__ == '__main__':
    print('PASS', verify())
