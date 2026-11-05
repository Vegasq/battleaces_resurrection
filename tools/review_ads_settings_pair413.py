"""Correct the Unity Ads settings name/function index in the original table."""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess

from tools.review_ads_settings_binding397 import (
    ROOT, OUT as OLD_OUT, GAME, ORIGINAL, ORIGINAL_SHA, LLVM,
    PE, describe_unity,
)

OUT = ROOT / 'local/privacy413-ads-settings-pair01'
NAMES_START = 0x192d030
FUNCTIONS_START = 0x192d0d0
COUNT = 20
NAME = b'UnityEngine.Advertisements.UnityAdsSettings::get_enabled\0'
GETTER = 0x1f48c0
SETTER = 0x1f48d0


def region(pe, data, rva, length):
    offset = pe.offset(pe.base + rva, length)
    return data[offset:offset + length]


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    pe, cp = PE(original), PE(current)
    names = [struct.unpack('<Q', region(pe, original, NAMES_START + 8*i, 8))[0]
             for i in range(COUNT)]
    functions = [struct.unpack('<Q', region(pe, original, FUNCTIONS_START + 8*i, 8))[0]
                 for i in range(COUNT)]
    assert region(pe, original, NAMES_START, COUNT*8) == region(cp, current, NAMES_START, COUNT*8)
    assert region(pe, original, FUNCTIONS_START, COUNT*8) == region(cp, current, FUNCTIONS_START, COUNT*8)
    texts = []
    for address in names:
        offset = pe.offset(address, 1)
        text = original[offset:offset+120].split(b'\0', 1)[0]
        assert text.startswith(b'UnityEngine.') and len(text) < 120
        texts.append(text + b'\0')
    assert texts[0] == b'UnityEngine.Connect.UnityConnectSettings::get_enabled\0'
    assert texts[-1] == b'UnityEngine.Advertisements.UnityAdsSettings::SetGameId\0'
    index = texts.index(NAME)
    assert index == 12 and names.count(names[index]) == 1
    assert functions[index] == pe.base + GETTER
    assert functions[index + 1] == pe.base + SETTER
    assert functions[4] == pe.base + 0x1f3be0  # previously mispaired function
    assert texts[4] == b'UnityEngine.Connect.UnityConnectSettings::get_eventUrl\0'
    assert all(pe.base <= value < pe.base + 0x2000000 for value in functions)

    getter = region(pe, original, GETTER, 0x10)
    setter = region(pe, original, SETTER, 0x1d)
    assert getter == region(cp, current, GETTER, len(getter))
    assert setter == region(cp, current, SETTER, len(setter))
    assert getter == bytes.fromhex('48 8b 05 01 01 ab 01 0f b6 80 c8 00 00 00 c3 cc')
    assert setter[:10] == bytes.fromhex('0f b6 d1 48 8b 0d ee 00 ab 01')
    assert setter[10:17] == bytes.fromhex('48 81 c1 b8 00 00 00')
    assert setter[-4:] == bytes.fromhex('48 ff 60 20')
    assert pe.base + GETTER not in pe.function_ends  # complete leaf to INT3
    assert pe.base + SETTER not in pe.function_ends  # complete leaf to INT3
    assembly = subprocess.check_output([
        str(LLVM), '-d', f'--start-address={pe.base + GETTER:#x}',
        f'--stop-address={pe.base + SETTER + len(setter):#x}',
        '--x86-asm-syntax=intel', str(ORIGINAL)])
    assert b'movzx\teax, byte ptr [rax + 0xc8]' in assembly
    assert b'jmp\tqword ptr [rax + 0x20]' in assembly
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'get-set-enabled.asm').write_bytes(assembly)
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  table_count=COUNT, index=index, name_slot=hex(NAMES_START + 8*index),
                  correct_function_slot=hex(FUNCTIONS_START + 8*index),
                  correct_function=hex(GETTER), setter=hex(SETTER),
                  prior_function=hex(0x1f3be0),
                  prior_function_actual_name=texts[4].decode().rstrip('\0'),
                  getter_reads_settings_byte='global_1ca49c8+0xc8',
                  setter_indirect_target='(global_1ca49c8+0xb8).vtable+0x20',
                  upstream_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
