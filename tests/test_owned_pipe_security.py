"""Asset-free bounded-parser and owned-query failure boundary controls."""
from copy import deepcopy
import json
import struct
from types import SimpleNamespace
import unittest
from tools.owned_pipe_security import inspect, parse_security_descriptor, parse_token_information, LIMIT
from tools.owned_suspended_launch import SuspendedChild

NONCE='0123456789abcdef0123456789abcdef'


def sid(rid=1000, authority=5):
    return bytes([1,1])+authority.to_bytes(6,'big')+struct.pack('<I',rid)


def ace(kind=0, flags=0, mask=0x12019f, raw_sid=None):
    raw_sid=raw_sid or sid()
    return struct.pack('<BBHI',kind,flags,8+len(raw_sid),mask)+raw_sid


def descriptor(*entries, control=0x8004, owner_sid=None, group_sid=None):
    payload=b''; owner=group=dacl=0
    if owner_sid is not None:owner=20+len(payload);payload+=owner_sid
    if group_sid is not None:group=20+len(payload);payload+=group_sid
    if entries:
        dacl=20+len(payload);body=b''.join(entries)
        payload+=struct.pack('<BBHHH',2,0,8+len(body),len(entries),0)+body
    return struct.pack('<BBHIIII',1,0,control,owner,group,0,dacl)+payload


class Observer:
    def __init__(self):
        self.owner=SuspendedChild();self.owner.pid=100;self.owner.handle=901
        self.owner.job=SimpleNamespace(handle=902)
        self.actual=dict(pid=101,creation_filetime=1000,image=r'C:\owned\child.exe',image_sha256='a'*64,in_owned_job=True)
        self.calls=[];self.fail={};self.closed=[];self.live={901:True,201:True}
        self.pipe=dict(file_type=3,server_pid=100)
        self.fact=dict(sid_sha256='b'*64,attributes=0)
    def record(self):return dict(self.actual,exit=None)
    def call(self,name,*args):
        self.calls.append((name,*args))
        if name in self.fail:raise self.fail[name]
    def validate_owner(self,owner):
        self.call('validate_owner',owner.handle)
        if owner is not self.owner:raise RuntimeError('wrong owner')
    def in_job(self,handle,job):self.call('in_job',handle,job)
    def exit(self,handle):
        self.call('exit',handle)
        return None if self.live.get(handle) else dict(exit_code=0)
    def open(self,pid):self.call('open',pid);return 201
    def identity(self,handle,pid,job):
        self.call('identity',handle,pid,job)
        return dict(pid=100,creation_filetime=900,image=r'C:\owned\root.exe',image_sha256='d'*64,in_owned_job=True) if handle==901 else deepcopy(self.actual)
    def duplicate(self,root,remote):self.call('duplicate',root,remote);return 301
    def pipe_identity(self,handle):self.call('pipe_identity',handle);return dict(self.pipe)
    def security(self,handle,information,nonce):
        self.call('security'+str(information),handle)
        return parse_security_descriptor(descriptor(ace()),nonce=nonce)
    def open_token(self,handle):self.call('open_token'+str(handle));return 401 if handle==901 else 402
    def token_information(self,token,information,nonce):
        self.call('token'+str(information),token)
        return dict(self.fact) if information==1 else dict(value=0)
    def close(self,handle):
        self.call('close'+str(handle));self.closed.append(handle)


