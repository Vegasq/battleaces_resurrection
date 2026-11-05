"""Review current recipe38 outage plus selected passive SDK entry/file routes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.extract_descriptors import PE
from tools.frida_sdk_queue440 import ENTRIES,GUARDED,build_source
from tools.review_d5_outage439 import ROOT,review as native_review
from tools.review_d5_exit_network368 import records_for,payloads

CASE=ROOT/'local/privacy440-outage-sdk03'
TRACE=ROOT/'local/privacy440-outage-sdk-trace03'
GAME=ROOT/'local/privacy301-runtime01/game'

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def review():
    native=native_review(CASE)
    report,sessions,bundle=read(CASE/'verification.json'),read(TRACE/'sessions.json'),read(TRACE/'rea-evidence.json')
    assert report['passed'] and report['prelaunch_observer'] is True
    assert sessions['case']=='local/'+CASE.name and [r['index'] for r in sessions['clients']]==[0,1]
    image=PE((GAME/'GameAssembly.dll').read_bytes())
    for name,(rva,expected) in (GUARDED|ENTRIES).items():
        offset=image.offset(image.base+rva,16)
        assert image.data[offset:offset+16].hex()==expected,name
    expected_hooks=[dict(key=key,rva=entry[0]) for key,entry in ENTRIES.items()]
    clients=[]
    for row in sessions['clients']:
        index,pid,session=row['index'],row['pid'],row['session_id']
        path=CASE/f'client-{index}/game-process.json'
        process=read(path)
        gate=CASE/f'client-{index}/observer-ready'
        assert process['pid']==pid and process['suspended_for_observer'] is True
        assert gate.read_bytes()==b'FRIDA_READY\n' and path.stat().st_mtime_ns<gate.stat().st_mtime_ns
        assert report['prelaunch_resume'][index]['pid']==pid
        config=read(TRACE/f'config-{index}.json')
        assert config['sdk_queue'] and config['unresolved_file_status'] and config['exit_boundary']
        assert config['game_sha256']==sha(GAME/'Battle Aces.exe')
        observer=TRACE/f'observer-{index}.js'
        assert observer.read_text(encoding='utf-8')==build_source(config['config'])
        assert config['source_sha256']==sha(observer)
        loads=records_for(bundle,session,'load_frida_script')
        finals=[item for item in records_for(bundle,session,'frida_session_status')
                if item['normalized_result'].get('state')=='detached']
        assert len(loads)==len(finals)==1
        load,final=loads[0],finals[0]
        assert load['normalized_result']['source_sha256']==sha(observer)
        early,messages=payloads(load),payloads(final)
        assert messages[:len(early)]==early and not final['normalized_result']['messages_truncated']
        assert [r['kind'] for r in early[-2:]]==['observer-ready','exit-boundary-armed']
        assert all(r['pid']==pid and r['runId']==config['config']['runId'] for r in messages)
        ready=[r for r in messages if r['kind']=='sdk-module-ready']
        assert len(ready)==1 and ready[0]['data']==dict(hooks=expected_hooks,errors=[])
        boundary=[r for r in messages if r['kind']=='self-terminate-entry']
        assert len(boundary)==1 and boundary[0]==messages[-1] and ready[0]['seq']<boundary[0]['seq']
        data=boundary[0]['data']
        assert data['exitStatus']==0 and data['sdkHooks']==expected_hooks and data['sdkErrors']==[]
        assert data['sdkCounts']=={key:0 for key in ENTRIES}
        assert data['errors']==[] and data['overflow'] is False and data['unknownRelativeRoots']==0
        assert data['counts']['ws2_32.dll:send']>0 and data['counts']['ws2_32.dll:recv']>0
        assert all(r['kind'] not in ('sdk-entry','file-operation','network-operation',
                   'process-create','budget-exceeded','decode-error') for r in messages)
        unresolved=[r for r in messages if r['kind']=='unresolved-file-operation']
        assert len(unresolved)==9 and all(r['data']['operation']=='NtWriteFile' and
               r['data']['returnValue']==-1073741816 for r in unresolved)
        clients.append(dict(index=index,pid=pid,selected_sdk_entry_counts=data['sdkCounts'],
                            native_send=data['counts']['ws2_32.dll:send'],
                            native_recv=data['counts']['ws2_32.dll:recv'],
                            sdk_root_selected_file_ops=0,unresolved_failed_invalid_handle_writes=9))
    return dict(passed=True,scope='current owned public1 two-client relay outage;pre-resume through self-exit',
                native_review=native,clients=clients,
                verifier_sha256=sha(CASE/'verification.json'),
                rea_bundle_sha256=sha(TRACE/'rea-evidence.json'),
                guarded_entry_bytes_checked=len(GUARDED),hooked_active_entries=len(ENTRIES),
                sdk_queue_state_observed=False,whole_wire_observed=False,final_installed=False)

if __name__=='__main__':
    result=review();target=CASE/'sdk-route-review.json'
    assert not target.exists()
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,clients=len(result['clients']),
                          guarded=len(GUARDED),hooks=len(ENTRIES))))
