"""Install release 174's client from Linux without the GUI installer or game launch.

Setup copies the game into a fresh deployment and runs the original bundled
installer backend in headless Wine. Only the explicit start command launches
the game. Source game files, personal saves and existing deployments are kept.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from client_patch.transport.launcher import native_storage_preflight
from client_patch.transport.player_name import chosen_name
from server.tls_transport import normalize_server_name
from tools.linux_wine import extract_payload, windows_path, wine_environment
from tools.package_integrity import verify
from tools.server_installer import copy_game

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_SHA256 = 'd85476da0ffce2fa9d491ea5e3efb7818b0e607b352c7089239c94806ed48e0d'
PAYLOAD_SHA256 = '1836ac93447781d5a6ce55585c28530cab2b23e4eacbb09416fa5c38fde5a6f4'
INSTALLER_BYTES = 13401088
PAYLOAD_BYTES = 13371286
PACKAGE_NAME = 'battleaces-client-win64'


def extract_installer(installer, destination):
    return extract_payload(installer, destination, product='client',
                           installer_bytes=INSTALLER_BYTES, installer_sha256=INSTALLER_SHA256,
                           payload_bytes=PAYLOAD_BYTES, payload_sha256=PAYLOAD_SHA256)


def python_command(package, *arguments):
    return ['wine', str(package / 'program/runtime/python.exe'), '-I', '-S', '-B', '-u', *arguments]


def installed_runtime(root):
    package = root / 'package' / PACKAGE_NAME
    verify(package, 'client')
    manifest = (package / 'package-manifest.json').read_bytes()
    identity = hashlib.sha256(manifest).hexdigest()[:20]
    runtime = root / 'game/.battleaces-resurrection/client-runtime' / identity
    verify(runtime, 'client')
    if (runtime / 'package-manifest.json').read_bytes() != manifest:
        raise ValueError('Installed client runtime differs from the selected release')
    return runtime


def check_command(root, runtime):
    # The installed runtime's _.pth selects production imports. This check hashes
    # files; it never loads the game or native helper DLL.
    script = (
        "import json,sys;from pathlib import Path;"
        "from client_patch.transport.launcher import verify_game,read_json,native_storage_preflight;"
        "from client_patch.transport import rc_setup;"
        "game=Path(sys.argv[1]).resolve();config=game/'.battleaces-resurrection/client-config.json';"
        "settings=rc_setup.settings(read_json(config,32768),config);"
        "assert settings['game_directory']==game,'Client game binding differs';"
        "native_storage_preflight(settings);"
        "verify_game(game,community=True,bridge_version=2,unified=True,player_features=True);"
        "print(json.dumps(dict(passed=True,game_started=False,scope='installed files and settings only')))"
    )
    return python_command(runtime, '-c', script, windows_path(root / 'game'))


def write_launcher(root):
    path = root / 'Start Battle Aces.sh'
    command = [sys.executable, '-m', 'tools.linux_client', 'start', '--root', str(root)]
    with path.open('x', encoding='utf-8') as stream:
        stream.write('#!/bin/sh\ncd ' + shlex.quote(str(ROOT)) + ' || exit 1\nexec ' +
                     shlex.join(command) + '\n')
    path.chmod(0o700)


def setup(root, installer, game, *, server='', name=None):
    if root == game or root.is_relative_to(game) or game.is_relative_to(root):
        raise ValueError('Choose a new deployment directory separate from the source game')
    for leaf in ('Battle Aces.exe', 'GameAssembly.dll', 'Battle Aces_Data'):
        if not (game / leaf).exists():
            raise ValueError('Game folder is missing ' + leaf)
    server = normalize_server_name(server.strip()) if server.strip() else ''
    if name is not None:
        name = chosen_name(name)
    working = root / 'game'
    native_storage_preflight(dict(game_directory=windows_path(working), local_profile='default'))
    root.mkdir(mode=0o700, parents=True)
    package = extract_installer(installer, root / 'package')
    print('Copying game files into ' + str(working) + '. The source game stays unchanged.', flush=True)
    copy_game(game, working)
    request = dict(game_directory=windows_path(working), server_host=server)
    if name is not None:
        request['display_name'] = name
    request_path = root / 'install-request.json'
    request_path.write_text(json.dumps(request) + '\n')
    log_path = root / 'install.log'
    print('Installing without GUI/game launch. Progress: ' + str(log_path), flush=True)
    environment = wine_environment(root, headless=True)
    command = python_command(package, '-m', 'tools.package_client', 'install-game',
                             '--request', windows_path(request_path))
    with log_path.open('xb') as log:
        result = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError('Installation failed; preserved working copy and log: ' + str(log_path))
    runtime = installed_runtime(root)
    with (root / 'check.log').open('xb') as log:
        result = subprocess.run(check_command(root, runtime), env=environment,
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError('Installed file verification failed; see ' + str(root / 'check.log'))
    write_launcher(root)
    (root / 'linux-setup.json').write_text(json.dumps(dict(
        schema=1, installer_sha256=INSTALLER_SHA256, payload_sha256=PAYLOAD_SHA256,
        wine=subprocess.check_output(['wine', '--version'], text=True).strip(),
        installed=True, game_started=False, files_verified=True), indent=2) + '\n')
    print('Installed and verified. Game was not launched. Start explicitly with: ' +
          shlex.quote(str(root / 'Start Battle Aces.sh')))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('setup', 'check', 'start'))
    parser.add_argument('--root', type=Path, default=ROOT / 'local/linux-client')
    parser.add_argument('--installer', type=Path)
    parser.add_argument('--game-dir', type=Path)
    parser.add_argument('--server', help='server IP or DNS name; omit for local AI only')
    parser.add_argument('--name', help='player name; defaults to the current account name')
    args = parser.parse_args(argv)
    if not sys.platform.startswith('linux'):
        parser.error('This wrapper is for Linux; use the native installer on Windows')
    if not shutil.which('wine'):
        parser.error('Required command is missing: wine')
    root = args.root.expanduser().resolve()
    try:
        if args.command == 'setup':
            if args.installer is None or args.game_dir is None:
                parser.error('setup requires --installer and --game-dir')
            setup(root, args.installer.expanduser().resolve(), args.game_dir.expanduser().resolve(),
                  server=args.server or '', name=args.name)
            return 0
        if any(value is not None for value in (args.installer, args.game_dir, args.server, args.name)):
            parser.error('--installer, --game-dir, --server and --name apply only to setup')
        runtime = installed_runtime(root)
        if not (root / 'wineprefix/system.reg').is_file():
            raise ValueError('Deployment Wine prefix is missing; run setup in a new directory')
        if args.command == 'check':
            command = check_command(root, runtime)
        else:
            if not (root / 'linux-setup.json').is_file():
                raise ValueError('Client setup did not complete; inspect install.log and check.log')
            command = python_command(runtime, '-m', 'tools.package_client', 'start', '--config',
                                     windows_path(root / 'game/.battleaces-resurrection/client-config.json'))
        os.chdir(root / 'game')
        os.execvpe(command[0], command, wine_environment(root, headless=args.command == 'check'))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Linux client: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
