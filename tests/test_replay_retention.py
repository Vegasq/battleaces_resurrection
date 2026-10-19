import hashlib
from contextlib import contextmanager
from pathlib import Path
import shutil
import unittest
import uuid
from tools import replay_retention as retention

ROOT=Path(__file__).resolve().parents[1]/'local'

@contextmanager
def owned_directory():
    folder=ROOT/('retention-unit-'+uuid.uuid4().hex)
    folder.mkdir()
    try:yield folder
    finally:
        if folder.resolve().is_relative_to(ROOT.resolve()):shutil.rmtree(folder)


class ReplayRetentionTests(unittest.TestCase):
    def arrange(self,folder,count):
        for index in range(count-99,count):(folder/retention.filename(index)).write_bytes(retention.payload(index))
        marker=folder/'unrelated.txt';marker.write_bytes(b'authored marker')
        (folder/'original native.rep').write_bytes(b'original native fixture')
        return dict(count=count,unrelated_sha256=hashlib.sha256(marker.read_bytes()).hexdigest())

    def test_both_original_retention_boundaries(self):
        for count in (100,101):
            with self.subTest(count=count),owned_directory() as name:
                folder=Path(name);fixture=self.arrange(folder,count)
                path,evidence=retention.verify(folder,fixture)
                self.assertEqual(path.name,'original native.rep')
                self.assertEqual(evidence['deleted_oldest'],count-99)
                self.assertEqual(evidence['total_replays'],100)

    def test_same_count_wrong_victim_and_changed_survivor_are_rejected(self):
        with owned_directory() as name:
            folder=Path(name);fixture=self.arrange(folder,100)
            (folder/retention.filename(1)).rename(folder/retention.filename(0))
            with self.assertRaisesRegex(AssertionError,'wrong creation-time'):retention.verify(folder,fixture)
            (folder/retention.filename(0)).rename(folder/retention.filename(1))
            (folder/retention.filename(1)).write_bytes(b'changed')
            with self.assertRaisesRegex(AssertionError,'bytes changed'):retention.verify(folder,fixture)

    def test_extra_native_file_and_changed_unrelated_marker_are_rejected(self):
        with owned_directory() as name:
            folder=Path(name);fixture=self.arrange(folder,101)
            extra=folder/'extra.rep';extra.write_bytes(b'extra')
            with self.assertRaisesRegex(AssertionError,'exactly one'):retention.verify(folder,fixture)
            extra.unlink();(folder/'unrelated.txt').write_bytes(b'changed')
            with self.assertRaisesRegex(AssertionError,'unrelated'):retention.verify(folder,fixture)
