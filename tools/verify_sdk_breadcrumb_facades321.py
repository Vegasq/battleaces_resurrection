"""Bind both public SDK breadcrumb facades to their exact recipe31 entry cuts."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA
from tools.verify_sdk_data_ingress322 import NEW_RVAS, CONTEXT_RVAS, MERGE_RVAS

ROOT = Path(__file__).resolve().parents[1]
METHODS = (
    (163500, 0x600006d, 3, 0x811180, 0x8112a0,
     ROOT / 'local/privacy318-web-callbacks01/breadcrumb-three.asm',
     'BugsnagUnity.Bugsnag::LeaveBreadcrumb with metadata'),
    (163501, 0x600006e, 2, 0x8112a0, 0x81135c,
     ROOT / 'local/privacy318-web-callbacks01/breadcrumb-two.asm',
     'BugsnagUnity.Bugsnag::LeaveBreadcrumb network'),
)
PREVIOUS_SHA = 'dd65e134d48a5da6c78ef69e48022027e89ad9ea6a5f300196d68f74e9bbf482'
RECIPE31_SHA = 'b54d14c93d9621b22bac8311751b24e48e0e6e1c0d61fb93563451c59326c6d8'
CURRENT_SHA = 'dd8464a34a84a3d4e66ef59390d28a894c75227f1eeab1c5f01ce1c10b808c26'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert sha(original) == OLD_SHA and sha(metadata) == MD_SHA and RECIPE_VERSION >= 31
    pe, md = PE(original), Metadata(metadata)
    _, table = pe.module('BugsnagUnity.Windows.dll', 666)
    current = patch_component('GameAssembly.dll', original)
    assert sha(current) == CURRENT_SHA
    recipe31 = bytearray(current)
    for rva in (*NEW_RVAS, *CONTEXT_RVAS):
        point = pe.offset(pe.base+rva)
        recipe31[point] = original[point]
    for rva in MERGE_RVAS:
        point = pe.offset(pe.base+rva)
        recipe31[point:point+5] = original[point:point+5]
    assert sha(recipe31) == RECIPE31_SHA
    previous = bytearray(recipe31)
    rows = {}
    counts = {}
    for index, token, argc, start, end, path, label in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
                method[6], method[2], method[-1]) == (
                'BugsnagUnity', 'Bugsnag', 'LeaveBreadcrumb', token, 59011, argc)
        assert struct.unpack_from('<Q', original, pe.offset(table + ((token & 0xffffff)-1)*8, 8))[0] == pe.base + start
        assert pe.function_ends[pe.base+start] == pe.base+end
        selected = b''.join(line for line in path.read_bytes().splitlines(keepends=True)
                            if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                            start <= int(match[1], 16)-pe.base < end)
        rows[start] = parse_assembly(selected, pe, original, start, end)
        patches = [patch for patch in COMPONENTS['GameAssembly.dll'].patches if patch.label == label]
        assert len(patches) == 1
        patch = patches[0]
        offset = pe.offset(pe.base+start)
        assert (patch.rva, patch.offset, patch.replacement) == (start, offset, b'\xc3')
        assert original[offset:offset+len(patch.guard)] == patch.guard
        assert current[offset:offset+end-start] == b'\xc3' + original[offset+1:offset+end-start]
        previous[offset] = original[offset]
        counts[label] = len(rows[start])
    assert rows[0x811180][0x811221]['text'] == 'mov rcx, qword ptr [rax + 0xb8]'
    assert rows[0x811180][0x811280]['text'].startswith('call 0x180018020')
    assert rows[0x8112a0][0x811333]['text'] == 'movups xmm0, xmmword ptr [rbx]'
    call = rows[0x8112a0][0x811346]['code']
    assert len(call) == 5 and call[0] == 0xe8
    assert 0x811346 + 5 + struct.unpack('<i', call[1:])[0] == 0x8181f0
    assert sha(previous) == PREVIOUS_SHA
    return dict(passed=True, recipe=RECIPE_VERSION, decoded_instructions=counts,
                previous_recipe_sha256=PREVIOUS_SHA, recipe31_sha256=RECIPE31_SHA,
                current_recipe_sha256=CURRENT_SHA,
                network_collector_call='0x811346 -> 0x8181f0')


if __name__ == '__main__':
    print('PASS', verify())
