import copy
import unittest

from tests import test_replay_binding_evidence as fixture_module
from tools.replay_signal_evidence import validate


class ReplaySignalEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture = fixture_module.ReplayBindingEvidenceTests()
        fixture.setUp()
        self.fixture = fixture
        self.value = copy.deepcopy(fixture.value)
        self.value.update(signal_category='Game', signal_name='Quit', signal_custom=False)
        self.value['behaviours'][0]['event']['persistent'] = []
        self.callback = dict(id='500', target=dict(id='600', **{'class': 'Example.Target'}),
                             declaring_class='Example.Target', method='Receive', token=0x06000001,
                             parameters=1, metadata_resolved=True, delegates=[])
        self.value['button_stream'] = dict(
            stream=dict(id='700', **{'class': 'Doozy.Runtime.Signals.SignalStream'}),
            category='UISelectable', name='UIButton', signals_counter=0, global_callback=None,
            receivers=[dict(receiver=dict(id='800', **{'class': 'Doozy.Runtime.Signals.SignalReceiver'}),
                            typed=True, connected=True, disconnecting=False, stream_matches=True,
                            stream=dict(id='700', **{'class': 'Doozy.Runtime.Signals.SignalStream'}),
                            callback=self.callback)])

    def log(self):
        return self.fixture.log(self.value)

    def test_payload_identity_is_distinct_from_broadcast_stream(self):
        result = validate(self.log())
        self.assertEqual((result['payload_category'], result['payload_name']), ('Game', 'Quit'))
        self.assertEqual((result['stream_category'], result['stream_name']), ('UISelectable', 'UIButton'))
        self.assertEqual(result['callbacks'][0]['method'], 'Receive')
        self.assertFalse(result['route_execution_qualified'])

    def test_rejects_payload_as_stream_identity(self):
        self.value['button_stream'].update(category='Game', name='Quit')
        with self.assertRaises(AssertionError):
            validate(self.log())

    def test_records_connection_mismatch_and_rejects_duplicate_receiver(self):
        stream = self.value['button_stream']
        stream['receivers'][0]['connected'] = False
        result = validate(self.log())
        self.assertEqual(len(result['receiver_connection_mismatches']), 1)
        self.assertFalse(result['route_execution_qualified'])
        stream['receivers'][0]['connected'] = True
        stream['receivers'].append(copy.deepcopy(stream['receivers'][0]))
        with self.assertRaises(AssertionError):
            validate(self.log())

    def test_untyped_receiver_is_explicitly_unresolved(self):
        self.value['button_stream']['receivers'][0].update(typed=False, connected=None,
            disconnecting=None, stream=None, stream_matches=None, callback=None)
        result = validate(self.log())
        self.assertEqual(len(result['untyped_receivers']), 1)
        self.assertFalse(result['healthy_replay_cancel_qualified'])

    def test_rejects_unresolved_callback_mislabeled_as_resolved(self):
        self.callback['method'] = ''
        with self.assertRaises(AssertionError):
            validate(self.log())


if __name__ == '__main__':
    unittest.main()
