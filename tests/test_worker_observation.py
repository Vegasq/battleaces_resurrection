import asyncio,unittest,weakref
from types import SimpleNamespace
from tools.worker_observation import WorkerObservations

class Worker:
    def __init__(self):
        self.pid=123;self.exit=None;self.failure=None;self._cleanup_task=None
        self.process=SimpleNamespace(poll=lambda:self.exit,args=['python']+['x']*6+['modules'])
        self._stderr_thread=SimpleNamespace(is_alive=lambda:False)
        self.game_data_sha256='game';self.dll_sha256='dll';self.ai_info={'samples':[1]}
        self.gate=asyncio.Event();self.bad=False
    async def cleanup(self):
        await self.gate.wait()
        if self.bad:raise ValueError('actual cleanup failure')
        self.exit=0
    async def close(self):
        if self._cleanup_task is None:self._cleanup_task=asyncio.create_task(self.cleanup())
        await asyncio.shield(self._cleanup_task)
        return 'original result'

class Tests(unittest.IsolatedAsyncioTestCase):
    async def settle(self):
        for _ in range(4):await asyncio.sleep(0)
    async def test_success_metadata_and_return_preserved(self):
        observer=WorkerObservations();worker=observer.add(Worker());worker.gate.set()
        self.assertEqual(await worker.close(),'original result');await self.settle()
        rows=observer.report();self.assertTrue(rows[0]['reaped']);self.assertEqual(rows[0]['exit_code'],0)
        worker.ai_info['samples'].append(2)
        self.assertEqual(observer.report()[0]['ai'],{'samples':[1]})
        await worker.close();await self.settle();self.assertEqual(len(observer.report()),1)
    async def test_completed_worker_reference_not_retained(self):
        observer=WorkerObservations();worker=observer.add(Worker());reference=weakref.ref(worker)
        # The fake process poll must not itself create a worker reference cycle.
        worker.process=SimpleNamespace(poll=lambda:0,args=['python']+['x']*6+['modules'])
        worker.gate.set();await worker.close();await self.settle();del worker;await self.settle()
        self.assertIsNone(reference());self.assertEqual(observer.active(),0);self.assertTrue(observer.report()[0]['reaped'])
    async def test_cancelled_caller_keeps_observation_until_real_cleanup(self):
        observer=WorkerObservations();worker=observer.add(Worker());gate=worker.gate
        worker.process=SimpleNamespace(poll=lambda:0,args=['python']+['x']*6+['modules'])
        reference=weakref.ref(worker);caller=asyncio.create_task(worker.close());await self.settle()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):await caller
        del caller;del worker;await self.settle();self.assertIsNotNone(reference())
        with self.assertRaises(RuntimeError):observer.report()
        gate.set();await self.settle();self.assertTrue(observer.report()[0]['reaped'])
        self.assertIsNone(reference())
    async def test_cleanup_error_is_not_suppressed_or_accepted(self):
        observer=WorkerObservations();worker=observer.add(Worker());worker.bad=True;worker.gate.set()
        with self.assertRaisesRegex(ValueError,'actual cleanup'):await worker.close()
        await self.settle();self.assertEqual(len(observer.errors),1)
        with self.assertRaises(RuntimeError):observer.active()
        with self.assertRaises(RuntimeError):observer.report()
    async def test_lost_worker_without_cleanup_is_not_acceptance(self):
        observer=WorkerObservations();worker=observer.add(Worker())
        worker.process=SimpleNamespace(poll=lambda:None,args=['python']+['x']*6+['modules'])
        del worker;await self.settle()
        with self.assertRaises(RuntimeError):observer.active()
        with self.assertRaises(RuntimeError):observer.report()

if __name__=='__main__':unittest.main()
