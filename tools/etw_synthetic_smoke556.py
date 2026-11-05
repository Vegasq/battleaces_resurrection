"""Synthetic, local-only file/socket/child activity for ETW schema discovery.

Run only from Run-ETWSensorSmoke556.ps1 after its three collectors start.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time


def run(output: Path) -> dict:
    output = output.resolve(strict=True)
    token = secrets.token_hex(8)
    payload = (f'BA_ETW_556_{token}\n').encode('ascii')
    parent_file = output / f'parent-{token}.bin'
    child_file = output / f'child-{token}.bin'
    with parent_file.open('xb') as stream:
        stream.write(payload)
        stream.flush()
    assert parent_file.read_bytes() == payload

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(10)
    port = listener.getsockname()[1]
    received: list[bytes] = []
    error: list[str] = []

    def receive() -> None:
        try:
            with listener.accept()[0] as connection:
                connection.settimeout(10)
                received.append(connection.recv(128))
                connection.sendall(payload[::-1])
        except Exception as exc:
            error.append(repr(exc))

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=10) as client:
            client.sendall(payload)
            reply = client.recv(128)
    finally:
        listener.close()
        thread.join(timeout=10)
    assert not thread.is_alive() and not error and received == [payload]
    assert reply == payload[::-1]

    child_code = ('import pathlib,sys,os; '
                  'p=pathlib.Path(sys.argv[1]); '
                  'p.write_bytes(bytes.fromhex(sys.argv[2])); '
                  'print(os.getpid())')
    child = subprocess.run(
        [sys.executable, '-c', child_code, str(child_file), payload.hex()],
        capture_output=True, text=True, timeout=15, check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    assert child_file.read_bytes() == payload
    result = {
        'passed': True,
        'marker': payload.decode('ascii').strip(),
        'parent_pid': __import__('os').getpid(),
        'child_pid': int(child.stdout.strip()),
        'loopback_address': '127.0.0.1',
        'loopback_port': port,
        'parent_file': str(parent_file),
        'child_file': str(child_file),
        'payload_sha256': hashlib.sha256(payload).hexdigest(),
        'unix_end_time': time.time(),
    }
    (output / 'activity.json').write_text(json.dumps(result, indent=2) + '\n',
                                           encoding='utf-8')
    return result


if __name__ == '__main__':
    assert len(sys.argv) == 2
    print(json.dumps(run(Path(sys.argv[1]))))
