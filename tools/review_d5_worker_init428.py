"""Verify the current state-three worker's shared callback-dispatch contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA

OUT = Path(__file__).resolve().parents[1] / 'local/privacy428-worker-init01'
FUNCTIONS = {0xc402d0: 0xc40373, 0xc425d0: 0xc42782,
             0xc3f140: 0xc3fbc2}
CALLS = {(0xc40308, 0xc425d0): 'e8c3220000',
         (0xc40320, 0xc3f140): 'e81beeffff'}
SITES = {0xc42694: '4c8b14cb', 0xc426b2: '41ffd2',
         0xc426c6: '41ffd2', 0xc42669: '488d9f280c0000',
         0xc426cb: '3bbb000c0000'}


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, current)
    source, patched = PE(original), PE(current)
    for begin, end in FUNCTIONS.items():
        assert source.function_ends[source.base + begin] == source.base + end
        assert patched.function_ends[patched.base + begin] == patched.base + end
        size = end - begin
        start, now = (source.offset(source.base + begin, size),
                      patched.offset(patched.base + begin, size))
        assert original[start:start+size] == current[now:now+size]
    for (site, target), expected in CALLS.items():
        code = bytes.fromhex(expected)
        assert site + 5 + struct.unpack_from('<i', code, 1)[0] == target
        for image, pe in ((original, source), (current, patched)):
            offset = pe.offset(pe.base + site, 5)
            assert image[offset:offset+5] == code
    for site, expected in SITES.items():
        code = bytes.fromhex(expected)
        for image, pe in ((original, source), (current, patched)):
            offset = pe.offset(pe.base + site, len(code))
            assert image[offset:offset+len(code)] == code
    assert original[source.offset(source.base + 0x18d6e8c, 6):][:6] == b'values'
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  current_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  function_bounds={hex(k): hex(v) for k, v in FUNCTIONS.items()},
                  worker_direct_calls={hex(site): hex(target) for site, target in CALLS},
                  callback_array_pointer=hex(0xc42694),
                  callback_invocations=[hex(0xc426b2), hex(0xc426c6)],
                  whole_worker_entry_guard_justified=False,
                  full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review()))