class ParserTests(unittest.TestCase):
    def test_allow_deny_flags_salt_equality_and_no_raw_sid(self):
        raw=sid();data=descriptor(ace(0),ace(1,0x1b,0x40000000),owner_sid=raw,group_sid=raw)
        result=parse_security_descriptor(data,nonce=NONCE)
        self.assertEqual(result['owner'],result['group'])
        self.assertEqual(result['owner']['sid_sha256'],result['dacl']['aces'][0]['sid_sha256'])
        deny=result['dacl']['aces'][1]
        self.assertEqual((deny['classification'],deny['flags'],deny['mask']),('deny',0x1b,0x40000000))
        self.assertNotEqual(result['owner'],parse_security_descriptor(data,nonce='f'*32)['owner'])
        encoded=json.dumps(result)
        self.assertNotIn(raw.hex(),encoded);self.assertNotIn('S-1-',encoded)

    def test_absent_null_and_empty_dacl_are_distinct(self):
        absent=parse_security_descriptor(descriptor(control=0x8000),nonce=NONCE)
        null=parse_security_descriptor(descriptor(),nonce=NONCE)
        empty=struct.pack('<BBHIIII',1,0,0x8004,0,0,0,20)+struct.pack('<BBHHH',2,0,8,0,0)
        self.assertEqual(absent['dacl']['state'],'absent');self.assertEqual(null['dacl']['state'],'null')
        self.assertEqual(parse_security_descriptor(empty,nonce=NONCE)['dacl'],dict(state='present',revision=2,size=8,ace_count=0,aces=[]))

    def test_label_public_integrity_and_unknown_ace_is_not_deny(self):
        raw=ace(17,0x10,3,sid(0x2000,16));data=bytearray(descriptor(raw));struct.pack_into('<H',data,2,0x8010)
        dacl=struct.unpack_from('<I',data,16)[0];struct.pack_into('<I',data,12,dacl);struct.pack_into('<I',data,16,0)
        label=parse_security_descriptor(bytes(data),nonce=NONCE)['sacl']['aces'][0]
        self.assertEqual(label['integrity_rid'],0x2000)
        opaque=parse_security_descriptor(descriptor(struct.pack('<BBHI',99,2,8,123)),nonce=NONCE)['dacl']['aces'][0]
        self.assertEqual(opaque['classification'],'unclassified');self.assertNotIn('mask',opaque)
        self.assertEqual(len(opaque['opaque_sha256']),64)

    def test_malformed_descriptor_acl_ace_and_sid_bounds_rejected(self):
        valid=descriptor(ace(),owner_sid=sid())
        bad=[b'',valid[:19],b'x'*(LIMIT+1)]
        for offset,fmt,value in [(0,'B',2),(2,'H',4),(4,'I',21),(4,'I',0xfffffffc),(16,'I',24)]:
            data=bytearray(valid);struct.pack_into('<'+fmt,data,offset,value);bad.append(bytes(data))
        for data in (descriptor(ace()),):
            dacl=struct.unpack_from('<I',data,16)[0]
            for offset,fmt,value in [(dacl+2,'H',65535),(dacl+4,'H',4097),(dacl+8+2,'H',3),(dacl+8+8+1,'B',16)]:
                mutation=bytearray(data);struct.pack_into('<'+fmt,mutation,offset,value);bad.append(bytes(mutation))
        for data in bad:
            with self.subTest(length=len(data)),self.assertRaises(ValueError):parse_security_descriptor(data,nonce=NONCE)

    def test_token_sid_pointers_counts_scalar_classes_and_group_attributes(self):
        base=0x1000;raw=sid()
        user=struct.pack('<QI4x',base+16,2)+raw
        result=parse_token_information(user,information_class=1,base_address=base,nonce=NONCE)
        groups=struct.pack('<I4xQI4x',1,base+24,0x14)+raw
        group=parse_token_information(groups,information_class=2,base_address=base,nonce=NONCE)
        self.assertEqual(group['entries'][0]['sid_sha256'],result['sid_sha256']);self.assertEqual(group['entries'][0]['attributes'],0x14)
        for cls,value in ((8,1),(27,3),(29,0)):
            parsed=parse_token_information(struct.pack('<I',value),information_class=cls,base_address=base,nonce=NONCE)
            self.assertEqual(parsed['value'],value)
        mutations=[(1,struct.pack('<QI4x',base-4,0)+raw),(1,struct.pack('<QI4x',base,0)+raw),
                   (2,struct.pack('<I4x',4097)),(2,struct.pack('<I4xQI4x',1,base+8,0)+raw),
                   (29,struct.pack('<I',2)),(8,struct.pack('<I',3)),(7,b'\0'*4)]
        for cls,data in mutations:
            with self.subTest(cls=cls),self.assertRaises(ValueError):parse_token_information(data,information_class=cls,base_address=base,nonce=NONCE)


