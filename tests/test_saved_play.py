"""Reject false saved-choice evidence without invoking a proprietary runtime."""
import copy
import json
import unittest
from tools.verify_saved_play import decode_settings, native_evidence, PHASES


class SavedPlayEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.expected=dict(deck=dict(units=list(range(21,29)),activeAbilityGroups=[2,0,0,0]),
            cosmetics=dict(schema=1,build=37822,profile='nativestest_authored',catalog_sha256='a'*64,
                           slots=[[slot,100+slot if slot<15 else 0] for slot in range(1,18)]))
        self.proof=dict(passed=True,restored=True,writable=True,projection12=True,read_error=False,state=self.expected['cosmetics'])
        self.army=dict(deck=dict(self.expected['deck'],entitlements=[dict(cosmeticAssetKeys=list(range(101,115)))]),
                       portraitId=106,bannerId=107)

    def text(self,mode=4,army=None):
        return '\n'.join([
            'COSMETICS PERSISTENCE PROOF passed: slots=17 restored=1 writable=1 projection12=1',
            'Practice difficulty initialized: selected=hard profile=19 source=saved;',
            'Human cosmetic intent frozen: slots=17 items=14 portrait=106 banner=107 catalog='+'a'*64+' synchronous=1',
            'Practice army snapshot: '+json.dumps(self.army if army is None else army),
            ('Practice difficulty snapshot: selected=hard modifierProfile=19 tuningProfile=19' if mode==4 else
             'Public AI difficulty snapshot: selected=easy modifierProfile=17 practiceSelectionUnchanged=1')])

    def test_actual_choices_are_required_in_both_distinct_mode_paths(self):
        for mode in (1,2,4,5):
            result=native_evidence(self.text(mode),self.proof,self.expected,mode)
            self.assertTrue(result['passed'])
            self.assertEqual(result['practice_used_saved_difficulty'],mode==4)

    def test_remaining_cases_complete_matrix_without_repeating190(self):
        original={(mode,state) for _,mode,state in PHASES['original']}
        remaining={(mode,state) for _,mode,state in PHASES['remaining']}
        self.assertEqual(len(original),2)
        self.assertEqual(len(remaining),6)
        self.assertFalse(original & remaining)
        self.assertEqual(original | remaining,{(mode,state) for mode in (1,2,4,5)
            for state in ('verified-refused','verified-handshake-timeout')})

    def test_tcp_deadline_is_a_separate_four_mode_matrix(self):
        cases=PHASES['connect-timeout']
        self.assertEqual(len(cases),4)
        self.assertEqual({(mode,state) for _,mode,state in cases},
                         {(mode,'verified-connect-timeout') for mode in (1,2,4,5)})
        self.assertFalse({name for name,_,_ in cases} &
                         {name for phase in ('original','remaining') for name,_,_ in PHASES[phase]})

    def test_unsupported_mode_and_public_preference_loss_rejected(self):
        for mode in (True,0,3,6):
            with self.subTest(mode=mode),self.assertRaises(AssertionError):
                native_evidence(self.text(),self.proof,self.expected,mode)
        for mode in (2,5):
            with self.subTest(mode=mode),self.assertRaises(AssertionError):
                native_evidence(self.text(mode).replace('practiceSelectionUnchanged=1','practiceSelectionUnchanged=0'),
                                self.proof,self.expected,mode)

    def test_default_or_overridden_preference_cannot_qualify_saved_choice(self):
        for old,new in [('source=saved','source=default'),('source=saved','source=override'),
                        ('modifierProfile=19','modifierProfile=18'),('selected=hard','selected=normal')]:
            with self.subTest(new=new),self.assertRaises(AssertionError):
                native_evidence(self.text().replace(old,new),self.proof,self.expected,4)
        with self.assertRaises(AssertionError):
            native_evidence(self.text()+'\nPractice difficulty selected: hard',self.proof,self.expected,4)

    def test_unchanged_files_do_not_substitute_for_native_selected_values(self):
        for field in ('units','activeAbilityGroups','entitlements'):
            bad=copy.deepcopy(self.army)
            if field=='entitlements':bad['deck'][field][0]['cosmeticAssetKeys'][0]=999
            else:bad['deck'][field][0]=999
            with self.subTest(field=field),self.assertRaises(AssertionError):
                native_evidence(self.text(army=bad),self.proof,self.expected,4)
        bad=copy.deepcopy(self.army);bad['portraitId']=999
        with self.assertRaises(AssertionError):native_evidence(self.text(army=bad),self.proof,self.expected,4)

    def test_stale_or_failed_cosmetic_restore_is_rejected(self):
        for field,value in [('passed',False),('restored',False),('writable',False),('projection12',False),('read_error',True)]:
            with self.subTest(field=field),self.assertRaises(AssertionError):
                native_evidence(self.text(),dict(self.proof,**{field:value}),self.expected,4)
        bad=copy.deepcopy(self.proof);bad['state']['profile']='nativestest_other'
        with self.assertRaises(AssertionError):native_evidence(self.text(),bad,self.expected,4)
        with self.assertRaises(AssertionError):native_evidence(self.text()+'\n'+self.text(),self.proof,self.expected,4)

    def test_saved_settings_reject_boolean_and_incomplete_deck(self):
        def encoded(units):
            deck=dict(SelectedDeck=dict(_units=[dict(_id=x) for x in units],_activeAbilities=[dict(_id=x) for x in (2,0,0,0)]))
            return ('[account]\ndecks = '+json.dumps(json.dumps(deck))+'\n').encode()
        self.assertEqual(decode_settings(encoded(range(21,29)))[1],self.expected['deck'])
        for units in ([True]*8,list(range(21,28)),[0]*8):
            with self.assertRaises(AssertionError):decode_settings(encoded(units))
