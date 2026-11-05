"""Static205 scheduler ownership. Does not prove safe scene cancellation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from tools.extract_descriptors import PE, Metadata, checked_input, GAME_ASSEMBLY_SHA256, METADATA_SHA256
from tools.review_analytics_listener import parse_assembly
from tools.review_map_loading import require

ROOTS = {0x32f97f0: 0x32f98be, 0x3303860: 0x3303a06,
         0x3303c30: 0x330401a, 0x330dc50: 0x330dcb1,
         0x330dcc0: 0x330de0c, 0x10110: 0x1017c}
PARTIAL = (0x33003f7, 0x3300548)
METHODS = {0xa8: ('RunCoroutine', 0x32f97f0, ['coroutine']),
           0xd8: ('RunCoroutineInternal', 0x32ffff0,
                  ['coroutine','segment','layer','layerHasValue','tag','handle','prewarm']),
           0xdb: ('KillCoroutines', 0x3303860, ['handle']),
           0xdd: ('KillCoroutinesOnInstance', 0x3303c30, ['handle']),
           0x11f: ('Nullify', 0x330dc50, ['handle']),
           0x120: ('Nullify', 0x330dcc0, ['coindex'])}
ANCHORS = {
    0x32f987c: 'xor r9d, r9d', 0x32f9888: 'xor r8d, r8d',
    0x32f988b: 'mov byte ptr [rsp + 0x38], 0x1',
    0x32f9890: 'mov rdx, rdi', 0x32f989a: 'mov qword ptr [rsp + 0x28], 0x0',
    0x32f98a3: 'mov byte ptr [rsp + 0x20], 0x0',
    0x33003f7: 'movsxd r12, dword ptr [r15 + 0x78]',
    0x3300435: 'mov r8, qword ptr [rsp + 0xe8]',
    0x330043d: 'mov rdx, r12', 0x3300440: 'mov rcx, rbx',
    0x33004c3: 'mov rcx, qword ptr [r15 + 0x100]',
    0x3300482: 'mov rcx, qword ptr [r15 + 0x108]',
    0x3303cda: 'mov rcx, qword ptr [rdi + 0x100]',
    0x330dc80: 'mov rcx, qword ptr [rdi + 0x100]',
    0x330dceb: 'mov rcx, qword ptr [rcx + 0x130]',
    0x330dd10: 'xor r8d, r8d',
    0x330dd13: 'mov rbx, qword ptr [rcx + 8*rbx + 0x20]',
    0x10114: 'mov rax, r8', 0x10123: 'lea r8, [rdx + 0x4]',
    0x10127: 'lea r8, [rcx + 8*r8]', 0x1012b: 'mov qword ptr [r8], rax',
}
EDGES = {0x32f9843:0x32f3a70, 0x32f986e:0x331cfa0, 0x32f98a8:0x32ffff0,
         0x33039e8:0x3303c30, 0x3303d6f:0x3311af0, 0x3303d7c:0x330dc50,
         0x3303d94:0x330d5d0, 0x3303f89:0x3303860,
         0x330dca6:0x330dcc0, 0x330dd18:0x10110, 0x3300443:0x10110}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def review(original, installed, evidence):
    original, installed, evidence = map(Path, (original, installed, evidence))
    data = checked_input(original/'GameAssembly.dll', GAME_ASSEMBLY_SHA256)
    raw_md = checked_input(original/'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat', METADATA_SHA256)
    current = (installed/'GameAssembly.dll').read_bytes()
    pe, md = PE(data), Metadata(raw_md)
    record = md.types[21044]
    require(md.string(record[0]) == 'Timing', 'scheduler identity differs')
    image, = [im for im in md.images if im[2] <= 21044 < im[2]+im[3]]
    methods = md.methods_for_type(record)
    count, table = pe.module(md.string(image[0]), max(m[6]&0xffffff for m in methods))
    found = set()
    for m in methods:
        token = m[6]&0xffffff
        if token not in METHODS:
            continue
        name, rva, args = METHODS[token]
        actual_args = [md.string(struct.unpack_from('<i', raw_md, md.header[22]+i*12)[0])
                       for i in range(m[4],m[4]+m[-1])]
        address, = struct.unpack_from('<Q',data,pe.offset(table+(token-1)*8,8))
        require(md.string(m[0]) == name and actual_args == args and address == pe.base+rva,
                'method overload binding differs')
        found.add(token)
    require(found == set(METHODS), 'method binding missing')
    offsets, = struct.unpack_from('<Q',data,pe.offset(0x1869bcde0+21044*8,8))
    fields = {}
    for i in range(record[18]):
        ni, = struct.unpack_from('<i',raw_md,md.header[24]+(record[8]+i)*12)
        fields[md.string(ni)] = struct.unpack_from('<i',data,pe.offset(offsets+i*4,4))[0]
    for name, offset in {'_nextUpdateProcessSlot':0x78,'_handleToIndex':0x100,
                         '_indexToHandle':0x108,'UpdateProcesses':0x130}.items():
        require(fields.get(name) == offset, 'scheduler field differs')
    rows, bodies = {}, []
    for start,end in list(ROOTS.items())+[PARTIAL]:
        full = start in ROOTS
        if full:
            require(pe.function_ends.get(pe.base+start) == pe.base+end, 'unwind extent differs')
        code_end = 0x330dde8 if start == 0x330dcc0 else end
        raw = (evidence/f'game-{start:x}.asm').read_bytes()
        lines = []
        for line in raw.decode().splitlines():
            match = re.match(r'^([0-9a-f]+):',line)
            if match and int(match[1],16) >= pe.base+code_end:
                continue
            lines.append(line)
        parsed = parse_assembly('\n'.join(lines).encode(),pe,data,start,code_end)
        rows.update(parsed)
        offset = pe.offset(pe.base+start,end-start)
        body = data[offset:offset+end-start]
        require(current[offset:offset+end-start] == body, 'installed bytes differ')
        bodies.append(dict(start=hex(start),end=hex(end),code_end=hex(code_end),full_body=full,
                           instructions=len(parsed),body_sha256=sha(body),assembly_sha256=sha(raw)))
    for address, expected in ANCHORS.items():
        require(rows[address]['text'] == expected, f'semantic anchor differs at {address:x}')
    for address,target in EDGES.items():
        code = rows[address]['code']
        require(len(code)==5 and code[0] in (0xe8,0xe9) and
                address+5+struct.unpack('<i',code[1:])[0]==target, 'direct edge differs')
    dispatch = struct.unpack_from('<9I',data,pe.offset(pe.base+0x330dde8,36))
    require(dispatch == (0x330dceb,0x330dd29,0x330dd60,0x330dd69,0x330dd72,
                         0x330dd7b,0x330dda4,0x330ddad,0x330ddb9), 'Nullify dispatch differs')
    prior = evidence.parent/'replay56-contract01/mec-run-coroutine-internal.asm'
    return dict(passed=True,scope=__doc__,original_sha256=sha(data),metadata_sha256=sha(raw_md),
                installed_sha256=sha(current),bodies=bodies,instructions=sum(b['instructions'] for b in bodies),
                prior_internal_sha256=sha(prior.read_bytes()),scheduler_owner='MEC.Timing.UpdateProcesses',
                tag=None,layer_has_value=False,prewarm=True,scene_cancellation_proved=False,
                callback_suppression_proved=False,runtime_recovery_proved=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original','installed','evidence','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args = parser.parse_args()
    result = review(args.original,args.installed,args.evidence)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2)
        stream.write('\n')
    print(json.dumps({'passed':True,'instructions':result['instructions']}))
