"""Authored component FlatBuffers and confirmed identity admission."""
import struct
import unittest

from client_patch.prediction_worker.entities import IdentityError, IdentityHistory, identities


def snapshot(frame, rows, *, duplicate=False):
    data = bytearray(96)
    struct.pack_into('<I',data,0,32)
    struct.pack_into('<HHHHHH',data,8,12,16,4,0,8,12)
    struct.pack_into('<iIII',data,32,24,frame,24,36)
    struct.pack_into('<HHHH',data,48,8,12,4,8)
    struct.pack_into('<HHHH',data,56,8,12,4,8)
    struct.pack_into('<i',data,64,8)
    struct.pack_into('<i',data,80,32)
    entries = list(rows.items())
    if duplicate:entries += entries[:1]
    def vector(values):
        start = len(data)
        data.extend(struct.pack('<I',len(values)))
        for value in values:data.extend(struct.pack('<I',value))
        return start
    for table,component in ((64,0),(80,1)):
        ids = vector([entity for entity,_ in entries])
        values = vector([value[component] for _,value in entries])
        struct.pack_into('<II',data,table+4,ids-table-4,values-table-8)
    return bytes(data)


class HistoryTests(unittest.TestCase):
    def test_zero_hq_id_and_component_identity_decode(self):
        raw = snapshot(4,{0:(0,3),79:(1,75)})
        self.assertEqual(identities(raw,expected_frame=4,max_entities=2),{0:(0,3),79:(1,75)})
        with self.assertRaises(IdentityError):identities(raw,expected_frame=3,max_entities=2)
        with self.assertRaises(IdentityError):identities(snapshot(4,{0:(0,3)},duplicate=True),expected_frame=4,max_entities=2)

    def test_predicted_spawn_never_admitted_before_confirmation(self):
        history = IdentityHistory()
        history.observe(snapshot(0,{0:(0,3)}),physical_frame=0)
        history.confirm(0)
        history.observe(snapshot(1,{0:(0,3),79:(0,75)}),physical_frame=1)
        self.assertIsNone(history.lookup(79))
        history.confirm(1)
        self.assertEqual(history.lookup(79),(0,75))
        frame,count = struct.unpack_from('<iI',history.packet())
        self.assertEqual((frame,count),(1,2))

    def test_correction_invalidates_future_maps_without_wrong_identity_promotion(self):
        history = IdentityHistory()
        history.observe(snapshot(0,{0:(0,3)}),physical_frame=0);history.confirm(0)
        history.observe(snapshot(1,{79:(0,75)}),physical_frame=1)
        history.invalidate_after(0)
        history.observe(snapshot(1,{79:(1,80)}),physical_frame=1)
        history.confirm(1)
        self.assertEqual(history.lookup(79),(1,80))
        with self.assertRaises(IdentityError):history.invalidate_after(0)

    def test_batched_confirmations_preserve_observed_dead_unit_identity(self):
        history = IdentityHistory()
        for frame,rows in enumerate(({0:(0,3)},{0:(0,3),79:(0,75)},{0:(0,3)})):
            history.observe(snapshot(frame,rows),physical_frame=frame)
        history.confirm(2)
        self.assertEqual(history.lookup(79),(0,75))
        self.assertEqual(history.promoted_frame,2)

    def test_budget_or_confirmed_rewrite_refuses_atomically(self):
        history = IdentityHistory(max_views=2,max_entities=2,max_known=3,max_bytes=96)
        history.observe(snapshot(0,{0:(0,3)}),physical_frame=0);history.confirm(0)
        history.observe(snapshot(1,{0:(0,3)}),physical_frame=1)
        before = history.packet(),dict(history.views),history.confirmed_frame
        with self.assertRaises(IdentityError):history.observe(snapshot(2,{0:(0,3)}),physical_frame=2)
        with self.assertRaises(IdentityError):history.observe(snapshot(0,{0:(1,3)}),physical_frame=0)
        with self.assertRaises(IdentityError):history.confirm(-1)
        self.assertEqual((history.packet(),history.views,history.confirmed_frame),before)


if __name__ == '__main__':unittest.main()
