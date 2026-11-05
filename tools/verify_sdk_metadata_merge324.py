"""Verify recipe34 cuts the SDK configuration-to-report metadata merges."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA
from tools.verify_sdk_data_ingress322 import MERGE_RVAS, LATEST_SHA

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT/'local/privacy324-metadata-merge01'
RECIPE33_SHA = 'e02bd2bbd2cfe104637816df7da3dfa481031503602a92035adb1ab7552dd5cd'
METHODS = (
    (163535, 'Client', '.ctor', 0x6000090, 0x812690, 0x81379a,
     ROOT/'local/privacy138-sdk-lifetime01/game-812690.asm'),
    (163543, 'Client', 'InitMetadata', 0x6000098, 0x813f40, 0x814089,
     ASM/'init-metadata.asm'),
    (164485, 'Metadata', 'MergeMetadata', 0x6000446, 0x8494f0, 0x84973b,
     ASM/'merge-metadata.asm'),
)
CALLS = (0x812ff0, 0x814064, 0x8161b2, 0x816289, 0x844701)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def direct_calls(pe, original, target):
    found = []
    for base, size, file_offset in pe.sections:
        for offset in range(file_offset, min(file_offset+size, len(original))-4):
            if original[offset] != 0xe8:
                continue
            va = base+offset-file_offset
            if va+5+struct.unpack_from('<i', original, offset+1)[0] == pe.base+target:
                found.append(va-pe.base)
    return tuple(found)


def verify():
    original, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert sha(original) == OLD_SHA and sha(metadata) == MD_SHA and RECIPE_VERSION == 34
    pe, md = PE(original), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 1224)
    rows, counts = {}, {}
    for index, typ_name, method_name, token, start, end, path in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
                method[6], method[2]) == (
                'BugsnagUnity' if typ_name == 'Client' else 'BugsnagUnity.Payload',
                typ_name, method_name, token, 59011)
        assert 1 <= (token & 0xffffff) <= count
        assert struct.unpack_from('<Q', original, pe.offset(table+((token & 0xffffff)-1)*8, 8))[0] == pe.base+start
        assert pe.function_ends[pe.base+start] == pe.base+end
        rows[start] = parse_assembly(path.read_bytes(), pe, original, start, end)
        counts[method_name] = len(rows[start])
    assert tuple(MERGE_RVAS) == CALLS[:2]
    assert direct_calls(pe, original, 0x8494f0) == CALLS
    assert direct_calls(pe, original, 0x813f40) == ()
    assert rows[0x812690][0x812f5f]['text'] == 'mov qword ptr [r14 + 0x20], rdi'
    assert rows[0x812690][0x812fc2]['text'].startswith('call 0x1808122e0')
    assert rows[0x812690][0x812fd0]['text'] == 'mov rdx, qword ptr [rax + 0x60]'
    assert rows[0x812690][0x812fe6]['text'] == 'mov rdx, qword ptr [rdx + 0x10]'
    assert rows[0x812690][0x812ffb]['text'].startswith('call 0x18080fb20')
    assert rows[0x813f40][0x813fef]['text'] == 'mov qword ptr [rdi + 0x20], rsi'
    assert rows[0x813f40][0x814042]['text'].startswith('call 0x1808122e0')
    assert rows[0x813f40][0x81405a]['text'] == 'mov rdx, qword ptr [rdx + 0x10]'
    assert rows[0x813f40][0x81407e]['text'].startswith('jmp 0x18080fb20')
    assert rows[0x8494f0][0x8496c2]['text'].startswith('call 0x180848d30')
    patched = patch_component('GameAssembly.dll', original)
    assert sha(patched) == LATEST_SHA
    previous = bytearray(patched)
    for start, label in ((0x812ff0, 'Bugsnag Client ctor omit configured metadata merge'),
                         (0x814064, 'Bugsnag Client InitMetadata omit configured metadata merge')):
        patch = [p for p in COMPONENTS['GameAssembly.dll'].patches if p.label == label]
        assert len(patch) == 1
        patch = patch[0]
        offset = pe.offset(pe.base+start)
        assert (patch.rva, patch.offset, patch.replacement) == (start, offset, b'\x90'*5)
        assert original[offset:offset+len(patch.guard)] == patch.guard
        assert patched[offset:offset+len(patch.guard)] == b'\x90'*5+original[offset+5:offset+len(patch.guard)]
        previous[offset:offset+5] = original[offset:offset+5]
    assert sha(previous) == RECIPE33_SHA
    return dict(passed=True, recipe=RECIPE_VERSION, methods=counts,
                direct_merge_calls=[hex(x) for x in CALLS],
                no_direct_init_metadata_calls=True,
                recipe33_sha256=RECIPE33_SHA, recipe34_sha256=LATEST_SHA)


if __name__ == '__main__':
    print('PASS', verify())
