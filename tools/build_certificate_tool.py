"""Compile the native Windows certificate helper, without PowerShell scripts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
SOURCES=('server/launcher/certificate_tool.cs','tools/build_certificate_tool.py')


def build(output):
    output=Path(output).resolve()
    if not any(output.is_relative_to(ROOT/p) for p in ('local','build','dist')): raise ValueError('Choose a local build output')
    output.mkdir(parents=True,exist_ok=False)
    framework=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'Microsoft.NET/Framework64/v4.0.30319'
    executable=output/'Generate Certificate.exe'
    before={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES}
    command=[str(framework/'csc.exe'),'/nologo','/target:exe','/platform:x64','/optimize+','/warnaserror+',
             '/reference:'+str(framework/'System.Web.Extensions.dll'),'/out:'+str(executable),str(ROOT/SOURCES[0])]
    result=subprocess.run(command,capture_output=True,text=True,timeout=60)
    if result.returncode: raise ValueError(result.stdout+result.stderr)
    if before!={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES}: raise ValueError('Sources changed during build')
    report=dict(schema=1,source_sha256=before,sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
    (output/'certificate-build.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().output),indent=2))
