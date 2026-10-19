"""Owned functional-backup input/write failures through combat,Continue,native Quit.

All mutations are fresh ignored profile fixtures in a disposable Windows copy.
Original JSON remains native-owned. A rejected input must survive the entire
match,not just menu startup. Shared storage is inventoried/read-hashed only.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import traceback

from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.verify_native_storage import snapshot,replay_evidence

ROOT=Path(__file__).resolve().parents[1]
FILE_ID='A3079428-5DC5-4617-AF2D-0C8656DA760B'
require=startup.require


def run(args):
    game,output,shared=args.game.resolve(),args.output.resolve(),args.shared_settings.resolve()
    require(os.name=='nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'),
            'owned ignored Windows paths required')
    require(60<=args.timeout<=300,'bounded native timeout required')
    require(not args.repair_after or (args.case not in ('missing','healthy','null-list') and args.fixture is not None),
            'repair requires an owned original fixture and a refusal/failure case')
    output.mkdir(parents=True,exist_ok=False)
    profile='nativestest_backup_'+secrets.token_hex(6)
    folder=game/'.battleaces-resurrection/profiles'/profile
    backup=folder/'StorageSyncBackup';backup.mkdir(parents=True,exist_ok=False)
    target=backup/FILE_ID
    baseline=None
    if args.case!='missing':
        if args.case=='malformed': baseline=b'{"Id":'
        else:
            require(args.fixture is not None,'original owned JSON fixture required')
            fixture=args.fixture.resolve();require(fixture.is_relative_to(ROOT/'local'),'owned fixture required')
            raw=fixture.read_bytes();require(0<len(raw)<=64*1024,'fixture size unsupported')
            value=json.loads(raw)
            require(value['Id']==FILE_ID and isinstance(value['Data'],dict),'original native backup shape required')
            value['Data']['CompletedMainMenuTutorials']|=1<<20
            if args.case=='null-list':
                # Measured native compatibility: JSON null is accepted. It is
                # not evidence of an actual typed null array/partial Set failure.
                value['Data']['NewQuestsList']=[1234567]
                value['Data']['CompletedQuestsList']=None
            baseline=json.dumps(value,separators=(',',':')).encode()
        target.write_bytes(baseline)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.SetFileAttributesW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong]
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    locked=None
    def channels():
        return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),
                    backup=snapshot(shared.parent/'StorageSyncBackup'))
    def sources():
        paths=[Path(__file__),ROOT/'tools/verify_native_storage.py']
        return quit_probe.sources()|{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report=dict(passed=False,scope=__doc__,case=args.case,profile=profile,shared_before=channels(),
                source_sha256_at_start=sources(),input_sha256=hashlib.sha256(baseline).hexdigest() if baseline else None)
    started=time.monotonic()
    try:
        if args.case=='readonly': require(kernel.SetFileAttributesW(str(target),1)!=0,'owned readonly fixture failed')
        if args.case=='locked':
            locked=kernel.CreateFileW(str(target),0x80000000,0,None,3,0x80,None)
            require(locked not in (None,ctypes.c_void_p(-1).value),'owned external input lock failed')
        options=argparse.Namespace(game=game,output=output/'native',shared_settings=shared,
            helper_build_receipt=args.helper_build_receipt,profile=profile,mode='confirm',visible=True,
            capture_dialog=False,after_practice=True,default_recipe=True,timeout=args.timeout,
            display_name='Backup Qualification',backup_notice_smoke=args.case not in ('healthy','missing','null-list'),backup_write_smoke=True)
        require(quit_probe.run(options)==0,'native AI/result/Continue/natural Quit failed')
        if locked is not None:
            require(kernel.CloseHandle(locked)!=0,'owned input lock release failed');locked=None
        text=(output/'native/native.log').read_text(encoding='utf-8')
        require('BA_RESURRECTION_NATIVE_BACKUP_GUARD_V1' in text,'backup guard not observed')
        rejected=args.case in ('malformed','locked')
        failed_write=rejected or args.case=='readonly'
        expected_result=0 if failed_write else 1
        require(text.count(f'NATIVE BACKUP writer probe: originalWriteBoolean={expected_result} managedExceptionOut=0 agreesWithPublication=1 automated=1')==1,
                'original writer Boolean did not match actual publication')
        after=target.read_bytes()
        if failed_write:
            require(after==baseline,'failed backup input/write was overwritten later in the match')
            require('NATIVE BACKUP save refused:' in text and 'NATIVE BACKUP save published:' not in text,
                    'refused backup still published or no original write was exercised')
            original=(output/'native/game.log').read_text(encoding='utf-8')
            require('System.IO.IOException: Local menu data could not be saved' in original,
                    'original native writer did not catch the authored managed save failure')
            marker='NATIVE SETTINGS notice source: backupRead=1 backupSave=0' if rejected else 'NATIVE SETTINGS notice source: backupRead=0 backupSave=1'
            require(text.count(marker)==1 and text.count('NATIVE SETTINGS notice rendered: originalDialog=1 prefab=89 titleAndBody=1 emptyLocalization=1 captured=1')==1 and
                    text.count('NATIVE SETTINGS notice pooled reuse passed:')==1,'backup warning/acknowledgment/reuse proof incomplete or duplicated')
            capture=game/'investigation/runtime'/('native-settings-notice-'+profile+'.png')
            raw=capture.read_bytes();require(raw.startswith(b'\x89PNG\r\n\x1a\n'),'backup warning capture missing')
            (output/'backup-warning.png').write_bytes(raw);report['notice_capture_sha256']=hashlib.sha256(raw).hexdigest()
        else:
            require('NATIVE BACKUP save published: originalJsonAndWriter=1 flushed=1 inPlaceFallback=0' in text and
                    'NATIVE BACKUP save refused:' not in text,'healthy original JSON publication failed')
            saved=json.loads(after);require(saved['Id']==FILE_ID,'native JSON identity changed')
            if args.case in ('healthy','null-list'):
                before=json.loads(baseline)
                require(saved['Data']['CompletedMainMenuTutorials']&(1<<20) and saved['LastEditDateTime']!=before['LastEditDateTime'],
                        'original load/write did not retain the seeded functional bit')
        require(('NATIVE BACKUP temporary defaults: originalCtorBuilderSetter=1 liveAccessorRetained=1 inputPreserved=1 completeNativeReadbackEqual=1' in text)==rejected,
                'rejected input did not receive complete original temporary defaults')
        require(set(backup.iterdir())=={target},'unexpected backup output or orphan temporary')
        replays=list((folder/'AutoSaveReplays').iterdir());require(len(replays)==1,'expected one original replay')
        report['replay']=replay_evidence(replays[0].read_bytes())
        report.update(input_unchanged=after==baseline,after_sha256=hashlib.sha256(after).hexdigest(),
                      after_bytes=len(after),natural_quit=True,original_write_exception_caught=failed_write)
        if args.repair_after:
            # Explicit diagnostic repair of OUR fixture only,after natural Quit.
            # Never performed by the ordinary client or on shared/user input.
            fixture=args.fixture.resolve();require(fixture.is_relative_to(ROOT/'local'),'owned repair fixture required')
            raw=fixture.read_bytes();require(0<len(raw)<=64*1024,'repair fixture size unsupported')
            repaired=json.loads(raw);require(repaired['Id']==FILE_ID and isinstance(repaired['Data'],dict),'native repair fixture required')
            repaired['Data']['CompletedMainMenuTutorials']|=1<<20
            repaired_bytes=json.dumps(repaired,separators=(',',':')).encode()
            if args.case=='readonly': require(kernel.SetFileAttributesW(str(target),128)!=0,'owned repair attribute restoration failed')
            target.write_bytes(repaired_bytes)
            # Native diagnostics intentionally CREATE_NEW their trace. Archive
            # only our completed/reaped run's exact trace before same-profile
            # restart;never borrow its old PID/deadline as current evidence.
            previous=json.loads((output/'native/verification.json').read_bytes())
            trace=folder/'quit-trace.jsonl'
            require(previous.get('passed') is True and previous.get('natural_exit') is True and
                    previous.get('owned_process_reaped') is True and previous.get('forced_cleanup') is False and
                    not trace.is_symlink() and trace.stat().st_nlink==1 and
                    trace.read_bytes()==(output/'native/quit-trace.jsonl').read_bytes(),
                    'same-profile restart requires our exact completed prior trace')
            trace.rename(output/'previous-profile-quit-trace.jsonl')
            options.output=output/'repaired-native';options.backup_notice_smoke=False
            require(quit_probe.run(options)==0,'repaired native restart/AI/result/Continue/Quit failed')
            restart=(options.output/'native.log').read_text(encoding='utf-8')
            saved=json.loads(target.read_bytes())
            require('NATIVE BACKUP initial read: nativeAccepted=1 writable=1' in restart and
                    'NATIVE BACKUP writer probe: originalWriteBoolean=1 managedExceptionOut=0 agreesWithPublication=1 automated=1' in restart and
                    'NATIVE BACKUP save refused:' not in restart and 'NATIVE SETTINGS notice source:' not in restart and
                    saved['Data']['CompletedMainMenuTutorials']&(1<<20) and saved['LastEditDateTime']!=repaired['LastEditDateTime'],
                    'explicit repaired backup not natively read/saved or warning persisted after restart')
            require(set(backup.iterdir())=={target},'repair left unexpected backup files')
            report['explicit_owned_repair']=dict(restarted=True,original_read_accepted=True,original_write_boolean=True,
                seeded_tutorial_bit_retained=True,natural_quit=True,repaired_input_sha256=hashlib.sha256(repaired_bytes).hexdigest(),
                after_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        report['passed']=True
    except BaseException as error:
        report.update(passed=False,error=repr(error),traceback=traceback.format_exc())
    finally:
        if locked is not None: kernel.CloseHandle(locked)
        restored=args.case!='readonly' or kernel.SetFileAttributesW(str(target),128)!=0
        report['owned_attributes_restored']=bool(restored)
        report.update(shared_after=channels(),source_sha256_at_finish=sources(),elapsed_seconds=time.monotonic()-started)
        report['shared_channels_unchanged']=report['shared_before']==report['shared_after']
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['passed'] &= bool(restored) and report['shared_channels_unchanged'] and report['source_files_unchanged']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({key:report[key] for key in ('passed','case','elapsed_seconds','shared_channels_unchanged')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('game','output','shared-settings','helper-build-receipt'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--fixture',type=Path,help='owned original native functional JSON')
    parser.add_argument('--case',choices=('missing','healthy','malformed','null-list','readonly','locked'),required=True)
    parser.add_argument('--timeout',type=int,default=240)
    parser.add_argument('--repair-after',action='store_true',help='explicit fixture repair after natural Quit,then repeat native gameplay in a new process')
    raise SystemExit(run(parser.parse_args()))
