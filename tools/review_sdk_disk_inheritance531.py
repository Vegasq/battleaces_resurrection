"""Bind the direct SDK disk-call proof to the current recipe47 image."""
from __future__ import annotations

import json
from pathlib import Path

from tools.review_unity_post512 import ROOT, review as current_review
from tools.review_recipe47_queue_connected524 import sha256

HISTORICAL = ROOT / 'local/privacy507-disk-reach01/review507.json'
NETWORK = ROOT / 'local/privacy508-network-targets01/review508.json'
OLD_GAME = ROOT / 'local/privacy506-game01'
CURRENT_GAME = ROOT / 'local/privacy512-game01'
RECEIPT_SHA = '20ece400ec8dc583982e44895e5e6b3e6dc3c1e245309d2365549ebac328ee0b'
NETWORK_SHA = 'ef3381e35b28358b51a56ac4e17c1b7c8ced1068db496a572d005c64e8e666ff'


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    assert sha256(HISTORICAL) == RECEIPT_SHA
    old = read(HISTORICAL)
    assert old['passed'] and old['recipe'] == 46
    assert old['selected_direct_disk_calls'] == 15
    assert old['in_memory_stream_calls'] == 4 and len(old['cuts']) == 7
    assert {row['kind'] for row in old['cuts']} == {'entry-return', 'branch-past-calls'}
    assert sum(len(row['direct_disk_calls']) for row in old['cuts']) == 15
    assert sha256(NETWORK) == NETWORK_SHA
    network = read(NETWORK)
    assert network['passed'] and network['recipe'] == 46
    assert network['direct_calls'] == 54
    assert network['system_net_direct_calls'] == 2
    assert network['unity_networking_direct_calls'] == 52
    assert network['sdk_web_request_send_entry_active'] is True
    bound = current_review()
    assert bound['passed'] and bound['recipe'] == 47
    current = CURRENT_GAME / 'GameAssembly.dll'
    previous = OLD_GAME / 'GameAssembly.dll'
    assert sha256(previous) == old['installed_sha256'] == sha256(current)
    manifest = read(CURRENT_GAME / '.battleaces-resurrection/patch-manifest.json')
    assert manifest['telemetry']['recipe_version'] == 47
    assert manifest['components']['GameAssembly.dll']['telemetry_guards'] == 108
    assert manifest['components']['GameAssembly.dll']['installed_sha256'] == sha256(current)
    assert sha256(CURRENT_GAME / '.battleaces-resurrection/original/GameAssembly.dll') == old['original_sha256']
    assert network['original_sha256'] == old['original_sha256']
    return {'passed': True, 'recipe': 47, 'installed_sha256': sha256(current),
            'historical_receipt_sha256': RECEIPT_SHA,
            'network_receipt_sha256': NETWORK_SHA,
            'selected_direct_disk_calls': 15, 'guarded_owners': 7,
            'selected_direct_network_calls': 54,
            'scope': 'byte-identical current GameAssembly inherits the verified selected direct SDK disk-call cuts and network-call inventory; active wrapper,indirect/native/other-module I/O and whole wire remain open'}


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
