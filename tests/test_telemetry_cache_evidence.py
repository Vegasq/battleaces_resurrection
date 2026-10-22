"""False-pass regressions for scoped original cache constructor diagnostics."""
import re
import unittest
from tools.telemetry_cache_evidence import validate


PATH = '[100] TELEMETRY CACHEPATH probe passed: version=1 thread=17 getters=4 originalBodies=1 scopedOwnedRoot=1 icallRestored=1 reportEnumeration=0 reportPayloadRead=0 wholeRunIsolation=0'
TYPED = '[102] TELEMETRY CACHETYPE probe passed: version=1 thread=17 parsed=4 constructed=2 errors=1 sessions=1 authoredFieldsRetained=1 missingKeyRejected=2 cacheManagerConstructed=0 reportDelivered=0 diskQueueRead=0'
DISK_TYPED=TYPED.replace('version=1','version=2').replace('cacheManagerConstructed=0','cacheManagerConstructed=1').replace('diskQueueRead=0','diskQueueRead=1')+' fromDisk=2'
READER='[101] TELEMETRY CACHEREADER probe passed: version=1 thread=17 instanceCtor=1 emptyBeforeCtor=1 emptyAfterCtor=1 seeds=2 enumerated=2 reads=2 rawBytesMatched=2 missingIdNull=2 fileIdentityBytesUnchanged=2 staticConfigRestored=1 deviceFilenameUnchanged=1 icallRestored=1 wholeRunIsolation=0'
BOUNDARIES=['[101] TELEMETRY CACHEREAD '+phase+': version=1 thread=17 kind='+kind
            for phase,kind in [('begin','event'),('end','event'),('begin','session'),('end','session')]]
DELIVERY_BEGIN='[102] TELEMETRY CACHEDELIVERY begin: version=1 thread=17 fresh=1 absentClient=1'
DELIVERY='[102] TELEMETRY CACHEDELIVERY probe passed: version=1 thread=17 realPayloadManager=1 realDelivery=1 absentClient=1 activeClientConstructed=0 deliverCalls=2 cachedStartCalls=1 iteratorFactories=5 moveNextFalse=5 originalDisposes=5 freshStateRetained=5 currentNull=5 capturesRetained=5 pendingCount=0 finishedCount=0 listFieldsUnchanged=2 reportFieldsUnchanged=2 deliveryFieldsUnchanged=1 payloadManagerFieldsUnchanged=1 reportDelivered=0 wholeRunIsolation=0'


def delivery_text():
    return '\n'.join([PATH,*BOUNDARIES,DISK_TYPED.replace('version=2','version=3'),DELIVERY_BEGIN,DELIVERY,READER.replace('[101]','[103]')])


class CacheContractEvidenceTests(unittest.TestCase):
    def test_fresh_delivery_cannot_be_promoted_to_operational_sdk_or_inflight_proof(self):
        text=delivery_text();rows=[dict(event='OnConfirm.dispatch',tick=110,thread=17)]
        proof=validate(text,rows,delivery_probe=True)
        self.assertEqual(proof['guarded_move_next_false'],5)
        self.assertEqual(proof['original_fresh_disposes'],5)
        self.assertTrue(proof['sdk_client_absent'])
        self.assertFalse(proof['operational_sdk_client_initialized'])
        self.assertFalse(proof['resumed_or_in_flight_delivery_qualified'])
        self.assertFalse(proof['whole_run_cache_isolation'])
        self.assertFalse(proof['report_delivered'])
        for kwargs,changed in [({},text),({'disk_probe':True},text),
                               ({'delivery_probe':True},'\n'.join([PATH,*BOUNDARIES,READER,DISK_TYPED]))]:
            with self.subTest(kwargs=kwargs),self.assertRaises(AssertionError):validate(changed,rows,**kwargs)

    def test_delivery_requires_all_fresh_owner_guard_capture_and_cleanup_records(self):
        text=delivery_text();rows=[dict(event='OnConfirm.dispatch',tick=110,thread=17)]
        changes=[]
        for line in (DELIVERY_BEGIN,DELIVERY):
            changes.extend([text.replace(line,''),text+'\n'+line,
                            text.replace(line,line.replace('thread=17','thread=18')),
                            text.replace(line,line.replace('[102]','[999]'))])
            for match in re.finditer(r'\b(\w+)=(\d+)',line):
                field=match[1]
                if field in ('version','thread'):continue
                bad='1' if match[2]=='0' else '0'
                changes.append(text.replace(line,re.sub(r'\b'+field+r'=\d+',field+'='+bad,line)))
        changes.extend([text.replace('version=3','version=2'),text+'\nTELEMETRY CACHE probe failed: failed guards',
                        text.replace(DELIVERY,DELIVERY+' extra=1'),
                        text.replace(DELIVERY_BEGIN,'SWAP').replace(DELIVERY,DELIVERY_BEGIN).replace('SWAP',DELIVERY),
                        text.replace(READER.replace('[101]','[103]'),'')+'\n'+READER])
        for changed in changes:
            with self.subTest(changed=changed),self.assertRaises(AssertionError):validate(changed,rows,delivery_probe=True)

    def test_explicit_disk_mode_cannot_accept_legacy_or_promote_whole_run_scope(self):
        text='\n'.join([PATH,*BOUNDARIES,READER,DISK_TYPED]);rows=[dict(event='OnConfirm.dispatch',tick=110,thread=17)]
        proof=validate(text,rows,disk_probe=True)
        self.assertTrue(proof['disk_queue_read'])
        self.assertTrue(proof['static_configuration_restored'])
        self.assertFalse(proof['whole_run_cache_isolation'])
        self.assertFalse(proof['report_delivered'])
        for disk,changed in [(False,text),(True,PATH+'\n'+TYPED),(True,text+'\n'+TYPED),
                             (False,PATH+'\n'+TYPED+'\n'+READER)]:
            with self.subTest(disk=disk,changed=changed),self.assertRaises(AssertionError):validate(changed,rows,disk_probe=disk)

    def test_disk_reader_state_fields_and_boundaries_are_required(self):
        text='\n'.join([PATH,*BOUNDARIES,READER,DISK_TYPED]);rows=[dict(event='OnConfirm.dispatch',tick=110,thread=17)]
        changes=[text.replace(READER,''),text+'\n'+READER,text.replace('fromDisk=2','fromDisk=0'),
                 text.replace(READER,READER.replace('thread=17','thread=18')),
                 text.replace(READER,READER.replace('[101]','[999]'))]
        for field,value in [('instanceCtor',0),('emptyBeforeCtor',0),('emptyAfterCtor',0),('seeds',1),
                            ('enumerated',1),('reads',1),('rawBytesMatched',1),('missingIdNull',0),
                            ('fileIdentityBytesUnchanged',0),('staticConfigRestored',0),('deviceFilenameUnchanged',0),
                            ('icallRestored',0),('wholeRunIsolation',1)]:
            changes.append(text.replace(READER,re.sub(r'\b'+field+r'=\d+',field+'='+str(value),READER)))
        for boundary in BOUNDARIES:
            changes.extend([text.replace(boundary,''),text+'\n'+boundary,
                            text.replace(boundary,boundary.replace('thread=17','thread=18')),
                            text.replace(boundary,boundary.replace('[101]','[99]'))])
        changes.append(text.replace(BOUNDARIES[0],'swap').replace(BOUNDARIES[1],BOUNDARIES[0]).replace('swap',BOUNDARIES[1]))
        for changed in changes:
            with self.subTest(changed=changed),self.assertRaises(AssertionError):validate(changed,rows,disk_probe=True)

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