class InspectionTests(unittest.TestCase):
    def run_inspect(self,api=None,record=None,**kwargs):
        api=api or Observer()
        return api,inspect(api.owner,child_record=record or api.record(),remote_pipe_handle=700,nonce=NONCE,_observer=api,**kwargs)

    def test_snapshot_is_query_only_with_owned_cleanup_and_equal_hashed_users(self):
        api,result=self.run_inspect()
        self.assertTrue(result['snapshot_qualified']);self.assertTrue(result['parent_child_user_equal'])
        self.assertEqual(result['pipe_access'],0x20080);self.assertEqual(result['duplicate_options'],0);self.assertEqual(result['token_access'],8)
        self.assertEqual(api.closed,[402,401,301,201]);self.assertEqual(api.owner.handle,901);self.assertEqual(api.owner.job.handle,902)
        self.assertEqual(result['cleanup']['owned_handles_opened'],4);self.assertTrue(result['cleanup']['complete'])
        self.assertFalse(result['causal_access_check']);self.assertFalse(result['full_P8_qualified'])

    def test_foreign_job_or_reused_pid_refuses_duplicate_and_closes_query_handle(self):
        for change in [dict(pid=102),dict(creation_filetime=1001),dict(image=r'C:\other.exe'),dict(image_sha256='c'*64),dict(in_owned_job=False)]:
            api=Observer();record=api.record();api.actual.update(change)
            _,result=self.run_inspect(api,record)
            self.assertFalse(result['identity_validated']);self.assertEqual(api.closed,[201])
            self.assertFalse(any(call[0]=='duplicate' for call in api.calls))
        api=Observer();api.fail['identity']=RuntimeError('foreign owned job')
        _,result=self.run_inspect(api);self.assertFalse(result['snapshot_qualified']);self.assertEqual(api.closed,[])
        api=Observer();original=api.identity
        def foreign_child(handle,pid,job):
            if handle==201:raise RuntimeError('child not in job')
            return original(handle,pid,job)
        api.identity=foreign_child
        _,result=self.run_inspect(api);self.assertFalse(result['identity_validated']);self.assertEqual(api.closed,[201])

    def test_dead_owner_or_child_never_reaches_pipe_query(self):
        for handle in (901,201):
            api=Observer();api.live[handle]=False;_,result=self.run_inspect(api)
            self.assertFalse(result['snapshot_qualified']);self.assertFalse(any(call[0]=='duplicate' for call in api.calls))
            self.assertEqual(api.closed,[] if handle==901 else [201])

    def test_wrong_pipe_type_or_server_and_duplicate_failure_close_only_owned(self):
        for change in (dict(file_type=1),dict(server_pid=999)):
            api=Observer();api.pipe.update(change);_,result=self.run_inspect(api)
            self.assertFalse(result['pipe_identity_validated']);self.assertEqual(api.closed,[301,201])
            self.assertFalse(any(call[0].startswith('security') for call in api.calls))
        api=Observer();api.fail['duplicate']=OSError('denied');_,result=self.run_inspect(api)
        self.assertFalse(result['snapshot_qualified']);self.assertEqual(api.closed,[201])

    def test_optional_label_and_token_queries_preserve_unknown_not_false(self):
        api=Observer();error=OSError('must not leak SID/rawbuffer');error.winerror=5
        api.fail.update(security16=error,token29=error)
        _,result=self.run_inspect(api)
        self.assertTrue(result['snapshot_qualified']);self.assertFalse(result['label_security']['known'])
        for role in ('parent','child'):self.assertEqual(result['tokens'][role]['is_app_container'],dict(known=False))
        self.assertEqual([r['winerror'] for r in result['errors']],[5,5,5])
        self.assertNotIn('must not leak',json.dumps(result));self.assertEqual(api.closed,[402,401,301,201])

    def test_base_failure_token_open_failure_and_cleanup_error_remain_explicit(self):
        api=Observer();api.fail.update(security7=OSError('fail'),open_token901=OSError('fail'),close301=OSError('fail'))
        _,result=self.run_inspect(api)
        self.assertFalse(result['snapshot_qualified']);self.assertFalse(result['base_security']['known'])
        self.assertIsNone(result['parent_child_user_equal']);self.assertFalse(result['tokens']['parent']['known'])
        self.assertEqual(api.closed,[402,201]);self.assertFalse(result['cleanup']['complete'])
        self.assertEqual(result['cleanup']['owned_handles_opened'],3)

    def test_wrong_owner_and_bad_inputs_have_no_query_side_effects(self):
        api=Observer()
        with self.assertRaises(ValueError):inspect(SimpleNamespace(handle=901,job=api.owner.job),child_record=api.record(),remote_pipe_handle=700,nonce=NONCE,_observer=api)
        for change in (dict(pid=True),dict(pid=0),dict(creation_filetime=0),dict(image='relative'),dict(image_sha256='bad'),dict(in_owned_job=False),dict(exit={})):
            with self.subTest(change=change),self.assertRaises(ValueError):self.run_inspect(api,dict(api.record(),**change))
        for handle in (True,0,-1,2**64-1):
            with self.assertRaises(ValueError):inspect(api.owner,child_record=api.record(),remote_pipe_handle=handle,nonce=NONCE,_observer=api)
        with self.assertRaises(ValueError):self.run_inspect(api,dict(api.record(),pid=100))
        self.assertEqual(api.calls,[])

    def test_mid_snapshot_owner_mutation_fails_liveness_boundary(self):
        api=Observer();original=api.token_information
        def mutate(*args):
            value=original(*args);api.owner.job.handle=903;return value
        api.token_information=mutate
        _,result=self.run_inspect(api)
        self.assertFalse(result['snapshot_qualified']);self.assertEqual(result['errors'][-1]['phase'],'post_snapshot_liveness')
        self.assertEqual(api.closed,[402,401,301,201])

    def test_missing_api_handles_never_become_owned_or_close_borrowed_handles(self):
        api=Observer();api.open=lambda pid:None
        _,result=self.run_inspect(api)
        self.assertEqual(result['errors'][0]['phase'],'child_open');self.assertEqual(api.closed,[])
        api=Observer();api.duplicate=lambda root,remote:None
        _,result=self.run_inspect(api)
        self.assertEqual(result['errors'][0]['phase'],'duplicate_pipe');self.assertEqual(api.closed,[201])
        api=Observer();api.open_token=lambda handle:None
        _,result=self.run_inspect(api)
        self.assertIsNone(result['parent_child_user_equal']);self.assertEqual(api.closed,[301,201])
        self.assertEqual(result['cleanup']['owned_handles_opened'],2)

    def test_process_exit_during_queries_prevents_snapshot_qualification(self):
        api=Observer();original=api.token_information
        def exit_child(*args):
            value=original(*args);api.live[201]=False;return value
        api.token_information=exit_child
        _,result=self.run_inspect(api)
        self.assertFalse(result['snapshot_qualified']);self.assertEqual(result['errors'][-1]['phase'],'post_snapshot_liveness')
        self.assertTrue(result['base_security']['known']);self.assertEqual(api.closed,[402,401,301,201])


if __name__=='__main__':unittest.main()
