"""Bind the original SDK OnSendError registration method and recipe28 entry cut."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from client_patch.patcher.telemetry import COMPONENTS,RECIPE_VERSION,patch_component
from tools.extract_descriptors import Metadata,PE
from tools.review_analytics_listener import parse_assembly
from tools.review_reporter_delegate_targets300 import ORIGINAL,METADATA,OLD_SHA,MD_SHA
from tools.verify_sdk_data_ingress322 import NEW_RVAS, CONTEXT_RVAS, MERGE_RVAS

ROOT=Path(__file__).resolve().parents[1]
ASM=ROOT/'local/privacy307-addonerror01/add-on-send-error.asm'
START,END=0x81b2b0,0x81b493
SITES=(0x3cc2802,0x3cc28f2,0x3cc2923,0x3cc2954,0x3cc2985,0x3cc29b6)
OUTPUT_SHA='2568beb2ed9deeda4e15941483889da53870ecbf05491d3c78455e4376b34739'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def verify():
    original,metadata=ORIGINAL.read_bytes(),METADATA.read_bytes()
    assert sha(original)==OLD_SHA and sha(metadata)==MD_SHA and RECIPE_VERSION>=28
    pe,md=PE(original),Metadata(metadata)
    assert pe.function_ends[pe.base+START]==pe.base+END
    method=md.methods[163618]
    typ=md.types[method[1]]
    assert (md.string(method[0]),md.string(typ[0]),md.string(typ[1]),
            method[6],method[7],method[2],method[-1])==(
                'AddOnSendError','Configuration','BugsnagUnity',0x60000e3,0x86,59011,1)
    count,table=pe.module('BugsnagUnity.Windows.dll',227)
    assert count>=227 and struct.unpack_from('<Q',original,pe.offset(table+226*8,8))[0]==pe.base+START
    rows=parse_assembly(ASM.read_bytes(),pe,original,START,END)
    assert rows[START]['text'].startswith('mov qword ptr [rsp + 0x10], rbx')
    assert rows[0x81b2e1]['text']=='mov rax, qword ptr [rbx + 0x160]'
    assert rows[0x81b340]['text']=='mov rcx, qword ptr [rbx + 0x168]'
    assert rows[0x81b390]['text']=='mov r8, rdi'
    assert rows[0x81b393]['text']=='mov rcx, r9'
    transformed=patch_component('GameAssembly.dll',original)
    previous=bytearray(transformed)
    for rva in (0x8181f0,0x835c60,0x835d00,0x818040,0x811180,0x8112a0,*NEW_RVAS,*CONTEXT_RVAS):
        offset=pe.offset(pe.base+rva)
        previous[offset]=original[offset]
    for rva in MERGE_RVAS:
        offset=pe.offset(pe.base+rva)
        previous[offset:offset+5]=original[offset:offset+5]
    assert sha(previous)==OUTPUT_SHA
    selected=[p for p in COMPONENTS['GameAssembly.dll'].patches if p.label=='BugsnagUnity.Configuration::AddOnSendError']
    assert len(selected)==1
    patch=selected[0]
    assert (patch.rva,patch.offset,patch.replacement)==(START,0x8198b0,b'\xc3')
    before=original[pe.offset(pe.base+START,END-START):][:END-START]
    after=transformed[pe.offset(pe.base+START,END-START):][:END-START]
    assert after==b'\xc3'+before[1:]
    direct=[]
    target=pe.base+START
    for base,size,file_offset in pe.sections:
        for offset in range(file_offset,min(file_offset+size,len(original))-4):
            if original[offset]!=0xe8:continue
            address=base+offset-file_offset
            if address+5+struct.unpack_from('<i',original,offset+1)[0]==target:
                direct.append(address-pe.base)
    assert tuple(direct)==SITES
    assert before[0]!=after[0] and transformed[patch.offset+1:patch.offset+len(patch.guard)]==original[patch.offset+1:patch.offset+len(patch.guard)]
    return dict(passed=True,recipe=RECIPE_VERSION,decoded_instructions=len(rows),
                direct_registration_sites=[hex(x) for x in direct],
                source_output_sha256=sha(transformed))


if __name__=='__main__':print('PASS',verify())
