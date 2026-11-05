"""Bind direct Python child-launch and explicit FFI routes to recipe47 packages."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tools.build_windows_packages import CLIENT, SERVER
from tools.package_integrity import verify
from tools.review_d5_packaged_ffi416 import EXPECTED_FFI, EXPECTED_MODULES, CONSTRUCTORS
from tools.review_d5_process_routes364 import inventory
from tools.review_recipe47_wire526 import review as wire_review

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / 'local/privacy526-public1-wire01'
PACKAGES = ROOT / 'local/privacy512-packages01'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def review() -> dict:
    wire = wire_review()
    assert wire['passed'] and wire['worker_count'] == 2
    routes = inventory()
    assert len(routes) == 7
    copied = {}
    for kind, names in (('client', CLIENT), ('server', SERVER)):
        package = PACKAGES / f'battleaces-{kind}-win64'
        assert verify(package, kind)
        for name in names:
            if Path(name).suffix in ('.py', '.ps1'):
                assert (ROOT / name).read_bytes() == (package / 'program/app' / name).read_bytes()
        copied[kind] = len(names)
    observed = set()
    for driver, expected in EXPECTED_MODULES.items():
        report = read(CASE / driver / f'{driver.split("-")[0]}-driver.json')
        assert report['passed'] and set(report['production_modules']) == expected
        kind = 'server' if driver == 'server' else 'client'
        package = PACKAGES / f'battleaces-{kind}-win64'
        manifest = read(package / 'package-manifest.json')
        for module, record in report['production_modules'].items():
            path = Path(record['path']).resolve()
            assert path.is_relative_to((package / 'program/app').resolve())
            relative = path.relative_to(package).as_posix()
            assert sha(path) == record['sha256'] == manifest['files'][relative]['sha256']
            tree = ast.parse(path.read_bytes(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in CONSTRUCTORS:
                    continue
                assert node.args and isinstance(node.args[0], ast.Constant)
                assert isinstance(node.args[0].value, str)
                assert node.func.attr == 'WinDLL'
                observed.add((module, node.args[0].value.lower()))
    assert observed == EXPECTED_FFI
    return {'passed': True, 'package_files': copied,
            'direct_python_process_calls': routes,
            'production_modules_per_driver': 6,
            'explicit_ffi_dlls': sorted({dll for _, dll in observed}),
            'wire_report_sha256': wire['report_sha256'],
            'scope': 'current package direct Python child-launch and selected reported-module explicit ctypes constructors; indirect/extension/native/OS broker routes and actual wire remain open'}


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
