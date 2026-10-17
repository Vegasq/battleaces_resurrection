"""Qualification relay preserves streams and applies bounded delay on real sockets."""
import asyncio
import unittest

from tools.stream_shaper import StreamShaper


class StreamShaperTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.writers, self.tasks, self.errors = set(), set(), []
        self.loop = asyncio.get_running_loop()
        self.previous_handler = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, data: self.errors.append(data))
        self.server = await asyncio.start_server(self.echo, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.relay = None

    async def echo(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task); self.writers.add(writer)
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except (OSError, asyncio.CancelledError): pass
        finally:
            writer.close()
            try: await writer.wait_closed()
            except OSError: pass
            self.tasks.discard(task); self.writers.discard(writer)

    async def asyncTearDown(self):
        if self.relay: await self.relay.close()
        self.server.close()
        for writer in list(self.writers): writer.close()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        await self.server.wait_closed()
        self.loop.set_exception_handler(self.previous_handler)
        self.assertEqual(self.errors, [])

    async def connect(self, **settings):
        self.relay = StreamShaper(self.port, **settings)
        port = await self.relay.start()
        return await asyncio.open_connection('127.0.0.1', port)

    async def test_ordered_large_stream_survives_delay_and_jitter(self):
        reader, writer = await self.connect(rtt_ms=50, jitter_ms=10, seed=101)
        data = bytes(range(256)) * 1024
        writer.write(data)
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)), 5), data)
        self.assertLessEqual(self.relay.stats['maximum_queued_chunks'], 32)
        self.assertEqual(self.relay.stats['forwarded_bytes'], 2 * len(data))
        writer.close(); await writer.wait_closed()

    async def test_measured_round_trip_includes_both_direction_delays(self):
        reader, writer = await self.connect(rtt_ms=100)
        started = self.loop.time()
        writer.write(b'round trip'); await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(10), 3), b'round trip')
        self.assertGreaterEqual(self.loop.time() - started, .095)
        writer.close(); await writer.wait_closed()

    async def test_capacity_and_shutdown_reap_live_connections(self):
        reader, writer = await self.connect(rtt_ms=500, maximum=1)
        writer.write(b'pending'); await writer.drain()
        await asyncio.sleep(.02)
        port = self.relay.listener.sockets[0].getsockname()[1]
        extra_reader, extra_writer = await asyncio.open_connection('127.0.0.1', port)
        self.assertEqual(await asyncio.wait_for(extra_reader.read(1), 1), b'')
        extra_writer.close(); await extra_writer.wait_closed()
        await asyncio.wait_for(self.relay.close(), 2)
        self.assertEqual(self.relay.tasks, set())
        self.assertEqual(self.relay.stats['rejected'], 1)
        self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')
        writer.close(); await writer.wait_closed()

    def test_invalid_settings_fail_before_opening_sockets(self):
        for setting in ({'rtt_ms': float('nan')}, {'jitter_ms': float('inf')},
                        {'rtt_ms': 501}, {'jitter_ms': -1}, {'maximum': 0}, {'rtt_ms': True}):
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                StreamShaper(self.port, **setting)

    async def test_peer_eof_racing_relay_close_leaves_no_live_reservations(self):
        for _ in range(8):
            reader, writer = await self.connect(rtt_ms=20)
            writer.write(b'pending'); await writer.drain()
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0)
            await asyncio.wait_for(self.relay.close(), 2)
            self.assertEqual(self.relay.tasks, set())


if __name__ == '__main__': unittest.main()
