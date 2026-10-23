"""Owned packaged native income/first-hit experiment; no Unity, AI or network."""
from __future__ import annotations
import argparse,hashlib,json,subprocess,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LEVELS=('easy','normal','hard','normal-repeat')
Q32=1<<32

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def require(value,message):
    if not value:raise ValueError(message)

def assess(levels):
    """Independent comparisons: actual deltas, human control and Normal repeat."""
    require(set(levels)==set(LEVELS),'four strength/control records required')
    normal=levels['normal'];checks={}
    def gains(record,army):
        samples={s['frame']:s for s in record['income']['samples']}
        require(200 in samples and 600 in samples,'fixed income endpoints required')
        first,last=(samples[f]['resources'][str(army)] for f in (200,600))
        require(first['current_supply']==last['current_supply']==0,'income control spent resources')
        for value in (first,last):
            require(value['primary']==value['primary_gathered'] and value['secondary']==value['secondary_gathered'] and
                    value['primary_lost']==value['secondary_lost']==0,'income control lost resources')
        return tuple(last[k]-first[k] for k in ('primary_gathered','secondary_gathered'))
    human_gain=gains(normal,0);bot_gain=gains(normal,1)
    require(all(v>0 for v in bot_gain) and human_gain==bot_gain,'Normal income baseline differs')
    checks['normal_repeat']=normal==levels['normal-repeat']
    reference=normal['combat']['hits'];require(set(reference)=={'0','1'},'both first hits required')
    require(reference['0']['delta']==reference['1']['delta']>0,'symmetric Normal first hits required')
    for level,record in levels.items():
        resource,damage,health=record['strength']
        require(all(type(v) is int and 0<v<=4*Q32 for v in record['strength']),'invalid factors')
        observed=gains(record,1)
        checks[level+'_income']=all(abs(actual*Q32-base*resource)<=Q32 for actual,base in zip(observed,bot_gain))
        checks[level+'_human_income']=gains(record,0)==human_gain
        checks[level+'_closed']=record['income']['closed'] is record['combat']['closed'] is True
        hits=record['combat']['hits'];require(set(hits)=={'0','1'},'both first hits required')
        checks[level+'_two_builds']=record['combat']['build_count']==2
        for target in ('0','1'):
            hit,baseline=hits[target],reference[target]
            before,after=hit['before'],hit['after'];attacker=hit['attacker']
            require(hit['delta']>0 and hit['delta']==after['current_damage']-before['current_damage'] and
                    before['current_damage']==0 and hit['live_units']==[1,1],'isolated first hit required')
            require(before['id']==after['id'] and before['army']==int(target) and attacker['army']==1-int(target),
                    'hit ownership differs')
            factor=damage if target=='0' else Q32
            checks[level+'_damage_to_'+target]=hit['delta']==(baseline['delta']*factor)>>32
            expected_health=(baseline['before']['max_health']*(health if target=='1' else Q32))>>32
            checks[level+'_target_health_'+target]=before['max_health']==after['max_health']==expected_health
            geometry=lambda h:(h['frame'],h['before']['id'],h['before']['type'],h['before']['position'],
                               h['attacker']['id'],h['attacker']['type'],h['attacker']['position'])
            checks[level+'_geometry_'+target]=geometry(hit)==geometry(baseline)
    return checks

