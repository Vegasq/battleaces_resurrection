"""Native and live-server evidence for a ready human Custom lobby waiting >30s."""
import re
from server.community_protocol import START


def require(value,message):
    if not value:raise AssertionError(message)


def validate(host_log,samples,rosters,commands,worker_requests,profiles):
    host_log=host_log.replace('\r\n','\n').replace('\r','\n')
    waiting=re.findall(r'^\[(\d+)\] COMMUNITY OPEN HOLD waiting: lobby=([0-9a-f]{32}) members=1 phase=Open nativeIdle=1 minimumMs=31000 BA_RESURRECTION_CUSTOM_OPEN_HOLD_V2$',host_log,re.M)
    released=re.findall(r'^\[(\d+)\] COMMUNITY OPEN HOLD released: lobby=([0-9a-f]{32}) elapsedMs=(\d+) members=1 phase=Open nativeIdle=1 BA_RESURRECTION_CUSTOM_OPEN_HOLD_V2$',host_log,re.M)
    require(len(waiting)==len(released)==1,'one fully-created native lobby hold/release required')
    began,lobby=waiting[0];ended,room,elapsed=released[0]
    require(room==lobby and int(elapsed)>=31000 and int(ended)-int(began)>=30000,'native Custom lobby did not wait beyond30s')
    native_start=re.findall(r'^\[(\d+)\] COMMUNITY MATCH SMOKE host native Start returned pending; round=0 \(NOT manual UI input\)$',host_log,re.M)
    require(len(native_start)==1 and int(native_start[0])>=int(ended),'original native Start preceded the ready-lobby hold')
    require(len(profiles)==len(set(profiles))==2 and len(samples)>=2,'two authenticated humans and live waiting samples required')
    expected=set(profiles);times=[]
    for sample in samples:
        require(sample['lobby']==lobby and sample['phase']==1 and sample['epoch']==0 and not sample['room'] and
                sample['workers']==sample['public_entries']==sample['public_offers']==0 and
                sample['members']==[profiles[0]],'waiting Custom lobby started,filled or changed ownership')
        times.append(sample['perf_ns'])
    require(times==sorted(set(times)) and times[-1]-times[0]>=30_000_000_000,'live server observations do not span30seconds')
    starts=[row['probe_perf_ns'] for row in commands if row['kind']==START]
    require(len(starts)==2 and starts==sorted(starts) and starts[0]>times[-1],'Custom Start overlapped waiting observations')
    require(len(worker_requests)==2 and all(t>=starts[0] for t in worker_requests),'native worker requested before original human Start')
    require(len(rosters)==2 and len({row['match'] for row in rosters})==2,'two distinct human Custom matches required')
    for roster in rosters:
        players=roster['players']
        require(roster['mode']==1 and len(players)==2 and {p['slot'] for p in players}=={0,1} and
                {p['profile'] for p in players}==expected and all(p['ai_profile_id']==0 for p in players),
                'Custom match inserted a bot or changed its human participants')
    return dict(lobby=lobby,native_elapsed_ms=int(elapsed),native_observed_ms=int(ended)-int(began),
                server_sample_span_seconds=(times[-1]-times[0])/1e9,server_samples=len(samples),
                fully_created_open_lobby=True,waiting_human_members=1,empty_seat_remained_empty=True,host_profile=profiles[0],
                public_entries=0,public_offers=0,workers_during_hold=0,
                matches=[row['match'] for row in rosters],human_profiles=sorted(expected),all_ai_profiles_zero=True,
                original_start_after_hold=True)
