"""Read-only protected-mode preflight controls; no console/native/ACL mocks pass as deployment."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from unittest import TestCase,mock

from tests.test_credentials import private_test_folder,remove_test_folder
from tools import verify_server_console as probe,build_windows_packages as builder


class ServerConsolePreflightTests(TestCase):
    def setUp(self):
        self.root=private_test_folder('server-console-preflight-')
        self.package=self.root/'package';self.package.mkdir()
        self.assets=self.root/'assets';self.assets.mkdir()
        (self.package/'program/launcher').mkdir(parents=True)
        (self.package/'Start Server.exe').write_bytes(b'authored nonexecutable fixture')
        (self.package/'package-manifest.json').write_text('{}')
        (self.assets/'asset-manifest.json').write_text('{}')
        self.production=('server/__init__.py',)
        self.launcher=('server/launcher/console_launcher.cpp',)
        (self.package/'program/launcher/launcher-build.json').write_text(json.dumps(dict(
            source_sha256={name:probe.digest(probe.ROOT/name) for name in self.launcher},
            argument_tests_passed=True,launcher_sha256=probe.digest(self.package/'Start Server.exe'))))

    def tearDown(self):remove_test_folder(self.root)

    def invoke(self,*,restricted,preflight=False,stale=False):
        inventory=dict(files={'program/app/'+name:dict(sha256='0'*64 if stale else probe.digest(probe.ROOT/name))
                              for name in self.production})
        with (mock.patch.object(builder,'SERVER',self.production),mock.patch.object(builder,'LAUNCHER_SOURCES',self.launcher),
              mock.patch('tools.package_integrity.verify',return_value=inventory),
              mock.patch('server.assets.verify_assets',return_value={'authored':True}),
              mock.patch('tools.verify_owner_credentials.restricting_sids_present',return_value=restricted),
              mock.patch('tests.test_tls_transport.generate_test_pki',side_effect=AssertionError('PKI forbidden')) as pki,
              mock.patch.object(probe.subprocess,'Popen',side_effect=AssertionError('process forbidden')) as process,
              redirect_stdout(io.StringIO())):
            code=probe.run(self.package,self.assets,self.root/'output',preflight_only=preflight)
            pki.assert_not_called();process.assert_not_called()
        report=json.loads((self.root/'output/verification.json').read_bytes())
        self.assertFalse(report['passed'])
        self.assertFalse(report['protected_operations_attempted'])
        self.assertFalse(report['controller_started'])
        self.assertFalse(report['forced_cleanup'])
        return code,report

    def test_restricted_token_refuses_before_protected_apis_even_without_preflight_flag(self):
        code,report=self.invoke(restricted=True)
        self.assertEqual(code,2)
        self.assertEqual(report['stage'],'normal_owner_required')

    def test_normal_owner_readiness_is_not_a_full_console_pass(self):
        code,report=self.invoke(restricted=False,preflight=True)
        self.assertEqual(code,0)
        self.assertEqual(report['stage'],'preflight_ready')

    def test_different_bundled_production_code_is_refused_before_private_or_process_work(self):
        code,report=self.invoke(restricted=False,stale=True)
        self.assertEqual(code,1)
        self.assertEqual(report['error_type'],'AssertionError')


class OwnedJobDrainTests(TestCase):
    def exercise(self,sequence,*,late=False):
        now=[0.0];seen=[];index=[0]
        def query(handle):
            seen.append(handle);value=sequence[min(index[0],len(sequence)-1)];index[0]+=1
            if late and index[0]>1:now[0]=6.0
            return dict(total_processes=3,active_processes=value[0],total_terminated_processes=value[1])
        def sleep(seconds):now[0]+=seconds
        result=probe.settle_job('authored-owned-handle',query=query,inspect=lambda h:[dict(pid=17,image='authored.exe')],
                                clock=lambda:now[0],sleep=sleep)
        self.assertTrue(all(handle=='authored-owned-handle' for handle in seen))
        return result

    def test_natural_delayed_job_accounting_is_observed_before_close(self):
        result=self.exercise([(1,0),(1,0),(0,0)])
        self.assertTrue(result['naturally_empty'])
        self.assertEqual(len(result['samples']),3)
        self.assertEqual(result['samples'][0]['processes'],[dict(pid=17,image='authored.exe')])

    def test_persistent_owned_process_is_not_turned_into_a_success(self):
        result=self.exercise([(1,0)])
        self.assertFalse(result['naturally_empty'])
        self.assertGreaterEqual(result['elapsed_seconds'],5)
        self.assertEqual(result['final']['active_processes'],1)

    def test_zero_after_forced_job_termination_cannot_qualify_natural_shutdown(self):
        self.assertFalse(self.exercise([(0,1)])['naturally_empty'])

    def test_empty_observed_after_deadline_cannot_qualify(self):
        self.assertFalse(self.exercise([(1,0),(0,0)],late=True)['naturally_empty'])
