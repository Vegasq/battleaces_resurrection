"""Bind direct original Unity .text references into the ads-manager cell region.

This is a literal RIP/absolute-pointer census, not alias or provider closure.
"""
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
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy400-manager-cell01'
LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
CELL_START, CELL_END = 0x1c0af00, 0x1c0afb0
WINDOWS = {0x17920: 0x1797e, 0x5fb70: 0x5fca2, 0x18469b0: 0x18469e8}
EXPECTED = {0x1792b: 0x1c0af58, 0x17932: 0x1c0af80,
            0x17950: 0x1c0af00, 0x5fbad: 0x1c0af00,
            0x18469b0: 0x1c0af88, 0x18469b7: 0x1c0af80,
            0x18469c7: 0x1c0af88, 0x18469ce: 0x1c0af80}
COMMENT = re.compile(rb'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+.+# 0x(18[0-9a-f]+)')


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, installed)
    pe, ip = PE(original), PE(installed)
    hits = {}
    process = subprocess.Popen([
        str(LLVM), '-d', '--section=.text', '--x86-asm-syntax=intel',
        str(ORIGINAL)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None and process.stderr is not None
    for line in process.stdout:
        match = COMMENT.match(line)
        if not match:
            continue
        target = int(match[3], 16) - pe.base
        if not CELL_START <= target < CELL_END:
            continue
        address = int(match[1], 16)
        site = address - pe.base
        code = bytes.fromhex(match[2].decode())
        assert site not in hits and len(code) == 7
        assert site + len(code) + struct.unpack_from('<i', code, 3)[0] == target
        assert original[pe.offset(address, 7):pe.offset(address, 7) + 7] == code
        assert installed[ip.offset(address, 7):ip.offset(address, 7) + 7] == code
        hits[site] = dict(site=hex(site), target=hex(target), code=code.hex())
    error = process.stderr.read()
    assert process.wait() == 0 and not error, error[:200]
    assert {site: int(row['target'], 16) for site, row in hits.items()} == EXPECTED
    OUT.mkdir(exist_ok=True)
    window_rows = []
    for start, end in WINDOWS.items():
        size = end - start
        old = original[pe.offset(pe.base + start, size):pe.offset(pe.base + start, size) + size]
        new = installed[ip.offset(ip.base + start, size):ip.offset(ip.base + start, size) + size]
        assert old == new
        if start != 0x18469b0:
            assert pe.function_ends[pe.base + start] == pe.base + end
        assembly = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={pe.base + start:#x}',
            f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel',
            str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, original, start, end)
        sites = [site for site in hits if start <= site < end]
        for site in sites:
            assert decoded[site]['code'].hex() == hits[site]['code']
        (OUT / f'{start:x}.asm').write_bytes(assembly)
        window_rows.append(dict(start=hex(start), end=hex(end),
                                complete_unwind=start != 0x18469b0,
                                instructions=len(decoded), sites=[hex(x) for x in sites]))
    assert sum(len(row['sites']) for row in window_rows) == len(EXPECTED)
    pointer = struct.pack('<Q', pe.base + CELL_START)
    absolute = []
    position = 0
    while (position := original.find(pointer, position)) >= 0:
        absolute.append(pe.address(position) - pe.base)
        position += 1
    assert absolute == [0x1c0af60]
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  rip_hits=len(hits), regions=window_rows,
                  absolute_cell_pointer_slots=[hex(x) for x in absolute],
                  all_direct_hits_in_known_registry_request_exit=True,
                  computed_aliases_or_secondary_callback_producer_resolved=False,
                  hits=[hits[x] for x in sorted(hits)])
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: result[key] for key in ('passed', 'rip_hits',
                                                  'absolute_cell_pointer_slots',
                                                  'all_direct_hits_in_known_registry_request_exit')}))
