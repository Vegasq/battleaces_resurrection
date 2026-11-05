"""Owned customized-profile failure/local-play/restart check using packaged play.

Copies an already qualified diagnostic profile, never a real player's profile.
Selected native lifetimes share that copy and installation-local hard preference.
The original installation preference is restored after the owned jobs exit.
No physical-input, full mode matrix, server-authentication or privacy claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tomllib
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]

PHASES = {
    'original': (('public-refused',1,'verified-refused'),
                 ('restart-practice-timeout',4,'verified-handshake-timeout')),
    'remaining': (('public1-timeout',1,'verified-handshake-timeout'),
                  ('public2-refused',2,'verified-refused'),
                  ('public2-timeout',2,'verified-handshake-timeout'),
                  ('public5-refused',5,'verified-refused'),
                  ('public5-timeout',5,'verified-handshake-timeout'),
                  ('practice-refused',4,'verified-refused')),
    'connect-timeout': (('public1-connect',1,'verified-connect-timeout'),
                        ('public2-connect',2,'verified-connect-timeout'),
                        ('public5-connect',5,'verified-connect-timeout'),
                        ('practice-connect',4,'verified-connect-timeout')),
}


def require(value,message):
    if not value:raise AssertionError(message)


def digest(raw):return hashlib.sha256(raw).hexdigest()


def decode_settings(raw):
    value=tomllib.loads(raw.decode('utf-8-sig'))
    deck=json.loads(value['account']['decks'])['SelectedDeck']
    units=[item['_id'] for item in deck['_units']]
    abilities=[item['_id'] for item in deck['_activeAbilities']]
    require(len(units)==8 and len(abilities)==4,'saved deck dimensions differ')
    require(all(type(v) is int and 0<v<=0xffffffff for v in units) and
            all(type(v) is int and 0<=v<=0xffffffff for v in abilities),'invalid saved deck identifiers')
    return value,dict(units=units,activeAbilityGroups=abilities)


def native_evidence(text,proof,expected,mode):
    require(type(mode) is int and mode in (1,2,4,5),'supported saved-profile mode required')
    require(all(proof.get(k) is True for k in ('passed','restored','writable','projection12')) and
            proof.get('read_error') is False and proof['state']==expected['cosmetics'],
            'native restored cosmetic state/projection differs')
    require(text.count('COSMETICS PERSISTENCE PROOF passed: slots=17 restored=1 writable=1 projection12=1')==1,
            'native cosmetic readback marker missing or duplicated')
    require(text.count('Practice difficulty initialized: selected=hard profile=19 source=saved;')==1,
            'hard preference was not loaded from saved installation state')
    require('Practice difficulty selected:' not in text,'diagnostic must not edit practice preference')
    armies=[json.loads(line.split('Practice army snapshot: ',1)[1]) for line in text.splitlines() if 'Practice army snapshot: ' in line]
    human=[army for army in armies if army.get('armyId',0)==0]
    require(len(human)==1,'one native human army required')
    human=human[0]
    require(all(human['deck'].get(k)==v for k,v in expected['deck'].items()),'native joined deck/abilities differ from saved selection')
    slots=expected['cosmetics']['slots']
    keys=[value for _,value in slots if value]
    require(human['deck'].get('entitlements')==[{'cosmeticAssetKeys':keys}],
            'native joined cosmetic entitlements differ from saved selection')
    roles=re.findall(r'Human cosmetic intent frozen: slots=17 items=(\d+) portrait=(\d+) banner=(\d+) catalog=([0-9a-f]{64}) synchronous=1',text)
    require(len(roles)==1,'one frozen native cosmetic intent required')
    count,portrait,banner,catalog=roles[0]
    require(int(count)==len(keys) and int(portrait)==human['portraitId'] and int(banner)==human['bannerId'] and
            catalog==expected['cosmetics']['catalog_sha256'],'frozen cosmetic roles/catalog differ from joined army')
    if mode==4:
        require(text.count('Practice difficulty snapshot: selected=hard modifierProfile=19 tuningProfile=19')==1,
                'Try Deck did not use saved hard difficulty')
    else:
        require(len(re.findall(r'Public AI difficulty snapshot: selected=(?:easy|normal|hard) modifierProfile=(?:17|18|19) practiceSelectionUnchanged=1',text))==1,
                'public random difficulty did not retain the practice choice')
    return dict(passed=True,mode=mode,deck=expected['deck'],cosmetic_slots=slots,
                native_cosmetic_projection=True,portrait=human['portraitId'],banner=human['bannerId'],
                saved_practice_difficulty='hard',practice_used_saved_difficulty=mode==4)


class SavedProfile:
    def __init__(self,game,profile,settings,cosmetics):
        self.profile=profile
        self.folder=game/'.battleaces-resurrection/profiles'/profile
        self.settings=settings
        self.table,self.deck=decode_settings(settings)
        self.cosmetics=dict(cosmetics,profile=profile)
        self.cosmetic_path=self.folder.with_name(profile+'.cosmetics.json')
        self.cosmetic_raw=(json.dumps(self.cosmetics,separators=(',',':'))+'\n').encode()
        self.practice=game/'.battleaces-resurrection/practice-settings.ini'
        self.practice_raw=b'schema=1\r\ndifficulty=hard\r\n'

    def seed(self):
        self.folder.mkdir(exist_ok=False)
        with (self.folder/'gameconfig-localuser.toml').open('xb') as stream:stream.write(self.settings)
        with self.cosmetic_path.open('xb') as stream:stream.write(self.cosmetic_raw)

    def check(self,game,output,pid,text,mode):
        current=(self.folder/'gameconfig-localuser.toml').read_bytes()
        require(decode_settings(current)[0]==self.table,'saved account/options changed during failure/play')
        require(self.cosmetic_path.read_bytes()==self.cosmetic_raw,'saved cosmetic file changed during failure/play')
        require(self.practice.read_bytes()==self.practice_raw,'saved practice file changed during failure/play')
        raw=(game/'investigation/runtime'/f'cosmetics-persistence-{pid}.json').read_bytes()
        proof=json.loads(raw)
        result=native_evidence(text,proof,dict(deck=self.deck,cosmetics=self.cosmetics),mode)
        (output/'cosmetics-persistence.json').write_bytes(raw)
        result.update(settings_sha256=digest(current),cosmetics_sha256=digest(self.cosmetic_raw),practice_sha256=digest(self.practice_raw),
                      account_and_options_preserved=True,cosmetics_bytes_preserved=True,practice_bytes_preserved=True)
        return result


def run(args):
    from tools import verify_packaged_play as play
    from tools.verify_owner_enrollment import restricting_sids_present
    game,package,output,seed_report=(p.resolve() for p in (args.game,args.package,args.output,args.seed_report))
    require(os.name=='nt' and not restricting_sids_present(),'normal Windows owner required before fixture writes')
    require(all(p.is_relative_to(ROOT/'local') for p in (game,package,output,seed_report)),'owned ignored inputs required')
    require(not output.exists(),'fresh output required')
    play.verify(package,'client');play.launcher.verify_game(game,community=True,bridge_version=2,unified=True,player_features=True)
    play.quit_probe.verify_build_receipt(game,args.helper_build_receipt.resolve())
    require((package/'program/client-helper/BattleAcesOffline.dll').read_bytes()==(game/'BattleAcesOffline.dll').read_bytes(),'packaged helper differs')
    ca=args.verified_ca.resolve()
    require(ca.is_relative_to(ROOT/'local'),'owned public CA required')
    play.launcher.tls.load_client_context(ca,'localhost')
    prior=json.loads(seed_report.read_bytes())
    require(prior['passed'] and prior['case']=='restart' and prior['forced_cleanup'] is False,'seed requires completed native profile restart')
    old_profile=prior['profile']
    require(re.fullmatch(r'nativestest_[a-z0-9_-]{1,34}',old_profile),'seed must be an owned diagnostic profile')
    old_game=Path(prior['config']['image']).resolve().parent
    require(old_game.is_relative_to(ROOT/'local') and old_game!=game,'seed must come from a separate owned copy')
    old_settings=old_game/'.battleaces-resurrection/profiles'/old_profile/'gameconfig-localuser.toml'
    old_cosmetics=old_settings.parent.with_name(old_profile+'.cosmetics.json')
    settings,cosmetic_raw=old_settings.read_bytes(),old_cosmetics.read_bytes()
    require(digest(settings)==prior['settings_after'] and digest(cosmetic_raw)==prior['cosmetic_after'],'qualified seed changed')
    cosmetics=json.loads(cosmetic_raw)
    require(cosmetics==prior['cosmetics-persistence']['state'] and prior['cosmetics-persistence']['restored'],'qualified cosmetics differ')
    require([slot for slot,_ in cosmetics['slots']]==list(range(1,18)),'all seventeen saved slots required')
    profile='nativestest_saved_'+secrets.token_hex(6)
    fixture=SavedProfile(game,profile,settings,cosmetics)
    require(not fixture.cosmetic_path.exists() and not fixture.folder.exists(),'fresh destination profile required')
    output.mkdir()
    phase_set=getattr(args,'phase_set','original')
    phases=PHASES[phase_set]
    report=dict(passed=False,scope=__doc__,phase_set=phase_set,profile=profile,game=str(game),seed_report_sha256=digest(seed_report.read_bytes()),
                seed_settings_sha256=digest(settings),seed_cosmetics_sha256=digest(cosmetic_raw),phases=[],
                authored_practice_preference='hard',source_sha256_at_start=play.sources())
    original=fixture.practice.read_bytes() if fixture.practice.exists() else None
    if original is not None:(output/'practice-before.ini').write_bytes(original)
    lock=game/'.battleaces-resurrection/saved-play.owner'
    acquired=changed=False
    try:
        with lock.open('x') as stream:stream.write(profile)
        acquired=True
        fixture.seed()
        # Replace only the disposable installation's preference, with an exact
        # backup. The same bytes remain installed across all native lifetimes.
        temporary=fixture.practice.with_name(profile+'.practice.tmp')
        with temporary.open('xb') as stream:stream.write(fixture.practice_raw)
        os.replace(temporary,fixture.practice);changed=True
        for index,(name,mode,state) in enumerate(phases):
            phase=output/name
            values=dict(vars(args),package=package,game=game,output=phase,mode=mode,connection_state=state,
                        rc_settings=False,expect_long_replay=False,native_replay_readback=False,native_replay_faults=False,
                        replay_retention=0,saved_preferences=fixture,visible=False,timeout=300)
            print('Saved-preference phase: '+name,flush=True)
            code=play.run(SimpleNamespace(**values))
            path=phase/'verification.json';value=json.loads(path.read_bytes())
            report['phases'].append(dict(name=name,report_sha256=digest(path.read_bytes()),passed=value['passed']))
            require(code==0 and value['passed'] and value['saved_preferences']['passed'] and value['natural_quit'] and
                    not value['forced_cleanup'] and value['driver_reaped'] and value['game_reaped'],'saved-preference phase failed')
            require(value['job_before_close']==dict(total_processes=2,active_processes=0,total_terminated_processes=0),'owned job not naturally empty')
            require(value['prior_replays_preserved'],'earlier replay changed')
            if index+1<len(phases):
                trace=fixture.folder/'quit-trace.jsonl'
                require(trace.read_bytes()==(phase/'quit-trace.jsonl').read_bytes(),'completed Quit trace differs')
                trace.rename(phase/'completed-profile-quit-trace.jsonl')
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
    finally:
        if changed:
            try:
                require(fixture.practice.read_bytes()==fixture.practice_raw,'preference changed unexpectedly; do not overwrite it')
                if original is None:fixture.practice.unlink()
                else:
                    restore=fixture.practice.with_name(profile+'.restore.tmp')
                    with restore.open('xb') as stream:stream.write(original)
                    os.replace(restore,fixture.practice)
                report['installation_preference_restored']=(fixture.practice.read_bytes() if fixture.practice.exists() else None)==original
            except BaseException as error:report.update(passed=False,restore_error=repr(error))
        if acquired:
            require(lock.read_text()==profile,'owned preference lock changed')
            lock.unlink()
        report['seed_files_unchanged']=old_settings.read_bytes()==settings and old_cosmetics.read_bytes()==cosmetic_raw
        report['source_files_unchanged']=play.sources()==report['source_sha256_at_start']
        report['passed'] &= report.get('installation_preference_restored',False) and report['seed_files_unchanged'] and report['source_files_unchanged']
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('passed','installation_preference_restored','seed_files_unchanged','error') if k in report}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('package','game','output','shared-settings','helper-build-receipt','verified-ca','seed-report'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase-set',choices=tuple(PHASES),default='original',
                        help='remaining completes190; connect-timeout qualifies pending TCP separately from TLS stall')
    raise SystemExit(run(parser.parse_args()))
