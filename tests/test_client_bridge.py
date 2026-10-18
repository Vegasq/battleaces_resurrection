"""Actual private socketpair -> verified TLS -> AUTH -> coordinator lobby tests."""
import asyncio
import json
from pathlib import Path
import socket
import os
import subprocess
import struct
import unittest
import uuid
from unittest import mock

from client_patch.transport import bridge as b
from client_patch.transport import launcher as launch
from server import admission as a, protocol as p, tls_transport as tls
from server.dedicated_server import DedicatedServer
from server.profiles import ProfileStore
from tests.synthetic import template as synthetic_template
from tests.test_admission import Store
from tests.test_tls_transport import generate_test_pki, remove_test_pki

ROOT = Path(__file__).resolve().parents[1]


class BridgeFramingTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_framing_and_invalid_version(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b.encode(b.DATA, 1, b'authored bytes'))
        self.assertEqual(await b.receive(reader), (b.DATA, 1, b'authored bytes'))
        for encoded in (struct.pack('<I', b.MAX_BODY + 1), struct.pack('<IBBI', 6, 2, b.OPEN, 1)):
            reader = asyncio.StreamReader()
            reader.feed_data(encoded)
            with self.assertRaises(b.BridgeProtocolError): await b.receive(reader)

    def test_invalid_payloads_and_ids_rejected(self):
        for kind, identity, payload in ((b.OPEN, 0, b''), (b.OPEN, 1, b'extra'),
                (b.DATA, 1, b''), (b.DATA, 1, b'x' * (b.CHUNK + 1)), (b.FAILURE, 1, b'unknown')):
            with self.assertRaises(b.BridgeProtocolError): b.encode(kind, identity, payload)

    async def test_v2_ready_is_bounded_canonical_and_version_specific(self):
        profile = ('p_' + '1a' * 16).encode()
        reader = asyncio.StreamReader()
        reader.feed_data(b.encode(b.READY, 1, profile, version=2))
        self.assertEqual(await b.receive(reader, version=2), (b.READY, 1, profile))
        for invalid in (b'', profile[:-1], profile.upper(), b'p_' + b'g' * 32, b'p_' + b'\xff' * 32):
            with self.assertRaises(b.BridgeProtocolError): b.encode(b.READY, 1, invalid, version=2)
        with self.assertRaises(b.BridgeProtocolError): b.encode(b.READY, 1, profile)
        for code in (8, 9):
            b.encode(b.FAILURE, 1, bytes([code]), version=2)
            with self.assertRaises(b.BridgeProtocolError): b.encode(b.FAILURE, 1, bytes([code]))
        for version in (True, 0, 3):
            with self.assertRaises(b.BridgeProtocolError): b.encode(b.OPEN, 1, version=version)


class ClientBridgeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT / 'local' / ('client-bridge-' + uuid.uuid4().hex)
        try: cls.pki = generate_test_pki(cls.folder)
        except BaseException:
            if cls.folder.exists(): remove_test_pki(cls.folder)
            raise

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.folder)

    async def asyncSetUp(self):
        self.store = Store()
        self.gate = a.AdmissionController(self.store)
        template = synthetic_template()
        self.events, self.loop_errors = [], []
        self.loop = asyncio.get_running_loop()
        self.previous_handler = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, data: self.loop_errors.append(data))
        self.server = DedicatedServer(template, ProfileStore(self.folder / uuid.uuid4().hex, template),
            tls_context=tls.load_server_context(self.pki['cert'], self.pki['key']), admission=self.gate,
            audit=lambda event, **data: self.events.append((event, data)))
        self.port = (await self.server.start('127.0.0.1', 0))[1]
        self.bridge, self.bridge_task, self.writer = None, None, None

    async def asyncTearDown(self):
        if self.writer:
            self.writer.close()
            try: await self.writer.wait_closed()
            except OSError: pass
        if self.bridge_task:
            await asyncio.wait_for(self.bridge_task, 3)
        await self.server.close()
        self.loop.set_exception_handler(self.previous_handler)
        self.assertEqual(self.loop_errors, [])

    def remote(self, *, expected='localhost', player=None, token=None):
        return b.Remote('127.0.0.1', self.port, tls.load_client_context(self.pki['ca'], expected),
                        player or self.store.player, token or self.store.token)

    async def start_bridge(self, *, expected='localhost', player=None, token=None, version=1, resolver=None):
        parent, child = socket.socketpair()
        parent.setblocking(False); child.setblocking(False)
        server_reader, server_writer = await asyncio.open_connection(sock=parent)
        self.reader, self.writer = await asyncio.open_connection(sock=child)
        remote = self.remote(expected=expected, player=player, token=token)
        self.assertNotIn(self.store.token, repr(remote))
        self.version = version
        self.bridge = b.Bridge(server_reader, server_writer, remote if resolver is None else resolver, version=version)
        self.bridge_task = asyncio.create_task(self.bridge.run())
        return self.bridge

    async def send(self, kind, identity, data=b''):
        self.writer.write(b.encode(kind, identity, data, version=self.version))
        await self.writer.drain()

    async def frame(self):
        return await asyncio.wait_for(b.receive(self.reader, version=self.version), 3)

    async def hello(self, identity):
        await self.send(b.OPEN, identity)
        if self.version == 2:
            self.assertEqual(await self.frame(), (b.READY, identity, self.store.player.encode()))
        hello = p.encode(p.HELLO, p.hello(255, self.store.player, 'Invited Player', 'friends'))
        # Game stream fragmentation must be independent of IPC/TLS boundaries.
        await self.send(b.DATA, identity, hello[:3])
        await self.send(b.DATA, identity, hello[3:])
        data = bytearray()
        while len(data) < 4 or len(data) < struct.unpack_from('<I', data)[0] + 4:
            kind, received_id, body = await self.frame()
            self.assertEqual((kind, received_id), (b.DATA, identity))
            data.extend(body)
        self.assertEqual(data[4], p.WELCOME)
        return bytes(data)

    async def test_private_bridge_authenticates_before_identity_bound_lobby(self):
        await self.start_bridge()
        data = await self.hello(1)
        self.assertNotIn(self.store.token.encode(), data)
        self.assertEqual(next(iter(self.server.peers)).profile_id, self.store.player)
        self.assertEqual(self.store.calls, 1)

    async def test_same_private_connection_reauthenticates_and_discards_old_session_data(self):
        await self.start_bridge()
        await self.hello(1)
        await self.send(b.CLOSE, 1)
        while (await self.frame())[:2] != (b.CLOSE, 1): pass
        await self.send(b.OPEN, 2)
        await self.send(b.DATA, 1, b'discard this retired session')
        await self.send(b.DATA, 2, p.encode(p.HELLO, p.hello(255, self.store.player, 'Invited Player', 'friends')))
        kind, identity, body = await self.frame()
        self.assertEqual((kind, identity, body[4]), (b.DATA, 2, p.WELCOME))
        self.assertEqual(self.store.calls, 2)
        self.assertEqual(len(self.server.peers), 1)

    async def test_wrong_certificate_name_never_sends_token_or_game_hello(self):
        await self.start_bridge(expected='wrong.invalid')
        await self.send(b.OPEN, 1)
        await self.send(b.DATA, 1, b'game bytes')
        self.assertEqual(await self.frame(), (b.FAILURE, 1, bytes([b.TLS_FAILURE])))
        self.assertEqual(self.store.calls, 0)
        self.assertEqual(self.server.rooms, {})

    async def test_revoked_invite_fails_on_next_session(self):
        await self.start_bridge()
        await self.hello(1)
        await self.send(b.CLOSE, 1)
        while (await self.frame())[:2] != (b.CLOSE, 1): pass
        self.store.revoked = True
        await self.send(b.OPEN, 2)
        self.assertEqual(await self.frame(), (b.FAILURE, 2, bytes([b.AUTH_FAILURE])))
        self.assertEqual(self.store.calls, 2)

    async def test_auth_identity_mismatch_never_forwards_game_bytes(self):
        await self.start_bridge(player='p_' + '0' * 32)
        await self.send(b.OPEN, 1)
        await self.send(b.DATA, 1, b'game bytes')
        self.assertEqual(await self.frame(), (b.FAILURE, 1, bytes([b.IDENTITY_FAILURE])))
        self.assertEqual(self.server.rooms, {})

    async def test_pending_connect_input_queue_is_bounded(self):
        entered = asyncio.Event()
        async def stalled(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        with mock.patch.object(tls, 'open_verified_connection', stalled):
            await self.start_bridge()
            await self.send(b.OPEN, 1)
            await asyncio.wait_for(entered.wait(), 1)
            for _ in range(b.QUEUE_BYTES // b.CHUNK + 1):
                await self.send(b.DATA, 1, b'x' * b.CHUNK)
            self.assertEqual(await self.frame(), (b.FAILURE, 1, bytes([b.QUEUE_FAILURE])))
            self.assertIsNone(self.bridge.session)
        self.assertEqual(self.store.calls, 0)

    async def test_out_of_order_session_id_closes_private_transport(self):
        await self.start_bridge()
        await self.send(b.OPEN, 2)
        self.assertEqual(await asyncio.wait_for(self.reader.read(1), 1), b'')
        await self.bridge_task
        self.assertEqual(self.store.calls, 0)

    async def test_oversized_header_is_rejected_without_body_or_remote_connection(self):
        await self.start_bridge()
        self.writer.write(struct.pack('<I', b.MAX_BODY + 1))
        await self.writer.drain()
        self.assertEqual(await asyncio.wait_for(self.reader.read(1), 1), b'')
        self.assertEqual(self.store.calls, 0)

    async def test_remote_eof_becomes_only_current_session_close(self):
        await self.start_bridge()
        await self.hello(1)
        for peer in list(self.server.peers): peer.close()
        while True:
            kind, identity, data = await self.frame()
            self.assertEqual(identity, 1)
            if kind == b.CLOSE: break
            self.assertEqual(kind, b.DATA)
        self.assertFalse(self.bridge_task.done())

    async def test_v2_unconfigured_then_reload_and_new_identity_on_same_stream(self):
        resolutions = 0
        async def resolve():
            nonlocal resolutions
            resolutions += 1
            if resolutions == 1: raise b.RemoteUnavailable()
            return self.remote()
        await self.start_bridge(version=2, resolver=resolve)
        self.assertEqual(resolutions, 0)  # No remote or credentials required at spawn.
        await self.send(b.OPEN, 1)
        self.assertEqual(await self.frame(), (b.FAILURE, 1, bytes([b.UNCONFIGURED_FAILURE])))
        self.assertEqual(self.store.calls, 0)
        await self.hello(2)
        first_identity = self.store.player
        await self.send(b.CLOSE, 2)
        while (await self.frame())[:2] != (b.CLOSE, 2): pass
        self.store.player = 'p_' + uuid.uuid4().hex
        self.assertNotEqual(self.store.player, first_identity)
        await self.hello(3)
        await self.send(b.DATA, 2, b'retired identity bytes')
        self.assertEqual((resolutions, self.store.calls), (3, 2))
        self.assertEqual([peer.profile_id for peer in self.server.peers], [self.store.player])

    async def test_v2_retiring_pending_resolver_cancels_before_tls(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()
        resolutions = 0
        async def resolve():
            nonlocal resolutions
            resolutions += 1
            if resolutions == 1:
                entered.set()
                try: await asyncio.Event().wait()
                finally: cancelled.set()
            return self.remote()
        await self.start_bridge(version=2, resolver=resolve)
        await self.send(b.OPEN, 1)
        await asyncio.wait_for(entered.wait(), 1)
        await self.send(b.CLOSE, 1)
        self.assertEqual(await self.frame(), (b.CLOSE, 1, b''))
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.store.calls, 0)
        await self.hello(2)
        self.assertEqual(self.store.calls, 1)

    async def test_v2_data_before_authentication_closes_private_stream(self):
        entered = asyncio.Event()
        async def resolve():
            entered.set()
            await asyncio.Event().wait()
        await self.start_bridge(version=2, resolver=resolve)
        await self.send(b.OPEN, 1)
        await asyncio.wait_for(entered.wait(), 1)
        await self.send(b.DATA, 1, b'premature hello')
        self.assertEqual(await asyncio.wait_for(self.reader.read(1), 1), b'')
        self.assertEqual(self.store.calls, 0)

    async def test_v2_client_cannot_supply_ready_identity(self):
        await self.start_bridge(version=2)
        await self.send(b.READY, 1, self.store.player.encode())
        self.assertEqual(await asyncio.wait_for(self.reader.read(1), 1), b'')
        self.assertEqual(self.store.calls, 0)

    async def test_v2_authenticated_but_ready_not_queued_rejects_data(self):
        await self.start_bridge(version=2)
        async with self.bridge.send_lock:
            await self.send(b.OPEN, 1)
            async def authenticated():
                while self.bridge.session is None or not self.bridge.session.authenticated:
                    await asyncio.sleep(.001)
            await asyncio.wait_for(authenticated(), 3)
            self.assertFalse(self.bridge.session.ready_sent)
            await self.send(b.DATA, 1, b'hello before READY publication')
            self.assertEqual(await asyncio.wait_for(self.reader.read(1), 3), b'')
        self.assertEqual(self.store.calls, 1)
        self.assertEqual(self.server.rooms, {})

    async def test_v2_invalid_local_config_is_recoverable_and_never_authenticates(self):
        async def resolve(): return object()
        await self.start_bridge(version=2, resolver=resolve)
        for identity in (1, 2):
            await self.send(b.OPEN, identity)
            self.assertEqual(await self.frame(), (b.FAILURE, identity, bytes([b.CONFIG_FAILURE])))
        self.assertEqual(self.store.calls, 0)
        self.assertFalse(self.bridge_task.done())

    async def test_v2_wrong_certificate_has_no_ready_or_authentication(self):
        await self.start_bridge(version=2, expected='wrong.invalid')
        await self.send(b.OPEN, 1)
        self.assertEqual(await self.frame(), (b.FAILURE, 1, bytes([b.TLS_FAILURE])))
        self.assertEqual(self.store.calls, 0)

    async def test_v2_identity_mismatch_has_no_ready_or_lobby(self):
        await self.start_bridge(version=2, player='p_' + '0' * 32)
        await self.send(b.OPEN, 1)
        self.assertEqual(await self.frame(), (b.FAILURE, 1, bytes([b.IDENTITY_FAILURE])))
        self.assertEqual(self.server.rooms, {})

    async def test_v2_revocation_rechecked_before_next_ready(self):
        await self.start_bridge(version=2)
        await self.hello(1)
        await self.send(b.CLOSE, 1)
        while (await self.frame())[:2] != (b.CLOSE, 1): pass
        self.store.revoked = True
        await self.send(b.OPEN, 2)
        self.assertEqual(await self.frame(), (b.FAILURE, 2, bytes([b.AUTH_FAILURE])))
        self.assertEqual(self.store.calls, 2)

    async def test_v2_config_resolver_reloads_without_relaxing_trust_or_game_binding(self):
        path = self.folder / (uuid.uuid4().hex + '.json')
        invite = self.folder / (uuid.uuid4().hex + '-private-invite.json')
        game = self.folder / 'working-game'
        resolver = launch.RemoteConfigResolver(path, game)
        await self.start_bridge(version=2, resolver=resolver)
        await self.send(b.OPEN, 1)
        self.assertEqual(await self.frame(), (b.FAILURE, 1, bytes([b.UNCONFIGURED_FAILURE])))
        config = dict(schema=2, game_directory=str(game), server_host='127.0.0.1', server_port=self.port,
            server_name='localhost', ca_bundle=str(self.pki['ca']), credential_file=str(invite),
            display_name='Configured Player', room='friends')
        path.write_text(json.dumps(config), encoding='utf-8')
        await self.send(b.OPEN, 2)
        self.assertEqual(await self.frame(), (b.FAILURE, 2, bytes([b.UNCONFIGURED_FAILURE])))
        invite.write_text('authored private-file boundary fixture', encoding='utf-8')
        # Windows private-file permissions are qualified separately. TLS/name and
        # real server admission/identity binding are exercised here without mocks.
        def credential(selected):
            self.assertEqual(selected, invite)
            return dict(player_id=self.store.player, token=self.store.token)
        with mock.patch.object(launch, 'read_credential_file', side_effect=credential) as read:
            await self.hello(3)
            await self.send(b.CLOSE, 3)
            while (await self.frame())[:2] != (b.CLOSE, 3): pass
            self.store.player = 'p_' + uuid.uuid4().hex
            await self.hello(4)
            await self.send(b.CLOSE, 4)
            while (await self.frame())[:2] != (b.CLOSE, 4): pass
            config['server_name'] = 'wrong.invalid'
            path.write_text(json.dumps(config), encoding='utf-8')
            await self.send(b.OPEN, 5)
            self.assertEqual(await self.frame(), (b.FAILURE, 5, bytes([b.TLS_FAILURE])))
            config['game_directory'] = str(self.folder / 'different-game')
            path.write_text(json.dumps(config), encoding='utf-8')
            await self.send(b.OPEN, 6)
            self.assertEqual(await self.frame(), (b.FAILURE, 6, bytes([b.CONFIG_FAILURE])))
            self.assertEqual(read.call_count, 3)
        self.assertEqual(self.store.calls, 2)


    async def test_unified_settings_can_enable_verified_online_play_after_local_start(self):
        from client_patch.transport import client
        path = self.folder / (uuid.uuid4().hex + '.json')
        game = self.folder / 'working-game'
        invite = self.folder / (uuid.uuid4().hex + '-private-invite.json')
        config = client.defaults(game)
        path.write_text(json.dumps(config))
        resolver = launch.RemoteConfigResolver(path, game, config_loader=client.load_connection)
        await self.start_bridge(version=2, resolver=resolver)
        await self.send(b.OPEN, 1)
        self.assertEqual(await self.frame(), (b.FAILURE, 1, bytes([b.UNCONFIGURED_FAILURE])))
        config.update(server_host='127.0.0.1', server_port=self.port, server_name='localhost',
                      ca_bundle=str(self.pki['ca']), credential_file=str(invite))
        path.write_text(json.dumps(config))
        invite.write_text('authored private-file boundary fixture')
        with mock.patch.object(launch, 'read_credential_file', return_value=dict(player_id=self.store.player, token=self.store.token)) as read:
            await self.hello(2)
            await self.send(b.CLOSE, 2)
            while (await self.frame())[:2] != (b.CLOSE, 2): pass
            config['server_name'] = 'wrong.invalid'
            path.write_text(json.dumps(config))
            await self.send(b.OPEN, 3)
            self.assertEqual(await self.frame(), (b.FAILURE, 3, bytes([b.TLS_FAILURE])))
            config['game_directory'] = str(self.folder / 'different-game')
            path.write_text(json.dumps(config))
            await self.send(b.OPEN, 4)
            self.assertEqual(await self.frame(), (b.FAILURE, 4, bytes([b.CONFIG_FAILURE])))
            self.assertEqual(read.call_count, 2)
        self.assertEqual(self.store.calls, 1)
        self.assertFalse(self.bridge_task.done())


@unittest.skipUnless(os.name == 'nt' and os.environ.get('BA_NATIVE_BRIDGE_PROBE'),
                     'set BA_NATIVE_BRIDGE_PROBE to the authored Windows probe executable')
class NativeClientBridgeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT / 'local' / ('native-bridge-' + uuid.uuid4().hex)
        cls.pki = generate_test_pki(cls.folder)
        cls.probe = Path(os.environ['BA_NATIVE_BRIDGE_PROBE']).resolve()
        if not cls.probe.is_file(): raise AssertionError('native bridge probe is missing')

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.folder)

    async def exercise(self, expected, returncode, *, version=1, recover=False):
        store = Store()
        identities = [store.player, 'p_' + uuid.uuid4().hex]
        gate = a.AdmissionController(store)
        handlers, received = set(), []
        async def authenticated_echo(reader, writer):
            handlers.add(asyncio.current_task())
            try:
                self.assertEqual(await gate.authenticate(reader, writer), store.player)
                payload = await reader.readexactly(4)
                received.append(payload)
                writer.write(payload)
                await writer.drain()
            except (a.AdmissionError, OSError, asyncio.IncompleteReadError):
                pass
            finally:
                await tls.close_tls_stream(writer)
        listener = await tls.start_tls_server(authenticated_echo, '127.0.0.1', 0,
            tls.load_server_context(self.pki['cert'], self.pki['key']))
        parent, child = socket.socketpair(socket.AF_INET)
        parent.setblocking(False)
        reader, writer = await asyncio.open_connection(sock=parent)
        def remote():
            return b.Remote('127.0.0.1', listener.sockets[0].getsockname()[1],
                            tls.load_client_context(self.pki['ca'], expected), store.player, store.token)
        resolutions = 0
        async def resolve():
            nonlocal resolutions
            resolutions += 1
            if recover and resolutions == 1: raise b.RemoteUnavailable()
            store.player = identities[resolutions - 1 - int(recover)]
            return remote()
        class StaleIdentityBridge(b.Bridge):
            async def send(self, kind, identity, data=b''):
                if kind == b.READY and identity == 2 + int(recover):
                    # A valid retired identity/data packet must not affect session2.
                    await super().send(b.READY, 1, identities[0].encode())
                    await super().send(b.DATA, 1, b'discard retired bytes')
                await super().send(kind, identity, data)
        bridge_task = asyncio.create_task(StaleIdentityBridge(reader, writer,
            resolve if version == 2 else remote(), version=version).run())
        process = None
        try:
            child.set_inheritable(True)
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {'handle_list': [child.fileno()]}
            command = [str(self.probe), str(child.fileno())]
            if version == 2: command += ['2-recover' if recover else '2', *identities]
            process = subprocess.Popen(command, close_fds=True,
                startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            child.set_inheritable(False)
            child.close()
            output, errors = await asyncio.to_thread(process.communicate, timeout=10)
            self.assertEqual(process.returncode, returncode, errors.decode())
            self.assertNotIn(store.token.encode(), output + errors)
            await asyncio.wait_for(bridge_task, 3)
            await asyncio.gather(*handlers)
            return received, store.calls, output, errors
        finally:
            child.close()
            if process is not None and process.poll() is None:
                process.kill()
                await asyncio.to_thread(process.communicate, timeout=3)
            bridge_task.cancel()
            await asyncio.gather(bridge_task, return_exceptions=True)
            writer.close()
            listener.close()
            await listener.wait_closed()
            for task in handlers: task.cancel()
            await asyncio.gather(*handlers, return_exceptions=True)
            await gate.close()

    async def test_native_process_reuses_inherited_socket_for_two_authenticated_sessions(self):
        received, calls, output, errors = await self.exercise('localhost', 0)
        self.assertEqual(received, [b'test', b'more'])
        self.assertEqual(calls, 2)
        self.assertIn(b'two authenticated sessions', output)
        self.assertEqual(errors, b'')

    async def test_native_process_receives_certificate_failure_without_authentication(self):
        received, calls, output, errors = await self.exercise('wrong.invalid', 1)
        self.assertEqual((received, calls), ([], 0))
        self.assertIn(b'Server certificate verification failed', errors)

    async def test_native_v2_reauthenticates_changed_identity_and_discards_retired_ready(self):
        received, calls, output, errors = await self.exercise('localhost', 0, version=2)
        self.assertEqual((received, calls), ([b'test', b'more'], 2))
        self.assertIn(b'two authenticated sessions', output)
        self.assertEqual(errors, b'')

    async def test_native_v2_unconfigured_recovers_on_same_inherited_handle(self):
        received, calls, output, errors = await self.exercise('localhost', 0, version=2, recover=True)
        self.assertEqual((received, calls), ([b'test', b'more'], 2))
        self.assertEqual(errors, b'')

    async def test_native_v2_certificate_failure_before_ready_or_game_bytes(self):
        received, calls, output, errors = await self.exercise('wrong.invalid', 1, version=2)
        self.assertEqual((received, calls), ([], 0))
        self.assertIn(b'Server certificate verification failed', errors)

    async def test_native_v2_rejects_malformed_identity_duplicate_ready_and_pre_auth_data(self):
        profile = ('p_' + 'a' * 32).encode()
        ready = b.encode(b.READY, 1, profile, version=2)
        cases = (
            (struct.pack('<IBBI', 40, 2, b.READY, 1) + b'p_' + b'Z' * 32, b'Invalid secure transport message'),
            (ready + ready, b'Unexpected secure transport identity'),
            (b.encode(b.DATA, 1, b'premature', version=2), b'Secure transport receive queue invalid'),
            (b.encode(b.DATA, 1, b'wrong version'), b'Invalid secure transport message'),
        )
        for packet, expected in cases:
            with self.subTest(expected=expected):
                parent, child = socket.socketpair(socket.AF_INET)
                parent.setblocking(False)
                reader, writer = await asyncio.open_connection(sock=parent)
                process = None
                try:
                    child.set_inheritable(True)
                    startup = subprocess.STARTUPINFO()
                    startup.lpAttributeList = {'handle_list': [child.fileno()]}
                    process = subprocess.Popen([str(self.probe), str(child.fileno()), '2', profile.decode(), profile.decode()],
                        close_fds=True, startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    child.set_inheritable(False)
                    child.close()
                    self.assertEqual(await asyncio.wait_for(b.receive(reader, version=2), 3), (b.OPEN, 1, b''))
                    writer.write(packet)
                    await writer.drain()
                    output, errors = await asyncio.to_thread(process.communicate, timeout=7)
                    self.assertEqual(process.returncode, 1)
                    self.assertIn(expected, errors)
                finally:
                    child.close()
                    if process is not None and process.poll() is None:
                        process.kill()
                        await asyncio.to_thread(process.communicate, timeout=3)
                    writer.close()
                    try: await writer.wait_closed()
                    except OSError: pass


if __name__ == '__main__': unittest.main()
