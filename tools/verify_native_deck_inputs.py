"""Owned native persisted-deck refusal and unfinished-deck compatibility probe.

Invalid fixtures must exit before startup/successful save and remain byte-identical. Healthy
new,missing-key,complete and unfinished profiles must reach the original menu.
No automatic repair or shared-file writes; healthy cleanup is forced,not Quit.
"""
import argparse
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import tomllib
import traceback

from client_patch.transport import launcher
from server.worker_client import _WindowsJob
from tools import verify_unified_startup as startup
from tools.verify_native_quit import verify_build_receipt

ROOT = Path(__file__).resolve().parents[1]


def fixtures(seed):
    text = seed.decode('utf-8-sig')
    table = tomllib.loads(text)
    base = json.loads(table['account']['decks'])
    assert len(base['SelectedDeck']['_units'])==8 and len(base['SelectedDeck']['_activeAbilities'])==4
    pattern = re.compile(r'^decks\s*=.*$',re.M)
    assert len(pattern.findall(text))==1,'use a native single-line deck fixture'

    def raw(value):
        # JSON basic-string escaping is valid for these authored TOML strings.
        replacement = 'decks = '+json.dumps(value,ensure_ascii=False)
        return pattern.sub(lambda _:replacement,text).encode('utf-8')

    def encoded(value): return raw(json.dumps(value,separators=(',',':')))

    cases = [(name,raw(value),False,None) for name,value in
             (('empty-string',''),('malformed-json','{unfinished'),('json-null','null'),('empty-object','{}'))]
    cases += [(name,pattern.sub(lambda _:'decks = '+value,text).encode('utf-8'),False,None)
              for name,value in (('toml-integer','7'),('toml-boolean','true'),('toml-array','[]'),('toml-table','{}'))]
    cases.append(('account-wrong-type',b'account = 7\n',False,None))
    variants = [('missing-selected',lambda d:d.pop('SelectedDeck')),
                ('null-selected',lambda d:d.update(SelectedDeck=None)),
                ('null-units',lambda d:d['SelectedDeck'].update(_units=None)),
                ('short-units',lambda d:d['SelectedDeck']['_units'].pop()),
                ('long-units',lambda d:d['SelectedDeck']['_units'].append({'_id':0})),
                ('null-abilities',lambda d:d['SelectedDeck'].update(_activeAbilities=None)),
                ('short-abilities',lambda d:d['SelectedDeck']['_activeAbilities'].pop()),
                ('long-abilities',lambda d:d['SelectedDeck']['_activeAbilities'].append({'_id':0})),
                ('unknown-unit',lambda d:d['SelectedDeck']['_units'][0].update(_id=0xfffffffe)),
                ('negative-unit',lambda d:d['SelectedDeck']['_units'][0].update(_id=-1)),
                ('overflow-unit',lambda d:d['SelectedDeck']['_units'][0].update(_id=0x100000000)),
                ('boolean-unit',lambda d:d['SelectedDeck']['_units'][0].update(_id=True)),
                ('string-unit',lambda d:d['SelectedDeck']['_units'][0].update(_id='1')),
                ('fractional-unit',lambda d:d['SelectedDeck']['_units'][0].update(_id=1.5)),
                ('null-unit-id',lambda d:d['SelectedDeck']['_units'][0].update(_id=None)),
                ('missing-unit-id',lambda d:d['SelectedDeck']['_units'][0].pop('_id')),
                ('duplicate-unit',lambda d:d['SelectedDeck']['_units'][1].update(_id=d['SelectedDeck']['_units'][0]['_id'])),
                ('wrong-slot',lambda d:d['SelectedDeck']['_units'].__setitem__(slice(0,3,2),list(reversed(d['SelectedDeck']['_units'][0:3:2])))),
                ('unknown-ability',lambda d:d['SelectedDeck']['_activeAbilities'][0].update(_id=0xfffffffe)),
                ('string-ability',lambda d:d['SelectedDeck']['_activeAbilities'][0].update(_id='1')),
                ('null-saved-entry',lambda d:d.update(Decks=[None]))]
    for name,change in variants:
        value=copy.deepcopy(base);change(value);cases.append((name,encoded(value),False,None))
    value=copy.deepcopy(base);bad=copy.deepcopy(value['SelectedDeck']);bad['_units'].pop();value['Decks']=[bad]
    cases.append(('bad-saved-shape',encoded(value),False,None))
    cases += [('healthy-complete',seed,True,[v['_id'] for v in base['SelectedDeck']['_units']]),
              ('healthy-missing-file',None,True,None),('healthy-missing-key',b'[account]\n',True,None)]
    for name,key in (('healthy-unfinished',0),('healthy-native-empty-sentinel',0xffffffff)):
        value=copy.deepcopy(base);value['SelectedDeck']['_units'][-1]['_id']=key
        cases.append((name,encoded(value),True,[v['_id'] for v in value['SelectedDeck']['_units']]))
    value=copy.deepcopy(base)
    for item in value['SelectedDeck']['_units']+value['SelectedDeck']['_activeAbilities']: item['_id']=0
    cases.append(('healthy-all-empty-native-fallback',encoded(value),True,None))
    value=copy.deepcopy(base);value.pop('Decks',None)
    cases.append(('healthy-missing-saved-list',encoded(value),True,[v['_id'] for v in base['SelectedDeck']['_units']]))
    value=copy.deepcopy(base);value['Decks']=None
    cases.append(('healthy-null-saved-list',encoded(value),True,[v['_id'] for v in base['SelectedDeck']['_units']]))
    value=copy.deepcopy(base);value['Decks']=[copy.deepcopy(value['SelectedDeck'])]
    cases.append(('healthy-stored-deck',encoded(value),True,[v['_id'] for v in base['SelectedDeck']['_units']]))
    return cases


