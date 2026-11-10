"""Confirmed selection epochs from authored views; no native library loaded."""
import importlib
import struct
import unittest

from tests.test_prediction_entity_history import snapshot


class ActiveTests(unittest.TestCase):
    def create(self, **kwargs):
        return importlib.import_module('client_patch.prediction_worker.entities').ActiveIdentityHistory(**kwargs)

    def promote(self, history, frame, rows):
        history.observe(snapshot(frame, rows), physical_frame=frame)
        history.confirm(frame)

    def test_speculative_views_do_not_issue_tokens_and_repeated_confirmed_view_is_stable(self):
        history=self.create()
        history.observe(snapshot(0,{0:(0,3),42:(0,75)}),physical_frame=0)
        self.assertEqual(history.active_packet(),struct.pack('<iI',-1,0))
        history.confirm(0);first=history.active_packet()
        self.assertEqual(len(first),8+2*20)
        self.assertTrue(all(row[3] for row in struct.iter_unpack('<IIIQ',first[8:])))
        self.promote(history,0,{0:(0,3),42:(0,75)})
        self.assertEqual(history.active_packet(),first)
        history.observe(snapshot(1,{0:(0,3),42:(1,80),79:(0,75)}),physical_frame=1)
        self.assertEqual(history.active_packet(),first)
        history.invalidate_after(0)
        self.promote(history,1,{0:(0,3),42:(0,75)})
        self.assertEqual(list(struct.iter_unpack('<IIIQ',history.active_packet()[8:])),list(struct.iter_unpack('<IIIQ',first[8:])))

    def test_confirmed_absence_reappearance_and_identity_changes_issue_new_tokens(self):
        history=self.create()
        self.promote(history,0,{42:(0,75)})
        old=struct.unpack_from('<IIIQ',history.active_packet(),8)[3]
        self.promote(history,1,{})
        self.assertEqual(history.active_packet(),struct.pack('<iI',1,0))
        self.promote(history,2,{42:(0,75)})
        second=struct.unpack_from('<IIIQ',history.active_packet(),8)[3]
        self.assertGreater(second,old)
        self.promote(history,3,{42:(1,75)})
        third=struct.unpack_from('<IIIQ',history.active_packet(),8)[3]
        self.promote(history,4,{42:(1,76)})
        fourth=struct.unpack_from('<IIIQ',history.active_packet(),8)[3]
        self.assertTrue(old<second<third<fourth)

    def test_batched_promotion_observes_intermediate_absence(self):
        history=self.create();self.promote(history,0,{42:(0,75)})
        old=history.active_packet()[8:]
        history.observe(snapshot(1,{}),physical_frame=1)
        history.observe(snapshot(2,{42:(0,75)}),physical_frame=2)
        history.confirm(2)
        self.assertNotEqual(history.active_packet()[8:],old)

    def test_invalid_or_rewritten_confirmed_views_reject_atomically(self):
        history=self.create();self.promote(history,0,{0:(0,3)})
        before=history.active_packet(),dict(history.views),history.confirmed_frame
        for action in (lambda:history.observe(snapshot(0,{0:(1,3)}),physical_frame=0),
                       lambda:history.invalidate_after(-1),lambda:history.confirm(-2)):
            with self.assertRaises(ValueError):action()
            self.assertEqual((history.active_packet(),history.views,history.confirmed_frame),before)

    def test_bootstrap_requires_an_actual_minus_one_view_and_stays_world_local(self):
        history=self.create()
        with self.assertRaises(ValueError):history.bootstrap(snapshot(0,{0:(0,3)}))
        raw=snapshot(0xffffffff,{0:(0,3)})
        history.bootstrap(raw)
        first=history.active_packet()
        self.assertEqual(struct.unpack_from('<iI',first),(-1,1))
        history.bootstrap(raw);self.assertEqual(history.active_packet(),first)
        self.promote(history,0,{0:(0,3)})
        self.assertEqual(history.active_packet()[8:],first[8:])
        fresh=self.create();self.assertEqual(fresh.active_packet(),struct.pack('<iI',-1,0))

    def test_gaps_renew_by_default_and_only_exact_interval_proof_can_preserve(self):
        for proven in (None,False,True):
            with self.subTest(proven=proven):
                history=self.create();self.promote(history,0,{0:(0,3),42:(0,75)})
                old=history.active_packet()[8:]
                history.observe(snapshot(3,{0:(0,3),42:(0,75)}),physical_frame=3)
                calls=[]
                def proof(first,last):calls.append((first,last));return proven
                history.confirm(3,continuity_proof=None if proven is None else proof)
                self.assertEqual(calls,[] if proven is None else [(0,3)])
                if proven is True:self.assertEqual(history.active_packet()[8:],old)
                else:self.assertNotEqual(history.active_packet()[8:],old)

    def test_proof_never_preserves_changed_identity_and_invalid_proof_is_atomic(self):
        history=self.create();self.promote(history,0,{42:(0,75)})
        old=history.active_packet()[8:]
        history.observe(snapshot(3,{42:(1,75)}),physical_frame=3)
        before=history.active_packet(),dict(history.views),history.confirmed_frame
        for bad in (True,lambda *_:1,lambda *_:(_ for _ in ()).throw(ValueError('unqualified'))):
            with self.assertRaises(ValueError):history.confirm(3,continuity_proof=bad)
            self.assertEqual((history.active_packet(),history.views,history.confirmed_frame),before)
        history.confirm(3,continuity_proof=lambda *_:True)
        self.assertNotEqual(history.active_packet()[8:],old)

    def test_token_exhaustion_and_byte_budget_fail_before_promotion(self):
        history=self.create();self.promote(history,0,{0:(0,3)})
        history.observe(snapshot(1,{0:(0,3),42:(0,75)}),physical_frame=1)
        history._next_token=0x10000000000000000
        before=history.active_packet(),dict(history.views),history.confirmed_frame
        with self.assertRaises(ValueError):history.confirm(1)
        self.assertEqual((history.active_packet(),history.views,history.confirmed_frame),before)
        limited=self.create(max_entities=1,max_bytes=20)
        with self.assertRaises(ValueError):limited.bootstrap(snapshot(0xffffffff,{0:(0,3)}))
        self.assertEqual((limited.views,limited.active_packet()),({},struct.pack('<iI',-1,0)))

    def test_explicit_dead_state_leaves_scalar_contract_but_not_active_selection(self):
        from client_patch.prediction_worker.entities import IdentityHistory
        from tests.test_prediction_worker_ledger_integration import view
        raw=bytearray(view(1,{0:(0,3),42:(0,75)}))
        # Add the authored SimFrame.States component without altering Army/Type.
        struct.pack_into('<HH',raw,8,14,24);struct.pack_into('<H',raw,20,20)
        vtable=len(raw);raw.extend(struct.pack('<HHHH',8,12,4,8))
        table=len(raw);raw.extend(struct.pack('<iII',table-vtable,8,12))
        raw.extend(struct.pack('<II',1,42));raw.extend(struct.pack('<II',1,6))
        struct.pack_into('<I',raw,52,table-52)
        history=self.create();self.promote(history,0,{0:(0,3),42:(0,75)})
        old=history.active[42][2]
        history.observe(bytes(raw),physical_frame=1);history.confirm(1)
        self.assertNotIn(42,history.active)
        scalar=IdentityHistory();scalar.observe(bytes(raw),physical_frame=1);scalar.confirm(1)
        self.assertEqual(scalar.lookup(42),(0,75))
        self.promote(history,2,{0:(0,3),42:(0,75)})
        self.assertGreater(history.active[42][2],old)


