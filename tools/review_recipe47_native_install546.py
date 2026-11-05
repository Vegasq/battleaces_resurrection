"""Bind private recipe47 installer shells, actual client install, and ordinary restart."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from client_patch.patcher.telemetry import COMPONENTS, RECIPE_VERSION, RUNTIME_VALIDATED
from client_patch.transport.launcher import verify_game
from tools.package_integrity import verify
from tools.review_unity_post512 import ROOT, GAME as PRIOR_GAME, review as review_current


PACKAGES = ROOT/'local/privacy512-packages01'
GAME = ROOT/'local/privacy543-game01'
SHELL = ROOT/'local/privacy542-qualification01/verification.json'
INSTALL = ROOT/'local/privacy543-client-install01/verification.json'
FRESH = ROOT/'local/privacy544-installed-startup01/verification.json'
RESTART = ROOT/'local/privacy545-installed-restart01/verification.json'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    assert RECIPE_VERSION == 47 and RUNTIME_VALIDATED is False
    assert review_current()['passed']
    build = read(PACKAGES/'build-report.json')
    assert build['source']['dirty'] and build['versions']['package']=='0.3.0-rc1.7'
    shell, install = read(SHELL), read(INSTALL)
    assert shell['passed'] and shell['recipe']==47 and shell['source']==build['source']
    assert install['passed'] and install['recipe']==47 and install['fresh_owned_install']
    assert install['form']['passed'] and install['form']['actual_native_install_click']
    assert install['form']['background_worker_observed'] and install['form']['controls_locked_while_busy']
    assert install['form']['progress_visible_while_busy'] and install['form']['controls_restored']
    assert install['original_backups_checked'] and not install['launch']['forced_cleanup']
    assert install['job']['total_processes']==3
    assert install['job']['active_processes']==install['job']['total_terminated_processes']==0
    manifests={}
    for product in ('client','server'):
        package=PACKAGES/f'battleaces-{product}-win64'
        manifests[product]=verify(package,product)
        archive=PACKAGES/build['packages'][product]['archive']
        assert sha(archive)==shell['products'][product]['archive_sha256']==build['packages'][product]['sha256']
        folder=ROOT/f'local/privacy542-{product}-installer01'
        exe=folder/('Install Battle Aces Server.exe' if product=='server' else 'Install Battle Aces.exe')
        receipt=read(folder/'installer-build.json')
        assert sha(exe)==receipt['installer_sha256']==shell['products'][product]['installer_sha256']
        assert receipt['payload_sha256']==sha(archive)
        for label in ('ui','payload'):
            check=shell['products'][product]['checks'][label]
            assert check['exit_code']==0
            assert check['job']['active_processes']==check['job']['total_terminated_processes']==0
            assert sha(ROOT/f'local/privacy542-qualification01/{product}-{label}.json')==check['report_sha256']
        assert shell['products'][product]['package_files']==len(manifests[product]['files'])
    assert install['installer_sha256']==shell['products']['client']['installer_sha256']
    runtime=Path(install['runtime'])
    assert runtime.is_relative_to(GAME/'.battleaces-resurrection/client-runtime')
    assert verify(runtime,'client')==manifests['client']
    assert sha(GAME/'.battleaces-resurrection/patch-manifest.json')==install['manifest_sha256']
    manifest=read(GAME/'.battleaces-resurrection/patch-manifest.json')
    assert manifest['telemetry']['recipe_version']==47
    assert manifest['telemetry']['runtime_validated'] is False
    assert manifest['components']['GameAssembly.dll']['telemetry_guards']==108
    assert manifest['components']['UnityPlayer.dll']['telemetry_guards']==66
    for name in COMPONENTS:
        assert (GAME/name).read_bytes()==(PRIOR_GAME/name).read_bytes()
    assert sha(GAME/'GameAssembly.dll')==install['installed_gameassembly_sha256']
    assert sha(GAME/'UnityPlayer.dll')==install['installed_unity_sha256']
    assert sha(GAME/'BattleAcesOffline.dll')==sha(PACKAGES/'battleaces-client-win64/program/client-helper/BattleAcesOffline.dll')
    verify_game(GAME,community=True,bridge_version=2,unified=True,player_features=True)
    runs=[]
    for path in (FRESH,RESTART):
        row=read(path)
        assert row['passed'] and row['installed_launcher'] and row['window_close_exit_zero']
        assert row['ordinary_features_ready'] and row['no_match_or_diagnostic_actions']
        assert row['menu_ready_seconds']>0 and row['idle_seconds_observed']>=30
        assert row['wrapper_reaped'] and row['game_reaped'] and not row['forced_cleanup']
        assert all(row[key] for key in ('source_files_unchanged','package_files_unchanged',
                                        'config_unchanged','shared_settings_unchanged'))
        assert Path(row['package'])==runtime and Path(row['game'])==GAME
        runs.append(dict(report_sha256=sha(path),profile=row['profile'],
                         menu_ready_seconds=row['menu_ready_seconds'],
                         idle_seconds=row['idle_seconds_observed']))
    assert runs[0]['profile']==runs[1]['profile']
    return dict(passed=True,recipe=47,guard_count=sum(len(c.patches) for c in COMPONENTS.values()),
                installer_shell_report_sha256=sha(SHELL),install_report_sha256=sha(INSTALL),
                client_installer_sha256=install['installer_sha256'],
                server_installer_sha256=shell['products']['server']['installer_sha256'],
                installed_gameassembly_sha256=sha(GAME/'GameAssembly.dll'),
                installed_unity_sha256=sha(GAME/'UnityPlayer.dll'),
                fresh_and_restart=runs,actual_client_install=True,
                server_install=False,published=False,whole_d5_qualified=False)


if __name__=='__main__':
    result=review()
    output=ROOT/'local/privacy546-native-install-review.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
