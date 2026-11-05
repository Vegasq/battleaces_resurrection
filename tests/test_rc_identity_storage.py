"""Identity isolation and exclusive first-publication failure recovery."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from client_patch.transport import rc_setup,launcher
from server.admission import rc_player_id

ROOT=Path(__file__).resolve().parents[1]


class RCIdentityStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='identity-storage-',dir=ROOT/'local')
        self.root=Path(self.directory.name);self.game=self.root/'game';self.game.mkdir()
        (self.game/'Battle Aces.exe').write_bytes(b'authored existence fixture')
        self.path=self.root/'config/client.json'
        rc_setup.save(dict(game_directory=str(self.game),display_name='Player',server_host='127.0.0.1',
                           expected_config_sha256=None),self.path)
        self.identities=self.path.parent/'rc-identities'
        self.identity=self.identities/(hashlib.sha256(b'127.0.0.1:47623/default').hexdigest()+'.json')

    def tearDown(self):self.directory.cleanup()

    def read(self):return rc_setup.Resolver(self.path,self.game).read()

    def test_hardlinked_identity_refuses_without_changing_either_name(self):
        self.read();before=self.identity.read_bytes();alias=self.root/'other-player.json'
        os.link(self.identity,alias)
        with self.assertRaises(launcher.LaunchError):self.read()
        self.assertEqual(self.identity.read_bytes(),before);self.assertEqual(alias.read_bytes(),before)

    def test_reparse_directory_refuses_before_lock_or_identity_creation(self):
        self.identities.mkdir();original=Path.lstat
        def metadata(path,*args,**kwargs):
            if path==self.identities:
                return SimpleNamespace(st_mode=stat.S_IFDIR|0o700,st_file_attributes=0x400,st_nlink=1)
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'lstat',metadata):
            with self.assertRaises(launcher.LaunchError):self.read()
        self.assertEqual(list(self.identities.iterdir()),[])

    @unittest.skipUnless(os.name=='nt','actual NTFS directory junction')
    def test_actual_windows_directory_junction_refuses_without_target_writes(self):
        target=self.root/'other-identities';target.mkdir()
        marker=target/'keep.txt';marker.write_bytes(b'other installation')
        quote=lambda p:"'"+str(p).replace("'","''")+"'"
        command=("$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path "+
                 quote(self.identities)+" -Target "+quote(target)+" | Out-Null")
        shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        result=subprocess.run([str(shell),'-NoProfile','-NonInteractive','-Command',command],
            capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,0,'owned junction creation failed')
        self.assertTrue(self.identities.lstat().st_file_attributes&0x400)
        with self.assertRaises(launcher.LaunchError):self.read()
        self.assertEqual([p.name for p in target.iterdir()],['keep.txt'])
        self.assertEqual(marker.read_bytes(),b'other installation')

    def test_symbolic_identity_is_not_treated_as_missing(self):
        self.identities.mkdir();original=Path.lstat
        def metadata(path,*args,**kwargs):
            if path==self.identity:return SimpleNamespace(st_mode=stat.S_IFLNK|0o777,st_file_attributes=0,st_nlink=1)
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'lstat',metadata):
            with self.assertRaises(launcher.LaunchError):self.read()
        self.assertFalse(self.identity.exists())

    def test_hardlinked_setup_lock_refuses_without_touching_target(self):
        self.identities.mkdir();target=self.root/'unrelated-file';target.write_bytes(b'preserve me')
        os.link(target,self.identities/'.rc-setup.lock')
        with self.assertRaises(launcher.LaunchError):self.read()
        self.assertEqual(target.read_bytes(),b'preserve me');self.assertFalse(self.identity.exists())

    def race(self,raw):
        if os.name=='nt':
            original=Path.rename
            def publish(path,target):
                if path.name.startswith('.identity-'):Path(target).write_bytes(raw)
                return original(path,target)
            return mock.patch.object(Path,'rename',publish)
        original=os.link
        def publish(source,target):
            Path(target).write_bytes(raw)
            return original(source,target)
        return mock.patch.object(os,'link',publish)

    def test_intervening_valid_identity_wins_and_is_not_overwritten(self):
        token='ba1_'+'A'*43;value=dict(player_id=rc_player_id(token),token=token)
        raw=json.dumps(value).encode()
        with self.race(raw):target=self.read()
        self.assertEqual(target.player_id,value['player_id']);self.assertEqual(self.identity.read_bytes(),raw)
        self.assertFalse(list(self.identities.glob('.identity-*.tmp')))

    def test_intervening_damaged_identity_is_preserved_and_refused(self):
        with self.race(b'{}'):
            with self.assertRaises(ValueError):self.read()
        self.assertEqual(self.identity.read_bytes(),b'{}')
        self.assertFalse(list(self.identities.glob('.identity-*.tmp')))

    def test_flush_failure_leaves_no_published_identity_and_retry_is_stable(self):
        with mock.patch.object(rc_setup.os,'fsync',side_effect=OSError('authored flush failure')):
            with self.assertRaises(OSError):self.read()
        self.assertFalse(self.identity.exists());self.assertFalse(list(self.identities.glob('.identity-*.tmp')))
        first=self.read();before=self.identity.read_bytes()
        self.assertEqual(self.read().player_id,first.player_id);self.assertEqual(self.identity.read_bytes(),before)


if __name__=='__main__':unittest.main()
