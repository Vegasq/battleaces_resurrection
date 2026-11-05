"""Verify the shipped Tutorial01 completion path and current BI guard."""

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

from tools.extract_descriptors import Metadata, PE


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path(os.environ.get('BA_ORIGINAL_GAME_ROOT', ROOT / 'local/pristine-game'))
CURRENT = ROOT / 'local/privacy301-runtime01/game/GameAssembly.dll'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target(pe, rva):
    address = pe.base + rva
    offset = pe.offset(address, 5)
    opcode = pe.data[offset]
    assert opcode in (0xE8, 0xE9), (hex(rva), hex(opcode))
    return opcode, rva + 5 + struct.unpack_from('<i', pe.data, offset + 1)[0]


def main(output):
    metadata_path = ORIGINAL / 'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat'
    original_path = ORIGINAL / 'GameAssembly.dll'
    md = Metadata(metadata_path.read_bytes())
    original = PE(original_path.read_bytes())
    current = PE(CURRENT.read_bytes())
    assert original.base == current.base == 0x180000000
    assert sha256(original_path) == 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
    assert md.string(md.types[1651][0]) == 'RGameTutorial01State'
    fields = [md.string(struct.unpack_from('<i', md.data, md.header[24] + (md.types[1651][8] + i) * 12)[0])
              for i in range(md.types[1651][18])]
    assert fields[3:7] == ['_postMatchUIComplete', '_tutorialSuccessfullyCompleted',
                           '_tutorialCompleteMessageSent', '_forceRestartFTUE']
    edges = {
        'TransitionIn_to_BI': (0x3DEF687, 0x3E32A10, 0xE8),
        'Update_to_MarkTutorial01Complete': (0x3DF01F3, 0x3E355A0, 0xE8),
        'MarkTutorial01Complete_to_ReconcileProgressionRequest': (0x3E35756, 0x3E3BAF0, 0xE9),
    }
    found = {}
    for label, (site, expected, opcode) in edges.items():
        observed = target(original, site)
        assert observed == (opcode, expected), (label, observed)
        assert target(current, site) == observed, label
        found[label] = {'site_rva': hex(site), 'target_rva': hex(expected), 'opcode': hex(opcode)}
    bi_start = current.data[current.offset(current.base + 0x3E32A10, 1)]
    assert bi_start == 0xC3
    for rva in (0x3E355A0, 0x3E3BAF0):
        original_start = original.data[original.offset(original.base + rva, 16):original.offset(original.base + rva, 16) + 16]
        current_start = current.data[current.offset(current.base + rva, 16):current.offset(current.base + rva, 16) + 16]
        assert current_start == original_start, hex(rva)
    result = {
        'passed': True,
        'scope': 'Original/current recipe38 Tutorial01 BI entry guard versus completion progression call sites and first 16 bytes; no gameplay completion or wire proof',
        'original_sha256': sha256(original_path),
        'metadata_sha256': sha256(metadata_path),
        'current_sha256': sha256(CURRENT),
        'tutorial_fields': fields,
        'edges': found,
        'current_bi_entry_byte': hex(bi_start),
        'progression_entries_unchanged_16_bytes': True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'output': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args().output)
