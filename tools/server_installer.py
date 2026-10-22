"""Install a standalone host by exporting data from a locally patched game."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

from .package_integrity import verify, ordinary_file, PackageError
from .import_assets import import_assets, verify_export
from client_patch.transport import launcher
from client_patch.patcher.patch_client import install as patch_game
from server.assets import verify_assets
from server.worker_client import _WindowsJob


def copy_game(source, target):
    """Independent working copy; never carry personal saves or hardlink binaries."""
    target.mkdir()
    names=('Battle Aces.exe','GameAssembly.dll','UnityPlayer.dll','baselib.dll',
           'nvngx_dlss.dll','NVUnityPlugin.dll','UnityCrashHandler64.exe',
           'frontconfig-client.toml','gameconfig-client.toml','gameconfig-server.toml')
    def checked_copy(path,destination):
        path=Path(path)
        ordinary_file(source,path.relative_to(source).as_posix())
        return shutil.copyfile(path,destination)
    for name in names:
        path=source/name
        if path.exists(): checked_copy(path,target/name)
    def copy_directory(path,destination):
        for item in (path,*path.rglob('*')):
            info=item.lstat()
            if item.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
                raise PackageError('Game data may not contain links or reparse points')
        shutil.copytree(path,destination,copy_function=checked_copy)
    copy_directory(source/'Battle Aces_Data',target/'Battle Aces_Data')
    original=source/'.battleaces-resurrection/original'
    if original.exists():
        destination=target/'.battleaces-resurrection/original';destination.parent.mkdir()
        copy_directory(original,destination)
        manifest=source/'.battleaces-resurrection/patch-manifest.json'
        if manifest.exists(): checked_copy(manifest,target/'.battleaces-resurrection/patch-manifest.json')


def export_game(game, output, *, timeout=300):
    if os.name != 'nt': raise PackageError('Server setup requires Windows')
    profile='sx_'+secrets.token_hex(4)
    launcher.native_storage_preflight(dict(game_directory=game,local_profile=profile))
    log=output.parent/'export-game.log'
    command=[str(game/'Battle Aces.exe'),'-offline-practice','-export-server-assets',
             '-local-profile='+profile,'-server-assets-dir='+str(output),
             '-screen-fullscreen','0','-screen-width','960','-screen-height','540','-logFile',str(log)]
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
    process=subprocess.Popen(command,cwd=game,startupinfo=info,creationflags=subprocess.CREATE_NO_WINDOW)
    job=None
    try:
        job=_WindowsJob(process.pid); deadline=time.monotonic()+timeout
        while not (output/'export.json').is_file():
            if process.poll() is not None: raise PackageError('Game data export exited before completion')
            if (output/'export-error.json').exists(): raise PackageError('Game could not export the supported server data')
            if time.monotonic()>=deadline: raise PackageError('Game data export timed out; close other game windows and retry')
            time.sleep(.2)
        manifest=json.loads((output/'export.json').read_bytes())
        if manifest.get('pid') != process.pid: raise PackageError('Game export belongs to another process')
        verify_export(output)
    finally:
        # Export-only process: no match or player session was started. The
        # game stays in its export loop; release only our owned process/job.
        if process.poll() is None: process.terminate()
        process.wait(timeout=15)
        if job: job.close()


def install(package, request):
    package=Path(package).resolve(); inventory=verify(package,'server')
    if (not isinstance(request,dict) or set(request)!={'game_directory','server_directory'}
            or any(not isinstance(v,str) or not v.strip() for v in request.values())):
        raise PackageError('Choose the patched game folder and an empty server folder')
    game=Path(request['game_directory']).expanduser().resolve()
    destination=Path(request['server_directory']).expanduser().resolve()
    if (destination==game or destination.is_relative_to(game) or game.is_relative_to(destination)
            or destination==package or destination.is_relative_to(package) or package.is_relative_to(destination)):
        raise PackageError('Choose a server folder separate from the game and installer files')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise PackageError('Choose an empty server folder; existing hosts and saves are never overwritten')
    ordinary_file(game,'Battle Aces.exe')
    ordinary_file(game,'GameAssembly.dll')
    print('Preparing server files...',file=sys.stderr,flush=True)
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=destination.with_name('.ba-'+secrets.token_hex(6));stage.mkdir()
    # Preserve failed stage for diagnosis. No existing server/config/key/data
    # is changed, and no public socket is opened by installation.
    for name in (*inventory['files'],'package-manifest.json'):
        source=ordinary_file(package,name);target=stage/name
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    verify(stage,'server')
    exported=stage/'.setup/export'
    exported.parent.mkdir()
    working=stage/'.setup/game'
    launcher.native_storage_preflight(dict(game_directory=working,local_profile='sx_'+'0'*8))
    print('Copying game data into private setup space. The source game is read only...',file=sys.stderr,flush=True)
    copy_game(game,working)
    patch_game(working,helper=stage/'program/client-helper/BattleAcesOffline.dll',community=True,
               cosmetics=True,progress=lambda done,total: None)
    launcher.verify_game(working,community=True,bridge_version=2,unified=True,player_features=True)
    print('Reading game maps, units and AI data. This can take a minute...',file=sys.stderr,flush=True)
    export_game(working,exported)
    assets=stage/'assets/build-37822'
    print('Checking and importing supported game data...',file=sys.stderr,flush=True)
    imported=import_assets(working,exported,assets,working/'.battleaces-resurrection/original/GameAssembly.dll')
    verify_assets(assets);verify(stage,'server')
    # This path is an independently copied,known child of this fresh staging
    # directory. Never recurse through or delete anything in the source game.
    working.resolve().relative_to(stage.resolve())
    if working.resolve()!=stage.resolve()/'.setup/game': raise PackageError('Setup working copy changed location')
    shutil.rmtree(working)
    if destination.exists():
        # Empty at the start is not permission to delete later arrivals.
        destination.rmdir()
    stage.rename(destination)
    return dict(installed=True,launcher=str(destination/'Start Server.exe'),
                server_directory=str(destination),playable_units=imported['playable_units'],
                port=47623,server_started=False,keys_created=False,
                first_start='Start Server.exe creates its own local certificate and config')
