"""Review the separate Main.Start -> c68390 listener handoff against pinned PE bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from tools.extract_descriptors import PE
from tools.review_analytics_listener import parse_assembly

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'local/privacy295-start-handoff01'
ORIGINAL=ROOT.parent.parent/'BattleAcesBeta_untouched/UnityPlayer.dll'
INSTALLED=ROOT/'local/privacy291-runtime01/game/UnityPlayer.dll'
ORIGINAL_SHA='ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc'
INSTALLED_SHA='a53b0c613a86c737b7caa7588c7c93ae20d5d5700f9321a406df9dcca8e32a7f'


def require(value,message):
    if not value:raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_range(pe,data,start,end):
    return data[pe.offset(pe.base+start,end-start):][:end-start]


def review():
    original,installed=ORIGINAL.read_bytes(),INSTALLED.read_bytes()
    require(sha(original)==ORIGINAL_SHA and sha(installed)==INSTALLED_SHA,'original or installed Unity identity differs')
    pe,ip=PE(original),PE(installed)
    roots={0xc66c20:(0xc66fc5,ROOT/'local/privacy183-dispatch01/unity-c66c20.asm'),
           0xc2ee90:(0xc2f414,ROOT/'local/privacy109-adsidentity01/unity-c2ee90.asm'),
           0xc68390:(0xc68536,EVIDENCE/'unity-c68390.asm'),
           0xc68190:(0xc68294,EVIDENCE/'unity-c68190.asm'),
           0xc69100:(0xc69186,EVIDENCE/'unity-c69100.asm'),
           0xc69270:(0xc692f2,EVIDENCE/'unity-c69270.asm')}
    rows={};files={}
    for start,(end,path) in roots.items():
        require(pe.function_ends.get(pe.base+start)==pe.base+end,'unwind extent differs')
        raw=path.read_bytes();rows.update(parse_assembly(raw,pe,original,start,end))
        files[path.name]=sha(raw)
    leaf_path=EVIDENCE/'unity-c68280-c68390.asm';leaf_raw=leaf_path.read_bytes()
    for start,end in ((0xc682a0,0xc682a5),(0xc682f0,0xc68311)):
        require(pe.base+start not in pe.function_ends,'leaf unexpectedly gained unwind root')
        selected=[]
        for line in leaf_raw.decode('utf-8').splitlines():
            match=re.match(r'^([0-9a-f]+): ',line)
            if match and start<=int(match[1],16)-pe.base<end:selected.append(line)
        rows.update(parse_assembly(('\n'.join(selected)+'\n').encode(),pe,original,start,end))
    files[leaf_path.name]=sha(leaf_raw)
    exact={
        0xc66c51:'mov rdx, qword ptr [rdi + 0x1248]',
        0xc66c58:'lea rcx, [rdi + 0x1568]',
        0xc66c5f:'call 0x180c68390',
        0xc2f033:'lea rax, [rip + 0x3a0c6]',
        0xc2f041:'mov qword ptr [rdi + 0x1598], rax',
        0xc683b8:'mov qword ptr [rcx + 0x40], rdx',
        0xc683c3:'lea rdx, [rcx + 0x8]',
        0xc683cb:'call 0x180c42230',
        0xc683d3:'lea rdx, [rip - 0x13a]',
        0xc683dd:'call 0x1805b8aa0',
        0xc684ed:'lea rax, [rip - 0x204]',
        0xc684f4:'mov qword ptr [rdx], rax',
        0xc684f7:'mov qword ptr [rdx + 0x8], rdi',
        0xc684fb:'mov byte ptr [rdx + 0x10], 0x1',
        0xc682a0:'jmp 0x180c69270',
        0xc6928a:'lea rcx, [rdi + 0x1850]',
        0xc69291:'call 0x180c42f40',
        0xc692bd:'mov rdx, qword ptr [rbx + 0x30]',
        0xc69118:'movzx ebx, byte ptr [rbx + 0x48]',
        0xc69178:'call 0x18080bc90',
        0xc682f0:'mov byte ptr [rcx + 0x49], r8b',
        0xc682f7:'mov byte ptr [rcx + 0x50], dl',
        0xc68301:'mov dword ptr [rcx + 0x4c], r9d',
        0xc6830c:'jmp 0x18056ca40',
        0xc681bd:'mov esi, dword ptr [rbx + 0x4c]',
        0xc681c8:'movzx edi, byte ptr [rbx + 0x49]',
        0xc681cc:'movzx ebx, byte ptr [rbx + 0x50]',
        0xc6826e:'call 0x18080bc90',
    }
    for rva,expected in exact.items():
        require(rows.get(rva,{}).get('text','').split(' <',1)[0]==expected,f'anchor differs at {rva:x}')
    require(read_range(pe,original,0xc66c20,0xc66c22)==bytes.fromhex('4057') and
            read_range(ip,installed,0xc66c20,0xc66c22)==bytes.fromhex('c357') and
            read_range(pe,original,0xc66c22,0xc66fc5)==read_range(ip,installed,0xc66c22,0xc66fc5),
            'current Main.Start entry guard or original tail differs')
    ctor_original=read_range(pe,original,0xc2ee90,0xc2f414)
    ctor_installed=read_range(ip,installed,0xc2ee90,0xc2f414)
    require([(0xc2ee90+i,a,b) for i,(a,b) in enumerate(zip(ctor_original,ctor_installed)) if a!=b]
            ==[(0xc2f402,1,0)],'constructor differs beyond existing device-statistics default cut')
    for start,end in ((0xc68390,0xc68536),(0xc68190,0xc68294),
                      (0xc69100,0xc69186),(0xc69270,0xc692f2),
                      (0xc682a0,0xc682a5),(0xc682f0,0xc68311)):
        require(read_range(pe,original,start,end)==read_range(ip,installed,start,end),
                'reviewed callback/helper changed in installed image')
    return dict(passed=True,scope='Static named Main.Start listener handoff only; no transitive callback or producer closure',
                original_sha256=sha(original),installed_sha256=sha(installed),asm_sha256=files,
                decoded_instructions=len(rows),semantic_anchors=len(exact),
                start_guard_before_handoff=True,
                ctor_delta='c2f402 device-statistics default 1->0 only',
                first_callback='c682a0 -> c69270; receiver+30 is ctor-bound c69100 scalar formatter',
                second_callback='c682f0 stores scalar flags/integer and passes c68190 to c56ca40',
                direct_advertising_callback_registration=False,upstream_producer_resolved=False,
                full_privacy_qualified=False)


if __name__=='__main__':
    result=review()
    path=EVIDENCE/'verification.json'
    with path.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2)
    print('PASS',path)
