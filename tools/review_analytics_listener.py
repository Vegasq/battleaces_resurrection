"""Read-only183 evidence gate for one concrete native configuration listener.

Consumes retained LLVM disassembly; never loads a DLL or invokes a collector.
Original bytes and generated disassembly stay outside Git. The positive record
layout/dispatch binding is finite, not a whole-program reachability proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from tools.extract_descriptors import PE
from tools.frida_ads_caller import describe_unity

ORIGINAL_SHA = 'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'
ROOTS = {
    0xc66c20: 0xc66fc5, 0x5b8aa0: 0x5b8bb7, 0xc42230: 0xc425ca,
    0xc42790: 0xc42f3d, 0xc66a80: 0xc66b46, 0xc668b0: 0xc66a77,
    0xc66fd0: 0xc6735c, 0xc46880: 0xc46935,
}
# Authored semantic assertions, not original procedure bodies. Bytes for every
# decoded instruction are independently compared with the pinned input image.
ANCHORS = {
    # Start: find the analytics-key listener list, register callback plus Main.
    0xc66c2d: 'mov rdi, rcx',
    0xc66cad: 'mov rbx, qword ptr [rdi + 0x1658]',
    0xc66cbb: 'mov r8d, 0x9',
    0xc66cf6: 'mov r8, rdi', 0xc66d00: 'mov rcx, rax',
    # The returned listener lives at tree node+48, keyed by node+20.
    0xc42255: 'mov r14, rdx', 0xc42270: 'lea rcx, [rdi + 0x20]',
    0xc42274: 'mov rdx, r14', 0xc425a8: 'lea rax, [rbx + 0x48]',
    # 24-byte listener records: function, bound owner, with-owner flag.
    0x5b8abc: 'mov rdi, r8', 0x5b8abf: 'mov rsi, rdx',
    0x5b8ac2: 'mov rbx, rcx', 0x5b8b80: 'mov ecx, dword ptr [rbx + 0xc00]',
    0x5b8b8e: 'lea rax, [rcx + 2*rcx]', 0x5b8b92: 'lea rdx, [rbx + 8*rax]',
    0x5b8ba3: 'mov qword ptr [rdx], rsi', 0x5b8baa: 'mov qword ptr [rdx + 0x8], rdi',
    0x5b8bae: 'mov byte ptr [rdx + 0x10], 0x1',
    # Dispatcher walks that same key tree and selects the bound-owner branch.
    0xc42836: 'mov rax, qword ptr [rdi]', 0xc42839: 'mov rbx, qword ptr [rax]',
    0xc42873: 'lea rax, [rbx + 0x20]', 0xc428d3: 'lea r15, [rbx + 0x48]',
    0xc42988: 'lea r15, [rbx + 0x48]',
    0xc42a70: 'mov eax, r14d', 0xc42a73: 'lea rcx, [rax + 2*rax]',
    0xc42a77: 'mov r10, qword ptr [r15 + 8*rcx]',
    0xc42a7b: 'lea rax, [r15 + 8*rcx]',
    0xc42a84: 'cmp byte ptr [rax + 0x10], 0x0',
    0xc42aa0: 'mov rcx, qword ptr [rax + 0x8]',
    0xc42aa4: 'lea r8, [rbp - 0x70]', 0xc42aa8: 'movzx r9d, bl',
    0xc42aac: 'mov byte ptr [rsp + 0x20], r12b',
    0xc42ab1: 'lea rdx, [rsp + 0x48]', 0xc42ab6: 'call r10',
    # RCX remains Main; R8 is a separate parser context, not an ads receiver.
    0xc66a86: 'cmp byte ptr [rsp + 0x60], 0x0',
    0xc66a8b: 'mov rbx, r8', 0xc66a9d: 'lea rsi, [rcx + 0x1660]',
    0xc66b07: 'mov rdx, rsi', 0xc66b0a: 'mov rcx, rbx',
    0xc66b12: 'lea rdx, [rsi + 0x8]', 0xc66b16: 'mov rcx, rbx',
    # Stop passes the same callback and exact Main owner to removal.
    0xc66fd6: 'mov rbp, rcx', 0xc66fde: 'cmp byte ptr [rbp + 0x1650], 0x0',
    0xc66ffa: 'mov rbx, qword ptr [rbp + 0x1658]',
    0xc6703c: 'mov r8, rbp', 0xc67046: 'mov rcx, rax',
    0xc468a4: 'cmp qword ptr [r11 + 8*r10], rdx',
    0xc468ae: 'cmp qword ptr [rcx + 0x8], r8',
    0xc468c0: 'mov qword ptr [rcx], 0x0',
    0xc468c7: 'mov qword ptr [rcx + 0x8], 0x0',
    0xc468cf: 'mov byte ptr [rcx + 0x10], 0x0',
}
CALLS = {0xc66cf1: 0xc42230, 0xc66d03: 0x5b8aa0,
         0xc66b0d: 0xac9ab0, 0xc66b19: 0xc668b0,
         0xc67037: 0xc42230, 0xc67049: 0xc46880}
LEAS = {0xc66cb4: ('rdx', 0x1a2ac10), 0xc66cf9: ('rdx', 0xc66a80),
        0xc66b00: ('r8', 0x1a2bae8), 0xc66ff3: ('rdx', 0x1a2ac10),
        0xc6703f: ('rdx', 0xc66a80)}


def parse_assembly(raw, pe, data, start, end):
    """Reject missing,overlapping,changed or out-of-range decoded bytes."""
    result = {}; cursor = start
    for line in raw.decode('utf-8').splitlines():
        match = re.match(r'^([0-9a-f]+): ((?:[0-9a-f]{2} )+)\s+(.+)$', line)
        if not match: continue
        rva = int(match[1], 16) - pe.base; code = bytes.fromhex(match[2])
        if rva != cursor or rva + len(code) > end:
            raise ValueError('Decoded extent is not complete and contiguous')
        offset = pe.offset(pe.base + rva, len(code))
        if data[offset:offset+len(code)] != code:
            raise ValueError('Decoded instruction differs from original bytes')
        text = ' '.join(match[3].split('#', 1)[0].split())
        result[rva] = dict(code=code, text=text); cursor += len(code)
    if cursor != end: raise ValueError('Decoded extent is incomplete')
    return result


def review(original, installed, evidence):
    data = Path(original).read_bytes(); patched = Path(installed).read_bytes(); evidence = Path(evidence)
    if hashlib.sha256(data).hexdigest() != ORIGINAL_SHA: raise ValueError('Pinned original required')
    descriptor = describe_unity(data, patched); pe = PE(data); rows = {}; files = []
    def require(value, label):
        if not value: raise ValueError(label)
    for start, end in ROOTS.items():
        require(pe.function_ends.get(pe.base+start) == pe.base+end, 'Unwind extent differs')
        path = evidence/f'unity-{start:x}.asm'; raw = path.read_bytes()
        parsed = parse_assembly(raw, pe, data, start, end); rows.update(parsed)
        offset = pe.offset(pe.base+start, end-start)
        files.append(dict(path=path.name, start=hex(start), end=hex(end), instructions=len(parsed),
                          assembly_sha256=hashlib.sha256(raw).hexdigest(),
                          original_body_sha256=hashlib.sha256(data[offset:offset+end-start]).hexdigest()))
    for rva, expected in ANCHORS.items():
        require(rows[rva]['text'] == expected, f'Semantic anchor differs at {rva:x}')
    for rva, target in CALLS.items():
        code = rows[rva]['code']
        require(len(code) == 5 and code[0] == 0xe8 and rva+5+struct.unpack('<i', code[1:])[0] == target,
                f'Direct callee differs at {rva:x}')
    for rva, (register, target) in LEAS.items():
        code = rows[rva]['code']
        require(len(code) == 7 and code[1] == 0x8d and code[2] & 0xc7 == 5 and
                rva+7+struct.unpack('<i', code[3:])[0] == target and rows[rva]['text'].startswith('lea '+register+', '),
                f'Bound literal/callback differs at {rva:x}')
    for rva, expected in ((0x1a2ac10, b'analytics\0'), (0x1a2bae8, b'enabled\0')):
        offset = pe.offset(pe.base+rva, len(expected))
        require(data[offset:offset+len(expected)] == expected, 'Selected configuration key differs')
    for slot, target in ((0x1a2c538+0xe0, 0xc66c20), (0x1a2c538+0xe8, 0xc66fd0)):
        offset = pe.offset(pe.base+slot, 8)
        require(struct.unpack_from('<Q', data, offset)[0] == pe.base+target, 'Retained platform slot differs')
    # Complete recipe comparison above binds the installed entry RET, not just
    # a guessed patched prefix. Preserve every other byte in the reviewed Start.
    for start, end in ROOTS.items():
        offset = pe.offset(pe.base+start, end-start)
        expected = data[offset:offset+end-start]
        if start == 0xc66c20: expected = b'\xc3'+expected[1:]
        require(patched[offset:offset+end-start] == expected, 'Reviewed installed body differs')
    return dict(passed=True, original_sha256=ORIGINAL_SHA, installed=descriptor, files=files,
                semantic_anchors=len(ANCHORS), direct_edges=len(CALLS), address_bindings=len(LEAS),
                computed_dispatch='c42ab6 -> c66a80 for the c66d03-bound analytics listener only',
                record=dict(stride=24, callback_offset=0, owner_offset=8, bound_flag_offset=16),
                existing_start_guard_prevents_named_registration=True,
                advertising_producer_resolved=False, whole_program_coverage=False, runtime_observed=False,
                scope='Static named configuration-listener registration/dispatch/removal; no transitive source-absence claim')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', required=True, type=Path)
    parser.add_argument('--installed', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); result = review(args.original, args.installed, args.evidence)
    with args.output.open('x', encoding='utf-8') as stream: json.dump(result, stream, indent=2)
    print(json.dumps({k:v for k,v in result.items() if k != 'files'}, indent=2))
