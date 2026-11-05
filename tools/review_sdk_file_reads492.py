"""Find direct File.ReadAllText calls owned by the shipped Bugsnag module."""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from client_patch.patcher.telemetry import RECIPE_VERSION, patch_component
from tools.extract_descriptors import ExtractionError, Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_sdk_direct_game401 import LLVM
from tools.review_webview_fulltext396 import METADATA, ORIGINAL, METADATA_SHA, ORIGINAL_SHA

TARGET = 0x35480a0  # System.IO.File.ReadAllText pinned in 481.


def review():
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION == 44
    pe, md = PE(raw), Metadata(metadata)
    count, table = pe.module('BugsnagUnity.Windows.dll', 1224)
    images = [image for image in md.images if md.string(image[0]) == 'BugsnagUnity.Windows.dll']
    assert len(images) == 1
    image = images[0]
    assert image[3] > 0 and image[2] >= 0 and image[2]+image[3] <= len(md.types)
    owners = {}
    for typ in md.types[image[2]:image[2]+image[3]]:
        if typ[16] == 0:
            continue
        methods = md.methods_for_type(typ)
        for method in methods:
            slot = (method[6] & 0xffffff) - 1
            if not 0 <= slot < count:
                continue
            pointer, = struct.unpack_from('<Q', raw, pe.offset(table+8*slot, 8))
            if pointer not in pe.function_ends:
                continue
            name = '.'.join(filter(None, (md.string(typ[1]), md.string(typ[0]),
                                          md.string(method[0]))))
            owners.setdefault(pointer-pe.base, set()).add(name)
    starts = sorted(owners)
    all_starts = sorted(address-pe.base for address in pe.function_ends)
    found = []
    for address, size, offset in pe.sections:
        for i in range(size-4):
            if raw[offset+i] != 0xe8:
                continue
            target = address+i+5+struct.unpack_from('<i', raw, offset+i+1)[0]-pe.base
            if target != TARGET:
                continue
            site = address+i-pe.base
            pos = bisect.bisect_right(starts, site)-1
            owner = starts[pos] if pos >= 0 else None
            if owner is None or pe.base+site >= pe.function_ends[pe.base+owner]:
                position = bisect.bisect_right(all_starts, site)-1
                root = all_starts[position] if position >= 0 else None
                if root is None or pe.base+site >= pe.function_ends[pe.base+root]:
                    found.append({'site': hex(site), 'owner': None})
                    continue
                end = pe.function_ends[pe.base+root]-pe.base
                assembly = subprocess.check_output([str(LLVM), '-d',
                    f'--start-address={pe.base+root:#x}',
                    f'--stop-address={pe.base+end:#x}',
                    '--x86-asm-syntax=intel', str(ORIGINAL)])
                decoded = parse_assembly(assembly, pe, raw, root, end)
                instructions = sorted(decoded)
                at = bisect.bisect_left(instructions, site)
                if site not in decoded:
                    found.append({'site': hex(site), 'owner': None,
                                  'raw_false_positive_in': hex(root)})
                    continue
                found.append({'site': hex(site), 'owner_rva': hex(root),
                              'owner_names': [], 'end_rva': hex(end),
                              'context': [decoded[address]['text'] for address in instructions[max(0,at-8):at+2]]})
            else:
                found.append({'site': hex(site), 'owner_rva': hex(owner),
                              'owner_names': sorted(owners[owner])})
    unnamed = {int(row['owner_rva'], 16) for row in found
               if row.get('owner_names') == []}
    unresolved_initial = set(unnamed)
    nearby = {root: [] for root in unresolved_initial}
    unresolved_modules = []
    for image in md.images:
        if not unnamed:
            break
        module = md.string(image[0])
        selected = md.types[image[2]:image[2]+image[3]]
        if not any(typ[16] for typ in selected):
            continue
        try:
            module_count, module_table = pe.module(module, 1)
        except ExtractionError:
            unresolved_modules.append(module)
            continue
        for typ in selected:
            if not typ[16]:
                continue
            for method in md.methods_for_type(typ):
                slot = (method[6] & 0xffffff)-1
                if not 0 <= slot < module_count:
                    continue
                pointer, = struct.unpack_from('<Q', raw, pe.offset(module_table+8*slot, 8))
                root = pointer-pe.base
                if any(abs(root-candidate) < 0x2000 for candidate in unresolved_initial):
                    name = '.'.join(filter(None, (md.string(typ[1]), md.string(typ[0]),
                                                  md.string(method[0]))))
                    for candidate in unresolved_initial:
                        if abs(root-candidate) < 0x2000:
                            nearby[candidate].append((abs(root-candidate),hex(root),module+':'+name))
                if root not in unnamed:
                    continue
                name = '.'.join(filter(None, (md.string(typ[1]), md.string(typ[0]),
                                              md.string(method[0]))))
                for row in found:
                    if row.get('owner_rva') == hex(root):
                        row['owner_names'].append(module+':'+name)
                unnamed.remove(root)
    assert [int(row['site'], 16) for row in found] == [
        0x836a7a, 0x83782e, 0x2630b35, 0x2632a86,
        0x458211d, 0x4592123, 0x4ceba3f, 0x54898b2]
    assert unnamed == {0x2630870, 0x2632790}
    assert found[0]['owner_names'] == ['BugsnagUnity.CacheManager.GetCachedDeviceId']
    assert found[1]['owner_names'] == ['BugsnagUnity.CacheManager.GetJsonFromCachePath']
    assert all(row.get('owner_names', []) and not any('Bugsnag' in name for name in row['owner_names'])
               for row in found[4:])
    current = patch_component('GameAssembly.dll', raw)
    getter = pe.offset(pe.base+0x8368b0)
    json_reader = pe.offset(pe.base+0x837816)
    assert current[getter:getter+3] == bytes.fromhex('31c0c3')
    assert current[json_reader:json_reader+6] == bytes.fromhex('e91f00000090')
    return {'passed': True, 'recipe': RECIPE_VERSION,
            'original_sha256': ORIGINAL_SHA, 'target': hex(TARGET),
            'current_sha256': hashlib.sha256(current).hexdigest(),
            'raw_direct_candidates': found,
            'unresolved_owner_roots': [hex(root) for root in sorted(unnamed)],
            'nearby_metadata_methods': {hex(root): sorted(entries)[:8]
                                        for root, entries in nearby.items()},
            'unresolved_modules': unresolved_modules,
            'named_sdk_calls_guarded': True}


if __name__ == '__main__':
    result = review()
    out = Path('local/privacy492-file-read01')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('passed','recipe','original_sha256',
        'current_sha256','target','named_sdk_calls_guarded','unresolved_owner_roots')},
        sort_keys=True))
