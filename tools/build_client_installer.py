"""Build our Windows Forms installer; optionally embed the clean client ZIP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('client_patch/installer/Installer.cs', 'tools/build_client_installer.py')


def build(output, payload=None, *, server=False):
    output = Path(output).resolve()
    if not any(output.is_relative_to(ROOT/name) for name in ('build', 'local', 'dist')):
        raise ValueError('Installer output must be under build/, local/ or dist/')
    output.mkdir(parents=True, exist_ok=False)
    framework = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'Microsoft.NET/Framework64/v4.0.30319'
    compiler = framework/'csc.exe'
    target = output/('Install Battle Aces Server.exe' if server else 'Install Battle Aces.exe')
    source_hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}
    arguments = [str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
                 '/warnaserror+', '/out:'+str(target)]
    if server: arguments.append('/define:SERVER_INSTALLER')
    for name in ('System.Windows.Forms', 'System.Drawing', 'System.Web.Extensions',
                 'System.IO.Compression', 'System.IO.Compression.FileSystem'):
        arguments.append('/reference:'+str(framework/(name+'.dll')))
    if payload is not None:
        payload = Path(payload).resolve()
        if not payload.is_file() or payload.stat().st_size > 32*1024*1024: raise ValueError('Invalid client payload ZIP')
        arguments.append('/resource:'+str(payload)+',BattleAces.Payload.zip')
    arguments.append(str(ROOT/'client_patch/installer/Installer.cs'))
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=60)
    if result.returncode: raise ValueError('Installer compilation failed: '+result.stdout+result.stderr)
    if source_hashes != {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}:
        raise ValueError('Installer source changed during compilation')
    receipt = dict(schema=1, installer_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                   product='server' if server else 'client',
                   source_sha256=source_hashes, powershell_required=False,
                   payload_sha256=hashlib.sha256(payload.read_bytes()).hexdigest() if payload else None)
    (output/'installer-build.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--payload', type=Path)
    parser.add_argument('--server', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.payload, server=args.server), indent=2))
