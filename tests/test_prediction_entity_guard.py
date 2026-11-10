"""Injected observer ABI/timeline tests; these do not load a native module."""
import ctypes as C
import struct
from types import SimpleNamespace
import unittest

from client_patch.prediction_worker.entity_guard import EntityGuard,EntityGuardError,Stats
from client_patch.prediction_worker.native import HostError
from server.game_data import encode_frame
from tests.test_prediction_worker import world_session,command
from tests.test_native_prediction_adapter import Heap


class Function:
    def __init__(self,call):self.call=call
    def __call__(self,*args):return self.call(*args)


class Helper:
    def __init__(self):
        self.value=Stats();self.value.version=1;self.value.owner=77
        self.installs=self.unbinds=0
        self.BAEntityGuardInstall=Function(self.install)
        self.BAEntityGuardBind=Function(self.bind)
        self.BAEntityGuardReset=Function(self.reset)
        self.BAGetEntityGuard=Function(self.read)
        self.BAEntityGuardUnbind=Function(self.unbind)
    def install(self):self.installs+=1;return 0
    def bind(self,world):self.value.world=world;self.value.master=world+0x22a08;return 0
    def reset(self):
        self.value.epoch+=1
        self.value.creates=self.value.hints=self.value.other_creates=self.value.other_hints=0
        return 0
    def read(self,out,size):
        assert size==96
        C.memmove(out,C.byref(self.value),size);return 0
    def unbind(self,world):
        assert world==self.value.world
        self.unbinds+=1;self.value.world=self.value.master=0;return 0


class Tests(unittest.TestCase):
    def observer(self):
        helper=Helper();arena=SimpleNamespace(dll=helper)
        return helper,arena,EntityGuard(arena,0x12340000)

    def step(self,observer,helper,frame,creates=1):
        observer.begin(encode_frame(frame,[b'',b'']));helper.value.creates=creates;observer.finish()

    def test_rolling_interval_allows_more_than_4095_lifetime_creations(self):
        helper,_,observer=self.observer()
        for frame in range(60):self.step(observer,helper,frame,256)
        self.assertTrue(observer.continuity(47,59));self.assertEqual(len(observer.counts),32)
        self.assertFalse(observer.continuity(-1,59));observer.close()

    def test_total_interval_wrap_refuses_before_admission(self):
        helper,_,observer=self.observer();self.step(observer,helper,0,4094)
        observer.begin(encode_frame(1,[b'',b'']));helper.value.creates=1
        with self.assertRaisesRegex(EntityGuardError,'interval'):observer.finish()
        self.assertFalse(observer.continuity(0,1));observer.close()

    def test_rewind_invalidates_counts_before_new_canonical_replay(self):
        helper,_,observer=self.observer()
        for frame in range(8):self.step(observer,helper,frame)
        self.assertTrue(observer.continuity(1,7));observer.invalidate_after(3)
        self.assertFalse(observer.continuity(1,7))
        for frame in range(4,8):self.step(observer,helper,frame,2)
        self.assertEqual(observer.counts[4],2);self.assertTrue(observer.continuity(1,7));observer.close()

    def test_wrong_world_foreign_error_and_direct_master_hint_refuse(self):
        for name,value in (('world',4),('master',4),('foreign',1),('depth',1),('error',5),('hints',1),('owner',78)):
            helper,_,observer=self.observer();setattr(helper.value,name,value)
            with self.assertRaises(EntityGuardError):observer.snapshot()
            # Retirement still releases the exact retained original world.
            helper.value.world=observer.world;observer.close()

    def test_frame_reset_and_one_finish_contract(self):
        helper,_,observer=self.observer()
        with self.assertRaises(EntityGuardError):observer.finish()
        observer.begin(encode_frame(0,[b'',b'']))
        with self.assertRaises(EntityGuardError):observer.begin(encode_frame(1,[b'',b'']))
        with self.assertRaises(EntityGuardError):observer.invalidate_after(-1)
        observer.finish()
        with self.assertRaises(EntityGuardError):observer.begin(encode_frame(0,[b'',b'']))
        observer.close();observer.close();self.assertEqual(helper.unbinds,1)

    def test_install_once_across_sequential_world_bindings(self):
        helper,arena,observer=self.observer();observer.close()
        second=EntityGuard(arena,0x56780000);self.assertEqual(helper.installs,1)
        second.close();self.assertEqual(helper.unbinds,2)

    def test_missing_observer_keeps_historical_headless_route_but_no_client_capability(self):
        self.assertIsNone(EntityGuard.optional(Heap(),1))
        _,session,key=world_session(arena=Heap())
        session.dispatch(command(64,struct.pack('<QII',key,12,4096)))
        self.assertEqual(session.dispatch(command(71,struct.pack('<Q',key))),(0,struct.pack('<I',0)))
        session.close()

    def test_real_dispatch_observes_process_step_and_rejects_creating_query(self):
        helper=Helper();heap=Heap();heap.dll=helper
        raw,session,key=world_session(arena=heap)
        session.dispatch(command(64,struct.pack('<QII',key,12,4096)))
        self.assertEqual(session.dispatch(command(71,struct.pack('<Q',key)))[1],struct.pack('<I',1))
        frame=encode_frame(0,[b'',b''])
        session.dispatch(command(65,struct.pack('<Q',key)+frame))
        session.dispatch(command(7,struct.pack('<Q',key)+frame))
        helper.value.creates=2
        session.dispatch(command(8,struct.pack('<QIi',key,50,-1)))
        self.assertEqual(session.entity_guards[key].counts,{0:2})
        original=raw.call
        def query(name,*args):
            result=original(name,*args)
            if name=='SimGetLabelsFrameBufferSize':helper.value.creates+=1
            return result
        raw.call=query
        with self.assertRaisesRegex(HostError,'query changed'):
            session.dispatch(command(11,struct.pack('<QII',key,0,0)))
        session.close();self.assertEqual(helper.unbinds,1)

    def test_original_view_auxiliary_hint_changes_are_permitted(self):
        helper=Helper();heap=Heap();heap.dll=helper
        raw,session,key=world_session(arena=heap)
        session.dispatch(command(64,struct.pack('<QII',key,12,4096)))
        original=raw.call
        def query(name,*args):
            result=original(name,*args)
            if name=='SimGetLabelsFrameBufferSize':helper.value.other_hints+=2
            return result
        raw.call=query
        self.assertEqual(session.dispatch(command(11,struct.pack('<QII',key,0,0)))[0],0)
        self.assertEqual(helper.value.other_hints,2);session.close()


if __name__=='__main__':unittest.main()
