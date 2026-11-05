"""Static197 binding of retained Main190 to the managed identity-token event.

Consumes pinned original files and retained disassembly without executing them.
No advertising-source,subscriber-absence or runtime-coverage claim is implied.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import PE, Metadata, checked_input, GAME_ASSEMBLY_SHA256, METADATA_SHA256
from tools.review_analytics_listener import parse_assembly, ORIGINAL_SHA
from tools.frida_ads_caller import describe_unity

ROOTS = {0xc308c0: 0xc3093a, 0x770b70: 0x770c1c, 0x778be0: 0x778c62,
         0x819490: 0x81956a, 0x80bc90: 0x80bd80, 0x818db0: 0x819486,
         0x76dd70: 0x76de82, 0x772f90: 0x77342f, 0x77fbb0: 0x781e79,
         0xa03030: 0xa032c7}
ANCHORS = {
    0xc308c9: 'mov rbx, rcx', 0xc308d1: 'cmp qword ptr [rax + 0x8], 0x0',
    0xc308d8: 'add rbx, 0x190', 0xc308e9: 'mov rdx, qword ptr [rax + 0x8]',
    0xc308e4: 'lea rcx, [rsp + 0x30]', 0xc3091d: 'mov qword ptr [rsp + 0x20], rbx',
    0xc30913: 'lea rdx, [rsp + 0x20]', 0xc30918: 'lea rcx, [rsp + 0x30]',
    0x818e41: 'mov r9, r14', 0x818e44: 'mov r8, rsi',
    0x818e57: 'mov r9, r14', 0x818e61: 'mov r8, rsi',
    0x818e7a: 'mov rdx, qword ptr [rbp + 0x6f]',
    0x818e99: 'mov rax, qword ptr [rbp + 0x67]',
    0x818f55: 'mov qword ptr [rcx + 0x8], rax',
    0x76dd80: 'mov r14, r8', 0x76dd83: 'mov rbx, rdx',
    0x76dddc: 'mov r8, r14', 0x76dddf: 'sub r8, rax',
    0x76dde2: 'movzx edx, byte ptr [rax]', 0x76dde5: 'movzx ecx, byte ptr [rax + r8]',
    0x76de48: 'mov qword ptr [rsi], rdi',
    0x770c01: 'mov qword ptr [rdi + 0xf8], rbx',
    0x778be6: 'mov rax, qword ptr [rdx]', 0x778bec: 'mov edx, dword ptr [rdx + 0x8]',
    0x778c28: 'movsxd rax, dword ptr [rbx + 0xf0]',
    0x778c3a: 'lea rdx, [rbx + 8*rax]',
    0x778c4b: 'mov dword ptr [rbx + 4*rax + 0xc0], 0x4',
    0x80bcfc: 'mov rbx, qword ptr [rsi + 0xf8]',
    0x80bd13: 'lea r8, [rsi + 0x60]', 0x80bd1f: 'mov rcx, rbx', 0x80bd22: 'call rax',
}
CALLS = {0xc308cc: 0x819490, 0xc308df: 0x819490, 0xc308ed: 0x770b70,
         0xc30922: 0x778be0, 0xc3092c: 0x80bc90, 0x819503: 0x818db0,
         0x818e75: 0x772f90, 0x818e94: 0x76dd70}
LITERALS = {0x19b32f8: 'AnalyticsSessionInfo', 0x19b3310: 'UnityEngine.Analytics',
            0x192e7f0: 'UnityEngine.UnityAnalyticsModule.dll', 0x19b3118: 'CallIdentityTokenChanged'}
# literal selection, resolver call, result publication, runtime export name
EXPORTS = [(0x780259, 0x19a9390, 0x780265, 0x1d0d988, 'il2cpp_class_get_methods'),
           (0x781001, 0x19ab3f0, 0x78100d, 0x1d0d8a0, 'il2cpp_method_get_name'),
           (0x78149b, 0x19abf08, 0x7814a7, 0x1d0d8e0, 'il2cpp_runtime_invoke'),
           (0x7815f1, 0x19abc20, 0x7815fd, 0x1d0d6a8, 'il2cpp_string_new_len')]


def require(value, message):
    if not value:
        raise ValueError(message)


def timing_import(pe):
    data = pe.data
    def word(fmt, offset):
        return struct.unpack_from(fmt, data, offset)[0]
    def name(rva):
        offset = pe.offset(pe.base + rva)
        return data[offset:data.index(b'\0', offset)].decode('ascii')
    header = word('<I', 60)
    directory, size = struct.unpack_from('<II', data, header + 24 + 112 + 8)
    for index in range(size // 20):
        entry = pe.offset(pe.base + directory + index * 20, 20)
        lookup, _, _, dll, iat = struct.unpack_from('<5I', data, entry)
        if not any((lookup, dll, iat)):
            break
        if iat <= 0x185a678 and (0x185a678 - iat) % 8 == 0:
            slot = (0x185a678 - iat) // 8
            for n in range(slot + 1):
                value = word('<Q', pe.offset(pe.base + (lookup or iat) + n * 8, 8))
                if not value:
                    break
                if n == slot:
                    require(not value >> 63, 'Named timer import required')
                    result = dict(dll=name(dll), name=name(value + 2), iat='0x185a678')
                    require(result['dll'].lower() == 'kernel32.dll' and result['name'] == 'QueryPerformanceFrequency',
                            'Timing import differs')
                    return result
    raise ValueError('Timing import absent')


def review(original, installed, evidence):
    original, installed, evidence = map(Path, (original, installed, evidence))
    data = checked_input(original / 'UnityPlayer.dll', ORIGINAL_SHA)
    patched = (installed / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(data, patched)
    pe = PE(data)
    rows, files = {}, []
    for start, end in ROOTS.items():
        require(pe.function_ends[pe.base + start] == pe.base + end, 'Unwind extent differs')
        path = evidence / f'unity-{start:x}.asm'
        parsed = parse_assembly(path.read_bytes(), pe, data, start, end)
        rows.update(parsed)
        offset = pe.offset(pe.base + start, end - start)
        require(data[offset:offset + end - start] == patched[offset:offset + end - start], 'Reviewed body changed')
        files.append(dict(path=path.name, start=hex(start), end=hex(end), instructions=len(parsed),
                          assembly_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    for rva, expected in ANCHORS.items():
        require(rows[rva]['text'] == expected, f'Anchor differs: {rva:x}')
    require(rows[0xa03201]['text'] == 'lea rcx, [rsi + 0x1498]', 'Timer output receiver differs')
    code = rows[0xa03216]['code']
    require(code[:2] == b'\xff\x15' and len(code) == 6 and
            0xa0321c + struct.unpack('<i', code[2:])[0] == 0x185a678, 'Timer import call differs')
    timer = timing_import(pe)
    for rva, target in CALLS.items():
        code = rows[rva]['code']
        require(len(code) == 5 and code[0] == 0xe8 and rva + 5 + struct.unpack('<i', code[1:])[0] == target,
                f'Call differs: {rva:x}')

    def rip(rva, target):
        code = rows[rva]['code']
        require(len(code) == 7 and code[2] & 0xc7 == 5 and
                rva + 7 + struct.unpack('<i', code[3:])[0] == target, f'RIP binding differs: {rva:x}')

    for rva, target in ((0x818e2c, 0x19b32f8), (0x818e3a, 0x19b3310),
                        (0x818e5a, 0x192e7f0), (0x818e89, 0x19b3118),
                        (0x818f41, 0x1cff698), (0x81954c, 0x1cff698),
                        (0x778bfd, 0x1d0d6a8), (0x80bd0c, 0x1d0d8e0),
                        (0x76dda5, 0x1d0d988), (0x76ddd0, 0x1d0d8a0)):
        rip(rva, target)
    names = dict(LITERALS)
    for lea, literal, store, cell, name in EXPORTS:
        rip(lea, literal)
        rip(store, cell)
        code = rows[lea + 7]['code']
        require(code == b'\xe8' + struct.pack('<i', 0x6b31c0 - (lea + 12)), 'Export resolver differs')
        names[literal] = name
    for address, name in names.items():
        expected = name.encode() + b'\0'
        offset = pe.offset(pe.base + address, len(expected))
        require(data[offset:offset + len(expected)] == expected, 'Bound name differs')
    gd = checked_input(original / 'GameAssembly.dll', GAME_ASSEMBLY_SHA256)
    meta = Metadata(checked_input(original / 'Battle Aces_Data/il2cpp_data/Metadata/global-metadata.dat', METADATA_SHA256))
    gp = PE(gd)
    matches = [(index, t) for index, t in enumerate(meta.types)
               if (meta.string(t[1]), meta.string(t[0])) == ('UnityEngine.Analytics', 'AnalyticsSessionInfo')]
    require(len(matches) == 1, 'Managed owner ambiguous')
    index, owner = matches[0]
    method, = [m for m in meta.methods_for_type(owner) if meta.string(m[0]) == 'CallIdentityTokenChanged']
    image, = [im for im in meta.images if im[2] <= index < im[2] + im[3]]
    require(meta.string(image[0]) == LITERALS[0x192e7f0] and method[6] == 0x06000008, 'Managed module/token differs')
    _, table = gp.module(meta.string(image[0]), 8)
    address = struct.unpack_from('<Q', gd, gp.offset(table + 7 * 8, 8))[0]
    require(address == gp.base + 0x53d7a00 and gp.function_ends[address] == gp.base + 0x53d7a5b, 'Managed body differs')
    managed = parse_assembly((evidence / 'managed-53d7a00.asm').read_bytes(), gp, gd, 0x53d7a00, 0x53d7a5b)
    for rva, text in {0x53d7a31: 'mov rdx, qword ptr [rax + 0xb8]', 0x53d7a38: 'mov rax, qword ptr [rdx + 0x8]',
                      0x53d7a45: 'mov rdx, rbx', 0x53d7a51: 'jmp qword ptr [rax + 0x18]'}.items():
        require(managed[rva]['text'] == text, 'Managed delegate forwarding differs')
    offset = gp.offset(address, 0x5b)
    require((installed / 'GameAssembly.dll').read_bytes()[offset:offset + 0x5b] == gd[offset:offset + 0x5b], 'Managed body changed')
    return dict(passed=True, scope=__doc__, original_sha256=ORIGINAL_SHA, installed=descriptor,
                files=files, timing_import=timer, managed_rva='0x53d7a00', managed_instructions=len(managed),
                managed_sha256=GAME_ASSEMBLY_SHA256, metadata_sha256=METADATA_SHA256,
                named_sink='UnityEngine.Analytics.AnalyticsSessionInfo.CallIdentityTokenChanged',
                advertising_producer_resolved=False, subscriber_set_resolved=False, runtime_observed=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'installed', 'evidence', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    report = review(args.original, args.installed, args.evidence)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(dict(passed=report['passed'], named_sink=report['named_sink'])))
