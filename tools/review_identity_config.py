"""Static200 parsed-token retention and change notification; no target execution.

Reads pinned original/current images and retained disassembly. Entry activation,
input transport, subscribers and the separate advertising producer stay unknown.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from tools.extract_descriptors import PE, checked_input
from tools.frida_ads_caller import describe_unity
from tools.review_analytics_listener import ORIGINAL_SHA, parse_assembly

ROOTS = {0xc416b0: 0xc41ebe, 0xac4ad0: 0xac5365, 0xacad70: 0xacaea0,
         0xacaea0: 0xacaf62, 0xacbf20: 0xacc008, 0x15b680: 0x15b77d,
         0xa1ca40: 0xa1caaa, 0xc308c0: 0xc3093a}
LEAF = (0xc308a0, 0xc308b6)
PRIOR_SHA = 'd1154fddb6f83a8b16107b2f1375a0dff745bd76c66204deecbe2c692d18a8c8'
LITERALS = {0x1a2ac28: 'IdentityConfigValue', 0x1a2ad94: 'token', 0x1976458: 'string'}
ANCHORS = {
    # Main and reader are separate; the selected value is written INTO Main190.
    0xc416cd: 'mov rbx, r8', 0xc416dc: 'mov r12, rcx',
    0xc41768: 'mov qword ptr [rbx + 0x78], rax',
    0xc41777: 'test rax, rax', 0xc4177a: 'je 0x180c4179d <UnityMain+0x43c33d>',
    0xc41786: 'lea rdx, [r12 + 0x190]', 0xc4178e: 'mov rcx, rbx',
    0xac4ae1: 'mov rcx, qword ptr [rcx + 0x78]', 0xac4ae5: 'mov r14, rdx',
    0xac4ae8: 'mov r8d, dword ptr [rcx + 0x10]', 0xac4aef: 'shr eax, 0x14',
    0xac4af6: 'bt r8d, 0x16', 0xac4afd: 'mov rcx, qword ptr [rcx]',
    0xac4b07: 'inc rdi', 0xac4b0a: 'cmp byte ptr [rcx + rdi], 0x0',
    0xac4b10: 'mov rdx, rcx', 0xac4b13: 'mov r8, rdi', 0xac4b16: 'mov rcx, r14',
    # Shared assignment retains destination, source and length; updates storage.
    0x15b69e: 'mov rsi, r8', 0x15b6a1: 'mov r14, rdx', 0x15b6a4: 'mov rbx, rcx',
    0x15b73a: 'mov r8, rsi', 0x15b73d: 'mov rdx, r14', 0x15b740: 'mov rcx, rax',
    0x15b743: 'mov rdi, rax', 0x15b74b: 'mov byte ptr [rdi + rsi], 0x0',
    0x15b758: 'mov byte ptr [rbx + 0x18], bpl', 0x15b75e: 'mov qword ptr [rbx + 0x10], rsi',
    # Reader stack bookkeeping uses +80, not the selected-node slot +78.
    0xa1ca54: 'lea rbx, [rcx + 0x80]', 0xa1ca8a: 'mov qword ptr [rbx + 0x10], rdi',
    # Exact-key search can fall back to aliases; not string-only validation.
    0xacad7f: 'mov r14, r8', 0xacad85: 'mov rdx, r14', 0xacad88: 'mov r8, r9',
    0xacad9f: 'mov rax, qword ptr [rbp + 0xc0]',
    0xacaeb5: 'cmp al, 0x3', 0xacaf03: 'mov qword ptr [rsp + 0x20], r8',
    0xacaf21: 'mov dword ptr [rsp + 0x30], 0x100005', 0xacaf50: 'add rax, 0x18',
    0xacbf9d: 'cmp edx, ecx', 0xacbfbb: 'mov r8d, edx', 0xacbfbe: 'mov rdx, rax',
    0xacbfca: 'lea rax, [rdi + 0x30]',
    0xac4b33: 'cmp r8d, 0x102', 0xac5327: 'xor r8d, r8d', 0xac5331: 'mov rcx, r14',
    # Compare effective identity to Main1138. Equal values bypass notification.
    0xc417df: 'lea rcx, [r12 + 0x190]', 0xc41841: 'lea rcx, [rbp - 0x19]',
    0xc41b2d: 'lea r10, [r12 + 0x1138]', 0xc41b6b: 'cmp rcx, rdx',
    0xc41bd9: 'je 0x180c41c35 <UnityMain+0x43c7d5>',
    0xc41c07: 'mov r8, r15', 0xc41c0a: 'mov rdx, r14', 0xc41c0d: 'mov rcx, r10',
    0xc41c15: 'mov rcx, r12', 0xc41c1d: 'mov rax, qword ptr [r12]',
    0xc41c21: 'mov rcx, r12', 0xc41c24: 'call qword ptr [rax + 0xd8]',
    0xc308a0: 'mov r8, rcx', 0xc308c9: 'mov rbx, rcx', 0xc308d8: 'add rbx, 0x190',
}
EDGES = {0xc41763: (0xe8, 0xacad70), 0xc41781: (0xe8, 0xa1ca40),
         0xc41791: (0xe8, 0xac4ad0), 0xac4b24: (0xe9, 0x15b680),
         0x15b746: (0xe8, 0x17fefb0), 0xacad91: (0xe8, 0xacaea0),
         0xacaf29: (0xe8, 0xacbf20), 0xacbfc1: (0xe8, 0x17ff3a0),
         0xac5334: (0xe8, 0x15b680), 0xc41845: (0xe8, 0xc43ae0),
         0xc41c10: (0xe8, 0x15b680), 0xc41c18: (0xe8, 0xc41ec0),
         0xc308b1: (0xe9, 0x56ca40)}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def review(original, installed, evidence, notification):
    original, installed, evidence, notification = map(Path, (original, installed, evidence, notification))
    data = checked_input(original / 'UnityPlayer.dll', ORIGINAL_SHA)
    patched = (installed / 'UnityPlayer.dll').read_bytes()
    descriptor = describe_unity(data, patched)
    prior_raw = notification.read_bytes()
    require(sha(prior_raw) == PRIOR_SHA, 'Retained197 notification report differs')
    prior = json.loads(prior_raw)
    require(prior['passed'] is True and prior['installed'] == descriptor, 'Notification installation differs')
    pe = PE(data); rows = {}; files = []
    for start, end in (*ROOTS.items(), LEAF):
        leaf = (start, end) == LEAF
        require((pe.base + start not in pe.function_ends) if leaf else
                pe.function_ends.get(pe.base + start) == pe.base + end, 'Unwind/leaf boundary differs')
        path = evidence / f'unity-{start:x}.asm'; raw = path.read_bytes()
        decoded = parse_assembly(raw, pe, data, start, end); rows.update(decoded)
        offset = pe.offset(pe.base + start, end - start)
        require(data[offset:offset + end - start] == patched[offset:offset + end - start], 'Reviewed body changed')
        files.append(dict(path=path.name, start=hex(start), end=hex(end), leaf=leaf,
                          instructions=len(decoded), assembly_sha256=sha(raw),
                          original_body_sha256=sha(data[offset:offset + end - start])))
    require(len([r for r in rows if LEAF[0] <= r < LEAF[1]]) == 4, 'Terminal leaf differs')
    for rva, expected in ANCHORS.items():
        require(rows[rva]['text'] == expected, f'Semantic anchor differs: {rva:x}')
    for rva, (opcode, target) in EDGES.items():
        code = rows[rva]['code']
        require(len(code) == 5 and code[0] == opcode and rva + 5 + struct.unpack('<i', code[1:])[0] == target,
                f'Direct edge differs: {rva:x}')
    for rva, target in ((0xc41723, 0x1a2ac28), (0xc41759, 0x1a2ad94), (0xc4176c, 0x1976458),
                        (0xacadb0, 0x1d0da00), (0xc308a3, 0xc308c0), (0xc308aa, 0x1d0cad0)):
        code = rows[rva]['code']
        require(len(code) == 7 and code[2] & 0xc7 == 5 and
                rva + 7 + struct.unpack('<i', code[3:])[0] == target, 'RIP binding differs')
    for rva, expected in LITERALS.items():
        raw = expected.encode() + b'\0'; offset = pe.offset(pe.base + rva, len(raw))
        require(data[offset:offset + len(raw)] == raw, 'Configuration name differs')
    for table in (0x1a2aec0, 0x1a2c538):
        offset = pe.offset(pe.base + table + 0xd8, 8)
        require(struct.unpack_from('<Q', data, offset)[0] == pe.base + LEAF[0], 'Main notification slot differs')
        require(data[offset:offset + 8] == patched[offset:offset + 8], 'Installed notification slot changed')
    # Reuse197's named managed sink instead of repeating the runtime-resolver work.
    require(prior['named_sink'] == 'UnityEngine.Analytics.AnalyticsSessionInfo.CallIdentityTokenChanged',
            'Retained named notification differs')
    return dict(passed=True, scope=__doc__, original_sha256=ORIGINAL_SHA, installed=descriptor,
                files=files, instructions=len(rows), notification_report_sha256=PRIOR_SHA,
                named_sink=prior['named_sink'], token_field='Main+190', parsed_input_retained=True,
                effective_change_field='Main+1138', queued_callback_reads_current_token=True,
                missing_member_clears_token=False, string_only_validation=False,
                entry_activation_resolved=False, input_transport_resolved=False,
                advertising_producer_resolved=False, runtime_observed=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original', 'installed', 'evidence', 'notification', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = review(args.original, args.installed, args.evidence, args.notification)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(dict(passed=result['passed'], instructions=result['instructions'], files=len(result['files']))))
