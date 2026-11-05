"""Bind recipe35 Configuration/NativeClient data-entry cuts to pinned originals."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA

ASM = Path('local/privacy345-config-ingress01')
METHODS = (
    (163624, 'Configuration', 'AddMetadata', 3, 0x81bdf0, 0x81be15, 'BugsnagUnity.Configuration::AddMetadata with section'),
    (163625, 'Configuration', 'AddMetadata', 2, 0x81be20, 0x81be3f, 'BugsnagUnity.Configuration::AddMetadata'),
    (163631, 'Configuration', 'SetUser', 3, 0x81bec0, 0x81bf9c, 'BugsnagUnity.Configuration::SetUser'),
    (163633, 'Configuration', 'AddFeatureFlag', 2, 0x81c1c0, 0x81c1df, 'BugsnagUnity.Configuration::AddFeatureFlag'),
    (163634, 'Configuration', 'AddFeatureFlags', 1, 0x81c1e0, 0x81c34d, 'BugsnagUnity.Configuration::AddFeatureFlags'),
    (164044, 'NativeClient', 'AddNativeMetadata', 2, 0x8359a0, 0x8359bf, 'BugsnagUnity.NativeClient::AddNativeMetadata'),
)
PREVIOUS_SHA = 'dd8464a34a84a3d4e66ef59390d28a894c75227f1eeab1c5f01ce1c10b808c26'
CURRENT_SHA = 'eb016205270a729cf36300e7d8bd64fb5115b26afd8c51d9291e3f377c7a8b33'
LATEST_SHA = 'ba894975597777edd2e7544ea2df9aafb59101800885734e7decb0b66660ff92'
NEWEST_SHA = '89b6da75d36009ec3824859c6583cf29650e7db6d23dd804ac6100fa30ef30fd'
RECIPE38_SHA = 'cd71b66d3249985e820fc75c3597034c3e2bcfdfa01da96c8844c19e0df8db08'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert (sha(original), sha(metadata)) == (OLD_SHA, MD_SHA) and RECIPE_VERSION in (35, 36, 37, 38)
    pe, md = PE(original), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 666)
    current = patch_component('GameAssembly.dll', original)
    actual_sha = sha(current)
    if RECIPE_VERSION == 38:
        assert sha(current) == RECIPE38_SHA
        normalized = bytearray(current)
        session = pe.offset(pe.base+0x826b40)
        assert normalized[session] == 0xc3
        normalized[session] = original[session]
        current = bytes(normalized)
    if RECIPE_VERSION >= 37:
        assert sha(current) == NEWEST_SHA
        normalized = bytearray(current)
        cache = pe.offset(pe.base+0x81428e)
        assert normalized[cache:cache+7] == bytes.fromhex('e9260000009090')
        normalized[cache:cache+7] = original[cache:cache+7]
        current = bytes(normalized)
    if RECIPE_VERSION >= 36:
        assert sha(current) == LATEST_SHA
        normalized = bytearray(current)
        scene = pe.offset(pe.base+0x818cf0)
        assert normalized[scene] == 0xc3
        normalized[scene] = original[scene]
        patched = bytes(normalized)
    else:
        patched = current
    assert sha(patched) == CURRENT_SHA
    previous = bytearray(patched)
    rows, decoded = {}, 0
    for index, type_name, name, argc, start, end, label in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        token = method[6]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]), method[2], method[-1]) == (
            'BugsnagUnity', type_name, name, 59011, argc)
        assert 0 <= (token & 0xffffff)-1 < count
        assert struct.unpack_from('<Q', original, pe.offset(table + ((token & 0xffffff)-1)*8, 8))[0] == pe.base+start
        assert pe.function_ends[pe.base+start] == pe.base+end
        raw = b''.join(line for line in (ASM/f'{start:x}.asm').read_bytes().splitlines(keepends=True)
                       if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                       start <= int(match[1], 16)-pe.base < end)
        rows[start] = parse_assembly(raw, pe, original, start, end)
        decoded += len(rows[start])
        matches = [patch for patch in COMPONENTS['GameAssembly.dll'].patches if patch.label == label]
        assert len(matches) == 1
        patch = matches[0]
        offset = pe.offset(pe.base+start)
        assert (patch.rva, patch.offset, patch.replacement) == (start, offset, b'\xc3')
        assert original[offset:offset+len(patch.guard)] == patch.guard
        assert patched[offset:offset+end-start] == b'\xc3' + original[offset+1:offset+end-start]
        previous[offset] = original[offset]
    assert sha(previous) == PREVIOUS_SHA
    # Distinct Configuration/NativeClient stores exist independently of facade/Client setters.
    assert rows[0x81bdf0][0x81bdf4]['text'] == 'mov rcx, qword ptr [rcx + 0x60]'
    assert rows[0x81be20][0x81be24]['text'] == 'mov rcx, qword ptr [rcx + 0x60]'
    assert rows[0x81bec0][0x81bf3b]['text'] == 'mov qword ptr [r8], rbx'
    assert rows[0x81c1c0][0x81c1c4]['text'] == 'mov rcx, qword ptr [rcx + 0x68]'
    assert rows[0x81c1e0][0x81c210]['text'] == 'mov eax, dword ptr [rbp + 0x18]'
    assert rows[0x81c1e0][0x81c2f6]['text'] == 'mov rcx, qword ptr [r14 + 0x68]'
    assert rows[0x8359a0][0x8359a4]['text'] == 'mov rcx, qword ptr [rcx + 0x28]'
    return dict(passed=True, recipe=RECIPE_VERSION, methods=len(METHODS),
                decoded_instructions=decoded, previous_sha256=PREVIOUS_SHA,
                recipe35_sha256=CURRENT_SHA, current_sha256=actual_sha)


if __name__ == '__main__':
    print('PASS', verify())
