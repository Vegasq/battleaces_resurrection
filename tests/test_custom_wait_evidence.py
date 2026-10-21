"""Reject early-start,auto-fill and ownership mismatches in waiting Custom proof."""
from copy import deepcopy
import unittest

from server.community_protocol import START
from tools.custom_wait_evidence import validate


class CustomWaitEvidenceTests(unittest.TestCase):
    def fixture(self):
        lobby='a'*32;profiles=['p_one','p_two']
        log=(f'[1000] COMMUNITY OPEN HOLD waiting: lobby={lobby} members=1 phase=Open nativeIdle=1 minimumMs=31000 BA_RESURRECTION_CUSTOM_OPEN_HOLD_V2\n'
             f'[32000] COMMUNITY OPEN HOLD released: lobby={lobby} elapsedMs=31000 members=1 phase=Open nativeIdle=1 BA_RESURRECTION_CUSTOM_OPEN_HOLD_V2\n'
             '[32000] COMMUNITY MATCH SMOKE host native Start returned pending; round=0 (NOT manual UI input)\n')
        samples=[dict(perf_ns=t,lobby=lobby,phase=1,epoch=0,members=[profiles[0]],room=False,
                      workers=0,public_entries=0,public_offers=0) for t in (1_000_000_000,31_800_000_000)]
        players=[dict(slot=seat,profile=profile,ai_profile_id=0) for seat,profile in enumerate(profiles)]
        rosters=[dict(match=key*32,mode=1,players=deepcopy(players)) for key in ('b','c')]
        commands=[dict(kind=START,probe_perf_ns=t) for t in (32_000_000_000,60_000_000_000)]
        return [log,samples,rosters,commands,[32_000_000_005,60_000_000_005],profiles]

    def test_fully_ready_open_lobby_then_two_original_human_starts(self):
        result=validate(*self.fixture())
        self.assertEqual(result['native_elapsed_ms'],31000)
        self.assertEqual(result['server_sample_span_seconds'],30.8)
        self.assertTrue(result['all_ai_profiles_zero'])
        self.assertTrue(result['empty_seat_remained_empty'])

    def test_actual_windows_line_endings_keep_the_same_evidence(self):
        args=self.fixture()
        expected=validate(*args)
        args[0]=args[0].replace('\n','\r\n')
        self.assertEqual(validate(*args),expected)

    def test_native_and_live_waits_must_each_cover_the_required_period(self):
        for change in ('native_elapsed','native_ticks','live_span','start_before_release','missing_start'):
            with self.subTest(change=change):
                args=self.fixture()
                if change=='native_elapsed':args[0]=args[0].replace('elapsedMs=31000','elapsedMs=29999')
                if change=='native_ticks':args[0]=args[0].replace('[32000] COMMUNITY OPEN HOLD released','[1001] COMMUNITY OPEN HOLD released')
                if change=='live_span':args[1][-1]['perf_ns']=2_000_000_000
                if change=='start_before_release':args[0]=args[0].replace('[32000] COMMUNITY MATCH','[31000] COMMUNITY MATCH')
                if change=='missing_start':args[0]='\n'.join(args[0].splitlines()[:2])+'\n'
                with self.assertRaises(AssertionError):validate(*args)

    def test_any_waiting_lobby_ownership_or_activity_change_is_rejected(self):
        for key,value in (('lobby','d'*32),('phase',2),('epoch',1),('room',True),('workers',1),
                          ('public_entries',1),('public_offers',1),('members',['p_one','stranger']),
                          ('members',['p_one','p_two']),('members',['p_two']),('members',['p_one','p_one'])):
            with self.subTest(key=key,value=value):
                args=self.fixture();args[1][-1][key]=value
                with self.assertRaises(AssertionError):validate(*args)

    def test_bot_changed_human_or_wrong_match_mode_is_rejected(self):
        for change in ('bot','profile','extra_army','wrong_slots','mode','same_match'):
            with self.subTest(change=change):
                args=self.fixture();rosters=args[2]
                if change=='bot':rosters[0]['players'][1]['ai_profile_id']=18
                if change=='profile':rosters[1]['players'][1]['profile']='stranger'
                if change=='extra_army':rosters[0]['players'].append(dict(slot=2,profile='bot',ai_profile_id=59))
                if change=='wrong_slots':rosters[0]['players'][1]['slot']=0
                if change=='mode':rosters[0]['mode']=2
                if change=='same_match':rosters[1]['match']=rosters[0]['match']
                with self.assertRaises(AssertionError):validate(*args)

    def test_worker_or_start_before_observed_wait_settles_is_rejected(self):
        for change in ('early_worker','early_start','missing_worker','duplicate_sample'):
            with self.subTest(change=change):
                args=self.fixture()
                if change=='early_worker':args[4][0]=1
                if change=='early_start':args[3][0]['probe_perf_ns']=1
                if change=='missing_worker':args[4].pop()
                if change=='duplicate_sample':args[1].append(deepcopy(args[1][-1]))
                with self.assertRaises(AssertionError):validate(*args)


if __name__=='__main__':unittest.main()
