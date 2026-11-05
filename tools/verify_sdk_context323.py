"""Bind both SDK context setters to original code and recipe33 entry cuts."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA
from tools.verify_sdk_data_ingress322 import CONTEXT_RVAS, MERGE_RVAS, CURRENT_SHA, LATEST_SHA

ROOT = Path(__file__).resolve().parents[1]
METHODS = (
    (163509, 'Bugsnag', 'set_Context', 0x8118e0, 0x81195e,
     ROOT/'local/privacy323-sdk-context01/public.asm', 'BugsnagUnity.Bugsnag::set_Context'),
    (163564, 'Client', 'SetContext', 0x817510, 0x8175ce,
     ROOT/'local/privacy323-sdk-context01/client.asm', 'BugsnagUnity.Client::SetContext'),
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert sha(original) == OLD_SHA and sha(metadata) == MD_SHA and RECIPE_VERSION >= 33
    pe, md = PE(original), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 666)
    current = patch_component('GameAssembly.dll', original)
    assert sha(current) == LATEST_SHA
    recipe33 = bytearray(current)
    for rva in MERGE_RVAS:
        offset = pe.offset(pe.base+rva)
        recipe33[offset:offset+5] = original[offset:offset+5]
    assert sha(recipe33) == 'e02bd2bbd2cfe104637816df7da3dfa481031503602a92035adb1ab7552dd5cd'
    previous = bytearray(recipe33)
    counts = {}
    rows = {}
    for index, typ_name, method_name, start, end, path, label in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
                method[2], method[-1]) == ('BugsnagUnity', typ_name, method_name, 59011, 1)
        token = method[6] & 0xffffff
        assert 1 <= token <= count
        assert struct.unpack_from('<Q', original, pe.offset(table+(token-1)*8, 8))[0] == pe.base+start
        assert pe.function_ends[pe.base+start] == pe.base+end
        raw = b''.join(line for line in path.read_bytes().splitlines(keepends=True)
                       if (match := re.match(rb'^([0-9a-f]+): ', line)) and
                       start <= int(match[1], 16)-pe.base < end)
        rows[start] = parse_assembly(raw, pe, original, start, end)
        matches = [p for p in COMPONENTS['GameAssembly.dll'].patches if p.label == label]
        assert len(matches) == 1
        patch = matches[0]
        offset = pe.offset(pe.base+start)
        assert (patch.rva, patch.offset, patch.replacement) == (start, offset, b'\xc3')
        assert original[offset:offset+len(patch.guard)] == patch.guard
        assert recipe33[offset:offset+end-start] == b'\xc3'+original[offset+1:offset+end-start]
        previous[offset] = original[offset]
        counts[label] = len(rows[start])
    assert tuple(row[3] for row in METHODS) == CONTEXT_RVAS
    assert sha(previous) == CURRENT_SHA
    assert rows[0x8118e0][0x811937]['text'].startswith('test rax, rax')
    assert rows[0x817510][0x817546]['text'].startswith('call 0x1808122e0')
    assert rows[0x817510][0x81755e]['text'] == 'mov qword ptr [rdx], rdi'
    assert rows[0x817510][0x8175c3]['text'].startswith('jmp 0x180013e00')
    return dict(passed=True, recipe=RECIPE_VERSION, decoded_instructions=counts,
                recipe32_sha256=CURRENT_SHA, recipe33_sha256=sha(recipe33),
                current_recipe_sha256=LATEST_SHA)


if __name__ == '__main__':
    print('PASS', verify())
