"""Classify two concrete offsets adjacent to the advertising callback object."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_manager_cell400 import LLVM
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA

OUT = Path(__file__).resolve().parents[1] / 'local/privacy429-adjacent-alias01'
SITES = {
    0xa03201: '488d8e98140000',
    0xa03216: 'ff155c74e500',
    0xa0321e: '488dbea0140000',
    0xc332a7: '4d8dbea0140000',
    0xc332ae: '488d057b93df00',
    0xc332b5: '49898698140000',
    0xc332c0: '488d05017ddf00',
    0xc332c7: '498907',
    0xc334b6: '488d8ba0140000',
    0xc334bd: '488b01',
    0xc334c0: 'ff5030',
    0xc30890: '0fb681a8010000c3',
}


def imported_symbol() -> tuple[str, int]:
    readobj = LLVM.with_name('llvm-readobj.exe')
    result = subprocess.run([str(readobj), '--coff-imports', str(ORIGINAL)],
                            capture_output=True, text=True, check=True)
    assert result.stderr == ''
    blocks = re.findall(r'Import \{\n(.*?)\n\}', result.stdout, re.S)
    for block in blocks:
        if 'ImportAddressTableRVA: 0x185A1D8' not in block:
            continue
        assert 'Name: KERNEL32.dll' in block
        names = re.findall(r'^  Symbol: ([^\n]+)', block, re.M)
        index = (0x185a678 - 0x185a1d8) // 8
        assert (0x185a678 - 0x185a1d8) % 8 == 0
        assert names[index] == 'QueryPerformanceFrequency (1116)'
        return names[index], index
    raise AssertionError('Pinned IAT block absent')


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    a, b = PE(original), PE(current)
    for site, expected in SITES.items():
        code = bytes.fromhex(expected)
        for image, pe in ((original, a), (current, b)):
            offset = pe.offset(pe.base + site, len(code))
            assert image[offset:offset+len(code)] == code
    assert 0xa03216 + 6 + struct.unpack('<i', bytes.fromhex('5c74e500'))[0] == 0x185a678
    assert 0xc332ae + 7 + struct.unpack('<i', bytes.fromhex('7b93df00'))[0] == 0x1a2c630
    assert 0xc332c0 + 7 + struct.unpack('<i', bytes.fromhex('017ddf00'))[0] == 0x1a2afc8
    for image, pe in ((original, a), (current, b)):
        offset = pe.offset(pe.base + 0x1a2afc8 + 0x30, 8)
        assert image[offset:offset+8] == struct.pack('<Q', pe.base + 0xc30890)
    symbol, index = imported_symbol()
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  performance_frequency_site=hex(0xa03201),
                  performance_frequency_iat=hex(0x185a678),
                  performance_frequency_import=symbol, import_index=index,
                  main_callback_vtable=hex(0x1a2c630),
                  main_adjacent_vtable=hex(0x1a2afc8),
                  main_adjacent_getter=hex(0xc30890),
                  producer_resolved=False, full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review()))
