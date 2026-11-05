"""Executable boundary controls and rejection of incomplete game182 evidence."""
import copy
import json
import shutil
import subprocess
import unittest

from tests import test_ads_caller as caller_tests
from tools.frida_ads_game import build_source, review_rows


GAME_HARNESS = caller_tests.HARNESS.replace(
    'toString(){return', 'equals(p){return this.v===p.v;}\n toUInt32(){return this.v>>>0;}\n toString(){return'
).replace(
    "const host={Process:",
    "const host={ptr:v=>new P(v==='0xffffffffffffffff'?-1:Number(v)),Process:"
).replace(
    'getCurrentThreadId:()=>29,',
    "getCurrentThreadId:()=>29,getModuleByName:name=>({getExportByName(){if(input.mode==='export')throw new Error('missing export');return new P(name==='kernelbase.dll'||input.mode==='alias'?100:200);}}),"
).replace(
    'Thread:{backtrace:', 'Thread:{sleep:s=>{if(s!==.2)throw new Error("hold differs");},backtrace:'
).replace(
    "const final=host.rpc.exports.finish();",
    """const foreign={};hooks.get(100).onEnter.call(foreign,[new P(77),new P(0)]);
 const afterForeign=host.rpc.exports.snapshot();
 if(afterForeign.finished)throw new Error('foreign termination closed observer');
 if(input.mode!=='no-exit'){
   const invocation={};hooks.get(100).onEnter.call(invocation,[new P(-1),new P(input.mode==='status'?7:0)]);
   if(hooks.has(200))hooks.get(200).onEnter.call({},[new P(-1),new P(0)]);
   if(input.mode==='returned')hooks.get(100).onLeave.call(invocation);
 }
 const final=host.rpc.exports.snapshot();"""
)


class AdsGameTests(unittest.TestCase):
    def setUp(self):
        fixture = caller_tests.AdsCallerTests(); fixture.setUp(); self.config = fixture.config

    def run_js(self, mode='', calls=0):
        node = shutil.which('node')
        if not node: self.skipTest('Node required for boundary control')
        result = subprocess.run([node, '-e', GAME_HARNESS],
            input=json.dumps(dict(source=build_source(self.config), config=self.config, mode=mode, calls=calls)),
            capture_output=True, text=True, check=True, timeout=5)
        return json.loads(result.stdout)

    def test_foreign_ignored_self_closes_once_across_forwarders(self):
        for mode, hooks in (('', 2), ('alias', 1)):
            with self.subTest(mode=mode):
                result = self.run_js(mode, 13)
                self.assertNotIn('error', result)
                review = review_rows(result['rows'], self.config)
                self.assertEqual((review['calls'], review['caller_records'], review['suppressed']), (13, 8, 5))
                self.assertEqual(review['armed']['data']['uniqueHooks'], hooks)
                self.assertEqual(result['detached'], 1)
                self.assertFalse(review['whole_process_coverage'])

    def test_quiet_interval_is_scoped_not_absence(self):
        review = review_rows(self.run_js()['rows'], self.config)
        self.assertEqual(review['calls'], 0)
        self.assertFalse(review['producer_resolved'])
        self.assertFalse(review['full_privacy_qualified'])

    def test_missing_returning_failed_or_nonzero_exit_rejected(self):
        for mode in ('no-exit', 'returned', 'status', 'export', 'final-guard', 'unload'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                review_rows(self.run_js(mode)['rows'], self.config)

    def test_boundary_identity_loss_and_tampering_rejected(self):
        rows = self.run_js()['rows']; variants = [rows[:-1], rows[1:]]
        for key, value in [('tid', 30), ('pid', True), ('elapsedMs', -1), ('runId', 'a'*32)]:
            bad = copy.deepcopy(rows); bad[-1][key] = value; variants.append(bad)
        for key, value in [('transportHoldMs', 0), ('currentProcessPseudoHandle', False), ('callerFinished', 1), ('exitStatus', True)]:
            bad = copy.deepcopy(rows); bad[-1]['data'][key] = value; variants.append(bad)
        bad = copy.deepcopy(rows); bad[-1], bad[-2] = bad[-2], bad[-1]; variants.append(bad)
        for bad in variants:
            with self.subTest(bad=bad), self.assertRaises(ValueError): review_rows(bad, self.config)


if __name__ == '__main__': unittest.main()
