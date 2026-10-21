"""Correlate original remote profile observations with the actual server bootstrap."""
import json
import re

from server.game_data import decompress_game_data,decode_deck,decode_identity
from server.protobuf_wire import get_bytes,get_repeated_bytes,get_uint


def require(value,message):
    if not value:raise AssertionError(message)


def expected_players(bootstrap,match,mode):
    game=get_bytes(decompress_game_data(bootstrap),1,required=True)
    require(get_uint(game,36)==mode,'profile bootstrap mode differs')
    armies=get_repeated_bytes(game,2)
    require(len(armies)==(2 if mode==1 else 4),'profile bootstrap roster differs')
    result=[]
    for seat,army in enumerate(armies):
        players=get_repeated_bytes(army,2);require(len(players)==1,'profile army requires one identity')
        identity=decode_identity(players[0]);deck=decode_deck(get_bytes(army,3,required=True))
        require(get_uint(army,1)==seat and identity['player_id']==seat+1,'profile bootstrap player/army changed')
        result.append(dict(match=match,mode=mode,army=seat,player=identity['player_id'],profile=identity['ai_profile_id'],
            name=identity['name'],portrait=get_uint(army,6),banner=get_uint(army,5),units=list(deck['units'])))
    return result


def validate(log,match,mode,expected):
    log=log.replace('\r\n','\n').replace('\r','\n')
    require(len(expected)==(2 if mode==1 else 4) and [row['army'] for row in expected]==list(range(len(expected))),
            'profile expected roster must be complete and ordered')
    def rows(phase):
        values=[]
        for line in log.splitlines():
            marker='REMOTE PROFILE '+phase+': '
            if marker in line:
                prefix,text=line.split(marker,1)
                require(re.fullmatch(r'\[\d+\] ',prefix) is not None,'profile evidence line has no native timestamp')
                values.append((log.index(line),json.loads(text)))
        return values
    frozen=rows('expected');loading=rows('loading');native=rows('native');results=rows('result')
    require([row for _,row in frozen]==expected,'native frozen profile differs from actual server bootstrap')
    require(len(results)==len(expected) and {row['army'] for _,row in results}==set(range(len(expected))),
            'each original result profile must be observed exactly once')
    require(len(loading)==1,'one original owned loading screen observation required')
    screen=loading[0][1]
    require(screen['match']==match and screen['mode']==screen['signal_mode']==mode and
            screen['view_mode'] in ((1,4) if mode==1 else (mode,)) and screen['front_owned'] is True and
            screen['live'] is True and screen['original_screen'] is True and screen['profile_roster_present'] is False,
            'original loading signal/mode/owner differs')
    require(len(native)==len(expected) and {row['army'] for _,row in native}==set(range(len(expected))),
            'every original native roster entry must be observed once')
    for _,actual in native:
        wanted=expected[actual['army']]
        require(all(actual[key]==value for key,value in wanted.items()),'original native roster differs from bootstrap')
        require(type(actual['loading_active']) is bool and actual['simulation_owned'] is True and actual['match_data_owned'] is True,
                'original native roster lacks actual current ownership')
    def one(marker):
        require(log.count(marker)==1,'missing/duplicate original profile lifecycle: '+marker)
        return log.index(marker)
    armed=one(f'REMOTE PROFILE proof armed: match={match} players={len(expected)} BA_RESURRECTION_REMOTE_PROFILE_V1')
    joined=one(f'Public native match joined: ticket=1 match={match} mode={mode} participants={len(expected)} seat=0 remoteWorld=1')
    delivered=one('Practice native EndOfGameResponse delivered;')
    complete=one(f'REMOTE PROFILE results complete: match={match} players={len(expected)} originalGetters=1 liveChildren=1')
    continued=one(f'Public result Continue routed: mode={mode} source=remote next=End')
    returned=one(f'Public native return: ticket=1 match={match} aborted=0 nativeIdle=1')
    retired=one(f'REMOTE PROFILE observer retired: match={match} rootedOwners=0')
    require(max(offset for offset,_ in frozen)<armed<joined<loading[0][0]<min(offset for offset,_ in native) and
            max(offset for offset,_ in native)<delivered<min(offset for offset,_ in results) and
            max(offset for offset,_ in results)<complete<continued<returned<retired,
            'profile observations are outside the owned original lifecycle')
    for _,actual in results:
        wanted=expected[actual['army']]
        for key in ('match','mode','army','player','name','portrait','banner','units'):
            require(actual[key]==wanted[key],'original result profile changed '+key)
        require(actual['is_ai'] is bool(wanted['profile']),'original result AI flag changed')
        require(actual['displayed'] in (wanted['name'],wanted['name']+' (Alias)'),
                'original result getter displays a different name')
        require(actual['front_owned'] is True and actual['live'] is True and
                type(actual['portrait_children']) is int and actual['portrait_children']>0 and
                type(actual['banner_children']) is int and actual['banner_children']>0,
                'original result profile lacks owned live avatar children')
    require(not any(marker in log for marker in ('Public client failure:','Client lifecycle invariant failed:',
            'Public fallback accepted:','remote original result profile observation deadline')),
            'profile observer or remote match failed')
    return dict(match=match,mode=mode,players=len(expected),bots=sum(row['profile']!=0 for row in expected),
        original_result_models=True,original_name_ai_and_deck_getters=True,live_avatar_children=True,
        original_loading_signal=True,loading_has_profile_roster=False,original_native_roster=True,
        roster_observed_during_loading=all(row['loading_active'] for _,row in native),
        original_continue_after_observation=True,rooted_owners_released=True,artwork_or_physical_qualified=False)
