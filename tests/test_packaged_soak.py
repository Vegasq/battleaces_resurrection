"""RC TLS admission/cleanup and packaged diagnostic output boundaries."""
import json
import unittest
from unittest import mock
from server import admission,rc_host,tls_transport
from tools import soak_server as soak,run_packaged_soak as packaged
from tests.test_dedicated_server import DedicatedFixture,wait_until


class SoakPathTests(unittest.TestCase):
    def test_output_refuses_source_or_package_asset_subtrees_before_creating(self):
        package=packaged.ROOT/'local/soak157-fixture-package'
        assets=packaged.ROOT/'local/soak157-fixture-assets'
        for output in (package,assets,package/'subdir',assets/'subdir',packaged.ROOT/'server/soak157-fixture'):
            with self.subTest(output=output),self.assertRaises(ValueError):packaged.run(package,assets,output)
            self.assertFalse(output.exists())

    def test_tls_is_explicit_and_original_duration_round_bounds_stay_in_force(self):
        base=['--assets','authored','--output','authored-output']
        self.assertFalse(soak.arguments(base).rc_tls)
        self.assertTrue(soak.arguments(base+['--rc-tls']).rc_tls)
        with mock.patch('sys.stderr'),self.assertRaises(SystemExit):soak.arguments(base+['--seconds','9'])


class SoakTLSTests(DedicatedFixture):
    async def start_tls(self):
        cert,key=rc_host.generate_certificate()
        (self.folder/'server.pem').write_bytes(cert);(self.folder/'server.key').write_bytes(key)
        context=tls_transport.load_server_context(self.folder/'server.pem',self.folder/'server.key')
        await self.start(tls_context=context,admission=admission.AdmissionController(None,rc_open=True))
        runner=soak.Soak.__new__(soak.Soak)
        runner.tls_context=context;runner.address=self.address;runner.peers=[];runner.report={'authentication':[]}
        return runner

    async def test_actual_tls_rc_identity_and_persistent_community_peer(self):
        runner=await self.start_tls()
        try:
            first,second=await runner.connect('unused-first'),await runner.connect('unused-second')
            self.assertNotEqual(first.profile,second.profile)
            self.assertEqual(set(self.server.community.sessions),{first.profile,second.profile})
            self.assertEqual(self.server.community.sessions[first.profile].peer.name,'Soak unused-first')
            self.assertEqual(len(runner.report['authentication']),2)
            for row in runner.report['authentication']:
                self.assertTrue(row['authenticated']);self.assertFalse(row['certificate_verified'])
                self.assertIn(row['tls_version'],('TLSv1.2','TLSv1.3'))
            self.assertNotIn('ba1_',json.dumps(runner.report))
            await first.command(soak.c.REFRESH)
        finally:
            for peer in runner.peers:await peer.close()

    async def test_auth_failure_closes_tls_stream_before_pump_ownership(self):
        runner=await self.start_tls()
        error=ValueError('authored admission failure')
        with mock.patch.object(admission,'authenticate_client',mock.AsyncMock(side_effect=error)):
            with self.assertRaises(ValueError) as caught:await runner.connect('unused')
        self.assertIs(caught.exception,error);self.assertFalse(runner.peers)
        self.assertFalse(runner.report['authentication'])
        await wait_until(lambda:not self.server.peers)


if __name__=='__main__':unittest.main()
