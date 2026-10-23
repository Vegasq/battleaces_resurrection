"""Diagnostic timing preserves the real storage/wire call and calling thread."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading
import unittest
from tools.verify_room_faults import observe_sync_call


class TimingTests(unittest.TestCase):
    def test_storage_arguments_return_identity_and_original_thread_are_preserved(self):
        rows=[];calls=[];answer=object();deck=[1,2];cosmetics=object()
        def save(*args,**kwargs):calls.append((args,kwargs,threading.get_ident()));return answer
        store=SimpleNamespace(save=save)
        observe_sync_call(store,'save',rows,('profile',))
        self.assertIs(store.save('profile155',deck,cosmetics=cosmetics),answer)
        self.assertEqual(calls,[(('profile155',deck),{'cosmetics':cosmetics},threading.get_ident())])
        self.assertIs(calls[0][0][1],deck)
        self.assertEqual((rows[0]['profile'],rows[0]['thread'],rows[0]['status']),('profile155',threading.get_ident(),'reply'))
        self.assertNotIn('deck',rows[0]);self.assertNotIn('cosmetics',rows[0])

    def test_original_storage_error_reaches_caller_without_retry(self):
        rows=[];error=PermissionError('original denied');calls=[]
        def save(*args,**kwargs):calls.append(1);raise error
        store=SimpleNamespace(save=save);observe_sync_call(store,'save',rows,('profile',))
        with self.assertRaises(PermissionError) as caught:store.save('profile155',[])
        self.assertIs(caught.exception,error);self.assertEqual(calls,[1])
        self.assertEqual((rows[0]['status'],rows[0]['error_type']),('error','PermissionError'))
        self.assertGreaterEqual(rows[0]['ended'],rows[0]['started'])

    def test_wire_packet_is_not_retained_and_executor_thread_is_not_changed(self):
        rows=[];calls=[];packet=object();reply=object()
        def wire(*args):calls.append((args,threading.get_ident()));return reply
        worker=SimpleNamespace(_wire_exchange=wire)
        observe_sync_call(worker,'_wire_exchange',rows,(None,'operation','request_id','frame'))
        with ThreadPoolExecutor(max_workers=1) as executor:
            self.assertIs(executor.submit(worker._wire_exchange,packet,7,25,10).result(timeout=3),reply)
        self.assertEqual(calls[0][0],(packet,7,25,10))
        self.assertEqual(rows[0]['thread'],calls[0][1]);self.assertNotEqual(rows[0]['thread'],threading.get_ident())
        self.assertEqual((rows[0]['operation'],rows[0]['request_id'],rows[0]['frame']),(7,25,10))
        self.assertNotIn('packet',rows[0]);self.assertNotIn('payload',rows[0])


if __name__=='__main__':unittest.main()
