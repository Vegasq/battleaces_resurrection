"""Installed build identity and credential-free endpoint display boundaries."""
import unittest
from client_patch.transport import client_info as info
from client_patch.transport import bridge


class ClientInfoTests(unittest.TestCase):
    def test_build_uses_installed_manifest_release_and_source_not_protocol_revision(self):
        manifest = dict(versions=dict(package='0.5.0-rc1', client_revision=1, game_build=37822),
                        source=dict(revision='a1b2c3d'+'0'*33, dirty=False))
        self.assertEqual(info.build_label(manifest), '0.5.0-rc1 (build a1b2c3d)')
        manifest['source']['dirty'] = True
        self.assertEqual(info.build_label(manifest), '0.5.0-rc1 (build a1b2c3d, modified)')
        self.assertEqual(info.build_label(None), 'Development (build unknown)')
        for malformed in ({},dict(versions={}),dict(versions={'package':'0.5.0-rc1'},source=None)):
            with self.assertRaises(ValueError): info.build_label(malformed)
        for version in ('<b>release</b>', 'bad\nlabel', 'x'*65):
            manifest['versions']['package'] = version
            with self.assertRaises(ValueError): info.build_label(manifest)

    def test_endpoint_codec_is_bounded_public_ascii_and_literal(self):
        for fields in (('',0,''), ('ba.sendsignal.cc',47623,'165.227.125.73'),
                       ('127.0.0.1',47623,'127.0.0.1'), ('::1',47623,'::1')):
            payload = info.target_bytes(*fields)
            self.assertEqual(info.read_target(payload), fields)
            bridge.encode(bridge.STATUS,1,payload,version=2)
            with self.assertRaises(bridge.BridgeProtocolError): bridge.encode(bridge.STATUS,1,payload)
        self.assertEqual(info.endpoint_label('ba.sendsignal.cc',47623,'165.227.125.73'),
                         'ba.sendsignal.cc:47623 (165.227.125.73)')
        self.assertEqual(info.endpoint_label('127.0.0.1',47623,'127.0.0.1'),'127.0.0.1:47623')
        self.assertEqual(info.endpoint_label('::1',47623,'::1'),'[::1]:47623')
        valid = info.target_bytes('server.example',47623)
        for bad in (b'',valid[:-1],valid+b'extra',b'\x02'+valid[1:],b'\x01\0\1\0\0'):
            with self.assertRaises(bridge.BridgeProtocolError): bridge.encode(bridge.STATUS,1,bad,version=2)
        for host in ('https://server.example','<b>server</b>','name@server','server\nprivate'):
            self.assertEqual(info.configured_label(dict(server_host=host,server_port=47623)),'')


if __name__=='__main__': unittest.main()
