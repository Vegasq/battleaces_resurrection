"""Experimental Linux host using release 174's unchanged Windows runtime in Wine.

Bypass the .NET installer UI, import an independent game copy, and provision TLS
with Linux OpenSSL. No system Wine prefix, desktop settings or firewall changes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys

from tools.package_integrity import verify
from tools.linux_wine import extract_payload, windows_path, wine_environment

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SHA256 = '268175028e7ae44a7698bb4d8325109b15db37237c39d9c542eb79a7c2912722'
PAYLOAD_SHA256 = '4c8ba7d2fca616b2ca38b3560d657edf6b7b2f26e4b2c9388ab60ee7943120b0'
INSTALLER_BYTES = 13579264
PAYLOAD_BYTES = 13549221
PACKAGE_NAME = 'battleaces-server-win64'


def runtime_command(package, *arguments):
    return ['wine', str(package / 'program/runtime/python.exe'), '-I', '-S', '-B',
            '-u', '-m', 'tools.package_server', *arguments]


def extract_installer(installer, destination):
    """Accept only the documented, hash-pinned 174 installer and ZIP resource."""
    return extract_payload(installer, destination, product='server',
                           installer_bytes=INSTALLER_BYTES, installer_sha256=INSTALLER_SHA256,
                           payload_bytes=PAYLOAD_BYTES, payload_sha256=PAYLOAD_SHA256)


def initialize_config(host):
    """Create missing RC configuration; preserve all existing config/key bytes."""
    from server.assets import verify_assets
    from server.configuration import load_config
    from server.credentials import _ensure_private_directory
    from server.tls_transport import load_server_context

    config = host / 'config/host.json'
    if config.exists():
        load_config(config)
        return config
    verify_assets(host / 'assets/build-37822')
    private = config.parent / 'private'
    _ensure_private_directory(private)
    directory = private / ('linux-tls-' + secrets.token_hex(12))
    _ensure_private_directory(directory)
    cert, key = directory / 'server.pem', directory / 'server.key'
    # OpenSSL writes only into a newly created owner-only directory. Its stderr
    # contains diagnostics, not key material, and is retained locally.
    with (directory / 'openssl.log').open('xb') as log:
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-noenc',
                        '-sha256', '-days', '3650', '-subj', '/CN=Battle Aces Linux Host',
                        '-keyout', str(key), '-out', str(cert)], check=True,
                       stdout=subprocess.DEVNULL, stderr=log, timeout=30)
    key.chmod(0o600)
    load_server_context(cert, key)
    value = dict(schema=2, access_mode='rc-open', listen_host='0.0.0.0', listen_port=47623,
                 assets_directory='../assets/build-37822', data_directory='../data',
                 certificate_file=cert.relative_to(config.parent).as_posix(),
                 private_key_file=key.relative_to(config.parent).as_posix(),
                 credential_directory=None, max_rooms=4, input_window=6,
                 diagnostic_audit=False, log_max_bytes=8388608, log_backups=4,
                 allow_insecure_loopback=False)
    # Publish a complete file exclusively. Never replace a concurrently created
    # host config, and keep relative paths valid in both Linux and Wine.
    temporary = config.parent / ('.linux-host-' + secrets.token_hex(12) + '.json')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    load_config(temporary)
    try:
        os.link(temporary, config)
    except FileExistsError:
        pass
    finally:
        temporary.unlink()
    load_config(config)
    return config


def write_launcher(root):
    path = root / 'Start Server.sh'
    if path.exists():
        return
    command = [sys.executable, '-m', 'tools.linux_server', 'start', '--root', str(root)]
    with path.open('x', encoding='utf-8') as stream:
        stream.write('#!/bin/sh\ncd ' + shlex.quote(str(ROOT)) + ' || exit 1\nexec ' +
                     shlex.join(command) + '\n')
    path.chmod(0o700)


def setup(root, installer, game):
    if root == game or root.is_relative_to(game) or game.is_relative_to(root):
        raise ValueError('Choose a new deployment directory separate from the source game')
    for name in ('Battle Aces.exe', 'GameAssembly.dll', 'Battle Aces_Data'):
        if not (game / name).exists():
            raise ValueError('Game folder is missing ' + name)
    root.mkdir(mode=0o700, parents=True)  # A failed setup is retained, never overwritten.
    package = extract_installer(installer, root / 'package')
    request = root / 'install-request.json'
    request.write_text(json.dumps(dict(game_directory=windows_path(game),
                                      server_directory=windows_path(root / 'host'))) + '\n')
    log_path = root / 'install.log'
    print('Copying and exporting game data. Progress and Wine diagnostics: ' + str(log_path), flush=True)
    with log_path.open('xb') as log:
        result = subprocess.run(runtime_command(package, 'install-server', '--request', windows_path(request)),
                                env=wine_environment(root), stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError('Setup failed; preserved working copy and log: ' + str(log_path))
    verify(root / 'host', 'server')
    initialize_config(root / 'host')
    write_launcher(root)
    (root / 'linux-setup.json').write_text(json.dumps(dict(
        schema=1, installer_sha256=INSTALLER_SHA256, payload_sha256=PAYLOAD_SHA256,
        wine=subprocess.check_output(['wine', '--version'], text=True).strip(),
        installed=True, server_started=False), indent=2) + '\n')
    print('Installed. Start with: ' + shlex.quote(str(root / 'Start Server.sh')))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('setup', 'start', 'check'))
    parser.add_argument('--root', type=Path, default=ROOT / 'local/linux-server')
    parser.add_argument('--installer', type=Path)
    parser.add_argument('--game-dir', type=Path)
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux'):
        parser.error('This wrapper is for Linux; use the native installer on Windows')
    for executable in ('wine', 'openssl'):
        if not shutil.which(executable):
            parser.error('Required command is missing: ' + executable)
    root = args.root.expanduser().resolve()
    try:
        if args.command == 'setup':
            if args.installer is None or args.game_dir is None:
                parser.error('setup requires --installer and --game-dir')
            setup(root, args.installer.expanduser().resolve(), args.game_dir.expanduser().resolve())
            return 0
        if args.installer is not None or args.game_dir is not None:
            parser.error('--installer and --game-dir apply only to setup')
        host = root / 'host'
        verify(host, 'server')
        if not (root / 'wineprefix/system.reg').is_file():
            raise ValueError('Deployment Wine prefix is missing; run setup in a new directory')
        initialize_config(host)
        write_launcher(root)
        command = (['wine', str(host / 'Start Server.exe')] if args.command == 'start'
                   else runtime_command(host, 'check'))
        os.chdir(host)
        os.execvpe(command[0], command, wine_environment(root))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Linux server: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
