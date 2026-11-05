"""Verify the ten SDK user/metadata/feature-flag entry guards in recipe32."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA

ASM = Path('local/privacy322-data-ingress01')
METHODS = (
    (163503, 'Bugsnag', 'SetUser', 3, 0x811450, 0x811566, 'BugsnagUnity.Bugsnag::SetUser'),
    (163516, 'Bugsnag', 'AddMetadata', 3, 0x811c60, 0x811cf6, 'BugsnagUnity.Bugsnag::AddMetadata with section'),
    (163517, 'Bugsnag', 'AddMetadata', 2, 0x811d00, 0x811d90, 'BugsnagUnity.Bugsnag::AddMetadata'),
    (163522, 'Bugsnag', 'AddFeatureFlag', 2, 0x811fb0, 0x81203d, 'BugsnagUnity.Bugsnag::AddFeatureFlag'),
    (163523, 'Bugsnag', 'AddFeatureFlags', 1, 0x812040, 0x812123, 'BugsnagUnity.Bugsnag::AddFeatureFlags'),
    (163571, 'Client', 'AddMetadata', 3, 0x817760, 0x817785, 'BugsnagUnity.Client::AddMetadata with section'),
    (163572, 'Client', 'AddMetadata', 2, 0x817790, 0x8177af, 'BugsnagUnity.Client::AddMetadata'),
    (163578, 'Client', 'SetUser', 3, 0x817830, 0x817938, 'BugsnagUnity.Client::SetUser'),
    (163579, 'Client', 'AddFeatureFlag', 2, 0x817940, 0x8179c4, 'BugsnagUnity.Client::AddFeatureFlag'),
    (163580, 'Client', 'AddFeatureFlags', 1, 0x8179d0, 0x817b7f, 'BugsnagUnity.Client::AddFeatureFlags'),
)
NEW_RVAS = tuple(row[4] for row in METHODS)
CONTEXT_RVAS = (0x8118e0, 0x817510)
MERGE_RVAS = (0x812ff0, 0x814064)
PREVIOUS_SHA = 'b54d14c93d9621b22bac8311751b24e48e0e6e1c0d61fb93563451c59326c6d8'
CURRENT_SHA = '4d622855c06fea1dd47eb10b57a73fe1731e85ea2b4dc8eb276d441756918dfd'
LATEST_SHA = 'dd8464a34a84a3d4e66ef59390d28a894c75227f1eeab1c5f01ce1c10b808c26'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert sha(original) == OLD_SHA and sha(metadata) == MD_SHA and RECIPE_VERSION >= 32
    pe, md = PE(original), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 666)
    patched = patch_component('GameAssembly.dll', original)
    assert sha(patched) == LATEST_SHA
    recipe32 = bytearray(patched)
    for rva in CONTEXT_RVAS:
        offset = pe.offset(pe.base+rva)
        recipe32[offset] = original[offset]
    for rva in MERGE_RVAS:
        offset = pe.offset(pe.base+rva)
        recipe32[offset:offset+5] = original[offset:offset+5]
    assert sha(recipe32) == CURRENT_SHA
    previous = bytearray(recipe32)
    rows = {}
    instructions = {}
    for index, typ_name, method_name, argc, start, end, label in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        token = method[6]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
                method[2], method[-1]) == (
                'BugsnagUnity', typ_name, method_name, 59011, argc)
        assert 0 <= (token & 0xffffff)-1 < count
        assert struct.unpack_from('<Q', original, pe.offset(table+((token & 0xffffff)-1)*8, 8))[0] == pe.base+start
        assert pe.function_ends[pe.base+start] == pe.base+end
        raw = b''.join(line for line in (ASM/f'{start:x}.asm').read_bytes().splitlines(keepends=True)
                       if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                       start <= int(match[1], 16)-pe.base < end)
        rows[start] = parse_assembly(raw, pe, original, start, end)
        matches = [patch for patch in COMPONENTS['GameAssembly.dll'].patches if patch.label == label]
        assert len(matches) == 1
        patch = matches[0]
        offset = pe.offset(pe.base+start)
        assert (patch.rva, patch.offset, patch.replacement) == (start, offset, b'\xc3')
        assert original[offset:offset+len(patch.guard)] == patch.guard
        assert recipe32[offset:offset+end-start] == b'\xc3'+original[offset+1:offset+end-start]
        previous[offset] = original[offset]
        instructions[label] = len(rows[start])
    assert sha(previous) == PREVIOUS_SHA
    # The direct Client entries can process caller data without a static
    # Bugsnag facade; the public entries can reach them independently.
    assert rows[0x817760][0x817764]['text'] == 'mov rcx, qword ptr [rcx + 0x20]'
    assert rows[0x817790][0x817794]['text'] == 'mov rcx, qword ptr [rcx + 0x20]'
    assert rows[0x817830][0x8178b8]['text'] == 'mov qword ptr [rdi + 0x18], rbx'
    assert rows[0x8179d0][0x817a00]['text'] == 'mov eax, dword ptr [rbp + 0x18]'
    for start, site in ((0x811450,0x8114b6),(0x811c60,0x811cc1),
                        (0x811d00,0x811d59),(0x811fb0,0x812009),
                        (0x812040,0x812096)):
        assert rows[start][site]['text'].startswith('call 0x180810c40')
    return dict(passed=True, recipe=RECIPE_VERSION, methods=len(METHODS),
                decoded_instructions=instructions, previous_recipe_sha256=PREVIOUS_SHA,
                recipe32_sha256=CURRENT_SHA, current_recipe_sha256=LATEST_SHA)


if __name__ == '__main__':
    print('PASS', verify())
