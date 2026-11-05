"""Packaged damaged-asset refusal and repaired native health check (203).

Owned asset copy and authored profiles; no live deployment or game UI changes.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import shutil
import traceback

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools/verify_room_faults.py'
LOCK_HELPER = ROOT / 'tools/verify_profile_storage.py'
DENIAL_HELPER = ROOT / 'tools/owned_file_denial.py'
CASES = {
    'missing_manifest': 'missing_manifest',
    'truncated_manifest': 'invalid_manifest',
    'list_manifest': 'invalid_manifest',
    'null_inventory': 'invalid_manifest',
    'missing_map': 'missing_asset',
    'changed_map': 'content_mismatch',
    'wrong_build': 'build_mismatch',
}


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def child(request_path):
    from tools.package_integrity import verify
    from tools import package_server
    from server import assets as asset_module, host, worker_client, rc_host
    from server.assets import verify_assets, ASSET_FAILURES
    from server.game_data import GameTemplate
    from server.cosmetics import CosmeticCatalog
    from server.profiles import ProfileStore
    from server.state_lock import exclusive_state

    request = json.loads(request_path.read_bytes())
    out, package, assets = request_path.parent, Path(request['package']), Path(request['assets'])
    report = dict(passed=False, scope=__doc__, cases=[], worker_creations=[], server_constructions=0)
    original_create = worker_client.SimulationWorker.create
    original_server = host.DedicatedServer
    options = request.get('options', {})
    sharing_lock = False
    permission_denial = False
    control = None
    def observe_server(*args, **kwargs):
        report['server_constructions'] += 1
        return original_server(*args, **kwargs)

    async def observe_create(*args, **kwargs):
        record = dict(started=True)
        report['worker_creations'].append(record)
        worker = await original_create(*args, **kwargs)
        record.update(pid=worker.pid, dll_sha256=worker.dll_sha256, test_backend=worker._test_backend)
        return worker

    try:
        require(sha(__file__) == request['driver_sha256'] and sha(HELPER) == request['helper_sha256'], 'driver changed')
        require(type(options) is dict and set(options) <= {'sharing_lock', 'lock_helper_sha256', 'locked_asset', 'permission_denial', 'denial_helper_sha256'}, 'unsupported asset scenario')
        sharing_lock = options.get('sharing_lock', False)
        permission_denial = options.get('permission_denial', False)
        require(type(sharing_lock) is bool and type(permission_denial) is bool and not (sharing_lock and permission_denial), 'unsupported access control selection')
        access_fault = sharing_lock or permission_denial
        locked_asset = options.get('locked_asset', 'manifest')
        require(locked_asset in ('manifest', 'map') and (access_fault or locked_asset == 'manifest'), 'unsupported locked asset')
        if sharing_lock:
            require(sha(LOCK_HELPER) == options.get('lock_helper_sha256'), 'lock control changed')
            spec = importlib.util.spec_from_file_location('asset_lock_control', LOCK_HELPER)
            lock_control = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(lock_control)
        if permission_denial:
            require(sha(DENIAL_HELPER) == options.get('denial_helper_sha256'), 'denial control changed')
            spec = importlib.util.spec_from_file_location('asset_denial_control', DENIAL_HELPER)
            denial_control = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(denial_control)
        verify(package, 'server')
        manifest = verify_assets(assets)
        modules = (asset_module, host, worker_client, package_server)
        for module in modules:
            require(Path(module.__file__).resolve() == package / 'program/app' / (module.__name__.replace('.', '/') + '.py'),
                    'bundled import differs')
        report['module_sha256'] = {str(Path(m.__file__).resolve()): sha(m.__file__) for m in modules}
        require((out / 'job-ready').exists(), 'owned job gate absent')
        bundle = out / 'asset-copy'
        shutil.copytree(assets, bundle)
        template = GameTemplate.load(bundle/'map-1v1.pb.gz', catalog_path=bundle/'unit-catalog.json',
                                     descriptors_path=bundle/'descriptors')
        profiles = ProfileStore(out/'data/profiles', template, catalog=CosmeticCatalog(bundle))
        for slot in range(2):
            profiles.save('asset_recovery_' + str(slot), template.default_decks[slot])
        before = {p.name: sha(p) for p in (out/'data/profiles').glob('*.json')}
        require(len(before) == 2, 'two persisted profiles required')
        cert, key = rc_host.generate_certificate()
        (out/'server.pem').write_bytes(cert)
        (out/'server.key').write_bytes(key)
        settings = json.loads((package/'config/host.example.json').read_bytes())
        settings.update(schema=2, access_mode='rc-open', assets_directory=str(bundle),
                        data_directory=str(out/'data'), listen_host='127.0.0.1', dashboard_port=0,
                        certificate_file=str(out/'server.pem'), private_key_file=str(out/'server.key'),
                        credential_directory=None)
        config = out/'host.json'
        save(config, settings)
        preserved = {name: sha(out/name) for name in ('server.pem', 'server.key', 'host.json')}
        manifest_path, map_path = bundle/'asset-manifest.json', bundle/'map-1v1.pb.gz'
        manifest_bytes, map_bytes = manifest_path.read_bytes(), map_path.read_bytes()
        worker_client.SimulationWorker.create = observe_create
        host.DedicatedServer = observe_server
        lock_cases = {'locked_manifest': 'unreadable_manifest'} if locked_asset == 'manifest' else {'locked_map': 'unreadable_asset'}
        if permission_denial:
            lock_cases = {'denied_' + locked_asset: 'unreadable_manifest' if locked_asset == 'manifest' else 'unreadable_asset'}
        cases = lock_cases if access_fault else CASES
        locked_path = manifest_path if locked_asset == 'manifest' else map_path
        for case, code in cases.items():
            if not access_fault:
                manifest_path.write_bytes(manifest_bytes)
                map_path.write_bytes(map_bytes)
            if case == 'missing_manifest':
                manifest_path.unlink()
            elif case == 'truncated_manifest':
                manifest_path.write_bytes(b'{private-marker')
            elif case == 'list_manifest':
                save(manifest_path, [])
            elif case == 'null_inventory':
                save(manifest_path, dict(manifest, files=None))
            elif case == 'missing_map':
                map_path.unlink()
            elif case == 'changed_map':
                map_path.write_bytes(bytes([map_bytes[0] ^ 1]) + map_bytes[1:])
            elif case == 'wrong_build':
                save(manifest_path, dict(manifest, simulation_sha256='0'*64))
            control = lock_control.OwnedFileLock(locked_path, bundle, allow_read=False) if sharing_lock else contextlib.nullcontext()
            if permission_denial:
                control = denial_control.OwnedFileReadDenial(locked_path, bundle, receipt=bundle/'permission-before.json')
            with control as lock:
                if sharing_lock:
                    report['sharing_lock'] = dict(probe_winerror=lock.probe_winerror, held_during=['check', 'start'], target=locked_asset, manifest_checks_under_lock=0)
                if permission_denial:
                    report['permission_denial'] = dict(**lock.evidence(), held_during=['check', 'start'], target=locked_asset, manifest_checks_under_denial=0)
                for command in ('check', 'start'):
                    if access_fault and locked_asset == 'map':
                        require(json.loads(manifest_path.read_text(encoding='utf-8')) == manifest, 'manifest unreadable or changed during map lock')
                        if sharing_lock:report['sharing_lock']['manifest_checks_under_lock'] += 1
                        if permission_denial:report['permission_denial']['manifest_checks_under_denial'] += 1
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        result = package_server.main([command, '--config', str(config)])
                    require(result == 1 and not stdout.getvalue(), 'damaged assets reported ready')
                    require(stderr.getvalue() == 'Host asset check failed: ' + ASSET_FAILURES[code] + '\n',
                            'fixed actionable diagnostic differs')
                    require(not report['worker_creations'] and report['server_constructions'] == 0, 'damaged assets reached native/server startup')
                    require({p.name: sha(p) for p in (out/'data/profiles').glob('*.json')} == before,
                            'asset failure changed profiles')
                    require(all(sha(out/name) == value for name, value in preserved.items()), 'host identity/config changed')
                    with exclusive_state(out/'data'):
                        pass
                    report['cases'].append(dict(case=case, command=command, code=code, exit_code=result,
                        diagnostic=stderr.getvalue().strip(), state_lock_released=True, profiles_preserved=True,
                        native_not_started=True))
            if sharing_lock:
                require(lock.handle is None, 'asset lock handle was not released')
                report['sharing_lock']['released'] = True
            if permission_denial:
                require(lock.handle is None and lock.restored and lock.before == lock.after, 'file permissions were not restored exactly')
                report['permission_denial'].update(lock.evidence())
        if not access_fault:
            manifest_path.write_bytes(manifest_bytes)
            map_path.write_bytes(map_bytes)
        require(manifest_path.read_bytes() == manifest_bytes and map_path.read_bytes() == map_bytes, 'asset bytes changed')
        require(verify_assets(bundle) == manifest, 'repaired asset copy differs')
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = package_server.main(['check', '--config', str(config)])
        health = json.loads(stdout.getvalue())
        require(result == 0 and not stderr.getvalue() and health['passed'] and health['tls'], 'repaired health failed')
        require(health['native']['stepped_frame'] == 0 and health['native']['exit_code'] == 0 and health['native']['reaped'],
                'repaired native step/cleanup differs')
        require(len(report['worker_creations']) == 1 and not report['worker_creations'][0]['test_backend'],
                'repaired check must create exactly one real worker')
        require({p.name: sha(p) for p in (out/'data/profiles').glob('*.json')} == before, 'repair changed profiles')
        require(all(sha(out/name) == value for name, value in preserved.items()), 'repair changed host identity/config')
        with exclusive_state(out/'data'):
            pass
        require(verify_assets(assets) == manifest, 'original assets changed')
        report.update(passed=True, repaired_health=health, profile_sha256=before,
                      preserved_config_identity_sha256=preserved, repaired_copy_verified=True,
                      original_assets_unchanged=True, state_lock_released=True)
    except BaseException as error:
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        worker_client.SimulationWorker.create = original_create
        host.DedicatedServer = original_server
        report['source_unchanged'] = sha(__file__) == request['driver_sha256'] and sha(HELPER) == request['helper_sha256']
        if sharing_lock:
            report['source_unchanged'] &= sha(LOCK_HELPER) == options.get('lock_helper_sha256')
        if permission_denial:
            report['source_unchanged'] &= sha(DENIAL_HELPER) == options.get('denial_helper_sha256')
            if control is not None and hasattr(control, 'during'):
                report.setdefault('permission_denial', {}).update(control.evidence())
        report['passed'] &= report['source_unchanged']
        save(out/'child-report.json', report)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child-request', type=Path, help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--sharing-lock', action='store_true', help='only actual Windows read-lock refusal and recovery;no damaged-asset repeats')
    mode.add_argument('--permission-denial', action='store_true', help='one owned file READ_DATA denial/exact descriptor restoration;no sharing-lock repeats')
    parser.add_argument('--locked-asset', choices=('manifest', 'map'), default='manifest', help='fixed owned access-fault target;requires a fault selection for map')
    for name in ('package', 'assets', 'output'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.child_request:
        raise SystemExit(child(args.child_request))
    require(all((args.package, args.assets, args.output)), 'package/assets/output required')
    from tools.verify_loading_recovery import run
    require(args.sharing_lock or args.permission_denial or args.locked_asset == 'manifest', 'map target requires an access fault')
    options = dict(sharing_lock=True, locked_asset=args.locked_asset, lock_helper_sha256=sha(LOCK_HELPER)) if args.sharing_lock else {}
    owned_root = None
    if args.permission_denial:
        options = dict(permission_denial=True, locked_asset=args.locked_asset, denial_helper_sha256=sha(DENIAL_HELPER))
        owned_root = Path.home()/'AppData/Local/BattleAcesDiagnostics/local'
    raise SystemExit(run(args.package, args.assets, args.output, driver=__file__, scope=__doc__, options=options, owned_root=owned_root))
