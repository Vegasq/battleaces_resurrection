import copy
import unittest

from tests import test_replay_signal_evidence as fixture_module
from tools.replay_nody_evidence import validate


class ReplayNodyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ReplaySignalEvidenceTests()
        self.fixture.setUp()
        self.value = self.fixture.value
        receiver = self.value['button_stream']['receivers'][0]
        listener = dict(id='900', **{'class': 'Doozy.Runtime.UIManager.Nodes.Listeners.UIButtonNodyListener'})
        receiver['callback'].update(target=listener, method='ProcessSignal')
        node = dict(id='1000', **{'class': 'Uncapped.UI.ShowUIObjectNode'})
        graph = dict(object=dict(id='1100', **{'class': 'Doozy.Runtime.Nody.FlowGraph'}),
                     graph_id='graph1', active_node=node,
                     nodes=[dict(object=node, node_id='n1', graph_id='graph1', graph_matches=True,
                                 name='Current', inputs=[], outputs=[
                                     dict(node_id='n1', port_id='p1', connections=['p2'],
                                          value_type='OriginalCondition', value='{"category":"Game","name":"Quit"}')],
                                 events=[]),
                            dict(object=dict(id='1200', **{'class': 'Example.EventNode'}),
                                 node_id='n2', graph_id='graph1', graph_matches=False, name='Exit',
                                 inputs=[dict(node_id='n2', port_id='p2', connections=['p1'],
                                              value_type='', value='')], outputs=[], events=[])])
        forward = copy.deepcopy(receiver['callback'])
        forward.update(target=node, method='OnUIButtonSignal')
        self.nody = dict(listener=listener, receiver_matches=True, connected=True, node=node,
                         forwarded=forward, graph=graph)
        receiver['nody'] = self.nody

    def log(self):
        return self.fixture.log()

    def test_records_conditions_and_links_without_executing_route(self):
        result = validate(self.log())
        self.assertTrue(result['selected_node_active'])
        self.assertEqual(result['output_selectors'][0]['parsed_value']['name'], 'Quit')
        self.assertEqual(len(result['port_links']), 2)
        self.assertFalse(result['route_execution_qualified'])
        self.assertFalse(result['healthy_replay_cancel_qualified'])

    def test_rejects_other_forward_target(self):
        self.nody['forwarded']['target'] = dict(id='999', **{'class': 'Example.Other'})
        with self.assertRaises(AssertionError):
            validate(self.log())

    def test_rejects_duplicate_and_foreign_port(self):
        node = self.nody['graph']['nodes'][0]
        node['outputs'].append(copy.deepcopy(node['outputs'][0]))
        with self.assertRaises(AssertionError):
            validate(self.log())
        node['outputs'].pop()
        node['outputs'][0]['node_id'] = 'other'
        with self.assertRaises(AssertionError):
            validate(self.log())

    def test_unresolved_links_remain_explicit(self):
        self.nody['graph']['nodes'][0]['outputs'][0]['connections'] = ['external']
        result = validate(self.log())
        self.assertEqual(result['unresolved_connections'], [dict(port_id='p1', connection='external')])
        self.assertFalse(result['route_execution_qualified'])

    def test_inactive_node_is_not_reported_as_active(self):
        self.nody['graph']['active_node'] = dict(id='1200', **{'class': 'Example.EventNode'})
        self.assertFalse(validate(self.log())['selected_node_active'])


if __name__ == '__main__':
    unittest.main()
