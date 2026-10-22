"""Strict decoder for live process-current-directory entry metadata."""
from pathlib import PureWindowsPath
import re
from tools.attribution_path_metadata import unresolved

BASE={'api','operation','phase','rootHandle','relativePath','frames'}


def resolved(data,*,peb_address):
    if not isinstance(data,dict) or set(data)!=BASE|{'rootPath','pebAddress','parametersAddress','resolution'}:
        raise ValueError('Resolved directory metadata keys differ')
    unresolved({key:data[key] for key in BASE})
    if data['resolution']!='process-current-directory' or data['pebAddress']!=peb_address:
        raise ValueError('Directory provenance differs')
    for address in (data['pebAddress'],data['parametersAddress']):
        if not isinstance(address,str) or not re.fullmatch('0x[0-9a-f]{1,16}',address) or int(address,16)==0:
            raise ValueError('Directory metadata address invalid')
    root=data['rootPath']
    if not isinstance(root,str) or not 1<=len(root)<=16384 or not PureWindowsPath(root).is_absolute() or '\0' in root:
        raise ValueError('Absolute bounded directory required')
    # Dot-segment normalization is outside the current selected-entry proof.
    if any(part in ('.','..') for part in data['relativePath'].replace('/','\\').split('\\')):
        raise ValueError('Dot-segment path needs a separate normalization contract')
    return dict(data)
