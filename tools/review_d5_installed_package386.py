"""Bind the corrected private client package to its owned installed runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.telemetry import RECIPE_VERSION, RUNTIME_VALIDATED
from tools.ads_connected382 import GAME
from tools.frida_ads_caller import describe_unity
from tools.game_installer import launcher_bytes, replay_launcher_bytes
from tools.package_integrity import verify
from tools.review_ads_state_callback296 import ORIGINAL, ORIGINAL_SHA

ROOT = Path(__file__).resolve().parents[1]
PAIR = ROOT / 'local/privacy358-packages02'
PACKAGE = PAIR / 'battleaces-client-win64'
OUT = ROOT / 'local/privacy386-installed-package01'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def review() -> dict:
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    build = json.loads((PAIR / 'build-report.json').read_text(encoding='utf-8'))
    archive = PAIR / build['packages']['client']['archive']
    assert sha(archive) == build['packages']['client']['sha256']
    package_inventory = verify(PACKAGE, 'client')
    identity = hashlib.sha256((PACKAGE / 'package-manifest.json').read_bytes()).hexdigest()[:20]
    relative = '.battleaces-resurrection/client-runtime/' + identity
    runtime = GAME / relative
    assert runtime.is_dir()
    assert verify(runtime, 'client') == package_inventory
    assert (runtime / 'package-manifest.json').read_bytes() == (PACKAGE / 'package-manifest.json').read_bytes()
    assert (GAME / 'Start Battle Aces.cmd').read_bytes() == launcher_bytes(relative)
    assert (GAME / 'Watch Replay.cmd').read_bytes() == replay_launcher_bytes()
    config = json.loads((GAME / '.battleaces-resurrection/client-config.json').read_text(encoding='utf-8'))
    assert config['schema'] == 4 and Path(config['game_directory']).resolve() == GAME.resolve()
    assert config['server_host'] == '127.0.0.1'
    patch = json.loads((GAME / '.battleaces-resurrection/patch-manifest.json').read_text(encoding='utf-8'))
    assert RECIPE_VERSION == patch['telemetry']['recipe_version'] == 38
    assert RUNTIME_VALIDATED is patch['telemetry']['runtime_validated'] is False
    helper_hash = sha(GAME / 'BattleAcesOffline.dll')
    assert helper_hash == patch['helper_sha256'] == sha(runtime / 'program/client-helper/BattleAcesOffline.dll')
    descriptor = describe_unity(original, (GAME / 'UnityPlayer.dll').read_bytes())
    assert descriptor['recipe'] == 38
    result = dict(passed=True, scope='owned private installed client package; no release or whole privacy claim',
                  recipe=38, runtime_identity=identity, package_files=len(package_inventory['files']),
                  archive_sha256=sha(archive), package_manifest_sha256=sha(PACKAGE / 'package-manifest.json'),
                  patch_manifest_sha256=sha(GAME / '.battleaces-resurrection/patch-manifest.json'),
                  helper_sha256=helper_hash, unity_sha256=descriptor['fileSha256'],
                  installed_launcher_exact=True, runtime_validated=False)
    OUT.mkdir(exist_ok=True)
    (OUT / 'review.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
