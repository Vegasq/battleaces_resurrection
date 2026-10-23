"""Validate opt-in unwind provenance and project unchanged legacy row data.

All operations, counters, sequence numbers and payload metadata remain present.
Projection removes only the separately validated observerUnwind annotation so
existing scope-specific validators can be reused. Neither view proves privacy.
"""
import re

BASE = {'schema','seq','runId','pid','tid','elapsedMs','kind','data'}
FIELDS = {'schema','depth','scopeId','started','completed','activeScopes','nestedPcFrames'}


def validate(rows, *, pid, run_id):
    def require(condition, message):
        if not condition:
            raise AssertionError(message)
    def integer(value, minimum=0):
        return type(value) is int and minimum <= value <= 2**53-1
    require(integer(pid,1) and pid < 2**32 and isinstance(run_id,str) and
            re.fullmatch('[0-9a-f]{32}',run_id), 'unwind identity required')
    require(isinstance(rows,list) and rows, 'unwind rows required')
    previous = dict(started=0,completed=0,nestedPcFrames=0)
    elapsed = -1; nested = []; projected = []
    for sequence, row in enumerate(rows,1):
        require(isinstance(row,dict) and set(row)==BASE|{'observerUnwind'}, 'unwind row envelope differs')
        require(type(row['schema']) is int and row['schema']==1 and type(row['seq']) is int and row['seq']==sequence and
                type(row['pid']) is int and row['pid']==pid and row['runId']==run_id and
                integer(row['tid'],1) and row['tid']<2**32 and integer(row['elapsedMs']) and row['elapsedMs']>=elapsed and
                isinstance(row['kind'],str) and isinstance(row['data'],dict), 'unwind row identity/order differs')
        elapsed=row['elapsedMs']; state=row['observerUnwind']
        require(isinstance(state,dict) and set(state)==FIELDS and all(integer(v) for v in state.values()), 'unwind fields/types differ')
        require(state['schema']==1 and state['depth'] in (0,1) and
                state['completed']<=state['started'] and state['activeScopes']==state['started']-state['completed'] and
                state['scopeId']<=state['started'] and (state['depth']==0)==(state['scopeId']==0) and
                (state['depth']==0 or state['activeScopes']>0), 'unwind scope inconsistent')
        require(all(state[key]>=value for key,value in previous.items()), 'unwind counters went backward')
        previous={key:state[key] for key in previous}
        if state['depth']:
            nested.append(dict(seq=sequence,kind=row['kind'],tid=row['tid'],scope_id=state['scopeId']))
        projected.append({key:row[key] for key in BASE})
    last=rows[-1]['observerUnwind']
    require(last['activeScopes']==0 and last['depth']==0, 'unwind scopes not drained at final observation')
    return dict(passed=True,rows=len(rows),unwinds_started=last['started'],unwinds_completed=last['completed'],
                nested_pc_frame_requests=last['nestedPcFrames'],rows_emitted_during_observer_unwind=nested,
                phase='emit',older_capture_attribution=False,unmarked_activity_attributed=False,
                full_privacy_qualified=False), projected
