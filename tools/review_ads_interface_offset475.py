"""Check the bounded pristine Unity IAdsIdListener subobject offset census."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'local/d5-ghidra-12.1.4/pdb-interface-offset475-console.log'
SCRIPT = ROOT / 'local/d5-ghidra-12.1.4/scripts/TraceAdsInterfaceOffset475.java'
UNITY = Path(os.environ.get('BA_ORIGINAL_GAME_ROOT', ROOT / 'local/pristine-game')) / 'UnityPlayer.dll'
EXPECTED_UNITY = 'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review() -> dict:
    assert sha(UNITY) == EXPECTED_UNITY
    lines = LOG.read_text(encoding='utf-16').splitlines()
    assert any('Processing read-only project file: /UnityPlayer.dll' in x for x in lines)
    assert any('Execute script: TraceAdsInterfaceOffset475.java' in x for x in lines)
    rows = [x.split('TraceAdsInterfaceOffset475.java> ', 1)[1] for x in lines
            if 'TraceAdsInterfaceOffset475.java> ' in x]
    total = [x for x in rows if x.startswith('TOTAL ')]
    assert len(total) == 1 and total[0].strip() == 'TOTAL scanned=59459 functions=19 hits=23 (GhidraScript)'
    functions = [x for x in rows if x.startswith('FUNCTION ')]
    instructions = [x for x in rows if x.startswith('INS ')]
    assert len(functions) == 19 and len(instructions) == 23
    analytics = [x for x in functions if any(name in x for name in
        ('AnalyticsCoreStats', 'UnityAnalytics', 'BaseUnityAnalytics'))]
    assert len(analytics) == 8
    assert not any('LEA' in x and '+ 0X1498]' in x and x.startswith('INS 180c')
                   for x in instructions)
    assert any('INS 180c2eed8 MOV QWORD PTR [RDI + 0X1498],RAX' in x for x in instructions)
    assert any('INS 180c332b5 MOV QWORD PTR [R14 + 0X1498],RAX' in x for x in instructions)
    return dict(passed=True, scanned_functions=59459, functions_with_exact_offset=19,
                exact_offset_instructions=23, analytics_functions_with_exact_offset=len(analytics),
                direct_analytics_lea_plus_1498=0, unity_sha256=sha(UNITY),
                script_sha256=sha(SCRIPT), log_sha256=sha(LOG))


if __name__ == '__main__':
    print(review())
