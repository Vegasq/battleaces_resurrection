"""Read-only194 binding of the second native random-state consumer to particles.

Retained PE/unwind/LLVM evidence only. No DLL loading, engine execution or claim
that all uses of the shared RNG/owner are known. Advertising producer stays open.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity
from tools.review_analytics_listener import ORIGINAL_SHA, parse_assembly

ROOTS = {
    0xfd4b10: 0xfd4bbd, 0x2482e0: 0x24841e, 0x2485c0: 0x248700,
    0x24ada0: 0x24af44, 0xd72220: 0xd72789, 0xd66880: 0xd66bcc,
    0xd65c40: 0xd662f1, 0xd5f730: 0xd5f81d, 0xd5fae0: 0xd6006c,
    0x5920b0: 0x5921d1,
}
BINDINGS = {
    8: (0x2482e0, 'UnityEngine.ParticleSystem::get_randomSeed'),
    10: (0x2485c0, 'UnityEngine.ParticleSystem::get_useAutoRandomSeed'),
    28: (0x24ada0, 'UnityEngine.ParticleSystem::Play'),
}
ANCHORS = {
    # Actual registration loop, same indexed pointer pair, explicit826 bound.
    0xfd4b38: 'xor r14d, r14d',
    0xfd4b40: 'mov rsi, qword ptr [r14 + r12 + 0x193b490]',
    0xfd4b51: 'mov rbp, qword ptr [r14 + r12 + 0x193ce60]',
    0xfd4b67: 'mov rdx, rsi', 0xfd4b6a: 'mov rcx, rbp',
    0xfd4b6d: 'call qword ptr [rbx + rax]',
    0xfd4b82: 'mov rdx, rsi', 0xfd4b85: 'mov rcx, rbp',
    0xfd4b91: 'add r14, 0x8', 0xfd4b95: 'cmp r15d, 0x33a',
    # Named public getters and native auto-seed use access the same member pair.
    0x2483d2: 'mov rax, qword ptr [rax + 0x40]', 0x2483de: 'mov eax, dword ptr [rax + 0x30]',
    0x2486b3: 'mov rax, qword ptr [rax + 0x40]', 0x2486bf: 'movzx eax, byte ptr [rax + 0x34]',
    # Play's selected component stays R15 through the relevant dispatch.
    0x24aee4: 'mov rcx, rdi', 0xd7228a: 'mov r15, qword ptr [r9 + 0x8]',
    0xd7268e: 'mov rcx, r15', 0xd66887: 'mov rbx, rcx',
    0xd66976: 'mov rcx, rbx',
    # Conditional auto-seed: four-word global state becomes public randomSeed.
    0xd65c55: 'mov rax, qword ptr [rcx + 0x40]', 0xd65c59: 'mov r14, rcx',
    0xd65c6a: 'cmp byte ptr [rax + 0x34], 0x0',
    0xd65c77: 'mov eax, dword ptr [r8 + 0xc0]', 0xd65c80: 'shl edx, 0xb',
    0xd65c83: 'xor edx, eax', 0xd65c8c: 'mov dword ptr [r8 + 0xc0], eax',
    0xd65c9a: 'mov dword ptr [r8 + 0xc4], eax', 0xd65caf: 'mov dword ptr [r8 + 0xc8], eax',
    0xd65cbd: 'mov dword ptr [r8 + 0xcc], ecx',
    0xd65cc4: 'mov rax, qword ptr [r14 + 0x40]', 0xd65cc8: 'mov dword ptr [rax + 0x30], ecx',
    # Existing second owner constructor fills precisely these sixteen bytes.
    0xd5f743: 'mov rdi, rcx', 0xd5f803: 'lea rcx, [rdi + 0xc0]',
    0xd5f814: 'mov rax, rdi', 0xd5fc36: 'mov rcx, rax',
    # Retained system-random-first branch; no actual getter call is made here.
    0x5920d8: 'test eax, eax',
}
CALLS = {0x24aeea: 0xd72220, 0xd72691: 0xd66880, 0xd66979: 0xd65c40,
         0xd5f80a: 0x5920b0, 0xd5fc39: 0xd5f730, 0x592161: 0x9fb910}
RIP_TARGETS = {0xfd4b31: 0, 0xfd4b88: 0x1d0d5c8,
               0xd65c70: 0x1d0ec98, 0xd5fc45: 0x1d0ec98, 0x5920d2: 0x185afc0}
BRANCHES = {0xd65c6e: 0xd65ccb, 0x5920da: 0x5921c0, 0xfd4b9c: 0xfd4b40}


def require(value, label):
    if not value:
        raise ValueError(label)


def review(original, installed, evidence):
    data, patched = Path(original).read_bytes(), Path(installed).read_bytes()
    require(hashlib.sha256(data).hexdigest() == ORIGINAL_SHA, 'Pinned original required')
    descriptor = describe_unity(data, patched)
    pe, rows, files = PE(data), {}, []
    for start, end in ROOTS.items():
        require(pe.function_ends.get(pe.base + start) == pe.base + end, 'Unwind extent differs')
        raw = (Path(evidence) / f'unity-{start:x}.asm').read_bytes()
        parsed = parse_assembly(raw, pe, data, start, end)
        rows.update(parsed)
        offset = pe.offset(pe.base + start, end - start)
        body = data[offset:offset + end - start]
        require(patched[offset:offset + end - start] == body, 'Named particle/RNG body changed in installed file')
        files.append(dict(start=hex(start), end=hex(end), instructions=len(parsed),
                          assembly_sha256=hashlib.sha256(raw).hexdigest(), body_sha256=hashlib.sha256(body).hexdigest()))
    for rva, text in ANCHORS.items():
        require(rows[rva]['text'] == text, f'Semantic anchor differs at {rva:x}')
    for rva, dest in CALLS.items():
        code = rows[rva]['code']
        require(len(code) == 5 and code[0] == 0xe8 and
                rva + 5 + struct.unpack_from('<i', code, 1)[0] == dest, f'Direct edge differs at {rva:x}')
    for rva, dest in RIP_TARGETS.items():
        code = rows[rva]['code']
        require(rva + len(code) + struct.unpack_from('<i', code, len(code) - 4)[0] == dest,
                f'RIP target differs at {rva:x}')
    for rva, dest in BRANCHES.items():
        code = rows[rva]['code']
        displacement = struct.unpack_from('<b' if len(code) == 2 else '<i', code, 1 if len(code) == 2 else 2)[0]
        require(rva + len(code) + displacement == dest, f'Branch differs at {rva:x}')
    pairs = []
    for index, (function, name) in BINDINGS.items():
        fslot, nslot = 0x193b490 + index * 8, 0x193ce60 + index * 8
        f = struct.unpack_from('<Q', data, pe.offset(pe.base + fslot, 8))[0]
        n = struct.unpack_from('<Q', data, pe.offset(pe.base + nslot, 8))[0]
        require(f == pe.base + function, 'Registered function differs')
        offset = pe.offset(n, len(name) + 1)
        require(data[offset:offset + len(name) + 1] == name.encode() + b'\0', 'Registered name differs')
        for off, size in ((pe.offset(pe.base + fslot, 8), 8), (pe.offset(pe.base + nslot, 8), 8), (offset, len(name) + 1)):
            require(patched[off:off + size] == data[off:off + size], 'Installed registration changed')
        pairs.append(dict(index=index, function=hex(function), name=name, name_slot=hex(nslot), function_slot=hex(fslot)))
    return dict(passed=True, scope=__doc__, original_sha256=ORIGINAL_SHA,
                installed_sha256=hashlib.sha256(patched).hexdigest(), installed_descriptor=descriptor,
                roots=files, decoded_instructions=len(rows), semantic_anchors=len(ANCHORS),
                direct_edges=len(CALLS), rip_bindings=len(RIP_TARGETS), branches=len(BRANCHES), bindings=pairs,
                particle_auto_seed_consumer_bound=True, exact_cpp_type_proved=False,
                all_owner_consumers_proved=False, advertising_producer_resolved=False, full_privacy_qualified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'installed', 'evidence', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    report = review(args.original, args.installed, args.evidence)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: report[key] for key in ('passed', 'decoded_instructions', 'semantic_anchors', 'particle_auto_seed_consumer_bound')}))
