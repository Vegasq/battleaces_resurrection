"""Prepared SCM operator boundaries; no service registration or private writes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from server.windows_service import registration
from tools import verify_scm_operator as diagnostic


class PreparedServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='scm186-test-',dir=diagnostic.ROOT/'local')
        self.root=Path(self.directory.name)
        self.package=self.root/'package';self.out=self.root/'output'
        runtime=self.package/'program/runtime/python.exe';runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b'authored executable placeholder; never run')
        (self.package/'package-manifest.json').write_text('{}')
        path=self.out/'config/host.json';path.parent.mkdir(parents=True)
        settings=json.loads((diagnostic.ROOT/'server/host-config.example.json').read_bytes())
        settings.update(schema=2,access_mode='rc-open',listen_host='127.0.0.1',listen_port=49713,
            assets_directory=str(self.root/'assets'),data_directory=str(self.out/'data'),
            certificate_file=str(path.parent/'cert.pem'),private_key_file=str(path.parent/'key.pem'),
            credential_directory=None,allow_insecure_loopback=False,dashboard_port=0)
        path.write_text(json.dumps(settings))
        name='BattleAcesDiag186_123456abcdef'
        self.plan=dict(output=str(self.out),package=str(self.package),runtime=str(runtime),config=str(path),
            service_name=name,binary_path=registration(self.package,path,name)['binary_path'],
            probe_script=str(diagnostic.ROOT/'tools/verify_scm_operator.py'),
            wrapper_script=str(diagnostic.ROOT/'tools/Run-SCMCheck.ps1'),
            config_sha256=diagnostic.digest(path),package_manifest_sha256=diagnostic.digest(self.package/'package-manifest.json'),
            source_sha256={str(diagnostic.ROOT/'tools'/name):diagnostic.digest(diagnostic.ROOT/'tools'/name)
                for name in ('verify_scm_operator.py','Run-SCMCheck.ps1','verify_server_recovery.py','server_console_match.py')})
        self.plan_path=self.out/'plan.json'
        # Synthetic package only; production config, paths, command and source pins execute normally.
        self.verifier=mock.patch('tools.package_integrity.verify');self.verifier.start()

    def tearDown(self):
        self.verifier.stop();self.directory.cleanup()

    def check(self,plan=None):
        self.plan_path.write_text(json.dumps(self.plan if plan is None else plan))
        return diagnostic.verify_plan(self.plan_path)

    def test_complete_bound_plan(self):
        plan,config=self.check()
        self.assertEqual(plan['service_name'],self.plan['service_name'])
        self.assertEqual(config.data_directory,self.out/'data')

    def test_missing_and_changed_source_pins_refuse(self):
        for mode in ('missing','changed'):
            with self.subTest(mode=mode):
                plan=copy.deepcopy(self.plan);key=next(iter(plan['source_sha256']))
                if mode=='missing':plan['source_sha256'].pop(key)
                else:plan['source_sha256'][key]='0'*64
                with self.assertRaisesRegex(AssertionError,'source'):self.check(plan)

    def test_unrelated_service_name_and_runtime_refuse(self):
        for field,value in (('service_name','BattleAcesResurrection'),('runtime',str(self.root/'another.exe')),
                            ('probe_script',str(self.root/'another.py')),('output',str(self.root))):
            with self.subTest(field=field):
                with self.assertRaises(AssertionError):self.check(dict(self.plan,**{field:value}))

    def test_changed_config_or_image_path_refuse(self):
        with self.assertRaisesRegex(AssertionError,'registration'):
            self.check(dict(self.plan,binary_path='an unrelated service command'))
        path=Path(self.plan['config']);value=json.loads(path.read_bytes());value['listen_port']+=1
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(AssertionError,'config changed'):self.check()

    def test_public_listener_cannot_be_enabled_even_with_new_config_hash(self):
        path=Path(self.plan['config']);value=json.loads(path.read_bytes());value['listen_host']='0.0.0.0'
        path.write_text(json.dumps(value));self.plan['config_sha256']=diagnostic.digest(path)
        with self.assertRaisesRegex(AssertionError,'listener/data'):self.check()

    def test_wait_responds_to_owned_abort(self):
        cycle=self.out/'cycle-1';cycle.mkdir()
        (self.out/'operator-abort').write_text('abort')
        with self.assertRaisesRegex(AssertionError,'cancelled'):
            diagnostic.wait_file(cycle/'absent',5)


if __name__=='__main__':unittest.main()
