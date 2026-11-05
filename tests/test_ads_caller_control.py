"""Opt-in read-only rejection tests using a retained authored native control.

Set BA_ADS_CALLER_CONTROL to its folder. Never launch or modify a target here.
"""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.ads_caller_control import review


@unittest.skipUnless(os.environ.get('BA_ADS_CALLER_CONTROL'),'retained authored native evidence not selected')
class AdsCallerControlEvidence(unittest.TestCase):
    def setUp(self):
        self.folder=Path(os.environ['BA_ADS_CALLER_CONTROL']).resolve()
        self.read_bytes=Path.read_bytes

    def changed(self,name,mutate):
        original=json.loads((self.folder/name).read_bytes())
        value=copy.deepcopy(original);mutate(value)
        encoded=json.dumps(value).encode()
        selected=(self.folder/name).resolve()
        def read(path):
            return encoded if path.resolve()==selected else self.read_bytes(path)
        with patch.object(Path,'read_bytes',read):
            with self.assertRaises((ValueError,AssertionError)):review(self.folder)
        self.assertEqual(json.loads((self.folder/name).read_bytes()),original)

    def test_native_control_accepts_with_explicit_scope(self):
        result=review(self.folder)
        self.assertTrue(result['passed'])
        self.assertEqual((result['calls'],result['threads'],result['post_detach_calls']),(13,2,2))
        self.assertFalse(result['producer_resolved'])
        self.assertFalse(result['game_executed'])

    def test_forced_or_incomplete_lifetime_rejected(self):
        for mutate in (
            lambda r:r['launch'].update(forced_cleanup=True),
            lambda r:r['tracker'].update(complete=False),
            lambda r:r['tracker']['final_accounting'].update(active=1),
            lambda r:r['tracker']['records'][0]['exit'].update(exit_code=1),
        ):
            with self.subTest(mutate=mutate):self.changed('owner.json',mutate)

    def test_foreign_mixed_truncated_and_error_provider_rejected(self):
        for mutate in (
            lambda r:r.update(isError=True),
            lambda r:r['structuredContent']['parameters'].update(session_id='foreign'),
            lambda r:r['structuredContent']['normalized_result'].update(pid=1),
            lambda r:r['structuredContent']['normalized_result'].update(messages_truncated=True),
            lambda r:r['structuredContent']['normalized_result']['messages'][2].update(script_id='foreign'),
            lambda r:r['structuredContent']['normalized_result']['messages'][2].update(type='error'),
        ):
            with self.subTest(mutate=mutate):self.changed('rea-final.json',mutate)

    def test_wrong_source_and_missing_detach_rejected(self):
        self.changed('rea-load.json',lambda r:r['structuredContent']['normalized_result'].update(source_sha256='0'*64))
        self.changed('rea-close.json',lambda r:r.update(isError=True))

    def test_lost_records_and_wrong_caller_or_thread_rejected(self):
        for mutate in (
            lambda r:r['structuredContent']['normalized_result']['messages'].pop(),
            lambda r:r['structuredContent']['normalized_result']['messages'][2]['payload'].update(tid=1),
            lambda r:r['structuredContent']['normalized_result']['messages'][2]['payload']['data']['caller'].update(rva='0x7'),
            lambda r:r['structuredContent']['normalized_result']['messages'][-1]['payload']['data'].update(calls=14),
        ):
            with self.subTest(mutate=mutate):self.changed('rea-final.json',mutate)


if __name__=='__main__':unittest.main()
