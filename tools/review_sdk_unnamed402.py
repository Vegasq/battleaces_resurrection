"""Classify unassigned original direct-call candidates from SDK review401.

Short SDK-local tail wrappers are decoded; two remaining complete bodies are
left unnamed. No indirect caller or whole-program delivery claim follows.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from client_patch.patcher.telemetry import patch_component
from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.review_analytics_listener import parse_assembly
from tools.review_sdk_direct_game401 import SHARED_ALIAS_TARGETS
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy402-sdk-unnamed01'
PRIOR = ROOT / 'local/privacy401-sdk-direct01/discovery.json'
LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
UNMAPPED = {0x11fd3a0, 0x11fd5e0}


def review() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    source = patch_component('GameAssembly.dll', raw)
    assert hashlib.sha256(source).hexdigest() == \
           'cd71b66d3249985e820fc75c3597034c3e2bcfdfa01da96c8844c19e0df8db08'
    installed = (GAME / 'GameAssembly.dll').read_bytes()
    pe, ip = PE(raw), PE(installed)
    prior = json.loads(PRIOR.read_text(encoding='utf-8'))
    assert prior['original_sha256'] == ORIGINAL_SHA
    unassigned = [row for row in prior['rows'] if not row['owner_modules']]
    aliases = [row for row in unassigned
               if int(row['target'], 16) in SHARED_ALIAS_TARGETS]
    remaining = [row for row in unassigned if row not in aliases]
    wrappers = [row for row in remaining if row['owner'] is None]
    body_calls = [row for row in remaining if row['owner'] is not None]
    assert (len(unassigned), len(aliases), len(remaining), len(wrappers),
            len(body_calls)) == (617, 606, 11, 9, 2)
    assert {int(row['owner'], 16) for row in body_calls} == UNMAPPED
    roots = sorted(pe.function_ends)
    OUT.mkdir(exist_ok=True)
    wrap_rows = []
    for row in wrappers:
        site = pe.base + int(row['site'], 16)
        position = bisect.bisect_right(roots, site) - 1
        assert position >= 0 and position + 1 < len(roots)
        start, end = pe.function_ends[roots[position]], roots[position + 1]
        assert start <= site < end and end - start <= 64
        size = end - start
        old = raw[pe.offset(start, size):pe.offset(start, size) + size]
        new = installed[ip.offset(start, size):ip.offset(start, size) + size]
        expected = source[pe.offset(start, size):pe.offset(start, size) + size]
        assert expected == new
        changes = [hex(start - pe.base + index) for index, (a, b) in enumerate(zip(old, new))
                   if a != b]
        assert changes == (['0x837130'] if row['site'] == '0x83713c' else [])
        assembly = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={start:#x}',
            f'--stop-address={end:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, raw, start - pe.base, end - pe.base)
        instruction = decoded[site - pe.base]
        assert len(instruction['code']) == 5 and instruction['code'][0] == 0xe9
        assert site - pe.base + 5 + struct.unpack_from('<i', instruction['code'], 1)[0] == \
               int(row['target'], 16)
        (OUT / f'{start-pe.base:x}-{end-pe.base:x}.asm').write_bytes(assembly)
        wrap_rows.append(dict(site=row['site'], target=row['target'],
                              start=hex(start - pe.base), end=hex(end - pe.base),
                              instructions=len(decoded), current_patch_offsets=changes))
    assert len({row['start'] for row in wrap_rows}) == 9
    body_rows = []
    for root in sorted(UNMAPPED):
        end = pe.function_ends[pe.base + root] - pe.base
        size = end - root
        old = raw[pe.offset(pe.base + root, size):pe.offset(pe.base + root, size) + size]
        new = installed[ip.offset(ip.base + root, size):ip.offset(ip.base + root, size) + size]
        assert old == new
        assembly = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={pe.base + root:#x}',
            f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, raw, root, end)
        row = next(item for item in body_calls if item['owner'] == hex(root))
        site = int(row['site'], 16)
        instruction = decoded[site]
        assert len(instruction['code']) == 5 and instruction['code'][0] == 0xe8
        assert site + 5 + struct.unpack_from('<i', instruction['code'], 1)[0] == 0x829d00
        (OUT / f'{root:x}.asm').write_bytes(assembly)
        body_rows.append(dict(root=hex(root), end=hex(end), site=row['site'],
                              target=row['target'], instructions=len(decoded)))
    direct_callers = []
    for start, size, offset in pe.sections:
        if start - pe.base != 0x6af000:
            continue
        code = memoryview(raw)[offset:offset + size]
        for index in range(size - 5):
            if code[index] not in (0xe8, 0xe9):
                continue
            site = start + index
            target = site + 5 + struct.unpack_from('<i', code, index + 1)[0]
            if target - pe.base in UNMAPPED:
                direct_callers.append(hex(site - pe.base))
    assert not direct_callers
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=hashlib.sha256(installed).hexdigest(),
                  unassigned_raw_hits=len(unassigned), shared_constructor_alias_hits=len(aliases),
                  sdk_local_tail_wrappers=len(wrap_rows), unmapped_complete_bodies=len(body_rows),
                  direct_rel32_callers_of_unmapped_bodies=direct_callers,
                  generic_or_indirect_reachability_resolved=False,
                  wrappers=wrap_rows, bodies=body_rows)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: result[key] for key in ('passed', 'unassigned_raw_hits',
                                                  'shared_constructor_alias_hits',
                                                  'sdk_local_tail_wrappers',
                                                  'unmapped_complete_bodies')}))
