"""Authored provider fixtures: no runtime instrumentation, target files or sockets."""
from copy import deepcopy
import ast
import hashlib
import json
import unittest

from tools.frida_control_source import build_source, build_request
from tools.verify_frida_control import REQUIRED, verify

IMAGE = 'R:\\owned\\python.exe'
SHA = hashlib.sha256(build_source(IMAGE).encode('utf-8')).hexdigest()
RUN = 'f' * 32
POSITIVE = dict(schema=1, pid=123, run_id=RUN, passed=True, bytes_sent=4, bytes_received=2)


def fixture():
    installed = [dict(key=key, offset='0x1234') for key in sorted(REQUIRED)]
    def message(kind, counts, elapsed):
        return dict(script_id='one', type='send', payload=dict(schema=1, pid=123, kind=kind,
            counts=counts, installed=installed, errors=[], loaded=['ws2_32.dll'], elapsedMs=elapsed))
    counts = {key: 0 for key in REQUIRED}
    ready = message('observer-ready', counts, 0)
    calls = message('heartbeat', {key: 1 for key in REQUIRED}, 100)
    normalized = dict(mode='spawn', device_id='local', target=IMAGE, pid=123, session_id='session-one', source_kind='file',
        source_path='R:\\owned\\observer.js', source_sha256=SHA, state='detached', cleanup_error=None,
        messages_truncated=False, scripts=[dict(script_id='one')], messages=[ready, calls])
    arguments=build_request(IMAGE,'R:\\owned',RUN)
    parameters={key:deepcopy(arguments[key]) for key in ('mode','device_id','program','argv')}
    parameters['session_id']='session-one'
    return dict(inputs=dict(schema=1,run_id=RUN,target_sha256='c'*64,script_sha256=SHA),arguments=arguments,
        result=dict(structuredContent=dict(operation='instrument_with_frida',
            predicate_type='rea.frida.instrumentation-observation', provider=dict(id='frida'),
            confidence='observed', evidence_id='ev_' + 'b' * 64, normalized_result=normalized,
            subject=None, environment=None, parameters=parameters)))


def check(value, positive=POSITIVE):
    return verify(value, script_sha256=SHA, target_path=IMAGE, target_sha256='c' * 64, run_id=RUN, positive=positive)


