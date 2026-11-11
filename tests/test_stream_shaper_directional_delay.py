"""Real owned loopback streams; directional scheduling metadata contains no payloads."""
import asyncio
import json
import math
import unittest

from tools.stream_shaper import StreamShaper


ROOT_FIELDS = {'schema', 'metadata_limit', 'revision', 'configured_rtt_ms', 'directions'}
CHUNK_FIELDS = {'connection', 'chunk', 'revision', 'configured_rtt_ms', 'received_loop',
                'due_loop', 'byte_count', 'forwarded_loop', 'drained_loop', 'held_ms'}
EXTRA_FIELDS = {'base_due_loop', 'directional_extra_ms', 'directional_window_id', 'final_due_loop'}
WINDOW_FIELDS = {'window_id', 'direction', 'extra_ms', 'duration_ms', 'requested_tick_ms',
                 'effective_tick_ms', 'requested_perf_counter_ns', 'effective_perf_counter_ns',
                 'start_loop', 'end_loop'}


class DirectionalDelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.writers, self.tasks, self.errors, self.clients = set(), set(), [], []
        self.loop = asyncio.get_running_loop()
        self.previous_handler = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, data: self.errors.append(data))
        self.server = await asyncio.start_server(self.echo, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.relay = None

    async def echo(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            self.tasks.discard(task)
            self.writers.discard(writer)

    async def asyncTearDown(self):
        for writer in self.clients:
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for writer in self.clients), return_exceptions=True)
        if self.relay:
            await self.relay.close()
        self.server.close()
        for writer in list(self.writers):
            writer.close()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        await self.server.wait_closed()
        self.loop.set_exception_handler(self.previous_handler)
        self.assertEqual(self.errors, [])

    async def connect(self, **settings):
        self.relay = StreamShaper(self.port, **settings)
        port = await self.relay.start()
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        self.clients.append(writer)
        return reader, writer

    async def rows(self, direction, count):
        async def ready():
            while True:
                rows = self.relay.delay_metadata()['directions'][direction]['rows']
                if len(rows) >= count:
                    return rows
                await asyncio.sleep(.001)
        return await asyncio.wait_for(ready(), 2)

    async def send(self, writer, data, count):
        writer.write(data)
        await writer.drain()
        return await self.rows('client_to_server', count)

    async def test_default_shape_and_schedule_are_unchanged(self):
        reader, writer = await self.connect(rtt_ms=60, metadata_limit=32)
        writer.write(b'ordinary')
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(8), 2), b'ordinary')
        metadata = self.relay.delay_metadata()
        self.assertEqual(set(metadata), ROOT_FIELDS)
        for bucket in metadata['directions'].values():
            self.assertTrue(bucket['rows'])
            for row in bucket['rows']:
                self.assertEqual(set(row), CHUNK_FIELDS)
                self.assertAlmostEqual(row['due_loop']-row['received_loop'], .03, places=5)

    async def test_high_queued_debt_gets_extra_once_without_changing_old_deadlines(self):
        reader, writer = await self.connect(rtt_ms=475, metadata_limit=32)
        old = (await self.send(writer, b'A', 1))[0]
        self.relay.set_rtt_ms(130)
        window = self.relay.set_directional_delay('client_to_server', 100, 250)
        second = (await self.send(writer, b'B', 2))[1]
        third = (await self.send(writer, b'C', 3))[2]
        self.assertEqual(set(old), CHUNK_FIELDS)
        self.assertGreater(old['due_loop']-second['received_loop'], .15)
        for row in (second, third):
            self.assertEqual(set(row), CHUNK_FIELDS | EXTRA_FIELDS)
            self.assertEqual(row['directional_window_id'], window['window_id'])
            self.assertEqual(row['directional_extra_ms'], 100)
            self.assertEqual(row['base_due_loop'], old['due_loop'])
            self.assertAlmostEqual(row['due_loop']-old['due_loop'], .1, places=6)
            self.assertEqual(row['due_loop'], row['final_due_loop'])
        self.assertEqual(second['due_loop'], third['due_loop'])
        self.assertEqual(await asyncio.wait_for(reader.readexactly(3), 2), b'ABC')
        actual = self.relay.delay_metadata()
        self.assertEqual(actual['directions']['client_to_server']['rows'][0]['due_loop'], old['due_loop'])
        self.assertTrue(all(set(row) == CHUNK_FIELDS for row in actual['directions']['server_to_client']['rows']))
        upstream = actual['directions']['client_to_server']['rows']
        self.assertEqual([row['byte_count'] for row in upstream], [1, 1, 1])
        self.assertEqual(sorted(row['forwarded_loop'] for row in upstream), [row['forwarded_loop'] for row in upstream])
        self.assertTrue(all(row['forwarded_loop']+self.loop._clock_resolution >= row['due_loop'] for row in upstream))

    async def test_expiry_returns_extra_to_zero_and_retains_ordered_tail(self):
        reader, writer = await self.connect(metadata_limit=32)
        # Establish both relay pipes before starting this deliberately short
        # window; accepting the client socket does not mean upstream connected.
        await self.send(writer, b'W', 1)
        self.assertEqual(await asyncio.wait_for(reader.readexactly(1), 2), b'W')
        window = self.relay.set_directional_delay('client_to_server', 100, 25)
        first = (await self.send(writer, b'A', 2))[1]
        self.assertEqual(first['directional_extra_ms'], 100)
        while self.loop.time() < window['end_loop']:
            await asyncio.sleep(.001)
        second = (await self.send(writer, b'B', 3))[2]
        self.assertEqual(second['directional_extra_ms'], 0)
        self.assertIsNone(second['directional_window_id'])
        self.assertLess(second['base_due_loop'], first['due_loop'])
        self.assertEqual(second['due_loop'], first['due_loop'])
        self.assertEqual(await asyncio.wait_for(reader.readexactly(2), 2), b'AB')
        third = (await self.send(writer, b'C', 4))[3]
        self.assertEqual(await asyncio.wait_for(reader.readexactly(1), 2), b'C')
        self.assertEqual(third['due_loop'], third['base_due_loop'])
        self.assertEqual(third['directional_extra_ms'], 0)

    async def test_server_to_client_direction_and_detached_records(self):
        reader, writer = await self.connect(metadata_limit=32)
        ticks = iter((1000, 1001))
        returned = self.relay.set_directional_delay('server_to_client', 50, 250, tick=lambda: next(ticks))
        self.assertEqual(set(returned), WINDOW_FIELDS)
        self.assertEqual((returned['requested_tick_ms'], returned['effective_tick_ms']), (1000, 1001))
        self.assertLessEqual(returned['requested_perf_counter_ns'], returned['effective_perf_counter_ns'])
        self.assertAlmostEqual(returned['end_loop']-returned['start_loop'], .25, places=6)
        returned['extra_ms'] = 0
        detached = self.relay.delay_metadata()
        detached['directional_delays'][0]['end_loop'] = 0
        await self.send(writer, b'reply', 1)
        self.assertEqual(await asyncio.wait_for(reader.readexactly(5), 2), b'reply')
        metadata = self.relay.delay_metadata()
        self.assertEqual(metadata['directional_delays'][0]['extra_ms'], 50)
        self.assertGreater(metadata['directional_delays'][0]['end_loop'], 0)
        self.assertEqual(set(metadata['directions']['client_to_server']['rows'][0]), CHUNK_FIELDS)
        reply = metadata['directions']['server_to_client']['rows'][0]
        self.assertEqual(reply['directional_extra_ms'], 50)
        self.assertAlmostEqual(reply['due_loop']-reply['base_due_loop'], .05, places=6)
        json.dumps(metadata, allow_nan=False)

    async def test_validation_owner_reentrancy_and_failed_clock_are_transactional(self):
        unopened = StreamShaper(self.port)
        with self.assertRaises(ValueError):
            unopened.set_directional_delay('client_to_server', 100, 250)
        await self.connect(metadata_limit=32)
        for direction, extra, duration in ((None, 100, 250), ('bad', 100, 250), ('client_to_server', True, 250),
                ('client_to_server', 0, 250), ('client_to_server', 101, 250), ('client_to_server', math.nan, 250),
                ('client_to_server', 100, 0), ('client_to_server', 100, 1001), ('client_to_server', 100, math.inf)):
            with self.subTest(direction=direction, extra=extra, duration=duration), self.assertRaises(ValueError):
                self.relay.set_directional_delay(direction, extra, duration)
        before = self.relay.delay_metadata()
        with self.assertRaises(ValueError):
            self.relay.set_directional_delay('client_to_server', 100, 250, tick=lambda: True)
        reverse = iter((100, 99))
        with self.assertRaises(ValueError):
            self.relay.set_directional_delay('client_to_server', 100, 250, tick=lambda: next(reverse))
        def reentrant():
            self.relay.set_rtt_ms(130)
            return 1
        with self.assertRaises(ValueError):
            self.relay.set_directional_delay('client_to_server', 100, 250, tick=reentrant)
        with self.assertRaises(ValueError):
            await asyncio.to_thread(self.relay.set_directional_delay, 'client_to_server', 100, 250)
        async def other_loop():
            self.relay.set_directional_delay('client_to_server', 100, 250)
        with self.assertRaises(ValueError):
            await asyncio.to_thread(lambda: asyncio.run(other_loop()))
        self.assertEqual(self.relay.delay_metadata(), before)
        self.assertEqual(self.relay.set_directional_delay('client_to_server', 100, 1)['window_id'], 1)

    async def test_overlap_limit_pause_close_and_cancellation_do_not_leave_tasks(self):
        reader, writer = await self.connect(rtt_ms=500, metadata_limit=32)
        window = self.relay.set_directional_delay('client_to_server', 100, 1000)
        with self.assertRaises(ValueError):
            self.relay.set_directional_delay('server_to_client', 100, 250)
        row = (await self.send(writer, b'cancelled', 1))[0]
        self.assertEqual(row['directional_window_id'], window['window_id'])
        await self.relay.outage()
        self.assertFalse(self.relay.tasks)
        with self.assertRaises(ValueError):
            self.relay.set_directional_delay('client_to_server', 100, 250)
        await self.relay.close()
        with self.assertRaises(ValueError):
            self.relay.set_directional_delay('client_to_server', 100, 250)
        self.assertFalse(self.relay.tasks)
        self.assertFalse(self.relay.listener.is_serving())
        self.assertEqual(await asyncio.wait_for(reader.read(), 2), b'')
        retained = self.relay.delay_metadata()['directions']['client_to_server']['rows'][0]
        self.assertIsNone(retained['forwarded_loop'])

    async def test_window_id_advances_after_expiry_and_limit_is_bounded(self):
        await self.connect()
        for index in range(1, 33):
            record = self.relay.set_directional_delay('client_to_server', 1, 1)
            self.assertEqual(record['window_id'], index)
            while self.loop.time() < record['end_loop']:
                await asyncio.sleep(.001)
        with self.assertRaises(ValueError):
            self.relay.set_directional_delay('client_to_server', 1, 1)
        self.assertEqual(len(self.relay.delay_metadata()['directional_delays']), 32)


if __name__ == '__main__':
    unittest.main()
