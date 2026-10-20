"""Synthetic evidence contracts only; actual native runs are separate ignored inputs."""
import copy
import hashlib
import json
import unittest
from pathlib import PureWindowsPath

from tools.frida_game_source import ENTRIES, SIZES, build_source, matches_source
from tools.verify_game_observation import GAME_SHAS, UNITY_SHA, owner_proof, prepared_root, window


def fixture():
    config = dict(image='Z:\\owned\\game\\Battle Aces.exe', runId='a'*32,
                  journal='Z:\\owned\\window\\events.jsonl', native={})
    for name, entries in ENTRIES.items():
        config['native'][name] = dict(path=str(PureWindowsPath(config['image']).parent/name), size=SIZES[name],
                                    entries=[dict(rva=rva, name=label, guard=guard) for rva, label, guard in entries])
    hooks = [dict(key=f'{name}:{label}', offset=hex(rva), guarded=True, guardHex=guard)
             for name, entries in ENTRIES.items() for rva, label, guard in entries]
    loaded = [dict(name=name, path=cfg['path'], size=cfg['size']) for name, cfg in config['native'].items()]
    counts = {h['key']: 0 for h in hooks}
    rows = []
    for i, kind in enumerate(('observer-ready', 'lifecycle-enter:RGameSingleton.OnDestroy',
                              'lifecycle-return:RGameSingleton.OnDestroy'), 1):
        values = dict(counts)
        if i > 1:
            values['gameassembly.dll:RGameSingleton.OnDestroy'] = 1
        rows.append(dict(schema=2, sequence=i, runId=config['runId'], kind=kind, pid=1234, thread=77,
                         architecture='x64', pointerSize=8, elapsedMs=i, counts=values,
                         installed=copy.deepcopy(hooks), loadedNative=copy.deepcopy(loaded), errors=[], nativeReady=True))
    source = build_source(config).encode()
    evidence = dict(evidence_id='ev_'+'a'*64, confidence='observed', provider=dict(id='frida'),
                    operation='instrument_with_frida', predicate_type='rea.frida.instrumentation-observation',
                    parameters=dict(session_id='s', device_id='local', mode='attach', pid=1234),
                    normalized_result=dict(session_id='s', device_id='local', mode='attach', pid=1234,
                        state='detached', messages_truncated=False, cleanup_error=None, source_kind='file',
                        source_path='Z:\\owned\\window\\observer.js', source_sha256=hashlib.sha256(source).hexdigest(),
                        scripts=[dict(script_id='one')], messages=[dict(type='send', script_id='one', payload=r) for r in rows]))
    capture = dict(arguments=dict(mode='attach', device_id='local', pid=1234, source_kind='file',
                                 path=evidence['normalized_result']['source_path'], duration_ms=60000),
                   result=dict(structuredContent=evidence, content=[]))
    sync(capture)
    return capture, copy.deepcopy(rows), source, config


def sync(capture):
    result = capture['result']
    result['content'] = [dict(type='text', text=json.dumps(result['structuredContent']))]


def owned():
    native = dict(passed=True, pid=1234, forced_cleanup=False, natural_exit=True, owned_process_reaped=True,
                  exit_code=0, source_files_unchanged=True, source_sha256_at_start={'owned.py': 'a'*64},
                  source_sha256_at_finish={'owned.py': 'a'*64}, shared_settings_unchanged=True,
                  shared_settings_before={'sha': 'b'*64}, shared_settings_after={'sha': 'b'*64},
                  quit_dispatch_tick=103, observed_exit_tick=110, native_quit_passed=True,
                  trace=[dict(pid=1234, thread=77, tick=100+i, event=event) for i, event in enumerate(
                      ('armed', 'Show.dispatch', 'Show.return', 'OnConfirm.dispatch', 'OnConfirm.return'))])
    images = {'UnityPlayer.dll': UNITY_SHA, 'GameAssembly.dll': sorted(GAME_SHAS)[0]}
    harness = dict(passed=True, pid=1234, forced_cleanup=False, native_verifier_exit_code=0,
                   quit_gate_release=dict(native_hooks_ready=True),
                   job_assigned=dict(total_processes=1, active_processes=1, total_terminated_processes=0),
                   job_before_close=dict(total_processes=1, active_processes=0, total_terminated_processes=0),
                   game_components_before=images, game_components_after=dict(images), source_unchanged=True, observer_unchanged=True)
    return harness, native


