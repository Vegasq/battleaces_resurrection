"""Bind the connected workers' Simulation.dll to its PE import boundary."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

from tools.review_d5_proactor_bytes412 import CASE, PACKAGES, GAME, ASSETS
from tools.review_d5_connected_pair338 import ROOT, run

OUT = ROOT / 'local/privacy417-simulation-imports01'
DLL = ASSETS / 'Simulation.dll'
SHA = '107bb83dc416a16492277392c50104660e34c48911345ae2e0d5afe3929a07fb'
LLVM_READOBJ = Path(r'C:\Program Files\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\WebGLSupport\BuildTools\Emscripten\llvm\llvm-readobj.exe')


def review() -> dict:
    connected = run(CASE, PACKAGES, GAME, ASSETS)
    assert connected['passed']
    report = json.loads((CASE / 'server/server-driver.json').read_text(encoding='utf-8'))
    assert report['passed'] and len(report['workers']) == 2
    assert all(row['reaped'] and row['exit_code'] == 0 and
               row['simulation_sha256'] == SHA for row in report['workers'])
    raw = DLL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    assert LLVM_READOBJ.is_file()
    imports = subprocess.check_output([str(LLVM_READOBJ), '--coff-imports', str(DLL)], text=True)
    headers = subprocess.check_output([str(LLVM_READOBJ), '--file-headers', str(DLL)], text=True)
    names = re.findall(r'^  Name: (.+)$', imports, re.M)
    symbols = re.findall(r'^  Symbol: ([^ ]+) ', imports, re.M)
    assert names == ['KERNEL32.dll']
    assert len(symbols) == 121 and len(set(symbols)) == len(symbols)
    assert {'GetProcAddress', 'LoadLibraryA', 'LoadLibraryExW'} <= set(symbols)
    assert 'DelayImportDescriptorRVA: 0x0' in headers
    assert 'DelayImportDescriptorSize: 0x0' in headers
    assert not any(name.lower() in {'ws2_32.dll', 'winhttp.dll', 'wininet.dll'} for name in names)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'imports.txt').write_text(imports, encoding='utf-8')
    (OUT / 'headers.txt').write_text(headers, encoding='utf-8')
    result = dict(passed=True, simulation_sha256=SHA,
                  worker_pids=[row['pid'] for row in report['workers']],
                  ordinary_import_dlls=names, ordinary_import_symbols=len(symbols),
                  delay_import_directory_empty=True,
                  dynamic_load_apis=sorted({'GetProcAddress', 'LoadLibraryA', 'LoadLibraryExW'}),
                  native_dynamic_lookup_and_os_wire_unresolved=True,
                  full_d5_qualified=False)
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    print(json.dumps(review(), sort_keys=True))
