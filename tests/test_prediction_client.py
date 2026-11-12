"""Authored portable launcher/install controls; no native game/DLL execution."""
import asyncio
from contextlib import nullcontext
import copy
import json
from pathlib import Path,PureWindowsPath
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch

from tools import prediction_client as p


class PredictionClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.package=self.root/'private';self.game=self.root/'working game'
        self.package.mkdir();self.game.mkdir();self.original=b'ORIGINAL';self.ordinary=b'ORDINARY';self.prediction=b'PREDICTION'
        helper=b'MZ'+b' '.join((b'BA_RESURRECTION_MOVEMENT_PIPELINE_V1',b'BA_RESURRECTION_NATIVE_WORKER_PROXY_V1',
            b'BA_RESURRECTION_ORIGINAL_COMMAND_SCHEDULING_V1'))
        helper+=b' '.join(h['name'].encode()+b'\0'for h in p.prediction_worker.CALL_HOOKS+p.prediction_actor_repair.CALL_HOOKS+p.prediction_actor_repair.TAIL_HOOKS+p.prediction_actor_repair.POINTER_HOOKS)
        helper+='-prediction-visual-correction'.encode('utf-16-le')
        self.helper=helper
        files={'program/runtime/python.exe':b'MZpython',
            'program/app/client_patch/prediction_worker/__main__.py':b'# authored\n',
            'program/app/client_patch/prediction_worker/checkpoint.py':b'# authored\n',
            p.ARTIFACTS['main_helper']:helper,p.ARTIFACTS['heap_helper']:b'MZheap',p.ARTIFACTS['cooperative']:b'MZcoop'}
        files[p.ARTIFACTS['main_helper_provenance']]=p.json_bytes(dict(helper_sha256=p.digest(helper)))
        for role,dll in (('heap_receipt','heap_helper'),('cooperative_receipt','cooperative')):
            receipt=dict(experimental=True,dll_sha256=p.digest(files[p.ARTIFACTS[dll]]),source_sha256='a'*64)
            if role=='heap_receipt':receipt['page_source_sha256']='b'*64
            files[p.ARTIFACTS[role]]=p.json_bytes(receipt)
        self.descriptor=dict(schema=1,profile=p.PROFILE,python='program/runtime/python.exe',module_root='program/app',
            artifacts={role:dict(path=name,sha256=p.digest(files[name]))for role,name in p.ARTIFACTS.items()},
            gameassembly=dict(ordinary_sha256=p.digest(self.ordinary),prediction_sha256=p.digest(self.prediction)))
        files[p.DESCRIPTOR]=p.json_bytes(self.descriptor)
        for name,data in files.items():
            path=self.package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.inventory=dict(schema=1,product='client',files={name:dict(bytes=len(data),sha256=p.digest(data))for name,data in files.items()})
        self.publish_inventory()
        state=self.game/'.battleaces-resurrection';(state/'original').mkdir(parents=True)
        (self.game/'Battle Aces.exe').write_bytes(b'MZgame');(self.game/'GameAssembly.dll').write_bytes(self.ordinary)
        (self.game/'BattleAcesOffline.dll').write_bytes(helper);(state/'original/GameAssembly.dll').write_bytes(self.original)
        sim=self.game/'Battle Aces_Data/Plugins/x86_64/Simulation.dll';sim.parent.mkdir(parents=True);sim.write_bytes(b'MZoriginalSim')
        self.manifest=dict(schema=2,original_sha256=p.digest(self.original),patched_sha256=p.digest(self.ordinary),
            helper_sha256=p.digest(helper),call_hooks=p.patcher.CALL_HOOKS+p.patcher.COMMUNITY_CALL_HOOKS+p.patcher.COSMETIC_CALL_HOOKS,
            tail_hooks=p.patcher.TAIL_HOOKS+p.patcher.COMMUNITY_TAIL_HOOKS+p.patcher.COSMETIC_TAIL_HOOKS,
            patches=p.patcher.PATCHES+p.patcher.COSMETIC_PATCHES+p.patcher.DLSS_PRIVACY_PATCHES,pointer_hooks=[],
            components={'GameAssembly.dll':dict(original_sha256=p.digest(self.original),patched_sha256=p.digest(self.ordinary),
                installed_sha256=p.digest(self.ordinary),telemetry_guards=7),'Other.dll':dict(installed_sha256='f'*64)},
            asset_loading=dict(keep='original verified loading'),local_settings=dict(keep=True),other_user_data=dict(keep=['unchanged']))
        self.manifest_path=state/'patch-manifest.json';self.manifest_path.write_bytes(p.json_bytes(self.manifest))
        self.addCleanup(patch.stopall)
        patch.object(p.patcher,'ORIGINAL_SHA256',p.digest(self.original)).start()
        patch.object(p,'SIM_SHA',p.digest(b'MZoriginalSim')).start()
        self.builder=patch.object(p.patcher,'build_patch',side_effect=self.build).start()
        self.verifier=patch.object(p.launcher,'verify_game').start()
        patch.object(p,'game_not_running',return_value=nullcontext()).start()

    def publish_inventory(self):
        (self.package/'package-manifest.json').write_bytes(p.json_bytes(self.inventory))

    def build(self,original,**kwargs):
        self.assertEqual(original,self.original);self.assertTrue(kwargs['community']);self.assertTrue(kwargs['cosmetics'])
        self.assertFalse(kwargs.get('quit_diagnostics',False))
        return self.prediction if kwargs.get('prediction_movement',False)else self.ordinary

    def test_preparation_updates_all_hashes_exact_hooks_and_preserves_other_components(self):
        result=p.prepare(self.package,self.game)
        self.assertTrue(result['ready']);self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.prediction)
        value=json.loads(self.manifest_path.read_bytes());expected=p.digest(self.prediction)
        self.assertEqual(value['patched_sha256'],expected)
        self.assertEqual(value['components']['GameAssembly.dll']['installed_sha256'],expected)
        self.assertEqual(value['components']['GameAssembly.dll']['patched_sha256'],expected)
        self.assertEqual(value['call_hooks'],self.manifest['call_hooks']+p.prediction_worker.CALL_HOOKS+p.prediction_actor_repair.CALL_HOOKS)
        self.assertEqual(value['pointer_hooks'],p.prediction_actor_repair.POINTER_HOOKS)
        self.assertEqual(value['tail_hooks'],self.manifest['tail_hooks']+p.prediction_actor_repair.TAIL_HOOKS)
        self.assertEqual(value['patches'],self.manifest['patches']+p.prediction_actor_repair.PATCHES)
        for field in ('asset_loading','local_settings','other_user_data'):self.assertEqual(value[field],self.manifest[field])
        self.assertEqual(value['components']['Other.dll'],self.manifest['components']['Other.dll'])
        self.assertEqual((self.game/'BattleAcesOffline.dll').read_bytes(),self.helper)
        self.assertFalse((self.game/'Start Battle Aces.cmd').exists())
        self.assertFalse(list((self.game/'.battleaces-resurrection').glob('.prediction-stage-*')))

    def test_ordinary_check_never_mutates_and_special_prepare_is_idempotent(self):
        before=self.manifest_path.read_bytes()
        with self.assertRaisesRegex(p.PackageError,'prepare'):p.check(self.package,self.game)
        self.assertEqual(self.manifest_path.read_bytes(),before)
        p.prepare(self.package,self.game)
        snapshot=self.manifest_path.read_bytes()
        with patch.object(p.os,'replace',side_effect=AssertionError('idempotent prepare wrote files')):
            self.assertTrue(p.prepare(self.package,self.game)['ready'])
        self.assertEqual(self.manifest_path.read_bytes(),snapshot)

    def test_verified_package_missing_repeat_pointer_export_refuses_before_game_changes(self):
        self.missing_export_refuses(p.prediction_actor_repair.POINTER_HOOKS[0]['name'])

    def test_verified_package_missing_natural_removal_tail_export_refuses_before_game_changes(self):
        self.missing_export_refuses(p.prediction_actor_repair.TAIL_HOOKS[0]['name'])

    def test_verified_package_missing_visual_join_refuses_before_game_changes(self):
        self.missing_export_refuses('OfflinePredictionVisualJoin')

    def test_verified_package_missing_visual_correction_flag_refuses_before_game_changes(self):
        self.missing_helper_bytes_refuse('-prediction-visual-correction'.encode('utf-16-le'),
            'lacks visual correction')

    def missing_export_refuses(self, export):
        self.missing_helper_bytes_refuse(export.encode()+b'\0','lacks movement prediction')

    def missing_helper_bytes_refuse(self, name, message):
        changed=self.helper.replace(name,b'authored_missing_export\0')
        self.assertNotEqual(changed,self.helper)
        helper_path=self.package/p.ARTIFACTS['main_helper'];helper_path.write_bytes(changed)
        provenance=p.json_bytes(dict(helper_sha256=p.digest(changed)))
        (self.package/p.ARTIFACTS['main_helper_provenance']).write_bytes(provenance)
        for role,data in (('main_helper',changed),('main_helper_provenance',provenance)):
            self.descriptor['artifacts'][role]['sha256']=p.digest(data)
            self.inventory['files'][p.ARTIFACTS[role]]=dict(bytes=len(data),sha256=p.digest(data))
        descriptor=p.json_bytes(self.descriptor);(self.package/p.DESCRIPTOR).write_bytes(descriptor)
        self.inventory['files'][p.DESCRIPTOR]=dict(bytes=len(descriptor),sha256=p.digest(descriptor));self.publish_inventory()
        before=self.manifest_path.read_bytes()
        with self.assertRaisesRegex(p.PackageError,message):p.prepare(self.package,self.game)
        self.assertEqual(self.manifest_path.read_bytes(),before)
        self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.ordinary)

    def test_prediction_pointer_and_argument_manifest_must_match_exact_recipe(self):
        p.prepare(self.package,self.game);good=json.loads(self.manifest_path.read_bytes())
        for field in ('pointer_hooks','patches','tail_hooks'):
            changed=copy.deepcopy(good);changed[field]=[];raw=p.json_bytes(changed);self.manifest_path.write_bytes(raw)
            with self.subTest(field=field),self.assertRaisesRegex(p.PackageError,'descriptors|byte patches'):
                p.check(self.package,self.game)
            self.assertEqual(self.manifest_path.read_bytes(),raw)
            self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.prediction)
        self.manifest_path.write_bytes(p.json_bytes(good))

    def test_both_top_and_component_hash_bookkeeping_must_be_exact(self):
        for field in ('top','patched','installed','hooks'):
            value=copy.deepcopy(self.manifest)
            if field=='top':value['patched_sha256']='0'*64
            elif field=='hooks':value['call_hooks']=[]
            else:value['components']['GameAssembly.dll'][field+'_sha256']='0'*64
            self.manifest_path.write_bytes(p.json_bytes(value));before=self.manifest_path.read_bytes()
            with self.subTest(field=field),self.assertRaises(p.PackageError):p.prepare(self.package,self.game)
            self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.ordinary)
            self.assertEqual(self.manifest_path.read_bytes(),before)

    def test_changed_package_backup_helper_or_recipe_pin_refuses_without_mutation(self):
        target=self.package/p.ARTIFACTS['heap_helper'];target.write_bytes(b'changed')
        with self.assertRaises(p.PackageError):p.prepare(self.package,self.game)
        self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.ordinary)
        target.write_bytes(b'MZheap')
        backup=self.game/'.battleaces-resurrection/original/GameAssembly.dll';backup.write_bytes(b'not original')
        with self.assertRaisesRegex(p.PackageError,'original'):p.prepare(self.package,self.game)
        backup.write_bytes(self.original);(self.game/'BattleAcesOffline.dll').write_bytes(b'foreign helper')
        with self.assertRaisesRegex(p.PackageError,'private package normally'):p.prepare(self.package,self.game)

    def test_inventory_valid_but_wrong_descriptor_or_recipe_pin_still_refuses(self):
        for field in ('module_root','gameassembly'):
            value=copy.deepcopy(self.descriptor)
            if field=='module_root':value[field]='program/app/alternate'
            else:value[field]['prediction_sha256']='0'*64
            path=self.package/p.DESCRIPTOR;path.write_bytes(p.json_bytes(value))
            raw=path.read_bytes();self.inventory['files'][p.DESCRIPTOR]=dict(bytes=len(raw),sha256=p.digest(raw));self.publish_inventory()
            with self.subTest(field=field),self.assertRaises(p.PackageError):p.prepare(self.package,self.game)
            self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.ordinary)

    def test_public_settings_copied_by_whitelist_and_private_identity_stays_separate(self):
        original=dict(schema=3,game_directory=str(self.game),display_name='Player',local_profile='main',server_host='example.test',
            server_port=5000,server_name='secret.test',ca_bundle='trust.pem',credential_file='DO-NOT-COPY.json',room='friends',
            fullscreen=False,solo_ai_host='local')
        normal=self.game/'.battleaces-resurrection/client-config.json';normal.write_bytes(p.json_bytes(original))
        p.prepare(self.package,self.game)
        value=json.loads((self.game/p.CONFIG).read_bytes())
        self.assertEqual(set(value),p.rc_setup.KEYS)
        self.assertEqual((value['local_profile'],value['server_host'],value['server_port']),('prediction_custom','example.test',5000))
        self.assertEqual((value['fullscreen'],value['solo_ai_host']),(False,'server'))
        self.assertNotIn('credential_file',value);self.assertNotIn('ca_bundle',value)
        self.assertEqual(json.loads(normal.read_bytes()),original)

    def test_fresh_private_settings_default_to_server_without_ordinary_config(self):
        result=p.prepare(self.package,self.game)
        value=json.loads((self.game/p.CONFIG).read_bytes())
        self.assertEqual(value['solo_ai_host'],'server')
        self.assertEqual(value['local_profile'],'prediction_custom')
        self.assertIn('public mode1 server AI',result['scope'])
        self.assertEqual(p.client.defaults(self.game)['solo_ai_host'],'local')
        self.assertFalse((self.game/'.battleaces-resurrection/client-config.json').exists())

    def test_existing_private_ai_host_and_other_saved_settings_survive_prepare(self):
        path,value=p.settings(self.game)
        path.parent.mkdir(parents=True)
        for host in ('local','server'):
            selected=dict(value,solo_ai_host=host,display_name='Saved private player',
                server_host='private.example',server_port=5001,fullscreen=False)
            before=p.json_bytes(selected);path.write_bytes(before)
            with self.subTest(host=host):
                p.prepare(self.package,self.game)
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(p.settings(self.game),(path,selected))

    def test_running_game_refusal_changes_no_game_or_manifest(self):
        before=self.manifest_path.read_bytes()
        with patch.object(p,'game_not_running',side_effect=p.PackageError('Close the game')):
            with self.assertRaisesRegex(p.PackageError,'Close the game'):p.prepare(self.package,self.game)
        self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.ordinary)
        self.assertEqual(self.manifest_path.read_bytes(),before)

    def test_native_storage_preflight_fails_before_patch_publication(self):
        before=self.manifest_path.read_bytes()
        with patch.object(p.launcher,'native_storage_preflight',side_effect=p.launcher.LaunchError('authored native path bound')):
            with self.assertRaisesRegex(p.launcher.LaunchError,'path bound'):p.prepare(self.package,self.game)
        self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.ordinary)
        self.assertEqual(self.manifest_path.read_bytes(),before)
        self.assertFalse((self.game/p.CONFIG).exists())

    def test_ordinary_profile_fits_but_long_private_profile_refuses_before_mutation(self):
        suffix=PureWindowsPath('.battleaces-resurrection/profiles/default/StorageSyncBackup/A3079428-5DC5-4617-AF2D-0C8656DA760B')
        desired=259-len('\\'+str(suffix))
        leaf='g'*(desired-len(str(self.root))-1)
        self.assertTrue(0<len(leaf)<255)
        game=self.root/leaf;self.assertTrue(game.resolve().is_relative_to(self.root.resolve()))
        shutil.copytree(self.game,game)
        self.assertEqual(p.launcher.native_storage_preflight(dict(game_directory=game,local_profile='default')),'default')
        assembly=(game/'GameAssembly.dll').read_bytes();manifest=game/'.battleaces-resurrection/patch-manifest.json'
        before=manifest.read_bytes()
        with self.assertRaisesRegex(p.launcher.LaunchError,'too long'):p.prepare(self.package,game)
        self.assertEqual((game/'GameAssembly.dll').read_bytes(),assembly);self.assertEqual(manifest.read_bytes(),before)
        self.assertFalse((game/p.CONFIG).exists())

    def test_wrong_original_simulation_refuses_before_game_or_config_publication(self):
        (self.game/'Battle Aces_Data/Plugins/x86_64/Simulation.dll').write_bytes(b'unsupported Sim')
        before=self.manifest_path.read_bytes()
        with self.assertRaisesRegex(p.PackageError,'original Simulation'):p.prepare(self.package,self.game)
        self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.ordinary)
        self.assertEqual(self.manifest_path.read_bytes(),before);self.assertFalse((self.game/p.CONFIG).exists())

    def test_second_publication_failure_rolls_back_exact_assembly_manifest_and_config(self):
        before=self.manifest_path.read_bytes();real_replace=p.os.replace;failed=False
        def replace(source,target):
            nonlocal failed
            if Path(target)==self.manifest_path and not failed:
                failed=True;raise PermissionError('authored manifest publication failure')
            return real_replace(source,target)
        with patch.object(p.os,'replace',side_effect=replace):
            with self.assertRaises(PermissionError):p.prepare(self.package,self.game)
        self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),self.ordinary)
        self.assertEqual(self.manifest_path.read_bytes(),before);self.assertFalse((self.game/p.CONFIG).exists())

    def test_failed_rollback_preserves_exact_old_files_in_owned_recovery_stage(self):
        before=self.manifest_path.read_bytes();real_replace=p.os.replace;manifest_failed=False
        def replace(source,target):
            nonlocal manifest_failed
            if Path(target)==self.manifest_path:
                manifest_failed=True;raise PermissionError('authored publication failure')
            if manifest_failed and Path(target)==self.game/'GameAssembly.dll':raise PermissionError('authored rollback failure')
            return real_replace(source,target)
        with patch.object(p.os,'replace',side_effect=replace):
            with self.assertRaisesRegex(p.PackageError,'rollback needs recovery'):p.prepare(self.package,self.game)
        stages=list((self.game/'.battleaces-resurrection').glob('.prediction-stage-*'));self.assertEqual(len(stages),1)
        self.assertEqual((stages[0]/'0.before').read_bytes(),self.ordinary)
        self.assertEqual((stages[0]/'1.before').read_bytes(),before)
        self.assertEqual(self.manifest_path.read_bytes(),before)

    def test_exact_windows_handle_refuses_mapping_and_closes_only_retained_handle(self):
        from contextlib import contextmanager
        # Test the actual function saved from the module, not the setup mock.
        import importlib.util
        spec=importlib.util.spec_from_file_location('authored_prediction_handle',Path(p.__file__))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        kernel=SimpleNamespace(CreateFileW=Mock(side_effect=[123,456]),CloseHandle=Mock(return_value=1))
        with patch.object(module.C,'WinDLL',return_value=kernel,create=True):
            with module.game_not_running(self.game):pass
        self.assertEqual([call.args[0]for call in kernel.CloseHandle.call_args_list],[456,123])
        args=kernel.CreateFileW.call_args.args;self.assertEqual((args[1],args[2],args[4]),(0xc0000000,0,3))
        kernel.CreateFileW.side_effect=[p.C.c_void_p(-1).value];kernel.CloseHandle.reset_mock()
        with patch.object(module.C,'WinDLL',return_value=kernel,create=True):
            with self.assertRaisesRegex(p.PackageError,'Close the game'):
                with module.game_not_running(self.game):pass
        kernel.CloseHandle.assert_not_called()
        kernel.CreateFileW.side_effect=[123,p.C.c_void_p(-1).value]
        with patch.object(module.C,'WinDLL',return_value=kernel,create=True):
            with self.assertRaisesRegex(p.PackageError,'GameAssembly'):
                with module.game_not_running(self.game):pass
        kernel.CloseHandle.assert_called_once_with(123)

    def test_start_uses_normal_visible_launch_api_fresh_data_and_no_game_automation(self):
        launch=AsyncMock(return_value=0)
        with patch.object(p.launcher,'launch',launch):
            self.assertEqual(p.start(self.package,self.game),0);first=launch.call_args
            self.assertEqual(p.start(self.package,self.game),0);second=launch.call_args
        self.assertNotEqual(first.kwargs['prediction_worker'].data_directory,second.kwargs['prediction_worker'].data_directory)
        for call in (first,second):
            config,remote,args=call.args;options=call.kwargs['prediction_worker']
            self.assertEqual(config['local_profile'],p.LOCAL_PROFILE)
            self.assertEqual(config['solo_ai_host'],'server')
            self.assertIs(getattr(options,'visual_correction',False),True)
            self.assertTrue(args.unified_experimental);self.assertTrue(args.original_command_scheduling_experimental)
            self.assertTrue(args.player_features);self.assertFalse(hasattr(args,'smoke'));self.assertFalse(hasattr(args,'quit_smoke'))
            self.assertEqual(options.module_root,self.package/'program/app')
            self.assertEqual(options.python,self.package/'program/runtime/python.exe')
            self.assertEqual(options.data_directory.parent.parent,self.game/'.battleaces-resurrection/prediction-client/runs')
            self.assertFalse(list(options.data_directory.iterdir()))
            argv=p.launcher.game_arguments(config,None,8765,args,prediction_worker=options)
            self.assertIn('-prediction-movement-experimental',argv)
            self.assertIn('-prediction-visual-correction',argv)
            self.assertIn('-original-command-scheduling-experimental',argv)
            self.assertIn('-solo-ai-host=server',argv)
            self.assertIn('-prediction-worker-python='+str(options.python),argv)
            self.assertFalse(any(word in flag for flag in argv for word in ('smoke','audit','probe','observe','stages','auto-ready','quit-','frame-timing')))
            receipt=json.loads((options.data_directory.parent/'launch.json').read_bytes())
            self.assertIs(receipt['visual_correction'],True)
            self.assertIs(receipt['scripted_gameplay'],False)


if __name__=='__main__':unittest.main()
