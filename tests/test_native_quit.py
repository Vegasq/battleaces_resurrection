"""Diagnostic false-pass regressions; authored fixtures, no game execution."""
import hashlib
import json
from pathlib import Path
import shutil
import unittest
import uuid
from unittest.mock import Mock, patch

from tools import verify_native_quit as quit_probe


class NativeQuitVerifierTests(unittest.TestCase):
    def test_already_exited_process_cannot_pass_after_the_deadline(self):
        with self.assertRaisesRegex(AssertionError,'within60s'):
            quit_probe.observe_exit(Mock(poll=Mock(return_value=0)),1000,lambda:61000)

    def test_exit_poll_crossing_deadline_is_rejected(self):
        clock = Mock(side_effect=[60999,61000])
        with self.assertRaisesRegex(AssertionError,'observation exceeded60s'):
            quit_probe.observe_exit(Mock(poll=Mock(return_value=0)),1000,clock)

    def test_timely_exit_and_still_running_are_distinct(self):
        self.assertEqual(quit_probe.observe_exit(Mock(poll=Mock(return_value=0)),1000,lambda:1200),1200)
        self.assertIsNone(quit_probe.observe_exit(Mock(poll=Mock(return_value=None)),1000,lambda:1200))

    def test_build_receipt_rejects_stale_helper_source_and_incomplete_scope(self):
        parent = Path(__file__).resolve().parents[1]/'local'
        parent.mkdir(exist_ok=True)
        root = parent/('quit-receipt-'+uuid.uuid4().hex)
        root.mkdir()
        self.addCleanup(shutil.rmtree,root)
        if root.is_dir():
            (root/'client_patch/src').mkdir(parents=True)
            (root/'game').mkdir()
            for name in ('client_patch/build.ps1','client_patch/src/helper.cpp','client_patch/src/header.hpp'):
                (root/name).write_bytes(b'authored source')
            helper = root/'game/BattleAcesOffline.dll'
            helper.write_bytes(b'authored non-executable helper')
            sources = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (root/'client_patch').rglob('*') if p.is_file()}
            receipt = dict(schema=1,sources_unchanged_during_build=True,source_sha256=sources,
                           helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest())
            path = root/'helper-build.json'
            path.write_text(json.dumps(receipt),encoding='utf-8')
            with patch.object(quit_probe,'ROOT',root):
                self.assertEqual(quit_probe.verify_build_receipt(root/'game',path)['receipt'],receipt)
                for change in ('helper','source','missing-header','changed-during-build'):
                    with self.subTest(change=change):
                        changed = json.loads(json.dumps(receipt))
                        if change=='helper': changed['helper_sha256']='0'*64
                        if change=='source': changed['source_sha256']['client_patch/src/helper.cpp']='0'*64
                        if change=='missing-header': del changed['source_sha256']['client_patch/src/header.hpp']
                        if change=='changed-during-build': changed['sources_unchanged_during_build']=False
                        path.write_text(json.dumps(changed),encoding='utf-8')
                        with self.assertRaisesRegex(AssertionError,'does not bind'):
                            quit_probe.verify_build_receipt(root/'game',path)
