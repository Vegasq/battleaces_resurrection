"""Pure evidence joins for real bound-Mouse input through non-HQ removal.

No input, selector edits, native calls, or diagnostic-row rewriting occurs here.
The original mobile wire/native/replay/feel proof remains independently required.
"""
from __future__ import annotations

import json
import re

PREFIX = 'MOBILE HELD CLICK '
SCHEMA = 3
UINT32, UINT64 = 2**32-1, 2**64-1
FIRST = ('setup','position_queued','position_observed','press_queued','pressed',
    'held_checkpoint','native_dead','natural_release')
FRESH = ('fresh_position_queued','fresh_position_observed','fresh_press_queued','fresh_pressed',
    'fresh_release_queued','fresh_released','fresh_input_closed','fresh_move_queued','complete')
FIELDS = set(('schema,event,sequence,world,match,slot,entity,unit_type,army,frame,tick_ms,sampled_us,'
    'session,input_sequence,selector,action,control,device,input_closed,owned_button,click_id,mode,primary,'
    'context,drag,original_token,current_token,canonical_token,current_ids,preview_ids,casting_ids,'
    'native_present,native_state,current_admitted,returned_serial,returned_down,returned_up,ledger_completed,ledger_serial,'
    'current_count,preview_count,pending_commands,'
    'selection_writes,history_writes,physicalUI').split(','))


def require(ok, reason):
    if not ok:
        raise AssertionError('mobile held click evidence: '+reason)


def integer(value, low=0, high=UINT64):
    return type(value) is int and low <= value <= high


def _unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate JSON key')
        result[key]=value
    return result


