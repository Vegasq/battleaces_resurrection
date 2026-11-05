"""Owned236 packaged content refusal/repair, with one changed-path native Quit.

Baseline mode stops at the IPC boundary to record the cached-read defect without
starting an unreadable game. No physical UI or post-verification I/O claim.
"""
import argparse
import contextlib
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import tomllib
import traceback
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
OWNED=Path.home()/'AppData/Local/BattleAcesDiagnostics/local'
DENIAL=ROOT/'tools/owned_file_denial.py'
LOCK=ROOT/'tools/verify_profile_storage.py'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


class BoundaryReached(RuntimeError):pass


def child(request_path):
    from tools import package_client
    from tools.package_integrity import verify
    from client_patch.transport import launcher,rc_setup
    from client_patch.patcher import bundle_loading as loading
    req=json.loads(request_path.read_bytes());out=request_path.parent;game=Path(req['game']);package=Path(req['package'])
    report=dict(passed=False,scope=__doc__,baseline=req['baseline'],cases=[],repaired=[],source_sha256=sha(__file__))
    assert sha(__file__)==req['driver_sha256'] and sha(DENIAL)==req['denial_sha256']
    if req.get('receipt_lock'):assert sha(LOCK)==req['lock_sha256']
    assert Path(package_client.__file__).resolve()==package/'program/app/tools/package_client.py'
    assert Path(loading.__file__).resolve()==package/'program/app/client_patch/patcher/bundle_loading.py'
    verify(package,'client');report['bundle_loading_sha256']=sha(loading.__file__)
    spec=importlib.util.spec_from_file_location('owned_denial',DENIAL);denial=importlib.util.module_from_spec(spec);spec.loader.exec_module(denial)
    name=min(loading.BUILD.BUNDLES,key=lambda n:(loading.BUILD.BUNDLES[n][0],n))
    target=game/loading.BUNDLE_DIR/name;original=target.read_bytes()
    assert hashlib.sha256(original).hexdigest()==loading.BUILD.BUNDLES[name][1]
    report.update(bundle=name,bundle_bytes=len(original),bundle_sha256=sha(target))
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong
    real_socket,real_subprocess,resolver,digest=launcher.socket,launcher.subprocess,rc_setup.Resolver,hashlib.file_digest
    real_replace=os.replace
    current=None;native=None;allow_native=False
    def pair(*args,**kwargs):
        current['ipc_requests']+=1
        if not allow_native:raise BoundaryReached('IPC boundary intercepted before creation')
        current['ipc_created']+=1
        return real_socket.socketpair(*args,**kwargs)
    def popen(command,**kwargs):
        nonlocal native
        current['process_requests']+=1
        assert allow_native and native is None
        command=list(command);assert '-unified-client' in command and not any('smoke' in a for a in command)
        command+=['-native-quit-smoke','-native-quit-mode=confirm']
        info=kwargs['startupinfo'].copy();info.wShowWindow=0;kwargs['startupinfo']=info
        tick=int(clock());native=real_subprocess.Popen(command,**kwargs)
        report['native']=dict(pid=native.pid,tick=tick,command=command)
        return native
    class ObservedResolver(resolver):
        async def __call__(self):
            current['remote_open_requests']+=1
            try:
                await super().__call__()
            except launcher.RemoteUnavailable:
                current['remote_unavailable']+=1
                raise
            current['resolved_remote_targets']+=1
            raise AssertionError('offline fixture unexpectedly resolved a remote target')
    def observed_digest(stream,algorithm,*args,**kwargs):
        if str(getattr(stream,'name','')).endswith('.bundle'):current['bundle_hashes']+=1
        return digest(stream,algorithm,*args,**kwargs)
    def replace(source,destination,*args,**kwargs):
        if Path(destination).resolve()!=game/loading.RECEIPT:return real_replace(source,destination,*args,**kwargs)
        staged=Path(source).read_bytes()
        entry=dict(staged_sha256=hashlib.sha256(staged).hexdigest(),staged_receipt_valid=loading._valid_receipt(json.loads(staged)),published=False)
        current['receipt_publications'].append(entry)
        try:result=real_replace(source,destination,*args,**kwargs)
        except OSError as error:
            entry['winerror']=getattr(error,'winerror',None);raise
        entry['published']=True;return result
    def start(label,*,healthy=False):
        nonlocal current,allow_native
        current=dict(label=label,ipc_requests=0,ipc_created=0,process_requests=0,remote_open_requests=0,remote_unavailable=0,resolved_remote_targets=0,bundle_hashes=0,receipt_publications=[])
        allow_native=healthy;stdout,stderr=io.StringIO(),io.StringIO();began=time.monotonic()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            try:current['exit_code']=package_client.main(['start','--config',req['config']])
            except BoundaryReached:current['boundary_reached']=True
        current.update(stdout=stdout.getvalue(),stderr=stderr.getvalue(),elapsed_seconds=time.monotonic()-began)
        return current.copy()
    launcher.socket=SimpleNamespace(**{**vars(real_socket),'socketpair':pair})
    launcher.subprocess=SimpleNamespace(**{**vars(real_subprocess),'Popen':popen})
    rc_setup.Resolver=ObservedResolver;hashlib.file_digest=observed_digest
    if req.get('receipt_lock'):os.replace=replace
    try:
        if req.get('receipt_lock'):
            spec=importlib.util.spec_from_file_location('receipt_lock_control',LOCK);locks=importlib.util.module_from_spec(spec);spec.loader.exec_module(locks)
            receipt=game/loading.RECEIPT;prior=receipt.read_bytes();(out/'cache-before.json').write_bytes(prior)
            info=target.stat();os.utime(target,ns=(info.st_atime_ns,info.st_mtime_ns+5_000_000_000))
            with locks.OwnedFileLock(receipt,game,allow_read=True) as lock:
                row=start('receipt-locked',healthy=not req['baseline'])
                report['receipt_locked']=row
                assert row['bundle_hashes']==1 and len(row['receipt_publications'])==1
                publication=row['receipt_publications'][0]
                assert publication['staged_receipt_valid'] and not publication['published'] and publication['winerror']==5
                assert receipt.read_bytes()==prior and not list(receipt.parent.glob(receipt.name+'.*.tmp'))
                report['receipt_lock']=dict(probe_winerror=lock.probe_winerror,prior_receipt_preserved=True,temporary_cleaned=True,content_bytes_preserved=sha(target)==report['bundle_sha256'])
                if req['baseline']:
                    assert row['exit_code']==1 and row['ipc_requests']==row['process_requests']==row['remote_open_requests']==0
                    assert 'Game content verification failed.' in row['stdout']
                    report['optional_cache_blocks_valid_content']=True
                else:
                    assert row['exit_code']==0 and row['ipc_requests']==row['ipc_created']==row['process_requests']==1
                    assert row['remote_open_requests']==row['remote_unavailable']==1 and row['resolved_remote_targets']==0 and native.poll()==0
                    assert row['stderr'].count('verification cache could not be saved')==1 and 'Game content verification failed' not in row['stdout']
                    report['healthy']=row
            assert lock.handle is None;report['receipt_lock']['released']=True
            recovered=start('receipt-recovered')
            assert recovered.get('boundary_reached') and recovered['ipc_created']==recovered['process_requests']==0 and recovered['bundle_hashes']==1
            assert len(recovered['receipt_publications'])==1 and recovered['receipt_publications'][0]['published'] and recovered['receipt_publications'][0]['staged_receipt_valid']
            assert 'verification cache could not be saved' not in recovered['stderr']
            assert receipt.read_bytes()!=prior and loading._valid_receipt(json.loads(receipt.read_bytes()))
            report['repaired'].append(recovered);(out/'cache-after.json').write_bytes(receipt.read_bytes())
            cached=start('receipt-reused')
            assert cached.get('boundary_reached') and cached['bundle_hashes']==0 and not cached['receipt_publications']
            assert cached['ipc_created']==cached['process_requests']==0
            report['repaired'].append(cached)
        cases=() if req.get('healthy_only') or req.get('receipt_lock') else ('denied',) if req['baseline'] else ('missing','damaged','denied')
        report['healthy_only']=req.get('healthy_only',False)
        for kind in cases:
            prior=(game/loading.RECEIPT).read_bytes();fingerprint=loading._fingerprint(target.stat())
            backup=target.with_suffix('.content-check-backup');assert not backup.exists()
            control=contextlib.nullcontext()
            try:
                if kind=='missing':target.rename(backup)
                elif kind=='damaged':
                    target.write_bytes(bytes([original[0]^1])+original[1:])
                    stamp=target.stat();os.utime(target,ns=(stamp.st_atime_ns,fingerprint['mtime_ns']+5_000_000_000))
                else:control=denial.OwnedFileReadDenial(target,game)
                with control:
                    if kind=='denied':assert loading._fingerprint(target.stat())==fingerprint
                    row=start(kind);row['kind']=kind
                    if kind=='denied':row['denial']=control.evidence();row['fingerprint_unchanged']=True
                    assert row['ipc_created']==row['process_requests']==row['remote_open_requests']==0
                    assert (game/loading.RECEIPT).read_bytes()==prior,'failed verification changed receipt'
                    if req['baseline']:
                        assert row.get('boundary_reached') and row['ipc_requests']==1 and row['bundle_hashes']==0
                        row['cached_read_defect_observed']=True
                    else:
                        assert row.get('exit_code')==1 and row['ipc_requests']==0 and not row.get('boundary_reached')
                        assert 'Client could not start: Game content verification failed. Repair the supported game files or reinstall the client patch.' in row['stdout']
                        assert row['bundle_hashes']==(1 if kind=='damaged' else 0)
                    report['cases'].append(row)
            finally:
                if kind=='missing' and backup.exists():backup.rename(target)
                elif kind=='damaged':target.write_bytes(original)
            assert sha(target)==report['bundle_sha256']
            if kind=='denied':
                assert control.restored and control.before==control.after and control.handle is None
                report['cases'][-1]['denial']=control.evidence()
            restored=start('restored-'+kind)
            assert restored.get('boundary_reached') and restored['ipc_requests']==1 and restored['ipc_created']==restored['process_requests']==restored['remote_open_requests']==0
            report['repaired'].append(restored)
        if not req['baseline'] and not req.get('receipt_lock'):
            healthy=start('healthy',healthy=True);report['healthy']=healthy
            assert healthy['exit_code']==0 and healthy['ipc_requests']==healthy['ipc_created']==healthy['process_requests']==1
            assert healthy['remote_open_requests']==healthy['remote_unavailable']==1
            assert healthy['resolved_remote_targets']==healthy['bundle_hashes']==0 and native.poll()==0
            assert 'Secure transport ended;' not in healthy['stdout']
        report['passed']=True
    except BaseException:report['error']=traceback.format_exc()
    finally:
        launcher.socket=real_socket;launcher.subprocess=real_subprocess;rc_setup.Resolver=resolver;hashlib.file_digest=digest;os.replace=real_replace
        report['source_unchanged']=sha(__file__)==req['driver_sha256'] and sha(DENIAL)==req['denial_sha256']
        if req.get('receipt_lock'):report['source_unchanged'] &= sha(LOCK)==req['lock_sha256']
        report['passed'] &= report['source_unchanged']
        (out/'child-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 1


def run(args):
    from tools.owned_suspended_launch import SuspendedChild
    from tools.package_integrity import verify
    from tools.verify_native_storage import snapshot
    from tools import verify_native_quit as quit_probe,verify_unified_startup as startup
    from tools.run_secure_match import read_native_log
    package,game,seed,out=(getattr(args,k).resolve() for k in ('package','game','seed','output'))
    assert all(p!=OWNED and p.is_relative_to(OWNED) for p in (package,game,seed,out)) and not out.exists()
    assert 'replay230-manual01' not in str(game)
    verify(package,'client');out.mkdir()
    profile='nativestest_content_'+secrets.token_hex(6);folder=game/'.battleaces-resurrection/profiles'/profile;folder.mkdir(parents=True)
    settings=folder/'gameconfig-localuser.toml';shutil.copyfile(seed,settings)
    before=settings.read_bytes();(out/'settings-before.toml').write_bytes(before)
    config=out/'client.json';config.write_text(json.dumps(dict(schema=3,game_directory=str(game),display_name='Content Recovery',local_profile=profile))+'\n')
    assert not (args.baseline and args.healthy_only)
    assert not (args.receipt_lock and args.healthy_only)
    req=dict(package=str(package),game=str(game),config=str(config),baseline=args.baseline,healthy_only=args.healthy_only,receipt_lock=args.receipt_lock,driver_sha256=sha(__file__),denial_sha256=sha(DENIAL),lock_sha256=sha(LOCK))
    (out/'request.json').write_text(json.dumps(req,indent=2)+'\n')
    shared=Path.home()/'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
    def channels():return dict(settings=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    identities=lambda:{n:sha(game/n) for n in ('Battle Aces.exe','BattleAcesOffline.dll','GameAssembly.dll','.battleaces-resurrection/patch-manifest.json')}
    report=dict(passed=False,baseline=args.baseline,profile=profile,shared_before=channels(),identities_before=identities(),config_sha256=sha(config),package_manifest_sha256=sha(package/'package-manifest.json'))
    source=quit_probe.sources()|{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in (Path(__file__),DENIAL,LOCK,ROOT/'tests/test_bundle_loading.py',ROOT/'tools/owned_suspended_launch.py')}
    report['source_sha256']=source
    for name,digest in source.items():
        dest=out/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,dest);assert sha(dest)==digest
    owner=None;started=time.monotonic()
    try:
        owner=SuspendedChild.create([str(package/'program/runtime/python.exe'),'-I','-B',str(Path(__file__).resolve()),'--child-request',str(out/'request.json')],cwd=out,creationflags=subprocess.CREATE_NO_WINDOW,owned_root=OWNED)
        owner.resume();deadline=time.monotonic()+120
        while owner.poll() is None and time.monotonic()<deadline:time.sleep(.1)
        assert owner.poll() is not None,'owned controller exceeded deadline'
        child_report=json.loads((out/'child-report.json').read_bytes());report['child']=child_report
        assert owner.poll()==0 and child_report['passed'],'owned child reported failure'
        if not args.baseline:
            launch=child_report['native'];text=read_native_log(game,launch['pid'],since_tick=launch['tick'])
            (out/'native.log').write_text(text,encoding='utf-8')
            trace=quit_probe.current_trace_rows((folder/'quit-trace.jsonl').read_bytes(),launch['pid'],launch['tick'])
            assert [r['event'] for r in trace]==['armed','Show.dispatch','Show.return','OnConfirm.dispatch','OnConfirm.return']
            assert 'NATIVE QUIT owned menu verified:' in text and 'NATIVE QUIT original confirmation dispatch:' in text
            assert not any(s in text for s in ('Native Quit probe failed:','Client lifecycle invariant failed:','Offline initialization failed:','COMMUNITY transport connected:'))
            report['quit_trace']=trace
        report['passed']=True
    except BaseException:report['error']=traceback.format_exc()
    finally:
        if owner:owner.close();report['owner']=owner.receipt
        after=settings.read_bytes();(out/'settings-after.toml').write_bytes(after)
        a,b=tomllib.loads(before.decode('utf-8-sig')),tomllib.loads(after.decode('utf-8-sig'))
        report['empty_menu_state_serialized']=False
        if a.get('account',{}).get('menuuistates')=='' and b.get('account',{}).get('menuuistates')=='{"States":[]}':
            a['account']['menuuistates']='{"States":[]}';report['empty_menu_state_serialized']=True
        report['saved_preferences_unchanged']=a==b
        report.update(shared_after=channels(),identities_after=identities(),source_unchanged=all(sha(ROOT/n)==h for n,h in source.items()),elapsed_seconds=time.monotonic()-started)
        report['passed'] &= bool(owner and not owner.receipt['forced_cleanup'] and owner.receipt['job_final']['active_processes']==0 and report['shared_before']==report['shared_after'] and report['identities_before']==report['identities_after'] and report['source_unchanged'] and report['saved_preferences_unchanged'] and sha(config)==report['config_sha256'])
        verify(package,'client')
        (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report.get(k) for k in ('passed','baseline','error','elapsed_seconds')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--child-request',type=Path)
    for n in ('package','game','seed','output'):p.add_argument('--'+n,type=Path)
    p.add_argument('--baseline',action='store_true');p.add_argument('--healthy-only',action='store_true');p.add_argument('--receipt-lock',action='store_true');args=p.parse_args()
    raise SystemExit(child(args.child_request) if args.child_request else run(args))