def experiment(assets):
    from dataclasses import replace
    from server.assets import verify_assets
    from server.ai_rules import RuleBook
    from server.bot_catalog import BotCatalog
    from server.game_data import GameTemplate,encode_frame,encode_player_input
    from server.protobuf_wire import field_bytes,field_uint,field_packed_uint,get_uint
    from server import native_simulation as native
    verify_assets(assets)
    template=GameTemplate.load(assets/'map-1v1.pb.gz',catalog_path=assets/'unit-catalog.json',descriptors_path=assets/'descriptors')
    catalog=BotCatalog(assets,template=template,rules=RuleBook(assets))
    choice=catalog.choose(1,difficulty='normal',randbelow=lambda bound:0)
    def execute(entity_type,ability,ids,command):
        group=field_uint(1,entity_type)+field_uint(2,ability)+field_packed_uint(3,ids)
        return field_bytes(1,field_bytes(1,group)+field_bytes(3,command))
    records={}
    for level in LEVELS:
        index=LEVELS.index(level) if level!='normal-repeat' else 1
        bot=replace(choice,difficulty=LEVELS[index],strength=catalog.strengths[17+index])
        match=template.build_match([dict(slot=0,name='Human control'),dict(slot=1,name=bot.name,ai_profile_id=bot.profile)],
            {0:bot.deck.units,1:bot.deck.units},seed=162,game_name='strength-control',bot_choices={1:bot})
        def join(slot):
            value=field_uint(1,slot)+field_bytes(2,match.deck_messages_by_slot[slot])
            for target,source in ((3,5),(4,6)):
                number=get_uint(match.armies_by_slot[slot],source)
                if number:value+=field_uint(target,number)
            return field_bytes(3,value)
        record=dict(strength=list(bot.strength),match_sha256=match.raw_sha256,bot_profile=bot.profile,
                    basic_unit=bot.deck.units[0],income=dict(samples=[]),combat=dict(hits={},build_count=0))
        for phase,limit in (('income',601),('combat',3000)):
            journal=hashlib.sha256();steps=0
            with native.NativeSimulation(match.raw_game_data,assets/'Simulation.dll') as sim:
                for frame in range(limit):
                    state=sim.state(include_entities=True) if phase=='combat' else None
                    actions={0:[],1:[]}
                    if phase=='combat':
                        owned={slot:[e for e in state['entities'] if e.get('army')==slot and 'type' in e] for slot in (0,1)}
                        if frame==140:
                            for slot in (0,1):
                                builders=[(e['id'],e['type'],ability) for e in owned[slot] for ability in template.entity_abilities[e['type']]
                                          if template.build_ability_slots.get(ability)==0]
                                entity,entity_type,ability=min(builders)
                                actions[slot].append(execute(entity_type,ability,[entity],field_bytes(1,b'')))
                                record['combat']['build_count']+=1
                        units={slot:[e for e in owned[slot] if e['type']==match.decks_by_slot[slot][0]] for slot in (0,1)}
                        require(all(len(value)<=1 for value in units.values()),'more than one test unit per army')
                        if all(units.values()) and frame%40==0:
                            for slot in (0,1):
                                attacker,target=units[slot][0],units[1-slot][0]
                                actions[slot].append(execute(attacker['type'],88,[attacker['id']],field_bytes(2,field_uint(1,target['id']))))
                    inputs={slot:encode_player_input(match.identities_by_slot[slot],[join(slot)] if frame==0 else actions[slot]) for slot in (0,1)}
                    data=encode_frame(frame,inputs);journal.update(len(data).to_bytes(4,'little')+data)
                    sim.process_frame(data);steps+=1
                    if phase=='income' and frame in (0,100,200,300,400,500,600):
                        current=sim.state();record['income']['samples'].append(dict(frame=frame,resources={str(k):v for k,v in current['resources'].items()},native_hash=current['canonical_fnv1a64']))
                    elif phase=='combat' and all(units.values()):
                        after=sim.state(include_entities=True)
                        for slot in (0,1):
                            key=str(slot);before=units[slot][0]
                            target=next((e for e in after['entities'] if e['id']==before['id']),None)
                            if key not in record['combat']['hits'] and target and target['current_damage']>before['current_damage']:
                                record['combat']['hits'][key]=dict(frame=frame,before=before,after=target,attacker=units[1-slot][0],
                                    live_units=[len(units[s]) for s in (0,1)],delta=target['current_damage']-before['current_damage'])
                        if len(record['combat']['hits'])==2:break
            require(sim.closed and native._runtime is None,'native world/runtime not closed')
            record[phase].update(closed=True,steps=steps,input_journal_sha256=journal.hexdigest())
        records[level]=record
    return records

