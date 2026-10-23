"""Storage ordering, cancellation ownership and bounded shutdown."""
import asyncio
import threading
from types import SimpleNamespace
import unittest
from server.profile_io import ProfileIO
from tests.test_dedicated_server import wait_until


class ProfileIOTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.calls, self.state = [], ()
        self.failure = None
        def save(profile, deck, *, cosmetics=None):
            self.calls.append((profile, deck, threading.get_ident()))
            self.entered.set()
            if not self.release.wait(3): raise TimeoutError('test storage gate')
            if self.failure: raise self.failure
            self.state = deck
        self.io = ProfileIO(SimpleNamespace(save=save, load_state=lambda *args:self.state), max_pending=2)

    async def asyncTearDown(self):
        self.release.set()
        await self.io.close()

    async def test_cancelled_save_remains_owned_and_reconnect_read_waits_for_it(self):
        deck=[1,2]
        write=asyncio.create_task(self.io.save('player',deck))
        await wait_until(self.entered.is_set)
        deck[:] = [9,9]
        write.cancel()
        with self.assertRaises(asyncio.CancelledError): await write
        read=asyncio.create_task(self.io.load_state('player',[]))
        await asyncio.sleep(.02)
        self.assertFalse(read.done());self.assertEqual(len(self.io.pending),2)
        self.assertNotEqual(self.calls[0][2],threading.get_ident())
        self.release.set()
        self.assertEqual(await read,(1,2))

    async def test_queue_limit_refuses_extra_work_without_running_it(self):
        write=asyncio.create_task(self.io.save('first',[1]))
        await wait_until(self.entered.is_set)
        read=asyncio.create_task(self.io.load_state('first',[]))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(OSError,'busy'): await self.io.save('extra',[9])
        self.release.set();await write;await read
        self.assertEqual([call[0] for call in self.calls],['first'])

    async def test_storage_failure_propagates_original_exception(self):
        self.failure=PermissionError('original denied');self.release.set()
        with self.assertRaises(PermissionError) as caught: await self.io.save('player',[1])
        self.assertIs(caught.exception,self.failure)
        self.assertEqual(self.state,())

    async def test_cancelled_close_drains_even_failed_abandoned_work(self):
        errors=[];loop=asyncio.get_running_loop();previous=loop.get_exception_handler()
        loop.set_exception_handler(lambda loop,context:errors.append(context))
        try:
            self.failure=PermissionError('late failure')
            write=asyncio.create_task(self.io.save('player',[1]))
            await wait_until(self.entered.is_set)
            write.cancel()
            with self.assertRaises(asyncio.CancelledError): await write
            close=asyncio.create_task(self.io.close())
            await asyncio.sleep(.01);close.cancel();await asyncio.sleep(.01)
            self.assertFalse(close.done())
            with self.assertRaisesRegex(OSError,'stopping'): await self.io.load_state('player',[])
            self.release.set()
            with self.assertRaises(asyncio.CancelledError): await close
            self.assertFalse(self.io.pending);self.assertFalse(errors)
            self.assertTrue(all(not thread.is_alive() for thread in self.io._executor._threads))
        finally:loop.set_exception_handler(previous)


if __name__=='__main__':unittest.main()
