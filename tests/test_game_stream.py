"""Synthetic persistent-record failure controls; no target launches or assets."""
import copy
import hashlib
import json
import unittest

from tests.test_game_observation import fixture
from tools.verify_game_stream import practice_anchor, stream


def response(value):
    return dict(structuredContent=value, content=[dict(type='text', text=json.dumps(value))])


def sync(call):
    call['result'] = response(call['result']['structuredContent'])


def records():
    old, rows, source, config = fixture()
    heartbeat = copy.deepcopy(rows[0]); heartbeat.update(kind='heartbeat', elapsedMs=5000)
    rows.insert(1, heartbeat)
    for i, row in enumerate(rows, 1):
        row['sequence'] = i
    rows[-2]['elapsedMs'] = 6000; rows[-1]['elapsedMs'] = 6001
    start = dict(arguments=dict(mode='attach', device_id='local', pid=1234), result=response(dict(
        session_id='s', mode='attach', device_id='local', pid=1234,
        state='running', target='Battle Aces.exe (pid 1234)')))
    def ev(operation, value):
        return dict(evidence_id='ev_'+'a'*64, confidence='observed', provider=dict(id='frida'),
            operation=operation, predicate_type='rea.frida.instrumentation-observation',
            parameters=dict(session_id='s'), normalized_result=value)
    def messages(values):
        return [dict(type='send', script_id='one', payload=copy.deepcopy(row)) for row in values]
    load = dict(arguments=dict(session_id='s', source_kind='file', path='Z:\\owned\\window\\observer.js'),
        result=response(ev('load_frida_script', dict(script_id='one', source_kind='file',
            source_path='Z:\\owned\\window\\observer.js', source_sha256=hashlib.sha256(source).hexdigest(),
            messages_truncated=False, messages=messages(rows[:1])))))
    statuses = []
    for state, values in [('running', rows[:2]), ('detached', rows)]:
        statuses.append(dict(arguments=dict(session_id='s'), result=response(ev('frida_session_status', dict(
            session_id='s', pid=1234, device_id='local', mode='attach', state=state,
            target='Battle Aces.exe (pid 1234)', scripts=[dict(script_id='one', name='rea-one')],
            messages_truncated=False, messages=messages(values))))))
    close = dict(arguments=dict(session_id='s'), result=response(dict(target_state='unknown')))
    return [start, load, statuses, close, rows, source, config]


class StreamTests(unittest.TestCase):
    def check(self, data):
        return stream(*data, pid=1234, quit_thread=77)

    def test_single_script_pass_has_explicit_limits(self):
        result = self.check(records())
        self.assertEqual(result['max_heartbeat_gap_ms'], 4999)
        self.assertTrue(result['single_script_ready_through_destroy'])
        self.assertFalse(result['continuous_lifecycle_coverage'])
        self.assertFalse(result['analytics_removal_qualified'])
        self.assertEqual(result['trailing_journal_rows'], 0)

    def test_provider_and_session_failures(self):
        cases = (
            lambda d: d[0]['arguments'].update(device_id='remote'),
            lambda d: d[0]['result']['structuredContent'].update(pid=4321),
            lambda d: d[1]['arguments'].update(session_id='other'),
            lambda d: d[1]['result']['structuredContent'].update(operation='instrument_with_frida'),
            lambda d: d[1]['result']['structuredContent'].update(confidence='inferred'),
            lambda d: d[1]['result']['structuredContent'].update(evidence_id='arbitrary'),
            lambda d: d[1]['result']['structuredContent']['normalized_result'].update(source_sha256='b'*64),
            lambda d: d[1]['result']['structuredContent']['normalized_result'].update(messages_truncated=True),
            lambda d: d[2][0]['arguments'].update(session_id='other'),
            lambda d: d[2][0]['result']['structuredContent']['normalized_result'].update(pid=4321),
            lambda d: d[2][0]['result']['structuredContent']['normalized_result'].update(scripts=[]),
            lambda d: d[2][0]['result']['structuredContent']['normalized_result'].update(state='detached'),
            lambda d: d[2][-1]['result']['structuredContent']['normalized_result'].update(state='running'),
            lambda d: d[2][-1]['result']['structuredContent']['normalized_result'].update(messages_truncated=True),
            lambda d: d[2][-1]['result']['structuredContent']['normalized_result']['messages'][0].update(type='error'),
            lambda d: d[3]['arguments'].update(session_id='other'),
            lambda d: d[3]['result']['structuredContent'].update(target_state='exited'),
        )
        for mutate in cases:
            with self.subTest(mutation=mutate):
                data = records(); mutate(data)
                for call in [data[0], data[1], *data[2], data[3]]:
                    sync(call)
                with self.assertRaises(ValueError):
                    self.check(data)

    def test_prefix_regression_and_journal_only_return_rejected(self):
        for change in ('prefix', 'trailing', 'wrong-thread', 'source'):
            with self.subTest(change=change):
                data = records()
                if change == 'prefix':
                    data[2][-1]['result']['structuredContent']['normalized_result']['messages'][0]['payload']['thread'] = 88
                elif change == 'trailing':
                    data[2][-1]['result']['structuredContent']['normalized_result']['messages'].pop()
                elif change == 'wrong-thread':
                    data[4][-1]['thread'] = 88
                    data[2][-1]['result']['structuredContent']['normalized_result']['messages'][-1]['payload']['thread'] = 88
                else:
                    data[5] += b'// altered\n'
                sync(data[2][-1])
                with self.assertRaises(ValueError):
                    self.check(data)

    def test_heartbeat_gap_rejected(self):
        data = records()
        data[4][-2]['elapsedMs'] = 16000; data[4][-1]['elapsedMs'] = 16001
        for message, row in zip(data[2][-1]['result']['structuredContent']['normalized_result']['messages'], data[4]):
            message['payload'] = copy.deepcopy(row)
        sync(data[2][-1])
        with self.assertRaisesRegex(ValueError, 'heartbeat gap'):
            self.check(data)


