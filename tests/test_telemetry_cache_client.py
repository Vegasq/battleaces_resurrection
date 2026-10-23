"""Authored evidence controls for genuine initialized SDK Client guard mode."""
import unittest
from tools.telemetry_cache_evidence import validate
from tests.test_telemetry_cache_evidence import delivery_text,DELIVERY_BEGIN

BEGIN='[102] TELEMETRY CACHECLIENT begin: version=1 thread=17 constructorGuards=6 callbackHeads=4'
END='[102] TELEMETRY CACHECLIENT probe passed: version=1 thread=17 nativeCtorCalls=1 clientCtorCalls=1 genuineNativeInterface=1 configurationRetained=1 coreFieldsPresent=14 dependencyGraphMatched=1 idleDelivery=1 globalCallbackHeadsUnchanged=4 reportingDisabled=1 wholeRunIsolation=0'
ROWS=[dict(event='OnConfirm.dispatch',tick=110,thread=17)]

def text():
    return (delivery_text().replace('CACHETYPE probe passed: version=3','CACHETYPE probe passed: version=4')
        .replace(DELIVERY_BEGIN,BEGIN+'\n'+END+'\n'+DELIVERY_BEGIN)
        .replace('CACHEDELIVERY begin: version=1','CACHEDELIVERY begin: version=2')
        .replace('CACHEDELIVERY probe passed: version=1','CACHEDELIVERY probe passed: version=2')
        .replace('absentClient=1','absentClient=0').replace('activeClientConstructed=0','activeClientConstructed=1'))

class CacheClientEvidenceTests(unittest.TestCase):
    def test_initialized_client_is_explicit_and_does_not_qualify_inflight_or_whole_run(self):
        proof=validate(text(),ROWS,client_probe=True)
        self.assertEqual(proof['version'],4)
        self.assertTrue(proof['reporting_disabled_sdk_client_initialized'])
        self.assertTrue(proof['operational_sdk_client_initialized'])
        self.assertFalse(proof['sdk_client_absent'])
        self.assertEqual(proof['initialized_sdk_core_fields'],14)
        self.assertEqual(proof['existing_global_callback_heads_unchanged'],4)
        self.assertFalse(proof['resumed_or_in_flight_delivery_qualified'])
        self.assertFalse(proof['whole_run_cache_isolation'])

    def test_legacy_absent_client_never_satisfies_new_mode_and_new_mode_is_not_implicit(self):
        with self.assertRaises(AssertionError):validate(delivery_text(),ROWS,client_probe=True)
        with self.assertRaises(AssertionError):validate(text(),ROWS,delivery_probe=True)
        self.assertFalse(validate(delivery_text(),ROWS,delivery_probe=True)['operational_sdk_client_initialized'])

    def test_missing_duplicate_or_partial_construction_cannot_pass(self):
        for altered in (text().replace(BEGIN+'\n',''),text().replace(END+'\n',''),text()+'\n'+END,
                        text().replace('coreFieldsPresent=14','coreFieldsPresent=13'),
                        text().replace('globalCallbackHeadsUnchanged=4','globalCallbackHeadsUnchanged=3'),
                        text().replace('reportingDisabled=1','reportingDisabled=0'),
                        text().replace('genuineNativeInterface=1','genuineNativeInterface=0'),
                        text().replace('absentClient=0','absentClient=1')):
            with self.subTest(altered=altered[-80:]),self.assertRaises(AssertionError):validate(altered,ROWS,client_probe=True)

    def test_constructor_order_thread_and_ticks_are_required(self):
        for altered in (text().replace(BEGIN,BEGIN.replace('thread=17','thread=18')),
                        text().replace(END,END.replace('[102]','[111]')),
                        text().replace(BEGIN+'\n'+END,END+'\n'+BEGIN),
                        text().replace(BEGIN+'\n'+END+'\n','')+'\n'+BEGIN+'\n'+END):
            with self.assertRaises(AssertionError):validate(altered,ROWS,client_probe=True)

if __name__=='__main__':unittest.main()
