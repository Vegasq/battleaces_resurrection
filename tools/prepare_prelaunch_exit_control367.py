"""Prepare one inert self-TerminateProcess positive control for the exit adapter."""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

from tools.frida_prelaunch_exit367 import build_source

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT/'local') and not output.exists()
    output.mkdir(parents=True)
    config = dict(image=str(Path(sys.executable).resolve()),
                  runId=secrets.token_hex(16),
                  fileRoots=[str(output/'owned-queue')],eventLimit=1000)
    script = output/'observer.js'
    script.write_text(build_source(config),encoding='utf-8')
    code = ('import ctypes;'
            'k=ctypes.WinDLL("kernel32");'
            'k.GetCurrentProcess.restype=ctypes.c_void_p;'
            'k.TerminateProcess.argtypes=[ctypes.c_void_p,ctypes.c_uint];'
            'k.TerminateProcess(k.GetCurrentProcess(),0)')
    request = dict(mode='spawn',program=config['image'],argv=['-B','-c',code],
                   script=str(script),config=config,
                   source_sha256=hashlib.sha256(script.read_bytes()).hexdigest())
    (output/'request.json').write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'prepared':True,'output':str(output)}))


if __name__=='__main__':main()
