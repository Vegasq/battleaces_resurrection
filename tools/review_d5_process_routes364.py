"""Inventory direct child-launch routes in the current private Python package pair."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tools.build_windows_packages import CLIENT, SERVER
from tools.package_integrity import verify

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT/'local/privacy358-packages02'
CASES = (ROOT/'local/privacy361-connected05', ROOT/'local/privacy362-connected02')
OUTPUT = ROOT/'local/privacy364-process-routes01/verification.json'
PROCESS_CALLS = {
    'subprocess': {'Popen', 'run', 'call', 'check_call', 'check_output',
                   'getoutput', 'getstatusoutput'},
    'asyncio': {'create_subprocess_exec', 'create_subprocess_shell'},
    'os': {'startfile', 'system', 'popen', 'spawnl', 'spawnle', 'spawnlp',
           'spawnlpe', 'spawnv', 'spawnve', 'spawnvp', 'spawnvpe', 'execv',
           'execve', 'execvp', 'execvpe'},
}
EXPECTED = {
    ('client_patch/transport/launcher.py', 268, 'subprocess.Popen'),
    ('server/rc_host.py', 39, 'subprocess.run'),
    ('server/worker_client.py', 147, 'subprocess.Popen'),
    ('tools/package_client.py', 129, 'subprocess.run'),
    ('tools/package_client.py', 132, 'subprocess.run'),
    ('tools/package_client.py', 135, 'subprocess.run'),
    ('tools/server_installer.py', 56, 'subprocess.Popen'),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory() -> list[dict]:
    found = set()
    for name in sorted(set(CLIENT + SERVER)):
        if not name.endswith('.py'):
            continue
        tree = ast.parse((ROOT/name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.attr in PROCESS_CALLS.get(func.value.id, set())):
                found.add((name, node.lineno, ast.unparse(func)))
    assert found == EXPECTED, (sorted(found - EXPECTED), sorted(EXPECTED - found))
    return [dict(path=path, line=line, call=call) for path, line, call in sorted(found)]


def main() -> None:
    build = json.loads((PACKAGES/'build-report.json').read_text(encoding='utf-8'))
    assert build['versions']['game_build'] == 37822
    copied = {}
    for kind, names in (('client', CLIENT), ('server', SERVER)):
        package = PACKAGES/f'battleaces-{kind}-win64'
        assert verify(package, kind)
        assert sha(PACKAGES/build['packages'][kind]['archive']) == build['packages'][kind]['sha256']
        count = 0
        for name in names:
            if not Path(name).suffix in ('.py', '.ps1'):
                continue
            assert (ROOT/name).read_bytes() == (package/'program/app'/name).read_bytes(), name
            count += 1
        copied[kind] = count
    launcher = (ROOT/'client_patch/transport/launcher.py').read_text(encoding='utf-8')
    worker = (ROOT/'server/worker_client.py').read_text(encoding='utf-8')
    cert = (ROOT/'server/rc_host.py').read_text(encoding='utf-8')
    gui = (ROOT/'client_patch/launcher/Configure-Client.ps1').read_text(encoding='utf-8')
    rc_gui = (ROOT/'client_patch/launcher/Configure-RCClient.ps1').read_text(encoding='utf-8')
    ps_launcher = (ROOT/'client_patch/launcher/Launch-Client.ps1').read_text(encoding='utf-8')
    package_client = (ROOT/'tools/package_client.py').read_text(encoding='utf-8')
    server_installer = (ROOT/'tools/server_installer.py').read_text(encoding='utf-8')
    assert "result = [str(root / 'Battle Aces.exe')" in launcher
    assert 'return subprocess.Popen(argv, cwd=config[\'game_directory\']' in launcher
    assert 'args = [sys.executable, "-I", "-S", "-B", "-u", "-c", bootstrap' in worker
    assert "runpy.run_module('server.simulation_worker'" in worker
    assert "'crypto/Generate Certificate.exe'" in cert
    assert "'New-RCCertificate.ps1'" in cert
    assert "'-m','tools.package_client'" in gui and "'-m','tools.package_client'" in rc_gui
    assert "Start-Process -FilePath (Join-Path $root 'Battle Aces.exe')" in ps_launcher
    assert "PACKAGE/'Install Battle Aces.exe'" in package_client
    assert "client_patch/launcher/Configure-Client.ps1'" in package_client
    assert "client_patch/launcher/Launch-Client.ps1'" in package_client
    assert "command=[str(game/'Battle Aces.exe'),'-offline-practice','-export-server-assets'" in server_installer
    runs = []
    for path in CASES:
        report_path = path/'verification.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        assert report['passed'] and report['rc_open'] and report['humans'] == 2
        assert report['mode'] in (2, 5) and not report['forced_cleanup']
        assert all(row['active_processes'] == row['total_terminated_processes'] == 0
                   for row in report['jobs'])
        assert [row['total_processes'] for row in report['jobs']] == [5, 2, 2]
        runs.append(dict(mode=report['mode'], report_sha256=sha(report_path),
                         job_process_totals=[row['total_processes'] for row in report['jobs']]))
    assert [row['mode'] for row in runs] == [5, 2]
    result = dict(passed=True, scope='Direct packaged Python/PowerShell child-launch sites and selected owned job accounting; native WebView/OS/indirect descendants excluded',
                  build_report_sha256=sha(PACKAGES/'build-report.json'),
                  source_files_compared=copied,
                  direct_python_process_calls=inventory(),
                  powershell_client_setup_spawns_bundled_package_client=True,
                  powershell_client_launcher_spawns_game=True,
                  certificate_bootstrap_spawns_crypto_helper_or_powershell=True,
                  client_setup_commands_spawn_installer_or_powershell=True,
                  server_asset_export_spawns_owned_game=True,
                  server_worker_spawns_bundled_python=True,
                  transport_launcher_spawns_configured_game=True,
                  selected_owned_runs=runs,
                  native_webview_and_os_descendants_unclassified=True,
                  whole_tree_qualified=False, full_d5_qualified=False)
    assert not OUTPUT.exists()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'direct_python_process_calls': len(result['direct_python_process_calls'])}))


if __name__ == '__main__':
    main()
