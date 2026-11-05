"""Byte-bound the seven new +5c byte writes outside unwind-owned functions.

This closes the selected instruction-window gap from review398 only. A source
window without a direct manager literal is not pointer-alias proof.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import subprocess

from tools.ads_connected382 import GAME
from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'local/privacy399-manager-gaps01'
PRIOR = ROOT / 'local/privacy398-manager-writes01/verification.json'
LLVM = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-objdump.exe')
DIRECT_LEADS = (b'0x181c0af00', b'0x180c307c0', b'0x1803611d0')


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    installed = (GAME / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(original, installed)
    pe, ip = PE(original), PE(installed)
    prior = json.loads(PRIOR.read_text(encoding='utf-8'))
    assert prior['passed'] and prior['original_sha256'] == ORIGINAL_SHA
    assert prior['installed_sha256'] == descriptor['fileSha256']
    selected = [row for row in prior['sites'] if row['owner'] is None and not row['prior389']]
    assert len(selected) == 7
    roots = sorted(pe.function_ends)
    windows: dict[tuple[int, int], list[dict]] = {}
    for row in selected:
        address = pe.base + int(row['site'], 16)
        position = bisect.bisect_right(roots, address) - 1
        assert position >= 0 and position + 1 < len(roots)
        start, end = pe.function_ends[roots[position]], roots[position + 1]
        assert start <= address < end
        windows.setdefault((start, end), []).append(row)
    assert len(windows) == 6
    OUT.mkdir(exist_ok=True)
    reviewed = []
    for (start, end), rows in sorted(windows.items()):
        size = end - start
        old = original[pe.offset(start, size):pe.offset(start, size) + size]
        new = installed[ip.offset(start, size):ip.offset(start, size) + size]
        assert old == new
        assembly = subprocess.check_output([
            str(LLVM), '-d', f'--start-address={start:#x}',
            f'--stop-address={end:#x}', '--x86-asm-syntax=intel',
            str(ORIGINAL)])
        decoded = parse_assembly(assembly, pe, original, start - pe.base, end - pe.base)
        assert not any(marker in assembly for marker in DIRECT_LEADS)
        for row in rows:
            instruction = decoded[int(row['site'], 16)]
            assert instruction['code'].hex() == row['code']
            assert instruction['text'].startswith('mov byte ptr [')
            assert ' + 0x5c], ' in instruction['text']
        (OUT / f'{start-pe.base:x}-{end-pe.base:x}.asm').write_bytes(assembly)
        reviewed.append(dict(start=hex(start - pe.base), end=hex(end - pe.base),
                             instructions=len(decoded), sites=[row['site'] for row in rows],
                             references_other_global_1ca4958=b'0x181ca4958' in assembly))
    assert sum(row['references_other_global_1ca4958'] for row in reviewed) == 2
    result = dict(passed=True, original_sha256=ORIGINAL_SHA,
                  installed_sha256=descriptor['fileSha256'], recipe=descriptor['recipe'],
                  new_ownerless_sites=len(selected), contiguous_gap_windows=len(reviewed),
                  prior389_ownerless_sites=2,
                  all_398_selected_sites_instruction_bound_with_prior389=True,
                  direct_manager_cell_predicate_or_callback_reference_in_new_windows=False,
                  pointer_aliases_or_other_write_forms_resolved=False,
                  advertising_producer_resolved=False, windows=reviewed)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: result[key] for key in ('passed', 'new_ownerless_sites',
                                                  'contiguous_gap_windows',
                                                  'advertising_producer_resolved')}))
