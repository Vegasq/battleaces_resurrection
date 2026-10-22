"""Authored evidence mutations; no game/runtime/sockets/filesystem observation."""
from copy import deepcopy
import ast
import hashlib
import json
import unittest
from tools.frida_attribution_source import build_source,control_request,validate_config
from tools.verify_attribution_control import KNOWN,REQUIRED,verify

IMAGE=r'R:\owned\python.exe'
FOLDER=r'R:\owned\control'
RUN='1'*32
TARGET='a'*64


def fixture():
    config,request=control_request(IMAGE,FOLDER,RUN);source=build_source(config).encode()
    inputs=dict(schema=1,config=config,request=request,target_sha256=TARGET,source_sha256=hashlib.sha256(source).hexdigest())
    positive=dict(schema=1,pid=100,runId=RUN,port=12345,childPid=101,childExit=0,bytesSent=7,bytesReceived=7,queueUnchanged=True)
    hooks=[dict(key=key) for key in sorted(KNOWN)];counts={k:int(k in REQUIRED) for k in KNOWN}
    frames=[dict(module='python314.dll',rva='0x123'),dict(module='kernelbase.dll',rva='0x456')]
    rows=[]
    def add(kind,data):
        rows.append(dict(schema=1,seq=len(rows)+1,runId=RUN,pid=100,tid=200,elapsedMs=len(rows)*10,kind=kind,data=data))
    add('module-ready',dict(installed=hooks,errors=[]))
    add('observer-ready',dict(installed=hooks,errors=[]))
    for operation,name,extra in (
        ('NtCreateFile','queued.json',{}),('NtReadFile','queued.json',{}),
        ('NtCreateFile','owned.tmp',{}),('NtWriteFile','owned.tmp',dict(requestedBytes=8)),
        ('NtReadFile','owned.tmp',{}),('NtSetInformationFile','owned.tmp',dict(informationClass=10)),
        ('NtOpenFile','published.bin',{}),('NtSetInformationFile','published.bin',dict(informationClass=64))):
        add('file-operation',dict(operation=operation,path=FOLDER+'\\queue\\'+name,api='ntdll.dll:'+operation,
                                  frames=frames,returnValue=0,pending=False,**extra))
    add('network-operation',dict(operation='GetAddrInfoW',api='ws2_32.dll:GetAddrInfoW',node='localhost',service='12345',frames=frames,returnValue=0,pending=False))
    add('network-operation',dict(operation='connect',api='ws2_32.dll:connect',endpoint=dict(family=4,address='127.0.0.1',port=12345),frames=frames,returnValue=-1,pending=False))
    add('process-create',dict(operation='CreateProcessW',api='kernelbase.dll:CreateProcessW',childPid=101,frames=frames,returnValue=1,pending=False))
    add('heartbeat',dict(counts=counts,installed=hooks,errors=[],unknownRelativeRoots=0,overflow=False))
    messages=[dict(script_id='script',type='send',payload=row) for row in rows]
    normalized=dict(mode='spawn',device_id='local',target=IMAGE,pid=100,state='detached',cleanup_error=None,
        messages_truncated=False,source_kind='file',source_path=request['path'],source_sha256=inputs['source_sha256'],
        session_id='session',scripts=[dict(script_id='script')],messages=messages)
    evidence=dict(operation='instrument_with_frida',provider=dict(id='frida'),confidence='observed',evidence_id='ev_'+'b'*64,
        predicate_type='rea.frida.instrumentation-observation',parameters={k:deepcopy(request[k]) for k in ('mode','device_id','program','argv')},normalized_result=normalized)
    evidence['parameters']['session_id']='session'
    return dict(inputs=inputs,result=dict(structuredContent=evidence),positive=positive,source=source,target_sha256=TARGET)


def check(value):
    value=deepcopy(value)
    value['result']['content']=[dict(type='text',text=json.dumps(value['result']['structuredContent']))]
    return verify(**value)


def rows(value):return value['result']['structuredContent']['normalized_result']['messages']