def records(log, match):
    """Validate the complete independent held prefix before granting any scope."""
    require(type(log) is str and len(log)<=32*1024*1024 and type(match) is str and
        re.fullmatch('[a-f0-9]{32}',match),'invalid log/match')
    own=[];all_rows=[]
    for index,line in enumerate(log.splitlines()):
        if PREFIX not in line:
            continue
        raw=line.split(PREFIX,1)[1]
        require(0<len(raw)<=8192,'row exceeds bound')
        try:
            row=json.loads(raw,object_pairs_hook=_unique)
        except (TypeError,ValueError) as error:
            raise AssertionError('mobile held click evidence: invalid JSON') from error
        require(type(row) is dict and set(row)==FIELDS and integer(row['schema'],SCHEMA,SCHEMA)and
            type(row['match']) is str and re.fullmatch('[a-f0-9]{32}',row['match']),
            'strict schema3/match differs; v1/v2 are preserved separately')
        all_rows.append(row);require(len(all_rows)<=42,'unexpected full-log held event count')
        if row['match']==match:
            own.append((index,row));require(len(own)<=21,'unexpected event count')
    require(len(own)==21,'complete held episode required')
    indices,rows=zip(*own);world=rows[0]['world']
    require(integer(world,1,2),'fixture world must be1/2')
    branch=('restored','release_queued','released','input_closed') if world==1 else (
        'release_queued','released','input_closed','restored')
    require([r['event']for r in rows]==list((*FIRST,*branch,*FRESH)) and
        [r['sequence']for r in rows]==list(range(1,22)),'missing/duplicate/reordered event')
    events={r['event']:r for r in rows};token=rows[0]['original_token']
    closed={'input_closed','fresh_input_closed','fresh_move_queued','complete'}
    held={'pressed','held_checkpoint','native_dead','natural_release','release_queued','fresh_pressed','fresh_release_queued'}
    if world==1:held.add('restored')
    absent={'natural_release'}|({'release_queued','released','input_closed'}if world==2 else set())
    for row in rows:
        event=row['event'];session=2 if event in FRESH else 1
        seq=(1 if event in FRESH[:2] else 2 if event in FRESH[2:4] else 3) if session==2 else (
            0 if event=='setup' else 1 if event in FIRST[1:3] else
            3 if event in ('release_queued','released','input_closed')or event=='restored'and world==2 else 2)
        is_closed=event in closed or event=='restored'and world==2
        require(all(integer(row[k],v,v)for k,v in (('schema',SCHEMA),('world',world),('slot',1),('entity',11),
            ('unit_type',1),('army',1),('session',session),('input_sequence',seq))) and
            integer(row['frame'],130,261) and all(integer(row[k])for k in ('tick_ms','sampled_us','returned_serial','ledger_serial')),
            'identity/session/input sequence/clock differs')
        require(all(type(row[k])is bool for k in ('input_closed','primary','context','drag','native_present',
            'current_admitted','returned_down','returned_up','ledger_completed','physicalUI')) and row['input_closed'] is is_closed and
            row['physicalUI'] is False and not row['context'] and not row['drag'] and
            not(row['returned_down']and row['returned_up']),'observed boolean/scope differs')
        require(all(type(row[k])is str and re.fullmatch('[a-f0-9]{1,16}',row[k])and int(row[k],16)>0
            for k in ('selector','action','control','device')),'bound input tuple is missing/noncanonical')
        require(row['owned_button'] is None if is_closed else type(row['owned_button']) is bool,
            'borrowed/closed button scope differs')
        require(integer(row['click_id'],0,UINT32)and integer(row['mode'],0,2)and integer(token,1) and
            row['original_token']==row['canonical_token']==token and
            all(integer(row[k])for k in ('original_token','canonical_token','current_token')) and
            row['current_token'] in (0,token)and
            all(integer(row[k],0,0)for k in ('selection_writes','history_writes')) and
            integer(row['pending_commands'],1 if event=='fresh_move_queued'else 0,1 if event=='fresh_move_queued'else 0),
            'canonical token or fixture write/queue invariant differs')
        for key in ('current_ids','preview_ids','casting_ids'):
            require(type(row[key])is list and len(row[key])<=4096 and len(row[key])==len(set(row[key]))and
                all(integer(v,0,UINT32)for v in row[key]),'invalid raw ID set')
        require(row['current_ids']in([],[11])and row['preview_ids']in([],[11])and row['casting_ids']==[],
            'foreign selection/casting input')
        require(all(integer(row[k],0,1)for k in ('current_count','preview_count'))and
            all(row[stem+'_count']==0 for stem in ('current','preview')if not row[stem+'_ids'])and
            row['ledger_serial']>=row['returned_serial']and
            (not row['ledger_completed']or row['ledger_serial']==row['returned_serial']),
            'original resolvable counts or returned/authorization ledger scalars differ')
        require(row['native_state']is None if not row['native_present'] else integer(row['native_state'],0,UINT32-1),
            'native state presence differs')
        require(not row['current_admitted']or row['current_token']==token and row['native_present'],
            'admission lacks original canonical identity')
        require(row['primary'] is (event in held) and row['mode']==(1 if event in held else 0) and
            (is_closed or row['owned_button'] is (event in held)),'original Single button lifecycle differs')
        if event in FIRST[:4]:
            require(row['returned_serial']==row['ledger_serial']==0 and not row['returned_down']and
                not row['returned_up']and not row['ledger_completed'],'position/setup invented a primary button return')
        if row['native_present']and row['native_state']!=6 and row['current_ids']==[11]:
            require(row['current_count']==1,'live original current member does not resolve')
        if event=='fresh_pressed':
            require(row['current_ids']==row['preview_ids']==[11]and row['current_count']==row['preview_count']==1,
                'fresh original Down lacks both admitted/resolvable numeric sets')
        if event in absent:
            require(not row['native_present']and not row['current_admitted']and row['current_token']==0,
                'physical absence identity/admission differs')
            require(row['current_count']==row['preview_count']==0,
                'physically absent raw member resolved through original Count')
        if event in ('native_dead','natural_release','release_queued')or event=='restored'and world==1:
            require(row['current_ids']==row['preview_ids']==[11],
                'schema3 original held numeric sets did not remain retained before Up')
        if world==2 and event in ('released','input_closed'):
            require(row['current_ids']==row['preview_ids']==[11]and row['current_count']==row['preview_count']==0,
                'original absent-Up raw retention/Count0 boundary differs')
        if (world==1 and event in ('released','input_closed'))or event in ('fresh_released','fresh_input_closed'):
            require(row['current_ids']==[11]and row['preview_ids']==[]and row['current_count']==1 and row['preview_count']==0,
                'original live Up current/preview resolution boundary differs')
        if event in ('setup','held_checkpoint','restored','fresh_released','fresh_input_closed','fresh_move_queued','complete'):
            require(row['native_present']and row['native_state']!=6 and row['current_admitted']and
                row['current_token']==token,'live/restored original token missing')
        if event in ('setup','held_checkpoint','fresh_released','fresh_input_closed','fresh_move_queued','complete'):
            require(row['current_ids']==[11]and row['current_count']==1,'original selection outcome/count differs')
        if event=='restored'and world==2:
            require(row['current_ids']==[11]and row['current_count']==1 and row['preview_ids']==[]and row['preview_count']==0,
                'restored original retained membership/Count1 differs')
        if event=='restored'and world==1:
            require(row['current_count']==row['preview_count']==1,'held restored original counts differ')
        if event=='native_dead':require(row['native_present']and row['native_state']==6,'native DEAD missing')
    require(len({r['selector']for r in rows})==1 and all(len({r[k]for r in rows if r['session']==session})==1
        for session in (1,2)for k in ('action','control','device')),'input owner tuple changed within session')
    require(all(b['frame']>=a['frame']and b['tick_ms']>=a['tick_ms']and b['sampled_us']>a['sampled_us']and
        b['returned_serial']>=a['returned_serial']for a,b in zip(rows,rows[1:])),'clocks/ticket serial regressed')
    for prefix,end in (('',('released','input_closed')),('fresh_',('fresh_released','fresh_input_closed','fresh_move_queued','complete'))):
        down=events[prefix+'pressed'];up=events[prefix+'released']
        require(down['returned_down']and not down['returned_up']and down['returned_serial']>0 and
            down['ledger_completed']and down['ledger_serial']==down['returned_serial']and
            down['returned_serial']>events[prefix+'press_queued']['ledger_serial']and
            up['returned_up']and not up['returned_down']and up['returned_serial']>down['returned_serial'],
            'original returned Down/Up callback is unbalanced')
        absent_up=world==2 and prefix==''
        require(up['ledger_completed']is absent_up and
            (up['ledger_serial']==up['returned_serial']if absent_up else up['ledger_serial']>up['returned_serial']),
            'returned Up was confused with unchanged production ledger authorization')
        between=[r for r in rows if down['sequence']<=r['sequence']<up['sequence']]
        require(all(r['returned_down']and not r['returned_up']and r['returned_serial']==down['returned_serial']and
            r['ledger_completed']and r['ledger_serial']==down['returned_serial']and
            r['click_id']==11 for r in between)and all(events[e]['returned_up']and not events[e]['returned_down']and
            events[e]['returned_serial']==up['returned_serial']and events[e]['ledger_completed']is up['ledger_completed']and
            events[e]['ledger_serial']==up['ledger_serial']and events[e]['click_id']==11 for e in end),
            'returned callback/ledger provenance changed inside session')
        marker=re.compile(r'Prediction input Single observed: world=(\d+) generation=(\d+) serial=(\d+) entity=(\d+) '
            r'originalDown=1 originalProcess=1 completedCallback=1 dispatchVerified=1 repairAuthorized=0')
        joined=[(i,m)for i,line in enumerate(log.splitlines())if (m:=marker.search(line))and
            tuple(map(int,(m[1],m[3],m[4])))==(world,down['returned_serial'],11)]
        start=indices[[r['event']for r in rows].index(prefix+'press_queued')]
        stop=indices[[r['event']for r in rows].index(prefix+'pressed')]
        require(len(joined)==1 and start<joined[0][0]<stop and int(joined[0][1][2])>0,
            'returned Down lacks the actual original accepted Single/Process marker')
    first_up=events['released'];second_down=events['fresh_pressed']
    return_fields=('returned_serial','returned_down','returned_up','ledger_completed','ledger_serial')
    require(all(tuple(r[k]for k in return_fields)==tuple(first_up[k]for k in return_fields)
        for r in rows if first_up['sequence']<=r['sequence']<second_down['sequence']),
        'position/restoration overwrote the prior returned primary Up witness')
    require(events['fresh_pressed']['returned_serial']>events['released']['ledger_serial'] and
        events['released']['current_ids']==[11] and
        (world==1 or events['restored']['returned_up']and events['restored']['ledger_completed']and
            events['restored']['returned_serial']==events['restored']['ledger_serial']==events['released']['returned_serial']),
        'first-release outcome or fresh callback serial differs')
    exact={'setup':130,'position_queued':148,'press_queued':150,'held_checkpoint':152,'native_dead':153,
        'natural_release':154,'fresh_position_queued':178,
        'fresh_press_queued':180,'fresh_release_queued':182,'fresh_move_queued':184}
    require(all(events[e]['frame']==f for e,f in exact.items())and
        148<=events['position_observed']['frame']<=150 and 150<=events['pressed']['frame']<=151 and
        178<=events['fresh_position_observed']['frame']<=180 and 180<=events['fresh_pressed']['frame']<=181 and
        182<=events['fresh_released']['frame']<=183 and
        events['input_closed']['frame']==events['released']['frame']and
        events['fresh_input_closed']['frame']==events['fresh_released']['frame']and
        (165<=events['release_queued']['frame']<=166 and 165<=events['released']['frame']<=167 if world==1 else
            events['release_queued']['frame']==154 and 154<=events['released']['frame']<=155)and
        260<=events['complete']['frame']<=261 and
        events['restored']['frame']>=154 and events['restored']['frame']<=174,
        'physical callback/event boundaries differ')
    carried_idle_history=False
    if events['setup']['click_id']==11:
        previous=[r for r in all_rows if r['world']==1 and r['event']=='complete'and
            r['sampled_us']<events['setup']['sampled_us']]
        require(world==2 and len(previous)==1,'initial reference11 lacks the prior completed real-input world')
        prior=records(log,previous[0]['match'])['events']['complete']
        require(prior['selector']==events['setup']['selector']and prior['input_closed']and prior['returned_up']and
            prior['click_id']==11 and not prior['primary']and prior['mode']==0,
            'initial idle history was not retained from the same prior released selector')
        carried_idle_history=True
    return dict(rows=list(rows),indices=list(indices),events=events,world=world,match=match,token=token,
        carried_idle_history=carried_idle_history)