class WorkerActiveTests(unittest.TestCase):
    def worker(self,*,before_begin=True,actual_minus_one=True,slot=0):
        from tests.test_prediction_worker import Raw,command
        from tests.test_prediction_worker_ledger_integration import NativeFixture,SnapshotHeap,view
        from client_patch.prediction_worker.native import NativeSession
        from tests.test_prediction_command_ledger import body,join
        class BootstrapNative(NativeFixture):
            def call(inner,name,*args):
                if name=='SimMakeSimFrame' and inner.physical<0 and actual_minus_one:
                    inner.frame=view(0xffffffff,inner.rows(),args[1])
                    return Raw.call(inner,name,*args)
                return super().call(name,*args)
        native=BootstrapNative();session=NativeSession(native,arena=SnapshotHeap(native))
        session.dispatch(command(1,b'\0'));_,data=session.dispatch(command(5,b'authored-world'))
        key,=struct.unpack('<Q',data)
        begin=lambda:session.dispatch(command(64,struct.pack('<QII',key,12,1024*1024)))
        if not before_begin:begin()
        session.dispatch(command(9,struct.pack('<QII',key,slot,0)))
        if before_begin:begin()
        session.dispatch(command(67,struct.pack('<QQ',key,1)+body([join(slot)],slot=slot)))
        self.addCleanup(session.close)
        return native,session,key

    def test_70_uses_actual_prebegin_own_bootstrap_and_never_changes_68(self):
        from tests.test_prediction_worker import command
        for slot in (0,1):
            native,session,key=self.worker(slot=slot)
            before=len(native.calls),tuple(session.arena.events)
            code,packet=session.dispatch(command(70,struct.pack('<Q',key)))
            self.assertEqual(code,0);self.assertEqual(struct.unpack_from('<i',packet)[0],-1)
            self.assertGreater(struct.unpack_from('<I',packet,4)[0],0)
            self.assertTrue(all(row[3] for row in struct.iter_unpack('<IIIQ',packet[8:])))
            self.assertEqual(session.dispatch(command(70,struct.pack('<Q',key))),(0,packet))
            self.assertEqual(session.dispatch(command(68,struct.pack('<Q',key))),(0,struct.pack('<iI',-1,0)))
            self.assertEqual((len(native.calls),tuple(session.arena.events)),before)
            self.assertFalse(session.bootstrap_identity_views)

    def test_no_prebegin_actual_view_means_no_synthetic_bootstrap(self):
        from tests.test_prediction_worker import command
        for options in (dict(before_begin=False),dict(actual_minus_one=False)):
            native,session,key=self.worker(**options)
            self.assertEqual(session.dispatch(command(70,struct.pack('<Q',key))),(0,struct.pack('<iI',-1,0)))

    def test_retirement_clears_active_epochs_and_stale_world_is_rejected(self):
        from tests.test_prediction_worker import command
        native,session,key=self.worker()
        session.dispatch(command(6,struct.pack('<Q',key)))
        self.assertFalse(session.active_identity_histories);self.assertFalse(session.bootstrap_identity_views)
        with self.assertRaises(RuntimeError):session.dispatch(command(70,struct.pack('<Q',key)))

    def test_actual_worker_gap_after_correction_renews_tokens_without_unqualified_proof(self):
        from tests.test_prediction_worker_ledger_integration import IntegrationTests
        from tests.test_prediction_command_ledger import MOVE
        fixture=IntegrationTests();fixture.ready()
        try:
            active=fixture.s.active_identity_histories[fixture.key]
            old=active.active[0][2]
            for number in (1,2,3):fixture.process(number);fixture.step();fixture.query()
            fixture.authority(1,remote=[MOVE]);fixture.authority(2);fixture.authority(3)
            fixture.process(4)
            self.assertEqual(active.promoted_frame,3)
            self.assertGreater(active.active[0][2],old)
            self.assertEqual(active.active[79][:2],(1,75))
            self.assertFalse(any(frame in active.views for frame in (1,2)))
            fixture.step()
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
