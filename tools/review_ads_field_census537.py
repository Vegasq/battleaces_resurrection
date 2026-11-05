"""Review exact-offset DeviceInfoEvent adsid field instruction census."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.extract_descriptors import PE
from tools.review_ads_device_event536 import review as review_event
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_unity_post512 import ROOT

LOG = ROOT/'local/d5-ghidra-12.1.4/pdb-device-ads-field537-console.log'
LOG_SHA = 'cae800a86d2ad618920d3022a2a73f0749033ecdb31d47bac3e6d702bcfd3be6'
GAME = ROOT/'local/privacy512-game01'
SELECTED = {
    '180c40439': 'MOV RDX,qword ptr [RCX + 0x5f0] OWNER 180c40420 UnityEngine::Analytics::DeviceInfoEvent::~DeviceInfoEvent',
    '180c491a6': 'MOV byte ptr [R12 + 0x5f0],0x0 OWNER 180c49110 UnityEngine::Analytics::DeviceInfoEvent::DeviceInfoEvent',
    '180c4bad6': 'LEA RDX,[RBX + 0x5f0] OWNER 180c4ba90 UnityEngine::Analytics::DeviceInfoEvent::ToJsonString',
    '180c4bae9': 'LEA RDX,[RBX + 0x618] OWNER 180c4ba90 UnityEngine::Analytics::DeviceInfoEvent::ToJsonString',
}


def review() -> dict:
    assert review_event()['passed']
    raw = ORIGINAL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA
    current = (GAME/'UnityPlayer.dll').read_bytes()
    old, new = PE(raw), PE(current)
    data = LOG.read_bytes()
    assert hashlib.sha256(data).hexdigest() == LOG_SHA
    log = data.decode('utf-16')
    assert 'TOTAL functions=59459 instructions=6056204 hits=560' in log
    hits = [line.split('TraceDeviceAdsField537.java> HIT ', 1)[1].split(' (GhidraScript)', 1)[0]
            for line in log.splitlines() if 'TraceDeviceAdsField537.java> HIT ' in line]
    assert len(hits) == 560
    owned = [line for line in hits if 'UnityEngine::Analytics::DeviceInfoEvent::' in line]
    assert len(owned) == 4
    assert {line.split(' ', 1)[0]: line.split(' ', 1)[1] for line in owned} == SELECTED
    for start in (0xc40420, 0xc49110, 0xc4ba90):
        end = old.function_ends[old.base+start]-old.base
        o, n = old.offset(old.base+start, end-start), new.offset(new.base+start, end-start)
        assert raw[o:o+end-start] == current[n:n+end-start]
    return {'passed': True, 'ghidra_log_sha256': LOG_SHA,
            'installed_unity_sha256': hashlib.sha256(current).hexdigest(),
            'analyzed_instructions': 6056204, 'numeric_offset_matches': len(hits),
            'device_event_matches': [hex(int(site, 16)-0x180000000) for site in SELECTED],
            'other_direct_device_event_field_writers_found': False,
            'scope': 'literal 0x5f0/0x618 instructions in analyzed functions; aliases, bulk copies and unanalysed code unresolved'}


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
