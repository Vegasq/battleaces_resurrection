"""Actual OS refusal/default TLS timeout and rejection of invented availability proof."""
import asyncio
import os
import time
import unittest
from server.tls_transport import open_verified_connection,rc_client_context,DEFAULT_HANDSHAKE_TIMEOUT
from tools.availability_endpoint import AvailabilityEndpoint
from tools.verify_packaged_play import network_availability_evidence,DRIVER


@unittest.skipUnless(os.name=='nt','native Windows endpoint/error qualification')
class OwnedEndpointTests(unittest.TestCase):
    def test_reserved_nonlistener_really_refuses_tcp(self):
        endpoint=AvailabilityEndpoint('rc-refused')
        try:
            with self.assertRaises(ConnectionRefusedError) as caught:
                asyncio.run(open_verified_connection('127.0.0.1',endpoint.port,rc_client_context('127.0.0.1')))
            # IOCP ConnectEx returns Win32 ERROR_CONNECTION_REFUSED(1225);
            # Winsock's WSAECONNREFUSED is10061. Both are actual OS refusals.
            self.assertTrue(caught.exception.winerror in (1225,10061) or caught.exception.errno==10061)
            self.assertFalse(endpoint.snapshot()['listening'])
            self.assertEqual(endpoint.snapshot()['peers'],[])
        finally:self.assertTrue(endpoint.close()['closed'])

    def test_real_tls_clienthello_reaches_unchanged_default_deadline(self):
        endpoint=AvailabilityEndpoint('rc-handshake-timeout');began=time.monotonic()
        try:
            with self.assertRaises((ConnectionAbortedError,TimeoutError)):
                asyncio.run(open_verified_connection('127.0.0.1',endpoint.port,rc_client_context('127.0.0.1')))
            self.assertGreaterEqual(time.monotonic()-began,DEFAULT_HANDSHAKE_TIMEOUT-.2)
            deadline=time.monotonic()+2
            while endpoint.snapshot()['live_peers']:
                self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            result=endpoint.snapshot()
            self.assertEqual(len(result['peers']),1)
            self.assertTrue(result['peers'][0]['client_hello'])
            self.assertTrue(result['peers'][0]['closed_by_client'])
            self.assertEqual(result['errors'],[])
        finally:
            result=endpoint.close()
            self.assertFalse(result['thread_alive'])
            self.assertEqual(result['owner_closed_peers'],0)


class AvailabilityEvidenceTests(unittest.TestCase):
    def proof(self):
        return dict(resolver_requests=1,availability_reasons=[],invite_reads=0,remote_connections=1,
            resolved_targets=[dict(host='127.0.0.1',port=12345,verify_certificate=False)],
            connection_attempts=[dict(host='127.0.0.1',port=12345,verify_certificate=False,
                connect_timeout=10.,handshake_timeout=5.,elapsed_seconds=5.01,
                error_type='ConnectionAbortedError',winerror=None,errno=None)],
            bridge_failures=[dict(session=1,code=2)])

    def test_driver_compiles_and_default_timeout_reason_is_not_fabricated(self):
        compile(DRIVER,'owned packaged driver','exec')
        report=network_availability_evidence(self.proof(),'Secure server unavailable','rc-handshake-timeout')
        self.assertEqual(report['bridge_codes'],[2])
        self.assertNotIn('authenticated',report)

    def test_no_shortened_timeout_success_wrong_route_or_reason_can_qualify(self):
        mutations=[('elapsed_seconds',.01),('elapsed_seconds',True),('elapsed_seconds',float('nan')),
                   ('handshake_timeout',.01),('connect_timeout',1.),('unexpected_success',True),
                   ('host','192.0.2.1'),('port',True),('verify_certificate',True)]
        for key,value in mutations:
            report=self.proof();report['connection_attempts'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(AssertionError):
                network_availability_evidence(report,'Secure server unavailable','rc-handshake-timeout')
        for field,value in (('resolver_requests',True),('availability_reasons',[8]),('invite_reads',1),
                            ('resolved_targets',[]),('bridge_failures',[dict(session=1,code=7)])):
            report=self.proof();report[field]=value
            with self.subTest(field=field),self.assertRaises(AssertionError):
                network_availability_evidence(report,'Secure server unavailable','rc-handshake-timeout')
        with self.assertRaises(AssertionError):
            network_availability_evidence(self.proof(),'','rc-handshake-timeout')

    def test_refusal_requires_os_error_not_a_local_settings_rejection(self):
        report=self.proof();report['connection_attempts'][0].update(error_type='ConnectionRefusedError',
            elapsed_seconds=.01,winerror=10061,errno=10061)
        self.assertEqual(network_availability_evidence(report,'Secure server unavailable','rc-refused')['bridge_codes'],[2])
        report['connection_attempts'][0].update(winerror=1225,errno=22)
        self.assertEqual(network_availability_evidence(report,'Secure server unavailable','rc-refused')['bridge_codes'],[2])
        report['connection_attempts'][0]['winerror']=report['connection_attempts'][0]['errno']=None
        with self.assertRaises(AssertionError):network_availability_evidence(report,'Secure server unavailable','rc-refused')


if __name__=='__main__':unittest.main()