def mobile_row_scope(witness, row):
    """Only the validated real callback intervals can admit primary/ref11 rows."""
    events=witness['events']
    require(row['world']==witness['world']and row['match']==witness['match']and
        row['original_incarnation']==witness['token'],'mobile/held owner identity differs')
    if row['event']=='original_mobile_selection_established':
        require(not row['left_held'],'setup is not idle')
        return witness['carried_idle_history'] if row['live_click_id']==11 else False
    require(row['focus_group']==-1,'cancelled original repeat focus silently restarted')
    intervals=[(events[p+'pressed'],events[p+'released'])for p in ('','fresh_')]
    true_possible=any(a['frame']<=row['frame']<=b['frame']for a,b in intervals)
    true_required=any(a['frame']<row['frame']<b['frame']for a,b in intervals)
    require(not row['left_held']or true_possible,'primary hold escaped original Down/Up interval')
    require(not true_required or row['left_held'],'primary released without original Up')
    if row['live_click_id']==11:
        require(events['pressed']['frame']<=row['frame']<=events['complete']['frame'],
            'reference11 preceded accepted original Down')
    return True


def bind_mobile(witness, rows, indices):
    """Join unmodified named snapshots to same-owner, same-callback held rows."""
    events=witness['events'];held_indices=dict(zip((r['event']for r in witness['rows']),witness['indices']))
    names=('setup','native_dead','natural_release','restored','fresh_press_queued','fresh_released','complete')
    episode=[(index,r)for index,r in zip(indices,rows)if r['event']!='snapshot']
    require(len(episode)==len(names),'mobile lifecycle is incomplete')
    for (index,row),name in zip(episode,names):
        held=events[name]
        require(row['frame']==held['frame']and row['sampled_us']<=held['sampled_us']and index<held_indices[name]and
            not any(index<i<held_indices[name]for i in indices),'named snapshot is not the original same-callback held observation')
        require(row['selected_ids']==held['current_ids']and row['preview_ids']==held['preview_ids']and
            row['casting_ids']==held['casting_ids']and row['current_incarnation']==held['current_token']and
            row['current_admitted']is held['current_admitted']and row['left_held']is held['primary']and
            row['right_held']is held['context']and row['live_click_id']==held['click_id']and
            row['native_identity_present']is held['native_present']and row['native_state']==held['native_state'],
            'named mobile snapshot differs from independently observed held state')
    require(episode[4][1]['frame']==180 and episode[5][1]['selection_scope_player_initiated']is None,
        'fresh selection was fabricated through a programmatic scope')
    return dict(passed=True,evidence_schema=SCHEMA,world=witness['world'],match=witness['match'],rows=witness['rows'],
        balanced_original_input=True,release_while_absent=witness['world']==2,
        selection_writes=0,history_writes=0,physicalUI=False)


