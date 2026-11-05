"""Build an opt-in endpoint-only CPython socket audit prelude for owned drivers."""
from __future__ import annotations

from pathlib import Path


def source(path: Path, *, positive_probe: bool = False) -> str:
    assert path.name == 'socket-audit.jsonl' and path.parent.name in (
        'server', 'client-0', 'client-1', 'client-2', 'client-3', 'worker-0', 'worker-1')
    return '''import atexit as _ba_atexit,json as _ba_json,os as _ba_os,sys as _ba_sys,time as _ba_time
_ba_audit_path=''' + repr(str(path.resolve())) + '''
_ba_audit_fd=_ba_os.open(_ba_audit_path,_ba_os.O_WRONLY|_ba_os.O_CREAT|_ba_os.O_EXCL,0o600)
_ba_audit_count=0
_ba_audit_overflow=False
_ba_audit_names=frozenset(('socket.bind','socket.connect','socket.sendto','socket.sendmsg',
    'socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr','socket.getnameinfo'))
def _ba_safe(value):
    if value is None or type(value) in (str,int):return value
    if type(value) in (tuple,list):return [_ba_safe(item) for item in value[:5]]
    return '<other>'
def _ba_record(event,address):
    global _ba_audit_count,_ba_audit_overflow
    if _ba_audit_count>=4096:
        if not _ba_audit_overflow:
            _ba_audit_overflow=True
            _ba_os.write(_ba_audit_fd,(_ba_json.dumps(dict(event='overflow',pid=_ba_os.getpid()))+'\\n').encode())
        return
    _ba_audit_count+=1
    _ba_os.write(_ba_audit_fd,(_ba_json.dumps(dict(event=event,address=_ba_safe(address),
        pid=_ba_os.getpid(),tick_ns=_ba_time.monotonic_ns()),separators=(',',':'))+'\\n').encode())
def _ba_hook(event,args):
    if event in _ba_audit_names:
        _ba_record(event,args[0] if event.startswith('socket.get') else args[1])
_ba_sys.addaudithook(_ba_hook)
_ba_record('observer-ready',None)
def _ba_finish():
    _ba_record('observer-exit',None)
    _ba_os.close(_ba_audit_fd)
_ba_atexit.register(_ba_finish)
''' + ("import socket as _ba_socket\n_ba_socket.getaddrinfo('localhost',0)\n" if positive_probe else '')
