"""Fail-closed bounds for the selected172 browser activation observation."""
import copy
import unittest
from pathlib import PureWindowsPath
from tools.frida_browser_activation import ENTRIES, build_source, review


class BrowserActivationTests(unittest.TestCase):
    def fixture(self):
        root = PureWindowsPath('E:/owned/local/game')
        groups = [dict(module=str(root/name), entries=[dict(name=label, rva=rva, sha256='a'*64)
                  for label, rva in entries.items()]) for name, entries in ENTRIES.items()]
        config = dict(image=str(root/'Battle Aces.exe'), runId='a'*32, fileRoots=[str(root/'owned')], eventLimit=4096)
        owner = dict(passed=True, pid=19, thread=19, exit_code=0, launch=dict(forced_cleanup=False), config=config, descriptors=groups,
                     tracker=dict(complete=True, final_accounting=dict(total=1, active=0, terminated=0)))
        counts = {e['name']: 0 for g in groups for e in g['entries']}
        keys = ('kernelbase.dll:CreateProcessW', 'kernelbase.dll:CreateProcessA', 'ntdll.dll:RtlExitUserProcess')
        payloads = [('observer-ready', {'errors': []})]
        for group in groups:
            payloads += [('activation-module', dict(path=group['module'])), ('activation-installed', group)]
        payloads += [('process-exit-entry', dict(exitStatus=0, errors=[], overflow=False,
                     boundaryApi='kernel32.dll:TerminateProcess', currentProcessPseudoHandle=True, transportHoldMs=200,
                     activation=dict(installed=[g['module'] for g in groups], counts=counts),
                     installed=[dict(key=k) for k in keys], counts={k: 0 for k in keys}))]
        normalized = dict(pid=19, state='detached', messages_truncated=False,
                          messages=[dict(type='send', payload=dict(schema=1, seq=i, pid=19, tid=19, runId=config['runId'],
                                    kind=k, data=d)) for i, (k, d) in enumerate(payloads, 1)])
        return config, groups, owner, normalized

    def test_descriptor_guard_rejects_wrong_module_entry_duplicate_and_hash(self):
        config, groups, _, _ = self.fixture()
        source = build_source(config, dict(pid=19, pebAddress='0x10000'), groups)
        self.assertIn('activationSnapshot()', source)
        self.assertIn("name.startsWith('ShellExecute')", source)
        self.assertNotIn('Thread.backtrace', source)
        for change in ('module', 'rva', 'duplicate', 'hash'):
            altered = copy.deepcopy(groups)
            if change == 'module': altered[0]['module'] = 'E:\\foreign.dll'
            elif change == 'rva': altered[0]['entries'][0]['rva'] += 1
            elif change == 'duplicate': altered[0]['entries'][1] = altered[0]['entries'][0]
            else: altered[0]['entries'][0]['sha256'] = 'x'*64
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_source(config, dict(pid=19, pebAddress='0x10000'), altered)

    def test_complete_scoped_capture(self):
        _, _, owner, normalized = self.fixture()
        self.assertTrue(review(normalized, owner)['no_selected_browser_activation'])
        self.assertFalse(review(normalized, owner)['full_privacy_qualified'])

    def test_missing_lifetime_module_install_and_counts_refuse(self):
        _, _, owner, normalized = self.fixture()
        for change in ('owner', 'tracker', 'install', 'counts', 'api', 'counter_event'):
            o, n = copy.deepcopy(owner), copy.deepcopy(normalized)
            final = n['messages'][-1]['payload']['data']
            if change == 'owner': o['passed'] = False
            elif change == 'tracker': o['tracker']['complete'] = False
            elif change == 'install': final['activation']['installed'].pop()
            elif change == 'counts': final['activation']['counts'].pop('Survey.OpenURL')
            elif change == 'api': final['installed'].pop(0)
            else: final['activation']['counts']['Survey.OpenURL'] = 1
            with self.subTest(change=change), self.assertRaises(ValueError): review(n, o)

    def test_transport_loss_foreign_pid_gap_or_error_refuse(self):
        _, _, owner, normalized = self.fixture()
        for change in ('truncated', 'pid', 'gap', 'error'):
            n = copy.deepcopy(normalized)
            if change == 'truncated': n['messages_truncated'] = True
            elif change == 'pid': n['pid'] += 1
            elif change == 'gap': n['messages'].pop(0)
            else: n['messages'][0]['type'] = 'error'
            with self.subTest(change=change), self.assertRaises(ValueError): review(n, owner)

    def test_forwarded_self_termination_pair_is_not_two_exits(self):
        _, _, owner, normalized = self.fixture()
        first = normalized['messages'][-1]['payload']['data']
        first['counts'].update({'kernel32.dll:TerminateProcess': 1, 'kernelbase.dll:TerminateProcess': 0})
        second = copy.deepcopy(normalized['messages'][-1]);second['payload']['seq'] += 1
        second['payload']['data']['boundaryApi'] = 'kernelbase.dll:TerminateProcess'
        second['payload']['data']['counts']['kernelbase.dll:TerminateProcess'] = 1
        normalized['messages'].append(second)
        self.assertEqual(review(normalized, owner)['terminal_snapshots'], 2)
        for change in ('thread', 'order', 'status', 'counter', 'hold'):
            n = copy.deepcopy(normalized);last=n['messages'][-1]['payload']
            if change == 'thread': last['tid'] += 1
            elif change == 'order': last['data']['boundaryApi'] = 'kernel32.dll:TerminateProcess'
            elif change == 'status': last['data']['exitStatus'] = 1
            elif change == 'counter': last['data']['counts']['kernelbase.dll:CreateProcessW'] = 1
            else: last['data']['transportHoldMs'] = 0
            with self.subTest(change=change), self.assertRaises(ValueError): review(n, owner)

    def test_activity_after_terminal_counter_snapshot_refuses(self):
        _, _, owner, normalized = self.fixture()
        for kind in ('activation-entry', 'process-create', 'shell-entry', 'activation-module'):
            n = copy.deepcopy(normalized)
            extra = copy.deepcopy(n['messages'][-1]);extra['payload']['seq'] += 1;extra['payload']['kind'] = kind
            n['messages'].append(extra)
            with self.subTest(kind=kind), self.assertRaises(ValueError): review(n, owner)


if __name__ == '__main__': unittest.main()
