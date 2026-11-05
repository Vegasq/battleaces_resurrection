"""Verify recipe26's four new reporter callback entry guards on the pinned original."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.review_reporter_delegate_targets300 import ORIGINAL, OLD_SHA


def verify() -> dict[str, object]:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == OLD_SHA
    assert RECIPE_VERSION in (26, 27, 28)
    component = COMPONENTS['GameAssembly.dll']
    names = ('<Subs>b__20_0', '<Subs>b__20_1', 'CleanBugEvents',
             'AssignCustomGroupingHash')
    selected = [p for p in component.patches if any(n in p.label for n in names)]
    assert len(selected) == 4 and all(p.replacement == b'\x31\xc0\xc3' for p in selected)
    transformed = patch_component('GameAssembly.dll', original)
    expected={26:'7e4b761efb3181ac78802ba2e986d2e1c2f2deda7c88d956e5b7a35f1435a0a2',
              27:'1064252ba1c044683b08d74894abfe30245ee47e9dd96fdf3fa7c6567bde0ed8',
              28:'2568beb2ed9deeda4e15941483889da53870ecbf05491d3c78455e4376b34739'}
    assert hashlib.sha256(transformed).hexdigest() == expected[RECIPE_VERSION]
    for patch in selected:
        assert original[patch.offset:patch.offset + len(patch.guard)] == patch.guard
        assert transformed[patch.offset:patch.offset + 3] == patch.replacement
    without_four = bytearray(transformed)
    for patch in selected:
        without_four[patch.offset:patch.offset + 3] = original[patch.offset:patch.offset + 3]
    changed = [i for i, (a, b) in enumerate(zip(without_four, transformed)) if a != b]
    assert len(changed) == 12
    assert set(changed) == {p.offset + i for p in selected for i in range(3)}
    return {'recipe': RECIPE_VERSION, 'new_callbacks': len(selected),
            'delta_bytes': len(changed), 'output_sha256': hashlib.sha256(transformed).hexdigest()}


if __name__ == '__main__':
    print('PASS', verify())
