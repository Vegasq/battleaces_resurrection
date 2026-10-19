"""Owned native practice/result/Continue/natural-Quit storage qualification.

Automates original callbacks in a visible disposable game, never ordinary play.
Hashes only the named shared TOML/replay/backup channels. The replay readback is
an independent bounded Deflate/protobuf structural check, not native playback.
"""
import argparse
import ctypes
from datetime import datetime,timedelta
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import stat
import threading
import time
import zlib

from server.protobuf_wire import parse_fields
from tools import verify_native_quit as quit_probe
from tools import verify_unified_startup as startup
from tools.run_secure_match import read_native_log

ROOT = Path(__file__).resolve().parents[1]
require = startup.require


def snapshot(folder):
    """Bounded non-following inventory; shared evidence contains hashes only."""
    if not folder.exists(): return dict(exists=False)
    require(folder.is_dir() and not folder.is_junction() and not folder.is_symlink(),'storage root must be an ordinary directory')
    rows = {};pending = [(folder,0)];total = 0
    while pending:
        parent,depth = pending.pop();require(depth<=4,'storage snapshot depth exceeded')
        for path in sorted(parent.iterdir()):
            require(len(rows)<512,'storage snapshot entry bound exceeded')
            info = path.lstat();name = path.relative_to(folder).as_posix()
            require(not getattr(info,'st_file_attributes',0)&0x400,'snapshot refuses reparse children')
            if stat.S_ISDIR(info.st_mode):
                rows[name] = dict(directory=True);pending.append((path,depth+1))
            else:
                require(stat.S_ISREG(info.st_mode) and info.st_size<=16*1024*1024,'storage file type/size unsupported')
                total += info.st_size;require(total<=64*1024*1024,'storage snapshot total bound exceeded')
                raw = path.read_bytes();require(len(raw)==info.st_size,'storage file changed during snapshot')
                rows[name] = dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    return dict(exists=True,entries=rows)


def replay_evidence(raw):
    require(isinstance(raw,bytes) and 0<len(raw)<=4*1024*1024,'replay compressed size unsupported')
    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    data = decoder.decompress(raw,16*1024*1024+1)
    require(len(data)<=16*1024*1024 and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
            'truncated,oversized or trailing replay Deflate data')
    fields = parse_fields(data,max_bytes=16*1024*1024,max_fields=16384)
    require(all(f.number in (1,2) and f.wire_type==2 for f in fields),'unexpected original replay wire fields')
    games = [f.value for f in fields if f.number==1];actions = [f.value for f in fields if f.number==2]
    require(len(games)==1 and games[0] and actions,'replay lacks game data or recorded input actions')
    require(parse_fields(games[0],max_bytes=16*1024*1024),'empty replay GameData')
    for action in actions: parse_fields(action)
    return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),decoded_bytes=len(data),
                game_data_sha256=hashlib.sha256(games[0]).hexdigest(),input_action_messages=len(actions),
                format='original native writer; independent raw-Deflate/protobuf structure readback',native_playback=False)


