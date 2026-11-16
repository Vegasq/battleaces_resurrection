import argparse
import copy
import json
import unittest

from tools.verify_settings_status import check_log, validate_options


class SettingsEvidenceTests(unittest.TestCase):
    def log(self, scope='menu'):
        phases = ['initial','general'] + ([] if scope == 'match' else ['reopened','offline'])
        lines = []
        for phase in phases:
            online = phase != 'offline'
            label = 'Resurrection 0.5.0-rc1 (build abc1234)  |  ' + ('Online' if online else 'Offline') + '\nServer: localhost:12345' + (' (127.0.0.1)' if online else '')
            lines.append(f'SETTINGS STATUS SMOKE readback: phase={phase} online={int(online)} active=1 ownedLabels=1 raycast=0 richText=0 text='+json.dumps(label))
        lines.extend(['SETTINGS STATUS SMOKE released: nativeOwnerReleased=1 ownedChildDestroyed=1'] * (1 if scope == 'match' else 2))
        if scope == 'match':
            lines += ['SETTINGS STATUS SMOKE original in-match Settings ClickEvent: bindingTargetsVerified=1 serializedCallbacks=1 mouseInput=0',
                      'SETTINGS STATUS SMOKE passed: scope=in-match online=1 released=1', 'PUBLIC QUEUE completed return:']
        else: lines.append('SETTINGS STATUS SMOKE passed: scope=menu onlineDrop=1 reopen=1 released=1')
        return '\n'.join(lines)

    def check(self, log, scope='menu', dropped=True):
        return check_log(log, scope, '0.5.0-rc1 (build abc1234)', 12345, dropped)

    def test_menu_and_match_require_distinct_complete_routes(self):
        self.assertEqual(self.check(self.log()), ['initial','general','reopened','offline'])
        self.assertEqual(self.check(self.log('match'), 'match', False), ['initial','general'])
        with self.assertRaises(AssertionError): self.check(self.log('match'))

    def test_corrupted_observations_fail(self):
        original = self.log()
        for corrupted in (
            original.replace('ownedLabels=1','ownedLabels=2',1),
            original.replace('127.0.0.1','127.0.0.2'),
            original.replace('abc1234','wrong'),
            original.replace('phase=offline online=0','phase=offline online=1'),
            original.replace('ownedChildDestroyed=1','ownedChildDestroyed=0',1),
            original+'\nSettings build/status failed: test',
        ):
            with self.subTest(corruption=corrupted):
                with self.assertRaises(AssertionError): self.check(corrupted)
        with self.assertRaises(AssertionError): self.check(original, dropped=False)

    def test_match_requires_original_button_and_continue(self):
        for fragment in ('original in-match Settings ClickEvent: bindingTargetsVerified=1 serializedCallbacks=1 mouseInput=0','PUBLIC QUEUE completed return:'):
            with self.assertRaises(AssertionError): self.check(self.log('match').replace(fragment,''),'match',False)

    def test_bounded_cli(self):
        value = argparse.Namespace(scope='menu', expected_helper_sha256='a'*64, timeout=180, build_label='0.5.0-rc1 (build diagnostic)')
        validate_options(value)
        for key, bad in (('scope','any'), ('timeout',0), ('timeout',float('nan')), ('expected_helper_sha256','wrong'), ('build_label','<secret>')):
            changed = copy.copy(value); setattr(changed,key,bad)
            with self.assertRaises(AssertionError): validate_options(changed)
