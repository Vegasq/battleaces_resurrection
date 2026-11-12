"""Private prediction for Custom1v1 and public mode1 server AI; separate settings."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import copy
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import sys

from tools.package_integrity import verify, ordinary_file, PackageError, SafeParser
from client_patch.patcher import patch_client as patcher, prediction_worker, prediction_actor_repair
from client_patch.transport import client, launcher, rc_setup
from server.protocol import SIM_SHA

PACKAGE = Path(__file__).resolve().parents[3]
PROFILE = 'private-custom-movement-prediction-v1'
DESCRIPTOR = 'program/prediction/prediction-profile.json'
CONFIG = '.battleaces-resurrection/prediction-client/client-config.json'
LOCAL_PROFILE = 'prediction_custom'
DEFAULT_SERVER = '134.209.176.39'
ARTIFACTS = {
    'main_helper':'program/client-helper/BattleAcesOffline.dll',
    'main_helper_provenance':'program/client-helper/helper-provenance.json',
    'heap_helper':'program/prediction/heap/BAHeap.dll',
    'heap_receipt':'program/prediction/heap/build.json',
    'cooperative':'program/prediction/cooperative/PredictionCooperative.dll',
    'cooperative_receipt':'program/prediction/cooperative/build.json',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def bounded(path, maximum=256*1024*1024):
    with Path(path).open('rb') as stream:
        value=stream.read(maximum+1)
    if len(value)>maximum:raise PackageError('Prediction input exceeds its size bound')
    return value


def json_bytes(value):
    return (json.dumps(value,indent=2)+'\n').encode('utf-8')


def profile(package):
    package=Path(package).resolve()
    inventory=verify(package,'client')
    if DESCRIPTOR not in inventory['files']:raise PackageError('This is not the private prediction package')
    value=launcher.read_json(ordinary_file(package,DESCRIPTOR),32768)
    required={'schema','profile','python','module_root','artifacts'}
    if (type(value)is not dict or not required<=set(value)<=required|{'gameassembly'} or
            type(value['schema'])is not int or value['schema']!=1 or value['profile']!=PROFILE or
            value['python']!='program/runtime/python.exe' or value['module_root']!='program/app' or
            type(value['artifacts'])is not dict or set(value['artifacts'])!=set(ARTIFACTS)):
        raise PackageError('Invalid private prediction profile')
    paths={}
    for role,name in ARTIFACTS.items():
        row=value['artifacts'][role]
        if (type(row)is not dict or set(row)!={'path','sha256'} or row['path']!=name or
                row['sha256']!=inventory['files'].get(name,{}).get('sha256')):
            raise PackageError('Prediction artifact differs from package inventory')
        paths[role]=ordinary_file(package,name)
    for name in (value['python'],'program/app/client_patch/prediction_worker/__main__.py',
                 'program/app/client_patch/prediction_worker/checkpoint.py'):
        if name not in inventory['files']:raise PackageError('Prediction runtime module is missing')
        ordinary_file(package,name)
    pins=value.get('gameassembly')
    if pins is not None and (type(pins)is not dict or set(pins)!={'ordinary_sha256','prediction_sha256'} or
            any(type(h)is not str or len(h)!=64 or any(c not in '0123456789abcdef'for c in h)for h in pins.values())):
        raise PackageError('Invalid prediction assembly pins')
    from client_patch.prediction_worker.native import helper_receipt,HostError
    try:
        helper_receipt(paths['heap_helper'],arena=True)
        helper_receipt(paths['cooperative'])
    except (OSError,ValueError,HostError):
        raise PackageError('Prediction helper receipts do not match their DLLs') from None
    helper=bounded(paths['main_helper'],8*1024*1024)
    markers=(b'BA_RESURRECTION_MOVEMENT_PIPELINE_V1',b'BA_RESURRECTION_NATIVE_WORKER_PROXY_V1',
        b'BA_RESURRECTION_ORIGINAL_COMMAND_SCHEDULING_V1')
    hooks=prediction_worker.CALL_HOOKS+prediction_actor_repair.CALL_HOOKS+prediction_actor_repair.TAIL_HOOKS+prediction_actor_repair.POINTER_HOOKS
    if any(m not in helper for m in markers)or any(h['name'].encode()+b'\0'not in helper for h in hooks):
        raise PackageError('Private package helper lacks movement prediction support')
    if b'OfflinePredictionVisualJoin\0'not in helper or '-prediction-visual-correction'.encode('utf-16-le')not in helper:
        raise PackageError('Private package helper lacks visual correction support')
    return dict(package=package,descriptor=value,paths=paths,inventory=inventory,
        package_sha256=digest(bounded(package/'package-manifest.json',1024*1024)))


def game_file(game,name):
    patcher.contained_path(game,name)
    return ordinary_file(game,name)


def destination(game,name):
    path=game/name
    patcher.contained_path(game,name)
    for item in (path,*path.parents):
        try:info=item.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode)or getattr(info,'st_file_attributes',0)&0x400:
            raise PackageError('Prediction destinations cannot be redirected')
        if item==game:break
    return path


def inspect_game(package,game):
    bundle=profile(package);game=Path(game).expanduser().resolve(strict=True)
    game_file(game,'Battle Aces.exe')
    simulation=game_file(game,'Battle Aces_Data/Plugins/x86_64/Simulation.dll')
    if digest(bounded(simulation,64*1024*1024))!=SIM_SHA:
        raise PackageError('Exact original Simulation.dll build is required before prediction preparation')
    launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True,
        original_command_scheduling_experimental=True)
    original=bounded(game_file(game,'.battleaces-resurrection/original/GameAssembly.dll'))
    if digest(original)!=patcher.ORIGINAL_SHA256:raise PackageError('Exact original GameAssembly backup is required')
    ordinary=patcher.build_patch(original,community=True,cosmetics=True)
    predicted=patcher.build_patch(original,community=True,cosmetics=True,prediction_worker=True,prediction_movement=True)
    hashes=dict(ordinary_sha256=digest(ordinary),prediction_sha256=digest(predicted))
    if bundle['descriptor'].get('gameassembly',hashes)!=hashes:
        raise PackageError('Prediction package assembly pins differ from its pure recipe')
    assembly=game_file(game,'GameAssembly.dll');manifest_path=game_file(game,'.battleaces-resurrection/patch-manifest.json')
    current=bounded(assembly);manifest_raw=bounded(manifest_path,131072)
    manifest=launcher.read_json(manifest_path,131072)
    actual=digest(current);component=manifest.get('components',{}).get('GameAssembly.dll',{})
    if (actual not in hashes.values()or manifest.get('original_sha256')!=patcher.ORIGINAL_SHA256 or
            component.get('original_sha256')!=patcher.ORIGINAL_SHA256 or
            any(value!=actual for value in (manifest.get('patched_sha256'),component.get('patched_sha256'),component.get('installed_sha256')))):
        raise PackageError('GameAssembly and both manifest hash records must match the exact supported recipe')
    helper_hash=bundle['descriptor']['artifacts']['main_helper']['sha256']
    if manifest.get('helper_sha256')!=helper_hash or digest(bounded(game_file(game,'BattleAcesOffline.dll'),8*1024*1024))!=helper_hash:
        raise PackageError('Install this private package normally into the selected working copy first')
    ordinary_hooks=patcher.CALL_HOOKS+patcher.COMMUNITY_CALL_HOOKS+patcher.COSMETIC_CALL_HOOKS
    extended=ordinary_hooks+prediction_worker.CALL_HOOKS+prediction_actor_repair.CALL_HOOKS
    is_prediction=actual==hashes['prediction_sha256']
    if manifest.get('call_hooks')!=(extended if is_prediction else ordinary_hooks):
        raise PackageError('GameAssembly hook descriptors differ from the exact prediction recipe')
    pointer_hooks=prediction_actor_repair.POINTER_HOOKS if is_prediction else []
    if manifest.get('pointer_hooks',[])!=pointer_hooks:
        raise PackageError('GameAssembly pointer descriptors differ from the exact prediction recipe')
    tail_hooks=patcher.TAIL_HOOKS+patcher.COMMUNITY_TAIL_HOOKS+patcher.COSMETIC_TAIL_HOOKS
    if manifest.get('tail_hooks')!=tail_hooks+(prediction_actor_repair.TAIL_HOOKS if is_prediction else []):
        raise PackageError('GameAssembly tail descriptors differ from the exact prediction recipe')
    ordinary_patches=patcher.PATCHES+patcher.COSMETIC_PATCHES+patcher.DLSS_PRIVACY_PATCHES
    patches=ordinary_patches+(prediction_actor_repair.PATCHES if is_prediction else [])
    if manifest.get('patches')!=patches:
        raise PackageError('GameAssembly byte patches differ from the exact prediction recipe')
    marker=dict(schema=1,profile=PROFILE,package_sha256=bundle['package_sha256'],**hashes)
    if is_prediction and manifest.get('prediction_client')!=marker:
        raise PackageError('Prediction manifest does not belong to this exact private package')
    return dict(bundle=bundle,game=game,assembly=assembly,manifest_path=manifest_path,
        current=current,manifest_raw=manifest_raw,manifest=manifest,predicted=predicted,hashes=hashes,
        hooks=extended,pointer_hooks=list(prediction_actor_repair.POINTER_HOOKS),
        tail_hooks=tail_hooks+prediction_actor_repair.TAIL_HOOKS,
        patches=ordinary_patches+prediction_actor_repair.PATCHES,marker=marker,is_prediction=is_prediction)


def settings(game):
    path=destination(game,CONFIG)
    if path.exists():
        value=launcher.read_json(game_file(game,CONFIG),32768)
        checked=rc_setup.settings(value,path)
        if checked['game_directory']!=game or value['local_profile']!=LOCAL_PROFILE or set(value)!=rc_setup.KEYS:
            raise PackageError('Private prediction settings binding changed')
        return path,value
    value=dict(schema=4,game_directory=str(game),display_name=client.defaults(game)['display_name'],
        local_profile=LOCAL_PROFILE,server_host=DEFAULT_SERVER,server_port=47623,room='community',fullscreen=True,solo_ai_host='server')
    source=game/'.battleaces-resurrection/client-config.json'
    if source.exists():
        public=launcher.read_json(game_file(game,'.battleaces-resurrection/client-config.json'),32768)
        client.local_settings(public,source)
        # Fresh prediction settings use server AI independently of the ordinary
        # client's local-AI preference. Existing private settings above persist.
        for key in ('display_name','server_host','server_port','room','fullscreen'):
            if key in public:value[key]=public[key]
        if not value['server_host']:value['server_host']=DEFAULT_SERVER
    rc_setup.settings(value,path)
    return path,value


@contextmanager
def game_not_running(game):
    """Retain an exclusive writable EXE handle; a mapped game image refuses it.

    No PID discovery/termination. Keeping this handle through publication also
    prevents another launch of this exact EXE during the patch transaction.
    """
    if os.name!='nt':raise PackageError('Prediction preparation requires Windows')
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[C.c_wchar_p,C.c_uint32,C.c_uint32,C.c_void_p,C.c_uint32,C.c_uint32,C.c_void_p]
    kernel.CreateFileW.restype=C.c_void_p
    kernel.CloseHandle.argtypes=[C.c_void_p];kernel.CloseHandle.restype=C.c_int
    handle=kernel.CreateFileW(str(game/'Battle Aces.exe'),0xc0000000,0,None,3,0x80,None)
    if handle==C.c_void_p(-1).value:
        raise PackageError('Close the game before preparing prediction, and check write access to its working copy')
    try:
        # Also refuse an image loaded by another executable name. Release this
        # short probe before rename; the retained EXE handle guards our launcher.
        assembly=kernel.CreateFileW(str(game/'GameAssembly.dll'),0xc0000000,0,None,3,0x80,None)
        if assembly==C.c_void_p(-1).value:
            raise PackageError('Close programs using GameAssembly.dll before preparing prediction')
        kernel.CloseHandle(assembly)
        yield
    finally:kernel.CloseHandle(handle)


def clean_stage(stage,state):
    if stage.parent.resolve()!=state.resolve()or not stage.name.startswith('.prediction-stage-'):
        raise PackageError('Unexpected prediction stage path')
    shutil.rmtree(stage)


def prepare(package,game):
    # Verify package first, before even creating the local installation lock.
    profile(package)
    game=Path(game).expanduser().resolve(strict=True)
    state=game/'.battleaces-resurrection'
    ordinary_file(game,'.battleaces-resurrection/patch-manifest.json')
    game_file(game,'Battle Aces.exe')
    with rc_setup.configuration_lock(state),game_not_running(game):
        checked=inspect_game(package,game)
        config,value=settings(game)
        launcher.native_storage_preflight(client.local_settings(value,config))
        manifest=copy.deepcopy(checked['manifest'])
        manifest['patched_sha256']=checked['hashes']['prediction_sha256']
        manifest['components']['GameAssembly.dll'].update(patched_sha256=manifest['patched_sha256'],installed_sha256=manifest['patched_sha256'])
        manifest['call_hooks']=checked['hooks'];manifest['pointer_hooks']=checked['pointer_hooks']
        manifest['tail_hooks']=checked['tail_hooks']
        manifest['patches']=checked['patches']
        manifest['prediction_client']=checked['marker']
        changes=[(checked['assembly'],checked['current'],checked['predicted']),
            (checked['manifest_path'],checked['manifest_raw'],json_bytes(manifest)),
            (config,bounded(config,32768)if config.exists()else None,json_bytes(value))]
        changes=[row for row in changes if row[1]!=row[2]]
        if changes:
            stage=state/('.prediction-stage-'+secrets.token_hex(12));stage.mkdir()
            published=[];rollback_failed=False
            try:
                for index,(target,before,after)in enumerate(changes):
                    if target.exists()and target.stat().st_nlink!=1:raise PackageError('Prediction targets cannot be hard linked')
                    if before is not None:patcher.atomic_write(stage/(str(index)+'.before'),before)
                    patcher.atomic_write(stage/str(index),after)
                for index,(target,before,after)in enumerate(changes):
                    if (bounded(target)if target.exists()else None)!=before:raise PackageError('Prediction target changed during preparation')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    os.replace(stage/str(index),target);published.append((target,before))
            except BaseException as original_error:
                for target,before in reversed(published):
                    try:
                        if before is None:target.unlink(missing_ok=True)
                        else:patcher.atomic_write(target,before)
                    except BaseException:rollback_failed=True
                if rollback_failed:
                    raise PackageError('Prediction preparation failed and rollback needs recovery; preserve the prediction stage')from original_error
                raise
            finally:
                if not rollback_failed:clean_stage(stage,state)
    return check(package,game)


def check(package,game):
    checked=inspect_game(package,game)
    if not checked['is_prediction']:raise PackageError('Run prediction prepare for this separate working copy first')
    path,value=settings(checked['game'])
    if not path.is_file():raise PackageError('Private prediction settings have not been prepared')
    launcher.native_storage_preflight(client.local_settings(value,path))
    return dict(ready=True,profile=PROFILE,game=str(checked['game']),config=str(path),
        patched_sha256=checked['hashes']['prediction_sha256'],helper_sha256=checked['manifest']['helper_sha256'],
        server_host=value['server_host'],scope='private Custom1v1 or public mode1 server AI movement prediction; no scripted gameplay')


def start(package,game):
    ready=prepare(package,game)
    bundle=profile(package);game=Path(ready['game']);path=Path(ready['config'])
    value=launcher.read_json(path,32768);config=client.local_settings(value,path)
    run=destination(game,'.battleaces-resurrection/prediction-client/runs/'+secrets.token_hex(16))
    run.mkdir(parents=True,exist_ok=False);data=run/'worker-data';data.mkdir()
    options=launcher.PredictionWorkerOptions(python=bundle['package']/'program/runtime/python.exe',
        module_root=bundle['package']/'program/app',heap_helper=bundle['paths']['heap_helper'],
        cooperative=bundle['paths']['cooperative'],data_directory=data,visual_correction=True)
    args=client.player_options(original_command_scheduling_experimental=True);args.run_name='prediction-client'
    patcher.atomic_write(run/'launch.json',json_bytes(dict(schema=1,profile=PROFILE,package_sha256=bundle['package_sha256'],
        game=str(game),worker_data=str(data),scripted_gameplay=False,visual_correction=options.visual_correction)))
    return asyncio.run(launcher.launch(config,rc_setup.Resolver(path,game),args,prediction_worker=options))


def main(argv=None):
    parser=SafeParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    for action in ('check','prepare','start'):
        sub=commands.add_parser(action);sub.add_argument('--game',type=Path,required=True,help='separate working copy already installed from this private package')
    args=parser.parse_args(argv)
    try:
        if args.command=='start':return start(PACKAGE,args.game)
        result=(check if args.command=='check'else prepare)(PACKAGE,args.game)
        print(json.dumps(dict(ok=True,result=result)));return 0
    except (OSError,ValueError,PackageError)as error:
        message=str(error)if isinstance(error,ValueError)else 'Cannot access the private prediction package or working game copy'
        print(json.dumps(dict(ok=False,error=message)),file=sys.stderr);return 1
    except KeyboardInterrupt:return 130


if __name__=='__main__':raise SystemExit(main())
