"""Read-only qualification of the owned attribution sensor control, never game absence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
from tools.frida_attribution_source import API, build_source, control_request
from tools.verify_frida_control import terminal_pid

MAX_BYTES=8*1024*1024
REQUIRED=frozenset(('ntdll.dll:NtCreateFile','ntdll.dll:NtOpenFile','ntdll.dll:NtReadFile',
    'ntdll.dll:NtWriteFile','ntdll.dll:NtSetInformationFile','ntdll.dll:NtClose',
    'kernelbase.dll:CreateProcessW','ws2_32.dll:connect','ws2_32.dll:send','ws2_32.dll:recv',
    'ws2_32.dll:getaddrinfo','ws2_32.dll:GetAddrInfoW'))
KNOWN=frozenset(module+':'+name for module,names in API.items() for name in names)


def integer(value,minimum=0):return type(value) is int and minimum<=value<=2**53-1
def digest(raw):return hashlib.sha256(raw).hexdigest()
def path(value):
    if not isinstance(value,str):raise ValueError('invalid path')
    if value.startswith('\\??\\') or value.startswith('\\\\?\\'):value=value[4:]
    return str(PureWindowsPath(value)).casefold()


def verify(inputs,result,positive,source,*,target_sha256):
    errors=[]
    def check(condition,code):
        if not condition:errors.append(code)
    report=dict(passed=False,scope='Owned localhost/file/process metadata control only;not game privacy qualification.',
                analytics_removal_qualified=False,descendants_instrumented=False,
                kernel_capture=False,wire_dns_qualified=False,exit_code_qualified=False,errors=errors)
    try:
        config=inputs['config'];request=inputs['request'];run=config['runId']
        canonical,arguments=control_request(config['image'],str(PureWindowsPath(request['path']).parent),run)
        check(inputs['schema']==1 and type(inputs['schema']) is int and config==canonical and request==arguments,'noncanonical_control')
        check(source in (build_source(config).encode(),build_source(config).replace('\n','\r\n').encode()),'noncanonical_source')
        check(inputs['source_sha256']==digest(source) and inputs['target_sha256']==target_sha256 and
              bool(re.fullmatch('[0-9a-f]{64}',target_sha256)),'input_identity_differs')
        check(not result.get('isError',False),'provider_error')
        evidence=result['structuredContent']
        texts=[json.loads(c['text']) for c in result.get('content',[]) if c.get('type')=='text']
        check(len(texts)==1 and texts[0]==evidence,'provider_envelope_differs')
        check(evidence['provider']['id']=='frida' and evidence['confidence']=='observed' and
              evidence['operation']=='instrument_with_frida' and evidence['predicate_type']=='rea.frida.instrumentation-observation' and
              bool(re.fullmatch('ev_[0-9a-f]{64}',evidence['evidence_id'])),'wrong_provider')
        parameters=evidence['parameters'];normalized=evidence['normalized_result']
        check(all(parameters.get(key)==request[key] for key in ('mode','device_id','program','argv')) and
              not parameters.get('remote'),'wrong_provider_request')
        check(normalized['mode']=='spawn' and normalized['device_id']=='local' and
              path(normalized['target'])==path(config['image']) and normalized['state']=='detached' and
              normalized['cleanup_error'] is None and normalized['messages_truncated'] is False and
              normalized['source_kind']=='file' and path(normalized['source_path'])==path(request['path']) and
              normalized['source_sha256']==digest(source),'wrong_capture_identity_or_boundary')
        pid=normalized['pid'];session=normalized['session_id'];scripts=normalized['scripts']
        check(integer(pid,1) and parameters['session_id']==session and isinstance(session,str) and bool(session) and
              len(scripts)==1,'mixed_process_session_scripts')
        script=scripts[0]['script_id'];messages=normalized['messages']
        check(0<len(messages)<=config['eventLimit'],'invalid_message_count')
        check(positive['schema']==1 and type(positive['schema']) is int and positive['runId']==run and
              positive['pid']==pid and type(positive['pid']) is int and integer(positive['port'],1) and positive['port']<=65535 and
              integer(positive['childPid'],1) and positive['childPid']!=pid and positive['childExit']==0 and type(positive['childExit']) is int and
              positive['bytesSent']==positive['bytesReceived']==7 and type(positive['bytesSent']) is type(positive['bytesReceived']) is int and
              positive['queueUnchanged'] is True,'wrong_positive_receipt')
        ready=False;elapsed=-1;installed=set();operations=[];heartbeats=[]
        root=PureWindowsPath(config['fileRoots'][0]);allowed={path(str(root/name)) for name in ('queued.json','owned.tmp','published.bin')}
        previous_counts={}
        for index,message in enumerate(messages,1):
            check(message['script_id']==script and message['type']=='send','mixed_script_or_script_error')
            row=message['payload'];data=row['data'];kind=row['kind']
            check(set(row)=={'schema','seq','runId','pid','tid','elapsedMs','kind','data'} and type(row['schema']) is int and row['schema']==1 and
                  row['runId']==run and type(row['pid']) is int and row['pid']==pid and integer(row['tid'],1) and
                  integer(row['seq'],1) and row['seq']==index and integer(row['elapsedMs']) and elapsed<=row['elapsedMs']<=10000,
                  'row_identity_sequence_time_differs')
            elapsed=row['elapsedMs']
            check(kind in ('module-ready','observer-ready','heartbeat','process-exit-entry','file-operation','network-operation','process-create'),
                  'unexpected_error_or_overflow_row')
            if 'errors' in data:check(data['errors']==[],'observer_error')
            if 'installed' in data:
                keys=[h['key'] for h in data['installed']]
                check(len(keys)==len(set(keys)) and set(keys)<=KNOWN and installed<=set(keys),'hook_inventory_differs')
                installed=set(keys)
                check(all('aliasOf' not in h or h['aliasOf'] in installed for h in data['installed']),'unbound_hook_alias')
            if kind=='observer-ready':
                check(not ready,'duplicate_ready');ready=True
            if kind in ('heartbeat','process-exit-entry'):
                check(ready and data['overflow'] is False and type(data['unknownRelativeRoots']) is int and
                      data['unknownRelativeRoots']==0,'incomplete_observation')
                counts=data['counts']
                check(REQUIRED<=installed and set(counts)<=installed and all(integer(v) for v in counts.values()) and
                      all(counts.get(k,-1)>=v for k,v in previous_counts.items()),'invalid_or_decreasing_counts')
                previous_counts=counts;heartbeats.append(index)
            if kind in ('file-operation','network-operation','process-create'):
                check(ready and data['api'] in installed and data['api'].split(':',1)[1]==data['operation'] and
                      type(data['returnValue']) is int and type(data['pending']) is bool,'operation_before_ready_or_bad_metadata')
                frames=data['frames']
                check(isinstance(frames,list) and 1<=len(frames)<=8 and
                      all(set(f)=={'module','rva'} and ((f['module'] is None and f['rva'] is None) or
                          (isinstance(f['module'],str) and bool(re.fullmatch('0x[0-9a-f]+',f['rva'])))) for f in frames) and
                      any(f['module'] in ('python314.dll','_socket.pyd') for f in frames),'missing_application_callsite')
                if kind=='file-operation':check(path(data['path']) in allowed,'unselected_file_path')
                if kind=='network-operation':
                    if 'endpoint' in data:
                        check(data['operation'] in ('connect','WSAConnect') and data['endpoint']==dict(family=4,address='127.0.0.1',port=positive['port']),
                              'unexpected_destination')
                    else:check(data.get('node')=='localhost' and data.get('service')==str(positive['port']) and data['returnValue']==0,'unexpected_resolution')
                if kind=='process-create':check(data.get('childPid')==positive['childPid'] and data['returnValue']!=0,'wrong_child_process')
                operations.append((index,kind,data))
        check(ready and heartbeats and heartbeats[-1]>max((i for i,_,_ in operations),default=0),'missing_final_snapshot')
        check(all(previous_counts.get(key,0)>0 for key in REQUIRED),'positive_hook_not_exercised')
        files=[data for _,kind,data in operations if kind=='file-operation' and data['returnValue']==0 and not data['pending']]
        def saw(name,filename,**fields):
            return any(d['operation']==name and path(d['path'])==path(str(root/filename)) and all(d.get(k)==v for k,v in fields.items()) for d in files)
        check(saw('NtCreateFile','queued.json') and saw('NtReadFile','queued.json') and
              saw('NtCreateFile','owned.tmp') and saw('NtWriteFile','owned.tmp',requestedBytes=8) and
              saw('NtReadFile','owned.tmp') and saw('NtSetInformationFile','owned.tmp',informationClass=10) and
              saw('NtOpenFile','published.bin') and saw('NtSetInformationFile','published.bin',informationClass=64),'file_control_missing')
        check(any(kind=='network-operation' and d['operation']=='connect' for _,kind,d in operations),'destination_control_missing')
        check(any(kind=='process-create' for _,kind,d in operations),'process_control_missing')
        report.update(evidence_id=evidence['evidence_id'],pid=pid,child_pid=positive['childPid'],rows=len(messages),
                      metadata_operations=len(operations),observed_counts_lower_bounds=previous_counts,
                      destination_attempt_and_resolution_qualified=not errors,file_operation_metadata_qualified=not errors,
                      application_callsite_qualified=not errors,child_creation_metadata_qualified=not errors)
    except (KeyError,IndexError,TypeError,ValueError,AttributeError):errors.append('malformed_or_incomplete_input')
    report['passed']=not errors
    return report


def read_json(p):
    raw=p.read_bytes()
    if len(raw)>MAX_BYTES:raise ValueError('input exceeds bound')
    return json.loads(raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--check-process-terminal',action='store_true')
    args=parser.parse_args();folder=args.control_dir.resolve()
    inputs=read_json(folder/'inputs.json');target=Path(inputs['config']['image'])
    report=verify(inputs,read_json(folder/'rea-result.json'),read_json(folder/'positive.json'),
                  (folder/'observer.js').read_bytes(),target_sha256=digest(target.read_bytes()))
    report['queue_unchanged']=(folder/'queue/queued.json').read_bytes()==b'authored queued report; never delivered\n'
    report['passed'] &= report['queue_unchanged']
    if args.check_process_terminal:
        report['terminal']=terminal_pid(report['pid']) if integer(report.get('pid'),1) else dict(terminal=False,not_checked=True)
        report['passed'] &= report['terminal']['terminal']
    with args.output.open('x',encoding='utf-8') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','rows','metadata_operations','errors') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
