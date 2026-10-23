"""Validate code-bound per-thread Unity log extents; preserve every underlying row."""
import re
from pathlib import PureWindowsPath
from tools.frida_unity_log_scope import check_entry
from tools.attribution_unwind_metadata import BASE


def validate(rows,*,pid,run_id,entry):
    check_entry(entry)
    def require(ok,message):
        if not ok:raise AssertionError(message)
    def number(x,minimum=0):return type(x) is int and minimum<=x<=2**53-1
    def call(x,history=False):
        if not isinstance(x,dict) or set(x)!={'id','caller'}|({'tid'} if history else set()) or not number(x['id'],1):return False
        if history and not number(x['tid'],1):return False
        c=x['caller']
        return isinstance(c,dict) and set(c)=={'module','rva'} and (c==dict(module=None,rva=None) or
            isinstance(c['module'],str) and 1<=len(c['module'])<=256 and c['module']==c['module'].lower() and
            not any(s in c['module'] for s in ('/','\\','\0')) and isinstance(c['rva'],str) and bool(re.fullmatch('0x[0-9a-f]{1,16}',c['rva'])))
    require(number(pid,1) and isinstance(run_id,str) and re.fullmatch('[0-9a-f]{32}',run_id),'Unity log identity required')
    require(isinstance(rows,list) and rows,'Unity log rows required')
    entered=returned=0;module=None;history=[];elapsed=-1;projected=[];scoped=[]
    for index,row in enumerate(rows,1):
        require(isinstance(row,dict) and set(row)==BASE|{'observerUnwind','nativeSymbols','unityLogScope'},'Unity log row envelope differs')
        require(type(row['schema']) is int and row['schema']==1 and type(row['seq']) is int and row['seq']==index and
            type(row['pid']) is int and row['pid']==pid and row['runId']==run_id and number(row['tid'],1) and
            number(row['elapsedMs']) and row['elapsedMs']>=elapsed,'Unity log row identity/order differs')
        elapsed=row['elapsedMs'];s=row['unityLogScope']
        require(isinstance(s,dict) and set(s)=={'schema','entered','returned','module','active','history','errors'} and
            type(s['schema']) is int and s['schema']==1 and s['errors']==[],'Unity log state/error differs')
        require(number(s['entered']) and number(s['returned']) and entered<=s['entered'] and returned<=s['returned']<=s['entered'],'Unity log counters differ')
        entered,returned=s['entered'],s['returned']
        require(isinstance(s['history'],list) and len(s['history'])==min(entered,8) and s['history'][:len(history)]==history and
            all(call(c,True) and c['id']==i for i,c in enumerate(s['history'],1)),'Unity log bounded history differs')
        history=s['history'];m=s['module']
        if m is not None:
            require(isinstance(m,dict) and set(m)=={'name','path','base','size','rva','sha256'} and m['name']=='unityplayer.dll' and
                isinstance(m['path'],str) and PureWindowsPath(m['path'])==PureWindowsPath(entry['module']) and
                m['rva']==entry['rva'] and type(m['rva']) is int and m['sha256']==entry['sha256'] and
                isinstance(m['base'],str) and re.fullmatch('0x[0-9a-f]{1,16}',m['base']) and number(m['size'],16) and m['size']<=2**32 and
                m['rva']+16<=m['size'],'Unity log loaded code binding differs')
            require(module is None or module==m,'Unity log module changed');module=m
        else:require(module is None and entered==0,'Unity log module disappeared/unbound calls')
        active=s['active']
        require(isinstance(active,list) and len(active)<=min(16,entered-returned) and
            all(call(c) and c['id']<=entered for c in active) and
            [c['id'] for c in active]==sorted({c['id'] for c in active}),'Unity log active scopes differ')
        for c in active:
            if c['id']<=len(history):require(dict(tid=row['tid'],**c)==history[c['id']-1],'Unity log scope/history caller differs')
        if active:scoped.append(dict(seq=index,kind=row['kind'],tid=row['tid'],active=active))
        projected.append({k:v for k,v in row.items() if k!='unityLogScope'})
    require(module is not None and entered==returned and not rows[-1]['unityLogScope']['active'],'Unity log final scope undrained/uninstalled')
    return dict(passed=True,entries=entered,returns=returned,module=module,history=history,
        rows_emitted_in_log_scope=scoped,phase='emit',arguments_or_log_text_read=False,full_privacy_qualified=False),projected