def sources():
    return startup.source_hashes() | {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),ROOT/'tools/verify_native_quit.py',ROOT/'client_patch/build.ps1')}


def run(args):
    require=startup.require;game=args.game.resolve();output=args.output.resolve()
    require(os.name=='nt' and game.is_relative_to(ROOT/'local') and output.is_relative_to(ROOT/'local'), 'owned local Windows paths required')
    require(args.valid_fixture.resolve().is_relative_to(ROOT/'local') and 30<=args.timeout<=180,'owned fixture/bounded timeout required')
    launcher.verify_game(game,community=True,bridge_version=2,unified=True)
    manifest=json.loads((game/'.battleaces-resurrection/patch-manifest.json').read_bytes())
    require(manifest.get('local_settings',{}).get('deck_input_guard') is True and
        any(h.get('name')=='OfflineLocalDeckStorageLoad' and h.get('rva')==0x3de76a2 for h in manifest['call_hooks']), 'install early native deck guard')
    receipt=verify_build_receipt(game,args.helper_build_receipt.resolve())
    cases=fixtures(args.valid_fixture.read_bytes())
    if args.case:
        cases=[row for row in cases if row[0] in args.case]
        require({row[0] for row in cases}==set(args.case),'unknown fixture name')
    output.mkdir(parents=True,exist_ok=False);profiles=game/'.battleaces-resurrection/profiles'
    runtime=game/'investigation/runtime';runtime.mkdir(parents=True,exist_ok=True)
    report=dict(passed=False,cases=[],scope=__doc__,helper_build=receipt,source_sha256_at_start=sources())
    clock=ctypes.WinDLL('kernel32').GetTickCount64;clock.restype=ctypes.c_ulonglong
    processes=[];started=time.monotonic();prefix='nativestest_deck_'+secrets.token_hex(5)

    def log(row):
        file=runtime/f'dedicated-native-{row["pid"]}.log';raw=file.read_bytes() if file.exists() else b''
        return '\n'.join(line for line in raw[:raw.rfind(b'\n')+1].decode('utf-8').splitlines()
            if (m:=re.match(r'^\[(\d+)\]',line)) and int(m[1])>=row['tick'])

    try:
        report['shared_before']=startup.shared_state(args.shared_settings.resolve())
        for name,data,healthy,expected in cases:
            profile=prefix+'_'+str(len(report['cases']));folder=profiles/profile;folder.mkdir(parents=True,exist_ok=False)
            target=folder/'gameconfig-localuser.toml'
            if data is not None: target.write_bytes(data);(output/(name+'-input.toml')).write_bytes(data)
            command=[str(game/'Battle Aces.exe'),'-offline-practice','-practice-ai-experimental','-local-profile='+profile,
                '-native-settings-deck-proof','-screen-fullscreen','0','-screen-width','960','-screen-height','540',
                '-logFile',str(output/(name+'-game.log'))]
            visible=args.visible and healthy;info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=5 if visible else 0
            tick=clock();process=subprocess.Popen(command,cwd=game,startupinfo=info,creationflags=0 if visible else subprocess.CREATE_NO_WINDOW,close_fds=True)
            row=dict(name=name,profile=profile,pid=process.pid,tick=tick,process=process,job=None,target=target,command=command);processes.append(row);row['job']=_WindowsJob(process.pid)
            (output/'processes.json').write_text(json.dumps([{k:(str(v) if isinstance(v,Path) else v)
                for k,v in entry.items() if k not in ('process','job')} for entry in processes],indent=2)+'\n',encoding='utf-8')
            deadline=time.monotonic()+args.timeout
            while True:
                text=log(row)
                if not healthy and process.poll() is not None: break
                if not healthy:
                    require('NATIVE SETTINGS deck input accepted:' not in text and 'Offline initial state reached' not in text,
                        'invalid persisted deck was accepted: '+name)
                if healthy:
                    require(process.poll() is None,'healthy native deck fixture exited early: '+name)
                    require('Native persisted deck load refused:' not in text and 'Local menu initialization failed:' not in text,'healthy native deck fixture refused: '+name)
                    if 'Offline practice menu ready:' in text and 'NATIVE SETTINGS DECK proof:' in text: break
                require(time.monotonic()<deadline,'native deck fixture deadline: '+name);time.sleep(.05)
            if healthy:
                proofs=[json.loads(line.split('NATIVE SETTINGS DECK proof: ',1)[1]) for line in text.splitlines() if 'NATIVE SETTINGS DECK proof:' in line]
                require(len(proofs)==1 and proofs[0]['owned'] and proofs[0]['profile']==profile and
                    'NATIVE SETTINGS deck input accepted:' in text,'healthy native graph proof missing')
                disk=tomllib.loads(target.read_text(encoding='utf-8-sig'));deck=json.loads(disk['account']['decks'])['SelectedDeck']
                units=[v['_id'] for v in deck['_units']]
                require(units==proofs[0]['units'] and (expected is None or units==expected),'healthy unfinished deck changed unexpectedly')
                process.terminate();process.wait(timeout=15)
                result=dict(case=name,passed=True,healthy=True,native_units=units,cleanup_forced=True)
            else:
                require(process.returncode==1610 and 'Native persisted deck load refused:' in text and
                    'inputPreserved=1 selectorUnused=1' in text and 'Offline initial state reached' not in text and
                    not re.search(r'NATIVE SETTINGS save result:[^\n]+ succeeded=1',text),'invalid deck did not refuse before startup/successful save: '+name)
                require(target.read_bytes()==data,'invalid persisted deck bytes changed: '+name)
                result=dict(case=name,passed=True,healthy=False,input_preserved=True,exit_code=process.returncode,
                    input_sha256=hashlib.sha256(data).hexdigest(),
                    protected_startup_write_refusals=len(re.findall(r'NATIVE SETTINGS save result:[^\n]+ succeeded=0[^\n]+validationProtected=1',text)),
                    refusal=[line.split('Native persisted deck load refused: ',1)[1] for line in text.splitlines() if 'Native persisted deck load refused: ' in line])
            (output/(name+'-native.log')).write_text(log(row)+'\n',encoding='utf-8');row['job'].close();row['job']=None
            require(startup.shared_state(args.shared_settings.resolve())==report['shared_before'],'shared native settings changed')
            result.update(pid=process.pid,profile=profile);report['cases'].append(result)
        report['passed']=True
    except BaseException as error: report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        for row in reversed(processes):
            if row['process'].poll() is None: row['process'].terminate()
            row['process'].wait(timeout=15)
            (output/(row['name']+'-native.log')).write_text(log(row)+'\n',encoding='utf-8')
            if row['target'].exists() and row['target'].stat().st_size<=1024*1024:
                (output/(row['name']+'-after.toml')).write_bytes(row['target'].read_bytes())
            if row['job']:row['job'].close()
        report.update(elapsed_seconds=time.monotonic()-started,owned_processes_reaped=all(r['process'].poll() is not None for r in processes),source_sha256_at_finish=sources(),
            shared_after=startup.shared_state(args.shared_settings.resolve()))
        report['source_files_unchanged']=report['source_sha256_at_start']==report['source_sha256_at_finish']
        report['shared_settings_unchanged']=report.get('shared_before')==report['shared_after']
        report['passed'] &= report['source_files_unchanged'] and report['shared_settings_unchanged'] and report['owned_processes_reaped']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','error','elapsed_seconds') if k in report}));return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('game','output','valid-fixture','helper-build-receipt','shared-settings'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=90)
    parser.add_argument('--case',action='append',help='run only named authored fixtures')
    parser.add_argument('--visible',action='store_true',help='show owned healthy control windows')
    raise SystemExit(run(parser.parse_args()))