class GameObservationTests(unittest.TestCase):
    def check(self, fixture_data):
        return window(*fixture_data, pid=1234, quit_thread=77)

    def test_positive_return_with_retained_owner_proof(self):
        result = self.check(fixture())
        self.assertTrue(result['original_destroy_return_observed'])
        self.assertEqual(result['provider_rows'], 3)
        self.assertEqual(owner_proof(*owned()), (1234, 77))

    def test_only_canonical_source_and_reviewed_entries(self):
        cap, rows, raw, config = fixture()
        self.assertTrue(matches_source(raw.replace(b'\n', b'\r\n'), config))
        with self.assertRaises(ValueError):
            self.check((cap, rows, raw+b'\n// unreviewed code', config))
        config['native']['unityplayer.dll']['entries'][0]['rva'] += 1
        with self.assertRaises(ValueError):
            build_source(config)

    def test_prepared_owner_metadata_cannot_be_replaced(self):
        _, _, source, config = fixture()
        harness, native = owned()
        native['profile'] = harness['profile'] = 'nativestest_synthetic'
        harness.update(config=config, run_id=config['runId'], observer_sha256=hashlib.sha256(source).hexdigest(), source_sha256='c'*64)
        settings = {key: copy.deepcopy(harness[key]) for key in
                    ('config', 'run_id', 'profile', 'observer_sha256', 'source_sha256', 'game_components_before')}
        prepared_root(harness, native, settings, source)
        for side, key, value in (
            ('harness', 'run_id', 'b'*32), ('settings', 'run_id', 'b'*32),
            ('harness', 'observer_sha256', 'b'*64), ('settings', 'observer_sha256', 'b'*64),
            ('harness', 'source_sha256', 'b'*64), ('settings', 'source_sha256', 'b'*64),
            ('harness', 'profile', 'nativestest_other'), ('settings', 'profile', 'nativestest_other'),
            ('settings', 'game_components_before', {'different': 'b'*64}),
        ):
            with self.subTest(side=side, key=key):
                h, s = copy.deepcopy(harness), copy.deepcopy(settings)
                (h if side == 'harness' else s)[key] = value
                with self.assertRaises(ValueError):
                    prepared_root(h, native, s, source)

    def test_trailing_journal_is_exposed_and_not_provider_evidence(self):
        cap, rows, raw, config = fixture()
        provider = cap['result']['structuredContent']['normalized_result']
        provider['messages'] = provider['messages'][:-1]
        sync(cap)
        result = self.check((cap, rows, raw, config))
        self.assertEqual(result['trailing_journal_rows'], 1)
        self.assertFalse(result['original_destroy_return_observed'])
        self.assertEqual(result['last_provider_ms'], 2)
        self.assertEqual(result['last_journal_ms'], 3)

    def test_journal_prefix_must_equal_provider(self):
        data = list(fixture()); data[1][0]['thread'] = 88
        with self.assertRaisesRegex(ValueError, 'prefix'):
            self.check(data)

    def test_provider_failure_and_identity_controls(self):
        cases = (
            lambda c, n: c['arguments'].update(duration_ms=60001),
            lambda c, n: c['arguments'].update(pid=4321),
            lambda c, n: n.update(messages_truncated=True),
            lambda c, n: n.update(cleanup_error='failed'),
            lambda c, n: n.update(source_sha256='0'*64),
            lambda c, n: n['scripts'][0].update(script_id=''),
            lambda c, n: n['messages'][0].update(type='error'),
            lambda c, n: c['result']['structuredContent']['parameters'].update(session_id='wrong'),
            lambda c, n: c['result']['structuredContent'].update(confidence='inferred'),
            lambda c, n: c['result']['structuredContent'].pop('confidence'),
            lambda c, n: c['result']['structuredContent'].update(evidence_id=None),
            lambda c, n: c['result']['structuredContent'].update(evidence_id='arbitrary'),
        )
        for mutate in cases:
            with self.subTest(mutation=mutate):
                cap, rows, raw, cfg = fixture()
                mutate(cap, cap['result']['structuredContent']['normalized_result']); sync(cap)
                with self.assertRaises(ValueError):
                    self.check((cap, rows, raw, cfg))

    def test_row_errors_identity_timing_counters_and_guards(self):
        cases = (
            lambda r: r[0].update(errors=['observer failure']),
            lambda r: r[0].update(elapsedMs=-1),
            lambda r: r[0].update(sequence=True),
            lambda r: r[1].update(elapsedMs=0),
            lambda r: r[0].update(runId='b'*32),
            lambda r: r[0].update(nativeReady=False),
            lambda r: r[0]['loadedNative'][0].update(size=1),
            lambda r: r[0]['installed'][0].update(guardHex='00'*16),
            lambda r: r[1]['installed'][0].update(offset='0x1'),
            lambda r: r[2]['counts'].update({'gameassembly.dll:RGameSingleton.OnDestroy': 0}),
            lambda r: r[0]['counts'].update({'gameassembly.dll:RGameSingleton.OnDestroy': True}),
        )
        for mutate in cases:
            with self.subTest(mutation=mutate):
                cap, rows, raw, cfg = fixture(); mutate(rows)
                cap['result']['structuredContent']['normalized_result']['messages'] = [dict(type='send', script_id='one', payload=r) for r in rows]
                sync(cap)
                with self.assertRaises(ValueError):
                    self.check((cap, rows, raw, cfg))

    def test_return_requires_same_original_thread(self):
        cap, rows, raw, cfg = fixture(); rows[-1]['thread'] = 88
        cap['result']['structuredContent']['normalized_result']['messages'][-1]['payload'] = rows[-1]; sync(cap)
        self.assertFalse(self.check((cap, rows, raw, cfg))['original_destroy_return_observed'])

    def test_owner_rejects_forced_cleanup_and_nonzero_exit(self):
        cases = (
            lambda h, n: h.update(forced_cleanup=True),
            lambda h, n: n.update(exit_code=1),
            lambda h, n: h.update(native_verifier_exit_code=1),
            lambda h, n: h['quit_gate_release'].update(native_hooks_ready=False),
            lambda h, n: h['job_before_close'].update(active_processes=1),
            lambda h, n: h['job_before_close'].update(total_terminated_processes=1),
            lambda h, n: h['job_before_close'].update(total_processes=True),
            lambda h, n: n.update(shared_settings_after={'changed': True}),
            lambda h, n: n['trace'][-1].update(thread=88),
        )
        for mutate in cases:
            with self.subTest(mutation=mutate):
                harness, native = owned(); mutate(harness, native)
                with self.assertRaises(ValueError):
                    owner_proof(harness, native)


if __name__ == '__main__':
    unittest.main()
