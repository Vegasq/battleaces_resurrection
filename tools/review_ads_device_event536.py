"""Bind the native device-info adsid serializer to current entry cuts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION
from tools.extract_descriptors import PE
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA
from tools.review_unity_post512 import ROOT, review as review_current

LOG = ROOT / 'local/d5-ghidra-12.1.4/pdb-device-ads536c-console.log'
LOG_SHA = '9a59aa4e2daa4b05dcca1196dc7893af26cb2b769adb0bb14fea6cee988e2d6f'
GAME = ROOT / 'local/privacy512-game01'
GUARDS = (0x1fda50, 0xc40840)


def region(raw: bytes, pe: PE, rva: int, size: int) -> bytes:
    offset = pe.offset(pe.base+rva, size)
    return raw[offset:offset+size]


def review() -> dict:
    bound = review_current()
    assert bound['passed'] and bound['recipe'] == RECIPE_VERSION == 47
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    current_path = GAME/'UnityPlayer.dll'
    current = current_path.read_bytes()
    assert hashlib.sha256(current).hexdigest() == bound['installed_unity_sha256']
    log_bytes = LOG.read_bytes()
    assert hashlib.sha256(log_bytes).hexdigest() == LOG_SHA
    log = log_bytes.decode('utf-16')
    assert 'TARGET c49110 UnityEngine::Analytics::DeviceInfoEvent::DeviceInfoEvent' in log
    assert 'this[0x5f0] = (DeviceInfoEvent)0x0;' in log
    assert '"adsid",' in log and '(this + 0x5f0),"adsid"' in log
    assert 'REF 1801fda7b UNCONDITIONAL_CALL OWNER 1801fda50 RemoteConfigSettings_CUSTOM_SendDeviceInfoInConfigRequest' in log
    assert 'REF 180c4089a UNCONDITIONAL_CALL OWNER 180c40840 BaseUnityAnalytics::LookForVersionChange' in log
    assert 'COUNT c49110 3' in log
    assert 'TARGET c4ba90 UnityEngine::Analytics::DeviceInfoEvent::ToJsonString' in log
    old, new = PE(original), PE(current)
    for start in (0xc49110, 0xc4ba90):
        end = old.function_ends[old.base+start]-old.base
        assert region(original, old, start, end-start) == region(current, new, start, end-start)
    patches = {patch.rva: patch for patch in COMPONENTS['UnityPlayer.dll'].patches}
    for rva in GUARDS:
        patch = patches[rva]
        assert region(original, old, rva, len(patch.guard)) == patch.guard
        assert region(current, new, rva, len(patch.replacement)) == patch.replacement
    assert patches[0x1fda50].replacement == b'\x31\xc0\xc3'
    assert patches[0xc40840].replacement.endswith(b'\xc3')
    return {'passed': True, 'recipe': 47,
            'installed_unity_sha256': bound['installed_unity_sha256'],
            'ghidra_log_sha256': LOG_SHA,
            'device_event_adsid_field': '0x5f0',
            'direct_constructor_callers': ['0x1fda50', '0xc40840'],
            'current_entry_cuts': [hex(rva) for rva in GUARDS],
            'scope': 'two direct device-info event constructor routes; indirect writers/callers and upstream ads ID provider unresolved'}


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
