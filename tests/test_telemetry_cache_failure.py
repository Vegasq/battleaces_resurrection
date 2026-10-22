"""False-pass regressions for the real pending-owner/disabled-ID evidence parser."""
import re
import unittest
from tools.telemetry_cache_failure_evidence import FIELDS,validate
from tests.test_telemetry_cache_evidence import delivery_text
from client_patch.patcher.telemetry import COMPONENTS
import struct


def fixture():
    lines=['[102] TELEMETRY CACHEFAILURE begin: version=1 thread=17 genuinePendingOwners=1 activeClientConstructed=0']
    lines += ['[102] TELEMETRY CACHEFAILURE device boundary: version=1 thread=17 phase='+p
              for p in ('read-begin','read-end','id-begin','id-end')]
    lines += ['[102] TELEMETRY CACHEFAILURE probe passed: version=1 thread=17 '+FIELDS]
    text=delivery_text().replace('[103] TELEMETRY CACHEREADER','\n'.join(lines)+'\n[103] TELEMETRY CACHEREADER')
    return text,[dict(event='OnConfirm.dispatch',tick=110,thread=17)]


class CacheFailureEvidence(unittest.TestCase):
    def test_complete_proof_keeps_operational_and_whole_lifetime_limits(self):
        text,rows=fixture();proof=validate(text,rows)
        self.assertTrue(proof['passed']);self.assertEqual(proof['matches_removed'],8)
        self.assertFalse(proof['operational_client_qualified']);self.assertFalse(proof['analytics_removal_qualified'])

    def test_missing_mutated_overclaimed_or_out_of_lifetime_proof_rejects(self):
        text,rows=fixture();lines=[s for s in text.splitlines() if 'TELEMETRY CACHEFAILURE' in s]
        changes=[]
        for line in lines:
            changes.extend([text.replace(line,''),text+'\n'+line,text.replace(line,line.replace('thread=17','thread=18')),
                            text.replace(line,line.replace('[102]','[111]'))])
        end=lines[-1]
        for m in re.finditer(r'\b(\w+)=(\d+)',end):
            if m[1] not in ('version','thread'):
                changes.append(text.replace(end,end[:m.start(2)]+('0' if m[2]!='0' else '1')+end[m.end(2):]))
        for changed in changes:
            with self.subTest(changed=changed),self.assertRaises(AssertionError):validate(changed,rows)

    def test_five_interior_branches_retain_original_cleanup_targets(self):
        patches={p.rva:p for p in COMPONENTS['GameAssembly.dll'].patches}
        targets={0x824bf1:0x824ce5,0x824d3a:0x824ce5,0x824e50:0x824f3c,0x824fa0:0x82508c,0x83692d:0x836aa8}
        for rva,target in targets.items():
            code=patches[rva].replacement
            self.assertEqual(code[0],0xe9);self.assertEqual(rva+5+struct.unpack_from('<i',code,1)[0],target)
        for original in (0x824b60,0x824e20,0x824f70,0x825190,0x733680,0x818f80,0x1b4fe50):
            self.assertNotIn(original,patches)