def child(request):
    import importlib,sys,traceback
    request=json.loads(Path(request).read_bytes());package,assets,out=(Path(request[k]) for k in ('package','assets','output'))
    started=time.monotonic();report=dict(passed=False,game_started=False,AI_decisions_started=False,network_started=False)
    def sources():
        return {str(Path(module.__file__).resolve()):sha(Path(module.__file__)) for name,module in tuple(sys.modules.items())
                if name.startswith('server.') and getattr(module,'__file__',None)}
    try:
        for name in ('server.assets','server.bot_catalog','server.game_data','server.native_simulation'):importlib.import_module(name)
        report.update(driver_sha256=sha(Path(__file__)),asset_manifest_sha256=sha(assets/'asset-manifest.json'),source_sha256=sources())
        report['levels']=experiment(assets)
        from server.assets import verify_assets
        verify_assets(assets);report['source_sha256_at_finish']=sources()
        require(report['source_sha256']==report['source_sha256_at_finish'],'runtime sources changed')
        manifest=json.loads((package/'package-manifest.json').read_bytes())
        for name,digest in report['source_sha256'].items():
            path=Path(name);require(path.is_relative_to(package/'program/app'),'foreign runtime source')
            require(digest==manifest['files'][path.relative_to(package).as_posix()]['sha256'],'runtime source manifest differs')
        require(sha(assets/'asset-manifest.json')==report['asset_manifest_sha256'],'asset manifest changed')
        require(sha(Path(__file__))==report['driver_sha256'],'driver changed')
        report['checks']=assess(report['levels']);report['passed']=all(report['checks'].values())
    except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        report['elapsed_seconds']=time.monotonic()-started;(out/'child-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if report['passed'] else 1

def run(package,assets,output):
    from tools.package_integrity import verify
    from tools.owned_suspended_launch import SuspendedChild,job_accounting
    package,assets,output=(Path(value).resolve() for value in (package,assets,output))
    require(all(p.is_relative_to(ROOT/'local') for p in (package,assets,output)) and not output.is_relative_to(package) and
            not output.is_relative_to(assets),'separate owned local paths required')
    verify(package,'server');output.mkdir(exist_ok=False);started=time.monotonic();owner=None
    report=dict(passed=False,graphical_qualified=False,full_catalog_qualified=False)
    try:
        report.update(driver_sha256=sha(Path(__file__)),package_manifest_sha256=sha(package/'package-manifest.json'))
        request=dict(package=str(package),assets=str(assets),output=str(output));path=output/'request.json'
        path.write_text(json.dumps(request,indent=2)+'\n')
        owner=SuspendedChild.create([str(package/'program/runtime/python.exe'),'-I','-B',str(Path(__file__).resolve()),'--child',str(path)],
                                    cwd=output,creationflags=subprocess.CREATE_NO_WINDOW);owner.resume()
        while owner.poll() is None:
            if time.monotonic()-started>120:raise TimeoutError('owned strength experiment deadline')
            time.sleep(.02)
        report.update(exit_code=owner.returncode,child=json.loads((output/'child-report.json').read_bytes()),job_final=job_accounting(owner.job))
        verify(package,'server')
        report['passed']=owner.returncode==0 and report['child']['passed'] is True and report['job_final']['active_processes']==report['job_final']['total_terminated_processes']==0 and sha(Path(__file__))==report['driver_sha256']
    except BaseException as error:report['error']=repr(error)
    finally:
        if owner:owner.close();report['launch']=owner.receipt;report['passed'] &= not owner.receipt['forced_cleanup']
        report['elapsed_seconds']=time.monotonic()-started;(output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ('passed','exit_code','elapsed_seconds','error') if k in report}))
    return 0 if report['passed'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--child',type=Path)
    for field in ('package','assets','output'):parser.add_argument('--'+field,type=Path)
    args=parser.parse_args()
    if args.child:raise SystemExit(child(args.child))
    if not all((args.package,args.assets,args.output)):parser.error('--package, --assets and --output required')
    raise SystemExit(run(args.package,args.assets,args.output))
