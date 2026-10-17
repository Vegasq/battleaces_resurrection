"""Raw sockets are capped before TLS; use actual Windows/asyncio loopback I/O."""
import asyncio
from pathlib import Path
import unittest
import uuid

from server import tls_transport as tls
from server.tls_listener import HandshakeBudget
from tests.test_tls_transport import generate_test_pki, remove_test_pki

ROOT = Path(__file__).resolve().parents[1]


class HandshakeBudgetTests(unittest.TestCase):
    def test_global_and_source_capacity_are_independent(self):
        budget = HandshakeBudget(maximum=2, per_address=1)
        self.assertEqual(budget.acquire('127.0.0.1'), ('127.0.0.1', None))
        self.assertEqual(budget.acquire('127.0.0.1'), (None, 'capacity'))
        self.assertEqual(budget.acquire('127.0.0.2'), ('127.0.0.2', None))
        self.assertEqual(budget.acquire('127.0.0.3'), (None, 'capacity'))
        budget.release('127.0.0.1')
        self.assertEqual(budget.acquire('127.0.0.3'), ('127.0.0.3', None))
        self.assertEqual(budget.pending, 2)

    def test_source_refill_survives_denials_and_ipv4_mapping(self):
        now = [0.0]
        budget = HandshakeBudget(burst=1, rate=1, clock=lambda: now[0])
        key, _ = budget.acquire('::ffff:127.0.0.1')
        self.assertEqual(key, '127.0.0.1')
        budget.release(key)
        for instant in (.25, .5, .75):
            now[0] = instant
            self.assertEqual(budget.acquire('127.0.0.1'), (None, 'source_rate'))
        now[0] = 1.0
        self.assertEqual(budget.acquire('127.0.0.1'), ('127.0.0.1', None))

    def test_global_rate_bounds_new_addresses_without_growing_table(self):
        now = [0.0]
        budget = HandshakeBudget(global_burst=1, global_rate=1, clock=lambda: now[0])
        key, _ = budget.acquire('127.0.0.1')
        budget.release(key)
        for suffix in range(2, 100):
            self.assertEqual(budget.acquire('127.0.0.' + str(suffix)), (None, 'global_rate'))
        self.assertEqual(len(budget.addresses), 1)
        now[0] = 1.0
        self.assertEqual(budget.acquire('127.0.0.2'), ('127.0.0.2', None))

    def test_address_table_expires_only_inactive_buckets(self):
        now = [0.0]
        budget = HandshakeBudget(max_addresses=1, clock=lambda: now[0])
        key, _ = budget.acquire('127.0.0.1')
        now[0] = 61.0
        self.assertEqual(budget.acquire('127.0.0.2'), (None, 'address_limit'))
        budget.release(key)
        now[0] = 67.0
        self.assertEqual(budget.acquire('127.0.0.2'), ('127.0.0.2', None))

    def test_invalid_bounds_fail_before_binding(self):
        for args in ({'maximum': 0}, {'per_address': 33}, {'burst': True},
                     {'rate': float('nan')}, {'global_rate': float('inf')}, {'max_addresses': 0}):
            with self.subTest(args=args), self.assertRaises(tls.TLSConfigurationError):
                HandshakeBudget(**args)


class BoundedTLSLoopbackTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT / 'local' / ('bounded-tls-' + uuid.uuid4().hex)
        try:
            cls.pki = generate_test_pki(cls.folder)
        except BaseException:
            if cls.folder.exists(): remove_test_pki(cls.folder)
            raise

    @classmethod
    def tearDownClass(cls):
        remove_test_pki(cls.folder)

    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        self.errors, self.writers, self.handlers, self.received = [], [], set(), []
        self.previous = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, context: self.errors.append(context))
        self.server = None
        self.context = tls.load_server_context(self.pki['cert'], self.pki['key'])
        self.client = tls.load_client_context(self.pki['ca'], 'localhost')

    async def asyncTearDown(self):
        if self.server: self.server.close()
        await asyncio.gather(*(tls.close_tls_stream(writer, timeout=.2) for writer in self.writers), return_exceptions=True)
        if self.server: await self.server.wait_closed()
        for task in self.handlers: task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)
        self.loop.set_exception_handler(self.previous)
        self.assertEqual(self.errors, [], 'unexpected event-loop cleanup/handshake error')

    async def echo(self, reader, writer):
        self.handlers.add(asyncio.current_task())
        self.writers.append(writer)
        try:
            data = await reader.readexactly(4)
            self.received.append(data)
            writer.write(data)
            await writer.drain()
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            await tls.close_tls_stream(writer, timeout=.2)

    async def start(self, **kwargs):
        self.server = await tls.start_tls_server(self.echo, '127.0.0.1', 0, self.context, **kwargs)
        return self.server.sockets[0].getsockname()[1]

    async def raw(self, port):
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        self.writers.append(writer)
        return reader, writer

    async def closed(self, reader):
        try:
            self.assertEqual(await asyncio.wait_for(reader.read(1), 2), b'')
        except ConnectionResetError:
            pass

    async def wait_until(self, condition):
        async with asyncio.timeout(2):
            while not condition():
                await asyncio.sleep(.005)

    async def exchange(self, port):
        reader, writer = await tls.open_verified_connection('127.0.0.1', port, self.client)
        self.writers.append(writer)
        writer.write(b'test')
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(4), 2), b'test')

    async def test_raw_capacity_rejects_before_tls_then_timeout_restores_service(self):
        port = await self.start(max_handshakes=2, max_handshakes_per_address=2, handshake_timeout=.15)
        first, _ = await self.raw(port)
        second, _ = await self.raw(port)
        await self.wait_until(lambda: self.server.budget.pending == 2)
        rejected, _ = await self.raw(port)
        await self.closed(rejected)
        self.assertEqual(self.server.stats['capacity'], 1)
        self.assertEqual(self.received, [])
        await self.closed(first)
        await self.closed(second)
        await self.wait_until(lambda: self.server.budget.pending == 0)
        await self.exchange(port)
        self.assertEqual(self.received, [b'test'])

    async def test_source_capacity_does_not_allocate_another_handshake(self):
        port = await self.start(max_handshakes=3, max_handshakes_per_address=1)
        first, _ = await self.raw(port)
        await self.wait_until(lambda: self.server.budget.pending == 1)
        for _ in range(5):
            rejected, _ = await self.raw(port)
            await self.closed(rejected)
        self.assertEqual(self.server.stats['accepted'], 1)
        self.assertEqual(self.server.stats['capacity'], 5)
        self.assertEqual(len(self.server._pending), 1)

    async def test_completed_tls_still_consumes_rate_budget(self):
        port = await self.start(global_handshake_burst=1, global_handshakes_per_second=.1)
        await self.exchange(port)
        await self.wait_until(lambda: self.server.budget.pending == 0)
        rejected, _ = await self.raw(port)
        await self.closed(rejected)
        self.assertEqual(self.server.stats['global_rate'], 1)
        self.assertEqual(self.server.stats['established'], 1)

    async def test_shutdown_reaps_stalled_handshakes_without_callback(self):
        port = await self.start()
        readers = [(await self.raw(port))[0] for _ in range(3)]
        await self.wait_until(lambda: self.server.budget.pending == 3)
        self.server.close()
        await asyncio.wait_for(self.server.wait_closed(), 1)
        for reader in readers: await self.closed(reader)
        self.assertEqual(self.server.budget.pending, 0)
        self.assertEqual(self.server.budget.active, {})
        self.assertEqual(self.server._pending, {})
        self.assertEqual(self.received, [])
        self.assertFalse(self.server.is_serving())

    async def test_immediate_close_and_serve_forever_cancellation(self):
        await self.start()
        waiter = asyncio.create_task(self.server.serve_forever())
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError): await waiter
        await self.server.wait_closed()
        self.assertEqual(self.server.budget.pending, 0)
        self.assertFalse(self.server.is_serving())

    async def test_malformed_tls_releases_capacity_and_never_reaches_application(self):
        port = await self.start(max_handshakes=1, max_handshakes_per_address=1)
        reader, writer = await self.raw(port)
        writer.write(b'GET / HTTP/1.0\r\n\r\n')
        await writer.drain()
        await self.closed(reader)
        await self.wait_until(lambda: self.server.budget.pending == 0)
        self.assertEqual(self.server.stats['handshake_failed'], 1)
        self.assertEqual(self.received, [])
        await self.exchange(port)

    async def test_non_numeric_bind_is_rejected_without_listener(self):
        with self.assertRaises(tls.TLSConfigurationError):
            await tls.start_tls_server(self.echo, 'localhost', 0, self.context)

    async def test_application_exception_aborts_without_unhandled_task(self):
        async def failing(reader, writer):
            raise RuntimeError('test-only application failure')
        self.server = await tls.start_tls_server(failing, '127.0.0.1', 0, self.context)
        port = self.server.sockets[0].getsockname()[1]
        reader, writer = await tls.open_verified_connection('127.0.0.1', port, self.client)
        self.writers.append(writer)
        await self.closed(reader)
        await self.wait_until(lambda: not self.server._clients)
        self.assertEqual(self.server.stats['handler_failed'], 1)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
