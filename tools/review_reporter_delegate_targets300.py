"""Resolve the six reporter AddOnSendError delegate indices through pinned IL2CPP tables."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import Metadata, PE

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent.parent / 'BattleAcesBeta_untouched/GameAssembly.dll'
INSTALLED = ROOT / 'local/privacy291-runtime01/game/GameAssembly.dll'
METADATA = ROOT.parent.parent / 'BattleAcesBeta_untouched/Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat'
OUT = ROOT / 'local/privacy300-reporter-registration01'
OLD_SHA = 'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758'
NEW_SHA = 'c6e4480475e515e71a46e9579ee48d4db1a7f22062db5282d73c314a204d6b4e'
MD_SHA = 'b760be9190309b14174cd272e1f83b730181b299bc7a0cdca66985c69dcdc57d'
EXPECTED = ((0x6b42af0, 6683, '<Subs>b__20_0', 0x6000562, 0x3cc6930, 0x3cc6a63, False),
            (0x6b42b08, 6684, '<Subs>b__20_1', 0x6000563, 0x3cc6a70, 0x3cc6b9a, False),
            (0x6b42ad0, 6668, 'CleanBugEvents', 0x6000553, 0x3cc3700, 0x3cc3c8c, False),
            (0x6b42ad8, 6670, 'AssignCustomGroupingHash', 0x6000555, 0x3cc4aa0, 0x3cc53a1, False),
            (0x6b42ac8, 6676, 'AddUserConfigToReport', 0x600055b, 0x3cc5df0, 0x3cc5ed4, True),
            (0x6b42ae8, 6667, 'FlagFirstEvent', 0x6000552, 0x3cc3600, 0x3cc36f4, True))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def body(pe, raw, start, end):
    return raw[pe.offset(pe.base + start, end - start):][:end - start]


def review():
    old, new, md_raw = ORIGINAL.read_bytes(), INSTALLED.read_bytes(), METADATA.read_bytes()
    require((sha(old), sha(new), sha(md_raw)) == (OLD_SHA, NEW_SHA, MD_SHA),
            'pinned original/installed/metadata identity differs')
    pe, ip, md = PE(old), PE(new), Metadata(md_raw)
    # c622050: metadata header+0x30 is the 36-byte method-definition table;
    # its dword+4 supplies declaringType for a kind2 index.
    for address, expected in ((0x622099, '488b05205b8206'),
                              (0x6220a0, '48634830'),
                              (0x6220a4, '488d14db'),
                              (0x6220af, '8b4c9104')):
        length = len(expected)//2
        require(body(pe, old, address, address + length).hex() == expected,
                f'kind2 method-definition lookup differs at {address:x}')
    count, table = pe.module('RGame.dll', 1)
    results = []
    for slot, index, name, token, rva, end, guarded in EXPECTED:
        encoded = struct.unpack_from('<Q', old, pe.offset(pe.base + slot, 8))[0]
        require(encoded & 1 and (encoded >> 29) - 1 == 2 and
                (encoded >> 1) & 0xfffffff == index,
                f'encoded kind2 index differs at {slot:x}')
        require(struct.unpack_from('<Q', new, ip.offset(ip.base + slot, 8))[0] == encoded,
                f'installed delegate slot differs at {slot:x}')
        method = md.methods[index]
        typ = md.types[method[1]]
        image = [item for item in md.images if item[2] <= method[1] < item[2] + item[3]]
        require(len(image) == 1 and md.string(image[0][0]) == 'RGame.dll' and
                md.string(method[0]) == name and method[6] == token and
                method[-1] == 1 and method[2] == 38515,
                f'metadata method contract differs at {index}')
        method_index = (token & 0xffffff) - 1
        require(0 <= method_index < count and
                struct.unpack_from('<Q', old, pe.offset(table + method_index*8, 8))[0] == pe.base + rva and
                pe.function_ends.get(pe.base + rva) == pe.base + end,
                f'codegen method pointer/unwind differs at {index}')
        before, after = body(pe, old, rva, end), body(ip, new, rva, end)
        require(after == (b'\x31\xc0\xc3' + before[3:] if guarded else before),
                f'installed method body differs at {rva:x}')
        results.append(dict(index=index, name=name, namespace=md.string(typ[1]),
                            type=md.string(typ[0]), token=hex(token), rva=hex(rva),
                            return_type_index=method[2], parameter_count=method[-1],
                            installed_false_guard=guarded))
    return dict(passed=True, scope='Six named Subs AddOnSendError targets and installed entry bytes; indirect callers/runtime delivery unresolved',
                original_sha256=sha(old), installed_sha256=sha(new), metadata_sha256=sha(md_raw),
                methods=results, original_return_type_equal=True,
                guarded_count=sum(row['installed_false_guard'] for row in results),
                unguarded_count=sum(not row['installed_false_guard'] for row in results),
                p7_complete=False)


if __name__ == '__main__':
    result = review()
    output = OUT / 'targets.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    print('PASS', output)
