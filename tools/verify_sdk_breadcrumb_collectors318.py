"""Bind the concrete SDK breadcrumb overloads and web-send entry cuts."""
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
    (164056, 'Breadcrumbs', 'Leave', 0x6000299, 3, 0x835c60, 0x835cf8,
     ROOT / 'local/privacy315-web-breadcrumb01/leave-simple.asm',
     'BugsnagUnity.Breadcrumbs::Leave with metadata'),
    (164057, 'Breadcrumbs', 'Leave', 0x600029a, 1, 0x835d00, 0x8361b9,
     ROOT / 'local/privacy315-web-breadcrumb01/leave-full.asm',
     'BugsnagUnity.Breadcrumbs::Leave'),
    (163585, 'Client', 'OnWebRequestSend', 0x60000c2, 1, 0x818040, 0x818145,
     ROOT / 'local/privacy318-web-callbacks01/send.asm',
     'BugsnagUnity.Client::OnWebRequestSend'),
)
PREVIOUS_SHA = '4627f1f224e5e193c0acc1205af2313c23cdc73d63a93739167726f41e8c48c3'
RECIPE30_SHA = 'dd65e134d48a5da6c78ef69e48022027e89ad9ea6a5f300196d68f74e9bbf482'
CURRENT_SHA = 'dd8464a34a84a3d4e66ef59390d28a894c75227f1eeab1c5f01ce1c10b808c26'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert sha(original) == OLD_SHA and sha(metadata) == MD_SHA and RECIPE_VERSION >= 30
    pe, md = PE(original), Metadata(metadata)
    _, table = pe.module('BugsnagUnity.Windows.dll', 666)
    patched = patch_component('GameAssembly.dll', original)
    assert sha(patched) == CURRENT_SHA
    recipe30 = bytearray(patched)
    if RECIPE_VERSION >= 31:
        for rva in (0x811180, 0x8112a0, *NEW_RVAS, *CONTEXT_RVAS):
            point = pe.offset(pe.base+rva)
            recipe30[point] = original[point]
        for rva in MERGE_RVAS:
            point = pe.offset(pe.base+rva)
            recipe30[point:point+5] = original[point:point+5]
    assert sha(recipe30) == RECIPE30_SHA
    previous = bytearray(recipe30)
    rows = {}
    result = {}
    for index, typ_name, method_name, token, arguments, start, end, path, label in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
                method[6], method[2], method[-1]) == (
                'BugsnagUnity', typ_name, method_name, token, 59011, arguments)
        assert struct.unpack_from('<Q', original, pe.offset(table + ((token & 0xffffff)-1)*8, 8))[0] == pe.base + start
        assert pe.function_ends[pe.base+start] == pe.base+end
        raw = b''.join(line for line in path.read_bytes().splitlines(keepends=True)
                       if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                       start <= int(match[1], 16)-pe.base < end)
        rows[label] = parse_assembly(raw, pe, original, start, end)
        matches = [p for p in COMPONENTS['GameAssembly.dll'].patches if p.label == label]
        assert len(matches) == 1
        patch = matches[0]
        offset = pe.offset(pe.base + start)
        assert (patch.rva, patch.offset, patch.replacement) == (start, offset, b'\xc3')
        assert original[offset:offset+len(patch.guard)] == patch.guard
        assert patched[offset] == 0xc3
        assert patched[offset+1:offset+end-start] == original[offset+1:offset+end-start]
        previous[offset] = original[offset]
        result[label] = len(rows[label])
    # The three-argument concrete overload forwards to the one-argument
    # overload, so both entries must be cut before their own input processing.
    forward = rows['BugsnagUnity.Breadcrumbs::Leave with metadata'][0x835cf3]['code']
    assert forward[0] == 0xe9 and 0x835cf3 + 5 + struct.unpack('<i', forward[1:])[0] == 0x835d00
    # The SDK web-send callback uses Client+0x88 and invokes its separate
    # request-handling helper before completion/abort. No target-name claim.
    web = rows['BugsnagUnity.Client::OnWebRequestSend']
    assert web[0x818089]['text'] == 'mov rbx, qword ptr [rbx + 0x88]'
    assert web[0x81812f]['code'][0] == 0xe8
    assert sha(previous) == PREVIOUS_SHA
    return dict(passed=True, recipe=RECIPE_VERSION, decoded_instructions=result,
                previous_recipe_sha256=PREVIOUS_SHA, recipe30_sha256=RECIPE30_SHA,
                current_recipe_sha256=CURRENT_SHA,
                forward_target='0x835d00', web_send_precompletion_call='0x81812f')


if __name__ == '__main__':
    print('PASS', verify())