def evaluate(log, *, attacker_log, mobile_episodes, expected_matches):
    require(PREFIX not in attacker_log and type(expected_matches)is list and len(expected_matches)==2 and
        len(set(expected_matches))==2 and type(mobile_episodes)is list and len(mobile_episodes)==2 and
        [ep.get('match')for ep in mobile_episodes]==expected_matches,'both victim-only ordered mobile episodes required')
    result=[]
    for world,(match,ep)in enumerate(zip(expected_matches,mobile_episodes),1):
        witness=records(log,match);bound=ep.get('mobile_held_click',{})
        require(ep.get('passed')is True and witness['world']==ep.get('world')==world and bound.get('passed')is True and
            bound.get('rows')==witness['rows']and ep.get('same_confirmed_token')is True and
            ep.get('original_mobile_release_observed')is True and ep.get('current_mobile_reinitialized_and_admitted')is True and
            ep.get('escape_native_replay',{}).get('continuation_frames')==20 and
            ep.get('fresh_native_confirmation',{}).get('continuation_frames')==20 and
            ep.get('fresh_motion',{}).get('passed')is True and ep.get('fresh',{}).get('order',{}).get('frame')==184,
            'held prefix lacks independent mobile release/escape/replay20/fresh command proof')
        result.append(bound)
    require(result[0]['rows'][-1]['sampled_us']<result[1]['rows'][0]['sampled_us'],
        'rematch input clocks do not follow the prior balanced completed world')
    require(sum(PREFIX in line for line in log.splitlines())==42,'extra/unjoined held episode')
    return dict(passed=True,evidence_schema=SCHEMA,episodes=result,selection_writes=0,history_writes=0,physicalUI=False,
        full_mobile_controls_accepted=False,natural_removal_empty_preview_held_accepted=False,
        scope='Schema3 original Down/returned Up, retained numeric IDs with original Count0 while absent and Count1 after restoration, fresh genuine click/Move184 and full native joins. Returned callbacks do not override production authorization; no broad natural-removal/empty-preview-held acceptance')
