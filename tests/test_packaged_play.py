"""Real owned job accounting; no proprietary game or fixture data."""
import os
import json
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock
import uuid
from client_patch.transport import client, launcher
from client_patch.transport.bridge import RemoteUnavailable
from server.worker_client import _WindowsJob
from tools.verify_packaged_play import job_accounting, availability_settings, availability_evidence, owned_display_name, owned_profile


class PackagedAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.base=Path(__file__).resolve().parents[1]/'local'
        self.folder=self.base/('packaged-availability-'+uuid.uuid4().hex)
        self.folder.mkdir(parents=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.folder.resolve().relative_to(self.base.resolve())
        shutil.rmtree(self.folder)

    def test_actual_resolver_rejects_each_fixture_before_invite_access(self):
        game=self.folder/'game'
        defaults=client.defaults(game)
        for state,reason in (('unconfigured',8),('missing-files',8),('invalid-trust',9)):
            with self.subTest(state=state):
                fixtures=self.folder/state
                value=availability_settings(defaults,state,fixtures)
                path=self.folder/(state+'.json')
                path.write_text(json.dumps(value))
                resolver=launcher.RemoteConfigResolver(path,game,config_loader=client.load_connection)
                with mock.patch.object(launcher,'read_credential_file',side_effect=AssertionError('invite must not be read')) as reader:
                    with self.assertRaises(RemoteUnavailable) as caught:resolver.read()
                    self.assertEqual(caught.exception.reason,reason)
                    reader.assert_not_called()
                self.assertEqual(path.read_text(),json.dumps(value))
                if state=='missing-files':self.assertFalse(fixtures.exists())
        self.assertEqual(defaults,client.defaults(game))

    def test_existing_fixture_refused_instead_of_overwritten(self):
        fixture=self.folder/'existing'
        fixture.mkdir()
        marker=fixture/'ca.pem';marker.write_bytes(b'keep original')
        with self.assertRaises(AssertionError):
            availability_settings(client.defaults(self.folder/'game'),'invalid-trust',fixture)
        self.assertEqual(marker.read_bytes(),b'keep original')

    def test_long_fixture_uses_valid_maximum_name_and_profile_even_with_short_bot(self):
        value=client.defaults(self.folder/'game')
        value.update(display_name=owned_display_name(True),local_profile=owned_profile(True))
        self.assertEqual(len(value['display_name']),32)
        self.assertEqual(len(value['local_profile']),48)
        client.local_settings(value,self.folder/'client.json')
        # A logical Windows root keeps the boundary test independent of checkout
        # depth and does not create any file on that drive.
        game=PureWindowsPath('E:/'+('g'*80))
        self.assertEqual(launcher.native_storage_preflight(dict(game_directory=game,local_profile=value['local_profile'])),value['local_profile'])
        shortest_replay=f"{value['display_name']}-Aliased-vs-X-Aliased-build-37822_2026.10.20-11.43.33.rep"
        path=game/'.battleaces-resurrection/profiles'/value['local_profile']/'AutoSaveReplays'/shortest_replay
        self.assertGreater(len(str(path)),260)
        self.assertEqual(owned_display_name(),'Packaged Gameplay')

    def test_wrong_native_code_or_connection_cannot_qualify_availability(self):
        report=dict(resolver_requests=1,availability_reasons=[9],remote_connections=0,invite_reads=0)
        text='Online connection settings are invalid; localWorldUnaffected=1'
        proof=availability_evidence(report,text,'invalid-trust')
        self.assertEqual(proof['reasons'],[9])
        self.assertEqual(proof['remote_tls_open_calls'],0)
        self.assertNotIn('sockets_opened',proof)
        for changed in (dict(report,availability_reasons=[8]),dict(report,resolver_requests=0),
                        dict(report,resolver_requests=True),dict(report,resolver_requests=3),
                        dict(report,remote_connections=1),dict(report,invite_reads=1)):
            with self.subTest(changed=changed),self.assertRaises(AssertionError):
                availability_evidence(changed,text,'invalid-trust')
        with self.assertRaises(AssertionError):availability_evidence(report,text,'unconfigured')
        with self.assertRaises(AssertionError):availability_evidence(report,'','invalid-trust')


@unittest.skipUnless(os.name=='nt','Windows job accounting')
class PackagedPlayJobTests(unittest.TestCase):
    def test_natural_child_exit_is_observed_before_job_close(self):
        process=subprocess.Popen([sys.executable,'-I','-B','-c','import sys; sys.stdin.buffer.read(1)'],stdin=subprocess.PIPE)
        job=None
        try:
            job=_WindowsJob(process.pid)
            self.assertGreaterEqual(job_accounting(job.handle)['active_processes'],1)
            process.stdin.write(b'x');process.stdin.flush();process.stdin.close()
            self.assertEqual(process.wait(timeout=5),0)
            deadline=time.monotonic()+5
            while job_accounting(job.handle)['active_processes']:
                self.assertLess(time.monotonic(),deadline)
                time.sleep(.02)
            self.assertGreaterEqual(job_accounting(job.handle)['total_processes'],1)
        finally:
            if job is not None:job.close()
            if process.poll() is None:process.kill();process.wait(timeout=5)
            if process.stdin and not process.stdin.closed:process.stdin.close()
