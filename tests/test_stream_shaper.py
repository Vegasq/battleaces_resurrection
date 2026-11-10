"""Qualification relay preserves streams and applies bounded delay on real sockets."""
import asyncio
import json
import unittest

from tools.stream_shaper import StreamShaper,ThreadedStreamShaper


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
        self.assertEqual(self.relay.stats['delay_samples'],2)
        self.assertGreaterEqual(self.relay.stats['minimum_delay_ms'],45)
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

    async def test_owned_thread_relays_and_releases_listener(self):
        relay=ThreadedStreamShaper(self.port,rtt_ms=80,jitter_ms=10,seed=17)
        try:
            reader,writer=await asyncio.open_connection('127.0.0.1',relay.port)
            data=bytes(range(256))*512;writer.write(data);await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)),5),data)
            writer.close();await writer.wait_closed()
        finally:result=await asyncio.to_thread(relay.close)
        self.assertTrue(result['thread_stopped'] and result['listener_closed'])
        self.assertEqual(result['active_connections'],0)
        self.assertEqual(result['forwarded_bytes'],2*len(data))
        self.assertGreater(result['delay_samples'],0)
        self.assertGreaterEqual(result['minimum_delay_ms'],29)
        with self.assertRaises(OSError):await asyncio.open_connection('127.0.0.1',relay.port)

    async def test_owned_thread_failed_bind_reaps_itself(self):
        with self.assertRaises(OSError):
            await asyncio.to_thread(ThreadedStreamShaper,self.port,listen_port=self.port)

    async def test_owned_thread_shutdown_with_pending_delivery(self):
        relay=ThreadedStreamShaper(self.port,rtt_ms=500)
        reader,writer=await asyncio.open_connection('127.0.0.1',relay.port)
        writer.write(b'pending');await writer.drain();await asyncio.sleep(.02)
        result=await asyncio.to_thread(relay.close)
        self.assertTrue(result['thread_stopped']);self.assertEqual(result['active_connections'],0)
        self.assertEqual(await asyncio.wait_for(reader.read(1),2),b'')
        writer.close();await writer.wait_closed()

    async def test_owned_thread_outage_refuses_then_restores_same_port(self):
        relay=ThreadedStreamShaper(self.port)
        reader=writer=None
        try:
            reader,writer=await asyncio.open_connection('127.0.0.1',relay.port)
            writer.write(b'before');await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(6),2),b'before')
            outage=await asyncio.to_thread(relay.outage)
            self.assertEqual(outage,dict(port=relay.port,disconnected=1))
            self.assertEqual(await asyncio.wait_for(reader.read(1),2),b'')
            with self.assertRaises(OSError):
                await asyncio.open_connection('127.0.0.1',relay.port)
            self.assertEqual(await asyncio.to_thread(relay.restore),relay.port)
            renewed,remote=await asyncio.open_connection('127.0.0.1',relay.port)
            remote.write(b'after');await remote.drain()
            self.assertEqual(await asyncio.wait_for(renewed.readexactly(5),2),b'after')
            remote.close();await remote.wait_closed()
        finally:
            if writer:writer.close();await writer.wait_closed()
            result=await asyncio.to_thread(relay.close)
        self.assertEqual(result['accepted'],2)
        self.assertEqual(result['active_connections'],0)
        self.assertTrue(result['thread_stopped'] and result['listener_closed'])

    async def wait_metadata(self, direction, count):
        async def ready():
            while True:
                value = self.relay.delay_metadata()['directions'][direction]
                if value['seen'] >= count:
                    return value
                await asyncio.sleep(.001)
        return await asyncio.wait_for(ready(), 2)

    async def test_downshift_preserves_queued_deadline_and_byte_order(self):
        reader, writer = await self.connect(rtt_ms=400, metadata_limit=32)
        try:
            writer.write(b'A'); await writer.drain()
            old = (await self.wait_metadata('client_to_server', 1))['rows'][0]
            self.assertEqual(old['revision'], 0)
            ticks = iter((1000, 1001))
            change = self.relay.set_rtt_ms(0, tick=lambda: next(ticks))
            self.assertEqual(change['revision'], 1)
            self.assertEqual(change['configured_rtt_ms'], 0)
            self.assertEqual((change['requested_tick_ms'], change['effective_tick_ms']), (1000, 1001))
            self.assertLessEqual(change['requested_perf_counter_ns'], change['effective_perf_counter_ns'])
            writer.write(b'B'); await writer.drain()
            rows = (await self.wait_metadata('client_to_server', 2))['rows']
            self.assertEqual([r['revision'] for r in rows], [0, 1])
            self.assertAlmostEqual(rows[0]['due_loop'] - rows[0]['received_loop'], .2, places=5)
            self.assertEqual(rows[1]['due_loop'], rows[0]['due_loop'])
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(reader.readexactly(1), .04)
            self.assertEqual(await asyncio.wait_for(reader.readexactly(2), 2), b'AB')
            data = self.relay.delay_metadata()
            self.assertTrue(data['directions']['server_to_client']['rows'])
            forwarded = data['directions']['client_to_server']['rows']
            self.assertGreater(forwarded[1]['held_ms'], 100)
            self.assertLessEqual(forwarded[0]['forwarded_loop'], forwarded[1]['forwarded_loop'])
            # Installed asyncio _run_once promotes timers below time()+its
            # clock resolution. This records its qualified accuracy, without
            # changing the existing single-sleep scheduling or queued deadlines.
            self.assertTrue(all(r['forwarded_loop'] + self.loop._clock_resolution >= r['due_loop']
                                for r in forwarded))
            json.dumps(data, allow_nan=False)
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_increase_applies_to_future_reads_in_both_directions(self):
        reader, writer = await self.connect(metadata_limit=32)
        writer.write(b'old'); await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(3), 2), b'old')
        self.relay.set_rtt_ms(100)
        started = self.loop.time()
        writer.write(b'new'); await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(3), 2), b'new')
        self.assertGreaterEqual(self.loop.time() - started, .095)
        metadata = self.relay.delay_metadata()
        for direction in ('client_to_server', 'server_to_client'):
            rows = metadata['directions'][direction]['rows']
            self.assertEqual([r['revision'] for r in rows], [0, 1])
            self.assertEqual([r['configured_rtt_ms'] for r in rows], [0, 100])
            self.assertAlmostEqual(rows[1]['due_loop'] - rows[1]['received_loop'], .05, places=5)
            self.assertEqual(rows[1]['byte_count'], 3)
        writer.close(); await writer.wait_closed()

    async def test_metadata_cap_drops_only_records_and_returns_detached_rows(self):
        reader, writer = await self.connect(metadata_limit=1)
        for value in (b'a', b'b', b'c'):
            writer.write(value); await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(1), 2), value)
        metadata = self.relay.delay_metadata()
        for direction in metadata['directions'].values():
            self.assertEqual((direction['seen'], direction['dropped'], len(direction['rows'])), (3, 2, 1))
            self.assertNotIn('data', direction['rows'][0])
            direction['rows'][0]['revision'] = -9
        self.assertEqual(self.relay.delay_metadata()['directions']['client_to_server']['rows'][0]['revision'], 0)
        self.assertEqual(self.relay.stats['forwarded_bytes'], 6)
        writer.close(); await writer.wait_closed()

    async def test_setter_refuses_wrong_loop_closed_bad_value_and_bound(self):
        unopened = StreamShaper(self.port)
        with self.assertRaises(ValueError): unopened.set_rtt_ms(130)
        reader, writer = await self.connect()
        for value in (True, -1, 501, float('nan'), float('inf'), '130'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.relay.set_rtt_ms(value)
        async def other_loop():
            with self.assertRaises(ValueError): self.relay.set_rtt_ms(130)
        await asyncio.to_thread(lambda: asyncio.run(other_loop()))
        with self.assertRaises(ValueError): self.relay.set_rtt_ms(130, tick=lambda: True)
        for _ in range(32): self.relay.set_rtt_ms(130)
        with self.assertRaises(ValueError): self.relay.set_rtt_ms(475)
        self.assertEqual(self.relay.delay_metadata()['revision'], 32)
        await self.relay.close()
        with self.assertRaises(ValueError): self.relay.set_rtt_ms(130)
        writer.close(); await writer.wait_closed()

    async def test_ordinary_default_has_no_chunk_capture(self):
        reader, writer = await self.connect()
        writer.write(b'ordinary'); await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(8), 2), b'ordinary')
        metadata = self.relay.delay_metadata()
        self.assertEqual(metadata['metadata_limit'], 0)
        for direction in metadata['directions'].values():
            self.assertEqual((direction['seen'], direction['dropped'], direction['rows']), (0, 0, []))
        for limit in (True, -1, 8193, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                StreamShaper(self.port, metadata_limit=limit)
        writer.close(); await writer.wait_closed()

    async def test_tick_failure_is_atomic_and_paused_setter_refuses(self):
        reader, writer = await self.connect(rtt_ms=100)
        before = self.relay.delay_metadata()
        for values in ((10, True), (10, 9)):
            ticks = iter(values)
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.relay.set_rtt_ms(475, tick=lambda: next(ticks))
            self.assertEqual(self.relay.delay_metadata(), before)
            self.assertEqual(self.relay.delay, .05)
        await self.relay.outage()
        with self.assertRaises(ValueError): self.relay.set_rtt_ms(475)
        await self.relay.restore()
        self.assertEqual(self.relay.set_rtt_ms(130)['revision'], 1)
        writer.close(); await writer.wait_closed()


if __name__ == '__main__': unittest.main()
