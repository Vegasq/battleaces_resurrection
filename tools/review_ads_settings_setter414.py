"""Resolve the corrected Unity Ads enabled setter's concrete virtual target."""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess

from tools.review_ads_settings_pair413 import (
    ROOT, GAME, ORIGINAL, ORIGINAL_SHA, LLVM, PE, describe_unity,
    region, review as review_pair,
)

OUT = ROOT / 'local/privacy414-ads-settings-setter01'
CONSTRUCTOR = (0xc03bf0, 0xc03e94)
NOTIFY = (0xc038d0, 0xc03932)
SETTER = (0x1f48d0, 0x1f48ed)
TARGET = (0xc03970, 0xc0397e)
TABLE = 0x1a27a18
GLOBAL = 0x1ca49c8


def review() -> dict:
    pair = review_pair()
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    assert descriptor['fileSha256'] == pair['current_sha256']
    pe, cp = PE(original), PE(current)
    assert pe.function_ends[pe.base + CONSTRUCTOR[0]] == pe.base + CONSTRUCTOR[1]
    assert pe.function_ends[pe.base + NOTIFY[0]] == pe.base + NOTIFY[1]
    for start, end in (CONSTRUCTOR, NOTIFY, SETTER, TARGET):
        assert region(pe, original, start, end-start) == region(cp, current, start, end-start)
    assert struct.unpack('<Q', region(pe, original, TABLE+0x20, 8))[0] == pe.base + TARGET[0]
    assert region(pe, original, TABLE, 0x28) == region(cp, current, TABLE, 0x28)
    constructor = region(pe, original, *[CONSTRUCTOR[0], CONSTRUCTOR[1]-CONSTRUCTOR[0]])
    assert constructor[0xc03c1c-CONSTRUCTOR[0]:0xc03c23-CONSTRUCTOR[0]] == bytes.fromhex(
        '48 8d b9 b8 00 00 00')
    assert constructor[0xc03c9b-CONSTRUCTOR[0]:0xc03ca2-CONSTRUCTOR[0]] == bytes.fromhex(
        '48 8d 05 76 3d e2 00')
    assert 0xc03c9b + 7 + struct.unpack_from('<i', constructor, 0xc03c9e-CONSTRUCTOR[0])[0] == TABLE
    assert constructor[0xc03ccd-CONSTRUCTOR[0]:0xc03cd0-CONSTRUCTOR[0]] == bytes.fromhex('48 89 07')
    setter = region(pe, original, SETTER[0], SETTER[1]-SETTER[0])
    assert setter[0x1f48d3-SETTER[0]:0x1f48da-SETTER[0]] == bytes.fromhex('48 8b 0d ee 00 ab 01')
    assert 0x1f48d3 + 7 + struct.unpack_from('<i', setter, 0x1f48d6-SETTER[0])[0] == GLOBAL
    assert setter[0x1f48e9-SETTER[0]:] == bytes.fromhex('48 ff 60 20')
    target = region(pe, original, TARGET[0], TARGET[1]-TARGET[0])
    assert target == bytes.fromhex('3a 51 10 74 08 88 51 10 e9 53 ff ff ff c3')
    assert TARGET[0] + 8 + 5 + struct.unpack_from('<i', target, 9)[0] == NOTIFY[0]
    notification = region(pe, original, NOTIFY[0], NOTIFY[1]-NOTIFY[0])
    assert notification[:15] == bytes.fromhex('40 57 48 83 ec 20 48 8b 79 08 48 85 ff 74 4d')

    OUT.mkdir(parents=True, exist_ok=True)
    for label, (start, end) in {'constructor': CONSTRUCTOR, 'setter-target': TARGET,
                                'change-notify': NOTIFY}.items():
        assembly = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={pe.base+start:#x}',
            f'--stop-address={pe.base+end:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)])
        (OUT / f'{label}.asm').write_bytes(assembly)
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  settings_global=hex(GLOBAL), inline_object_offset='0xb8',
                  constructor_vtable=hex(TABLE), setter_virtual_slot='0x20',
                  concrete_target=hex(TARGET[0]), changed_byte_offset='0x10',
                  changed_global_field='global_1ca49c8+0xc8',
                  changed_value_notification=hex(NOTIFY[0]),
                  upstream_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
