import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from server.host_audit import HostAudit, QueuedHostAudit, AuditQueueFull


class HeldStream:
    def __init__(self, original, *, error=None, short=False):
        self.original, self.error, self.short = original, error, short
        self.entered, self.release = threading.Event(), threading.Event()
        self.closed = False

    def write(self, data):
        self.entered.set()
        if not self.release.wait(10): raise TimeoutError('test writer was not released')
        if self.error: raise self.error
        if self.short: return self.original.write(data[:-1])
        return self.original.write(data)

    def close(self):
        self.closed = True
        self.original.close()


class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.audits, self.held = [], []

    async def asyncTearDown(self):
        for stream in self.held: stream.release.set()
        for audit in self.audits:
            try: await audit.aclose()
            except OSError: pass
            self.assertFalse(audit.status()['thread_alive'])
        self.temporary.cleanup()

    def make(self, **kwargs):
        audit = QueuedHostAudit(self.root/str(len(self.audits)), max_bytes=65536,
                                backups=2, diagnostics=True, **kwargs)
        self.audits.append(audit)
        return audit

    def hold(self, audit, **kwargs):
        stream = HeldStream(audit.stream, **kwargs)
        audit.stream = stream  # Writer is idle; no producer has been called.
        self.held.append(stream)
        return stream

    async def entered(self, stream):
        self.assertTrue(await asyncio.to_thread(stream.entered.wait, 2))

    def records(self, audit):
        return [json.loads(line) for path in reversed(audit.paths) if path.exists()
                for line in path.read_text(encoding='utf-8').splitlines()]

    async def test_held_write_allows_loop_progress_and_preserves_timestamp_payload_order(self):
        audit = self.make()
        stream = self.hold(audit)
        before = time.perf_counter_ns()
        payload = ['original']
        audit('first', payload=payload)
        await self.entered(stream)
        payload[0] = 'changed'
        audit('second', label='界')
        # A blocked write does not prevent unrelated coroutine work or enqueue.
        progressed = asyncio.Event()
        asyncio.get_running_loop().call_soon(progressed.set)
        await asyncio.wait_for(progressed.wait(), 1)
        self.assertEqual(audit.status()['pending_records'], 2)
        released = time.perf_counter_ns()
        stream.release.set()
        await audit.aclose()
        rows = self.records(audit)
        self.assertEqual([r['event'] for r in rows], ['first', 'second'])
        self.assertEqual(rows[0]['payload'], ['original'])
        self.assertEqual(rows[1]['label'], '界')
        self.assertTrue(all(before <= r['perf_counter_ns'] < released for r in rows))
        status = audit.status()
        self.assertEqual((status['accepted'], status['written'], status['pending_bytes']), (2, 2, 0))
        self.assertTrue(status['closed']); self.assertFalse(status['failed'])

    async def test_count_and_byte_limits_include_inflight_and_drain_accepted_records(self):
        for limit in ('count', 'bytes'):
            with self.subTest(limit=limit):
                callback = mock.Mock()
                audit = self.make(on_failure=callback, max_pending_records=1 if limit=='count' else 10,
                                  max_pending_bytes=65536)
                stream = self.hold(audit)
                audit('first', text='x'*40000 if limit=='bytes' else '')
                await self.entered(stream)
                audit('overflow', text='x'*40000 if limit=='bytes' else '')
                audit('cleanup')  # Sticky failure must not interrupt resource cleanup.
                callback.assert_called_once()
                self.assertEqual(audit.status()['rejected'], 2)
                stream.release.set()
                with self.assertRaises(AuditQueueFull): await audit.aclose()
                self.assertEqual([r['event'] for r in self.records(audit)], ['first'])
                status = audit.status()
                self.assertEqual((status['accepted'], status['written'], status['abandoned']), (1, 1, 0))
                self.assertLessEqual(status['peak_bytes'], status['byte_limit'])

    async def test_write_error_and_short_write_notify_without_another_producer_call(self):
        for short in (False, True):
            with self.subTest(short=short):
                notified = threading.Event()
                error = OSError('owned write failed')
                audit = self.make(on_failure=notified.set)
                stream = self.hold(audit, short=short, error=None if short else error)
                audit('first'); await self.entered(stream); audit('second')
                stream.release.set()
                self.assertTrue(await asyncio.to_thread(notified.wait, 2))
                with self.assertRaises(OSError) as caught: await audit.aclose()
                if not short: self.assertIs(caught.exception, error)
                status = audit.status()
                self.assertEqual((status['accepted'], status['written'], status['abandoned']), (2, 0, 2))
                self.assertEqual(status['pending_bytes'], 0)
                self.assertTrue(stream.closed)

    async def test_repeated_cancellation_waits_for_write_and_close(self):
        audit = self.make(); stream = self.hold(audit)
        audit('last'); await self.entered(stream)
        closing = asyncio.create_task(audit.aclose())
        await asyncio.sleep(0)
        for _ in range(3):
            closing.cancel(); await asyncio.sleep(0)
            self.assertFalse(closing.done())
            self.assertFalse(stream.closed)
        stream.release.set()
        with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(closing, 2)
        self.assertTrue(stream.closed)
        self.assertEqual(audit.status()['written'], 1)
        await audit.aclose()

    async def test_rotation_omission_and_filter_match_synchronous_logger_bytes(self):
        audit = self.make(max_pending_bytes=1024*1024)
        reference = HostAudit(self.root/'reference', max_bytes=65536, backups=2, diagnostics=True)
        reference.session = audit.session
        unrelated = audit.directory/'notes.txt'; unrelated.write_text('keep')
        try:
            with mock.patch('server.host_audit.time.perf_counter_ns', return_value=42), \
                    mock.patch('server.host_audit.datetime') as clock:
                clock.now.return_value.isoformat.return_value = 'fixed'
                for i in range(100):
                    for target in (audit, reference): target('row', index=i, text='界'*900)
                for target in (audit, reference): target('huge', text='x'*70000)
            await audit.aclose(); reference.close()
            self.assertEqual([p.read_bytes() for p in audit.paths], [p.read_bytes() for p in reference.paths])
            self.assertEqual(unrelated.read_text(), 'keep')
            self.assertTrue(all(p.stat().st_size <=65536 for p in audit.paths))
            self.assertEqual(self.records(audit)[-1]['event'], 'audit_record_omitted')
        finally: reference.close()
        quiet = self.make(); quiet.diagnostics=False
        quiet('frame_queued', frame=1); quiet('done'); await quiet.aclose()
        self.assertEqual([r['event'] for r in self.records(quiet)], ['done'])

    async def test_close_failure_and_callback_failure_are_visible(self):
        audit = self.make(on_failure=mock.Mock(side_effect=ValueError('notify failed')))
        original = audit.stream
        class BadClose:
            def close(self):
                original.close()
                raise OSError('close failed')
        audit.stream = BadClose()
        with self.assertRaisesRegex(OSError, 'close failed'): await audit.aclose()
        self.assertEqual(audit.status()['notification_error'], 'ValueError')

    async def test_rotation_failure_is_reported_and_thread_is_joined(self):
        audit = self.make()
        audit.size = audit.max_bytes
        with mock.patch.object(audit, '_rotate', side_effect=OSError('rotation failed')):
            audit('rotate')
            with self.assertRaisesRegex(OSError, 'rotation failed'): await audit.aclose()
        self.assertEqual(audit.status()['abandoned'], 1)
        self.assertTrue(audit.status()['closed'])
        self.assertFalse(audit.status()['thread_alive'])

    async def test_host_cancellation_holds_state_lock_until_audit_drains(self):
        from server import host
        from server.state_lock import exclusive_state, StateBusyError
        from types import SimpleNamespace
        config = SimpleNamespace(data_directory=self.root/'drain', assets_directory=self.root/'assets',
            log_max_bytes=65536, log_backups=2, diagnostic_audit=True, dashboard_port=0,
            minimum_client_revision=0, client_update_message='', experimental_command_scheduling=False,
            max_rooms=4, input_window=64, access_mode='rc-open', listen_host='127.0.0.1', listen_port=0)
        ready, stopped = asyncio.Event(), asyncio.Event()
        audits, streams = [], []
        def factory(*args, **kwargs):
            audit = QueuedHostAudit(*args, **kwargs); audits.append(audit); self.audits.append(audit)
            streams.append(self.hold(audit))
            return audit
        server = mock.Mock()
        async def start(*args):
            audits[0]('server_started'); return ('127.0.0.1', 12345)
        async def close():
            audits[0]('server_stopped'); stopped.set()
        server.start = start; server.close = close
        server.listener.serve_forever = asyncio.Event().wait
        with mock.patch.object(host, 'prepare', return_value=(mock.Mock(), None, None,
                    dict(game_build=37822, asset_format=1, files={}))), \
                mock.patch.object(host, 'check_native', mock.AsyncMock(return_value={})), \
                mock.patch.object(host, 'HostAudit', side_effect=factory), \
                mock.patch.object(host, 'DedicatedServer', return_value=server), \
                mock.patch.object(host, 'ProfileStore'), mock.patch('builtins.print'):
            task = asyncio.create_task(host.run(config, on_ready=lambda address:ready.set()))
            try:
                await asyncio.wait_for(ready.wait(), 2); await self.entered(streams[0])
                task.cancel(); await asyncio.wait_for(stopped.wait(), 2)
                self.assertFalse(task.done())
                with self.assertRaises(StateBusyError):
                    with exclusive_state(config.data_directory): pass
                streams[0].release.set()
                with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(task, 2)
                with exclusive_state(config.data_directory): pass
                self.assertEqual(audits[0].status()['written'], 2)
                self.assertFalse(audits[0].status()['thread_alive'])
            finally:
                for stream in streams: stream.release.set()
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_thread_start_failure_closes_open_file(self):
        with mock.patch('server.host_audit.threading.Thread.start', side_effect=RuntimeError('start')), \
                mock.patch.object(HostAudit, 'close', autospec=True, wraps=HostAudit.close) as close:
            # Explicit delegate because autospec/wraps does not call methods consistently.
            close.side_effect = lambda audit: audit.stream.close()
            with self.assertRaisesRegex(RuntimeError, 'start'):
                QueuedHostAudit(self.root/'failed', max_bytes=65536, backups=1)
            close.assert_called_once()
            self.assertTrue(close.call_args.args[0].stream.closed)

    async def test_async_stage_observer_refuses_before_mutation(self):
        from tools.audit_stage_probe import AuditStages
        from server import host_audit
        audit = self.make(); stream, encoder = audit.stream, host_audit.json
        with self.assertRaisesRegex(ValueError, 'synchronous'):
            AuditStages(audit, host_audit, None)
        self.assertIs(audit.stream, stream); self.assertIs(host_audit.json, encoder)

    async def test_idle_write_failure_stops_host_and_preserves_cleanup_and_state_lock(self):
        from server import host
        from server.state_lock import exclusive_state, StateBusyError
        from types import SimpleNamespace
        config = SimpleNamespace(data_directory=self.root/'host', assets_directory=self.root/'assets',
            log_max_bytes=65536, log_backups=2, diagnostic_audit=True, dashboard_port=0,
            minimum_client_revision=0, client_update_message='', experimental_command_scheduling=False,
            max_rooms=4, input_window=64, access_mode='rc-open', listen_host='127.0.0.1', listen_port=0)
        manifest = dict(game_build=37822, asset_format=1, files={})
        audits, held = [], []
        cleanup_entered, cleanup_release, ready = asyncio.Event(), asyncio.Event(), asyncio.Event()
        listener = None
        def factory(*args, **kwargs):
            audit = QueuedHostAudit(*args, **kwargs); audits.append(audit); self.audits.append(audit)
            held.append(self.hold(audit, error=OSError('host writer failure')))
            return audit
        class Server:
            def __init__(self, *args, **kwargs):
                self.audit = kwargs['audit']; self.listener = None
            async def start(self, address, port):
                nonlocal listener
                self.listener = listener = await asyncio.start_server(lambda r,w:w.close(), address, port)
                self.audit('server_started')
                return self.listener.sockets[0].getsockname()[:2]
            async def close(self):
                cleanup_entered.set()
                # Rejected diagnostic events must not abort this cleanup.
                self.audit('worker_cleanup')
                await cleanup_release.wait()
                self.listener.close(); await self.listener.wait_closed()
                self.audit('server_stopped')
        with mock.patch.object(host, 'prepare', return_value=(mock.Mock(), None, None, manifest)), \
                mock.patch.object(host, 'check_native', mock.AsyncMock(return_value={})), \
                mock.patch.object(host, 'HostAudit', side_effect=factory), \
                mock.patch.object(host, 'DedicatedServer', Server), mock.patch.object(host, 'ProfileStore'), \
                mock.patch('builtins.print'):
            task = asyncio.create_task(host.run(config, on_ready=lambda address:ready.set()))
            try:
                await asyncio.wait_for(ready.wait(), 2); await self.entered(held[0])
                held[0].release.set()
                await asyncio.wait_for(cleanup_entered.wait(), 2)
                with self.assertRaises(StateBusyError):
                    with exclusive_state(config.data_directory): pass
                cleanup_release.set()
                with self.assertRaisesRegex(OSError, 'host writer failure'):
                    await asyncio.wait_for(task, 2)
                with exclusive_state(config.data_directory): pass
                self.assertFalse(listener.is_serving())
                self.assertTrue(audits[0].status()['closed'])
                self.assertFalse(audits[0].status()['thread_alive'])
                self.assertEqual(audits[0].status()['rejected'], 2)
            finally:
                cleanup_release.set()
                for stream in held: stream.release.set()
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if listener: listener.close(); await listener.wait_closed()


if __name__ == '__main__': unittest.main()
