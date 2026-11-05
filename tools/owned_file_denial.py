"""Diagnostic-only READ_DATA deny ACE on one owned regular file, then exact undo.

Never changes owner, group, SACL, token privileges, directories or shared files.
Retains READ_CONTROL/WRITE_DAC on the original non-delete-shared file handle.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[1]
EXTERNAL=Path.home()/'AppData/Local/BattleAcesDiagnostics/local'


def owned_file(path, folder):
    path,folder=Path(path).absolute(),Path(folder).absolute()
    roots=((ROOT/'local').resolve(),EXTERNAL.resolve())
    if not any(folder!=r and folder.is_relative_to(r) for r in roots) or path==folder or not path.is_relative_to(folder):
        raise ValueError('strict owned diagnostic file required')
    for p in (path,*path.parents):
        if p.exists() and getattr(p.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('reparse paths are not allowed')
        if p==folder:break
    if path.resolve()!=path or folder.resolve()!=folder or not path.is_file() or path.stat().st_nlink!=1:
        raise ValueError('one ordinary unlinked diagnostic file required')
    return path,folder


class OwnedFileReadDenial:
    def __init__(self,path,folder,*,receipt=None):
        if os.name!='nt':raise ValueError('Windows file access control required')
        self.path,self.folder=owned_file(path,folder)
        self.handle=None;self.changed=False;self.restored=False;self.probe_winerror=None
        self.receipt=Path(receipt).absolute() if receipt is not None else None
        if self.receipt and (self.receipt.parent!=self.folder or self.receipt.exists()):
            raise ValueError('fresh receipt beside owned file required')
        from server.credentials import _WindowsPrivacy
        self.api=_WindowsPrivacy();a,k=self.api.advapi,self.api.kernel
        a.GetSecurityInfo.argtypes=[w.HANDLE,c.c_int,w.DWORD,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p,c.POINTER(c.c_void_p)];a.GetSecurityInfo.restype=w.DWORD
        a.SetSecurityInfo.argtypes=[w.HANDLE,c.c_int,w.DWORD,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p];a.SetSecurityInfo.restype=w.DWORD
        a.SetFileSecurityW.argtypes=[w.LPCWSTR,w.DWORD,c.c_void_p];a.SetFileSecurityW.restype=w.BOOL
        a.GetSecurityDescriptorDacl.argtypes=[c.c_void_p,c.POINTER(w.BOOL),c.POINTER(c.c_void_p),c.POINTER(w.BOOL)];a.GetSecurityDescriptorDacl.restype=w.BOOL
        a.GetSecurityDescriptorControl.argtypes=[c.c_void_p,c.POINTER(w.WORD),c.POINTER(w.DWORD)];a.GetSecurityDescriptorControl.restype=w.BOOL
        k.GetFileInformationByHandle.argtypes=[w.HANDLE,c.c_void_p];k.GetFileInformationByHandle.restype=w.BOOL
        k.GetFinalPathNameByHandleW.argtypes=[w.HANDLE,w.LPWSTR,w.DWORD,w.DWORD];k.GetFinalPathNameByHandleW.restype=w.DWORD

    def snapshot(self):
        a,k=self.api.advapi,self.api.kernel
        sd=c.c_void_p();text=w.LPWSTR()
        code=a.GetSecurityInfo(self.handle,1,7,None,None,None,None,c.byref(sd))
        if code:raise c.WinError(code)
        try:
            present,defaulted,acl=w.BOOL(),w.BOOL(),c.c_void_p()
            if not a.GetSecurityDescriptorDacl(sd,c.byref(present),c.byref(acl),c.byref(defaulted)) or not present or not acl:
                raise ValueError('existing non-null DACL required')
            header=c.string_at(acl,8);size=struct.unpack_from('<H',header,2)[0]
            if not 8<=size<=60000:raise ValueError('bounded DACL required')
            control,revision=w.WORD(),w.DWORD()
            if not a.GetSecurityDescriptorControl(sd,c.byref(control),c.byref(revision)):
                raise c.WinError(c.get_last_error())
            if not a.ConvertSecurityDescriptorToStringSecurityDescriptorW(sd,1,7,c.byref(text),None):
                raise c.WinError(c.get_last_error())
            return dict(dacl_hex=c.string_at(acl,size).hex(),sddl=text.value,control=control.value)
        finally:
            if text:k.LocalFree(c.cast(text,c.c_void_p))
            k.LocalFree(sd)

    def set_dacl(self,raw):
        if not raw:raise ValueError('null/empty DACL forbidden')
        buf=c.create_string_buffer(raw)
        code=self.api.advapi.SetSecurityInfo(self.handle,1,4,None,None,buf,None)
        if code:raise c.WinError(code)

    def __enter__(self):
        a,k=self.api.advapi,self.api.kernel
        self.handle=k.CreateFileW(str(self.path),0x60000,3,None,3,0x200000,None)
        if self.handle==c.c_void_p(-1).value:
            self.handle=None;raise c.WinError(c.get_last_error())
        try:
            info=c.create_string_buffer(52);final=c.create_unicode_buffer(32768)
            if not k.GetFileInformationByHandle(self.handle,info):raise c.WinError(c.get_last_error())
            if struct.unpack_from('<I',info,0)[0]&0x410 or struct.unpack_from('<I',info,40)[0]!=1:
                raise ValueError('handle is not an ordinary single-link file')
            length=k.GetFinalPathNameByHandleW(self.handle,final,len(final),0)
            if not 0<length<len(final) or Path(final.value.removeprefix('\\\\?\\'))!=self.path:
                raise ValueError('opened file path differs')
            self.before=self.snapshot()
            if self.before['control'] not in (0x8004,0x8404):
                raise ValueError('diagnostic supports only unprotected DACL with optional auto-inherited bit')
            sd=c.c_void_p();deny=None
            try:
                if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:(D;;0x1;;;'+self.api.sid+')',1,c.byref(sd),None):
                    raise c.WinError(c.get_last_error())
                present,defaulted,acl=w.BOOL(),w.BOOL(),c.c_void_p()
                if not a.GetSecurityDescriptorDacl(sd,c.byref(present),c.byref(acl),c.byref(defaulted)):raise c.WinError(c.get_last_error())
                size=struct.unpack_from('<H',c.string_at(acl,8),2)[0]
                deny=c.string_at(acl,size)[8:]
            finally:
                if sd:k.LocalFree(sd)
            old=bytes.fromhex(self.before['dacl_hex']);rev,unused,size,count,reserved=struct.unpack('<BBHHH',old[:8])
            new=struct.pack('<BBHHH',rev,unused,size+len(deny),count+1,reserved)+deny+old[8:]
            if self.receipt:self.receipt.write_text(json.dumps(dict(path=str(self.path),before=self.before),indent=2)+'\n')
            self.set_dacl(new);self.changed=True
            self.during=self.snapshot()
            if bytes.fromhex(self.during['dacl_hex'])!=new:raise ValueError('deny DACL differs from declared insertion')
            probe=k.CreateFileW(str(self.path),0x80000000,7,None,3,0x80,None)
            self.probe_winerror=c.get_last_error()
            if probe!=c.c_void_p(-1).value:
                k.CloseHandle(probe);raise ValueError('read denial did not refuse GENERIC_READ')
            if self.probe_winerror!=5:raise ValueError('expected real Windows access denied5')
            return self
        except BaseException:
            self.close();raise

    def close(self):
        if self.handle is None:return
        try:
            if self.changed:
                # SetSecurityInfo can add SE_DACL_AUTO_INHERITED even when the
                # supplied ACE bytes are unchanged. The legacy file-specific
                # descriptor setter is deliberate here: restore the original
                # DACL including its inheritance control bits, not new policy.
                # The retained non-delete-shared handle pins this exact file.
                if self.before['control']&0x400:
                    self.set_dacl(bytes.fromhex(self.before['dacl_hex']))
                else:
                    sd=c.c_void_p()
                    try:
                        if not self.api.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(self.before['sddl'],1,c.byref(sd),None):
                            raise c.WinError(c.get_last_error())
                        if not self.api.advapi.SetFileSecurityW(str(self.path),4,sd):raise c.WinError(c.get_last_error())
                    finally:
                        if sd:self.api.kernel.LocalFree(sd)
                self.after=self.snapshot()
                if self.after!=self.before:raise ValueError('original owner/group/DACL/control not restored exactly')
                self.changed=False;self.restored=True
        finally:
            self.api.kernel.CloseHandle(self.handle);self.handle=None

    def __exit__(self,*unused):self.close()

    def evidence(self):
        digest=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()
        return dict(probe_winerror=self.probe_winerror,denied_mask=1,scope='current-user FILE_READ_DATA on one file',
                    before_descriptor_sha256=digest(self.before),during_descriptor_sha256=digest(self.during),
                    restored=self.restored,after_descriptor_sha256=digest(self.after) if self.restored else None,
                    handle_closed=self.handle is None)
