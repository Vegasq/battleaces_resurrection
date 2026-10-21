import json
import re
import unittest

from tests import test_replay_signal_evidence as fixture_module
from tools.replay_menu_evidence import validate, COMPLETE, BUTTON_COMPLETE
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


if __name__ == '__main__':
    unittest.main()
