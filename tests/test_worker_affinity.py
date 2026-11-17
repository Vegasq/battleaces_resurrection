"""Authored controls only; never change the test runner's process affinity."""
import os
import struct
import unittest
from unittest.mock import patch

from server import worker_affinity as a


def core(mask, group=0):
    raw = bytearray(48)
    struct.pack_into('<II', raw, 0, 0, 48)
    struct.pack_into('<H', raw, 30, 1)
    struct.pack_into('<QH', raw, 32, mask, group)
    return bytes(raw)


class Process:
    pid = os.getpid() + 10000
    _handle = 123

    def poll(self):
        return None


class API:
    def __init__(self):
        self.mask = 15
        self.calls = []

    def topology(self):
        return ((0, 1), (2, 3))

    def masks(self, handle):
        return self.mask, 15

    def set_mask(self, handle, mask):
        self.calls.append((handle, mask))
        self.mask = mask

    def pid(self, handle):
        return Process.pid


class WorkerAffinityTests(unittest.TestCase):
    def test_parse_smt_and_select_distinct_cores(self):
        cores = a.parse_core_topology(core(3) + core(12))
        self.assertEqual(cores, ((0, 1), (2, 3)))
        self.assertEqual(a.select_physical_cpus(cores, 14), (1, 2))

    def test_topology_refuses_truncation_overlap_groups_and_empty(self):
        for raw in (b'', core(3)[:-1], core(3)+core(2), core(1, 1)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                a.parse_core_topology(raw)

    def test_refuses_one_physical_core_even_with_smt(self):
        with self.assertRaises(ValueError):
            a.select_physical_cpus(((0, 1), (2, 3)), 3)

    def test_invalid_cpu_requests(self):
        for cpus in ([], [True], [0, 0], [-1], [64], [0, 1, 2], '0'):
            with self.subTest(cpus=cpus), self.assertRaises(ValueError):
                a.WindowsWorkerAffinity(cpus)

    def test_retained_handle_and_receipt_no_pid_open(self):
        api = API()
        with patch.object(a, '_WindowsAPI', return_value=api):
            policy = a.WindowsWorkerAffinity([0, 2])
            receipt = policy.apply(Process())
            self.assertEqual(api.calls, [(123, 5)])
            self.assertEqual(receipt['actual_mask'], 5)
            self.assertEqual(receipt['physical_core_indices'], [0, 1])
            self.assertIs(receipt['before_create'], True)
            self.assertEqual(policy.verify(), 5)
            with self.assertRaises(ValueError):
                policy.apply(Process())

    def test_siblings_and_outside_inherited_mask_refused_before_mutation(self):
        for cpus, mask in (([0, 1], 15), ([0, 2], 3)):
            api = API(); api.mask = mask
            with patch.object(a, '_WindowsAPI', return_value=api), self.assertRaises(ValueError):
                a.WindowsWorkerAffinity(cpus).apply(Process())
            self.assertEqual(api.calls, [])

    def test_actual_mask_mismatch_refused(self):
        api = API()
        api.set_mask = lambda *args: None
        with patch.object(a, '_WindowsAPI', return_value=api), self.assertRaises(ValueError):
            a.WindowsWorkerAffinity([0]).apply(Process())

    def test_identity_self_dead_and_missing_handle_refused(self):
        for change in ('self', 'dead', 'handle', 'identity'):
            process, api = Process(), API()
            if change == 'self': process.pid = os.getpid()
            if change == 'dead': process.poll = lambda: 0
            if change == 'handle': process._handle = None
            if change == 'identity': api.pid = lambda handle: 1
            with patch.object(a, '_WindowsAPI', return_value=api), self.assertRaises(ValueError):
                a.WindowsWorkerAffinity([0]).apply(process)
            self.assertEqual(api.calls, [])


if __name__ == '__main__':
    unittest.main()
