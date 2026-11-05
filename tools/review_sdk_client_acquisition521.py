"""Bind direct Bugsnag Client construction to guarded source entry paths."""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_sdk_direct_game401 import LLVM
from tools.review_webview_fulltext396 import METADATA, METADATA_SHA, ORIGINAL, ORIGINAL_SHA

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy520-game01'
OUT = ROOT / 'local/privacy521-sdk-client01'
TARGETS = {
    0x80b370: [],
    0x810660: [],
    0x8106f0: [(0x80b592, 'jmp', 0x80b370),
                (0x8106e0, 'jmp', 0x810660),
                (0x3cc2a1c, 'call', 0x3cc2140)],
    0x812690: [(0x8108d1, 'call', 0x8106f0)],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review() -> dict:
    assert RECIPE_VERSION == 47 and RUNTIME_VALIDATED is False
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 1224)
    assert count == 1224
    types = [typ for typ in md.types if md.string(typ[0]) == 'Client'
             and md.string(typ[1]) == 'BugsnagUnity']
    assert len(types) == 1
    ctors = [method for method in md.methods_for_type(types[0])
             if md.string(method[0]) == '.ctor']
    assert len(ctors) == 1 and ctors[0][6] == 0x6000090
    slot = (ctors[0][6] & 0xffffff) - 1
    assert slot == 143
    assert struct.unpack_from('<Q', raw, pe.offset(table + slot * 8, 8))[0] == pe.base + 0x812690

    roots = sorted(pe.function_ends)
    found = {target: [] for target in TARGETS}
    for start, size, offset in pe.sections:
        if start - pe.base not in (0x1000, 0x6af000):
            continue
        code = raw[offset:offset + size]
        for opcode, mnemonic in ((0xe8, 'call'), (0xe9, 'jmp')):
            cursor = 0
            needle = bytes((opcode,))
            while (site := code.find(needle, cursor)) >= 0:
                if site + 5 <= size:
                    target = start + site + 5 + struct.unpack_from('<i', code, site + 1)[0] - pe.base
                    if target in found:
                        va = start + site
                        index = bisect.bisect_right(roots, va) - 1
                        owner = roots[index] - pe.base
                        assert roots[index] <= va < pe.function_ends[roots[index]]
                        found[target].append((va - pe.base, mnemonic, owner))
                cursor = site + 1
    for target, expected in TARGETS.items():
        assert sorted(found[target]) == sorted(expected), (hex(target), found[target])

    pointer_sites = {}
    for target, expected_site in ((0x812690, 0x6a38568), (0x8106f0, 0x6a38400),
                                  (0x810660, 0x6a383f8), (0x80b370, 0x6a3a740)):
        pointer = struct.pack('<Q', pe.base + target)
        hits = []
        cursor = 0
        while (site := raw.find(pointer, cursor)) >= 0:
            hits.append(pe.address(site) - pe.base)
            cursor = site + 1
        assert hits == [expected_site], (hex(target), hits)
        pointer_sites[hex(target)] = [hex(site) for site in hits]

    decoded = {}
    for owner in (0x80b370, 0x810660, 0x8106f0, 0x3cc2140):
        end = pe.function_ends[pe.base + owner] - pe.base
        asm = subprocess.check_output([str(LLVM), '-d',
            f'--start-address={pe.base + owner:#x}',
            f'--stop-address={pe.base + end:#x}',
            '--x86-asm-syntax=intel', str(ORIGINAL)])
        decoded[owner] = parse_assembly(asm, pe, raw, owner, end)
    for target, sites in found.items():
        for site, mnemonic, owner in sites:
            row = decoded[owner][site]
            assert row['text'].startswith(mnemonic + ' 0x')
            assert int(row['text'].split('0x', 1)[1].split()[0], 16) == pe.base + target

    installed = (GAME / 'GameAssembly.dll').read_bytes()
    manifest = json.loads((GAME / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    assert manifest['telemetry']['recipe_version'] == 47
    assert manifest['components']['GameAssembly.dll']['patched_sha256'] == hashlib.sha256(installed).hexdigest()
    selected = [patch for patch in COMPONENTS['GameAssembly.dll'].patches
                if patch.rva in (0x80b370, 0x810660, 0x8106f0, 0x3cc2140)]
    assert len(selected) == 4
    for patch in selected:
        assert patch.replacement == b'\xc3'
        assert raw[patch.offset:patch.offset + len(patch.guard)] == patch.guard
        assert installed[patch.offset:patch.offset + 1] == b'\xc3'
    result = {'passed': True, 'original_sha256': ORIGINAL_SHA,
              'metadata_sha256': METADATA_SHA, 'installed_sha256': hashlib.sha256(installed).hexdigest(),
              'ctor_rva': '0x812690', 'ctor_token': '0x6000090', 'ctor_slot': slot,
              'direct_edges': {hex(target): [[hex(site), mnemonic, hex(owner)]
                                           for site, mnemonic, owner in sites]
                               for target, sites in found.items()},
              'absolute_pointer_sites': pointer_sites,
              'guarded_entry_rvas': [hex(patch.rva) for patch in selected],
              'indirect_acquisition_excluded': False, 'final_privacy_qualified': False}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'review521.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
