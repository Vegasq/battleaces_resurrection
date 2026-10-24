"""Meaningful refusal controls for native crashes mistaken for valid evidence."""
import copy
import unittest
from tools.frida_crash_control import build_source
from tools.native_crash_evidence import FAULT, validate_control

SHA = 'a' * 64
CONFIG = dict(image=r'C:\owned\native_crash_control.exe', runId='b'*32, pid=17, mainThread=19)


def fixture():
    rows = '\n'.join(f'{kind} pid=17 thread=19 mainThread=19 code={code} errorMode={mode}'
                     for kind, code, mode in [('before-mode', 0, 1), ('ready', 0, 3),
                                              ('native-invoke', 0, 3), ('original-filter', FAULT, 3)])+'\n'
    report = dict(passed=True, target_sha256=SHA, config=CONFIG.copy(), os_error_mode_changed=True,
                  exception_filter_replaced_by_probe=False, game_started=False,
                  source_before={str(i): SHA for i in range(4)}, source_after={str(i): SHA for i in range(4)},
                  launch=dict(pid=17, tid=19, resume_previous_count=1, forced_cleanup=False,
                              owned_process_reaped=True, exit_code=FAULT), exit_code=FAULT, native_log=rows,
                  tracker=dict(complete=True, errors=[], final_accounting=dict(total=1, active=0, terminated=0),
                               records=[dict(pid=17, image=CONFIG['image'], image_sha256=SHA, in_owned_job=True,
                                             creation_filetime=1, exit=dict(wait_signaled=True, exit_code=FAULT, exit_filetime=2))]))
    data = [dict(mainThread=19, handlerReplaced=False, errorModeChangedByObserver=False, targetApisInvoked=False),
            dict(target='CrashControlInvoke', nativeCaller=True, mainThread=19),
            dict(code=FAULT, flags=0, count=0, nullArguments=True)]
    messages = [dict(type='send', payload=dict(schema=1, seq=i, runId=CONFIG['runId'], pid=17,
                                             thread=19, kind=kind, data=value))
                for i, (kind, value) in enumerate(zip(('control-ready', 'trigger', 'raise-entry'), data), 1)]
    final = dict(structuredContent=dict(operation='frida_session_status', normalized_result=dict(
        pid=17, mode='attach', state='detached', messages_truncated=False, messages=messages)))
    return report, final


class NativeCrashControlTests(unittest.TestCase):
    def test_complete_control_does_not_claim_game_qualification(self):
        result = validate_control(*fixture(), expected_target_sha256=SHA)
        self.assertTrue(result['passed'])
        self.assertFalse(result['game_crash_qualified'])
        self.assertFalse(result['full_privacy_qualified'])

    def test_natural_exit_alone_is_insufficient(self):
        for marker in ('before-mode', 'ready', 'native-invoke', 'original-filter'):
            report, final = fixture()
            report['native_log'] = '\n'.join(row for row in report['native_log'].splitlines() if not row.startswith(marker+' '))
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                validate_control(report, final, expected_target_sha256=SHA)

    def test_harness_force_reporter_child_changed_mode_or_thread_refuses(self):
        changes = [lambda r: r['launch'].__setitem__('forced_cleanup', True),
                   lambda r: r['launch'].__setitem__('resume_previous_count', True),
                   lambda r: r.__setitem__('exit_code', 1),
                   lambda r: r['tracker']['final_accounting'].__setitem__('total', 2),
                   lambda r: r['tracker']['final_accounting'].__setitem__('total', True),
                   lambda r: r['tracker']['records'].append(copy.deepcopy(r['tracker']['records'][0])),
                   lambda r: r['tracker']['records'][0].__setitem__('image_sha256', 'c'*64),
                   lambda r: r.__setitem__('native_log', r['native_log'].replace('errorMode=3', 'errorMode=2')),
                   lambda r: r.__setitem__('native_log', r['native_log'].replace('thread=19', 'thread=20')),
                   lambda r: r['source_after'].__setitem__('0', 'c'*64)]
        for change in changes:
            report, final = fixture(); change(report)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_control(report, final, expected_target_sha256=SHA)

    def test_observer_fault_intervention_truncation_and_js_caller_refuse(self):
        changes = [lambda v: v.__setitem__('messages_truncated', True),
                   lambda v: v.__setitem__('state', 'running'),
                   lambda v: v['messages'].pop(),
                   lambda v: v['messages'][1]['payload']['data'].__setitem__('nativeCaller', False),
                   lambda v: v['messages'][0]['payload']['data'].__setitem__('targetApisInvoked', True),
                   lambda v: v['messages'][2]['payload']['data'].__setitem__('code', 1),
                   lambda v: v['messages'][2]['payload']['data'].__setitem__('flags', False),
                   lambda v: v['messages'][1]['payload']['data'].__setitem__('nativeCaller', 1),
                   lambda v: v['messages'][2]['payload'].__setitem__('thread', 20),
                   lambda v: v['messages'][2]['payload'].__setitem__('seq', True)]
        for change in changes:
            report, final = fixture(); change(final['structuredContent']['normalized_result'])
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_control(report, final, expected_target_sha256=SHA)

    def test_source_is_passive_and_identity_bounded(self):
        source = build_source(CONFIG)
        self.assertNotIn('new NativeFunction', source)
        self.assertNotIn('Interceptor.replace', source)
        self.assertNotIn('setExceptionHandler', source)
        for key, value in [('image', r'C:\other\game.exe'), ('pid', True), ('mainThread', 0), ('runId', 'x')]:
            config = dict(CONFIG); config[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): build_source(config)


if __name__ == '__main__':
    unittest.main()
