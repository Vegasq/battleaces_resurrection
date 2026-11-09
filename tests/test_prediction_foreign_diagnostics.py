"""Synthetic allocator failures; no simulation DLL is loaded."""
import ctypes as C
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from client_patch.prediction_worker.native import Arena, ArenaStats, ForeignEvent, HostError


class DiagnosticTests(unittest.TestCase):
    def arena(self, reader=None):
        arena = Arena.__new__(Arena)
        arena._diagnostic_attempted = False
        arena._diagnostic_path = None
        arena._foreign = None if reader is None else (lambda:C.sizeof(ForeignEvent), lambda:1, reader)
        class DLL:
            def BAGetStats(self, pointer, size):
                value = C.cast(pointer, C.POINTER(ArenaStats)).contents
                value.version, value.error, value.foreign_threads = 2, 1, 4
                return 0
        arena.dll = DLL()
        return arena

    def test_old_helper_preserves_primary_error_without_writing(self):
        arena = self.arena()
        with self.assertRaisesRegex(HostError, 'unsafe heap ownership'):
            arena.healthy()
        self.assertFalse(arena._diagnostic_attempted)

    def test_published_record_saved_once_and_primary_error_preserved(self):
        calls = []
        def read(out, count, size):
            calls.append(1)
            if len(calls) == 1:
                return -2
            out[0].version, out[0].operation = 1, 2
            out[0].thread_id, out[0].owner_thread_id = 9, 7
            out[0].frame_count, out[0].addresses[0] = 1, 0x1234
            return count
        arena = self.arena(read)
        with tempfile.TemporaryDirectory() as folder, patch.object(Path, 'cwd', return_value=Path(folder)):
            with self.assertRaisesRegex(HostError, 'unsafe heap ownership.*diagnostic='):
                arena.healthy()
            path = Path(folder) / 'native-foreign-events.json'
            before = path.read_bytes()
            report = json.loads(before)
            self.assertEqual(report['events'][0]['frames'][0]['address'], 0x1234)
            self.assertEqual(report['events'][0]['thread_id'], 9)
            with self.assertRaises(HostError):
                arena.healthy()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(calls), 2)

    def test_unpublished_records_have_a_finite_retry_budget(self):
        calls = []
        def read(*args):
            calls.append(1)
            return -2
        arena = self.arena(read)
        with tempfile.TemporaryDirectory() as folder, patch.object(Path, 'cwd', return_value=Path(folder)), patch('client_patch.prediction_worker.native.time.sleep'):
            with self.assertRaisesRegex(HostError, 'unsafe heap ownership'):
                arena.healthy()
            report = json.loads((Path(folder) / 'native-foreign-events.json').read_text())
            self.assertIn('unavailable: -2', report['diagnostic_error'])
            self.assertEqual(len(calls), 11)


if __name__ == '__main__':
    unittest.main()
