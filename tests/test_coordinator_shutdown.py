"""Coordinator cancellation must not bypass owned profile I/O and the host lock."""
import asyncio
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from server import profiles
from server.dedicated_server import DedicatedServer
from server.state_lock import exclusive_state, StateBusyError
from tests.synthetic import template
from tests.test_dedicated_server import wait_until


class CoordinatorShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def check_early_cancellation(self, fail):
        entered, release, finished = (threading.Event() for _ in range(3))
        ready, stop = asyncio.Event(), asyncio.Event()
        events, errors = [], []
        loop=asyncio.get_running_loop(); previous=loop.get_exception_handler()
        loop.set_exception_handler(lambda loop,context:errors.append(context))
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); game=template()
            # This authored catalog allows two distinct valid saved decks.
            game.catalog[100]['deck_slot_flags']=3;game.catalog[101]['deck_slot_flags']=3
            store=profiles.ProfileStore(folder/'profiles',game)
            deck=tuple(range(100,108)); store.save('p_shutdown',deck)
            changed=(101,100,*deck[2:])
            path=folder/'profiles/p_shutdown.json'; before=path.read_bytes()
            server=DedicatedServer(game,store,audit=lambda event,**fields:events.append(event))
            original=profiles.os.replace
            def publish(source,target):
                if Path(target)!=path:return original(source,target)
                entered.set()
                try:
                    if not release.wait(5):raise TimeoutError('owned publication gate')
                    if fail:raise PermissionError('authored publication refusal')
                    return original(source,target)
                finally:finished.set()
            write=owner=joiner=None
            async def host_owner():
                with exclusive_state(folder):
                    await server.start('127.0.0.1',0)
                    ready.set()
                    await stop.wait()
                    await server.close()
            try:
                with mock.patch.object(profiles.os,'replace',side_effect=publish):
                    owner=asyncio.create_task(host_owner());await ready.wait()
                    write=asyncio.create_task(server.profile_io.save('p_shutdown',changed))
                    await wait_until(entered.is_set)
                    # Disconnect the network-style waiter; ProfileIO still owns
                    # the actual thread. Cancel shutdown at its FIRST await,
                    # before it has reached ProfileIO.close's own protection.
                    write.cancel()
                    with self.assertRaises(asyncio.CancelledError):await write
                    stop.set();await asyncio.sleep(0)
                    self.assertTrue(server.closing)
                    owner.cancel();await asyncio.sleep(.02)
                    owner.cancel();await asyncio.sleep(.02)
                    self.assertFalse(owner.done(),'coordinator released host ownership before profile publication settled')
                    self.assertFalse(finished.is_set())
                    with self.assertRaises(StateBusyError):
                        with exclusive_state(folder):pass
                    joiner=asyncio.create_task(server.close());await asyncio.sleep(.01)
                    self.assertFalse(joiner.done())
                    release.set()
                    with self.assertRaises(asyncio.CancelledError):await owner
                    await joiner
                    self.assertTrue(finished.is_set())
                    self.assertFalse(server.profile_io.pending)
                    self.assertTrue(all(not t.is_alive() for t in server.profile_io._executor._threads))
                    self.assertFalse(server.tasks or server.peers or server.worker_cleanup)
                    self.assertFalse(server.listener.is_serving())
                    self.assertTrue(server.community.maintenance.done())
                    with exclusive_state(folder):pass
                    self.assertFalse(list((folder/'profiles').glob('.profile-*.tmp')))
                    if fail:self.assertEqual(path.read_bytes(),before)
                    else:self.assertEqual(store.load('p_shutdown',deck),list(changed))
                    await server.close()
                    self.assertEqual(events.count('server_stopped'),1)
                    await asyncio.sleep(0);self.assertFalse(errors)
            finally:
                release.set();stop.set()
                if owner:await asyncio.gather(owner,return_exceptions=True)
                if joiner:await asyncio.gather(joiner,return_exceptions=True)
                if write:await asyncio.gather(write,return_exceptions=True)
                await server.close()
                await asyncio.to_thread(finished.wait,5)
                loop.set_exception_handler(previous)

    async def test_early_repeated_cancel_keeps_lock_until_actual_profile_publish(self):
        await self.check_early_cancellation(False)

    async def test_early_repeated_cancel_drains_failed_publish_and_preserves_previous_file(self):
        await self.check_early_cancellation(True)


if __name__=='__main__':unittest.main()
