"""Pin recipe27's reporter-only initial and setter false-state changes."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, patch_component
from tools.extract_descriptors import PE
from tools.review_reporter_delegate_targets300 import ORIGINAL, OLD_SHA


def verify() -> dict[str, object]:
    original=ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest()==OLD_SHA
    assert RECIPE_VERSION in (27,28)
    pe=PE(original)
    patches={p.label:p for p in COMPONENTS['GameAssembly.dll'].patches
             if 'enabled=false' in p.label or 'force=false' in p.label}
    assert len(patches)==2
    initializer=next(p for p in patches.values() if 'enabled=false' in p.label)
    setter=next(p for p in patches.values() if 'force=false' in p.label)
    assert (initializer.rva,initializer.offset,initializer.replacement)==(0x3cc687c,0x3cc4e7c,b'\xc6\x41\x18\x00')
    assert (setter.rva,setter.offset,setter.replacement)==(0x3cc30fd,0x3cc16fd,b'\xb3\x00\x90')
    assert pe.function_ends[pe.base+0x3cc6650]==pe.base+0x3cc6886
    assert pe.function_ends[pe.base+0x3cc30f0]==pe.base+0x3cc3149
    transformed=patch_component('GameAssembly.dll',original)
    expected={27:'1064252ba1c044683b08d74894abfe30245ee47e9dd96fdf3fa7c6567bde0ed8',
              28:'2568beb2ed9deeda4e15941483889da53870ecbf05491d3c78455e4376b34739'}
    assert hashlib.sha256(transformed).hexdigest()==expected[RECIPE_VERSION]
    for patch in patches.values():
        assert original[patch.offset:patch.offset+len(patch.guard)]==patch.guard
        assert transformed[patch.offset:patch.offset+len(patch.replacement)]==patch.replacement
    # Both complete methods retain their tails. MOV BL,0/NOP preserves the
    # original CMP flags consumed by JNE and the existing static-field store.
    for start,end in ((0x3cc6650,0x3cc6886),(0x3cc30f0,0x3cc3149)):
        offset=pe.offset(pe.base+start,end-start)
        before=bytearray(original[offset:offset+end-start])
        after=transformed[offset:offset+end-start]
        for patch in patches.values():
            if start<=patch.rva<end:
                pos=patch.rva-start
                before[pos:pos+len(patch.replacement)]=patch.replacement
        assert after==before
    assert transformed[setter.offset:setter.offset+5]==b'\xb3\x00\x90\x75\x18'
    without=bytearray(transformed)
    for patch in patches.values():
        without[patch.offset:patch.offset+len(patch.replacement)]=original[patch.offset:patch.offset+len(patch.replacement)]
    changed=[i for i,(a,b) in enumerate(zip(without,transformed)) if a!=b]
    assert changed==sorted([initializer.offset+3,setter.offset,setter.offset+1,setter.offset+2])
    return dict(passed=True,recipe=RECIPE_VERSION,changed_bytes=len(changed),
                output_sha256=hashlib.sha256(transformed).hexdigest())


if __name__=='__main__':
    print('PASS',verify())