class FridaControlTests(unittest.TestCase):
    def test_complete_control_is_bounded_and_does_not_promote_identity_or_exit(self):
        result = check(fixture())
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['last_message_elapsed_ms'], 100)
        self.assertFalse(result['provider_artifact_identity_reported'])
        self.assertFalse(result['provider_environment_reported'])
        self.assertFalse(result['process_exit_or_descendant_cleanup_qualified'])
        self.assertEqual(result['observed_counts_lower_bounds'], {key: 1 for key in REQUIRED})

    def test_missing_positive_receipt_or_traffic_fails(self):
        for receipt in ({}, None, dict(passed=True, bytes_sent=True, bytes_received=2),
                        dict(passed=True, bytes_sent=4, bytes_received=0)):
            with self.subTest(receipt=receipt):self.assertFalse(check(fixture(), receipt)['passed'])
        value = fixture()
        value['result']['structuredContent']['normalized_result']['messages'][1]['payload']['counts']['ws2_32.dll:connect'] = 0
        self.assertFalse(check(value)['passed'])
        for key, wrong in (('pid',124), ('run_id','e'*32), ('schema',True)):
            receipt = POSITIVE.copy();receipt[key] = wrong
            with self.subTest(key=key):self.assertFalse(check(fixture(),receipt)['passed'])

    def test_partial_unattached_or_failed_hooks_cannot_be_zero_coverage(self):
        for case in ('missing_counter', 'missing_hook', 'hook_error', 'no_ready', 'script_error', 'wrong_script', 'wrong_pid'):
            value = fixture()
            messages = value['result']['structuredContent']['normalized_result']['messages']
            row = messages[1]['payload']
            if case == 'missing_counter':row['counts'].pop('ws2_32.dll:recv')
            elif case == 'missing_hook':row['installed'] = row['installed'][:-1]
            elif case == 'hook_error':row['errors'] = ['attach failed']
            elif case == 'no_ready':messages.pop(0)
            elif case == 'script_error':messages[1]['type'] = 'error'
            elif case == 'wrong_script':messages[1]['script_id'] = 'other'
            elif case == 'wrong_pid':row['pid'] = 124
            with self.subTest(case=case):self.assertFalse(check(value)['passed'])

    def test_late_mixed_decreasing_or_invalid_samples_fail(self):
        for case in ('decreased', 'disappeared', 'negative', 'bool', 'saturated', 'time', 'duplicate_hook', 'duplicate_ready'):
            value = fixture()
            messages = value['result']['structuredContent']['normalized_result']['messages']
            later = deepcopy(messages[-1]);later['payload']['elapsedMs'] = 200;messages.append(later)
            row = later['payload']
            if case == 'decreased':row['counts']['ws2_32.dll:send'] = 0
            elif case == 'disappeared':row['counts'].pop('ws2_32.dll:send');row['installed'] = row['installed'][:-1]
            elif case == 'negative':row['counts']['ws2_32.dll:send'] = -1
            elif case == 'bool':row['counts']['ws2_32.dll:send'] = True
            elif case == 'saturated':row['counts']['ws2_32.dll:send'] = 2**53 - 1
            elif case == 'time':row['elapsedMs'] = 1
            elif case == 'duplicate_hook':row['installed'].append(deepcopy(row['installed'][0]))
            elif case == 'duplicate_ready':row['kind'] = 'observer-ready'
            with self.subTest(case=case):self.assertFalse(check(value)['passed'])

    def test_provider_target_source_and_cleanup_bindings(self):
        mutations = [('source_sha256', 'd' * 64), ('messages_truncated', True), ('cleanup_error', 'detach failed'),
                     ('state', 'running'), ('device_id', 'remote'), ('target', 'R:\\other.exe')]
        for key, replacement in mutations:
            value = fixture();value['result']['structuredContent']['normalized_result'][key] = replacement
            with self.subTest(key=key):self.assertFalse(check(value)['passed'])
        value = fixture();value['arguments']['argv'].insert(0, IMAGE)
        self.assertFalse(check(value)['passed'])
        value = fixture();value['inputs']['target_sha256'] = 'd'*64
        self.assertFalse(check(value)['passed'])
        value = fixture();value.pop('inputs')
        self.assertFalse(check(value)['passed'])
        self.assertFalse(check(dict(result=dict(isError=True)))['passed'])

    def test_provider_parameters_and_canonical_body_are_bound(self):
        for key, wrong in (('mode','attach'),('device_id','remote'),('program','R:\\other.exe'),
                           ('argv',['different program']),('session_id','other-session')):
            value=fixture();value['result']['structuredContent']['parameters'][key]=wrong
            with self.subTest(key=key):self.assertFalse(check(value)['passed'])
        value=fixture();value['arguments']['argv'][3]='pass'
        value['result']['structuredContent']['parameters']['argv']=value['arguments']['argv'].copy()
        self.assertFalse(check(value)['passed'])
        value=fixture();value['result']['structuredContent']['normalized_result']['session_id']=None
        value['result']['structuredContent']['parameters']['session_id']=None
        self.assertFalse(check(value)['passed'])

    def test_empty_script_negative_time_and_changed_hook_location_are_rejected(self):
        for case in ('empty_script','negative_time','changed_offset'):
            value=fixture();n=value['result']['structuredContent']['normalized_result']
            if case=='empty_script':
                n['scripts'][0]['script_id']=None
                for message in n['messages']:message['script_id']=None
            elif case=='negative_time':n['messages'][0]['payload']['elapsedMs']=-1
            else:
                n['messages'][1]['payload']['installed']=deepcopy(n['messages'][1]['payload']['installed'])
                n['messages'][1]['payload']['installed'][0]['offset']='0x4321'
            with self.subTest(case=case):self.assertFalse(check(value)['passed'])

    def test_input_configuration_is_strict(self):
        for sha in ('A' * 64, 'not a hash', None):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                verify({}, script_sha256=sha, target_path=IMAGE, target_sha256=SHA, run_id=RUN, positive={})
        for path in ('relative.exe', '/tmp/target', None):
            with self.subTest(path=path), self.assertRaises(ValueError):
                verify({}, script_sha256=SHA, target_path=path, target_sha256=SHA, run_id=RUN, positive={})
        for invalid in (None,'short','F'*32):
            with self.subTest(run=invalid), self.assertRaises(ValueError):
                verify({}, script_sha256=SHA, target_path=IMAGE, target_sha256=SHA, run_id=invalid, positive={})

    def test_generated_configuration_is_data_and_has_no_native_game_hooks(self):
        path = 'R:\\owned\\quoted"\\python.exe'
        source = build_source(path)
        line = next(line for line in source.splitlines() if line.startswith('const config = '))
        self.assertEqual(json.loads(line[len('const config = '):-1]), dict(image=path, native={}))
        for invalid in ('relative.exe', 'R:\\owned\\bad\n.exe', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):build_source(invalid)

    def test_control_request_keeps_paths_as_literals_and_omits_executable_from_argv(self):
        folder='R:\\owned space\\quoted"\\new control'
        request=build_request(IMAGE,folder,RUN)
        self.assertEqual(request['program'],IMAGE)
        self.assertEqual(request['argv'][:3],['-I','-B','-c'])
        self.assertEqual(len(request['argv']),4)
        parsed=ast.parse(request['argv'][3])
        root_assignment=parsed.body[1]
        self.assertEqual(root_assignment.value.args[0].value,folder)
        self.assertEqual(request['duration_ms'],10000)
        for invalid in (None,'short','F'*32):
            with self.subTest(run=invalid),self.assertRaises(ValueError):build_request(IMAGE,folder,invalid)


if __name__ == '__main__':unittest.main()
