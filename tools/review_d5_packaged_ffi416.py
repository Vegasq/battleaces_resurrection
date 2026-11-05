"""Classify explicit FFI constructors in the 412 packaged Python driver modules."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tools.review_d5_proactor_bytes412 import CASE, PACKAGES, GAME, ASSETS
from tools.review_d5_connected_pair338 import ROOT, run

OUT = ROOT / 'local/privacy416-packaged-ffi01'
EXPECTED_MODULES = {
    'server': {'server.credentials', 'server.dedicated_server', 'server.host',
               'server.host_audit', 'server.tls_transport', 'server.worker_client'},
    'client-0': {'client_patch.transport.bridge', 'client_patch.transport.client',
                 'client_patch.transport.launcher', 'client_patch.transport.rc_setup',
                 'server.credentials', 'tools.package_integrity'},
    'client-1': {'client_patch.transport.bridge', 'client_patch.transport.client',
                 'client_patch.transport.launcher', 'client_patch.transport.rc_setup',
                 'server.credentials', 'tools.package_integrity'},
}
EXPECTED_FFI = {
    ('server.credentials', 'kernel32'),
    ('server.credentials', 'advapi32'),
    ('server.worker_client', 'kernel32'),
}
CONSTRUCTORS = {'WinDLL', 'CDLL', 'OleDLL', 'PyDLL'}


def review() -> dict:
    connected = run(CASE, PACKAGES, GAME, ASSETS)
    assert connected['passed']
    findings = {}
    for driver, expected in EXPECTED_MODULES.items():
        report = json.loads((CASE / driver / f'{driver.split("-")[0]}-driver.json').read_text(encoding='utf-8'))
        assert report['passed'] and set(report['production_modules']) == expected
        package = PACKAGES / ('battleaces-server-win64' if driver == 'server'
                              else 'battleaces-client-win64')
        inventory = json.loads((package / 'package-manifest.json').read_text(encoding='utf-8'))
        rows = []
        for module, record in sorted(report['production_modules'].items()):
            path = Path(record['path']).resolve()
            assert path.is_relative_to((package / 'program/app').resolve())
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            assert digest == record['sha256']
            rel = path.relative_to(package).as_posix()
            assert digest == inventory['files'][rel]['sha256']
            tree = ast.parse(raw, filename=str(path))
            calls = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in CONSTRUCTORS:
                    continue
                assert len(node.args) >= 1 and isinstance(node.args[0], ast.Constant)
                assert isinstance(node.args[0].value, str)
                calls.append(dict(kind=node.func.attr, dll=node.args[0].value.lower(),
                                  line=node.lineno))
            rows.append(dict(module=module, relative_path=rel, sha256=digest,
                             explicit_ffi_constructors=calls))
        findings[driver] = rows
    unique = {(row['module'], call['dll']) for rows in findings.values()
              for row in rows for call in row['explicit_ffi_constructors']}
    assert unique == EXPECTED_FFI
    assert all(call['kind'] == 'WinDLL' for rows in findings.values()
               for row in rows for call in row['explicit_ffi_constructors'])
    result = dict(passed=True, case='privacy412-proactor-pair01',
                  package_source_bound=True, reviewed_modules=findings,
                  explicit_ffi_dlls=sorted(set(dll for _, dll in unique)),
                  direct_network_dll_constructor_in_selected_modules=False,
                  other_imports_extensions_dynamic_calls_and_os_wire_unresolved=True,
                  full_d5_qualified=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    result = review()
    print(json.dumps(dict(passed=True, modules={name: len(rows)
                  for name, rows in result['reviewed_modules'].items()},
                  explicit_ffi_dlls=result['explicit_ffi_dlls'])))
