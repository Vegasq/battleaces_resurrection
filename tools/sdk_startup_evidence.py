"""Validate bounded passive SDK entry evidence;no complete privacy claim.

The caller separately verifies REA envelopes,source/module identities,clock
alignment,base I/O evidence and the owned process's natural exit/job cleanup.
"""
import re
from tools.frida_sdk_startup import ENTRIES


def validate(rows,*,pid,run_id,sdk):
    def require(value,message):
        if not value:raise AssertionError(message)
    def integer(value,minimum=0):return type(value) is int and minimum<=value<=2**53-1
    def frames(value):
        if not isinstance(value,list) or not 1<=len(value)<=8:return False
        for frame in value:
            if not isinstance(frame,dict) or set(frame)!={'module','rva'}:return False
            if frame==dict(module=None,rva=None):continue
            module,rva=frame['module'],frame['rva']
            if not isinstance(module,str) or not 1<=len(module)<=256 or module!=module.lower() or \
                    any(char in module for char in ('/','\\','\0')) or not isinstance(rva,str) or \
                    not re.fullmatch('0x[0-9a-f]{1,16}',rva):return False
        return True
    require(integer(pid,1) and pid<2**32 and isinstance(run_id,str) and
            re.fullmatch('[0-9a-f]{32}',run_id),'SDK PID/run identity required')
    require(isinstance(rows,list) and rows,'SDK rows required')
    require(isinstance(sdk,dict) and set(sdk)=={'module','entries'} and
            isinstance(sdk['module'],str),'SDK descriptor differs')
    entries=sdk['entries']
    require(isinstance(entries,list) and len(entries)==len(ENTRIES) and
        all(isinstance(e,dict) and set(e)=={'name','rva','sha256'} and
            e['name'] in ENTRIES and type(e['rva']) is int and e['rva']==ENTRIES[e['name']] and
            isinstance(e['sha256'],str) and re.fullmatch('[0-9a-f]{64}',e['sha256']) for e in entries) and
        len({e['name'] for e in entries})==len(ENTRIES),'SDK entry descriptor differs')
    ready=False;installation=None;events={name:[] for name in ENTRIES}
    previous=dict.fromkeys(ENTRIES,0);samples=[];elapsed=-1;terminal=[]
    allowed={'module-ready','observer-ready','heartbeat','clock-anchor','file-operation',
             'network-operation','process-create','unresolved-file-root','resolved-cwd-root',
             'process-exit-entry','termination-request','sdk-installed','sdk-entry'}
    for seq,row in enumerate(rows,1):
        require(isinstance(row,dict) and set(row)=={'schema','seq','runId','pid','tid','elapsedMs','kind','data'},
                'SDK row envelope differs')
        require(type(row['schema']) is int and row['schema']==1 and type(row['seq']) is int and
            row['seq']==seq and type(row['pid']) is int and row['pid']==pid and row['runId']==run_id and
            integer(row['tid'],1) and row['tid']<2**32 and integer(row['elapsedMs']) and
            row['elapsedMs']>=elapsed,'SDK row identity/order differs')
        elapsed=row['elapsedMs'];kind=row['kind'];data=row['data']
        require(kind in allowed and isinstance(data,dict),'SDK row kind/data differs')
        if 'errors' in data:require(data['errors']==[],'observer errors present')
        if kind=='observer-ready':
            require(not ready,'duplicate observer-ready');ready=True
        if kind=='sdk-installed':
            require(ready and installation is None,'SDK installation missing readiness or repeated')
            require(data==dict(module=sdk['module'],entries=entries,entryEventLimitPerName=8,
                argumentsRead=False,targetApisInvoked=False,sdkRootReplaced=False,generalUnityPathReplaced=False),
                'SDK installation contract differs')
            # Equality alone accepts0 as False;require actual Boolean values.
            require(type(data['entryEventLimitPerName']) is int and all(data[key] is False for key in
                ('argumentsRead','targetApisInvoked','sdkRootReplaced','generalUnityPathReplaced')),
                'SDK installation field types differ')
            installation=row
        if kind=='sdk-entry':
            require(installation is not None and set(data)=={'name','call','frames'} and
                data['name'] in ENTRIES,'unexpected SDK entry')
            calls=events[data['name']]
            require(type(data['call']) is int and data['call']==len(calls)+1 and data['call']<=8 and
                frames(data['frames']),'SDK entry sequence/frame bound differs')
            calls.append(row)
        if kind in ('heartbeat','process-exit-entry'):
            require(ready and data.get('errors')==[] and data.get('overflow') is False and integer(data.get('unknownRelativeRoots')),
                    'SDK snapshot base observer incomplete')
            snapshot=data.get('sdk')
            require(isinstance(snapshot,dict) and set(snapshot)=={'installed','counts'} and
                type(snapshot['installed']) is bool and snapshot['installed']==(installation is not None),
                'SDK installation snapshot differs')
            counts=snapshot['counts']
            require(isinstance(counts,dict) and set(counts)==set(ENTRIES) and
                all(integer(v) and previous[name]<=v and len(events[name])<=v for name,v in counts.items()),
                'SDK counters missing/noninteger/backward')
            require(installation is not None or not any(counts.values()),'SDK activity before installation')
            previous=dict(counts);samples.append(row)
            if kind=='process-exit-entry':terminal.append(row)
    require(installation is not None and samples and len(terminal)==2 and rows[-2:]==terminal,
            'SDK final two termination entries required')
    require(all(len(events[name])==min(value,8) for name,value in previous.items()),
            'SDK final counters do not match bounded entry records')
    require(all(row['data']['sdk']['installed'] is True for row in terminal),
            'SDK witness did not survive through termination entries')
    return dict(passed=True,entry_counts=previous,entry_record_count=sum(map(len,events.values())),
        installed_seq=installation['seq'],samples=len(samples),selected_sdk_entries_quiet=not any(previous.values()),
        sdk_root_replaced=False,target_apis_invoked=False,
        full_privacy_qualified=False,scope=__doc__)