def sources():
    paths = (Path(__file__),)
    return quit_probe.sources() | {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run(args):
    game,output = args.game.resolve(),args.output.resolve()
    require(os.name=='nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'),'owned ignored Windows paths required')
    output.mkdir(parents=True,exist_ok=False)
    profile = 'nativestest_storage_'+secrets.token_hex(6)
    folder = game/'.battleaces-resurrection/profiles'/profile
    folder.mkdir(parents=True,exist_ok=False)
    shared = args.shared_settings.resolve()
    def shared_state():
        return dict(toml=startup.shared_state(shared),replays=snapshot(shared.parent/'AutoSaveReplays'),backup=snapshot(shared.parent/'StorageSyncBackup'))
    report = dict(passed=False,scope=__doc__,case=args.case,profile=profile,source_sha256_at_start=sources())
    started = time.monotonic();stop = threading.Event();watcher = None;fixtures = []
    attributes = ctypes.WinDLL('kernel32',use_last_error=True).SetFileAttributesW
    attributes.argtypes = [ctypes.c_wchar_p,ctypes.c_uint32];attributes.restype = ctypes.c_int
    payload = b'authored read-only replay target\n'
    def deny_targets():
        try:
            while not stop.wait(.1):
                process_path = output/'native/process.json'
                if not process_path.exists(): continue
                try: process = json.loads(process_path.read_bytes())
                except json.JSONDecodeError: continue
                text = read_native_log(game,process['pid'],since_tick=process['launch_tick'])
                if 'Practice native EndOfGameResponse delivered;' not in text: continue
                require(not list((folder/'AutoSaveReplays').iterdir()),'fault control requires an empty owned replay folder')
                now = datetime.now()
                # Less than100 files avoids triggering original replay retention.
                # Cover native seconds-based naming around the result callback.
                for second in range(-2,46):
                    suffix = (now+timedelta(seconds=second)).strftime('%Y.%m.%d-%H.%M.%S')
                    target = folder/'AutoSaveReplays'/('Storage Qualification-Aliased-vs-Practice AI-Aliased-build-37822_'+suffix+'.rep')
                    with target.open('xb') as stream: stream.write(payload)
                    fixtures.append(target)
                    require(attributes(str(target),1)!=0,'owned read-only replay target setup failed')
                report['fault_injected_after_native_result'] = True
                return
        except BaseException as error: report['fault_injection_error'] = repr(error)
    try:
        report['shared_before'] = shared_state()
        functional_fixture = getattr(args,'functional_fixture',None)
        seeded = None
        if functional_fixture:
            fixture = functional_fixture.resolve();require(fixture.is_relative_to(ROOT/'local'),'functional fixture must be owned and local')
            raw = fixture.read_bytes();require(0<len(raw)<=64*1024,'functional fixture size unsupported')
            seeded = json.loads(raw)
            require(isinstance(seeded,dict) and seeded.get('Id')==fixture.name and re.fullmatch(r'[A-F0-9-]{36}',fixture.name) and
                    isinstance(seeded.get('Data'),dict) and type(seeded['Data'].get('CompletedMainMenuTutorials')) is int,
                    'expected an original native functional backup fixture')
            seeded['Data']['CompletedMainMenuTutorials'] |= 1<<20
            backup = folder/'StorageSyncBackup';backup.mkdir()
            (backup/fixture.name).write_text(json.dumps(seeded,separators=(',',':')),encoding='utf-8')
            report['seeded_functional_state'] = dict(fixture_sha256=hashlib.sha256(raw).hexdigest(),
                completed_menu_tutorial_bit=1<<20,native_reader_and_writer=True)
        if args.case=='blocked': (folder/'AutoSaveReplays').write_bytes(b'authored replay directory blocker\n')
        if args.case=='denied':
            (folder/'AutoSaveReplays').mkdir();watcher = threading.Thread(target=deny_targets,daemon=True);watcher.start()
        if args.case=='managed-fault':
            require(b'BA_RESURRECTION_NATIVE_STORAGE_FAULT_V1' in (game/'BattleAcesOffline.dll').read_bytes(),'install the owned native storage fault diagnostic helper')
            (folder/'native-replay-directory-blocker').write_bytes(b'authored native replay directory fault\n')
        options = argparse.Namespace(game=game,output=output/'native',shared_settings=shared,
            helper_build_receipt=args.helper_build_receipt,profile=profile,mode='confirm',visible=True,
            capture_dialog=False,after_practice=True,default_recipe=True,timeout=args.timeout,
            display_name='X'*96 if args.case=='long-name' else 'Storage Qualification',storage_directory_fault=args.case=='managed-fault')
        require(quit_probe.run(options)==0,'native result/Continue/natural Quit did not pass')
        text = (output/'native/native.log').read_text(encoding='utf-8')
        require('NATIVE STORAGE backup verified: staticField=1 getterCalled=0 localOnlyPolicy=1 isolated=1' in text,
                'native backup static root not verified')
        replay = folder/'AutoSaveReplays'
        if args.case=='blocked':
            require(replay.read_bytes()==b'authored replay directory blocker\n' and
                    'NATIVE STORAGE autosave refused:' in text and 'sharedFallback=0 cleanupContinues=1 saved=0' in text,
                    'blocked autosave was not refused nonfatally with unchanged input')
        elif args.case=='denied':
            game_log = (output/'native/game.log').read_text(encoding='utf-8')
            require('System.UnauthorizedAccessException:' in game_log and 'Uncapped.Replay.SaveReplayFile' in game_log and
                    'managedException=1' not in text,'original read-only file failure was not handled as expected')
            require(report.get('fault_injected_after_native_result') is True and len(fixtures)==48 and
                    set(replay.iterdir())==set(fixtures) and all(p.read_bytes()==payload for p in fixtures),
                    'managed failure changed read-only fixture bytes or wrote an unexpected replay')
            report['readonly_target_count'] = len(fixtures)
            report['original_save_error_handled'] = True
        elif args.case=='managed-fault':
            require('NATIVE STORAGE explicit directory fault armed:' in text and
                    'NATIVE STORAGE autosave boundary: invoked=1 managedException=1 cleanupContinues=1 saved=unclaimed' in text,
                    'original managed directory exception did not reach the nonfatal invocation boundary')
            require(not list(replay.iterdir()) and (folder/'native-replay-directory-blocker').read_bytes()==b'authored native replay directory fault\n',
                    'managed directory failure changed its fixture or wrote a replay')
            report['original_managed_exception_caught'] = True
        elif args.case=='long-name':
            game_log = (output/'native/game.log').read_text(encoding='utf-8')
            require(not list(replay.iterdir()) and 'System.IO.DirectoryNotFoundException:' in game_log and
                    'Uncapped.Replay.SaveReplayFile' in game_log and 'X'*96 in game_log,
                    'long-name control did not retain its original handled save failure')
            report['original_save_error_handled'] = True
        else:
            require('NATIVE STORAGE autosave boundary: invoked=1 managedException=0 cleanupContinues=1 saved=unclaimed' in text,
                    'original autosave invocation did not return normally')
            paths = list(replay.iterdir());require(len(paths)==1 and paths[0].suffix=='.rep','expected exactly one profile-local original replay')
            report['replay'] = dict(file=paths[0].name,**replay_evidence(paths[0].read_bytes()))
        backup = folder/'StorageSyncBackup'
        files = list(backup.iterdir());require(files,'postgame native functional backup missing')
        report['backup'] = {}
        for path in files:
            raw = path.read_bytes();value = json.loads(raw)
            require(isinstance(value,dict) and value,'native functional backup is not a populated JSON object')
            report['backup'][path.name] = dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),fields=sorted(value))
            if seeded:
                require(value['Id']==seeded['Id'] and type(value['Data']['CompletedMainMenuTutorials']) is int and
                        value['Data']['CompletedMainMenuTutorials']&(1<<20) and value['LastEditDateTime']!=seeded['LastEditDateTime'],
                        'original native load/write did not retain the seeded functional tutorial bit')
                report['seeded_functional_state']['retained_after_native_write'] = True
        report.update(passed=True,native_result=True,native_continue=True,native_quit=True)
    except BaseException as error:
        report.update(error=repr(error));raise
    finally:
        stop.set()
        if watcher is not None: watcher.join(timeout=10)
        restored_attributes = [attributes(str(p),128)!=0 for p in fixtures]
        report['owned_readonly_attributes_restored'] = all(restored_attributes)
        if watcher is not None and (watcher.is_alive() or 'fault_injection_error' in report): report['passed'] = False
        report['passed'] &= report['owned_readonly_attributes_restored']
        report['source_sha256_at_finish'] = sources()
        report['source_files_unchanged'] = report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['shared_after'] = shared_state()
        report['shared_channels_unchanged'] = report.get('shared_before')==report['shared_after']
        report['passed'] &= report['source_files_unchanged'] and report['shared_channels_unchanged']
        report['elapsed_seconds'] = time.monotonic()-started
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({key:report[key] for key in ('passed','case','elapsed_seconds','shared_channels_unchanged')}))
    require(report['passed'],'native storage qualification failed')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game','output','shared-settings','helper-build-receipt'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--case',choices=('healthy','blocked','long-name','denied','managed-fault'),default='healthy')
    parser.add_argument('--timeout',type=int,default=240)
    parser.add_argument('--functional-fixture',type=Path,help='owned native JSON; seed a functional tutorial bit and require its native read/write roundtrip')
    run(parser.parse_args())
