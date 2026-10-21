"""Read-only Nody graph inventory; no inferred click/recovery success."""
import json

from tools.replay_signal_evidence import validate as signal_inventory
from tools.replay_binding_evidence import require


def validate(text):
    signal = signal_inventory(text)
    receivers = signal['binding_inventory']['inventory']['button_stream']['receivers']
    observed = [r for r in receivers if 'nody' in r]
    require(len(observed) == 1, 'one original Nody listener inventory required')
    receiver = observed[0]
    value = receiver['nody']
    require(value['listener'] == receiver['callback']['target'] and
            value['listener']['class'] == 'Doozy.Runtime.UIManager.Nodes.Listeners.UIButtonNodyListener' and
            receiver['callback']['method'] == 'ProcessSignal' and value['receiver_matches'] is True and
            type(value['connected']) is bool, 'Nody listener/receiver ownership differs')
    forward = value['forwarded']
    require(forward is not None and forward['target'] == value['node'] and
            forward['metadata_resolved'] is True and forward['method'] and
            type(forward['token']) is int and forward['token'] >> 24 == 6 and forward['parameters'] == 1,
            'forwarded callback does not own the recorded node')
    graph = value['graph']
    nodes = graph['nodes']
    require(isinstance(nodes, list) and 1 <= len(nodes) <= 128,
            'Nody graph inventory outside bound')
    require(len({n['object']['id'] for n in nodes}) == len(nodes) and
            len({n['node_id'] for n in nodes}) == len(nodes) and all(n['node_id'] for n in nodes),
            'duplicate/empty graph node identity')
    selected = [n for n in nodes if n['object'] == value['node']]
    require(len(selected) == 1 and selected[0]['graph_matches'] is True and
            selected[0]['graph_id'] == graph['graph_id'], 'callback node is not in its recorded graph')
    ports = {}
    selectors = []
    event_bindings = []
    for node in nodes:
        for direction in ('inputs', 'outputs'):
            require(isinstance(node[direction], list) and len(node[direction]) <= 32,
                    'Nody port list outside bound')
            for port in node[direction]:
                require(port['port_id'] and port['port_id'] not in ports and
                        port['node_id'] == node['node_id'] and isinstance(port['connections'], list) and
                        len(port['connections']) <= 32 and all(isinstance(c, str) for c in port['connections']),
                        'duplicate/foreign/incomplete graph port')
                ports[port['port_id']] = dict(node=node['node_id'], port=port)
                parsed = None
                if port['value']:
                    try:
                        parsed = json.loads(port['value'])
                    except (ValueError, TypeError):
                        pass
                if node is selected[0] and direction == 'outputs':
                    selectors.append(dict(port_id=port['port_id'], value_type=port['value_type'],
                                          raw_value=port['value'], parsed_value=parsed,
                                          connections=port['connections']))
        require(isinstance(node['events'], list) and len(node['events']) <= 32,
                'Nody event list outside bound')
        for action in node['events']:
            for call in (action.get('event') or {}).get('persistent') or []:
                event_bindings.append(dict(node_id=node['node_id'], node_name=node['name'],
                                           field=action['field'], call=call))
    unresolved = []
    links = []
    for port_id, item in ports.items():
        for destination in item['port']['connections']:
            target = ports.get(destination)
            if target is None:
                unresolved.append(dict(port_id=port_id, connection=destination))
            else:
                links.append(dict(source_node=item['node'], source_port=port_id,
                                  target_node=target['node'], target_port=destination))
    return dict(signal_inventory=signal, graph=graph, callback=forward, selected_node=selected[0],
                selected_node_active=graph['active_node'] == value['node'],
                output_selectors=selectors, port_links=links, unresolved_connections=unresolved,
                event_bindings=event_bindings, route_execution_qualified=False,
                healthy_replay_cancel_qualified=False, malformed_recovery_qualified=False)
