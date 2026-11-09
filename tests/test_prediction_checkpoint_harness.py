import json
from pathlib import Path
import tempfile
import unittest

from tools.verify_prediction_checkpoint import read_progress


class ProgressRaceTests(unittest.TestCase):
    def test_reader_uses_previous_complete_record_during_partial_successor(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'progress.jsonl'
            previous = dict(operation='SimStep',next_frame=500)
            path.write_bytes(json.dumps(previous).encode()+b'\n'+b'{"operation":')
            self.assertEqual(read_progress(path),previous)
            with path.open('ab') as stream:
                stream.write(b'"SimMakeSimFrame","next_frame":501}\n')
            self.assertEqual(read_progress(path),dict(operation='SimMakeSimFrame',next_frame=501))

    def test_initial_empty_or_partial_record_is_not_a_native_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'progress.jsonl'
            for content in (b'',b'{"operation":'):
                path.write_bytes(content)
                self.assertIsNone(read_progress(path))

    def test_completed_corruption_remains_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'progress.jsonl'
            path.write_bytes(b'{broken}\n')
            with self.assertRaises(ValueError): read_progress(path)
