import unittest
import struct
from client_patch.patcher.patch_client import build_patch, install, redirect_relocated_pointer


class PatcherSafetyTests(unittest.TestCase):
    def test_unsupported_original_rejected_before_pe_processing(self):
        for original in (b'', b'MZ' + bytes(256)):
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                build_patch(original)

    def test_named_recovery_copy_cannot_be_patched(self):
        with self.assertRaisesRegex(ValueError, 'read-only'):
            install('BattleAcesBeta_untouched')

    def test_quit_diagnostics_cannot_target_a_nonlocal_installation(self):
        with self.assertRaisesRegex(ValueError, 'owned ignored local test'):
            install('nonlocal-authored-placeholder', quit_diagnostics=True)

    def test_pointer_redirect_preserves_existing_aslr_relocation(self):
        original = bytearray(128)
        base = 0x180000000
        struct.pack_into('<Q',original,8,base+0x120)
        struct.pack_into('<IIH',original,64,0x2000,12,0xa018)
        hook = dict(name='authored-pointer',offset=8,rva=0x2018,target_rva=0x120,
                    before=original[8:16].hex(),relocation_block_offset=64,
                    relocation_block_before=original[64:72].hex(),relocation_entry_offset=72,
                    relocation_entry_before=original[72:74].hex())
        patched = bytearray(original)
        redirect_relocated_pointer(original,patched,hook,base,0x8000)
        self.assertEqual(patched[16:],original[16:])
        # The same loader DIR64 delta must land on the thunk in the relocated image.
        delta = 0x7ff000000000-base
        self.assertEqual(struct.unpack_from('<Q',patched,8)[0]+delta,0x7ff000008000)
        for change in ('slot','relocation-modified','wrong-relocation-type','wrong-relocation-page'):
            with self.subTest(change=change):
                data, candidate, contract = bytearray(original),bytearray(original),dict(hook)
                if change=='slot': data[8]^=1
                if change=='relocation-modified': candidate[72]^=1
                if change=='wrong-relocation-type':
                    data[73]=candidate[73]=0x30
                    contract['relocation_entry_before']=data[72:74].hex()
                if change=='wrong-relocation-page':
                    data[65]=candidate[65]=0x30
                    contract['relocation_block_before']=data[64:72].hex()
                before = bytes(candidate)
                with self.assertRaisesRegex(ValueError,'mismatch'):
                    redirect_relocated_pointer(data,candidate,contract,base,0x8000)
                self.assertEqual(candidate,before)
