"""A cancelled shutdown must retain the host lock until threaded history I/O ends."""
import asyncio
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
from unittest import mock

from server import web_dashboard as dashboard
from server.state_lock import exclusive_state, StateBusyError
from tests.test_dedicated_server import wait_until


class DashboardShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def check_cancelled_write(self, fail):
        entered, release, finished = (threading.Event() for _ in range(3))
        closing = asyncio.Event()
        errors = []
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: errors.append(context))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'web-matches.json'
            dashboard.write_history(path, [])
            before = path.read_bytes()
            server = NS(rooms={}, closing=False, match_observer=None,
                        community=NS(directory_rows=()))
            web = dashboard.Dashboard(server, path)
            room = NS(match_id='shutdown_match', mode=1, public_match=None,
                      community_lobby='custom', frame=160,
                      template=NS(alliances={0: 0, 1: 1}),
                      peers={0: NS(profile_id='p_alice', name='Alice')},
                      bots={1: NS(name='Computer')})
            original_replace = dashboard.os.replace

            def publish(source, target):
                # Real serialization/flush/fsync has finished. Pause precisely
                # before publication; no real user path or security policy used.
                entered.set()
                try:
                    if not release.wait(5): raise TimeoutError('test publication gate')
                    if fail: raise OSError('injected publication failure')
                    return original_replace(source, target)
                finally:
                    finished.set()

            async def host_owner():
                with exclusive_state(folder):
                    await web.start('127.0.0.1', 0)
                    web.record(room, 'match_completed',
                               {'result': {'complete': True, 'winning_alliance': 1}})
                    await closing.wait()
                    await web.close()

            owner = joiner = None
            try:
                with mock.patch.object(dashboard.os, 'replace', side_effect=publish):
                    owner = asyncio.create_task(host_owner())
                    await wait_until(entered.is_set)
                    closing.set()
                    await wait_until(lambda: web.stopping)
                    owner.cancel()
                    await asyncio.sleep(.02)
                    owner.cancel()
                    await asyncio.sleep(.02)
                    self.assertFalse(owner.done(), 'shutdown released ownership before publication ended')
                    with self.assertRaises(StateBusyError):
                        with exclusive_state(folder): pass
                    joiner = asyncio.create_task(web.close())
                    await asyncio.sleep(.01)
                    self.assertFalse(joiner.done())
                    self.assertIsNone(server.match_observer)
                    release.set()
                    with self.assertRaises(asyncio.CancelledError): await owner
                    await joiner
                    self.assertTrue(finished.is_set())
                    with exclusive_state(folder): pass
                    self.assertIsNone(web.worker)
                    self.assertFalse(web.handlers)
                    self.assertFalse(list(Path(folder).glob('.web-matches-*.tmp')))
                    if fail:
                        self.assertEqual(path.read_bytes(), before)
                        self.assertFalse(web.persistence_ok)
                    else:
                        rows = dashboard.read_history(path)
                        self.assertEqual(rows[0]['state'], 'completed')
                        self.assertEqual(rows[0]['winning_alliance'], 1)
                        self.assertTrue(web.persistence_ok)
                    await web.close()  # Idempotent after a cancelled caller.
                    await asyncio.sleep(0)
                    self.assertFalse(errors)
            finally:
                release.set()
                closing.set()
                if owner: await asyncio.gather(owner, return_exceptions=True)
                if joiner: await asyncio.gather(joiner, return_exceptions=True)
                await asyncio.gather(web.close(), return_exceptions=True)
                # Also drain the pre-fix failure path before removing its files.
                await asyncio.to_thread(finished.wait, 5)
                await asyncio.to_thread(lambda: None)
                loop.set_exception_handler(previous_handler)

    async def test_cancelled_shutdown_waits_for_publication_and_keeps_host_lock(self):
        await self.check_cancelled_write(fail=False)

    async def test_cancelled_shutdown_consumes_write_failure_and_keeps_old_history(self):
        await self.check_cancelled_write(fail=True)


if __name__ == '__main__': unittest.main()
