"""Check recipe47 public ads guard and owned run provenance; REA result is scoped."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.telemetry import COMPONENTS
from tools.review_unity_post512 import GAME, ROOT, review as review_recipe47

REPORT = ROOT / 'local/privacy518-public-ads01/verification.json'
OBSERVER = ROOT / 'tools/ads_public_probe518.js'
EXPECTED_OBSERVER = '9987ac21d04f7d1c6d1667b0d6abdbfd12cb97be57c1eb045816d54b7e2406ff'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review() -> dict:
    bound = review_recipe47()
    assert bound['passed'] and bound['recipe'] == 47
    assert sha(OBSERVER) == EXPECTED_OBSERVER
    guards = {item.rva: item for item in COMPONENTS['UnityPlayer.dll'].patches}
    assert guards[0x5fb70].replacement == bytes.fromhex('31c0c3')
    assert guards[0x361870].replacement == b'\xc3'
    image = (GAME / 'UnityPlayer.dll').read_bytes()
    assert image[0x5ef70:0x5ef73] == bytes.fromhex('31c0c3')
    assert image[0x360c70] == 0xc3
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    assert report['passed'] and report['exit_code'] == 0
    assert report['images_unchanged'] and not report['launch']['forced_cleanup']
    assert report['tracker']['final_accounting'] == {'total': 1, 'active': 0, 'terminated': 0}
    assert Path(report['game']).resolve() == GAME.resolve()
    assert report['ready']['pid'] == report['tracker']['root_pid'] == 53284
    return {'passed': True, 'recipe': 47, 'installed_unity_sha256': bound['installed_unity_sha256'],
            'observer_sha256': EXPECTED_OBSERVER, 'owner_report_sha256': sha(REPORT),
            'source_installed_owner_binding': True,
            'rea_messages_independently_persisted': False,
            'full_p9_qualified': False}


if __name__ == '__main__':
    result = review()
    path = ROOT / 'local/privacy518-public-ads01/review518.json'
    with path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, sort_keys=True))
