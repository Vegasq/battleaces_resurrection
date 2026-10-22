"""False-pass regressions for scoped original cache constructor diagnostics."""
import re
import unittest
from tools.telemetry_cache_evidence import validate


PATH = '[100] TELEMETRY CACHEPATH probe passed: version=1 thread=17 getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0'
TYPED = '[102] TELEMETRY CACHETYPE probe passed: version=1 thread=17 parsed=4 constructed=2 errors=1 sessions=1 authoredFieldsRetained=1 missingKeyRejected=2 cacheManagerConstructed=0 reportDelivered=0 diskQueueRead=0'


class CacheContractEvidenceTests(unittest.TestCase):
    def test_scoped_proof_preserves_its_limits(self):
        proof=validate(PATH+'\n'+TYPED,[dict(event='OnConfirm.dispatch',tick=110,thread=17)])
        self.assertTrue(proof['passed'])
        self.assertFalse(proof['whole_run_cache_isolation'])
        self.assertFalse(proof['disk_queue_read'])
        self.assertFalse(proof['report_delivered'])

    def test_incomplete_duplicate_failed_or_overclaimed_records_reject(self):
        text=PATH+'\n'+TYPED;rows=[dict(event='OnConfirm.dispatch',tick=110,thread=17)]
        changes=[PATH,TYPED,text+'\n'+PATH,text+'\n'+TYPED,TYPED+'\n'+PATH,
                 text+'\nTELEMETRY CACHE probe failed: injected control']
        for key,value in [('icallRestored','0'),('wholeRunIsolation','1'),('reportPayloadRead','1'),
                          ('reportEnumeration','1'),('originalBodies','0'),('missingKeyRejected','0'),
                          ('authoredFieldsRetained','0'),('errors','0'),('sessions','0'),
                          ('cacheManagerConstructed','1'),('reportDelivered','1'),('diskQueueRead','1')]:
            changes.append(re.sub(r'\b'+key+r'=\d+',key+'='+value,text))
        changes.extend([text.replace('missingKeyRejected=2','missingKeyRejected=1'),
                        text.replace('constructed=2','constructed=1'),text.replace('parsed=4','parsed=2'),
                        text.replace('getters=4','getters=3'),text.replace('version=1','version=2'),
                        text.replace('thread=17','thread=18'),text.replace('[102]','[111]')])
        for changed in changes:
            with self.subTest(changed=changed),self.assertRaises(AssertionError):validate(changed,rows)
        for changed_rows in [[],rows+rows,[dict(event='OnConfirm.dispatch',tick=99,thread=17)],
                             [dict(event='OnConfirm.dispatch',tick=110,thread=18)]]:
            with self.subTest(rows=changed_rows),self.assertRaises(AssertionError):validate(text,changed_rows)
