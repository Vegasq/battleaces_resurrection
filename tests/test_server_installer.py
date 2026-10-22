import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock
from tests.test_credentials import private_test_folder,remove_test_folder
from tools import server_installer as installer


class ServerInstallerTests(unittest.TestCase):
    def setUp(self):
        self.root=private_test_folder('si-');self.game=self.root/'game';self.package=self.root/'package'
        self.game.mkdir();self.package.mkdir();(self.game/'Battle Aces_Data').mkdir()
        for name,data in {'Battle Aces.exe':b'fixture exe','GameAssembly.dll':b'fixture dll',
                          'Battle Aces_Data/asset':b'fixture asset',
                          '.battleaces-resurrection/profiles/default/save':b'personal save'}.items():
            path=self.game/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        files={'Start Server.exe':b'MZ authored launcher','program/runtime/python.exe':b'authored interpreter'}
        for name,data in files.items():
            path=self.package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        (self.package/'package-manifest.json').write_text(json.dumps(dict(schema=1,product='server',
            files={n:dict(bytes=len(d),sha256=hashlib.sha256(d).hexdigest()) for n,d in files.items()})))

    def tearDown(self): remove_test_folder(self.root)

    def test_working_copy_is_independent_and_never_contains_personal_saves(self):
        target=self.root/'copy';installer.copy_game(self.game,target)
        self.assertFalse((target/'.battleaces-resurrection/profiles').exists())
        (target/'GameAssembly.dll').write_bytes(b'changed private copy')
        self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),b'fixture dll')

    def test_install_publishes_only_after_import_and_never_patches_source(self):
        destination=self.root/'installed'
        def exported(game,out):
            self.assertNotEqual(game,self.game);self.assertFalse((game/'.battleaces-resurrection/profiles').exists())
            out.mkdir();(out/'fixture').write_bytes(b'export')
        with (mock.patch.object(installer,'export_game',side_effect=exported),mock.patch.object(installer,'patch_game') as patch,
              mock.patch.object(installer.launcher,'verify_game'),mock.patch.object(installer,'verify_assets'),mock.patch.object(installer,'import_assets',return_value={'playable_units':100})):
            result=installer.install(self.package,dict(game_directory=str(self.game),server_directory=str(destination)))
        self.assertNotEqual(patch.call_args.args[0],self.game)
        self.assertTrue(Path(result['launcher']).is_file());self.assertFalse(result['server_started'])
        self.assertFalse((destination/'.setup/game').exists())
        self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),b'fixture dll')

    def test_nonempty_destination_is_never_replaced(self):
        destination=self.root/'existing';destination.mkdir();(destination/'host.json').write_bytes(b'keep')
        with mock.patch.object(installer,'export_game') as export:
            with self.assertRaisesRegex(ValueError,'empty'):installer.install(self.package,dict(
                game_directory=str(self.game),server_directory=str(destination)))
        export.assert_not_called();self.assertEqual((destination/'host.json').read_bytes(),b'keep')

    def test_failed_export_does_not_publish_or_change_source(self):
        destination=self.root/'not-published'
        with (mock.patch.object(installer,'export_game',side_effect=ValueError('export failed')),
              mock.patch.object(installer,'patch_game'),mock.patch.object(installer.launcher,'verify_game')):
            with self.assertRaisesRegex(ValueError,'export failed'):installer.install(self.package,dict(
                game_directory=str(self.game),server_directory=str(destination)))
        self.assertFalse(destination.exists());self.assertEqual((self.game/'GameAssembly.dll').read_bytes(),b'fixture dll')
