"""Closed-log main-thread visual ownership retirement proof; no engine calls."""
from __future__ import annotations

import json
import re


PREFIX = 'VISUAL CORRECTION LIFETIME '
FIELDS = {'schema','event','world','match','frame','reason','trigger','sampled_us','thread','owner_thread',
    'entries_before','pulses_before','roots_before','entries_after','pulses_after','roots_after',
    'movement_world','movement_match','worker_world','worker_match','prepared','pacing_started','failed',
    'visual_failed','end_sent','drained','match_ended','abort_pending','connected'}
FLAGS = {'prepared','pacing_started','failed','visual_failed','end_sent','drained','match_ended','abort_pending','connected'}
REASONS = {'keep','drained','failed','aborted','disconnected','movement_inactive','movement_changed','worker_retired','worker_changed'}
TRIGGERS = {'frontend','drain_complete','publication_inactive','new_world','join_inactive','unpublished_frame'}
NORMAL_TRIGGERS = {'frontend','drain_complete','publication_inactive','join_inactive'}


def require(value, reason):
    if not value: raise AssertionError('prediction visual lifetime: '+reason)


def integer(value, low=0, high=2**64-1):
    return type(value) is int and low <= value <= high


def reason(row):
    # Independent scalar specification: END/matchEnded alone NEVER clears.
    if row['visual_failed'] or row['failed']: return 'failed'
    if row['drained']: return 'drained'
    if row['abort_pending']: return 'aborted'
    if not row['connected']: return 'disconnected'
    if not row['prepared'] or not row['pacing_started']: return 'movement_inactive'
    if row['movement_world'] != row['world'] or row['movement_match'] != row['match']: return 'movement_changed'
    if not row['worker_world'] or not row['worker_match']: return 'worker_retired'
    if row['worker_world'] != row['world'] or row['worker_match'] != row['match']: return 'worker_changed'
    return 'keep'


def rows(log):
    require(type(log) is str and len(log.encode('utf-8')) <= 64*1024*1024, 'bounded closed log required')
    def unique(pairs):
        result = {}
        for key,value in pairs:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    def constant(value): raise AssertionError('prediction visual lifetime: invalid JSON number '+value)
    result = []; previous = -1
    for index,line in enumerate(log.splitlines()):
        if PREFIX not in line: continue
        raw = line.split(PREFIX,1)[1]; require(len(raw.encode('utf-8')) <= 4096, 'retirement row exceeds bound')
        row = json.loads(raw,object_pairs_hook=unique,parse_constant=constant)
        require(type(row) is dict and set(row) == FIELDS and type(row['schema']) is int and row['schema'] == 1 and
                row['event'] == 'retired', 'retirement schema differs')
        require(integer(row['world'],1) and type(row['match']) is str and re.fullmatch('[a-f0-9]{32}',row['match']) and
                integer(row['frame'],-1,0x7fffffff) and integer(row['sampled_us'],1) and
                row['sampled_us'] > previous and row['reason'] in REASONS and row['trigger'] in TRIGGERS,
                'retirement identity/frame/clock/reason differs')
        require(all(type(row[k]) is bool for k in FLAGS) and
                all(integer(row[k],1,0xffffffff) for k in ('thread','owner_thread')) and
                row['thread'] == row['owner_thread'], 'retirement is not on retained Unity main thread')
        for prefix in ('movement','worker'):
            require(integer(row[prefix+'_world']) and type(row[prefix+'_match']) is str and
                    (row[prefix+'_match'] == '' or re.fullmatch('[a-f0-9]{32}',row[prefix+'_match'])),
                    'observed lifetime key schema differs')
        require(all(integer(row[k],0,2048) for k in ('entries_before','entries_after')) and
                all(integer(row[k],0,32768) for k in ('pulses_before','pulses_after')) and
                all(integer(row[k],0,4099) for k in ('roots_before','roots_after')) and
                row['pulses_before'] <= 16*row['entries_before'], 'retained count budget differs')
        require(row['entries_after'] == row['pulses_after'] == row['roots_after'] == 0,
                'visual roots/entries/pulses survived retirement')
        require(row['reason'] == reason(row) and row['reason'] != 'keep', 'active drain was prematurely cleared or reason is false')
        row['_line'] = index; result.append(row); previous = row['sampled_us']
        require(len(result) <= 64, 'per-process retirement count exceeds producer bound')
    return result


