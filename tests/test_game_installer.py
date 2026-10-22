"""Game-local runtime publication and launch script, with authored patch fixtures."""
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest import mock
from tools import game_installer as installer
from tools.package_integrity import verify
from client_patch.transport import rc_setup

ROOT=Path(__file__).resolve().parents[1]


class GameInstallerTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/'local'/('game-installer-'+uuid.uuid4().hex)
        self.package=self.root/'download';self.game=self.root/'working game'
        self.game.mkdir(parents=True);(self.game/'Battle Aces.exe').write_bytes(b'authored fixture')
        files={'program/runtime/python.exe':b'authored interpreter fixture',
               'program/client-helper/BattleAcesOffline.dll':b'MZ authored helper',
               'config/client.example.json':b'{}'}
        for name,data in files.items():
            path=self.package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        (self.package/'package-manifest.json').write_text(json.dumps(dict(schema=1,product='client',
            files={n:dict(bytes=len(d),sha256=hashlib.sha256(d).hexdigest()) for n,d in files.items()})))
        (self.package/'config/client.json').write_text('{"do_not_copy":"personal downloaded settings"}')
        self.patch=mock.patch.object(installer,'patch_game');self.patcher=self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.root.resolve().relative_to((ROOT/'local').resolve());shutil.rmtree(self.root)

    def install(self,host='127.0.0.1'):
        return installer.install(self.package,dict(game_directory=str(self.game),server_host=host))

    def test_copies_only_immutable_payload_and_creates_self_contained_game_script(self):
        result=self.install()
        runtime=Path(result['runtime']);verify(runtime,'client')
        self.assertFalse((runtime/'config/client.json').exists())
        self.assertEqual(self.patcher.call_args.args,(self.game,))
        self.assertEqual(self.patcher.call_args.kwargs['helper'],runtime/'program/client-helper/BattleAcesOffline.dll')
        self.assertNotIn(str(self.package),(self.game/installer.LAUNCHER).read_text())
        self.assertIn('%~dp0',(self.game/installer.LAUNCHER).read_text())
        self.assertIn('DisableDelayedExpansion',(self.game/installer.LAUNCHER).read_text())
        value=json.loads((self.game/installer.CONFIG).read_bytes())
        self.assertEqual(value['server_host'],'127.0.0.1')
        self.assertEqual(value['schema'],4)

    def test_update_preserves_name_profile_port_and_local_identity(self):
        result=self.install();path=Path(result['config'])
        value=json.loads(path.read_bytes());value.update(display_name='Nick',local_profile='friends',server_port=5000)
        path.write_text(json.dumps(value))
        a=rc_setup.Resolver(path,self.game).read()
        self.install()
        b=rc_setup.Resolver(path,self.game).read()
        self.assertEqual((a.player_id,a.token),(b.player_id,b.token))
        after=json.loads(path.read_bytes())
        self.assertEqual((after['display_name'],after['local_profile'],after['server_port']),('Nick','friends',5000))

    def test_invalid_address_or_foreign_launcher_is_refused_before_patch(self):
        with self.assertRaises(ValueError):self.install('https://bad.example')
        self.patcher.assert_not_called()
        self.assertFalse((self.game/'.battleaces-resurrection').exists())
        target=self.game/installer.LAUNCHER;target.write_bytes(b'authored user script')
        with self.assertRaisesRegex(ValueError,'unrelated'):self.install()
        self.assertEqual(target.read_bytes(),b'authored user script')
        self.patcher.assert_not_called()

    def test_launcher_publish_failure_preserves_old_connection_and_script(self):
        result=self.install();config=Path(result['config']);script=Path(result['launcher'])
        before=(config.read_bytes(),script.read_bytes())
        original=installer.atomic_write;failed=False
        def write(path,data):
            nonlocal failed
            if path==script and not failed:failed=True;raise PermissionError('authored failure')
            return original(path,data)
        with mock.patch.object(installer,'atomic_write',side_effect=write):
            with self.assertRaises(PermissionError):self.install('localhost')
        self.assertEqual((config.read_bytes(),script.read_bytes()),before)

    def test_corrupt_cached_runtime_is_not_used_or_silently_repaired(self):
        result=self.install();runtime=Path(result['runtime'])
        (runtime/'program/runtime/python.exe').write_bytes(b'damaged')
        self.patcher.reset_mock()
        with self.assertRaises(ValueError):self.install()
        self.patcher.assert_not_called()

    def test_user_controlled_values_cannot_enter_batch_source(self):
        for relative in ('../escape','C:/absolute','abc & whoami','.battleaces-resurrection/client-runtime/%PATH%'):
            with self.assertRaises(ValueError):installer.launcher_bytes(relative)

    def test_uninstall_restores_before_removing_owned_files_and_keeps_saves(self):
        result=self.install();helper=self.game/'BattleAcesOffline.dll';helper.write_bytes(b'known helper')
        manifest=self.game/'.battleaces-resurrection/patch-manifest.json'
        manifest.write_text(json.dumps(dict(helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest())))
        saves=self.game/'.battleaces-resurrection/profiles/default';saves.mkdir(parents=True)
        (saves/'gameconfig-localuser.toml').write_bytes(b'keep saved deck')
        self.patcher.return_value={'state':'restored'}
        installer.uninstall(self.game)
        self.assertTrue(self.patcher.call_args.kwargs['restore'])
        self.assertFalse(helper.exists());self.assertFalse(Path(result['launcher']).exists())
        self.assertEqual((saves/'gameconfig-localuser.toml').read_bytes(),b'keep saved deck')
        self.assertTrue(Path(result['runtime']).is_dir())

    def test_failed_restore_does_not_remove_launcher_or_helper(self):
        result=self.install();helper=self.game/'BattleAcesOffline.dll';helper.write_bytes(b'known helper')
        (self.game/'.battleaces-resurrection/patch-manifest.json').write_text(json.dumps(
            dict(helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest())))
        self.patcher.side_effect=PermissionError('running game')
        with self.assertRaises(PermissionError): installer.uninstall(self.game)
        self.assertTrue(helper.exists());self.assertTrue(Path(result['launcher']).exists())


if __name__=='__main__':unittest.main()
