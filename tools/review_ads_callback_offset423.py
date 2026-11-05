"""Census exact 0x1498 operands in pinned original Unity executable code."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

from tools.extract_descriptors import PE
from tools.ads_connected382 import GAME
from tools.frida_ads_caller import describe_unity
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_ads_manager_cell400 import LLVM

OUT = Path(__file__).resolve().parents[1] / 'local/privacy423-ads-offset-census01'
LINE = re.compile(r'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(.+)$')
TOKEN = re.compile(r'(?<![0-9a-f])0x1498(?![0-9a-f])')
EXPECTED = {
    0xa03201, 0xa04d68, 0xa0eda4, 0xc2eed8, 0xc2f47e, 0xc2f55a,
    0xc3085a, 0xc332b5, 0xc33b99, 0xc46a44, 0xc66b75, 0xc68184,
    0xcfe6c4, 0x10b539c, 0x13eb363, 0x13ec2ef, 0x13f0737,
    0x14797ac, 0x1482898, 0x14828d2, 0x14829bc, 0x1494df3,
    0x14ab320,
}
KNOWN_CALLBACK_OBJECT = {
    0xc2eed8, 0xc2f47e, 0xc2f55a, 0xc3085a, 0xc332b5,
    0xc33b99, 0xc46a44, 0xc66b75, 0xc68184,
}


def review() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    pe = PE(raw)
    process = subprocess.Popen(
        [str(LLVM), '-d', '--section=.text', '--x86-asm-syntax=intel', str(ORIGINAL)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout is not None and process.stderr is not None
    hits = []
    for line in process.stdout:
        match = LINE.match(line)
        if not match:
            continue
        instruction = match[3].split('#', 1)[0].strip()
        if not TOKEN.search(instruction):
            continue
        site = int(match[1], 16) - pe.base
        code = bytes.fromhex(match[2])
        offset = pe.offset(pe.base + site, len(code))
        assert raw[offset:offset+len(code)] == code
        hits.append(dict(site=hex(site), bytes=code.hex(), instruction=instruction))
    assert process.wait() == 0 and process.stderr.read() == ''
    assert {int(row['site'], 16) for row in hits} == EXPECTED
    assert all(not row['instruction'].startswith('lea\t') or
               row['instruction'].startswith('lea\trcx, [rbx - 0x1498]')
               for row in hits if int(row['site'], 16) in KNOWN_CALLBACK_OBJECT)
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(raw, current)
    current_pe = PE(current)
    for row in hits:
        site = int(row['site'], 16)
        if site not in KNOWN_CALLBACK_OBJECT:
            continue
        code = bytes.fromhex(row['bytes'])
        offset = current_pe.offset(current_pe.base + site, len(code))
        assert current[offset:offset+len(code)] == code
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  exact_operand_hits=hits, count=len(hits),
                  known_callback_object_sites=[hex(x) for x in sorted(KNOWN_CALLBACK_OBJECT)],
                  other_same_numeric_operand_sites=[hex(x) for x in sorted(EXPECTED - KNOWN_CALLBACK_OBJECT)],
                  callback_producer_resolved=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True, count=result['count'],
                          callback_object_sites=len(result['known_callback_object_sites']),
                          other_sites=len(result['other_same_numeric_operand_sites']))))
