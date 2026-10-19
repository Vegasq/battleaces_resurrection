"""Per-army evidence for one owned local public match; no runtime actions."""
import json
import re
from tools.verify_practice_ai import movement_evidence


def require(condition,message):
    if not condition:raise AssertionError(message)


def public_match(log,resources,*,mode,display_name):
    log=log.replace('\r\n','\n').replace('\r','\n')
    require(mode in (1,2,5),'unsupported public evidence mode')
    starts=re.findall(r'Practice requested: match=([0-9a-f]{32}) mode=([1245]) ',log)
    require(len(starts)==1 and int(starts[0][1])==mode,'local public match identity/mode differs')
    participants=2 if mode==1 else 4
    difficulty=re.search(r'Public AI difficulty snapshot: selected=(\w+) modifierProfile=(17|18|19) practiceSelectionUnchanged=1',log)
    require(difficulty,'random public difficulty snapshot missing')
    armies=[json.loads(line.split('Practice army snapshot: ',1)[1]) for line in log.splitlines() if 'Practice army snapshot: ' in line]
    require(len(armies)==participants and [a.get('armyId',0) for a in armies]==list(range(participants)),
            'public army count/order differs')
    require([a.get('allianceId',0) for a in armies]==[seat%2 for seat in range(participants)],'public team alliances differ')
    require(armies[0]['players'][0]['playerHandleWithName']['playerName']==display_name,'configured human name lost')
    require(log.count('Practice AI join captured:')==participants-1 and log.count('Practice AI JoinedGame delivered:')==participants-1,
            'missing/duplicate native bot join')
    require(f'Local AI all ready: bots={participants-1} sharedSimulation=1 producers={participants}' in log,
            'not every independent bot became ready in the shared world')
    bots=[];names={display_name}
    for seat,army in enumerate(armies[1:],1):
        player=army['players'][0];name=player['playerHandleWithName']['playerName'];profile=player['aiProfileId']
        profiles=(58,62,63,64) if mode==1 else (59,) if mode==2 or seat==2 else (60,)
        require(name and name!='Practice AI' and name not in names and profile in profiles,'public bot name/profile pool differs')
        names.add(name)
        portrait,banner=army.get('portraitId',0),army.get('bannerId',0)
        require(portrait and banner,'public native bot avatar missing')
        require(f'Practice effective AI profile: id={profile} expectedTableEntry=1' in log,'native bot profile override missing')
        require(log.count(f'Practice native JoinArmy validated: army={seat} ')==1,'bot frozen deck did not join exactly once')
        moved,ordered=movement_evidence(log,set(army['deck']['units']),seat)
        require(moved&ordered,'bot did not autonomously move produced units: '+str(seat))
        supply=max((int(row['current_supply']) for row in resources if row['viewer']==str(seat%2) and row['army']==str(seat)),default=0)
        require(supply>0,'native bot supply missing: '+str(seat))
        bindings={}
        for phase in ('in-game','result'):
            # Native observer checks live/current owner,actual name,model AI flag,
            # avatar keys and visible portrait/banner child bindings before log.
            pattern=rf'Public AI identity binding: phase={phase} name=(.*?) modelAi=([01]) portrait=(\d+) banner=(\d+) portraitChildren=(\d+) bannerChildren=(\d+) live=1 currentMatch=1 army={seat}$'
            matches=[row for row in re.finditer(pattern,log,re.MULTILINE) if
                     row[1] in ((name,name+' (Alias)') if phase=='result' else (name,)) and
                     (phase!='result' or row[2]=='1') and int(row[3])==portrait and int(row[4])==banner and
                     int(row[5])>0 and int(row[6])>0]
            require(matches,'public native profile binding missing: '+phase+' army='+str(seat));bindings[phase]=True
        bots.append(dict(seat=seat,profile=profile,name=name,portrait=portrait,banner=banner,deck=army['deck']['units'],
                         max_supply=supply,ordered_moving_units=sorted(moved&ordered),native_profile_bindings=bindings))
    markers=[f'PUBLIC QUEUE SMOKE original OnMapSelected: mode={mode} visible=1 automatedCallback=1',
             'Practice native EndOfGameResponse delivered;','PRACTICE SMOKE native Continue (automated)',
             f'Practice returned: completed=1 mode={mode} seat=-1 presenceRetained=0 standalone=1','NATIVE QUIT owned menu verified:']
    offsets=[log.find(marker) for marker in markers]
    require(all(value>=0 and log.count(marker)==1 for value,marker in zip(offsets,markers)) and offsets==sorted(offsets),
            'public original Play/result/Continue/menu/Quit order differs')
    return dict(match=starts[0][0],mode=mode,human_name=display_name,human_deck=armies[0]['deck']['units'],
                public_difficulty=difficulty[1],bots=bots,native_result=True,native_continue=True,returned_to_menu=True)


def public_search(log,*,mode):
    log=log.replace('\r\n','\n').replace('\r','\n')
    starts=re.findall(r'Native search began: ticket=(\d+) mode=(\d+) nativeStatus=5 originalPanel=1',log)
    require(len(starts)==1 and int(starts[0][1])==mode,'native public search missing or duplicated')
    ticket=starts[0][0]
    markers=[f'Native search began: ticket={ticket} mode={mode} nativeStatus=5 originalPanel=1',
             f'Public search intent: ticket={ticket} mode={mode} originalSearch=1 deadlineMs=30000',
             f'Public fallback accepted: ticket={ticket} mode={mode} beforeAmbiguousCommit=1',
             f'Native search match accepted: ticket={ticket} status=7',
             f'Native search joining signal: ticket={ticket} mode={mode} activeConnection=1 originalRouter=1']
    offsets=[log.find(marker) for marker in markers]
    require(all(value>=0 and log.count(marker)==1 for value,marker in zip(offsets,markers)) and offsets==sorted(offsets),
            'native public search/fallback/found/joining order differs')
    releases=[line for line in log.splitlines() if f'Native search released: ticket={ticket} ' in line]
    require(len(releases)==1 and releases[0].endswith('status=0') and log.find(releases[0])>offsets[-1],
            'native public search was not released after joining')
    require('owner=remote' not in log and log.count('owner=local-practice nativeIdle=1')==1,
            'unconfigured public match acquired/released another world')
    return dict(ticket=int(ticket),mode=mode,original_panel=True,native_status_sequence=[5,7,0],
                optional_server_fallback=True,joining_original_router=True,
                scope='component phases only; no timer/Cancel/pixel/online-wait qualification')
