"""Bind six reporter AddOnSendError delegate metadata references to their encoded indices."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import ExtractionError, PE
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent.parent / 'BattleAcesBeta_untouched/GameAssembly.dll'
INSTALLED = ROOT / 'local/privacy291-runtime01/game/GameAssembly.dll'
ASSEMBLY = ROOT / 'local/privacy279-game-3cc2140.asm'
OUT = ROOT / 'local/privacy298-reporter-delegates01'
OLD_SHA = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
NEW_SHA = 'c6e4480475e515e71a46e9579ee48d4db1a7f22062db5282d73c314a204d6b4e'
REFS = ((0x3cc276d, 0x186b42af0, 0x60003437, 6683),
        (0x3cc2861, 0x186b42b08, 0x60003439, 6684),
        (0x3cc2903, 0x186b42ad0, 0x60003419, 6668),
        (0x3cc2934, 0x186b42ad8, 0x6000341d, 6670),
        (0x3cc2965, 0x186b42ac8, 0x60003429, 6676),
        (0x3cc2996, 0x186b42ae8, 0x60003417, 6667))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def review():
    original, installed, asm = ORIGINAL.read_bytes(), INSTALLED.read_bytes(), ASSEMBLY.read_bytes()
    if sha(original) != OLD_SHA or sha(installed) != NEW_SHA:
        raise ValueError('GameAssembly identity differs')
    pe, ip = PE(original), PE(installed)
    rows = parse_assembly(asm, pe, original, 0x3cc2140, 0x3cc2ae7)
    result = []
    for site, address, encoded, index in REFS:
        row = rows[site]
        if not row['text'].startswith('mov r8, qword ptr [rip + ') or \
                pe.base + site + 7 + struct.unpack_from('<i', row['code'], 3)[0] != address:
            raise ValueError(f'delegate reference differs at {site:x}')
        raw = original[pe.offset(address, 8):][:8]
        if int.from_bytes(raw, 'little') != encoded or \
                (encoded >> 29) - 1 != 2 or (encoded >> 1) & 0xfffffff != index:
            raise ValueError(f'encoded method reference differs at {address:x}')
        if installed[ip.offset(address, 8):][:8] != raw:
            raise ValueError(f'installed encoded method reference differs at {address:x}')
        result.append(dict(site=hex(site), storage=hex(address), encoded=hex(encoded),
                           kind=2, index=index))
    # c61cc00's original decoder tests the low bit and dispatches by bits29..31;
    # c61c9f0 uses the low28-bit index. Do not turn these indices into names.
    decoder = ((0x61cc18, 'f6d2'), (0x61cc30, '81e1ffffff0f'),
               (0x61cc36, 'c1e81d'), (0x61cc39, 'ffc8'),
               (0x61c9f6, 'c1e91d'), (0x61c9f9, 'd1ea'),
               (0x61c9fb, '81e2ffffff0f'))
    for address, expected in decoder:
        if original[pe.offset(pe.base + address, len(expected)//2):][:len(expected)//2].hex() != expected:
            raise ValueError(f'metadata decoder bytes differ at {address:x}')
    try:
        pe.offset(0x186e47c80, 8)
    except ExtractionError:
        table_file_backed = False
    else:
        table_file_backed = True
    if table_file_backed:
        raise ValueError('runtime method table unexpectedly file-backed')
    return dict(passed=True, scope='Six encoded delegate references only; runtime method targets unresolved',
                original_sha256=sha(original), installed_sha256=sha(installed),
                assembly_sha256=sha(asm), references=result,
                runtime_method_table_pointer_file_backed=False,
                delegate_target_methods_resolved=False, p7_complete=False)


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    result = review()
    path = OUT / 'verification.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('PASS', path)
