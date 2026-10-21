"""Strict reader for an opt-in, read-only original replay-button inventory.

A healthy practice world supplies the loaded original controller and hidden
replay button. This proves its retained bindings, not replay entry, a click,
healthy replay cancellation, malformed recovery, or rendered UI acceptance.
"""
import json
import re


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def validate(text):
    records = re.findall(r'^\[\d+\] REPLAY BINDING inventory: (.+)$', text, re.M)
    passed = re.findall(r'^\[\d+\] REPLAY BINDING inventory passed: version=1 '
                        r'phase=healthy-practice worldStable=1 fsmStable=1 bindingsStable=1 '
                        r'clicks=0 behavioursAdded=0 eventRebuilds=0 rootsReleasedOnReturn=1$', text, re.M)
    require(len(records) == len(passed) == 1 and 'Replay binding inventory failed:' not in text,
            'one complete unchanged replay binding inventory required')
    value = json.loads(records[0])
    require(value['controller']['class'] == 'Uncapped.ConcedeFlowUIController' and
            value['button']['class'] == 'Doozy.Runtime.UIManager.Components.UIButton' and
            value['controller']['id'] != value['button']['id'] and
            all(re.fullmatch(r'[1-9][0-9]*', value[key]['id']) for key in ('controller', 'button')) and
            value['initialized'] is True and value['active'] is False and
            isinstance(value['path'], str) and 0 < len(value['path']) <= 32768,
            'original initialized hidden replay button identity missing')
    behaviours = value['behaviours']
    require(isinstance(behaviours, list) and 1 <= len(behaviours) <= 32,
            'original behaviour inventory missing/outside bound')
    require(len({b['id'] for b in behaviours}) == len(behaviours), 'duplicate behaviour entry')
    bindings = []
    runtime_count = runner_count = 0
    for behaviour in behaviours:
        require(behaviour['selectable'] == value['button']['id'] and type(behaviour['kind']) is int,
                'behaviour belongs to another button')
        runners = behaviour['runners']
        require(runners is None or isinstance(runners, list) and len(runners) <= 32,
                'runner inventory outside bound')
        runner_count += len(runners or [])
        event = behaviour['event']
        if event is None:
            continue
        for name in ('persistent', 'runtime', 'compiled_persistent', 'executing'):
            require(event[name] is None or isinstance(event[name], list) and len(event[name]) <= 32,
                    'event list outside bound')
        runtime_count += len(event['runtime'] or [])
        for call in event['persistent'] or []:
            if call['method'] != 'ReplayEndGame':
                continue
            require(call['target'] == value['controller'] and call['method_name_present'] is True and
                    call['mode'] == 1 and call['state'] == 2,
                    'ReplayEndGame target/method/mode/state differs')
            bindings.append({'behaviour': behaviour['kind'], 'method': call['method']})
    require(len(bindings) <= 1, 'duplicate retained original ReplayEndGame bindings')
    return dict(original_replay_endgame_binding=bindings[0] if bindings else None, inventory=value,
                runtime_listener_count=runtime_count, runner_count=runner_count,
                clicks=0, bindings_unchanged=True, world_unchanged=True,
                signal_receivers_qualified=False,
                healthy_replay_cancel_qualified=False, malformed_recovery_qualified=False)
