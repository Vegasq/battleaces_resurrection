"""First-run RC host configuration; self-signed TLS, no player enrollment."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import xml.etree.ElementTree as ET

from .configuration import load_config, ConfigurationError
from . import credentials as private
from .tls_transport import load_server_context


def _der(tag, body):
    length = len(body)
    encoded = bytes([length]) if length < 128 else bytes([128 + (length.bit_length()+7)//8]) + length.to_bytes((length.bit_length()+7)//8, 'big')
    return bytes([tag]) + encoded + body


def _integer(raw):
    raw = raw.lstrip(b'\0') or b'\0'
    if raw[0] & 128: raw = b'\0' + raw
    return _der(2, raw)


def _pem(label, raw):
    encoded = base64.b64encode(raw)
    return b'-----BEGIN ' + label + b'-----\n' + b'\n'.join(encoded[i:i+64] for i in range(0, len(encoded), 64)) + b'\n-----END ' + label + b'-----\n'


def generate_certificate():
    """Return certificate/key bytes only; never print subprocess output or keys."""
    shell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    native = Path(__file__).resolve().parents[2] / 'crypto/Generate Certificate.exe'
    command = ([str(native), '--pipe-certificate'] if native.is_file() else
               [str(shell), '-NoProfile', '-NonInteractive', '-File', str(Path(__file__).with_name('New-RCCertificate.ps1'))])
    result = subprocess.run(command,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode or len(result.stdout) > 32768:
        raise ConfigurationError('Windows could not create the RC server certificate')
    try:
        value = json.loads(result.stdout.decode('utf-8-sig'))
        root = ET.fromstring(value['key_xml'])
        integers = [_integer(b'\0')] + [_integer(base64.b64decode(root.findtext(name), validate=True))
                    for name in ('Modulus', 'Exponent', 'D', 'P', 'Q', 'DP', 'DQ', 'InverseQ')]
        return (_pem(b'CERTIFICATE', base64.b64decode(value['certificate'], validate=True)),
                _pem(b'RSA PRIVATE KEY', _der(48, b''.join(integers))))
    except (KeyError, ValueError, TypeError, ET.ParseError):
        raise ConfigurationError('Windows returned an invalid RC server certificate') from None


def initialize(path, assets):
    """Only create a missing config; existing host settings/keys are never changed."""
    path, assets = Path(path).resolve(), Path(assets).resolve()
    if path.exists(): return load_config(path)
    if not (assets / 'asset-manifest.json').is_file():
        raise ConfigurationError('Import your supported local game assets before starting the server')
    path.parent.mkdir(parents=True, exist_ok=True)
    directory = path.parent / 'private' / ('rc-tls-' + secrets.token_hex(12))
    private._ensure_private_directory(path.parent / 'private')
    private._ensure_private_directory(directory)
    certificate, key = generate_certificate()
    cert_path, key_path = directory / 'server.pem', directory / 'server.key'
    private._write_file(cert_path, certificate)
    private._write_file(key_path, key)
    load_server_context(cert_path, key_path)
    value = dict(schema=2, access_mode='rc-open', listen_host='0.0.0.0', listen_port=47623,
                 assets_directory=str(assets), data_directory=str(path.parent.parent / 'data'),
                 certificate_file=str(cert_path), private_key_file=str(key_path), credential_directory=None,
                 max_rooms=4, input_window=6, diagnostic_audit=False, log_max_bytes=8388608,
                 log_backups=4, allow_insecure_loopback=False,
                 dashboard_host='127.0.0.1', dashboard_port=47624)
    # Exclusive publication: never replace a configured server, including races.
    temporary = directory / 'host.json'
    temporary.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    load_config(temporary)  # Validate all paths before publishing.
    try:
        with temporary.open('r+b') as stream: stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic, exclusive publication on the same volume.
    except FileExistsError: pass
    return load_config(path)
