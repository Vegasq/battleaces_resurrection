"""Evidence controls for the scene-unload chain; no native execution."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import review_scene_release as gate


@unittest.skipUnless(os.environ.get('BA_SCENE_RELEASE_EVIDENCE'),'retained evidence is opt-in')
class SceneReleaseTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.original=self.root.parent.parent/'BattleAcesBeta_untouched'
        self.installed=self.root/'local/r171g'
        self.evidence=Path(os.environ['BA_SCENE_RELEASE_EVIDENCE']).resolve()

    def review(self):
        return gate.review(self.original,self.installed,self.evidence)

    def changed(self,name,transform,message):
        read=Path.read_bytes
        target=self.evidence/name
        def modified(path):
            raw=read(path)
            return transform(raw) if path==target else raw
        with patch.object(Path,'read_bytes',modified):
            with self.assertRaisesRegex(ValueError,message):self.review()

    def test_chain_is_not_reported_as_safe_cancellation(self):
        result=self.review()
        self.assertTrue(result['running_unload_uses_chain'])
        self.assertEqual(result['instructions'],1576)
        self.assertEqual(len(result['bodies']),14)
        for name in ('safe_cancellation_proved','callback_suppression_proved','runtime_recovery_proved'):
            self.assertIs(result[name],False)

    def test_wrong_scene_generic_binding_rejected(self):
        with patch.dict(gate.SPECS,{0x6aeda08:(24804,6117,-1,1064,'RemoveScene')}):
            with self.assertRaisesRegex(ValueError,'generic binding differs'):self.review()

    def test_missing_chain_call_rejected(self):
        self.changed('game-45987d0.asm',
                     lambda raw:b'\n'.join(line for line in raw.split(b'\n')
                                           if not line.startswith(b'18459898f:')),
                     'complete and contiguous')

    def test_reversed_running_branch_rejected(self):
        self.changed('game-45987d0.asm',
                     lambda raw:raw.replace(b'jne\t0x184598957',b'je\t0x184598957'),
                     'semantic anchor differs')


@unittest.skipUnless(os.environ.get('BA_SCENE_PROVIDER_EVIDENCE'),'retained provider evidence is opt-in')
class SceneProviderTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.evidence=Path(os.environ['BA_SCENE_PROVIDER_EVIDENCE']).resolve()

    def review(self):
        return gate.review_provider(self.root.parent.parent/'BattleAcesBeta_untouched',
                                    self.root/'local/r171g',self.evidence)

    def changed(self,name,transform,message):
        read=Path.read_bytes
        target=self.evidence/name
        def modified(path):
            raw=read(path)
            return transform(raw) if path==target else raw
        with patch.object(Path,'read_bytes',modified):
            with self.assertRaisesRegex(ValueError,message):self.review()

    def test_early_completion_is_not_cancellation(self):
        result=self.review()
        self.assertTrue(result['passed'])
        self.assertEqual(result['instructions'],717)
        self.assertTrue(result['completion_before_activation'])
        self.assertTrue(result['destroy_releases_dependency'])
        self.assertFalse(result['safe_cancellation_proved'])
        self.assertFalse(result['runtime_recovery_proved'])

    def test_activation_branch_inversion_rejected(self):
        self.changed('game-4ceab60.asm',
                     lambda raw:raw.replace(b'jne\t0x184cead7c',b'je\t0x184cead7c'),
                     'provider anchor differs')

    def test_scene_handle_substitution_rejected(self):
        self.changed('game-4cea9c0.asm',
                     lambda raw:raw.replace(b'lea\trcx, [rbx + 0xd0]',b'lea\trcx, [rbx + 0xa8]'),
                     'provider anchor differs')

    def test_missing_progress_branch_rejected(self):
        self.changed('game-4ceab60.asm',
                     lambda raw:b'\n'.join(line for line in raw.split(b'\n')
                                           if not line.startswith(b'184ceac5f:')),
                     'complete and contiguous')


@unittest.skipUnless(os.environ.get('BA_QUIT_ADMISSION_INSTALLED'), 'installed Quit evidence is opt-in')
class QuitAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.original = self.root.parent.parent/'BattleAcesBeta_untouched'
        self.installed = Path(os.environ['BA_QUIT_ADMISSION_INSTALLED']).resolve()
        self.evidence = self.root/'local/native-quit-contract01'

    def review(self):
        return gate.review_quit_admission(self.original, self.installed, self.evidence)

    def test_static_gate_does_not_claim_pending_load_exit(self):
        result = self.review()
        self.assertTrue(result['passed'])
        self.assertTrue(result['positive_asset_loading_count_vetoes_quit'])
        self.assertEqual(len(result['bodies']), 5)
        self.assertEqual(len(result['bindings']), 8)
        self.assertEqual(result['byte_anchors'], 7)
        self.assertEqual(result['instructions'], 0)
        for name in ('asset_count_equals_map_loading_proved', 'safe_cancellation_proved',
                     'pending_load_quit_proved', 'runtime_recovery_proved'):
            self.assertIs(result[name], False)

    def test_changed_installed_veto_branch_rejected(self):
        read = Path.read_bytes
        target = self.installed/'GameAssembly.dll'
        def modified(path):
            raw = read(path)
            if path == target:
                pe = gate.PE(raw)
                offset = pe.offset(pe.base+0x3e93473, 1)
                self.assertEqual(raw[offset], 0x7f)
                raw = raw[:offset]+b'\x7e'+raw[offset+1:]
            return raw
        with patch.object(Path, 'read_bytes', modified):
            with self.assertRaisesRegex(ValueError, 'installed quit body differs'):
                self.review()

    def test_false_return_interpretation_rejected(self):
        with patch.dict(gate.QUIT_ANCHORS, {0x3e9349f: 'b0014883c428c3'}):
            with self.assertRaisesRegex(ValueError, 'quit semantic anchor differs'):
                self.review()

    def test_shared_ui_body_still_requires_exact_method_token(self):
        with patch.dict(gate.QUIT_METHODS, {('Uncapped.UI', 'UIQuitButton'):
                        {0x06002e5f: ('Quit', 0x3d06f50)}}):
            with self.assertRaisesRegex(ValueError, 'quit method binding differs'):
                self.review()

    def test_retained_body_hash_mismatch_rejected(self):
        read = Path.read_bytes
        target = self.evidence/'slices.json'
        def modified(path):
            raw = read(path)
            if path == target:
                saved = gate.json.loads(raw)
                saved['assets-wantsquit']['code_sha256'] = '0'*64
                raw = gate.json.dumps(saved).encode()
            return raw
        with patch.object(Path, 'read_bytes', modified):
            with self.assertRaisesRegex(ValueError, 'retained quit bytes differ'):
                self.review()

    def test_unknown_type_rejected_with_binding_error(self):
        with patch.dict(gate.QUIT_METHODS, {('UI', 'UIQuitButton'):
                        {0x06003450: ('Quit', 0x3d06f50)}}):
            with self.assertRaisesRegex(ValueError, 'quit type binding differs'):
                self.review()


@unittest.skipUnless(os.environ.get('BA_ASSET_QUIT_EVIDENCE') and os.environ.get('BA_QUIT_ADMISSION_INSTALLED'),
                     'asset Quit retained evidence is opt-in')
class AssetQuitRetryTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.evidence=Path(os.environ['BA_ASSET_QUIT_EVIDENCE']).resolve()
        self.installed=Path(os.environ['BA_QUIT_ADMISSION_INSTALLED']).resolve()

    def review(self):
        return gate.review_asset_quit_retry(self.root.parent.parent/'BattleAcesBeta_untouched',
                                           self.installed,self.evidence)

    def changed(self,name,transform,message):
        read=Path.read_bytes;target=self.evidence/name
        def modified(path):
            raw=read(path)
            return transform(raw) if path==target else raw
        with patch.object(Path,'read_bytes',modified):
            with self.assertRaisesRegex(ValueError,message):self.review()

    def test_completion_retry_is_static_and_startup_is_only_a_window(self):
        result=self.review()
        self.assertTrue(result['passed'])
        self.assertEqual(result['instructions'],452)
        self.assertEqual([b['full_body'] for b in result['bodies']],[True,True,True,False])
        self.assertEqual(result['concrete_background_load'],'LargeGroupAudioTable')
        self.assertEqual([c['method'] for c in result['completion_contexts']],
                         ['LoadAssetAsync','<LoadTableInBackground>b__5_0','add_Completed'])
        for name in ('startup_whole_body_unchanged','positive_counter_runtime_recovery_proved',
                     'safe_cancellation_proved','hung_engine_recovery_proved'):
            self.assertIs(result[name],False)

    def test_reversed_count_or_wants_quit_guard_rejected(self):
        for before,after in ((b'jg\t0x18166c76f',b'jle\t0x18166c76f'),
                             (b'je\t0x18166c76f',b'jne\t0x18166c76f')):
            self.changed('game-166c650.asm',lambda raw:raw.replace(before,after),'asset quit semantic anchor')

    def test_missing_original_decrement_rejected(self):
        self.changed('game-166c650.asm',lambda raw:b'\n'.join(line for line in raw.split(b'\n')
                     if not line.startswith(b'18166c70d:')),'complete and contiguous')

    def test_wrong_generic_callback_slot_rejected(self):
        self.changed('game-1381620.asm',lambda raw:raw.replace(b'mov\tr8, qword ptr [r8 + 0x30]',
                     b'mov\tr8, qword ptr [r8 + 0x40]'),'asset quit semantic anchor')

    def test_counter_decrement_in_place_of_new_load_increment_rejected(self):
        self.changed('game-1381620.asm',lambda raw:raw.replace(b'inc\tdword ptr [rax + 0x8]',
                     b'dec\tdword ptr [rax + 0x8]'),'asset quit semantic anchor')

    def test_changed_installed_callback_is_not_qualified(self):
        read=Path.read_bytes;target=self.installed/'GameAssembly.dll'
        def modified(path):
            raw=read(path)
            if path==target:
                pe=gate.PE(raw);offset=pe.offset(pe.base+0x166c744,1)
                self.assertEqual(raw[offset],0x7f)
                raw=raw[:offset]+b'\x7e'+raw[offset+1:]
            return raw
        with patch.object(Path,'read_bytes',modified):
            with self.assertRaisesRegex(ValueError,'qualified installed recipe23'):self.review()


if __name__=='__main__':unittest.main()
