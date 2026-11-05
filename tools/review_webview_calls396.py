"""Byte-check the non-library-looking direct Vuplex call candidates.

The full executable raw scan is a discovery aid. This reviewer decodes its
RGame-owned and CursorInfo-owner hits only; it makes no indirect-route claim.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess

from tools.extract_descriptors import PE
from tools.review_analytics_listener import parse_assembly
from tools.review_webview_fulltext396 import ORIGINAL, ORIGINAL_SHA, OUT

LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
CURSOR_OWNERS = {0x5159be0, 0x5174480}


def review() -> dict:
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    pe = PE(raw)
    discovery = json.loads((OUT / 'discovery.json').read_text(encoding='utf-8'))
    assert discovery['original_sha256'] == ORIGINAL_SHA
    candidates = discovery['raw_candidates']
    selected = [row for row in candidates if row['owner_is_rgame'] or
                (row['owner'] is not None and int(row['owner'], 16) in CURSOR_OWNERS)]
    assert len(selected) == 20
    assert sum(row['owner_is_rgame'] for row in selected) == 10
    assert sum(int(row['owner'], 16) in CURSOR_OWNERS for row in selected) == 10
    reviewed = []
    for owner in sorted({int(row['owner'], 16) for row in selected}):
        unwind_end = pe.function_ends[pe.base + owner] - pe.base
        # These two large shared owners contain embedded data near their tails.
        # Stop at the last selected call; a linear decode of the entire unwind
        # extent would interpret jump-table bytes as instructions.
        end = (max(int(row['site'], 16) for row in selected
                   if row['owner'] == hex(owner)) + 5
               if owner in CURSOR_OWNERS else unwind_end)
        assembly = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={pe.base + owner:#x}',
            f'--stop-address={pe.base + end:#x}', '--x86-asm-syntax=intel',
            str(ORIGINAL)])
        (OUT / f'{owner:x}.asm').write_bytes(assembly)
        instructions = parse_assembly(assembly, pe, raw, owner, end)
        calls = []
        for row in candidates:
            if row['owner'] != hex(owner):
                continue
            site, target = int(row['site'], 16), int(row['target'], 16)
            decoded = instructions.get(site)
            if decoded is None:
                continue
            code = decoded['code']
            if len(code) != 5 or code[0] not in (0xe8, 0xe9):
                continue
            assert site + 5 + struct.unpack_from('<i', code, 1)[0] == target
            calls.append(dict(site=row['site'], target=row['target'],
                              target_names=row['target_names'], text=decoded['text']))
        reviewed.append(dict(owner=hex(owner), decoded_end=hex(end),
                             unwind_end=hex(unwind_end),
                             owner_names=next((r['owner_names'] for r in selected
                                               if r['owner'] == hex(owner)), []),
                             instructions=len(instructions), calls=calls))
    actual = {call['site'] for body in reviewed for call in body['calls']}
    assert actual == {row['site'] for row in selected}
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  raw_candidates=len(candidates),
                  decoded_selected_calls=len(actual),
                  rgame_calls=sum(row['owner_is_rgame'] for row in selected),
                  cursorinfo_calls=sum(int(row['owner'], 16) in CURSOR_OWNERS
                                       for row in selected),
                  bodies=reviewed, other_raw_candidates_instruction_checked=False,
                  indirect_or_dynamic_routes_excluded=False)
    (OUT / 'review.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: result[key] for key in ('passed', 'raw_candidates',
                                                  'decoded_selected_calls',
                                                  'rgame_calls', 'cursorinfo_calls')}))
