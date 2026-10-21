"""Authored native-log fixtures; no installed game data or recovered names."""
from copy import deepcopy
import json
import unittest

from tools.public_profile_evidence import validate


class PublicProfileEvidenceTests(unittest.TestCase):
    def fixture(self,mode=2):
        key='a'*32;count=2 if mode==1 else 4
        expected=[dict(match=key,mode=mode,army=seat,player=seat+1,profile=0 if seat==0 else 500+seat,
            name='Fixture Player '+str(seat),portrait=900+seat,banner=950+seat,units=list(range(100+10*seat,108+10*seat)))
            for seat in range(count)]
        lines=[]
        def add(text):lines.append('['+str(len(lines)+1)+'] '+text)
        for value in expected:add('REMOTE PROFILE expected: '+json.dumps(value))
        add(f'REMOTE PROFILE proof armed: match={key} players={count} BA_RESURRECTION_REMOTE_PROFILE_V1')
        add(f'Public native match joined: ticket=1 match={key} mode={mode} participants={count} seat=0 remoteWorld=1')
        add('REMOTE PROFILE loading: '+json.dumps(dict(match=key,mode=mode,signal_mode=mode,view_mode=mode,
            front_owned=True,live=True,original_screen=True,profile_roster_present=False)))
        for value in expected:add('REMOTE PROFILE native: '+json.dumps(dict(value,loading_active=False,simulation_owned=True,match_data_owned=True)))
        add('Practice native EndOfGameResponse delivered; winner=1')
        results=[]
        for value in reversed(expected):
            actual={key:item for key,item in value.items() if key!='profile'}
            actual.update(displayed=value['name']+' (Alias)',is_ai=value['profile']!=0,
                portrait_children=2,banner_children=2,front_owned=True,live=True)
            results.append(actual);add('REMOTE PROFILE result: '+json.dumps(actual))
        add(f'REMOTE PROFILE results complete: match={key} players={count} originalGetters=1 liveChildren=1')
        add(f'Public result Continue routed: mode={mode} source=remote next=End')
        add(f'Public native return: ticket=1 match={key} aborted=0 nativeIdle=1')
        add(f'REMOTE PROFILE observer retired: match={key} rootedOwners=0')
        return '\n'.join(lines)+'\n',key,mode,expected,results

    def test_all_public_modes_and_windows_line_endings(self):
        for mode in (1,2,5):
            for newline in ('\n','\r\n'):
                with self.subTest(mode=mode,newline=newline):
                    log,key,mode,expected,_=self.fixture(mode)
                    result=validate(log.replace('\n',newline),key,mode,expected)
                    self.assertTrue(result['original_result_models'])
                    self.assertEqual(result['bots'],len(expected)-1)
                    self.assertFalse(result['artwork_or_physical_qualified'])

    def test_changed_original_result_identity_avatar_deck_or_owner_is_rejected(self):
        for field,value in (('name','Other'),('displayed','Practice Bot'),('player',9000),('mode',4),
            ('portrait',0),('banner',0),('units',list(range(8))),('is_ai',False),('is_ai',1),
            ('portrait_children',0),('banner_children',False),('front_owned',False),('live',False)):
            with self.subTest(field=field,value=value):
                log,key,mode,expected,results=self.fixture();before=results[0];after=deepcopy(before);after[field]=value
                log=log.replace('REMOTE PROFILE result: '+json.dumps(before),'REMOTE PROFILE result: '+json.dumps(after))
                with self.assertRaises(AssertionError):validate(log,key,mode,expected)

    def test_missing_duplicate_or_foreign_result_model_is_rejected(self):
        for change in ('missing','duplicate','foreign'):
            with self.subTest(change=change):
                log,key,mode,expected,results=self.fixture()
                line=next(row for row in log.splitlines() if 'REMOTE PROFILE result: '+json.dumps(results[0]) in row)
                if change=='missing':log=log.replace(line+'\n','')
                if change=='duplicate':log+=line+'\n'
                if change=='foreign':log=log.replace('REMOTE PROFILE result: '+json.dumps(results[0]),
                    'REMOTE PROFILE result: '+json.dumps(dict(results[0],match='b'*32)))
                with self.assertRaises(AssertionError):validate(log,key,mode,expected)

    def test_bootstrap_difference_or_early_continue_is_rejected(self):
        for change in ('frozen_name','missing_retirement','early_continue','client_error','fallback'):
            with self.subTest(change=change):
                log,key,mode,expected,_=self.fixture()
                if change=='frozen_name':expected[0]['name']='Different authoritative name'
                if change=='missing_retirement':log=log.replace('REMOTE PROFILE observer retired:','OTHER retired:')
                if change=='early_continue':
                    lines=log.splitlines();line=next(row for row in lines if 'Public result Continue routed:' in row)
                    lines.remove(line);lines.insert(0,line);log='\n'.join(lines)+'\n'
                if change=='client_error':log+='[100] Public client failure: owned probe failed\n'
                if change=='fallback':log+='[100] Public fallback accepted: ticket=1\n'
                with self.assertRaises(AssertionError):validate(log,key,mode,expected)

    def test_loading_and_original_native_roster_are_required_separately(self):
        for change in ('missing_loading','wrong_signal','invented_loading_roster','missing_native','stale_native','altered_native'):
            with self.subTest(change=change):
                log,key,mode,expected,_=self.fixture()
                if change=='missing_loading':log='\n'.join(row for row in log.splitlines() if 'REMOTE PROFILE loading:' not in row)+'\n'
                if change=='wrong_signal':log=log.replace('"signal_mode": 2','"signal_mode": 4')
                if change=='invented_loading_roster':log=log.replace('"profile_roster_present": false','"profile_roster_present": true')
                if change=='missing_native':log='\n'.join(row for row in log.splitlines() if 'REMOTE PROFILE native:' not in row)+'\n'
                if change=='stale_native':log=log.replace('"simulation_owned": true','"simulation_owned": false')
                if change=='altered_native':
                    before=dict(expected[0],loading_active=False,simulation_owned=True,match_data_owned=True)
                    log=log.replace('REMOTE PROFILE native: '+json.dumps(before),'REMOTE PROFILE native: '+json.dumps(dict(before,name='Different')))
                with self.assertRaises(AssertionError):validate(log,key,mode,expected)


if __name__=='__main__':unittest.main()
