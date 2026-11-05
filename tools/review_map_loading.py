"""Static204 original map-loader ownership boundaries; no native execution.

Does not prove cancellation safety or runtime recovery. The iterator jump table
is data, not instructions. All claims are pinned to original bytes and metadata.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from tools.extract_descriptors import PE, Metadata, checked_input, GAME_ASSEMBLY_SHA256, METADATA_SHA256
from tools.review_analytics_listener import parse_assembly

ROOTS = {0x3dbb340: 0x3dbb3d6, 0x3dbb660: 0x3dbb7bc,
         0x3dbcf80: 0x3dbd9ac, 0x3dbb8c0: 0x3dbbcf3}
JUMP_TABLE = (0x3dbd15b, 0x3dbd213, 0x3dbd3f2, 0x3dbd579, 0x3dbd670, 0x3dbd86d, 0x3dbd8ee)
ANCHORS = {
    0x3dbb6b2: 'mov qword ptr [rax + 0x18], rbx',
    0x3dbb70f: 'mov qword ptr [r9 + 0x20], rdi',
    0x3dbb75f: 'mov qword ptr [r9 + 0x30], rsi',
    0x3dbd12e: 'movsxd rax, dword ptr [rdi + 0x10]',
    0x3dbd14e: 'mov eax, dword ptr [r12 + 4*rax + 0x3dbd990]',
    0x3dbd223: 'cmp byte ptr [rbx + 0x70], 0x0',
    0x3dbd230: 'mov dword ptr [rdi + 0x10], 0x1',
    0x3dbd382: 'mov byte ptr [rbx + 0x70], 0x1',
    0x3dbd3e1: 'movups xmmword ptr [rcx], xmm0',
    0x3dbd662: 'mov dword ptr [rdi + 0x10], 0x3',
    0x3dbd698: 'mov dword ptr [rdi + 0x10], 0x4',
    0x3dbd85f: 'mov dword ptr [rdi + 0x10], 0x5',
    0x3dbd8e0: 'mov dword ptr [rdi + 0x10], 0x6',
    0x3dbd918: 'mov rax, qword ptr [rdi + 0x30]',
    0x3dbd929: 'call qword ptr [rax + 0x18]',
    0x3dbd931: 'mov byte ptr [rbx + 0x70], 0x0',
    0x3dbb37f: 'mov rdi, qword ptr [rbx + 0x20]',
    0x3dbb3a4: 'cmp dword ptr [rdi + 0x38], eax',
    0x3dbb3bb: 'sete al',
}
EDGES = {0x3dbd2de: 0x3b21920, 0x3dbd3d1: 0x3b217e0,
         0x3dbd596: 0x78c30, 0x3dbb3b4: 0x78c30,
         0x3dbd5a9: 0x4cf3160, 0x3dbd5b8: 0x4cf30c0,
         0x3dbd688: 0x5083200, 0x3dbd855: 0x330ff90,
         0x3dbd8d6: 0x3312920, 0x3dbd368: 0x3312920}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def review(original, installed, evidence):
    original, installed, evidence = map(Path, (original, installed, evidence))
    data = checked_input(original/'GameAssembly.dll', GAME_ASSEMBLY_SHA256)
    metadata = checked_input(original/'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat', METADATA_SHA256)
    current = (installed/'GameAssembly.dll').read_bytes()
    pe, md = PE(data), Metadata(metadata)
    methods = {1563: {'MoveNext': 0x3dbcf80, 'System.IDisposable.Dispose': 0x6af170},
               1564: {'get_IsLoading': 0x3dbb340, 'LoadCoroutine': 0x3dbb660,
                      'Simulation_SimulationShutdown': 0x3dbb8c0}}
    fields = {1563: {'<>1__state': 0x10, '<>4__this': 0x18, 'mapAddress': 0x20,
                     'complete': 0x30, '<unloadAsyncTask>5__2': 0x38, '<activationOp>5__3': 0x50},
              1564: {'_loadingHandle': 0x20, '_loadedScene': 0x40, '_lastLoadedMapAsset': 0x68,
                     '_existingLoadRunning': 0x70, '_minimumLoadingScreenTime': 0x74,
                     '_minimumProvingGroundLoadingTime': 0x78}}
    identities = []
    for index, expected in methods.items():
        record = md.types[index]
        name = md.string(record[0])
        require(name == ('<LoadCoroutine>d__18' if index == 1563 else 'MapManager'), 'type identity differs')
        image, = [image for image in md.images if image[2] <= index < image[2] + image[3]]
        selected = {md.string(m[0]): m for m in md.methods_for_type(record) if md.string(m[0]) in expected}
        require(set(selected) == set(expected), 'method inventory differs')
        count, table = pe.module(md.string(image[0]), max(m[6] & 0xffffff for m in selected.values()))
        for method_name, row in selected.items():
            token = (row[6] & 0xffffff) - 1
            require(0 <= token < count, 'method token out of range')
            address, = struct.unpack_from('<Q', data, pe.offset(table + token*8, 8))
            require(address == pe.base + expected[method_name], 'native method binding differs')
        offsets, = struct.unpack_from('<Q', data, pe.offset(0x1869bcde0 + index*8, 8))
        actual = {}
        for field in range(record[18]):
            name_index, _, _ = struct.unpack_from('<3i', metadata, md.header[24] + (record[8]+field)*12)
            actual[md.string(name_index)] = struct.unpack_from('<i', data, pe.offset(offsets + field*4, 4))[0]
        require(all(actual.get(k) == v for k, v in fields[index].items()), 'field layout differs')
        identities.append(dict(type=name, methods={k:hex(v) for k,v in expected.items()}, fields=fields[index]))
    rows, bodies = {}, []
    for start, end in ROOTS.items():
        require(pe.function_ends.get(pe.base+start) == pe.base+end, 'unwind extent differs')
        raw = (evidence/f'game-{start:x}.asm').read_bytes()
        code_end = 0x3dbd990 if start == 0x3dbcf80 else end
        lines = []
        for line in raw.decode().splitlines():
            address = re.match(r'^([0-9a-f]+):', line)
            if address and int(address[1],16) >= pe.base + code_end:
                continue
            lines.append(line)
        parsed = parse_assembly('\n'.join(lines).encode(), pe, data, start, code_end)
        rows.update(parsed)
        offset = pe.offset(pe.base+start, end-start)
        require(data[offset:offset+end-start] == current[offset:offset+end-start], 'installed body differs')
        bodies.append(dict(start=hex(start), end=hex(end), code_end=hex(code_end),
            instructions=len(parsed), body_sha256=digest(data[offset:offset+end-start]), assembly_sha256=digest(raw)))
    for address, expected in ANCHORS.items():
        require(rows[address]['text'] == expected, f'semantic anchor differs at {address:x}')
    for address, target in EDGES.items():
        code = rows[address]['code']
        require(len(code) == 5 and code[0] == 0xe8 and address + 5 + struct.unpack('<i',code[1:])[0] == target,
                'direct edge differs')
    require(struct.unpack_from('<7I',data,pe.offset(pe.base+0x3dbd990,28)) == JUMP_TABLE, 'state dispatch differs')
    offset = pe.offset(pe.base+0x6af170,3)
    require(pe.base+0x6af170 not in pe.function_ends and data[offset:offset+3] == b'\xc2\0\0' and
            current[offset:offset+3] == data[offset:offset+3], 'Dispose is not the unchanged empty leaf')
    return dict(passed=True, scope=__doc__, original_sha256=digest(data), metadata_sha256=digest(metadata),
                installed_sha256=digest(current), types=identities, bodies=bodies,
                instructions=sum(b['instructions'] for b in bodies), jump_table=[hex(v) for v in JUMP_TABLE],
                dispose=dict(rva='0x6af170', bytes='c20000', operation='ret 0'),
                cancellation_proved=False, runtime_recovery_proved=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original','installed','evidence','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    report = review(args.original,args.installed,args.evidence)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report,stream,indent=2)
        stream.write('\n')
    print(json.dumps(dict(passed=True,instructions=report['instructions'],bodies=len(report['bodies']))))
