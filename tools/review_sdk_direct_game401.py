"""Bind named RGame direct calls into Bugsnag code to current entry guards.

This is a direct rel32/codegen-table review. Shared generic aliases, unnamed
owners, virtual/delegate calls, reflection and live queue/wire remain outside it.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.ads_connected382 import GAME
from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly
from tools.review_webview_fulltext396 import ORIGINAL, METADATA, ORIGINAL_SHA, METADATA_SHA

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy401-sdk-direct01'
LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
MODULES = {'RGame.dll', 'BugsnagUnity.Windows.dll', 'Bugsnag.dll'}
OWNERS = {0x3cc2140, 0x3cc2bc0, 0x3cc2c90, 0x3cc2ff0,
          0x3cc3150, 0x3cc3c90}
GUARDS = OWNERS - {0x3cc3c90} | {0x3cc3700}
SHARED_ALIAS_TARGETS = {0x83b380, 0x83b520}


def review() -> dict:
    raw, metadata = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(metadata).hexdigest() == METADATA_SHA
    assert RECIPE_VERSION == 38
    pe, md = PE(raw), Metadata(metadata)
    ownership: dict[int, set[str]] = {}
    names: dict[int, list[str]] = {}
    for image in md.images:
        module = md.string(image[0])
        if module not in MODULES:
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
                    ownership.setdefault(address, set()).add(module)
                    names.setdefault(address, []).append(
                        f'{md.string(typ[1])}.{md.string(typ[0])}::{md.string(method[0])}')
    targets = {address for address, modules in ownership.items()
               if (modules & {'BugsnagUnity.Windows.dll', 'Bugsnag.dll'}) and
               'RGame.dll' not in modules}
    roots = sorted(pe.function_ends)
    candidates = []
    format_calls = []
    for start, size, offset in pe.sections:
        if start - pe.base != 0x6af000:
            continue
        code = memoryview(raw)[offset:offset + size]
        for index in range(size - 5):
            if code[index] not in (0xe8, 0xe9):
                continue
            address = start + index
            target = address + 5 + struct.unpack_from('<i', code, index + 1)[0]
            if code[index] == 0xe8 and target == pe.base + 0x3cc3c90:
                format_calls.append(address - pe.base)
            if target not in targets:
                continue
            position = bisect.bisect_right(roots, address) - 1
            owner = roots[position] if position >= 0 and address < pe.function_ends[roots[position]] else None
            candidates.append(dict(site=hex(address - pe.base), target=hex(target - pe.base),
                                   target_names=names[target],
                                   owner=hex(owner - pe.base) if owner else None,
                                   owner_modules=sorted(ownership.get(owner, [])) if owner else []))
    named_game = [row for row in candidates if 'RGame.dll' in row['owner_modules']]
    aliases = [row for row in named_game if int(row['target'], 16) in SHARED_ALIAS_TARGETS]
    reporting = [row for row in named_game if row not in aliases]
    assert len(candidates) == 1543 and len(named_game) == 107
    assert len(aliases) == 87 and len(reporting) == 20
    assert {int(row['owner'], 16) for row in reporting} == OWNERS
    assert format_calls == [0x3cc3a59]
    source = patch_component('GameAssembly.dll', raw)
    assert hashlib.sha256(source).hexdigest() == \
           'cd71b66d3249985e820fc75c3597034c3e2bcfdfa01da96c8844c19e0df8db08'
    installed = (GAME / 'GameAssembly.dll').read_bytes()
    ip = PE(installed)
    OUT.mkdir(exist_ok=True)
    bodies = []
    for root in sorted(OWNERS | {0x3cc3700}):
        end = pe.function_ends[pe.base + root] - pe.base
        assembly = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={pe.base + root:#x}',
            f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel',
            str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, raw, root, end)
        calls = [row for row in reporting if row['owner'] == hex(root)]
        for row in calls:
            site = int(row['site'], 16)
            target = int(row['target'], 16)
            instruction = decoded[site]
            assert len(instruction['code']) == 5 and instruction['code'][0] == 0xe8
            assert site + 5 + struct.unpack_from('<i', instruction['code'], 1)[0] == target
        if root == 0x3cc3700:
            instruction = decoded[0x3cc3a59]
            assert instruction['text'].startswith('call 0x183cc3c90')
        guard = None
        if root in GUARDS:
            patches = [patch for patch in COMPONENTS['GameAssembly.dll'].patches
                       if patch.rva == root]
            assert len(patches) == 1
            patch = patches[0]
            old = pe.offset(pe.base + root, len(patch.guard))
            new = ip.offset(ip.base + root, len(patch.replacement))
            assert raw[old:old + len(patch.guard)] == patch.guard
            assert source[old:old + len(patch.replacement)] == patch.replacement
            assert installed[new:new + len(patch.replacement)] == patch.replacement
            guard = patch.replacement.hex()
        (OUT / f'{root:x}.asm').write_bytes(assembly)
        bodies.append(dict(root=hex(root), end=hex(end), instructions=len(decoded),
                           reporting_calls=len(calls), installed_guard=guard))
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  metadata_sha256=METADATA_SHA,
                  installed_sha256=hashlib.sha256(installed).hexdigest(),
                  recipe=RECIPE_VERSION, raw_candidates=len(candidates),
                  named_rgame_candidates=len(named_game), shared_alias_hits=len(aliases),
                  reporting_specific_calls=len(reporting), guarded_owner_bodies=len(GUARDS),
                  format_sim_error_direct_call=format_calls,
                  format_sim_error_direct_caller_guarded=True,
                  unnamed_or_indirect_routes_excluded=False,
                  whole_queue_or_wire_excluded=False,
                  bodies=bodies, reporting_calls=reporting)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: result[key] for key in ('passed', 'raw_candidates',
                                                  'named_rgame_candidates',
                                                  'shared_alias_hits',
                                                  'reporting_specific_calls',
                                                  'guarded_owner_bodies')}))