class AnchorTests(unittest.TestCase):
    def setUp(self):
        self.text = '\n'.join((
            '[1] Local menu ready: fixture BA_RESURRECTION_LOCAL_MENU_V1',
            '[2] NATIVE QUIT owned gate released: profile=nativestest_fixture BA_RESURRECTION_NATIVE_QUIT_GATE_V1',
            '[3] Practice requested: match='+('a'*32)+' mode=4 selectedDeckSnapshot=1 standalone=1',
            '[3] PRACTICE SMOKE original EditDeck mode4 callback: fixture',
            '[4] Practice native EndOfGameResponse delivered; fixture',
            '[5] PRACTICE SMOKE native Continue (automated)',
            '[7] NATIVE QUIT original confirmation dispatch: thread=77 worldIdle=1 assetLoadingCount=0 naturalExitDeadlineSeconds=60'))
        self.practice = dict(native_result=True, native_continue=True, returned_to_menu=True,
                             bot_max_supply=14, autonomous_action_records=9, match='a'*32)
        self.native = dict(practice=self.practice, after_practice=True, launch_tick=0,
            quit_dispatch_tick=6, observed_exit_tick=9,
            trace=[{}, {}, {}, dict(event='OnConfirm.dispatch', tick=6, thread=77),
                   dict(event='OnConfirm.return', tick=8, thread=77)])

    def test_native_clock_anchor_and_no_movement_claim(self):
        result = practice_anchor(self.text, 'nativestest_fixture', self.native)
        self.assertTrue(result['readiness_before_practice'])
        self.assertFalse(result['startup_before_attachment_covered'])
        self.assertFalse(result['bot_movement_qualified'])

    def test_missing_duplicate_wrong_profile_and_late_gate_rejected(self):
        for text in (self.text.replace('[2]', '[7]'), self.text.replace('profile=nativestest_fixture', 'profile=other'),
                     self.text+'\n'+self.text.splitlines()[1], '\n'.join(self.text.splitlines()[1:])):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    practice_anchor(text, 'nativestest_fixture', self.native)

    def test_shifted_log_wrong_match_thread_and_owner_mode_rejected(self):
        import re
        for case in ('shifted', 'match', 'thread', 'mode'):
            with self.subTest(case=case):
                text = self.text; native = copy.deepcopy(self.native)
                if case == 'shifted':
                    text = re.sub(r'\[(\d+)\]', lambda m: '['+str(int(m[1])+999999999)+']', text)
                elif case == 'match':
                    text = text.replace('match='+('a'*32), 'match='+('b'*32))
                elif case == 'thread':
                    text = text.replace('thread=77', 'thread=88')
                else:
                    native['after_practice'] = False
                with self.assertRaises(ValueError):
                    practice_anchor(text, 'nativestest_fixture', native)


if __name__ == '__main__':
    unittest.main()
