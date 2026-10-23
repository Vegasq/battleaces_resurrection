"""Validate native symbol scope metadata without erasing underlying observations."""
import re
from pathlib import PureWindowsPath
from tools.attribution_unwind_metadata import BASE
from tools.frida_attribution_symbols import APIS,LOAD_APIS


def validate(rows,*,pid,run_id,include_module_load=False):
    if type(include_module_load) is not bool:
        raise TypeError('include_module_load must be bool')
    apis=LOAD_APIS if include_module_load else APIS
    def require(ok,message):
        if not ok:raise AssertionError(message)
    def integer(x,minimum=0):return type(x) is int and minimum<=x<=2**53-1
    def caller(value):
        if value==dict(module=None,rva=None):return True
        return isinstance(value,dict) and set(value)=={'module','rva'} and isinstance(value['module'],str) and \
            1<=len(value['module'])<=256 and value['module']==value['module'].lower() and not any(c in value['module'] for c in ('/','\\','\0')) and \
            isinstance(value['rva'],str) and re.fullmatch('0x[0-9a-f]{1,16}',value['rva'])
    def call(value,history=False):
        return isinstance(value,dict) and set(value)=={'id','moduleId','api','caller','observerUnwindDepth'}|({'tid'} if history else set()) and \
            integer(value['id'],1) and integer(value['moduleId'],1) and value['api'] in apis and caller(value['caller']) and \
            type(value['observerUnwindDepth']) is int and value['observerUnwindDepth'] in (0,1) and (not history or integer(value['tid'],1))
    require(integer(pid,1) and isinstance(run_id,str) and re.fullmatch('[0-9a-f]{32}',run_id),'symbol identity required')
    require(isinstance(rows,list) and rows,'symbol rows required')
    previous_entered=previous_returned=0;last_elapsed=-1;modules={};projected=[];scoped=[]
    for index,row in enumerate(rows,1):
        require(isinstance(row,dict) and set(row)==BASE|{'observerUnwind','nativeSymbols'},'symbol row envelope differs')
        require(type(row['schema']) is int and row['schema']==1 and type(row['seq']) is int and row['seq']==index and
                type(row['pid']) is int and row['pid']==pid and row['runId']==run_id and integer(row['tid'],1) and
                integer(row['elapsedMs']) and row['elapsedMs']>=last_elapsed,'symbol row identity/order differs')
        last_elapsed=row['elapsedMs'];state=row['nativeSymbols']
        require(isinstance(state,dict) and set(state)=={'schema','entered','returned','active','modules','errors'} and
                type(state['schema']) is int and state['schema']==1 and state['errors']==[],'symbol schema/error differs')
        entered,returned=state['entered'],state['returned']
        require(integer(entered) and integer(returned) and previous_entered<=entered and previous_returned<=returned<=entered,'symbol counters invalid/backward')
        previous_entered,previous_returned=entered,returned
        active=state['active'];require(isinstance(active,list) and len(active)<=16 and all(call(c) and c['id']<=entered for c in active) and
            len({c['id'] for c in active})==len(active) and [c['id'] for c in active]==sorted(c['id'] for c in active) and
            len(active)<=entered-returned,'symbol active scopes differ')
        if state['modules'] is not None:
            require(isinstance(state['modules'],list) and len(state['modules'])<=16,'symbol module budget differs')
            current={}
            for m in state['modules']:
                require(isinstance(m,dict) and set(m)=={'id','name','path','base','size','exports','counts','history'} and integer(m['id'],1) and
                    m['name'] in ('dbghelp.dll','dbghelp-x86_64.dll') and isinstance(m['path'],str) and 1<=len(m['path'])<=32768 and
                    PureWindowsPath(m['path']).is_absolute() and '\0' not in m['path'] and
                    isinstance(m['base'],str) and re.fullmatch('0x[0-9a-f]{1,16}',m['base']) and integer(m['size'],16) and m['size']<=2**32,'symbol module identity differs')
                require(m['id'] not in current and isinstance(m['exports'],list) and len(m['exports'])<=len(apis),'symbol exports differ')
                names=[]
                for e in m['exports']:
                    require(isinstance(e,dict) and set(e) in ({'name','rva','sha256'},{'name','rva','sha256','aliasOf'}) and e['name'] in apis and
                        integer(e['rva']) and e['rva']+16<=m['size'] and isinstance(e['sha256'],str) and re.fullmatch('[0-9a-f]{64}',e['sha256']),'symbol export binding differs')
                    if 'aliasOf' in e:require(isinstance(e['aliasOf'],str) and re.fullmatch('[1-9][0-9]*:(?:'+('|'.join(apis))+')',e['aliasOf']),'symbol alias differs')
                    names.append(e['name'])
                require(len(names)==len(set(names)) and isinstance(m['counts'],dict) and set(m['counts'])==set(names) and
                    all(integer(v) for v in m['counts'].values()),'symbol counts differ')
                require(isinstance(m['history'],list) and len(m['history'])<=8*len(apis) and
                    all(call(c,True) and c['moduleId']==m['id'] and c['id']<=entered for c in m['history']) and
                    len({c['id'] for c in m['history']})==len(m['history']),'symbol history differs')
                for name,count in m['counts'].items():
                    history=[c for c in m['history'] if c['api']==name]
                    require(len(history)==min(count,8),'symbol bounded history/count mismatch')
                old=modules.get(m['id'])
                if old:
                    require(all(m[k]==old[k] for k in ('id','name','path','base','size','exports')) and
                        all(m['counts'][name]>=count for name,count in old['counts'].items()) and m['history'][:len(old['history'])]==old['history'],'symbol module/history changed')
                current[m['id']]=m
            require(set(modules)<=set(current),'symbol module disappeared');modules=current
        if active:scoped.append(dict(seq=index,kind=row['kind'],tid=row['tid'],active=active))
        projected.append({k:v for k,v in row.items() if k!='nativeSymbols'})
    require(rows[-1]['nativeSymbols']['modules'] is not None and previous_entered==previous_returned and not rows[-1]['nativeSymbols']['active'],'symbol final scopes undrained')
    require(sum(sum(m['counts'].values()) for m in modules.values())==previous_entered,'symbol final module totals differ')
    require(all(c['moduleId'] in modules and c['api'] in modules[c['moduleId']]['counts'] for r in scoped for c in r['active']),'symbol scope module unbound')
    return dict(passed=True,entries=previous_entered,returns=previous_returned,modules=list(modules.values()),
                rows_emitted_in_native_symbol_scope=scoped,phase='emit',full_privacy_qualified=False),projected
