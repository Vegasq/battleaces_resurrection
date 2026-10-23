"""Query-only security snapshot of an existing owned server pipe and processes.

No pipe names/contents, remote memory, raw SIDs, privileges, setters, access-check
simulation, impersonation or process creation/termination. Facts are snapshots,
not an explanation of an observed access denial or a privacy qualification.
"""
from __future__ import annotations
import ctypes as c
from ctypes import wintypes as w
import hashlib
from pathlib import PureWindowsPath
import re
import struct
from tools.owned_job_tracker import _WindowsObserver
from tools.owned_suspended_launch import SuspendedChild

LIMIT = 1024 * 1024
PIPE_ACCESS = 0x20080  # READ_CONTROL | FILE_READ_ATTRIBUTES
TOKEN_CLASSES = {'user': 1, 'groups': 2, 'restricted_sids': 11, 'type': 8,
                 'integrity': 25, 'is_app_container': 29, 'mandatory_policy': 27}


def _nonce(value):
    if not isinstance(value, str) or not 16 <= len(value) <= 256 or '\0' in value:
        raise ValueError('Bounded nonempty per-capture nonce required')
    return value


def _digest(data, nonce, domain):
    return hashlib.sha256(domain.encode('ascii') + b'\0' + nonce.encode('utf-8') + b'\0' + data).hexdigest()


def _buffer(data):
    if type(data) is not bytes or not 1 <= len(data) <= LIMIT:
        raise ValueError('Bounded local byte buffer required')


def _sid(data, offset, end, nonce):
    if type(offset) is not int or offset < 0 or offset + 8 > end or end > len(data):
        raise ValueError('SID header outside bounded buffer')
    revision, count = data[offset:offset+2]
    length = 8 + 4 * count
    if revision != 1 or count > 15 or offset + length > end:
        raise ValueError('Malformed bounded SID')
    raw = data[offset:offset+length]
    value = {'sid_sha256': _digest(raw, nonce, 'sid')}
    # SECURITY_MANDATORY_LABEL_AUTHORITY is public; no other RID is exposed.
    if raw[2:8] == b'\0\0\0\0\0\x10' and count == 1:
        value['integrity_rid'] = struct.unpack_from('<I', raw, 8)[0]
    return value, offset + length


def _acl(data, offset, nonce):
    if offset % 4 or offset < 20 or offset + 8 > len(data):
        raise ValueError('ACL header outside descriptor')
    revision, _, size, count, _ = struct.unpack_from('<BBHHH', data, offset)
    if revision not in (2, 4) or size < 8 or offset + size > len(data) or count > 4096:
        raise ValueError('Malformed bounded ACL')
    cursor, end, entries = offset + 8, offset + size, []
    for _ in range(count):
        if cursor + 4 > end:
            raise ValueError('ACE header outside ACL')
        kind, flags, length = struct.unpack_from('<BBH', data, cursor)
        if length < 4 or length % 4 or cursor + length > end:
            raise ValueError('Malformed bounded ACE')
        item = dict(type=kind, flags=flags, size=length)
        if kind in (0, 1, 17):
            if length < 16:
                raise ValueError('Standard ACE is too short')
            sid, used = _sid(data, cursor + 8, cursor + length, nonce)
            if used != cursor + length:
                raise ValueError('Standard ACE has unexpected trailing data')
            item.update(classification={0: 'allow', 1: 'deny', 17: 'mandatory_label'}[kind],
                        mask=struct.unpack_from('<I', data, cursor + 4)[0], **sid)
        else:
            item.update(classification='unclassified',
                        opaque_sha256=_digest(data[cursor:cursor+length], nonce, 'ace'))
        entries.append(item)
        cursor += length
    return dict(state='present', revision=revision, size=size, ace_count=count, aces=entries)


def parse_security_descriptor(data: bytes, *, nonce: str):
    """Parse only a bounded SECURITY_DESCRIPTOR_RELATIVE, emitting no raw SIDs."""
    _nonce(nonce); _buffer(data)
    if len(data) < 20:
        raise ValueError('Relative descriptor header missing')
    revision, _, control, owner, group, sacl, dacl = struct.unpack_from('<BBHIIII', data)
    if revision != 1 or not control & 0x8000:
        raise ValueError('Self-relative revision-one descriptor required')
    result = dict(revision=revision, control=control)
    for name, offset in (('owner', owner), ('group', group)):
        if not offset:
            result[name] = None
        else:
            if offset < 20 or offset % 4:
                raise ValueError('SID offset outside descriptor payload')
            result[name] = _sid(data, offset, len(data), nonce)[0]
    for name, offset, bit in (('dacl', dacl, 4), ('sacl', sacl, 16)):
        if not control & bit:
            if offset:
                raise ValueError('Absent ACL has a nonzero offset')
            result[name] = dict(state='absent')
        elif not offset:
            result[name] = dict(state='null')
        else:
            result[name] = _acl(data, offset, nonce)
    return result


