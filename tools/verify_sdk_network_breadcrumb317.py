"""Verify the SDK network-breadcrumb collector's exact recipe29 entry cut."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA
from tools.verify_sdk_data_ingress322 import NEW_RVAS, CONTEXT_RVAS, MERGE_RVAS

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / 'local/privacy315-web-breadcrumb01/leave.asm'
START, END = 0x8181f0, 0x81884e
PREVIOUS_SHA = '2568beb2ed9deeda4e15941483889da53870ecbf05491d3c78455e4376b34739'
RECIPE29_SHA = '4627f1f224e5e193c0acc1205af2313c23cdc73d63a93739167726f41e8c48c3'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert sha(original) == OLD_SHA and sha(metadata) == MD_SHA
    assert RECIPE_VERSION >= 29
    pe, md = PE(original), Metadata(metadata)
    method = md.methods[163587]
    typ = md.types[method[1]]
    assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
            method[6], method[2], method[-1]) == (
            'BugsnagUnity', 'Client', 'LeaveNetworkBreadcrumb', 0x60000c4, 59011, 2)
    _, table = pe.module('BugsnagUnity.Windows.dll', 240)
    assert struct.unpack_from('<Q', original, pe.offset(table + 195*8, 8))[0] == pe.base + START
    assert pe.function_ends[pe.base + START] == pe.base + END
    rows = parse_assembly(ASM.read_bytes(), pe, original, START, END)
    assert rows[START]['text'] == 'push rbx'
    patches = [p for p in COMPONENTS['GameAssembly.dll'].patches
               if p.label == 'BugsnagUnity.Client::LeaveNetworkBreadcrumb']
    assert len(patches) == 1
    patch = patches[0]
    offset = pe.offset(pe.base + START)
    assert (patch.rva, patch.offset, patch.replacement) == (START, offset, b'\xc3')
    assert original[offset:offset+len(patch.guard)] == patch.guard
    current = patch_component('GameAssembly.dll', original)
    assert current[offset] == 0xc3
    recipe29 = bytearray(current)
    for rva in (0x835c60, 0x835d00, 0x818040, 0x811180, 0x8112a0, *NEW_RVAS, *CONTEXT_RVAS):
        point = pe.offset(pe.base+rva)
        recipe29[point] = original[point]
    for rva in MERGE_RVAS:
        point = pe.offset(pe.base+rva)
        recipe29[point:point+5] = original[point:point+5]
    assert sha(recipe29) == RECIPE29_SHA
    previous = bytearray(recipe29)
    previous[offset] = original[offset]
    assert sha(previous) == PREVIOUS_SHA
    assert current[offset+1:offset+END-START] == original[offset+1:offset+END-START]
    return dict(passed=True, recipe=RECIPE_VERSION, method='Client.LeaveNetworkBreadcrumb',
                return_type='void', decoded_instructions=len(rows),
                previous_recipe_output_sha256=PREVIOUS_SHA,
                recipe29_output_sha256=RECIPE29_SHA,
                current_output_sha256=sha(current))


if __name__ == '__main__':
    print('PASS', verify())
