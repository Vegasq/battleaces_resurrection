"""Install the complete client beside the game and publish its normal launcher."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sys

from .package_integrity import verify, ordinary_file, PackageError
from client_patch.patcher.patch_client import contained_path, install as patch_game, atomic_write
from client_patch.patcher.bundle_loading import console_progress
from client_patch.transport import client, rc_setup, launcher
from client_patch.transport.player_name import default_name, chosen_name

LAUNCHER = 'Start Battle Aces.cmd'
MARKER = b'rem BA_RESURRECTION_GAME_LAUNCHER_V1'
CONFIG = '.battleaces-resurrection/client-config.json'


def uninstall(game):
    game=Path(game).expanduser().resolve()
    target=contained_path(game,LAUNCHER)
    script=target.read_bytes() if target.exists() else None
    if script is not None and (MARKER not in script or len(script)>4096):
        raise PackageError('An unrelated Start Battle Aces.cmd exists; it was preserved')
    manifest=launcher.read_json(game/'.battleaces-resurrection/patch-manifest.json',131072)
    helper=contained_path(game,'BattleAcesOffline.dll')
    if helper.exists() and hashlib.sha256(helper.read_bytes()).hexdigest()!=manifest.get('helper_sha256'):
        raise PackageError('Client helper changed; original files and helper were preserved')
    print('Restoring verified original game files...',file=sys.stderr,flush=True)
    result=patch_game(game,restore=True,progress=console_progress)
    if result.get('state')!='restored': raise PackageError('Original game restore did not complete')
    # Only our known launcher/helper are removed after the verified restoration.
    # Retain profiles,original backups,config and cached runtime for recovery.
    if target.exists():
        if target.read_bytes()!=script: raise PackageError('Launcher changed during restore; it was preserved')
        target.unlink()
    helper.unlink(missing_ok=True)
    return dict(uninstalled=True,original_game_restored=True,saves_preserved=True,
                recovery_directory=str(game/'.battleaces-resurrection'))


def launcher_bytes(runtime_relative):
    # Only an authored relative path with a hexadecimal version ID enters CMD.
    import re
    if not re.fullmatch(r'\.battleaces-resurrection/client-runtime/[0-9a-f]{20}', runtime_relative):
        raise PackageError('Invalid installed runtime path')
    runtime = runtime_relative.replace('/', '\\')
    return ('@echo off\r\nsetlocal DisableDelayedExpansion\r\n' + MARKER.decode() + '\r\n'
            f'"%~dp0{runtime}\\program\\runtime\\python.exe" -I -B -m tools.package_client start '
            '--config "%~dp0.battleaces-resurrection\\client-config.json"\r\n'
            'set "BA_CLIENT_EXIT=%errorlevel%"\r\n'
            'if not "%BA_CLIENT_EXIT%"=="0" pause\r\n'
            'exit /b %BA_CLIENT_EXIT%\r\n').encode('ascii')


def install(package, request):
    package = Path(package).resolve()
    inventory = verify(package, 'client')
    required = {'game_directory', 'server_host'}
    if not isinstance(request, dict) or not required <= set(request) <= required | {'display_name'}:
        raise PackageError('Choose the game folder, server IP and player name')
    if not all(isinstance(value, str) for value in request.values()):
        raise PackageError('Game folder and server IP must be text')
    game = Path(request['game_directory']).expanduser().resolve()
    if not (game / 'Battle Aces.exe').is_file(): raise PackageError('Choose the folder containing Battle Aces.exe')
    # Validate the normal native storage boundary before patching/copying anything.
    config = contained_path(game, CONFIG)
    target = contained_path(game, LAUNCHER)
    before_config = config.read_bytes() if config.exists() else None
    before_launcher = target.read_bytes() if target.exists() else None
    if before_launcher is not None and (MARKER not in before_launcher or len(before_launcher) > 4096):
        raise PackageError('An unrelated Start Battle Aces.cmd exists; keep it and choose another working copy')
    previous = launcher.read_json(config, 32768) if before_config is not None else {}
    if previous: client.local_settings(previous, config)
    name = previous['display_name'] if previous else default_name()
    if 'display_name' in request: name = chosen_name(request['display_name'])
    settings = dict(schema=4, game_directory=str(game), server_host=request['server_host'].strip(),
                    server_port=previous.get('server_port', 47623), display_name=name,
                    local_profile=previous.get('local_profile', 'default'), room=previous.get('room', 'community'))
    validated = rc_setup.settings(settings, config)
    launcher.native_storage_preflight(client.local_settings(settings, config))
    settings['server_host'] = validated['server_host']
    identity = hashlib.sha256((package/'package-manifest.json').read_bytes()).hexdigest()[:20]
    relative = '.battleaces-resurrection/client-runtime/' + identity
    runtime = contained_path(game, relative)
    if package == runtime or package.is_relative_to(runtime):
        raise PackageError('Run the installer from its extracted package or standalone executable')
    script = launcher_bytes(relative)
    print('Preparing the local game launcher and runtime...', file=sys.stderr, flush=True)
    runtime.parent.mkdir(parents=True, exist_ok=True)
    # Runtime publication is separate from the game's verified patch transaction.
    # A previous installed version remains usable until the new launcher commits.
    if not runtime.exists():
        stage = runtime.with_name('.stage-' + secrets.token_hex(12))
        stage.mkdir()
        for name in (*inventory['files'], 'package-manifest.json'):
            source = ordinary_file(package, name)
            destination = stage / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        verify(stage, 'client')
        try: stage.rename(runtime)
        except FileExistsError: verify(runtime, 'client')
    else:
        if verify(runtime, 'client') != inventory or (runtime/'package-manifest.json').read_bytes() != (package/'package-manifest.json').read_bytes():
            raise PackageError('Cached client runtime differs from this installer')
    print('Checking supported game files and installing the patch...', file=sys.stderr, flush=True)
    patch_game(game, helper=runtime/'program/client-helper/BattleAcesOffline.dll',
               community=True, cosmetics=True, progress=console_progress)
    print('Saving server settings and creating Start Battle Aces.cmd...', file=sys.stderr, flush=True)
    with rc_setup.configuration_lock(config.parent):
        if (config.read_bytes() if config.exists() else None) != before_config:
            raise PackageError('Settings changed during installation; reopen the installer')
        if (target.read_bytes() if target.exists() else None) != before_launcher:
            raise PackageError('Game launcher changed during installation; existing launcher was preserved')
        try:
            atomic_write(config, (json.dumps(settings, indent=2)+'\n').encode('utf-8'))
            atomic_write(target, script)
        except BaseException:
            if before_config is None: config.unlink(missing_ok=True)
            else: atomic_write(config, before_config)
            if before_launcher is None: target.unlink(missing_ok=True)
            else: atomic_write(target, before_launcher)
            raise
    return dict(installed=True, launcher=str(target), config=str(config), runtime=str(runtime),
                server_host=settings['server_host'], offline_supported=True)
