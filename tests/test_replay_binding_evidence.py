import copy
import json
import unittest

from tools.replay_binding_evidence import validate


class ReplayBindingEvidenceTests(unittest.TestCase):
    def setUp(self):
        controller = dict(id='100', **{'class': 'Uncapped.ConcedeFlowUIController'})
        self.value = dict(controller=controller,
                          button=dict(id='200', **{'class': 'Doozy.Runtime.UIManager.Components.UIButton'}),
                          initialized=True, active=False, path='InGame/Options/LeaveReplay',
                          behaviours=[dict(id='300', kind=7, selectable='200', runners=[],
                                           event=dict(persistent=[dict(target=controller,
                                                                      method='ReplayEndGame',
                                                                      method_name_present=True,
                                                                      mode=1, state=2)],
                                                      runtime=[], compiled_persistent=[], executing=[]))])

    def log(self, value=None):
        return '[1] REPLAY BINDING inventory: '+json.dumps(value or self.value)+'\n'+(
            '[2] REPLAY BINDING inventory passed: version=1 phase=healthy-practice '
            'worldStable=1 fsmStable=1 bindingsStable=1 clicks=0 behavioursAdded=0 '
            'eventRebuilds=0 rootsReleasedOnReturn=1\n')

    def test_retains_binding_and_does_not_claim_recovery(self):
        result = validate(self.log())
        self.assertEqual(result['original_replay_endgame_binding']['behaviour'], 7)
        self.assertFalse(result['healthy_replay_cancel_qualified'])
        self.assertFalse(result['malformed_recovery_qualified'])

    def test_rejects_other_controller_and_disabled_callback(self):
        for key, value in [('target', dict(id='999', **{'class': 'Uncapped.ConcedeFlowUIController'})),
                           ('method_name_present', False), ('state', 0), ('mode', 0)]:
            changed = copy.deepcopy(self.value)
            changed['behaviours'][0]['event']['persistent'][0][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate(self.log(changed))

    def test_rejects_duplicate_and_foreign_behaviour(self):
        changed = copy.deepcopy(self.value)
        changed['behaviours'].append(copy.deepcopy(changed['behaviours'][0]))
        with self.assertRaises(AssertionError):
            validate(self.log(changed))
        changed['behaviours'].pop()
        changed['behaviours'][0]['selectable'] = '999'
        with self.assertRaises(AssertionError):
            validate(self.log(changed))

    def test_reports_secondary_routes_without_claiming_they_ran(self):
        self.value['behaviours'][0]['runners'] = [{'action': 'OtherAction'}]
        self.value['behaviours'][0]['event']['runtime'] = [{'id': '400', 'class': 'RuntimeDelegate'}]
        result = validate(self.log())
        self.assertEqual((result['runner_count'], result['runtime_listener_count']), (1, 1))
        self.assertEqual(result['clicks'], 0)

    def test_signal_only_inventory_is_a_finding_not_a_click_proof(self):
        self.value['behaviours'][0]['event']['persistent'] = []
        self.value.update(signal_category='Game', signal_name='Quit', signal_custom=False)
        result = validate(self.log())
        self.assertIsNone(result['original_replay_endgame_binding'])
        self.assertFalse(result['signal_receivers_qualified'])
        self.assertFalse(result['healthy_replay_cancel_qualified'])

    def test_rejects_missing_mutating_or_failed_observation(self):
        for text in [self.log().splitlines()[0], self.log().replace('clicks=0', 'clicks=1'),
                     self.log()+'[3] Replay binding inventory failed: changed\n', self.log()+self.log()]:
            with self.subTest(text=text[-80:]), self.assertRaises(AssertionError):
                validate(text)


if __name__ == '__main__':
    unittest.main()
