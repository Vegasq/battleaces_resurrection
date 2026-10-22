"""Strict entry-only unresolved-file metadata decoder;never classify absent I/O."""
import re


def unresolved(data):
    if not isinstance(data,dict) or set(data)!={'api','operation','phase','rootHandle','relativePath','frames'}:
        raise ValueError('Unresolved path metadata keys differ')
    operation=data['operation']
    if operation not in ('NtCreateFile','NtOpenFile','NtDeleteFile') or data['api']!='ntdll.dll:'+operation or data['phase']!='entry':
        raise ValueError('Unknown unresolved entry ABI')
    root=data['rootHandle'];name=data['relativePath'];frames=data['frames']
    if not isinstance(root,str) or not re.fullmatch('0x[0-9a-f]{1,16}',root) or int(root,16)==0:
        raise ValueError('Invalid unresolved root handle')
    if not isinstance(name,str) or not 1<=len(name)<=4096 or name.startswith(('\\','/')) or '\0' in name:
        raise ValueError('Invalid bounded relative file name')
    if not isinstance(frames,list) or not 1<=len(frames)<=8:raise ValueError('Missing bounded caller frames')
    for frame in frames:
        if not isinstance(frame,dict) or set(frame)!={'module','rva'}:raise ValueError('Caller metadata keys differ')
        module,rva=frame['module'],frame['rva']
        if module is None and rva is None:continue
        if not isinstance(module,str) or not 1<=len(module)<=256 or module!=module.lower() or any(c in module for c in ('/','\\','\0')) or \
                not isinstance(rva,str) or not re.fullmatch('0x[0-9a-f]{1,16}',rva):
            raise ValueError('Invalid caller module/offset')
    return dict(data)
