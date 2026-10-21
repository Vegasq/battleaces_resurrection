import json
import re
import unittest

from tests import test_replay_signal_evidence as fixture_module
from tools.replay_menu_evidence import validate, COMPLETE, BUTTON_COMPLETE, CANCEL_COMPLETE, INVALID_COMPLETE, SEMANTIC_COMPLETE, PARTIAL_COMPLETE
from tools.replay_binding_evidence import validate as binding


class ReplayMenuEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture = fixture_module.ReplaySignalEvidenceTests()
        fixture.setUp()
        fixture.value['active_self'] = True
        self.binding = fixture.log().replace('phase=healthy-practice', 'phase=healthy-replay')
        self.replay = dict(input_action_messages=100, game_data_sha256='a'*64)
        self.text = ('[0] NATIVE REPLAY MENU load dispatch: profile=nativestest_replayui_0123456789ab '
                     'mainMenu=1 worldIdle=1 originalLoadReplayFromFile=1 extraPlayCalls=0 fsmWrites=0 helperTicks=0\n'
                     '[1] NATIVE REPLAY MENU loaded: frames=100 gameDataSha256='+'a'*64+
                     ' loadReturned=1 originalPlayInternal=1\n'
                     '[2] Original replay runner update restored: primaryIntegration=1 originalPredicate=1 helperTicks=0\n'+self.binding+
                     '[3] NATIVE REPLAY MENU in-game: world=10 presented=30 originalMainFsm=1 practiceActive=0 frames=100\n'
                     '[4] NATIVE REPLAY MENU exit API dispatch: originalReplayEndGame=1 buttonClicks=0 fsmWrites=0 helperTicks=0\n'
                     '[5] NATIVE REPLAY MENU exit API returned: originalCallbackReturned=1\n'
                     '[6] '+COMPLETE+'\n')

    def test_api_control_does_not_claim_a_bound_button_or_disk_ui(self):
        result = validate(self.text, self.replay)
        self.assertTrue(result['original_file_load_and_internal_play'])
        self.assertTrue(result['original_exit_api'])
        self.assertFalse(result['bound_button_exit_qualified'])
        self.assertFalse(result['user_exposed_disk_selection_qualified'])

    def test_replay_phase_is_not_satisfied_by_practice_marker(self):
        with self.assertRaises(AssertionError):
            validate(self.text.replace('phase=healthy-replay', 'phase=healthy-practice'), self.replay)
        with self.assertRaises(AssertionError):
            binding(self.binding)

    def test_requires_the_production_runner_without_its_failure(self):
        for text in (self.text.replace('Original replay runner update restored:', 'not a runner:'),
                     self.text+'Original replay runner update failed: original runner missing\n'):
            with self.subTest(text=text[-90:]), self.assertRaises(AssertionError):
                validate(text, self.replay)

    def test_rejects_wrong_record_or_nonadvancing_presentation(self):
        for text in (self.text.replace('presented=30', 'presented=0'),
                     self.text.replace('gameDataSha256='+'a'*64, 'gameDataSha256='+'b'*64),
                     self.text.replace('loaded: frames=100', 'loaded: frames=101')):
            self.assertNotEqual(text, self.text)
            with self.subTest(text=text[-80:]), self.assertRaises(AssertionError):
                validate(text, self.replay)

    def test_rejects_extra_play_batch_or_practice(self):
        for text in (self.text.replace('extraPlayCalls=0', 'extraPlayCalls=1'),
                     self.text+'NATIVE REPLAY playback armed:', self.text+'Practice requested:'):
            with self.subTest(text=text[-80:]), self.assertRaises(AssertionError):
                validate(text, self.replay)

    def test_rejects_missing_or_repeated_exit_api_boundary(self):
        for text in (self.text.replace(COMPLETE, ''), self.text+'[7] '+COMPLETE,
                     self.text+'Native replay menu control failed: owner changed'):
            with self.subTest(text=text[-80:]), self.assertRaises(AssertionError):
                validate(text, self.replay)

    def button_text(self):
        value=json.loads(re.search(r'REPLAY BINDING inventory: (.+)',self.binding)[1])
        value['active']=True
        opened='[4] NATIVE REPLAY BUTTON options dispatch: originalTryShowOptionsConcedeView=1 buttonInitiallyHidden=1 fsmWrites=0\n'
        visible='[5] NATIVE REPLAY BUTTON visible inventory: '+json.dumps(value)+'\n'
        show=dict(id='301',**{'class':'Uncapped.UI.ShowUIObjectComponent'})
        view=dict(id='302',**{'class':'Doozy.Runtime.UIManager.Containers.UIView'})
        def call(target,method):return dict(target=target,method=method,method_name_present=True,state=2,mode=1)
        authored=dict(binder=dict(id='300',**{'class':'Uncapped.BindUISelectableToInputAction'}),
                     same_game_object=True,show=show,view=view,
                     click_event=dict(persistent=[call(show,'Show'),call(view,'Hide')],runtime=[]),
                     confirm_event=dict(persistent=[call(value['controller'],'ReplayEndGame')],runtime=[]))
        binding='[6] NATIVE REPLAY BUTTON authored binding: '+json.dumps(authored)+'\n'
        dispatch='[7] NATIVE REPLAY BUTTON authored dispatch: originalBindClickButton=1 active=1 interactable=1 originalExitApi=0 buttonClicks=1 fsmWrites=0 helperTicks=0\n'
        prefix=self.text[:self.text.index('[4] NATIVE REPLAY MENU exit API dispatch:')]
        confirm='[8] NATIVE REPLAY BUTTON confirmation dispatch: originalModalOnConfirm=1 currentNavigation=1 nativeModel=1 persistentReplayEndGame=1 originalExitApi=0 fsmWrites=0 helperTicks=0\n'
        return prefix+opened+visible+binding+dispatch+confirm+'[9] NATIVE REPLAY BUTTON authored returned: originalCallbackReturned=1\n[10] '+BUTTON_COMPLETE+'\n'

    def test_visible_button_route_is_distinct_from_api_and_physical_input(self):
        text=self.button_text()
        result=validate(text,self.replay,button_exit=True)
        self.assertTrue(result['bound_button_exit_qualified'])
        self.assertTrue(result['original_options_opened'])
        self.assertFalse(result['original_exit_api'])
        self.assertFalse(result['physical_ui_input_qualified'])
        with self.assertRaises(AssertionError):validate(text,self.replay)
        with self.assertRaises(AssertionError):validate(self.text,self.replay,button_exit=True)

    def test_button_control_rejects_hidden_foreign_or_cleanup_routes(self):
        text=self.button_text()
        for bad in (text.replace('"active": true','"active": false'),
                    text.replace('"initialized": true','"initialized": false'),
                    text.replace('"signal_name": "Quit"','"signal_name": "Other"'),
                    text+'NATIVE REPLAY BUTTON failure cleanup: originalExitApiReturned=1 successUnclaimed=1\n',
                    text+'NATIVE REPLAY MENU exit API dispatch: injected\n',
                    text.replace('originalTryShowOptionsConcedeView=1','originalTryShowOptionsConcedeView=0')):
            self.assertNotEqual(text,bad)
            with self.subTest(text=bad[-100:]), self.assertRaises(AssertionError):
                validate(bad,self.replay,button_exit=True)

    def test_authored_exit_requires_existing_active_serialized_binding(self):
        text=self.button_text()
        for bad in (text.replace('"same_game_object": true','"same_game_object": false'),
                    text.replace('"method": "ReplayEndGame"','"method": "Other"'),
                    text.replace('"state": 2','"state": 0'),
                    text.replace('"method_name_present": true','"method_name_present": false'),
                    text.replace('"method": "Hide"','"method": "Show"'),
                    text.replace('"mode": 1','"mode": 0'),
                    text.replace('"runtime": []','"runtime": [{}]'),
                    text.replace('originalModalOnConfirm=1','originalModalOnConfirm=0')):
            self.assertNotEqual(text,bad)
            with self.subTest(text=bad[-100:]), self.assertRaises(AssertionError):
                validate(bad,self.replay,button_exit=True)

    def cancel_text(self):
        text=self.button_text()
        start=text.index('[4] NATIVE REPLAY BUTTON options dispatch:')
        confirm=text.index('[8] NATIVE REPLAY BUTTON confirmation dispatch:')
        cycle=text[start:confirm]
        cancel=('[8] NATIVE REPLAY BUTTON cancel dispatch: originalModalOnCancel=1 currentNavigation=1 '
                'emptyCancelEvent=1 closeOnCancel=1 world=10 presented=36 originalExitApi=0 fsmWrites=0 helperTicks=0\n'
                '[9] NATIVE REPLAY BUTTON cancel returned: originalCallbackReturned=1\n'
                '[10] NATIVE REPLAY BUTTON cancel settled: world=10 presentedBefore=36 presentedAfter=40 '
                'sameReplay=1 nativeRelease=1 navigationCount=0 optionsHidden=1 fsmWrites=0 helperTicks=0\n')
        return text[:start]+cycle+cancel+cycle+text[confirm:].replace(BUTTON_COMPLETE,CANCEL_COMPLETE)

    def test_cancel_requires_same_replay_progress_then_fresh_original_leave_confirm(self):
        result=validate(self.cancel_text(),self.replay,button_exit=True,cancel_first=True)
        self.assertTrue(result['confirmation_cancel_qualified'])
        self.assertEqual(result['button_clicks'],2)
        self.assertFalse(result['physical_ui_input_qualified'])
        self.assertFalse(result['malformed_recovery_qualified'])
        with self.assertRaises(AssertionError):validate(self.button_text(),self.replay,button_exit=True,cancel_first=True)
        with self.assertRaises(AssertionError):validate(self.cancel_text(),self.replay,button_exit=True)

    def test_cancel_rejects_world_replacement_stalled_playback_or_missing_release(self):
        text=self.cancel_text()
        for before,after in [('cancel settled: world=10','cancel settled: world=11'),
                             ('presentedAfter=40','presentedAfter=36'),
                             ('presentedBefore=36','presentedBefore=35'),
                             ('nativeRelease=1','nativeRelease=0'),
                             ('emptyCancelEvent=1','emptyCancelEvent=0'),
                             ('originalModalOnCancel=1','originalModalOnCancel=0'),
                             ('navigationCount=0','navigationCount=1')]:
            with self.subTest(before=before),self.assertRaises(AssertionError):
                validate(text.replace(before,after),self.replay,button_exit=True,cancel_first=True)

    def test_cancel_cannot_follow_the_second_leave_or_use_only_one_leave(self):
        text=self.cancel_text()
        first=text.index('[4] NATIVE REPLAY BUTTON options dispatch:')
        second=text.index('[4] NATIVE REPLAY BUTTON options dispatch:',first+1)
        end=text.index('[8] NATIVE REPLAY BUTTON confirmation dispatch:')
        cancel=text.index('[8] NATIVE REPLAY BUTTON cancel dispatch:')
        late=text[:cancel]+text[second:end]+text[cancel:second]+text[end:]
        with self.assertRaises(AssertionError):validate(late,self.replay,button_exit=True,cancel_first=True)
        with self.assertRaises(AssertionError):
            validate(text[:second]+text[end:],self.replay,button_exit=True,cancel_first=True)

    def invalid_text(self):
        invalid=('[0] NATIVE REPLAY INVALID dispatch: case=invalid-deflate-07 bytes=1 mainMenu=1 worldIdle=1 '
                 'originalLoadReplayFromFile=1 fsmWrites=0 helperTicks=0\n'
                 '[1] NATIVE REPLAY INVALID refused: originalLoadReturned=0 originalStopCalls=0 fsmWrites=0 helperTicks=0\n'
                 '[2] NATIVE REPLAY INVALID settled: sameOwner=1 mainMenu=1 worldIdle=1 decodedDataAbsent=1 '
                 'navigationCount=0 filePinReleased=1 originalFileReleased=1 originalStopCalls=0 fsmWrites=0 helperTicks=0\n')
        return invalid+self.cancel_text().replace(CANCEL_COMPLETE,INVALID_COMPLETE)

    def test_invalid_deflate_refusal_is_scoped_and_requires_subsequent_healthy_playback(self):
        text=self.invalid_text()
        result=validate(text,self.replay,button_exit=True,cancel_first=True,invalid_first=True)
        self.assertTrue(result['invalid_deflate_refusal_qualified'])
        self.assertTrue(result['confirmation_cancel_qualified'])
        self.assertFalse(result['malformed_recovery_qualified'])
        self.assertFalse(result['physical_ui_input_qualified'])
        with self.assertRaises(AssertionError):validate(self.cancel_text(),self.replay,button_exit=True,cancel_first=True,invalid_first=True)
        with self.assertRaises(AssertionError):validate(text,self.replay,button_exit=True,cancel_first=True)

    def test_invalid_refusal_rejects_changed_owner_retained_data_or_unreleased_file(self):
        text=self.invalid_text()
        for before,after in [('case=invalid-deflate-07','case=other'),('originalLoadReturned=0','originalLoadReturned=1'),
                             ('sameOwner=1','sameOwner=0'),('decodedDataAbsent=1','decodedDataAbsent=0'),
                             ('originalFileReleased=1','originalFileReleased=0'),('originalStopCalls=0','originalStopCalls=1')]:
            with self.subTest(before=before),self.assertRaises(AssertionError):
                validate(text.replace(before,after),self.replay,button_exit=True,cancel_first=True,invalid_first=True)

    def test_invalid_refusal_must_precede_the_healthy_load_and_cannot_replace_it(self):
        text=self.invalid_text();load=text.index('[0] NATIVE REPLAY MENU load dispatch:')
        with self.assertRaises(AssertionError):
            validate(text[load:]+text[:load],self.replay,button_exit=True,cancel_first=True,invalid_first=True)
        with self.assertRaises(AssertionError):
            validate(text[:load]+INVALID_COMPLETE,self.replay,button_exit=True,cancel_first=True,invalid_first=True)

    def semantic_text(self):
        text=self.invalid_text();offset=text.index('[0] NATIVE REPLAY MENU load dispatch:')
        semantic=''
        for name,size in (('empty-replay',2),('missing-game-config',4)):
            semantic+=(f'[3] NATIVE REPLAY SEMANTIC dispatch: case={name} bytes={size} mainMenu=1 worldIdle=1 '
                       'originalLoadReplayFromFile=1 fsmWrites=0 helperTicks=0\n'
                       f'[4] NATIVE REPLAY SEMANTIC refused: case={name} originalLoadReturned=0 originalStopCalls=0 fsmWrites=0 helperTicks=0\n'
                       f'[5] NATIVE REPLAY SEMANTIC settled: case={name} sameOwner=1 mainMenu=1 worldIdle=1 decodedDataAbsent=1 '
                       'navigationCount=0 originalFileReleased=1 originalStopCalls=0 fsmWrites=0 helperTicks=0\n')
        return (text[:offset]+semantic+text[offset:]).replace(INVALID_COMPLETE,SEMANTIC_COMPLETE)

    def test_semantic_refusals_are_two_named_cases_not_all_malformed_recovery(self):
        result=validate(self.semantic_text(),self.replay,button_exit=True,cancel_first=True,invalid_first=True,semantic_first=True)
        self.assertEqual(result['semantic_refusal_cases'],['empty-replay','missing-game-config'])
        self.assertFalse(result['malformed_recovery_qualified'])
        self.assertFalse(result['physical_ui_input_qualified'])
        with self.assertRaises(AssertionError):validate(self.invalid_text(),self.replay,button_exit=True,cancel_first=True,invalid_first=True,semantic_first=True)
        with self.assertRaises(AssertionError):validate(self.semantic_text(),self.replay,button_exit=True,cancel_first=True,invalid_first=True)

    def test_semantic_refusals_require_both_actual_refusals_and_native_cleanup(self):
        text=self.semantic_text()
        for before,after in [('case=missing-game-config','case=empty-replay'),('case=empty-replay bytes=2','case=empty-replay bytes=4'),
                             ('SEMANTIC refused: case=empty-replay originalLoadReturned=0','SEMANTIC refused: case=empty-replay originalLoadReturned=1'),
                             ('decodedDataAbsent=1','decodedDataAbsent=0'),('originalFileReleased=1','originalFileReleased=0')]:
            with self.subTest(before=before),self.assertRaises(AssertionError):
                validate(text.replace(before,after),self.replay,button_exit=True,cancel_first=True,invalid_first=True,semantic_first=True)

    def test_semantic_cases_must_settle_before_next_case_and_healthy_load(self):
        text=self.semantic_text();begin=text.index('[3] NATIVE REPLAY SEMANTIC dispatch:')
        middle=text.index('[3] NATIVE REPLAY SEMANTIC dispatch:',begin+1)
        end=text.index('[0] NATIVE REPLAY MENU load dispatch:')
        reordered=text[:begin]+text[middle:end]+text[begin:middle]+text[end:]
        with self.assertRaises(AssertionError):
            validate(reordered,self.replay,button_exit=True,cancel_first=True,invalid_first=True,semantic_first=True)
        with self.assertRaises(AssertionError):
            validate(text[:begin]+text[end:],self.replay,button_exit=True,cancel_first=True,invalid_first=True,semantic_first=True)

    def partial_text(self):
        partial=('[0] NATIVE REPLAY PARTIAL dispatch: case=missing-version-build mainMenu=1 worldIdle=1 originalLoadReplayFromFile=1 fsmWrites=0 helperTicks=0\n'
                 '[1] NATIVE REPLAY PARTIAL accepted: originalLoadReturned=1 decodedDataApplied=1 missingVersionBuild=1 originalPlayInternal=1 fsmWrites=0 helperTicks=0\n'
                 '[2] Original replay runner update failed: replay reader managed invocation failed\n'
                 '[3] NATIVE REPLAY PARTIAL failure observed: sameOwner=1 mainMenu=1 worldIdle=1 decodedDataRetained=1 originalRunnerFailures=1 sameDataRetries=0 originalFileReleased=1 originalStopCalls=0 fsmWrites=0 helperTicks=0\n')
        healthy=self.cancel_text().replace(CANCEL_COMPLETE,PARTIAL_COMPLETE)
        healthy=healthy.replace('[2] Original replay runner update restored:',
            '[2] Original replay runner recovery allowed: sameOwner=1 newDecodedData=1 fsmWrites=0 helperTicks=0\n[2] Original replay runner update restored:')
        return partial+healthy

    def test_partial_recovery_requires_one_actual_failure_then_healthy_replacement(self):
        result=validate(self.partial_text(),self.replay,button_exit=True,cancel_first=True,partial_first=True)
        self.assertTrue(result['partial_initialization_replacement_qualified'])
        self.assertFalse(result['malformed_recovery_qualified'])
        self.assertFalse(result['physical_ui_input_qualified'])
        with self.assertRaises(AssertionError):validate(self.cancel_text(),self.replay,button_exit=True,cancel_first=True,partial_first=True)
        with self.assertRaises(AssertionError):validate(self.partial_text(),self.replay,button_exit=True,cancel_first=True)

    def test_partial_recovery_rejects_retrying_same_bad_data_or_helper_stop(self):
        text=self.partial_text()
        for before,after in [('newDecodedData=1','newDecodedData=0'),('sameDataRetries=0','sameDataRetries=1'),
                             ('decodedDataRetained=1','decodedDataRetained=0'),('originalStopCalls=0','originalStopCalls=1')]:
            with self.subTest(before=before),self.assertRaises(AssertionError):
                validate(text.replace(before,after),self.replay,button_exit=True,cancel_first=True,partial_first=True)

    def test_partial_recovery_cannot_hide_additional_or_unrecovered_pump_failures(self):
        text=self.partial_text()
        with self.assertRaises(AssertionError):
            validate(text+'Original replay runner update failed: another\n',self.replay,button_exit=True,cancel_first=True,partial_first=True)
        with self.assertRaises(AssertionError):
            validate(text.replace('Original replay runner recovery allowed:','not recovery:'),self.replay,button_exit=True,cancel_first=True,partial_first=True)


if __name__ == '__main__':
    unittest.main()
