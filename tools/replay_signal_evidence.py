"""Read existing UIButton broadcast subscribers; payload ID is not stream ID."""
from tools.replay_binding_evidence import validate as binding_inventory, require


def validate(text):
    result = binding_inventory(text)
    stream = result['inventory'].get('button_stream')
    require(isinstance(stream, dict) and stream['category'] == 'UISelectable' and
            stream['name'] == 'UIButton' and
            stream['stream']['class'] == 'Doozy.Runtime.Signals.SignalStream' and
            type(stream['signals_counter']) is int and stream['signals_counter'] >= 0,
            'original UIButton broadcast stream identity missing')
    receivers = stream['receivers']
    require(isinstance(receivers, list) and len(receivers) <= 32 and
            len({r['receiver']['id'] for r in receivers}) == len(receivers),
            'receiver inventory outside bound/duplicate')
    callbacks = []
    unresolved = []

    def callback(value, depth=0):
        if value is None:
            return
        require(depth < 4 and isinstance(value['delegates'], list) and len(value['delegates']) <= 32,
                'delegate tree outside bound')
        if value['metadata_resolved'] is True:
            require(bool(value['method']) and bool(value['declaring_class']) and
                    type(value['token']) is int and value['token'] >> 24 == 6 and
                    type(value['parameters']) is int and value['parameters'] >= 0,
                    'callback metadata identity incomplete')
            callbacks.append({key: value[key] for key in
                              ('target', 'declaring_class', 'method', 'token', 'parameters')})
        else:
            require(value['metadata_resolved'] is False and value['method'] == '' and
                    value['declaring_class'] == '' and value['token'] == 0 and value['parameters'] == -1,
                    'unresolved callback mislabeled')
            unresolved.append(value['id'])
        for child in value['delegates']:
            callback(child, depth+1)

    callback(stream['global_callback'])
    untyped = []
    connection_mismatches = []
    for entry in receivers:
        if entry['typed'] is True:
            require(type(entry['connected']) is bool and type(entry['disconnecting']) is bool and
                    type(entry['stream_matches']) is bool and
                    entry['stream_matches'] == (entry['stream']['id'] == stream['stream']['id']) and
                    entry['receiver']['class'] == 'Doozy.Runtime.Signals.SignalReceiver',
                    'typed receiver fields/class incomplete')
            if not entry['connected'] or not entry['stream_matches'] or entry['disconnecting']:
                connection_mismatches.append({key: entry[key] for key in
                                              ('receiver', 'stream', 'connected', 'stream_matches', 'disconnecting')})
            callback(entry['callback'])
        else:
            require(entry['typed'] is False and all(entry[key] is None for key in
                    ('connected', 'disconnecting', 'stream', 'stream_matches', 'callback')),
                    'unreviewed receiver incorrectly claims a decoded callback')
            untyped.append(entry['receiver'])
    return dict(binding_inventory=result, payload_category=result['inventory']['signal_category'],
                payload_name=result['inventory']['signal_name'], stream_category=stream['category'],
                stream_name=stream['name'], receivers=len(receivers), callbacks=callbacks,
                unresolved_delegates=unresolved, untyped_receivers=untyped,
                receiver_connection_mismatches=connection_mismatches,
                route_execution_qualified=False, healthy_replay_cancel_qualified=False,
                malformed_recovery_qualified=False)