def parse_token_information(data: bytes, *, information_class: int, base_address: int, nonce: str):
    """Parse copied x64 token buffers; every SID pointer must remain in this copy."""
    _nonce(nonce); _buffer(data)
    if type(base_address) is not int or base_address <= 0:
        raise ValueError('Local buffer base required')
    def sid_at(pointer):
        offset = pointer - base_address
        if offset % 4:
            raise ValueError('Unaligned token SID')
        return _sid(data, offset, len(data), nonce)[0]
    if information_class in (1, 25):
        if len(data) < 16:
            raise ValueError('SID_AND_ATTRIBUTES missing')
        pointer, attributes = struct.unpack_from('<QI', data)
        if pointer < base_address + 16:
            raise ValueError('Token SID overlaps attributes header')
        return dict(sid_at(pointer), attributes=attributes)
    if information_class in (2, 11):
        if len(data) < 8:
            raise ValueError('TOKEN_GROUPS header missing')
        count = struct.unpack_from('<I', data)[0]
        if count > 4096 or 8 + 16 * count > len(data):
            raise ValueError('TOKEN_GROUPS entries exceed bounded buffer')
        entries = []
        for index in range(count):
            pointer, attributes = struct.unpack_from('<QI', data, 8 + 16 * index)
            if pointer < base_address + 8 + 16 * count:
                raise ValueError('Token SID overlaps group table')
            entries.append(dict(sid_at(pointer), attributes=attributes))
        return dict(count=count, entries=entries)
    if information_class in (8, 27, 29):
        if len(data) != 4:
            raise ValueError('Token scalar size differs')
        value = struct.unpack('<I', data)[0]
        if information_class == 8:
            if value not in (1, 2):
                raise ValueError('Unknown token type')
            return dict(value=value, name={1:'primary', 2:'impersonation'}[value])
        if information_class == 29:
            if value not in (0, 1):
                raise ValueError('Unknown app-container BOOL')
            return dict(value=bool(value))
        return dict(value=value)
    raise ValueError('Token class is outside the query-only whitelist')


class _SecurityObserver(_WindowsObserver):
    def __init__(self):
        super().__init__()
        if c.sizeof(c.c_void_p) != 8:
            raise RuntimeError('x64 local token layouts required')
        self.adv = c.WinDLL('advapi32', use_last_error=True)
        declarations = {
            'GetCurrentProcess': ([], w.HANDLE),
            'DuplicateHandle': ([w.HANDLE,w.HANDLE,w.HANDLE,c.POINTER(w.HANDLE),w.DWORD,w.BOOL,w.DWORD],w.BOOL),
            'GetFileType': ([w.HANDLE],w.DWORD),
            'GetNamedPipeServerProcessId': ([w.HANDLE,c.POINTER(w.ULONG)],w.BOOL),
            'LocalFree': ([c.c_void_p],c.c_void_p),
        }
        for name,(args,result) in declarations.items():
            fn=getattr(self.api,name);fn.argtypes,fn.restype=args,result
        declarations = {
            'GetSecurityInfo': ([w.HANDLE,c.c_int,w.DWORD,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p,c.POINTER(c.c_void_p)],w.DWORD),
            'GetSecurityDescriptorControl': ([c.c_void_p,c.POINTER(w.WORD),c.POINTER(w.DWORD)],w.BOOL),
            'GetSecurityDescriptorLength': ([c.c_void_p],w.DWORD),
            'MakeSelfRelativeSD': ([c.c_void_p,c.c_void_p,c.POINTER(w.DWORD)],w.BOOL),
            'OpenProcessToken': ([w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)],w.BOOL),
            'GetTokenInformation': ([w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)],w.BOOL),
        }
        for name,(args,result) in declarations.items():
            fn=getattr(self.adv,name);fn.argtypes,fn.restype=args,result

    def duplicate(self, root, remote):
        handle=w.HANDLE()
        self._check(self.api.DuplicateHandle(root,remote,self.api.GetCurrentProcess(),c.byref(handle),PIPE_ACCESS,False,0))
        if not handle.value:
            raise RuntimeError('DuplicateHandle returned no owned handle')
        return handle.value

    def pipe_identity(self, handle):
        c.set_last_error(0)
        kind=int(self.api.GetFileType(handle))
        if kind != 3:
            if kind == 0 and c.get_last_error():
                raise c.WinError(c.get_last_error())
            raise RuntimeError('Duplicated object is not a pipe')
        pid=w.ULONG()
        self._check(self.api.GetNamedPipeServerProcessId(handle,c.byref(pid)))
        return dict(file_type=kind, server_pid=int(pid.value))

    def security(self, handle, information, nonce):
        pointer=c.c_void_p()
        status=int(self.adv.GetSecurityInfo(handle,6,information,None,None,None,None,c.byref(pointer)))
        try:
            if status:
                raise c.WinError(status)
            if not pointer.value:
                raise RuntimeError('Security descriptor allocation missing')
            control=w.WORD(); revision=w.DWORD()
            self._check(self.adv.GetSecurityDescriptorControl(pointer,c.byref(control),c.byref(revision)))
            if control.value & 0x8000:
                size=int(self.adv.GetSecurityDescriptorLength(pointer))
                if not 20 <= size <= LIMIT:
                    raise ValueError('Descriptor size outside bound')
                data=c.string_at(pointer,size)
            else:
                size=w.DWORD()
                ok=self.adv.MakeSelfRelativeSD(pointer,None,c.byref(size))
                error=c.get_last_error()
                if not ok and error != 122:
                    raise c.WinError(error)
                if ok or not 20 <= size.value <= LIMIT:
                    raise RuntimeError('Bounded descriptor conversion probe failed')
                buffer=c.create_string_buffer(size.value); capacity=size.value
                self._check(self.adv.MakeSelfRelativeSD(pointer,buffer,c.byref(size)))
                if not 20 <= size.value <= capacity:
                    raise ValueError('Descriptor conversion size differs')
                data=buffer.raw[:size.value]
            return parse_security_descriptor(data,nonce=nonce)
        finally:
            if pointer.value and self.api.LocalFree(pointer):
                raise RuntimeError('LocalFree security descriptor failed')

    def open_token(self, process):
        token=w.HANDLE()
        self._check(self.adv.OpenProcessToken(process,8,c.byref(token)))
        if not token.value:
            raise RuntimeError('Token handle missing')
        return token.value

    def token_information(self, token, information_class, nonce):
        size=w.DWORD()
        ok=self.adv.GetTokenInformation(token,information_class,None,0,c.byref(size))
        error=c.get_last_error()
        if not ok and error != 122:
            raise c.WinError(error)
        if ok or not 1 <= size.value <= LIMIT:
            raise RuntimeError('Bounded token information probe failed')
        buffer=c.create_string_buffer(size.value); capacity=size.value
        self._check(self.adv.GetTokenInformation(token,information_class,buffer,capacity,c.byref(size)))
        if not 1 <= size.value <= capacity:
            raise ValueError('Token information returned size differs')
        return parse_token_information(buffer.raw[:size.value],information_class=information_class,
                                       base_address=c.addressof(buffer),nonce=nonce)


