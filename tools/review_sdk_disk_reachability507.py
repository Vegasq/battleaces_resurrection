"""Prove current entry/branch cuts bypass selected direct SDK disk calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED
from tools.review_sdk_file_io503 import EXPECTED, ORIGINAL, PE, review as file_inventory

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / 'local/privacy506-game01'
ENTRY_CUTS = {0x8368b0, 0x836b50, 0x837720, 0x837740, 0x837850}
BRANCH_CUTS = {0x836830: (0x83683a, 0x836884),
               0x837810: (0x837816, 0x83783a)}
DISK_OWNERS = ENTRY_CUTS | set(BRANCH_CUTS)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review() -> dict:
    assert RECIPE_VERSION == 46 and RUNTIME_VALIDATED is False
    inventory = file_inventory()
    assert inventory['passed'] and len(inventory['direct_calls']) == 19
    disk = [row for row in EXPECTED if row[4].startswith(('File.', 'Directory.'))]
    memory = [row for row in EXPECTED if row not in disk]
    assert len(disk) == 15 and len(memory) == 4
    assert {row[1] for row in disk} == DISK_OWNERS
    assert all(row[4].startswith(('StreamReader.', 'StreamWriter.')) for row in memory)
    patches = {patch.rva: patch for patch in COMPONENTS['GameAssembly.dll'].patches}
    original = ORIGINAL.read_bytes()
    pe = PE(original)
    installed = (GAME / 'GameAssembly.dll').read_bytes()
    manifest_path = GAME / '.battleaces-resurrection/patch-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['telemetry']['recipe_version'] == 46
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 108
    assert hashlib.sha256(installed).hexdigest() == manifest['components']['GameAssembly.dll']['installed_sha256']
    assert sha(GAME / '.battleaces-resurrection/original/GameAssembly.dll') == hashlib.sha256(original).hexdigest()
    result = []
    for owner in sorted(DISK_OWNERS):
        calls = [row[0] for row in disk if row[1] == owner]
        assert calls and all(owner < call < pe.function_ends[pe.base + owner] - pe.base for call in calls)
        cut = patches[owner] if owner in ENTRY_CUTS else patches[BRANCH_CUTS[owner][0]]
        assert original[cut.offset:cut.offset + len(cut.guard)] == cut.guard
        assert installed[cut.offset:cut.offset + len(cut.replacement)] == cut.replacement
        assert cut.offset == pe.offset(pe.base + cut.rva, len(cut.guard))
        if owner in ENTRY_CUTS:
            assert cut.rva == owner
            assert cut.replacement in (b'\xc3', b'\x31\xc0\xc3')
            kind, target = 'entry-return', None
        else:
            site, expected_target = BRANCH_CUTS[owner]
            assert cut.rva == site and cut.replacement[0] == 0xe9
            target = site + 5 + struct.unpack_from('<i', cut.replacement, 1)[0]
            assert target == expected_target
            assert owner < site < min(calls) and max(calls) + 5 < target
            # These original prologues fall through to the patched jump.
            prefix = original[pe.offset(pe.base + owner, site - owner):
                              pe.offset(pe.base + owner, site - owner) + site - owner]
            assert prefix == ({0x836830: bytes.fromhex('48895c2408574883ec30'),
                               0x837810: bytes.fromhex('40534883ec30')}[owner])
            kind = 'branch-past-calls'
        result.append(dict(owner=hex(owner), cut=hex(cut.rva), kind=kind,
                           direct_disk_calls=[hex(call) for call in calls],
                           target=hex(target) if target is not None else None))
    return dict(passed=True, recipe=46, original_sha256=hashlib.sha256(original).hexdigest(),
                installed_sha256=hashlib.sha256(installed).hexdigest(),
                manifest_sha256=sha(manifest_path), selected_direct_disk_calls=len(disk),
                in_memory_stream_calls=len(memory), cuts=result,
                scope='normal entry into named SDK methods, selected direct System.IO calls only; indirect/native I/O and wire excluded')


if __name__ == '__main__':
    print(json.dumps(review(), indent=2))
