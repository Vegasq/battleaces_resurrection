"""Reject incomplete/overclaimed evidence and guard the two ownership contracts."""
import re,struct,unittest
from client_patch.patcher.telemetry import COMPONENTS
from tools.telemetry_activation_evidence import FIELDS,validate

def fixture():
    return ('[100] TELEMETRY ACTIVATION begin: version=1 thread=17 retainedMain=1 retainedSession=1 originalInitializerInvoked=0\n'
            '[101] TELEMETRY ACTIVATION probe passed: version=1 thread=17 '+FIELDS,
            [dict(event='OnConfirm.dispatch',tick=110,thread=17)])

class ActivationEvidence(unittest.TestCase):
    def test_complete_proof_keeps_unexercised_state_and_value_limits(self):
        text,rows=fixture();proof=validate(text,rows)
        self.assertTrue(proof['passed']);self.assertTrue(proof['retained_native_string_address'])
        for key in ('identity_payload_read','original_acquisition_invoked','original_initializer_invoked',
                    'nonempty_retained_value_runtime_qualified','other_transition_runtime_qualified','analytics_removal_qualified'):
            self.assertFalse(proof[key])

    def test_missing_duplicated_wrong_thread_late_or_altered_claims_reject(self):
        text,rows=fixture();lines=text.splitlines();changes=[]
        for line in lines:
            changes.extend([text.replace(line,''),text+'\n'+line,text.replace(line,line.replace('thread=17','thread=18')),
                            text.replace(line,re.sub(r'^\[\d+\]','[111]',line))])
            for match in re.finditer(r'\b(\w+)=(\d+)',line):
                changed=line[:match.start(2)]+('0' if match[2]!='0' else '1')+line[match.end(2):]
                changes.append(text.replace(line,changed))
        for changed in changes:
            with self.subTest(changed=changed),self.assertRaises(AssertionError):validate(changed,rows)

    def test_transition_decline_retains_existing_busy_clear_tail_and_getter_fast_path(self):
        patches={p.rva:p for p in COMPONENTS['UnityPlayer.dll'].patches}
        decline=patches[0xc3bafc];getter=patches[0xc478f5]
        self.assertEqual(0xc3bafc+5+struct.unpack_from('<i',decline.replacement,1)[0],0xc3bb0b)
        self.assertEqual(decline.replacement[5:],b'\x90'*10)
        self.assertEqual(getter.guard[:2],b'\x74\x10');self.assertEqual(getter.replacement,b'\x90\x90')
        self.assertEqual(getter.guard[2:6],bytes.fromhex('488d4148'))
        self.assertEqual(patches[0xc34270].replacement,bytes.fromhex('31c0c3'))
        for untouched in (0xc3b990,0xc3bb0b,0xc3d120,0xc3d1b0,0xc478c0,0xc43ae0,0x2047b0):
            self.assertNotIn(untouched,patches)
