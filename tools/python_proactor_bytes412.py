"""Build an opt-in byte-count-only Windows asyncio Proactor diagnostic."""
from __future__ import annotations

from pathlib import Path


def source(path: Path) -> str:
    assert path.name == 'byte-audit.jsonl'
    assert path.parent.name in ('server', 'client-0', 'client-1', 'client-2',
                                'client-3', 'worker-0', 'worker-1',
                                'privacy412-proactor-control01')
    return '''import atexit as _ba_bytes_atexit,json as _ba_bytes_json,os as _ba_bytes_os
import asyncio.windows_events as _ba_bytes_windows
_ba_bytes_path=''' + repr(str(path.resolve())) + '''
_ba_bytes_fd=_ba_bytes_os.open(_ba_bytes_path,_ba_bytes_os.O_WRONLY|_ba_bytes_os.O_CREAT|_ba_bytes_os.O_EXCL,0o600)
_ba_bytes_stats={'send':0,'recv':0,'sendto':0,'recvfrom':0,'recv_into':0,
                 'recvfrom_into':0,'sendfile':0,'requested_send_bytes':0,
                 'completed_send_bytes':0,'completed_recv_bytes':0,
                 'failed':0,'cancelled':0,'unclassified':0}
_ba_bytes_peers={}
_ba_bytes_errors=[]
_ba_bytes_overflow=False
def _ba_bytes_emit(kind,data):
    row=dict(event=kind,pid=_ba_bytes_os.getpid(),data=data)
    _ba_bytes_os.write(_ba_bytes_fd,(_ba_bytes_json.dumps(row,separators=(',',':'))+'\\n').encode('utf-8'))
def _ba_bytes_peer(sock):
    global _ba_bytes_overflow
    try:
        handle=str(sock.fileno())
        peer=sock.getpeername()
        if not isinstance(peer,tuple) or len(peer)<2 or not isinstance(peer[0],str) or type(peer[1]) is not int:
            raise ValueError('unsupported peer endpoint')
        key=handle+'|'+peer[0]+'|'+str(peer[1])
        if key not in _ba_bytes_peers:
            if len(_ba_bytes_peers)>=128:
                _ba_bytes_overflow=True;return None
            _ba_bytes_peers[key]=dict(handle=handle,address=peer[0],port=peer[1],
                send_calls=0,recv_calls=0,send_bytes=0,recv_bytes=0)
        return _ba_bytes_peers[key]
    except (AttributeError,OSError,TypeError,ValueError):
        _ba_bytes_stats['unclassified']+=1
        return None
def _ba_bytes_wrap(name):
    original=getattr(_ba_bytes_windows.IocpProactor,name)
    def observe(self,sock,*args,**kwargs):
        _ba_bytes_stats[name]+=1
        peer=_ba_bytes_peer(sock)
        sending=name in ('send','sendto','sendfile')
        if peer is not None:peer['send_calls' if sending else 'recv_calls']+=1
        if name in ('send','sendto') and args:
            _ba_bytes_stats['requested_send_bytes']+=len(args[0])
        result=original(self,sock,*args,**kwargs)
        if hasattr(result,'add_done_callback'):
            def complete(future):
                try:
                    if future.cancelled():
                        _ba_bytes_stats['cancelled']+=1;return
                    value=future.result()
                    size=(value if type(value) is int else len(value) if isinstance(value,(bytes,bytearray)) else None)
                    if size is None:
                        _ba_bytes_stats['unclassified']+=1;return
                    key='completed_send_bytes' if sending else 'completed_recv_bytes'
                    _ba_bytes_stats[key]+=size
                    if peer is not None:peer['send_bytes' if sending else 'recv_bytes']+=size
                except (OSError,RuntimeError,TypeError,ValueError):
                    _ba_bytes_stats['failed']+=1
            result.add_done_callback(complete)
        else:
            _ba_bytes_stats['unclassified']+=1
        return result
    setattr(_ba_bytes_windows.IocpProactor,name,observe)
for _ba_bytes_name in ('send','recv','sendto','recvfrom','recv_into','recvfrom_into','sendfile'):
    _ba_bytes_wrap(_ba_bytes_name)
_ba_bytes_emit('observer-ready',dict(methods=7))
def _ba_bytes_finish():
    _ba_bytes_emit('observer-exit',dict(stats=_ba_bytes_stats,peers=list(_ba_bytes_peers.values()),
                                       errors=_ba_bytes_errors,overflow=_ba_bytes_overflow))
    _ba_bytes_os.close(_ba_bytes_fd)
_ba_bytes_atexit.register(_ba_bytes_finish)
'''
