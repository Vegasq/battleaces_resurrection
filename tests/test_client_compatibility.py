import asyncio
from pathlib import Path
import re
import unittest

from server import client_compatibility as policy, protocol as p, community_protocol as c
from tests.test_dedicated_server import DedicatedFixture, TestPeer


class ClientCompatibilityTests(DedicatedFixture):
    async def handshake(self, revision, *, community=False):
        reader, writer = await asyncio.open_connection(*self.address[:2])
        peer = TestPeer(reader, writer); self.clients.append(peer)
        payload = (c.hello('version-test', 'Version test', client_revision=revision) if community
                   else p.hello(0, 'version-test', 'Version test', client_revision=revision))
        await peer.send(c.HELLO if community else p.HELLO, payload)
        return peer

    async def test_legacy_client_rejected_before_presence_room_profile_or_worker(self):
        for community in (False, True):
            with self.subTest(community=community):
                if self.server is not None: await self.server.close()
                await self.start(minimum_client_revision=1)
                peer = await self.handshake(None, community=community)
                error = (await peer.receive(p.ERROR)).decode()
                self.assertTrue(error.startswith('BA_UPDATE_REQUIRED/1/Client update required'))
                self.assertFalse(self.server.rooms or self.server.community.sessions or self.workers)
                self.assertFalse(list((self.folder/'profiles').glob('*.json')))
                await peer.close()

    async def test_current_and_newer_clients_are_compatible(self):
        await self.start(minimum_client_revision=1)
        peer = await self.handshake(2)
        self.assertEqual(p.decode_welcome(await peer.receive(p.WELCOME))[0], 0)
        self.assertEqual(len(self.server.rooms), 1)

    async def test_rejection_contains_configured_plain_text(self):
        text = 'Client update required.\nGet the newest installer from GitHub Releases.'
        await self.start(minimum_client_revision=2, client_update_message=text)
        peer = await self.handshake(1, community=True)
        self.assertEqual((await peer.receive(p.ERROR)).decode(), policy.rejection(2, text))
        self.assertTrue(any(row['event']=='client_update_required' and row['client_revision']==1 for row in self.events))

    async def test_explicit_legacy_rollout_setting(self):
        await self.start(minimum_client_revision=0)
        peer = await self.handshake(None)
        await peer.receive(p.WELCOME)


class CompatibilityPolicyTests(unittest.TestCase):
    def test_revision_does_not_replace_build_and_protocol_validation(self):
        for revision in (None, 0, 1, 5):
            payload = p.hello(0, 'test', 'Test', client_revision=revision)
            self.assertEqual(p.client_revision(payload), revision or 0)
            self.assertEqual(p.decode_hello(payload)[:3], (0, 'test', 'Test'))
            with self.assertRaises(p.ProtocolError): p.decode_hello(payload[:3]+bytes(32)+payload[35:])

    def test_native_and_package_release_policy_agree(self):
        root=Path(__file__).resolve().parents[1]
        native=(root/'client_patch/src/client_compatibility.hpp').read_text()
        self.assertEqual(int(re.search(r'constexpr uint32_t revision=(\d+);',native)[1]),policy.CLIENT_REVISION)
        from tools.build_windows_packages import PACKAGE_VERSION
        self.assertIn(PACKAGE_VERSION, policy.DEFAULT_UPDATE_MESSAGE)

    def test_bounded_plain_text_policy(self):
        for minimum, text in ((True,'Update'),(-1,'Update'),(2**32,'Update'),(1,''),(1,'x'*161),(1,'bad\rtext'),(1,'bad\x00text')):
            with self.subTest(minimum=minimum,text=text), self.assertRaises(ValueError): policy.validate_policy(minimum,text)
