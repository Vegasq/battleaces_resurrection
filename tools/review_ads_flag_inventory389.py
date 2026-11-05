"""Bound all literal C6 [base+5c],1 candidates in original Unity .text.

This encoding inventory cannot prove all writers or pointer provenance.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy389-ads-flag-all01'
PRIOR = ROOT / 'local/privacy312-ads-manager-writers01'
OWNERS = {
    0x4bd4f3: (0x4bd4f0, 0x4bd4f7, OUT),
    0x8e0d73: (0x8e0a50, 0x8e12e1, OUT),
    0xecb7b4: (0xecad00, 0xecbb33, OUT),
    0xece6c8: (0xecd9c0, 0xecf9d6, OUT),
    0xf95731: (0xf95700, 0xf95752, OUT),
    0xfba8f3: (0xfba8b0, 0xfbaa5f, OUT),
    0x105065c: (0x1050370, 0x105067d, PRIOR),
    0x10508ef: (0x1050680, 0x105090e, PRIOR),
    0x1050a95: (0x1050910, 0x1050ab3, PRIOR),
    0x1050c0c: (0x1050ac0, 0x1050c2d, PRIOR),
    0x105109e: (0x1050e10, 0x10510e8, PRIOR),
    0x12e7493: (0x12e7490, 0x12e7497, OUT),
    0x12e8dc7: (0x12e8d00, 0x12e8f1c, OUT),
    0x1551203: (0x1550da0, 0x1551627, OUT),
    0x17c5fc2: (0x17c5bd0, 0x17c600c, OUT),
}
SHORT = {0x4bd4f3, 0x12e7493}


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, installed)
    pe, ip = PE(original), PE(installed)
    start, size, offset = next(s for s in pe.sections if s[0] == pe.base + 0x1000)
    found = [start + index - pe.base for index in range(size - 3)
             if original[offset + index] == 0xc6
             and original[offset + index + 1] & 0xf8 == 0x40
             and original[offset + index + 2] == 0x5c
             and original[offset + index + 3] == 1]
    assert found == sorted(OWNERS), [hex(site) for site in found]
    counts = {}
    for site, (root, end, folder) in OWNERS.items():
        if site not in SHORT:
            assert pe.function_ends[pe.base + root] == pe.base + end
        assembly = (folder / f'{root:x}.asm').read_bytes()
        rows = parse_assembly(assembly, pe, original, root, end)
        row = rows.get(site) or rows.get(site - 1)
        assert row and row['code'].endswith(original[pe.offset(pe.base + site, 4):
                                                     pe.offset(pe.base + site, 4) + 4])
        assert row['text'].startswith('mov byte ptr [') and row['text'].endswith(' + 0x5c], 0x1')
        assert not any(marker in assembly for marker in
                       (b'0x181c0af00', b'0x1803611d0', b'0x180c307c0'))
        old, new = pe.offset(pe.base + root, end - root), ip.offset(ip.base + root, end - root)
        assert original[old:old + end - root] == installed[new:new + end - root]
        counts[hex(site)] = dict(root=hex(root), decoded_instructions=len(rows),
                                 complete_unwind_owner=site not in SHORT)
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  encoding='C6 ModRM 40..47 disp8 5c imm8 01',
                  literal_write_candidates=len(found), complete_owner_sites=len(found) - len(SHORT),
                  short_window_sites=[hex(site) for site in sorted(SHORT)],
                  direct_manager_global_or_callback_reference_in_selected_windows=False,
                  manager_pointer_alias_or_other_encoding_resolved=False, sites=counts)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: value for key, value in result.items() if key != 'sites'}, sort_keys=True))
