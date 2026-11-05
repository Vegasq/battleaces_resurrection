"""Bounded graphical rematch evidence; no game injection or process discovery."""
import re
import math

from tools.packaged_network_evidence import require

ROUNDS=21
ROLES=('server','launcher0','game0','launcher1','game1')
LIMITS={role:dict(handles=64 if role.startswith('game') else 16,
                  private_bytes=(256 if role.startswith('game') else 64)*1024*1024)
        for role in ROLES}


def idle_round(log):
    rows=re.findall(r'COMMUNITY SOAK idle: round=(\d+) lobby=([0-9a-f]{32}) nativeIdle=1 BA_RESURRECTION_CUSTOM_SOAK_V1',log)
    require([int(row[0]) for row in rows]==list(range(1,len(rows)+1)) and len(rows)<=ROUNDS,
            'graphical soak idle sequence is not contiguous')
    require(len({row[1] for row in rows})<=1,'graphical soak changed its lobby')
    return len(rows)


def assess(boundaries,trend):
    require([row['round'] for row in boundaries]==list(range(1,ROUNDS+1)),
            'graphical soak needs initial match and twenty rematches')
    require(bool(trend),'graphical soak lacks intermediate resource samples')
    baseline,final=boundaries[2],boundaries[-1]
    for row in boundaries+trend:
        require(set(row['processes'])==set(ROLES),'resource sample omitted an owned process')
        for role,sample in row['processes'].items():
            first=baseline['processes'][role]
            require(sample['pid']==first['pid'] and sample['created_filetime']==first['created_filetime'],
                    'owned process identity changed during graphical soak')
            require(all(type(sample[key]) is int and sample[key]>0 for key in ('pid','created_filetime','private_bytes','working_set_bytes','handles')),
                    'resource measurement is missing or invalid')
    result={}
    for role in ROLES:
        before,after=baseline['processes'][role],final['processes'][role]
        growth={key:after[key]-before[key] for key in LIMITS[role]}
        result[role]=dict(growth=growth,limits=LIMITS[role],
            passed=all(growth[key]<=bound for key,bound in LIMITS[role].items()),
            peak={key:max(row['processes'][role][key] for row in boundaries+trend)
                  for key in ('private_bytes','working_set_bytes','handles')})
    return dict(passed=all(row['passed'] for row in result.values()),baseline_round=3,
                final_round=ROUNDS,processes=result,trend_samples=len(trend))


def assess_cadence(events, matches):
    """Fixed21-match target using raw timestamps; resource/lifetime are separate."""
    require(len(matches)==ROUNDS and len(set(matches))==ROUNDS,'cadence needs21unique matches')
    grouped={match:[] for match in matches}
    for event in events:
        if event['event']=='frame_queued':
            require(event.get('match') in grouped,'unexpected cadence match')
            grouped[event['match']].append(event)
    result={}
    for match,rows in grouped.items():
        require([row['frame'] for row in rows]==list(range(1220)),'cadence needs every original frame in order')
        stamps=[row['perf_counter_ns'] for row in rows]
        require(all(type(stamp) is int and stamp>0 for stamp in stamps),'invalid cadence timestamp')
        intervals=[b-a for a,b in zip(stamps,stamps[1:])]
        require(all(value>0 for value in intervals),'non-increasing cadence timestamps')
        work=[row['worker_ms'] for row in rows]
        require(all(type(value) in (int,float) and math.isfinite(value) and value>=0 for value in work),
                'invalid worker timing')
        #19.5Hz=39/2. Integer comparison avoids rounding away a failing boundary.
        elapsed=stamps[-1]-stamps[0]
        late=sum(value>50 for value in work)
        checks=dict(cadence=2*len(intervals)*1_000_000_000>=39*elapsed,
                    publication_gap=max(intervals)<=1_000_000_000,
                    worker_budget=100*late<=len(work))
        result[match]=dict(passed=all(checks.values()),checks=checks,frames=len(rows),
                           effective_hz=len(intervals)*1_000_000_000/elapsed,
                           maximum_gap_ms=max(intervals)/1_000_000,worker_calls_over50ms=late)
    return dict(passed=all(row['passed'] for row in result.values()),
                scope='21 packaged graphical matches; per-match cadence,publication gap and worker await budget',
                limits=dict(minimum_hz=19.5,maximum_gap_ms=1000,worker_over50ms_percent=1),matches=result)
