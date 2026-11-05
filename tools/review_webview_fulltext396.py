"""Discover direct rel32 calls/jumps to Vuplex-only methods in PE executable code.

Raw opcode hits are candidates until decoded at instruction boundaries. This
extends the earlier RGame-method-body inventory without claiming indirect calls.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import Metadata, PE

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent.parent / 'BattleAcesBeta_untouched/GameAssembly.dll'
METADATA = ROOT.parent.parent / 'BattleAcesBeta_untouched/Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat'
OUT = ROOT / 'local/privacy396-webview-fulltext01'
ORIGINAL_SHA = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
METADATA_SHA = 'b760be9190309b14174cd272e1f83b730181b299bc7a0cdca66985c69dcdc57d'


def review() -> dict:
    raw, md_raw = ORIGINAL.read_bytes(), METADATA.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    assert hashlib.sha256(md_raw).hexdigest() == METADATA_SHA
    pe, md = PE(raw), Metadata(md_raw)
    ownership: dict[int, set[str]] = {}
    names: dict[int, list[str]] = {}
    for image in md.images:
        module = md.string(image[0])
        if module not in ('RGame.dll', 'Vuplex.WebView.dll'):
            continue
        selected = md.types[image[2]:image[2] + image[3]]
        methods = [method for typ in selected if typ[16]
                   for method in md.methods_for_type(typ)]
        count, table = pe.module(module, max(method[6] & 0xffffff for method in methods))
        for typ in selected:
            for method in md.methods_for_type(typ) if typ[16] else ():
                slot = (method[6] & 0xffffff) - 1
                assert 0 <= slot < count
                address = struct.unpack_from('<Q', raw, pe.offset(table + slot * 8, 8))[0]
                if address:
                    ownership.setdefault(address, set()).add(module)
                    names.setdefault(address, []).append(
                        f'{md.string(typ[1])}.{md.string(typ[0])}::{md.string(method[0])}')
    targets = {address for address, owners in ownership.items()
               if 'Vuplex.WebView.dll' in owners and 'RGame.dll' not in owners}
    executable = [section for section in pe.sections
                  if section[0] - pe.base in (0x1000, 0x6af000)]
    assert len(executable) == 2
    roots = sorted(pe.function_ends)
    candidates = []
    for start, size, offset in executable:
        assert size > 0 and offset + size <= len(raw)
        code = memoryview(raw)[offset:offset + size]
        for index in range(size - 5):
            opcode = code[index]
            if opcode not in (0xe8, 0xe9):
                continue
            address = start + index
            target = address + 5 + struct.unpack_from('<i', code, index + 1)[0]
            if target not in targets:
                continue
            position = bisect.bisect_right(roots, address) - 1
            owner = roots[position] if position >= 0 and address < pe.function_ends[roots[position]] else None
            candidates.append(dict(site=hex(address - pe.base), opcode=hex(opcode),
                                   target=hex(target - pe.base), target_names=names[target],
                                   owner=hex(owner - pe.base) if owner is not None else None,
                                   owner_names=names.get(owner, []) if owner is not None else [],
                                   owner_is_rgame=owner in ownership and 'RGame.dll' in ownership[owner]))
    result = dict(original_sha256=ORIGINAL_SHA, metadata_sha256=METADATA_SHA,
                  executable_sections=[dict(start=hex(start - pe.base), size=size)
                                       for start, size, _ in executable],
                  vuplex_only_targets=len(targets), raw_candidates=candidates,
                  candidate_count=len(candidates), instruction_checked=False,
                  indirect_routes_excluded=False)
    OUT.mkdir(exist_ok=True)
    (OUT / 'discovery.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps({key: result[key] for key in ('executable_sections', 'vuplex_only_targets', 'candidate_count')}))
