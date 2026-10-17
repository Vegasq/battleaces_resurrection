"""Actual TLS admission/protocol tests with ephemeral PKI and an in-memory store.

Credential-store persistence and Windows private ACLs have separate tests. The
store substitution here lets cancellation/rate tests control verification timing.
"""
import asyncio
from pathlib import Path
import secrets
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import ssl
import unittest
import uuid
from unittest import mock

from server import admission as a, protocol as p, tls_transport as tls
from server.credentials import AuthenticationError
from server.dedicated_server import DedicatedServer
from server.profiles import ProfileStore
from tests.synthetic import template as synthetic_template
from tests.test_tls_transport import generate_test_pki, remove_test_pki

ROOT = Path(__file__).resolve().parents[1]


class Store:
    def __init__(self):
        self.token = 'ba1_' + secrets.token_urlsafe(32)
        self.player = 'p_' + secrets.token_hex(16)
        self.revoked, self.calls, self.failure = False, 0, None
        self.started, self.release = threading.Event(), threading.Event()
        self.release.set()

    def authenticate(self, token):
        self.calls += 1
        self.started.set()
        if not self.release.wait(3):
            raise RuntimeError('test verification was not released')
        if self.failure:
            raise self.failure
        if self.revoked or token != self.token:
            raise AuthenticationError()
        return self.player


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT / 'local' / ('admission-tests-' + uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.folder)

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.folder)

    async def asyncSetUp(self):
        self.store = Store()
        self.gate = a.AdmissionController(self.store, timeout=1)
        self.context = tls.load_server_context(self.pki['cert'], self.pki['key'])
        self.client_tls = tls.load_client_context(self.pki['ca'], 'localhost')
        self.writers, self.handlers, self.categories, self.identities = [], set(), [], []
        self.listener = self.coordinator = None

    async def asyncTearDown(self):
        self.store.release.set()
        for writer in self.writers:
            await tls.close_tls_stream(writer)
        if self.coordinator:
            await self.coordinator.close()
        if self.listener:
            self.listener.close()
            await self.listener.wait_closed()
        await asyncio.gather(*list(self.handlers), return_exceptions=True)
        await asyncio.gather(*list(self.gate.verifications), return_exceptions=True)
        await self.gate.close()

    async def start(self):
        async def handle(reader, writer):
            task = asyncio.current_task()
            self.handlers.add(task)
            try:
                self.identities.append(await self.gate.authenticate(reader, writer))
                await reader.read()
            except a.AdmissionError as error:
                self.categories.append(error.category)
                writer.write(p.encode(p.ERROR, b'authentication failed'))
                await writer.drain()
            finally:
                await tls.close_tls_stream(writer)
                self.handlers.discard(task)
        self.listener = await tls.start_tls_server(handle, '127.0.0.1', 0, self.context)
        return self.listener.sockets[0].getsockname()[1]

    async def connect(self, port):
        reader, writer = await tls.open_verified_connection('127.0.0.1', port, self.client_tls)
        self.writers.append(writer)
        return reader, writer

    async def wait_until(self, condition):
        async with asyncio.timeout(2):
            while not condition():
                await asyncio.sleep(.005)

    async def test_verified_tls_authentication_returns_only_bound_identity(self):
        reader, writer = await self.connect(await self.start())
        player = await a.authenticate_client(reader, writer, self.store.token)
        self.assertEqual(player, self.store.player)
        self.assertEqual(self.identities, [player])
        self.assertEqual(self.gate.pending, 0)

    async def test_revoked_credential_has_generic_error(self):
        self.store.revoked = True
        reader, writer = await self.connect(await self.start())
        writer.write(p.encode(a.AUTH, struct.pack('<H', a.AUTH_VERSION) + self.store.token.encode()))
        kind, payload = await p.receive(reader)
        self.assertEqual((kind, payload), (p.ERROR, b'authentication failed'))
        self.assertEqual(self.categories, ['invalid'])
        self.assertEqual(self.identities, [])

    async def test_oversized_auth_rejected_before_reading_its_body(self):
        reader, writer = await self.connect(await self.start())
        writer.write(struct.pack('<I', a.MAX_AUTH_BODY + 1))
        self.assertEqual(await asyncio.wait_for(p.receive(reader), .5), (p.ERROR, b'authentication failed'))
        self.assertEqual(self.store.calls, 0)
        self.assertEqual(self.categories, ['protocol'])

    async def test_game_hello_cannot_skip_authentication(self):
        reader, writer = await self.connect(await self.start())
        writer.write(p.encode(p.HELLO, p.hello(255, self.store.player, 'Player')))
        self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
        self.assertEqual(self.store.calls, 0)

    async def test_authentication_read_deadline_releases_capacity(self):
        self.gate.timeout = .05
        reader, writer = await self.connect(await self.start())
        self.assertEqual(await asyncio.wait_for(p.receive(reader), 1), (p.ERROR, b'authentication failed'))
        self.assertEqual(self.gate.pending, 0)
        self.assertEqual(self.categories, ['timeout'])

    async def test_verification_timeout_retains_capacity_until_thread_finishes(self):
        self.gate.timeout, self.gate.max_pending = .05, 1
        self.store.release.clear()
        port = await self.start()
        reader, writer = await self.connect(port)
        writer.write(p.encode(a.AUTH, struct.pack('<H', 1) + self.store.token.encode()))
        self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
        self.assertTrue(self.store.started.is_set())
        self.assertEqual(self.gate.pending, 1)
        second_reader, second_writer = await self.connect(port)
        self.assertEqual(await p.receive(second_reader), (p.ERROR, b'authentication failed'))
        self.assertEqual(self.categories, ['timeout', 'capacity'])
        self.store.release.set()
        await self.wait_until(lambda: self.gate.pending == 0)

    async def test_rate_limit_and_refill(self):
        now = [0.0]
        await self.gate.close()
        self.gate = a.AdmissionController(self.store, burst=2, attempts_per_second=.1, clock=lambda: now[0])
        port = await self.start()
        for _ in range(2):
            reader, writer = await self.connect(port)
            writer.write(p.encode(a.AUTH, b'invalid'))
            self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
        reader, writer = await self.connect(port)
        self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
        self.assertEqual(self.categories[-1], 'rate_limit')
        now[0] = 30.0
        reader, writer = await self.connect(port)
        self.assertEqual(await a.authenticate_client(reader, writer, self.store.token), self.store.player)

    async def test_rejected_attempts_preserve_fractional_refill(self):
        now = [0.0]
        await self.gate.close()
        self.gate = a.AdmissionController(self.store, burst=1, attempts_per_second=1, clock=lambda: now[0])
        port = await self.start()
        reader, writer = await self.connect(port)
        self.assertEqual(await a.authenticate_client(reader, writer, self.store.token), self.store.player)
        for instant in (.25, .5, .75):
            now[0] = instant
            reader, writer = await self.connect(port)
            self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
            self.assertEqual(self.categories[-1], 'rate_limit')
        now[0] = 1.0
        reader, writer = await self.connect(port)
        self.assertEqual(await a.authenticate_client(reader, writer, self.store.token), self.store.player)

    async def test_stalled_credentials_leave_default_executor_available(self):
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        self.store.release.clear()
        self.gate.timeout = .05
        reader, writer = await self.connect(await self.start())
        writer.write(p.encode(a.AUTH, struct.pack('<H', 1) + self.store.token.encode()))
        self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
        self.assertTrue(self.store.started.is_set())
        self.assertEqual(await asyncio.wait_for(asyncio.to_thread(lambda: 'available'), .2), 'available')

    async def test_keylogging_or_common_name_fallback_cannot_send_credentials(self):
        class UnsafeWriter:
            def __init__(self, keylog, common_name):
                context = SimpleNamespace(keylog_filename=keylog, verify_mode=ssl.CERT_REQUIRED,
                                          check_hostname=True, hostname_checks_common_name=common_name)
                self.tls = SimpleNamespace(version=lambda: 'TLSv1.3', context=context)
            def get_extra_info(self, name): return self.tls if name == 'ssl_object' else None
            def write(self, payload): raise AssertionError('unsafe credential write')
        for keylog, common_name in (('configured-key-log', False), (None, True)):
            with self.assertRaises(a.AdmissionError):
                await a.authenticate_client(asyncio.StreamReader(), UnsafeWriter(keylog, common_name), self.store.token)

    async def test_arbitrary_store_exception_text_is_not_exposed(self):
        self.store.failure = RuntimeError(self.store.token)
        reader, writer = await self.connect(await self.start())
        writer.write(p.encode(a.AUTH, struct.pack('<H', 1) + self.store.token.encode()))
        self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
        self.assertEqual(self.categories, ['internal'])

    async def test_plaintext_cannot_receive_a_client_credential(self):
        class PlainWriter:
            def get_extra_info(self, name): return None
            def write(self, payload): raise AssertionError('plaintext credential write')
        with self.assertRaises(a.AdmissionError):
            await a.authenticate_client(asyncio.StreamReader(), PlainWriter(), self.store.token)
        with self.assertRaises(a.AdmissionError):
            await self.gate.authenticate(asyncio.StreamReader(), PlainWriter())
        self.assertEqual(self.store.calls, 0)
        self.assertEqual(self.gate.pending, 0)

    async def test_shutdown_reports_unfinished_verification_without_cancelling_thread(self):
        self.gate.timeout = .05
        self.store.release.clear()
        reader, writer = await self.connect(await self.start())
        writer.write(p.encode(a.AUTH, struct.pack('<H', 1) + self.store.token.encode()))
        self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
        self.assertFalse(await self.gate.close(timeout=.02))
        self.assertEqual(self.gate.pending, 1)
        self.assertTrue(all(not task.cancelled() for task in self.gate.verifications))
        self.store.release.set()
        await self.wait_until(lambda: self.gate.pending == 0)
        self.assertTrue(await self.gate.close(timeout=.1))

    async def start_coordinator(self):
        template = synthetic_template()
        profiles = ProfileStore(self.folder / uuid.uuid4().hex, template)
        self.events = []
        self.coordinator = DedicatedServer(template, profiles, tls_context=self.context, admission=self.gate,
            audit=lambda event, **data: self.events.append((event, data)))
        return (await self.coordinator.start('127.0.0.1', 0))[1]

    async def test_coordinator_hello_is_bound_to_authenticated_profile(self):
        reader, writer = await self.connect(await self.start_coordinator())
        player = await a.authenticate_client(reader, writer, self.store.token)
        writer.write(p.encode(p.HELLO, p.hello(255, player, 'Private Player', 'friends')))
        kind, payload = await p.receive(reader)
        self.assertEqual(kind, p.WELCOME)
        self.assertEqual(next(iter(self.coordinator.peers)).profile_id, self.store.player)

    async def test_coordinator_rejects_impersonated_profile_without_echo(self):
        reader, writer = await self.connect(await self.start_coordinator())
        await a.authenticate_client(reader, writer, self.store.token)
        writer.write(p.encode(p.HELLO, p.hello(255, 'another-player', 'Name', 'friends')))
        self.assertEqual(await p.receive(reader), (p.ERROR, b'authentication failed'))
        self.assertFalse(self.coordinator.rooms)
        self.assertTrue(any(event == 'authentication_failed' and fields['category'] == 'identity_mismatch'
                            for event, fields in self.events))
        self.assertNotIn(self.store.token, str(self.events))

    async def test_shutdown_during_authentication_cannot_create_a_room(self):
        port = await self.start_coordinator()
        authenticate = self.gate.authenticate
        async def stop_after_auth(reader, writer):
            player = await authenticate(reader, writer)
            self.coordinator.closing = True
            return player
        with mock.patch.object(self.gate, 'authenticate', stop_after_auth):
            reader, writer = await self.connect(port)
            player = await a.authenticate_client(reader, writer, self.store.token)
            writer.write(p.encode(p.HELLO, p.hello(255, player, 'Player', 'friends')))
            kind, payload = await p.receive(reader)
        self.assertEqual((kind, payload), (p.ERROR, b'server stopped'))
        self.assertFalse(self.coordinator.rooms)

    async def test_plaintext_public_bind_and_partial_security_configuration_rejected(self):
        template = synthetic_template()
        profiles = ProfileStore(self.folder / uuid.uuid4().hex, template)
        for settings in ({'tls_context': self.context}, {'admission': self.gate}):
            with self.assertRaises(ValueError):
                DedicatedServer(template, profiles, **settings)
        coordinator = DedicatedServer(template, profiles)
        with self.assertRaisesRegex(ValueError, 'loopback'):
            await coordinator.start('0.0.0.0', 0)
        self.assertIsNone(coordinator.listener)
