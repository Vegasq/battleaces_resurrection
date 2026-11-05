"""Classify the fourteen exact +1498 operand sites outside the callback object."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_ads_callback_offset423 import KNOWN_CALLBACK_OBJECT
from tools.review_ads_adjacent_alias429 import review as alias_review

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy430-offset-remaining01'
PRIOR = ROOT / 'local/privacy423-ads-offset-census01/verification.json'
GROUPS = {
    'performance_frequency': {0xa03201},
    'float_scalar': {0xa04d68, 0xcfe6c4, 0x13f0737},
    'frame_or_immediate': {0xa0eda4, 0x10b539c, 0x13eb363, 0x13ec2ef},
    'array_storage': {0x14797ac, 0x1482898, 0x14828d2,
                      0x14829bc, 0x1494df3, 0x14ab320},
}
EXTRA = {
    0x148289f: '486bf038',
    0x1494dfd: 'e87ee0feff',
    0x1482e95: '8b4108',
    0x1482e98: '486bf838',
    0x1482eae: '4883c338',
    0x14ab49a: 'e86102fdff',
    0x147b715: '8b4108',
    0x147b718: '486bf838',
    0x147b72e: '4883c338',
}


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    a, b = PE(original), PE(current)
    prior = json.loads(PRIOR.read_text(encoding='utf-8'))
    assert prior['passed'] and prior['original_sha256'] == ORIGINAL_SHA
    assert len(prior['exact_operand_hits']) == 23
    sites = {int(row['site'], 16): row for row in prior['exact_operand_hits']}
    grouped = set().union(*GROUPS.values())
    assert len(grouped) == 14 and grouped == set(sites) - KNOWN_CALLBACK_OBJECT
    assert alias_review()['passed']
    for site in grouped:
        row = sites[site]
        code = bytes.fromhex(row['bytes'])
        for image, pe in ((original, a), (current, b)):
            offset = pe.offset(pe.base + site, len(code))
            assert image[offset:offset+len(code)] == code
    assert sites[0xa03201]['instruction'] == 'lea\trcx, [rsi + 0x1498]'
    assert sites[0xa04d68]['instruction'].startswith('cvtsi2sd\t')
    assert sites[0xcfe6c4]['instruction'].startswith('movss\t')
    assert sites[0x13f0737]['instruction'].startswith('movss\t')
    assert all(('rsp' in sites[s]['instruction'] or 'rbp' in sites[s]['instruction'])
               for s in (0xa0eda4, 0x10b539c, 0x13ec2ef))
    assert sites[0x13eb363]['instruction'] == 'mov\teax, 0x1498'
    assert sites[0x14797ac]['instruction'] == 'mov\tqword ptr [rsi + 0x1498], rdi'
    assert all('qword ptr [rdi + 0x1498]' in sites[s]['instruction']
               for s in (0x1482898, 0x14828d2, 0x14829bc))
    assert sites[0x1494df3]['instruction'] == 'lea\tr15, [rbx + 0x1498]'
    assert sites[0x14ab320]['instruction'] == 'lea\trcx, [rbx + 0x1498]'
    for site, expected in EXTRA.items():
        code = bytes.fromhex(expected)
        for image, pe in ((original, a), (current, b)):
            offset = pe.offset(pe.base + site, len(code))
            assert image[offset:offset+len(code)] == code
    assert 0x1494dfd + 5 + struct.unpack('<i', bytes.fromhex('7ee0feff'))[0] == 0x1482e80
    assert 0x14ab49a + 5 + struct.unpack('<i', bytes.fromhex('6102fdff'))[0] == 0x147b700
    assert a.function_ends[a.base+0x1482e80] == a.base+0x1482ee5
    assert a.function_ends[a.base+0x147b700] == a.base+0x147b76f
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  classified={k: [hex(s) for s in sorted(v)] for k, v in GROUPS.items()},
                  exact_other_site_count=14, exact_callback_site_count=9,
                  selected_array_stride=0x38,
                  all_exact_numeric_sites_have_instruction_classification=True,
                  computed_aliases_unresolved=True, producer_resolved=False,
                  full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review()))