def _error(phase,error):
    # Never stringify OS buffers, SIDs, security descriptors or exception payloads.
    return dict(phase=phase,type=type(error).__name__,winerror=getattr(error,'winerror',None))


def _image(value):
    if not isinstance(value,str) or '\0' in value or not PureWindowsPath(value).is_absolute():
        raise ValueError('Tracked absolute image required')
    return str(PureWindowsPath(value.removeprefix('\\\\?\\'))).casefold()


def _record(value):
    if type(value) is not dict or value.get('in_owned_job') is not True or 'exit' not in value or value['exit'] is not None:
        raise ValueError('Live owned tracker record required')
    if type(value.get('pid')) is not int or not 0 < value['pid'] <= 0xffffffff:
        raise ValueError('Tracked PID required')
    if type(value.get('creation_filetime')) is not int or not 0 < value['creation_filetime'] < 2**64:
        raise ValueError('Tracked creation FILETIME required')
    _image(value.get('image'))
    if not isinstance(value.get('image_sha256'),str) or not re.fullmatch('[0-9a-fA-F]{64}',value['image_sha256']):
        raise ValueError('Tracked executable digest required')
    return {key:value[key] for key in ('pid','creation_filetime','image','image_sha256','in_owned_job')}


def inspect(owner, *, child_record, remote_pipe_handle: int, nonce: str, _observer=None):
    """Return a JSON snapshot; runtime failures remain unknown and clean up locally.

    Only this call's query/token/duplicated handles are closed. The owner process
    and job handles are borrowed. `_observer` exists solely for authored tests.
    """
    _nonce(nonce); record=_record(child_record)
    if type(owner) is not SuspendedChild or not owner.handle or not owner.job or not owner.job.handle:
        raise ValueError('Exact existing SuspendedChild owner required')
    if type(owner.pid) is not int or not 0 < owner.pid <= 0xffffffff:
        raise ValueError('Existing owner PID required')
    if record['pid']==owner.pid:
        raise ValueError('Distinct tracked child process required')
    if type(remote_pipe_handle) is not int or not 0 < remote_pipe_handle < 2**64-1:
        raise ValueError('Positive existing remote pipe handle required')
    observer=_observer or _SecurityObserver()
    root_handle,job_handle,root_pid=owner.handle,owner.job.handle,owner.pid
    result=dict(schema=1,query_only=True,pipe_access=PIPE_ACCESS,duplicate_options=0,
                token_access=8,owner_pid=owner.pid,child_pid=record['pid'],identity_validated=False,
                pipe_identity_validated=False,base_security={'known':False},label_security={'known':False},
                tokens={'parent':{},'child':{}},parent_child_user_equal=None,
                errors=[],cleanup={'owned_handles_opened':0,'owned_handles_closed':0,'errors':[],
                                   'borrowed_owner_closed':False,'borrowed_job_closed':False},
                atomic_snapshot=False,effective_thread_tokens_observed=False,
                causal_access_check=False,full_P8_qualified=False,full_privacy_qualified=False)
    owned=[];phase='owner_identity'
    try:
        observer.validate_owner(owner)
        if observer.exit(owner.handle) is not None:
            raise RuntimeError('Owner is not live')
        root_identity=observer.identity(root_handle,root_pid,job_handle)
        _record(dict(root_identity,exit=None))
        if root_identity['pid']!=root_pid:
            raise RuntimeError('Borrowed root identity differs')
        result['owner_identity']=root_identity
        phase='child_open';child=observer.open(record['pid'])
        if not child:
            raise RuntimeError('Child query handle missing')
        owned.append(child)
        phase='child_identity';actual=observer.identity(child,record['pid'],owner.job.handle)
        if any(actual.get(key)!=record[key] for key in ('pid','creation_filetime','in_owned_job')) or _image(actual.get('image'))!=_image(record['image']) or actual.get('image_sha256','').lower()!=record['image_sha256'].lower():
            raise RuntimeError('Child identity differs from live tracker record')
        if observer.exit(child) is not None:
            raise RuntimeError('Child is not live')
        result['identity_validated']=True
        result['child_identity']=actual
        phase='duplicate_pipe';pipe=observer.duplicate(owner.handle,remote_pipe_handle)
        if not pipe:
            raise RuntimeError('Owned duplicate missing')
        owned.append(pipe)
        phase='pipe_identity';identity=observer.pipe_identity(pipe)
        if identity.get('file_type')!=3 or identity.get('server_pid')!=owner.pid:
            raise RuntimeError('Pipe server is not the live owner')
        result['pipe_identity']=identity;result['pipe_identity_validated']=True
        for name,information in (('base_security',7),('label_security',16)):
            try:
                result[name]=dict(known=True,value=observer.security(pipe,information,nonce))
            except Exception as error:
                result['errors'].append(_error(name,error))
        for role,process in (('parent',owner.handle),('child',child)):
            try:
                token=observer.open_token(process)
                if not token:
                    raise RuntimeError('Owned token handle missing')
                owned.append(token)
            except Exception as error:
                result['errors'].append(_error(role+'_open_token',error))
                result['tokens'][role]={'known':False}
                continue
            for name,information in TOKEN_CLASSES.items():
                try:
                    result['tokens'][role][name]=dict(known=True,value=observer.token_information(token,information,nonce))
                except Exception as error:
                    result['tokens'][role][name]=dict(known=False)
                    result['errors'].append(_error(role+'_'+name,error))
        users=[result['tokens'][role].get('user',{}) for role in ('parent','child')]
        if all(user.get('known') and isinstance(user.get('value',{}).get('sid_sha256'),str) for user in users):
            result['parent_child_user_equal']=users[0]['value']['sid_sha256']==users[1]['value']['sid_sha256']
        phase='post_snapshot_liveness'
        if owner.handle!=root_handle or not owner.job or owner.job.handle!=job_handle or owner.pid!=root_pid:
            raise RuntimeError('Borrowed owner handles or PID changed during snapshot')
        observer.validate_owner(owner)
        final_root=observer.identity(root_handle,root_pid,job_handle)
        if final_root != root_identity:
            raise RuntimeError('Root identity changed during snapshot')
        observer.in_job(child,owner.job.handle)
        if observer.exit(owner.handle) is not None or observer.exit(child) is not None:
            raise RuntimeError('A process exited during snapshot')
        result['live_before_and_after']=True
    except Exception as error:
        result['errors'].append(_error(phase,error))
    finally:
        result['cleanup']['owned_handles_opened']=len(owned)
        for handle in reversed(owned):
            try:
                observer.close(handle)
                result['cleanup']['owned_handles_closed']+=1
            except Exception as error:
                result['cleanup']['errors'].append(_error('close_owned_handle',error))
        result['cleanup']['complete']=not result['cleanup']['errors']
    result['snapshot_qualified']=bool(result['identity_validated'] and result['pipe_identity_validated']
                                    and result['base_security']['known'] and result.get('live_before_and_after')
                                    and result['cleanup']['complete'])
    return result