def _events(log):
    starts = []; drains = []
    for index,line in enumerate(log.splitlines()):
        if 'Movement pacing START:' in line:
            found = re.search(r'Movement pacing START: match=([a-f0-9]{32}) world=([0-9]+)(?:\s|$)',line)
            require(found is not None, 'malformed actual movement world START')
            match,world = found.groups(); require(integer(int(world),1), 'invalid movement world')
            starts.append(dict(match=match,world=int(world),line=index))
        if 'Movement terminal drain complete:' in line:
            found = re.search(r'Movement terminal drain complete: match=([a-f0-9]{32}) confirmed=([0-9]+) '
                r'physical=([0-9]+) presented=([0-9]+) target=([0-9]+)(?:\s|$)',line)
            require(found is not None, 'malformed actual terminal drain completion')
            match,*counts = found.groups(); confirmed,physical,presented,target = map(int,counts)
            require(all(integer(n,0,0x7fffffff) for n in (confirmed,physical,presented,target)) and
                    min(physical,presented) >= target and confirmed <= physical, 'incomplete actual native drain')
            drains.append(dict(match=match,confirmed=confirmed,physical=physical,presented=presented,target=target,line=index))
    return starts,drains


def evaluate(logs, matches, *, visual_records=(), pids=None):
    require(type(logs) is list and len(logs) == 2 and type(matches) is list and len(matches) == 2 and
            len(set(matches)) == 2 and all(type(m) is str and re.fullmatch('[a-f0-9]{32}',m) for m in matches),
            'both clients and two authority-bound matches required')
    require(type(pids) is list and len(pids) == 2 and len(set(pids)) == 2 and
            all(integer(pid,1,0xffffffff) for pid in pids), 'two actual capture process IDs required')
    clients = []
    for client,log in enumerate(logs):
        observed = rows(log); starts,drains = _events(log)
        require([r['match'] for r in starts] == [r['match'] for r in drains] == matches and
                len({r['world'] for r in starts}) == 2, 'closed client world/drain sequence missing or reused')
        require(len(observed) == 2 and [r['match'] for r in observed] == matches and
                len({r['owner_thread'] for r in observed}) == 1, 'exactly two main-thread world retirements required per client')
        worlds = []
        for index,(row,start,drain) in enumerate(zip(observed,starts,drains)):
            require(row['world'] == start['world'] == row['movement_world'] == row['worker_world'] and
                    row['match'] == row['movement_match'] == row['worker_match'], 'retirement uses stale or foreign lifetime keys')
            require(row['reason'] == 'drained' and row['trigger'] in NORMAL_TRIGGERS and
                    row['prepared'] is row['pacing_started'] is row['end_sent'] is row['drained'] is
                    row['match_ended'] is row['connected'] is True and
                    row['failed'] is row['visual_failed'] is row['abort_pending'] is False,
                    'normal drain retirement was replaced by failure/disconnect/new-world fallback')
            require(row['roots_before'] == 3+2*row['entries_before'] and row['frame'] == drain['presented'] and
                    row['frame'] >= 650, 'normal retained root counts/last publication differ')
            limit = starts[index+1]['line'] if index+1 < len(starts) else len(log.splitlines())
            require(start['line'] < drain['line'] < row['_line'] < limit,
                    'old visual ownership survived until next world or preceded actual drain')
            if client == 0:
                poses = [p for p in visual_records if p['event'] == 'visual_pose' and p['world'] == row['world'] and p['match'] == row['match']]
                require(poses and max(p['sampled_us'] for p in poses) <= row['sampled_us'],
                        'subject retirement precedes its actual joined visual observations')
            worlds.append(dict(world=row['world'],match=row['match'],frame=row['frame'],reason=row['reason'],trigger=row['trigger'],
                sampled_us=row['sampled_us'],thread=row['thread'],owner_thread=row['owner_thread'],
                entries_before=row['entries_before'],pulses_before=row['pulses_before'],roots_before=row['roots_before'],
                entries_after=0,pulses_after=0,roots_after=0,drain_complete=drain,
                retirement_line=row['_line'],before_next_world=True,record=row))
        clients.append(dict(client=client,pid=pids[client],passed=True,worlds=worlds))
    return dict(schema=1,passed=True,clients=clients,retirements=4,normal_drain_only=True,
        full_feature_accepted=False,physical_input_accepted=False,
        scope='Four closed-client main-thread visual root retirements after actual normal drains, before next world/exit',
        limitations=['Root counts describe owned GC handles and policy entries, not complete process memory.',
            'Existing parent native/wire/visual/natural lifecycle gates remain mandatory.'])
