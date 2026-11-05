"""Exercise the unchanged native server installer Install action in an owned Job."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import time

from client_patch.transport.launcher import verify_game
from server.assets import verify_assets
from tools.owned_suspended_launch import ROOT, SuspendedChild
from tools.package_integrity import verify
from tools.review_recipe47_native_install546 import review as review_client_install

GAME = ROOT / 'local/privacy543-game01'
INSTALLER = ROOT / 'local/privacy542-server-installer01/Install Battle Aces Server.exe'
HOST = ROOT / 'local/privacy543-client-install01/NativeFormHost.exe'
OUTPUT = ROOT / 'local/privacy548-server-install01'
SERVER = ROOT / 'local/privacy548-server01'
SOURCE_FILES = ('Battle Aces.exe', 'GameAssembly.dll', 'UnityPlayer.dll',
                'BattleAcesOffline.dll', '.battleaces-resurrection/patch-manifest.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    return {name: digest(GAME / name) for name in SOURCE_FILES}


def run():
    assert review_client_install()['passed']
    verify_game(GAME, community=True, bridge_version=2, unified=True,
                player_features=True)
    assert not OUTPUT.exists() and not SERVER.exists()
    assert INSTALLER.is_file() and HOST.is_file()
    before = snapshot()
    OUTPUT.mkdir()
    shutil.copyfile(HOST, OUTPUT / HOST.name)
    shutil.copyfile(ROOT / 'local/privacy543-client-install01/NativeFormHost.cs',
                    OUTPUT / 'NativeFormHost.cs')
    request = {'game_directory': str(GAME), 'server_directory': str(SERVER)}
    (OUTPUT / 'request.json').write_text(json.dumps(request) + '\n', encoding='utf-8')
    gate = OUTPUT / 'owner-job.ready'
    form_path = OUTPUT / 'form.json'
    child = SuspendedChild.create([str(OUTPUT / HOST.name), str(INSTALLER),
                                   str(OUTPUT / 'request.json'), str(form_path), str(gate)],
                                  cwd=OUTPUT)
    try:
        gate.write_text('owned job attached\n', encoding='utf-8', newline='\n')
        child.resume()
        deadline = time.monotonic() + 900
        while child.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError('Native server installer exceeded 900 seconds')
            time.sleep(.25)
        form = json.loads(form_path.read_text(encoding='utf-8'))
    finally:
        child.close()
        (OUTPUT / 'owner-launch.json').write_text(json.dumps(child.receipt, indent=2) + '\n',
                                                   encoding='utf-8')
    assert child.returncode == 0 and form['passed']
    assert form['actual_native_install_click'] and form['background_worker_observed']
    assert form['controls_locked_while_busy'] and form['progress_visible_while_busy']
    assert form['controls_restored'] and not child.receipt['forced_cleanup']
    assert child.receipt['job_final']['active_processes'] == 0
    assert child.receipt['job_final']['total_terminated_processes'] == 0
    assert SERVER.is_dir() and verify(SERVER, 'server')
    verify_assets(SERVER / 'assets/build-37822')
    assert (SERVER / 'Start Server.exe').is_file()
    assert not (SERVER / 'config/private').exists()
    after = snapshot()
    assert before == after
    result = {'passed': True, 'recipe': 47, 'actual_native_install_click': True,
              'server_started': False, 'private_keys_created': False,
              'source_game_unchanged': True, 'installer_sha256': digest(INSTALLER),
              'form': form, 'job': child.receipt['job_final'],
              'source_game_sha256': before,
              'asset_manifest_sha256': digest(SERVER / 'assets/build-37822/asset-manifest.json')}
    (OUTPUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n',
                                               encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(run(), sort_keys=True))
