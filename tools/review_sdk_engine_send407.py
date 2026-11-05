"""Classify direct callers of shared UnityWebRequest.SendWebRequest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.ads_connected382 import GAME
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_sdk_direct_game401 import LLVM
from tools.review_webview_fulltext396 import ORIGINAL, METADATA, ORIGINAL_SHA, METADATA_SHA

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy407-engine-send01'
SOURCE_SHA = 'cd71b66d3249985e820fc75c3597034c3e2bcfdfa01da96c8844c19e0df8db08'
TARGET = 0x53dd0d0
CALLS = {
    0x80e9cf: ('BugsnagUnity.Windows.dll', 'BugsnagNetworking.BugsnagUnityWebRequest::SendWebRequest', 0x80e920),
    0x821cab: ('BugsnagUnity.Windows.dll', '.<PushToServer>d__21::MoveNext', 0x820de0),
    0x4cd4084: ('Unity.ResourceManager.dll', 'UnityEngine.ResourceManagement.WebRequestQueue::BeginWebRequest', 0x4cd4000),
    0x4cf5973: ('Unity.ResourceManager.dll', 'UnityEngine.ResourceManagement.AsyncOperations.UnityWebRequestOperation::Execute', 0x4cf5920),
}


def resolve_names(raw: bytes, metadata: bytes) -> dict[int, set[tuple[str, str]]]:
    pe, md = PE(raw), Metadata(metadata)
    result: dict[int, set[tuple[str, str]]] = {}
    for image in md.images:
        module = md.string(image[0])
        if module not in ('BugsnagUnity.Windows.dll', 'Unity.ResourceManager.dll'):
            continue
        selected = md.types[image[2]:image[2] + image[3]]
        methods = [method for typ in selected if typ[16]
                   for method in md.methods_for_type(typ)]
        count, table = pe.module(module, max(method[6] & 0xffffff for method in methods))
        for typ in selected:
            for method in md.methods_for_type(typ) if typ[16] else ():
                slot = (method[6] & 0xffffff) - 1
                assert 0 <= slot < count
                address = struct.unpack_from('<Q', raw, pe.offset(table + slot * 8, 8))[0]
                if address:
                    name = f'{md.string(typ[1])}.{md.string(typ[0])}::{md.string(method[0])}'
                    result.setdefault(address - pe.base, set()).add((module, name))
    return result


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION == 38
    pe = PE(raw)
    names = resolve_names(raw, metadata)
    hits = []
    for start, size, offset in pe.sections:
        if start - pe.base not in (0x1000, 0x6af000):
            continue
        code = memoryview(raw)[offset:offset + size]
        for index in range(size - 5):
            if code[index] not in (0xe8, 0xe9):
                continue
            address = start + index
            destination = address + 5 + struct.unpack_from('<i', code, index + 1)[0]
            if destination == pe.base + TARGET:
                hits.append(address - pe.base)
    assert hits == sorted(CALLS)

    source = patch_component('GameAssembly.dll', raw)
    assert hashlib.sha256(source).hexdigest() == SOURCE_SHA
    current = (GAME / 'GameAssembly.dll').read_bytes()
    cp = PE(current)
    patches = [patch for patch in COMPONENTS['GameAssembly.dll'].patches
               if patch.rva == 0x820de0]
    assert len(patches) == 1 and patches[0].replacement == b'\x31\xc0\xc3'
    OUT.mkdir(parents=True, exist_ok=True)
    callers = []
    for site, (module, name, root) in CALLS.items():
        assert (module, name) in names[root]
        end = pe.function_ends[pe.base + root] - pe.base
        assert root <= site < end
        size = end - root
        original_body = raw[pe.offset(pe.base + root, size):pe.offset(pe.base + root, size) + size]
        current_body = current[cp.offset(cp.base + root, size):cp.offset(cp.base + root, size) + size]
        changed = [root + i for i, (a, b) in enumerate(zip(original_body, current_body)) if a != b]
        assert changed == ([0x820de0, 0x820de1, 0x820de2] if root == 0x820de0 else [])
        if root == 0x820de0:
            original_offset = pe.offset(pe.base + root, len(patches[0].guard))
            current_offset = cp.offset(cp.base + root, 3)
            assert raw[original_offset:original_offset + len(patches[0].guard)] == patches[0].guard
            assert source[original_offset:original_offset + 3] == b'\x31\xc0\xc3'
            assert current[current_offset:current_offset + 3] == b'\x31\xc0\xc3'
        assembly = subprocess.check_output([str(LLVM), '-d',
            f'--start-address={pe.base + root:#x}',
            f'--stop-address={pe.base + end:#x}',
            '--x86-asm-syntax=intel', str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, raw, root, end)
        instruction = decoded[site]
        assert len(instruction['code']) == 5 and instruction['code'][0] == 0xe8
        assert site + 5 + struct.unpack_from('<i', instruction['code'], 1)[0] == TARGET
        assert instruction['text'].startswith(f'call 0x{pe.base + TARGET:x}')
        (OUT / f'{root:x}.asm').write_bytes(assembly)
        callers.append(dict(site=hex(site), module=module, method=name,
                            owner=hex(root), end=hex(end),
                            decoded_instructions=len(decoded),
                            current_changed_bytes=[hex(x) for x in changed]))
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  metadata_sha256=METADATA_SHA, source_sha256=SOURCE_SHA,
                  current_sha256=hashlib.sha256(current).hexdigest(),
                  recipe=RECIPE_VERSION, engine_send_target=hex(TARGET),
                  direct_callers=callers, sdk_callers=2, resource_manager_callers=2,
                  cached_sdk_caller_guarded_before_send=True,
                  sdk_wrapper_indirect_acquisition_resolved=False,
                  whole_wire_excluded=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: value for key, value in result.items() if key != 'direct_callers'},
                     sort_keys=True))
