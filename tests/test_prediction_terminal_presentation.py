"""Authored FlatBuffers only;native post-completion advancement is separate."""
import struct
import unittest

from client_patch.prediction_worker.native import HostError
from client_patch.prediction_worker.presentation import confirmed_terminal_view


def snapshot(*, complete=1, terminal=8, frame=10):
    data = bytearray(160)
    struct.pack_into('<I',data,0,64)
    struct.pack_into('<HH',data,8,52,12)
    struct.pack_into('<H',data,12,4)
    struct.pack_into('<H',data,58,8)
    struct.pack_into('<iII',data,64,56,frame,56)
    struct.pack_into('<HHHHHHH',data,80,14,32,4,8,12,16,24)
    struct.pack_into('<i',data,128,48)
    data[132] = complete
    struct.pack_into('<iII',data,136,terminal,1,2)
    struct.pack_into('<Q',data,152,0x123456789abcdef0)
    return bytes(data)


class TerminalTests(unittest.TestCase):
    def test_unconfirmed_completion_changes_only_copied_complete_scalar(self):
        original = snapshot()
        view, masked, key = confirmed_terminal_view(original,confirmed_frame=7,physical_frame=10)
        self.assertTrue(masked)
        self.assertEqual([i for i,(a,b) in enumerate(zip(original,view)) if a != b],[132])
        self.assertEqual(original[132],1)
        self.assertEqual(key,(8,1,2,0x123456789abcdef0))

    def test_confirmation_admits_original_completion_and_correction_retracts_it(self):
        original = snapshot()
        for confirmed in (8,9,10):
            view, masked, key = confirmed_terminal_view(original,confirmed_frame=confirmed,physical_frame=10)
            self.assertIs(view,original)
            self.assertFalse(masked)
            self.assertEqual(key[0],8)
        corrected = snapshot(complete=0)
        self.assertEqual(confirmed_terminal_view(corrected,confirmed_frame=9,physical_frame=10),(corrected,False,None))

    def test_inconsistent_native_frame_or_terminal_metadata_refuses(self):
        for data, confirmed, physical in ((snapshot(),7,11),(snapshot(terminal=11),7,10),
                                          (snapshot(terminal=-1),7,10),(snapshot(),11,10),
                                          (snapshot(complete=2),7,10)):
            with self.assertRaises(HostError):
                confirmed_terminal_view(data,confirmed_frame=confirmed,physical_frame=physical)


if __name__ == '__main__':unittest.main()
