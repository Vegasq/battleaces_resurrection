"""Verify the six original reporter Subs registration calls and installed entry cut."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import Metadata, PE
from tools.review_analytics_listener import parse_assembly

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent.parent / 'BattleAcesBeta_untouched/GameAssembly.dll'
INSTALLED = ROOT / 'local/privacy291-runtime01/game/GameAssembly.dll'
ASSEMBLY = ROOT / 'local/privacy279-game-3cc2140.asm'
OUT = ROOT / 'local/privacy297-reporter-subs01'
OLD_SHA = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
NEW_SHA = 'c6e4480475e515e71a46e9579ee48d4db1a7f22062db5282d73c314a204d6b4e'
METADATA = ROOT.parent.parent / 'BattleAcesBeta_untouched/Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat'
METADATA_SHA = 'b760be9190309b14174cd272e1f83b730181b299bc7a0cdca66985c69dcdc57d'
START, END = 0x3cc2140, 0x3cc2ae7


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def segment(pe, raw):
    return raw[pe.offset(pe.base + START, END - START):][:END - START]


def review():
    old, new, asm, metadata = (ORIGINAL.read_bytes(), INSTALLED.read_bytes(),
                               ASSEMBLY.read_bytes(), METADATA.read_bytes())
    if sha(old) != OLD_SHA or sha(new) != NEW_SHA or sha(metadata) != METADATA_SHA:
        raise ValueError('GameAssembly/metadata identity differs')
    pe, ip = PE(old), PE(new)
    if pe.function_ends.get(pe.base + START) != pe.base + END:
        raise ValueError('Subs unwind extent differs')
    rows = parse_assembly(asm, pe, old, START, END)
    calls = (0x3cc2802, 0x3cc28f2, 0x3cc2923, 0x3cc2954, 0x3cc2985, 0x3cc29b6)
    delegates = (0x3cc2780, 0x3cc2874, 0x3cc2915, 0x3cc2946,
                 0x3cc2977, 0x3cc29a8)
    for address in calls:
        if rows[address]['text'].split(' <', 1)[0] != 'call 0x18081b2b0':
            raise ValueError(f'registration call differs at {address:x}')
    for address in delegates:
        if rows[address]['text'].split(' <', 1)[0] != 'call 0x18179aa50':
            raise ValueError(f'delegate construction differs at {address:x}')
    if rows[0x3cc2419]['text'] != 'mov rdi, rax':
        raise ValueError('Configuration receiver binding differs')
    direct_exclusions = ('0x183cc30f0', '0x183cc3600',
                         '0x183cc5440', '0x183cc5df0')
    if any(rows[address]['text'].startswith('call ') and
           any(target in rows[address]['text'] for target in direct_exclusions)
           for address in rows):
        raise ValueError('unexpected direct reporter callback call in Subs')
    if rows[0x3cc2793]['text'] != 'mov qword ptr [rcx + 0x8], rsi' or \
            rows[0x3cc2887]['text'] != 'mov qword ptr [rcx + 0x10], rsi':
        raise ValueError('cached delegate slots differ')
    before, after = segment(pe, old), segment(ip, new)
    if after != b'\xc3' + before[1:]:
        raise ValueError('installed Subs entry guard/tail differs')
    md = Metadata(metadata)
    name = 'BugsnagUnity.Windows.dll'
    image = [item for item in md.images if md.string(item[0]) == name]
    if len(image) != 1:
        raise ValueError('BugsnagUnity image ambiguous')
    matches = []
    for index in range(image[0][2], image[0][2] + image[0][3]):
        record = md.types[index]
        if record[9] < 0:
            continue
        for method in md.methods_for_type(record):
            if method[6] == 0x60000e3:
                matches.append((md.string(record[1]), md.string(record[0]),
                                md.string(method[0])))
    if matches != [('BugsnagUnity', 'Configuration', 'AddOnSendError')]:
        raise ValueError('helper metadata identity differs')
    count, table = pe.module(name, 227)
    if count < 227 or int.from_bytes(old[pe.offset(table + 226*8, 8):][:8], 'little') != pe.base + 0x81b2b0:
        raise ValueError('helper method pointer differs')
    # Search every mapped GameAssembly section for the exact rel32 direct-call
    # encoding. Then bind every candidate to a decoded instruction in Subs.
    direct_sites = []
    target = pe.base + 0x81b2b0
    for base, size, file_offset in pe.sections:
        for offset in range(file_offset, min(file_offset + size, len(old)) - 4):
            if old[offset] != 0xe8:
                continue
            address = base + offset - file_offset
            if address + 5 + struct.unpack_from('<i', old, offset + 1)[0] == target:
                direct_sites.append(address - pe.base)
    if tuple(direct_sites) != calls:
        raise ValueError('AddOnSendError direct-call candidate inventory differs')
    return dict(passed=True, scope='Six original calls from Subs only; no indirect/other registration closure',
                original_sha256=sha(old), installed_sha256=sha(new),
                metadata_sha256=sha(metadata), assembly_sha256=sha(asm),
                helper='BugsnagUnity.Configuration.AddOnSendError',
                helper_method_token='0x60000e3', decoded_instructions=len(rows),
                all_mapped_section_direct_e8_sites=[hex(x) for x in direct_sites],
                registration_calls=[hex(x) for x in calls],
                delegate_constructors=[hex(x) for x in delegates],
                installed_subs_entry_ret=True, other_callers_excluded=False,
                reporter_enabled_caller_values_resolved=False, p7_complete=False)


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    result = review()
    output = OUT / 'verification.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('PASS', output)
