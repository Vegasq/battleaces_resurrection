"""Independently bind recipe47's actual native server Install result."""
from __future__ import annotations

import hashlib
import json

from server.assets import verify_assets
from tools.owned_suspended_launch import ROOT
from tools.package_integrity import verify
from tools.review_recipe47_native_install546 import review as review_client

CASE = ROOT / 'local/privacy548-server-install01'
SERVER = ROOT / 'local/privacy548-server01'
GAME = ROOT / 'local/privacy543-game01'
INSTALLER = ROOT / 'local/privacy542-server-installer01/Install Battle Aces Server.exe'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def review():
    assert review_client()['passed']
    run, form, launch = (read(CASE / 'verification.json'), read(CASE / 'form.json'),
                         read(CASE / 'owner-launch.json'))
    assert run['passed'] and run['recipe'] == 47
    assert run['installer_sha256'] == sha(INSTALLER)
    assert sha(CASE / 'NativeFormHost.exe') == sha(ROOT / 'local/privacy543-client-install01/NativeFormHost.exe')
    assert sha(CASE / 'NativeFormHost.cs') == sha(ROOT / 'local/privacy543-client-install01/NativeFormHost.cs')
    assert read(CASE / 'request.json') == {
        'game_directory': str(GAME), 'server_directory': str(SERVER)}
    assert (CASE / 'owner-job.ready').read_bytes() == b'owned job attached\n'
    assert form == run['form'] and form['passed'] and not form['error']
    assert all(form[key] for key in ('actual_native_install_click',
                                    'background_worker_observed',
                                    'controls_locked_while_busy',
                                    'progress_visible_while_busy',
                                    'elapsed_title_observed', 'controls_restored'))
    assert form['final_status'] == 'Installed. Open Start Server.exe in your server folder to host.'
    assert launch['create_suspended'] and launch['primary_thread_resumed']
    assert launch['create_return_tick'] <= launch['job_assigned_tick'] <= launch['resume_before_tick']
    assert launch['resume_previous_count'] == 1 and launch['exit_code'] == 0
    assert launch['owned_process_reaped'] and not launch['forced_cleanup']
    assert launch['job_final'] == run['job']
    assert launch['job_final'] == {'total_processes': 4, 'active_processes': 0,
                                   'total_terminated_processes': 0}
    assert verify(SERVER, 'server')
    verify_assets(SERVER / 'assets/build-37822')
    assert run['asset_manifest_sha256'] == sha(SERVER / 'assets/build-37822/asset-manifest.json')
    assert (SERVER / 'Start Server.exe').is_file()
    assert not (SERVER / 'config/private').exists()
    assert run['source_game_unchanged'] and not run['server_started']
    assert not run['private_keys_created']
    for name, digest in run['source_game_sha256'].items():
        assert sha(GAME / name) == digest
    return {'passed': True, 'recipe': 47, 'actual_native_install': True,
            'source_game_unchanged': True, 'server_started': False,
            'job': launch['job_final'],
            'run_sha256': sha(CASE / 'verification.json'),
            'asset_manifest_sha256': run['asset_manifest_sha256'],
            'full_d5_qualified': False}


if __name__ == '__main__':
    result = review()
    output = CASE / 'review549.json'
    if output.exists():
        assert read(output) == result
    else:
        output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