class AttributionControlTests(unittest.TestCase):
    def test_positive_scope_keeps_network_absence_descendant_wire_and_exit_unqualified(self):
        result=check(fixture());self.assertTrue(result['passed'],result)
        for key in ('analytics_removal_qualified','descendants_instrumented','kernel_capture','wire_dns_qualified','exit_code_qualified'):
            self.assertFalse(result[key],key)
        self.assertTrue(result['application_callsite_qualified'])

    def test_generator_preserves_windows_paths_and_control_program_as_literals(self):
        folder="R:\\owned space\\quote' name\\control"
        config,request=control_request(IMAGE,folder,RUN)
        source=build_source(config)
        line=next(line for line in source.splitlines() if line.startswith('const config='))
        self.assertEqual(json.loads(line[len('const config='):line.index(', api=')]),config)
        parsed=ast.parse(request['argv'][3])
        assignment=parsed.body[1]
        self.assertEqual(assignment.value.args[0].value,folder)
        self.assertEqual(request['argv'][:3],['-I','-B','-c'])

    def test_rejects_mixed_pid_session_script_source_request_or_provider(self):
        for mode in ('pid','session','script','source','request','remote','confidence','provider','target','truncated','cleanup'):
            value=fixture();e=value['result']['structuredContent'];n=e['normalized_result']
            if mode=='pid':rows(value)[2]['payload']['pid']=999
            elif mode=='session':e['parameters']['session_id']='other'
            elif mode=='script':rows(value)[2]['script_id']='other'
            elif mode=='source':value['source']+=b'// changed'
            elif mode=='request':e['parameters']['argv']=['other']
            elif mode=='remote':e['parameters']['remote']={'address':'elsewhere'}
            elif mode=='confidence':e['confidence']='inferred'
            elif mode=='provider':e['provider']['id']='other'
            elif mode=='target':n['target']=r'R:\other\python.exe'
            elif mode=='truncated':n['messages_truncated']=True
            elif mode=='cleanup':n['cleanup_error']='failed'
            with self.subTest(mode=mode):self.assertFalse(check(value)['passed'])

    def test_rejects_errors_gaps_early_snapshots_missing_hooks_and_counts(self):
        for mode in ('errors','gap','time','missing_final','missing_hook','missing_count','bool_count','unresolved','bool_root','overflow','decode_error','notready'):
            value=fixture();m=rows(value);last=m[-1]['payload']['data']
            if mode=='errors':last['errors']=['test']
            elif mode=='gap':m[3]['payload']['seq']=99
            elif mode=='time':m[-1]['payload']['elapsedMs']=0
            elif mode=='missing_final':m.pop()
            elif mode=='missing_hook':last['installed']=[h for h in last['installed'] if h['key']!='ws2_32.dll:connect']
            elif mode=='missing_count':last['counts']['ws2_32.dll:connect']=0
            elif mode=='bool_count':last['counts']['ws2_32.dll:connect']=True
            elif mode=='unresolved':last['unknownRelativeRoots']=1
            elif mode=='bool_root':last['unknownRelativeRoots']=False
            elif mode=='overflow':last['overflow']=True
            elif mode=='decode_error':m[3]['payload']['kind']='decode-error'
            elif mode=='notready':m[1]['payload']['kind']='module-ready'
            with self.subTest(mode=mode):self.assertFalse(check(value)['passed'])

    def test_rejects_misdecoded_names_destinations_children_file_classes_and_callers(self):
        for mode in ('ansi_tail','port','address','family','child','rename','delete','pending','write','file_escape','frames'):
            value=fixture();m=rows(value)
            data=lambda index:m[index]['payload']['data']
            if mode=='ansi_tail':data(10)['node']='localhost\x00unrelated heap'
            elif mode=='port':data(11)['endpoint']['port']=99
            elif mode=='address':data(11)['endpoint']['address']='192.0.2.1'
            elif mode=='family':data(11)['endpoint']['family']=6
            elif mode=='child':data(12)['childPid']=999
            elif mode=='rename':data(7)['informationClass']=14
            elif mode=='delete':data(9)['informationClass']=14
            elif mode=='pending':data(5)['pending']=True
            elif mode=='write':data(5)['requestedBytes']=7
            elif mode=='file_escape':data(2)['path']=r'R:\outside\queued.json'
            elif mode=='frames':data(5)['frames']=[dict(module='kernelbase.dll',rva='0x1')]
            with self.subTest(mode=mode):self.assertFalse(check(value)['passed'])

    def test_positive_receipt_requires_actual_counts_identity_and_child_completion(self):
        for key,value in (('runId','2'*32),('pid',True),('childPid',100),('childExit',True),('childExit',1),
                          ('bytesSent',True),('bytesReceived',0),('queueUnchanged',False)):
            item=fixture();item['positive'][key]=value
            with self.subTest(key=key,value=value):self.assertFalse(check(item)['passed'])

    def test_malformed_inputs_fail_closed_without_exposing_raw_data(self):
        value=fixture();value['result']['structuredContent']['normalized_result']['messages']=[dict(type='error',payload='private-placeholder')]
        result=check(value);self.assertFalse(result['passed']);self.assertNotIn('private-placeholder',str(result))
        value=fixture();value['inputs']={};self.assertFalse(check(value)['passed'])

    def test_source_configuration_rejects_unbounded_or_foreign_path_shapes(self):
        config=fixture()['inputs']['config']
        for changes in ({'fileRoots':[]},{'fileRoots':None},{'fileRoots':['R:\\']},{'eventLimit':True},
                        {'eventLimit':4097},{'image':'relative.exe'},{'runId':'A'*32},{'extra':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate_config(config|changes)


if __name__=='__main__':unittest.main()
