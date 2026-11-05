"""Bind the corrected Ads flag notification's three immediate helper bodies."""
from __future__ import annotations

import hashlib
import json
import subprocess

from tools.review_ads_settings_pair413 import (
    ROOT, GAME, ORIGINAL, ORIGINAL_SHA, LLVM, PE, describe_unity, region,
)

OUT = ROOT / 'local/privacy415-ads-settings-notify01'
ROOT_FN = (0xc038d0, 0xc03932)
HELPERS = {
    'state-byte': (0x5b8d40, 0x5b8df0),
    'state-update': (0x5ba5a0, 0x5ba653),
    'state-propagate': (0x5bd620, 0x5bd716),
}
EXPECTED_CALLS = {
    'state-byte': (0xc038f0, 0x5b8d40),
    'state-update': (0xc03903, 0x5ba5a0),
    'state-propagate': (0xc03922, 0x5bd620),
}


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    pe, cp = PE(original), PE(current)
    assert pe.function_ends[pe.base + ROOT_FN[0]] == pe.base + ROOT_FN[1]
    root = region(pe, original, ROOT_FN[0], ROOT_FN[1]-ROOT_FN[0])
    assert root == region(cp, current, ROOT_FN[0], len(root))
    assert root[0xc038d6-ROOT_FN[0]:0xc038da-ROOT_FN[0]] == bytes.fromhex('48 8b 79 08')
    assert root[0xc038df-ROOT_FN[0]:0xc038e6-ROOT_FN[0]] == bytes.fromhex('80 3d 5c 93 10 01 00')

    OUT.mkdir(parents=True, exist_ok=True)
    reviewed = []
    for label, (start, end) in HELPERS.items():
        assert pe.function_ends[pe.base + start] == pe.base + end
        old = region(pe, original, start, end-start)
        assert old == region(cp, current, start, end-start)
        site, target = EXPECTED_CALLS[label]
        call = root[site-ROOT_FN[0]:site-ROOT_FN[0]+5]
        assert call[0] == 0xe8
        assert site + 5 + int.from_bytes(call[1:], 'little', signed=True) == target == start
        asm = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={pe.base+start:#x}',
            f'--stop-address={pe.base+end:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)])
        assert b'0x180c307c0' not in asm and b'0x1498' not in asm
        (OUT / f'{label}.asm').write_bytes(asm)
        reviewed.append(dict(label=label, start=hex(start), end=hex(end),
                             bytes=len(old), sha256=hashlib.sha256(old).hexdigest()))
    propagate = region(pe, original, *[HELPERS['state-propagate'][0],
                                       HELPERS['state-propagate'][1]-HELPERS['state-propagate'][0]])
    for site, target in ((0x5bd6dc, 0x5ba5a0), (0x5bd6e7, 0x5bd620)):
        call = propagate[site-0x5bd620:site-0x5bd620+5]
        assert call[0] == 0xe8
        assert site + 5 + int.from_bytes(call[1:], 'little', signed=True) == target
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  notify_root=hex(ROOT_FN[0]), immediate_helpers=reviewed,
                  propagation_can_recurse=True,
                  selected_bodies_have_no_direct_callback_reference=True,
                  indirect_descendant_routes_resolved=False,
                  advertising_id_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
