"""Owned authored long-name fixtures for ORIGINAL native replay retention.

Never imports the game or edits shared settings. Fixtures deliberately are not
valid replay messages: native retention enumerates names/creation times only.
"""
import ctypes
import hashlib
import os
from pathlib import Path


def require(value,reason):
    if not value:raise AssertionError(reason)


def api_path(path):
    path=Path(path).absolute()
    return Path('\\\\?\\'+str(path)) if os.name=='nt' else path


def payload(index):return ('authored retention fixture '+str(index)+'\n').encode('ascii')


def filename(index):return 'authored-retention-'+str(index).zfill(3)+'-'+'x'*100+'.rep'


def creation_time(path,index):
    """Use unique Windows creation times, the original ascending retention key."""
    require(os.name=='nt','native retention fixtures require Windows')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.SetFileTime.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.CreateFileW(str(api_path(path)),0x100,1,None,3,0x00200000,None)
    require(handle not in (None,ctypes.c_void_p(-1).value),'cannot open owned retention creation-time fixture')
    # 2020-01-01 UTC + distinct minutes, away from daylight-saving transitions.
    ticks=ctypes.c_ulonglong(132223104000000000+index*600000000)
    try:require(kernel.SetFileTime(handle,ctypes.byref(ticks),None,ctypes.byref(ticks)),'cannot set owned fixture creation time')
    finally:kernel.CloseHandle(handle)


def prepare(folder,count,owned_root):
    folder,owned_root=Path(folder).absolute(),Path(owned_root).resolve()
    require(count in (100,101),'retention boundary must be100 or101')
    require(folder.resolve()==folder and folder.is_relative_to(owned_root) and
            folder.name=='AutoSaveReplays' and folder.parent.name.startswith('nativestest_packaged_'),
            'retention fixtures require a fresh owned packaged profile')
    require(not folder.exists(),'refuse an existing retention fixture directory')
    folder.mkdir(parents=True,exist_ok=False)
    for index in range(count):
        path=folder/filename(index)
        require(len(str(path))>260 and len(path.name)<255,'fixture must exercise long full paths with supported components')
        with api_path(path).open('xb') as stream:stream.write(payload(index))
        creation_time(path,index)
    marker=folder/'unrelated.txt';marker.write_bytes(b'authored non-replay marker\n')
    return dict(count=count,creation_time_key='original ascending CreationTime',
                fixture_leaf_characters=len(filename(0)),full_path_characters=len(str(folder/filename(0))),
                unrelated_sha256=hashlib.sha256(marker.read_bytes()).hexdigest())


def verify(folder,fixture):
    folder=Path(folder)
    expected_count=fixture['count'];deleted_count=expected_count-99
    paths={p.name:p for p in folder.iterdir()}
    expected={filename(index) for index in range(deleted_count,expected_count)}
    observed={name for name in paths if name.startswith('authored-retention-')}
    require(observed==expected,'original retention removed wrong creation-time fixtures')
    for index in range(deleted_count,expected_count):
        require(api_path(paths[filename(index)]).read_bytes()==payload(index),'retained fixture bytes changed')
    require(hashlib.sha256(paths['unrelated.txt'].read_bytes()).hexdigest()==fixture['unrelated_sha256'],
            'original retention changed unrelated file')
    native=[p for name,p in paths.items() if name not in expected and name!='unrelated.txt']
    require(len(native)==1 and native[0].suffix=='.rep','expected exactly one new original replay after retention')
    require(len(paths)==101,'original retention did not leave100 replays plus unrelated marker')
    return native[0],dict(original_retention=True,initial_replays=expected_count,deleted_oldest=deleted_count,
                          retained_fixture_replays=99,total_replays=100,unrelated_file_unchanged=True)
