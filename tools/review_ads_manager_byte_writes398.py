"""Inventory decoded-looking MOV byte [nonstack base+5c] sites in Unity .text.

This extends the prior C6 literal-one review. The offset alone never proves
the receiver is the advertising manager; indirect and bulk writers remain.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import re
import subprocess

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_flag_inventory389 import OWNERS as PRIOR_SITES
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy398-manager-writes01'
LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
LINE = re.compile(r'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(mov\s+byte ptr \[(?!rsp|rbp)[^\]]+\+ 0x5c\],.+)$')
DIRECT_LEADS = (b'0x181c0af00', b'0x180c307c0', b'0x1803611d0')


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, installed)
    pe, ip = PE(original), PE(installed)
    roots = sorted(pe.function_ends)
    candidates = []
    process = subprocess.Popen([
        str(LLVM), '-d', '--section=.text', '--x86-asm-syntax=intel',
        str(ORIGINAL)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    for raw_line in process.stdout:
        match = LINE.match(raw_line.decode('utf-8', 'replace'))
        if not match:
            continue
        address = int(match[1], 16)
        code = bytes.fromhex(match[2])
        site = address - pe.base
        assert original[pe.offset(address, len(code)):pe.offset(address, len(code)) + len(code)] == code
        assert installed[ip.offset(address, len(code)):ip.offset(address, len(code)) + len(code)] == code
        position = bisect.bisect_right(roots, address) - 1
        owner = roots[position] if position >= 0 and address < pe.function_ends[roots[position]] else None
        prior = any(site in (old, old - 1) for old in PRIOR_SITES)
        candidates.append(dict(site=hex(site), code=code.hex(), text=match[3],
                               owner=hex(owner - pe.base) if owner else None,
                               prior389=prior, complete_owner=False))
    err = process.stderr.read()
    assert process.wait() == 0 and not err, err[:200]
    assert len(candidates) == 45
    assert sum(row['prior389'] for row in candidates) == 15
    owners = sorted({int(row['owner'], 16) for row in candidates if row['owner']})
    assert len(owners) == 34
    OUT.mkdir(exist_ok=True)
    reviewed = []
    for root in owners:
        end = pe.function_ends[pe.base + root] - pe.base
        size = end - root
        old = original[pe.offset(pe.base + root, size):pe.offset(pe.base + root, size) + size]
        new = installed[ip.offset(ip.base + root, size):ip.offset(ip.base + root, size) + size]
        assert old == new
        assembly = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={pe.base + root:#x}',
            f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel',
            str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, original, root, end)
        assert not any(marker in assembly for marker in DIRECT_LEADS)
        sites = [row for row in candidates if row['owner'] == hex(root)]
        for row in sites:
            site = int(row['site'], 16)
            instruction = decoded[site]
            assert instruction['code'].hex() == row['code']
            assert instruction['text'].startswith('mov byte ptr [')
            assert ' + 0x5c], ' in instruction['text']
            row['complete_owner'] = True
        (OUT / f'{root:x}.asm').write_bytes(assembly)
        reviewed.append(dict(root=hex(root), end=hex(end),
                             instructions=len(decoded), sites=[x['site'] for x in sites]))
    assert sum(row['complete_owner'] for row in candidates) == 36
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  scope='MOV byte ptr [nonstack base+0x5c] decoded by linear .text disassembly',
                  candidates=len(candidates), previously_reviewed=15, new_candidates=30,
                  complete_owner_sites=36, ownerless_sites=9, complete_owner_roots=len(owners),
                  direct_manager_cell_predicate_or_callback_refs_in_complete_owners=False,
                  ownerless_or_indirect_aliases_resolved=False,
                  alternate_encodings_or_bulk_writes_resolved=False,
                  advertising_producer_resolved=False,
                  sites=candidates, owners=reviewed)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: result[key] for key in ('passed', 'candidates',
                                                  'previously_reviewed', 'new_candidates',
                                                  'complete_owner_sites', 'ownerless_sites')}))
