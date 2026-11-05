"""Bound direct RIP references to the native Main singleton in original Unity.

Capture assembly only under ignored local/. A pass is a direct-reference/body
inventory, never a complete pointer-alias or advertising-acquisition proof.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from tools.extract_descriptors import PE
from tools.review_analytics_listener import parse_assembly
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.frida_ads_caller import describe_unity
from tools.ads_connected382 import GAME

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy383-main-singleton01'
LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
TARGET_RVA = 0x1d0eb28


def scan(pe: PE, raw: bytes):
    # The sole file-backed executable .text section for this pinned image.
    start, size, offset = next(s for s in pe.sections if s[0] == pe.base + 0x1000)
    target = pe.base + TARGET_RVA
    starts = sorted(pe.function_ends)
    hits = []
    for index in range(size - 6):
        if raw[offset + index] not in (0x89, 0x8b, 0x8d):
            continue
        if raw[offset + index + 1] & 0xc7 != 0x05:
            continue
        at = start + index
        if at + 6 + struct.unpack_from('<i', raw, offset + index + 2)[0] != target:
            continue
        root = starts[bisect.bisect_right(starts, at) - 1]
        covered = root <= at < pe.function_ends[root]
        hits.append((at, root if covered else None,
                     pe.function_ends[root] if covered else None))
    return hits


def verify(*, capture=False):
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    pe = PE(raw)
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(raw, installed)
    ip = PE(installed)
    hits = scan(pe, raw)
    assert len(hits) == 65
    roots = {(root, end) for _, root, end in hits if root is not None}
    assert LLVM.is_file()
    OUT.mkdir(exist_ok=True)
    bodies = {}
    for root, end in sorted(roots):
        name = f'{root - pe.base:x}.asm'
        path = OUT / name
        if capture and not path.exists():
            path.write_bytes(subprocess.check_output([
                str(LLVM), '--disassemble', f'--start-address={root:#x}',
                f'--stop-address={end:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)]))
        rows = parse_assembly(path.read_bytes(), pe, raw, root - pe.base, end - pe.base)
        assert rows and min(rows) == root - pe.base and max(rows) < end - pe.base
        bodies[root] = rows
    candidates = []
    unbounded = []
    for at, root, _ in hits:
        original_off, installed_off = pe.offset(at, 6), ip.offset(at, 6)
        assert raw[original_off:original_off + 6] == installed[installed_off:installed_off + 6]
        if root is None:
            # Unwind coverage has gaps and small leaf procedures. This proves
            # only the individual RIP instruction, not its complete owner.
            off = pe.offset(at)
            begin = at - 1 if raw[off - 1] in range(0x40, 0x50) else at
            name = f'leaf-{at - pe.base:x}.asm'
            path = OUT / name
            if capture and not path.exists():
                path.write_bytes(subprocess.check_output([
                    str(LLVM), '--disassemble', f'--start-address={begin:#x}',
                    f'--stop-address={at + 6:#x}', '--x86-asm-syntax=intel', str(ORIGINAL)]))
            rows = path.read_text(errors='replace').splitlines()
            line = next((line for line in rows if line.startswith(f'{begin:x}:')), None)
            assert line and '# 0x181d0eb28' in line and re.search(r'\b(mov|lea)\b', line)
            unbounded.append(hex(at - pe.base))
            candidates.append(dict(site=hex(at - pe.base), root=None, text=line))
            continue
        row = bodies[root].get(at - pe.base)
        if row is None and raw[pe.offset(at) - 1] in range(0x40, 0x50):
            row = bodies[root].get(at - pe.base - 1)
        assert row is not None
        assert re.match(r'^(mov|lea) ', row['text']) and '[rip ' in row['text'], (hex(at - pe.base), row['text'])
        candidates.append(dict(site=hex(at - pe.base), root=hex(root - pe.base),
                               text=row['text']))
    # Detect immediate same-body references; a callee/alias may still derive
    # the secondary interface from a Main pointer without this literal.
    direct_bodies = [hex(root - pe.base) for root, rows in bodies.items()
                     if any('0x1498' in row['text'] or '0x180c307c0' in row['text']
                            for row in rows.values())]
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  rip_reference_candidates=len(hits), decoded_roots=len(roots),
                  leaf_or_unwind_gap_sites=unbounded,
                  direct_ads_body_roots=direct_bodies,
                  reference_instruction_bytes_unchanged=True,
                  candidates=candidates,
                  alias_or_deeper_producer_resolved=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    result = verify(capture=args.capture)
    print(json.dumps({k: v for k, v in result.items() if k != 'candidates'}))
