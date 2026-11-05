"""Bind the remaining direct metadata merge to the guarded cached-report route."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL, METADATA, OLD_SHA, MD_SHA
from tools.verify_sdk_metadata_merge324 import CALLS, direct_calls
from tools.verify_sdk_data_ingress322 import LATEST_SHA

ROOT = Path(__file__).resolve().parents[1]
INSTALLED = ROOT/'local/privacy301-runtime01/game/GameAssembly.dll'
INSTALLED_SHA = '30600add160a5bd1c23f4f3e37749080596985582ce577e22308cbfe9c64713e'
ASM = ROOT/'local'
METHODS = (
    (163559, 'BugsnagUnity', 'Client', 'NotifyOnMainThread', 0x60000a8,
     0x815ba0, 0x816cca, ROOT/'local/errors165-independent01/game-815ba0.asm'),
    (163677, '', '<ProcessCachedItems>d__37', 'MoveNext', 0x600011e,
     0x8204c0, 0x820c69, ASM/'privacy325-cached-merge-movenext.asm'),
    (164327, 'BugsnagUnity.Payload', 'Event', '.ctor', 0x60003a8,
     0x843e80, 0x845c9c, ASM/'privacy325-cached-merge-event.asm'),
    (164513, 'BugsnagUnity.Payload', 'Report', '.ctor', 0x6000462,
     0x84b090, 0x84b51c, ASM/'privacy325-cached-merge-report.asm'),
)
EDGES = ((0x8209e1, 0x84b090), (0x84b4a9, 0x843e80), (0x844701, 0x8494f0))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def body(pe, raw, start, end):
    return raw[pe.offset(pe.base+start, end-start):][:end-start]


def verify():
    original, metadata, installed = ORIGINAL.read_bytes(), METADATA.read_bytes(), INSTALLED.read_bytes()
    assert (sha(original), sha(metadata), sha(installed), RECIPE_VERSION) == (
        OLD_SHA, MD_SHA, INSTALLED_SHA, 34)
    pe, ip, md = PE(original), PE(installed), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 1224)
    rows, counts = {}, {}
    for index, namespace, typ_name, method_name, token, start, end, path in METHODS:
        method = md.methods[index]
        typ = md.types[method[1]]
        assert (md.string(typ[1]), md.string(typ[0]), md.string(method[0]),
                method[6], method[2]) == (namespace, typ_name, method_name, token,
                                          38515 if method_name == 'MoveNext' else 59011)
        assert 1 <= token & 0xffffff <= count
        assert struct.unpack_from('<Q', original, pe.offset(table+((token & 0xffffff)-1)*8, 8))[0] == pe.base+start
        assert pe.function_ends[pe.base+start] == pe.base+end
        rows[start] = parse_assembly(path.read_bytes(), pe, original, start, end)
        counts[f'{typ_name}::{method_name}'] = len(rows[start])
    for callsite, target in EDGES:
        owner = next(start for _, _, _, _, _, start, end, _ in METHODS if start <= callsite < end)
        code = rows[owner][callsite]['code']
        assert len(code) == 5 and code[0] == 0xe8
        assert callsite+5+struct.unpack('<i', code[1:])[0] == target
    assert direct_calls(pe, original, 0x84b090) == (0x8209e1,)
    assert direct_calls(pe, original, 0x843e80) == (0x84b4a9,)
    assert direct_calls(pe, original, 0x8494f0) == CALLS
    notify = 0x815ba0
    for callsite in CALLS[2:4]:
        code = rows[notify][callsite]['code']
        assert len(code) == 5 and code[0] == 0xe8
        assert callsite+5+struct.unpack('<i', code[1:])[0] == 0x8494f0
    patches = COMPONENTS['GameAssembly.dll'].patches
    patch = [p for p in patches if p.label == '.<ProcessCachedItems>d__37::MoveNext']
    assert len(patch) == 1
    patch = patch[0]
    start, end = 0x8204c0, 0x820c69
    assert (patch.rva, patch.offset, patch.replacement) == (start, pe.offset(pe.base+start), b'\x31\xc0\xc3')
    assert body(pe, original, start, start+len(patch.guard)) == patch.guard
    notify_patch = [p for p in patches if p.label == 'BugsnagUnity.Client::NotifyOnMainThread queued collector']
    assert len(notify_patch) == 1
    notify_patch = notify_patch[0]
    assert (notify_patch.rva, notify_patch.offset, notify_patch.replacement) == (
        notify, pe.offset(pe.base+notify), b'\xc3')
    assert body(pe, original, notify, notify+len(notify_patch.guard)) == notify_patch.guard
    source = patch_component('GameAssembly.dll', original)
    assert sha(source) == LATEST_SHA
    for image, descriptor in ((source, PE(source)), (installed, ip)):
        assert body(descriptor, image, start, start+3) == b'\x31\xc0\xc3'
        assert body(descriptor, image, start+3, end) == body(pe, original, start+3, end)
        assert body(descriptor, image, notify, notify+1) == b'\xc3'
        assert body(descriptor, image, notify+1, 0x816cca) == body(pe, original, notify+1, 0x816cca)
        for callsite in CALLS[:2]:
            assert body(descriptor, image, callsite, callsite+5) == b'\x90'*5
        for _, _, _, _, _, ctor, ctor_end, _ in METHODS[2:]:
            assert body(descriptor, image, ctor, ctor_end) == body(pe, original, ctor, ctor_end)
    return dict(passed=True, recipe=RECIPE_VERSION, instructions=counts,
                direct_edges=[f'{a:x}->{b:x}' for a, b in EDGES],
                guarded_entries=[hex(notify), hex(start)],
                direct_merge_calls=[hex(x) for x in CALLS], source_sha256=LATEST_SHA,
                installed_sha256=INSTALLED_SHA)


if __name__ == '__main__':
    print('PASS', verify())
